"""Fake Win32 and synthetic events only: no real device registration."""
import ctypes
import threading
import time
import unittest
from unittest.mock import patch

from extensions.behavior.input_features import validate_frame
from extensions.behavior.windows_input_worker import (
    PasswordProbe, InputSession, RAWINPUT, RAWINPUTHEADER, RAWKEYBOARD, RAWMOUSE,
    RAWINPUTDEVICE, RIDEV_INPUTSINK, register_raw_input, _signatures, worker_loop)


def config():
    return {'recording': True, 'permission_revision': 1, 'user_scope': 'user-1', 'worker_epoch': 8}


class Function:
    def __init__(self, result=1):
        self.result, self.calls = result, []
    def __call__(self, *args):
        if args and isinstance(args[0], ctypes.Array):
            self.calls.append([(d.usUsagePage, d.usUsage, d.dwFlags, d.hwndTarget) for d in args[0]])
        else: self.calls.append(args)
        return self.result


class Library:
    def __getattr__(self, name):
        function = Function()
        setattr(self, name, function)
        return function


class LayoutTests(unittest.TestCase):
    def test_raw_data_is_a_union_at_header_offset(self):
        self.assertEqual(ctypes.sizeof(RAWKEYBOARD), 16)
        self.assertEqual(ctypes.sizeof(RAWMOUSE), 24)
        self.assertEqual(RAWINPUT.data.offset, ctypes.sizeof(RAWINPUTHEADER))
        self.assertEqual(RAWMOUSE.button_union.offset, 4)
        raw = RAWINPUT()
        raw.header.dwType = 1
        raw.keyboard.VKey = 0x41
        copied = RAWINPUT.from_buffer_copy(bytes(raw))
        self.assertEqual(copied.keyboard.VKey, 0x41)
        copied.mouse.usButtonFlags = 0x400
        copied.mouse.usButtonData = 0xff88
        self.assertEqual(ctypes.c_int16(copied.mouse.usButtonData).value, -120)

    def test_registration_has_sink_target_and_removal_has_null_target(self):
        fake = Library()
        with self.assertRaises(ValueError): register_raw_input(None, fake)
        register_raw_input(0x123456789, fake)
        register_raw_input(0x123456789, fake, remove=True)
        first, last = fake.RegisterRawInputDevices.calls
        self.assertEqual(first, [(1, 6, 0x100, 0x123456789), (1, 2, 0x100, 0x123456789)])
        self.assertEqual(last, [(1, 6, 1, None), (1, 2, 1, None)])
        self.assertEqual(RIDEV_INPUTSINK, 0x100)
        self.assertEqual(fake.RegisterRawInputDevices.argtypes[0]._type_, RAWINPUTDEVICE)

    def test_win32_pointer_signatures_and_msg_storage(self):
        from ctypes import wintypes
        user, kernel = Library(), Library()
        hook = ctypes.CFUNCTYPE(None)
        _signatures(user, kernel, hook, hook)
        self.assertEqual(user.PeekMessageW.argtypes[0]._type_, wintypes.MSG)
        self.assertEqual(user.CreateWindowExW.restype, wintypes.HWND)
        self.assertEqual(user.SetWinEventHook.restype, wintypes.HANDLE)
        self.assertEqual(ctypes.sizeof(user.DefWindowProcW.restype), ctypes.sizeof(ctypes.c_void_p))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.at = 100.0
        self.frames = []
        self.session = InputSession(config(), self.frames.append, clock=lambda:self.at)
        self.session.foreground((1, 2, '3'))

    def test_unknown_and_password_gate_before_fine_aggregation(self):
        session = self.session
        session.key(0x43, self.at)
        raw = RAWMOUSE(); raw.usButtonFlags = 0x401; raw.usButtonData = 120; raw.lLastX = 1
        session.mouse(raw, self.at, (.1, .2))
        session.seal()
        unknown = self.frames[-1]
        validate_frame(unknown)
        self.assertEqual(unknown['keys']['counts'], {'other':1})
        self.assertEqual(unknown['mouse']['left'], 0)
        self.assertIsNone(unknown['mouse']['grid'])
        self.assertEqual(unknown['scroll']['vertical']['delta'], 120)
        session.focus('password_paused')
        session.key(0x41, self.at); session.mouse(raw, self.at, (.1, .2)); session.seal()
        self.assertEqual(len(self.frames), 1)

    def test_front_switch_seals_and_clears_modifiers_drag_and_anonymous_identity(self):
        session = self.session
        session.focus('ok')
        session.key(0x11, self.at)
        raw = RAWMOUSE(); raw.usButtonFlags = 1
        session.mouse(raw, self.at, (.1, .2))
        old_id = session.identity['window_instance']
        self.at += .3
        session.foreground((0x10001, 8, '9'))
        self.assertEqual(len(self.frames), 1)
        self.assertEqual(self.frames[0]['window_instance'], old_id)
        self.assertEqual(session.identity['window_instance'], old_id+1)
        session.focus('ok'); session.key(0x43, self.at)
        raw.usButtonFlags = 2
        session.mouse(raw, self.at, (.8, .9)); session.seal()
        self.assertEqual(self.frames[1]['shortcuts'], {})
        self.assertEqual(self.frames[1]['drag']['candidates'], 0)
        self.assertEqual(self.frames[1]['sequence'], 1)

    def test_mouse_axes_signed_scroll_movement_and_relative_drag(self):
        session = self.session; session.focus('ok')
        raw = RAWMOUSE(); raw.lLastX = 5; raw.usButtonFlags = 1|0x400; raw.usButtonData = 120
        session.mouse(raw, self.at, (.1,.1))
        raw.usButtonFlags = 0x400|0x800; raw.usButtonData = 0xff88
        self.at += .3; session.mouse(raw, self.at, (.4,.4))
        raw.usButtonFlags = 2; self.at += .2; session.mouse(raw,self.at,(.8,.8))
        session.seal(); frame = self.frames[0]; validate_frame(frame)
        self.assertEqual(frame['mouse']['moves'], 3)
        self.assertEqual(frame['scroll']['vertical'], {'count':2,'delta':0,'reversed':1})
        self.assertEqual(frame['scroll']['horizontal']['delta'], -120)
        self.assertEqual(frame['drag']['candidates'],1)
        self.assertEqual(len(frame['drag']['cells']),2)

    def test_key_repeat_uses_held_key_and_shortcut_has_no_typing_semantic(self):
        session = self.session; session.focus('ok')
        session.key(0x41,self.at); session.key(0x42,self.at+.01)
        session.key(0x42,self.at+.02)
        session.key(0x11,self.at+.03); session.key(0x43,self.at+.04)
        session.seal(); frame = self.frames[0]
        self.assertEqual(frame['keys']['repeat'],1)
        self.assertEqual(frame['shortcuts'],{'copy':1})
        self.assertEqual(frame['semantic_ops'][-1],{'kind':'copy','count':1})

    def test_burst_id_survives_second_seal_and_final_partial_is_emitted(self):
        session = self.session; session.focus('ok')
        session.key(0x41,self.at+.9)
        self.at += 1; session.tick()
        session.key(0x42,self.at+.1)
        self.at += .2; session.seal()
        self.assertEqual(self.frames[0]['bursts'][0]['id'],self.frames[1]['bursts'][0]['id'])
        self.assertEqual([f['sequence'] for f in self.frames],[0,1])

    def test_fake_worker_stop_seals_without_requiring_second(self):
        stop = threading.Event()
        events = iter([('focus','ok',100.0),('key',0x41,100.1)])
        def probe():
            try: return next(events)
            except StopIteration: stop.set()
        frames = []
        with patch('extensions.behavior.windows_input_worker.time.sleep'):
            worker_loop(config(),frames.append,stop_event=stop,probe=probe,clock=lambda:100.2)
        self.assertEqual(len(frames),1)
        self.assertEqual(frames[0]['keys']['counts'],{'text_entry':1})
        validate_frame(frames[0])

    def test_high_rate_is_constant_space_and_opaque(self):
        session=self.session; session.focus('ok')
        raw=RAWMOUSE(); raw.lLastX=1
        for index in range(20000):
            session.mouse(raw,self.at,None)
            session.key(0x41,self.at+index/100000)
        session.seal(); frame=self.frames[0]; validate_frame(frame)
        self.assertEqual(frame['mouse']['moves'],20000)
        self.assertFalse(hasattr(session,'events'))
        self.assertEqual(len(session.held),1)
        self.assertEqual(len(session.aggregator._grid),256)
        self.assertLessEqual(len(frame['semantic_ops']),32)

    def test_probe_quality_flapping_cannot_starve_periodic_frames(self):
        session = self.session
        # A 200ms-valid result refreshed every 250ms has legitimate unknown
        # intervals. Privacy transitions discard partial features, but must
        # not postpone the worker's one-second flush indefinitely.
        for index in range(1, 202):
            self.at = 100 + index * .01
            quality = 'ok' if index % 25 < 20 else 'privacy_context_unknown'
            session.focus(quality)
            session.key(0x41, self.at)
            session.tick()
        self.assertGreaterEqual(len(self.frames), 2)
        for frame in self.frames:
            validate_frame(frame)
        self.assertEqual([f['sequence'] for f in self.frames], list(range(len(self.frames))))

    def test_password_transition_still_discards_pending_features(self):
        session = self.session
        session.focus('ok')
        session.key(0x41, self.at)
        self.at += .9
        session.focus('password_paused')
        session.key(0x42, self.at)
        self.at += .2
        session.tick()
        self.assertEqual(self.frames, [])
        session.focus('privacy_context_unknown')
        session.key(0x43, self.at)
        self.at += 1
        session.tick()
        self.assertEqual(len(self.frames), 1)
        self.assertEqual(self.frames[0]['focus_quality'], 'privacy_context_unknown')
        self.assertEqual(self.frames[0]['keys']['counts'], {'other': 1})


