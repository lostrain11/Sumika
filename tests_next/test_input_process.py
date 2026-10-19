"""Parent protocol and bounded supervision; real input smoke is opt-in."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

from extensions.behavior.input_features import FrameAggregator
from extensions.behavior.input_process import InputFeatureProcess, QUEUE_FRAMES
from extensions.behavior.library import BehaviorLibrary


def frame(sequence, worker_epoch=1, *, pad=None):
    aggregator = FrameAggregator(identity={'user_scope':'project-1','worker_epoch':worker_epoch,
        'foreground_epoch':1,'focus_epoch':1,'window_instance':9}, observed_from='100.0',sequence=sequence)
    aggregator.key(0x41,100.1)
    result=aggregator.seal('101.0')
    if pad: result['padding_field']=pad
    return result


def permission():
    return {'recording':True,'paused':False,'revoked':False,'revision':1,'excluded_apps':['private-app']}


class RecordFramesTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='p11-frames-'); self.addCleanup(temporary.cleanup)
        self.library=BehaviorLibrary(Path(temporary.name)/'behavior.sqlite3')
        self.scope={'user':'project-1','session':'test-session'}

    def test_batch_persists_and_replays_idempotently(self):
        self.library.record_frames([frame(0),frame(1)],scope=self.scope)
        self.library.record_frames([frame(0),frame(1)],scope=self.scope)
        with self.library._connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM frames').fetchone()[0],2)

    def test_replayed_frame_with_changed_content_is_rejected(self):
        self.library.record_frames([frame(0)],scope=self.scope)
        changed=frame(0); changed['keys']['counts']['text_entry']=2
        with self.assertRaises(ValueError): self.library.record_frames([changed],scope=self.scope)

    def test_unknown_schema_and_budget_rejected(self):
        for invalid in ({'schema':'other'},frame(0,pad='x'*20000)):
            with self.assertRaises(ValueError): self.library.record_frames([invalid],scope=self.scope)


class MemoryLibrary:
    def __init__(self): self.calls=[]
    def record_frames(self,batch,*,scope): self.calls.append((batch,scope))


class ParentSupervisionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='p11-parent-'); self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name); self.library=MemoryLibrary()
        self.process=InputFeatureProcess(self.root,self.library,'project-1',session_id='host-session')
        self.process._worker_epoch=1; self.process._state='running'
        self.addCleanup(self.process.stop)

    def test_bounded_queue_overflow_fails_channel_without_replay(self):
        for sequence in range(QUEUE_FRAMES): self.assertTrue(self.process._enqueue(frame(sequence)))
        self.assertFalse(self.process._enqueue(frame(QUEUE_FRAMES)))
        status=self.process.status()
        self.assertEqual(status['status'],'failed'); self.assertEqual(status['error'],'input_queue_overflow')
        self.assertEqual(status['queued'],0); self.assertEqual(status['queued_bytes'],0)
        self.process._commit_batch(); self.assertEqual(self.library.calls,[])

    def test_independent_byte_cap_and_exact_dequeue_accounting(self):
        size=len(json.dumps(frame(0)).encode('utf8'))+100
        with patch('extensions.behavior.input_process.QUEUE_BYTES',size):
            self.assertTrue(self.process._enqueue(frame(0)))
            self.assertFalse(self.process._enqueue(frame(1)))
        self.assertEqual(self.process.status()['error'],'input_queue_overflow')

    def test_commit_uses_host_scope_and_callback_after_success(self):
        notifications=[]
        self.process.on_frames=lambda batch:notifications.append((batch,len(self.library.calls)))
        self.process._enqueue(frame(0)); self.process._commit_batch()
        self.assertEqual(self.library.calls[0][1],{'user':'project-1','session':'host-session'})
        self.assertEqual(notifications[0][1],1)
        self.assertIn('received_at',notifications[0][0][0])
        self.assertEqual(self.process.status()['queued_bytes'],0)
        self.process._commit_batch(); self.assertEqual(len(notifications),1)

    def test_commit_failure_isolates_channel_and_does_not_notify(self):
        def explode(batch,*,scope): raise RuntimeError('private directory name')
        self.library.record_frames=explode
        notifications=[]; self.process.on_frames=notifications.append
        self.process._enqueue(frame(0)); self.process._commit_batch()
        self.assertEqual(self.process.status()['error'],'input_commit_failed')
        self.assertEqual(notifications,[])

    def test_permission_predicate_false_discards_pending_frames_before_stop(self):
        notifications=[]
        self.process.on_frames=notifications.append
        self.process.can_commit=lambda:False
        self.process._enqueue(frame(0)); self.process._enqueue(frame(1))
        self.process.stop()
        self.assertEqual(self.library.calls,[])
        self.assertEqual(notifications,[])
        self.assertEqual(self.process.status()['frames'],0)
        self.assertEqual(self.process.status()['queued_bytes'],0)
        self.assertIsNone(self.process.status()['error'])
        self.assertIn(self.process.status()['status'],('stopped','permission_stopped'))

    def test_commit_guard_covers_transaction_and_is_released_before_callback(self):
        permission_lock=threading.Lock(); order=[]
        @contextmanager
        def guard():
            with permission_lock:
                order.append('guard_enter')
                yield True
                order.append('guard_exit')
        def record(batch,*,scope):
            self.assertTrue(permission_lock.locked()); order.append('record')
        def notify(batch):
            self.assertFalse(permission_lock.locked()); order.append('notify')
        self.library.record_frames=record
        self.process.commit_guard=guard; self.process.on_frames=notify
        self.process._enqueue(frame(0)); self.process._commit_batch()
        self.assertEqual(order,['guard_enter','record','guard_exit','notify'])
        self.assertEqual(self.process.status()['frames'],1)

    def test_commit_guard_denial_stops_and_discards_without_callback(self):
        @contextmanager
        def guard(): yield False
        notifications=[]
        self.process.commit_guard=guard; self.process.on_frames=notifications.append
        self.process._enqueue(frame(0)); self.process._commit_batch()
        self.assertEqual(self.library.calls,[]); self.assertEqual(notifications,[])
        self.assertEqual(self.process.status()['status'],'permission_stopped')
        self.assertFalse(self.process._enqueue(frame(1)))
        self.assertEqual(self.process.status()['frames'],0)

    def test_schema_scope_epoch_and_sequence_fail_closed(self):
        for change in ({'user_scope':'other-user'},{'worker_epoch':2},{'sequence':3},
                       {'padding_field':'SECRET'},{'focus_quality':'invented'}):
            with self.subTest(change=change):
                process=InputFeatureProcess(self.root,self.library,'project-1'); process._worker_epoch=1
                self.assertFalse(process._enqueue(dict(frame(0),**change)))
                self.assertEqual(process.status()['error'],'invalid_input_frame')
                self.assertEqual(process.status()['queued'],0)

    def test_explicit_raw_active_permission_required(self):
        for state in (None,{},dict(permission(),paused=True),dict(permission(),revoked=True),
                      dict(permission(),recording=False),dict(permission(),revision=True)):
            with self.assertRaises(PermissionError): self.process.start(permission=state)

    def test_protocol_rejects_before_ready_duplicate_ready_and_oversized_line(self):
        cases=[{'frame':frame(0)}, {'status':'ready','worker_epoch':2}, {'status':'unknown'},
               {'error':'SECRET'}, 'not-json', b'x'*17000+b'\n']
        for message in cases:
            with self.subTest(message=type(message).__name__):
                process=InputFeatureProcess(self.root,self.library,'project-1'); process._worker_epoch=1
                raw=message if isinstance(message,bytes) else ((message if isinstance(message,str) else json.dumps(message))+'\n').encode()
                fake=type('Fake',(),{'stdout':io.BytesIO(raw)})()
                process._read(fake,1)
                self.assertEqual(process.status()['status'],'failed')
                self.assertNotIn('SECRET',process.status()['error'])
        process=InputFeatureProcess(self.root,self.library,'project-1'); process._worker_epoch=1
        line=json.dumps({'status':'ready','worker_epoch':1})+'\n'
        process._read(type('Fake',(),{'stdout':io.BytesIO((line+line).encode())})(),1)
        self.assertEqual(process.status()['error'],'invalid_worker_protocol')

    def test_ready_followed_by_eof_remains_failed(self):
        line=json.dumps({'status':'ready','worker_epoch':1})+'\n'
        self.process._read(type('Fake',(),{'stdout':io.BytesIO(line.encode())})(),1)
        self.assertEqual(self.process.status()['error'],'worker_unexpected_eof')
        self.process.stop(); self.assertEqual(self.process.status()['status'],'failed')

    def test_old_epoch_failure_does_not_kill_new_channel(self):
        self.process._fail('old_failure',epoch=0)
        self.assertEqual(self.process.status()['status'],'running')

    def test_delayed_old_epoch_reaper_cannot_stop_restarted_worker(self):
        with patch.object(self.process,'_stop_worker') as stop:
            self.process._reap_failed(0)
        stop.assert_not_called()


class ScriptPipe:
    def __init__(self): self.condition=threading.Condition(); self.lines=[]; self.closed=False
    def put(self,message):
        with self.condition:
            self.lines.append((json.dumps(message)+'\n').encode()); self.condition.notify_all()
    def readline(self,limit):
        with self.condition:
            while not self.lines and not self.closed: self.condition.wait(.5)
            return self.lines.pop(0)[:limit] if self.lines else b''
    def close(self):
        with self.condition: self.closed=True; self.condition.notify_all()


class ScriptProcess:
    def __init__(self,*args,**kwargs):
        self.stdout=ScriptPipe(); self.stdin=self; self.returncode=None; self.config=None
        self.closed=False; self.killed=False
    def write(self,raw):
        message=json.loads(raw)
        if 'action' in message:
            self.stdout.put({'frame':frame(0,self.config['worker_epoch'])})
            self.returncode=0; self.stdout.close()
        else:
            self.config=message
            self.stdout.put({'status':'ready','worker_epoch':message['worker_epoch']})
    def flush(self): pass
    def close(self): self.closed=True
    def poll(self): return self.returncode
    def wait(self,timeout=None): return self.returncode
    def kill(self): self.killed=True; self.returncode=-1; self.stdout.close()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='p11-lifecycle-'); self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name); self.library=MemoryLibrary()

    def test_ready_final_seal_stop_and_pipe_threads_are_reclaimed(self):
        children=[]
        def create(*args,**kwargs):
            child=ScriptProcess(*args,**kwargs); children.append(child); return child
        process=InputFeatureProcess(self.root,self.library,'project-1',session_id='host-session')
        self.addCleanup(process.stop)
        with patch('extensions.behavior.input_process.capability_python',return_value=sys.executable), \
             patch('extensions.behavior.input_process.subprocess.Popen',side_effect=create):
            status=process.start(permission=permission())
            self.assertEqual(status['status'],'running')
            self.assertEqual(children[0].config['permission_revision'],1)
            self.assertIn(os.getpid(),children[0].config['excluded_pids'])
            reader,commit=process._reader,process._commit
            self.assertEqual(process.stop()['status'],'stopped')
        self.assertEqual(len(self.library.calls),1)
        self.assertFalse(reader.is_alive()); self.assertFalse(commit.is_alive())
        self.assertTrue(children[0].closed); self.assertTrue(children[0].stdout.closed)
        self.assertIsNone(process._process)

    def test_failure_kills_waits_closes_and_joins_worker_threads(self):
        child=ScriptProcess()
        process=InputFeatureProcess(self.root,self.library,'project-1')
        self.addCleanup(process.stop)
        with patch('extensions.behavior.input_process.capability_python',return_value=sys.executable), \
             patch('extensions.behavior.input_process.subprocess.Popen',return_value=child):
            process.start(permission=permission())
            reader,commit=process._reader,process._commit
            child.stdout.put({'frame':frame(4,child.config['worker_epoch'])})
            reader.join(2)
            if process._reaper: process._reaper.join(3)
        self.assertTrue(child.killed); self.assertTrue(child.closed); self.assertTrue(child.stdout.closed)
        self.assertFalse(reader.is_alive()); self.assertFalse(commit.is_alive())
        self.assertEqual(process.status()['status'],'failed')
        self.assertEqual(self.library.calls,[])

    def test_permission_disabled_before_stop_discards_worker_final_seal(self):
        child=ScriptProcess(); allowed=[True]; notifications=[]
        process=InputFeatureProcess(self.root,self.library,'project-1',
            can_commit=lambda:allowed[0],on_frames=notifications.append)
        self.addCleanup(process.stop)
        with patch('extensions.behavior.input_process.capability_python',return_value=sys.executable), \
             patch('extensions.behavior.input_process.subprocess.Popen',return_value=child):
            process.start(permission=permission())
            allowed[0]=False
            process.stop()
            if process._reaper: process._reaper.join(3)
        self.assertEqual(self.library.calls,[]); self.assertEqual(notifications,[])
        self.assertEqual(process.status()['frames'],0)
        self.assertIsNone(process._process)


@unittest.skipUnless(os.environ.get('SUMIKA_REAL_INPUT_TEST')=='1','real input requires explicit opt-in')
class WorkerSmokeTests(unittest.TestCase):
    def test_start_stop(self):
        from extensions.desktop.runtime import capability_python
        if capability_python('desktop') is None: self.skipTest('desktop runtime unavailable')
        with tempfile.TemporaryDirectory(prefix='p11-smoke-') as directory:
            root=Path(directory); library=BehaviorLibrary(root/'behavior.sqlite3')
            process=InputFeatureProcess(root,library,'project-1',runtime_root=Path(__file__).resolve().parents[1])
            try: self.assertEqual(process.start(permission=permission())['status'],'running')
            finally: self.assertEqual(process.stop()['status'],'stopped')


if __name__=='__main__': unittest.main()
