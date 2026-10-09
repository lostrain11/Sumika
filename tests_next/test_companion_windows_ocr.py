import unittest
from extensions.companion.windows_ocr import WindowsOCR, normalize_text


class WindowsOCRTests(unittest.TestCase):
    @staticmethod
    def _image(value):
        return {'data_base64': value}

    def test_cjk_normalization_preserves_latin_words(self):
        self.assertEqual(normalize_text('内 存 管 理 Boot Loader'), '内存管理 Boot Loader')

    def test_cache_is_single_frame_and_cleared_on_stop(self):
        calls=[]
        def recognize(image):
            calls.append(image)
            return [{'text':'章 节','region':[0.1,0.2,0.5,0.3]}]
        ocr=WindowsOCR(recognize)
        a={'data_base64':'a'}
        self.assertIn('章节',ocr(a)['text'])
        ocr(a)
        self.assertEqual(len(calls),1)
        ocr({'data_base64':'b'});ocr(a)
        self.assertEqual(len(calls),3)
        ocr.stop();ocr(a)
        self.assertEqual(len(calls),4)

    def test_oversize_lines_bounded_and_invalid_regions_rejected(self):
        ocr=WindowsOCR(lambda image:[{'text':'X'*1000,'region':[0,0,1,1]}],max_chars=256)
        self.assertLessEqual(len(ocr({'data_base64':'a'})['text']),256)
        invalid=WindowsOCR(lambda image:[{'text':'text','region':[1,0,0,1]}])
        with self.assertRaises(ValueError):invalid({'data_base64':'b'})

    def test_equal_decoded_pixels_reuse_ocr(self):
        calls = []
        ocr = WindowsOCR(lambda image: (calls.append(image) or [
            {'text':'正文', 'region':[0,0,1,1]}]))
        ocr._make_fingerprint = lambda image: b'near'
        first = self._image('first')
        second = self._image('second')
        ocr(first); result = ocr(second)
        self.assertEqual(len(calls), 1)
        self.assertIn('正文', result['text'])

    def test_different_pixels_run_ocr(self):
        calls = []
        ocr = WindowsOCR(lambda image: (calls.append(image) or [
            {'text':'正文', 'region':[0,0,1,1]}]))
        ocr._make_fingerprint = lambda image: image['data_base64'].encode()
        ocr(self._image('black')); ocr(self._image('white'))
        self.assertEqual(len(calls), 2)