class ProbeTests(unittest.TestCase):
    def completed_query(self, value=False):
        probe = PasswordProbe(lambda: value)
        self.addCleanup(probe.close)
        probe.poll('window', 100)
        deadline = time.monotonic() + .5
        while probe._results.empty() and time.monotonic() < deadline:
            time.sleep(.001)
        self.assertFalse(probe._results.empty(), 'probe result did not arrive')
        return probe

    def test_success_result_expires_even_before_next_request(self):
        probe = self.completed_query()
        self.assertEqual(probe.poll('window', 100.1), 'ok')
        self.assertEqual(probe.poll('window', 100.21), 'privacy_context_unknown')
        self.assertEqual(probe._serial, 1)

    def test_invalidated_inflight_result_cannot_restore_safe_quality(self):
        probe = self.completed_query()
        probe.invalidate()
        self.assertEqual(probe.poll('window', 100.1), 'privacy_context_unknown')

    def test_switch_away_and_back_cannot_reuse_old_focus_result(self):
        probe = self.completed_query()
        self.assertEqual(probe.poll('other-window', 100.05), 'privacy_context_unknown')
        self.assertEqual(probe.poll('window', 100.1), 'privacy_context_unknown')

    def test_hung_probe_has_one_thread_one_request_and_expires_unknown(self):
        entered, release = threading.Event(), threading.Event()
        calls=[]
        def query():
            calls.append(1); entered.set(); release.wait(2); return False
        probe=PasswordProbe(query)
        self.addCleanup(release.set); self.addCleanup(probe.close)
        self.assertEqual(probe.poll('window1',100),'privacy_context_unknown')
        self.assertTrue(entered.wait(.5))
        for index in range(100):
            self.assertEqual(probe.poll('window1',100.3+index),'privacy_context_unknown')
        self.assertEqual(len(calls),1)
        self.assertLessEqual(probe._requests.qsize(),1)
        release.set(); probe._thread.join(.02)
        # A late result is not accepted as safe.
        self.assertEqual(probe.poll('window2',202),'privacy_context_unknown')

    def test_success_password_and_rate_limit(self):
        done=threading.Event()
        def query(): done.set(); return True
        probe=PasswordProbe(query); self.addCleanup(probe.close)
        probe.poll('window',100)
        self.assertTrue(done.wait(.5))
        deadline=time.monotonic()+.5
        while probe._results.empty() and time.monotonic()<deadline: time.sleep(.001)
        self.assertEqual(probe.poll('window',100.1),'password_paused')
        self.assertEqual(probe._serial,1)
        probe.poll('window',100.24); self.assertEqual(probe._serial,1)
        probe.poll('window',100.25); self.assertEqual(probe._serial,2)


if __name__ == '__main__': unittest.main()
