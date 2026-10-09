import base64
import io
import unittest
import importlib.util

from extensions.companion.windows_visual import collect_visual, WindowsVisualCollector


class WindowsVisualTests(unittest.TestCase):
    def test_native_session_reused_and_pause_releases_buffer(self):
        from extensions.companion.contracts import PerceptionService
        sessions = []
        class Session:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.stopped = False
                sessions.append(self)
            def start(self): pass
            def stop(self): self.stopped = True
            def snapshot(self):
                if self.stopped: raise RuntimeError('stopped')
                return {'valid':False, 'width':2, 'height':2, 'provider':'windows-graphics-capture'}
        collector = WindowsVisualCollector(approved=True, session_factory=Session)
        perception = PerceptionService(collector)
        perception.select_target('window:1:pid:2'); perception.start()
        perception.observe(); perception.observe()
        self.assertEqual(len(sessions), 1)
        perception.pause()
        self.assertTrue(sessions[0].stopped)
        with self.assertRaises(RuntimeError): collector('window:1:pid:2')
        perception.select_target('window:3:pid:4'); perception.start(); perception.observe()
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[1].kwargs['handle'], 3)
        perception.stop()
        self.assertTrue(sessions[1].stopped)

    def test_valid_frame_is_bounded_and_encoded_in_memory(self):
        if importlib.util.find_spec('PIL') is None or importlib.util.find_spec('numpy') is None:
            self.skipTest('pixel encoding requires the isolated desktop environment')
        import numpy as np
        from PIL import Image
        pixels = np.zeros((1800, 2000, 4), dtype='uint8')
        pixels[:,:,2] = 200
        frame = {'pixels':pixels,'valid':True,'width':2000,'height':1800,'provider':'windows-graphics-capture'}
        bundle = collect_visual(handle=1, process_id=2, approved=True, collector=lambda **kw:frame)
        with Image.open(io.BytesIO(base64.b64decode(bundle.image['data_base64']))) as image:
            self.assertEqual(image.size, (1600, 1440))
            self.assertGreater(image.getpixel((10,10))[0], 150)
        self.assertEqual(bundle.target, 'window:1:pid:2')

    def test_invalid_frame_has_no_model_image(self):
        bundle = collect_visual(handle=1, process_id=2, approved=True, collector=lambda **kw:{
            'valid':False,'width':2,'height':2,'provider':'windows-graphics-capture','reason':'black'})
        self.assertFalse(bundle.valid)
        self.assertIsNone(bundle.image)
