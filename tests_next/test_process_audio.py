import json
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.desktop.process_audio import ProcessAudioCapture


class ProcessAudioTests(unittest.TestCase):
    def test_timestamp_error_and_discontinuity_flags_do_not_claim_valid_clock(self):
        with tempfile.TemporaryDirectory() as root:
            helper=Path(root)/'helper.exe';helper.write_bytes(b'fixture')
            capture=ProcessAudioCapture(helper,process_id=5,creation_time='7',approved=True)
            packets=[{'status':'started','process_id':5,'creation':'7','sample_rate':16000,
                'channels':1,'sample_width':2,'process_isolation':True},
                {'status':'pcm','process_id':5,'pcm':'AQI=','device_position':0,'qpc_position':0,'capture_flags':5},
                {'status':'pcm','process_id':5,'pcm':'AQI='}]
            class Proc:
                stdout=io.StringIO('\n'.join(json.dumps(p) for p in packets)+'\n')
                def poll(self): return 0
            values,timing=[],[]
            capture._read(Proc(),values.append,timing.append)
            self.assertEqual(len(values),2)
            self.assertFalse(timing[0]['timestamp_valid'])
            self.assertTrue(timing[0]['data_discontinuity'])
            self.assertIsNone(timing[1])
    def test_native_qpc_and_device_positions_are_forwarded_as_capture_clock(self):
        with tempfile.TemporaryDirectory() as root:
            helper = Path(root) / 'helper.exe'; helper.write_bytes(b'fixture')
            capture=ProcessAudioCapture(helper,process_id=5,creation_time='7',approved=True)
            handshake={'status':'started','process_id':5,'creation':'7','sample_rate':16000,
                'channels':1,'sample_width':2,'process_isolation':True}
            packet={'status':'pcm','process_id':5,'pcm':'AQI=','device_position':32000,'qpc_position':998877}
            class Proc:
                stdout=io.StringIO('\n'.join(json.dumps(p) for p in (handshake,packet))+'\n')
                def poll(self): return 0
            pcm,timing=[],[]
            capture._read(Proc(),pcm.append,on_timing=timing.append)
            self.assertEqual(pcm,[b'\x01\x02'])
            self.assertEqual(timing,[{'device_position':32000,'qpc_position':998877,'sample_rate':16000,
                'timestamp_valid':True,'data_discontinuity':False,
                'clock_scope':'native-packet-start','qpc_unit':'100ns'}])

    def test_requires_consent_and_native_helper(self):
        with tempfile.TemporaryDirectory() as root:
            helper = Path(root) / 'helper.exe'
            helper.write_bytes(b'fixture')
            with self.assertRaises(PermissionError):
                ProcessAudioCapture(helper, process_id=5, creation_time='7')
            capture = ProcessAudioCapture(helper, process_id=5, creation_time='7', approved=True)
            self.assertEqual(capture.process_id, 5)

    def test_decodes_bounded_pcm_and_rejects_bad_packet(self):
        with tempfile.TemporaryDirectory() as root:
            helper = Path(root) / 'helper.exe'; helper.write_bytes(b'fixture')
            capture = ProcessAudioCapture(helper, process_id=5, creation_time='7', approved=True)
            handshake = {'status':'started', 'process_id':5, 'creation':'7',
                         'sample_rate':16000, 'channels':1, 'sample_width':2,
                         'process_isolation':True}
            class Proc:
                stdout = io.StringIO('\n'.join(json.dumps(p) for p in [handshake,
                    {'status':'pcm','process_id':5,'pcm':'AQI='},
                    {'status':'pcm','process_id':5,'pcm':'!!!'}]) + '\n')
                stdin = None
                def poll(self): return 0
            values = []
            capture._read(Proc(), values.append)
            self.assertEqual(values[0], b'\x01\x02')
            self.assertEqual(len(values), 1)
            self.assertEqual(capture.error, 'Error')

    def test_real_pipe_handshake_stop_and_repeated_cleanup(self):
        script = (
            "import sys,json; assert sys.stdin.readline() == 'START\\n'; "
            "print(json.dumps(dict(status='started',process_id=5,creation='7',"
            "sample_rate=16000,channels=1,sample_width=2,process_isolation=True)),flush=True); "
            "sys.stdin.readline()"
        )
        self._run_helper_fixture(script, success=True)

    def test_real_pipe_native_startup_error_is_reported_and_reclaimed(self):
        script = (
            "import sys,json; sys.stdin.readline(); "
            "print(json.dumps(dict(status='error',reason='COMException',hresult=-123)),"
            "file=sys.stderr,flush=True); sys.exit(1)"
        )
        capture = self._run_helper_fixture(script, success=False)
        self.assertEqual(capture.status()['state'], 'error')
        self.assertEqual(capture.error, {'reason': 'COMException', 'hresult': -123})

    def test_real_pipe_rejects_wrong_target_handshake(self):
        script = (
            "import sys,json; sys.stdin.readline(); "
            "print(json.dumps(dict(status='started',process_id=6,creation='7',"
            "sample_rate=16000,channels=1,sample_width=2,process_isolation=True)),flush=True); "
            "sys.stdin.readline()"
        )
        capture = self._run_helper_fixture(script, success=False)
        self.assertEqual(capture.error, 'ValueError')

    def _run_helper_fixture(self, script, *, success):
        launch = subprocess.Popen
        children, jobs = [], []
        class Job:
            def __init__(self): self.closed = False; jobs.append(self)
            def assign(self, child): self.child = child
            def close(self): self.closed = True
        def popen(command, **options):
            child = launch([sys.executable, '-u', '-c', script], **options)
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as root:
            helper = Path(root) / 'helper.exe'; helper.write_bytes(b'fixture')
            capture = ProcessAudioCapture(helper, process_id=5, creation_time='7', approved=True)
            with patch('extensions.desktop.process_audio.subprocess.Popen', side_effect=popen), \
                    patch('extensions.desktop.process_audio.ChildJob', Job):
                try:
                    if success:
                        self.assertEqual(capture.start(lambda pcm: None)['state'], 'recording')
                        with self.assertRaisesRegex(RuntimeError, 'already active'):
                            capture.start(lambda pcm: None)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                            capture.start(lambda pcm: None)
                finally:
                    capture.stop()
                    capture.stop()
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertTrue(all(job.closed for job in jobs))
            self.assertIsNone(capture._process)
            self.assertIsNone(capture._reader)
            return capture
