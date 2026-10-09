import unittest
from unittest.mock import Mock
from extensions.companion.contracts import ObservationBundle
from extensions.companion.windows_learning import WindowsLearningCollector


class WindowsLearningTests(unittest.TestCase):
    target='window:123:pid:42'

    def test_existing_ocr_cache_scoped_to_page_and_invalid_capture(self):
        from extensions.companion.windows_ocr import WindowsOCR
        recognize = Mock(return_value=[{'text':'lesson','region':[0,0,1,1]}])
        ocr = WindowsOCR(recognizer=recognize)
        collector = WindowsLearningCollector(approved=True,visual=self.visual,text=self.text,ocr=ocr)
        self.text.collect.return_value = self.bundle(valid=False)
        identity = {'kind':'pdf','document':'lesson.pdf','page':1}
        self.text.reader_context.return_value = identity
        collector(self.target);collector(self.target)
        self.assertEqual(recognize.call_count,1)
        self.text.reader_context.return_value = dict(identity,page=2)
        collector(self.target)
        self.assertEqual(recognize.call_count,2)
        original = self.visual.return_value
        from dataclasses import replace
        self.visual.return_value = replace(original,valid=False,image=None)
        collector(self.target)
        self.assertIsNone(ocr._result)
        self.visual.return_value = original
        collector(self.target)
        self.assertEqual(recognize.call_count,3)
        collector.stop()
        self.assertIsNone(ocr._result)

    def test_stop_clears_existing_ocr_when_visual_stop_fails(self):
        self.visual.stop.side_effect = RuntimeError('capture stop failed')
        with self.assertRaises(RuntimeError):
            self.collector.stop()
        self.ocr.stop.assert_called_once()

    def test_pdf_crop_maps_verified_viewport_and_rejects_frame_size_mismatch(self):
        import base64, io
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('requires capability image runtime')
        pixels = Image.new('RGB',(100,80),'white')
        buffer = io.BytesIO()
        pixels.save(buffer,format='PNG')
        pixels.close()
        visual = ObservationBundle.now(source='window-visual', target=self.target,
            valid=True, image={'media_type':'image/png',
                'data_base64':base64.b64encode(buffer.getvalue()).decode('ascii')},
            metadata={'width':100,'height':80})
        region = {'window_size':[100,80], 'bounds':[10,20,90,80]}
        cropped = WindowsLearningCollector._crop_reader(visual,region)
        with Image.open(io.BytesIO(base64.b64decode(cropped.image['data_base64']))) as image:
            self.assertEqual(image.size,(80,60))
        self.assertEqual(cropped.metadata['image_region']['bounds'],[10,20,90,80])
        mismatch = dict(region,window_size=[101,80])
        self.assertIs(WindowsLearningCollector._crop_reader(visual,mismatch),visual)

    def test_changed_reader_region_keeps_original_image(self):
        identity = {'kind':'pdf','document':'lesson.pdf','page':1}
        self.text.reader_context.return_value = identity
        self.text.reader_region.side_effect = [
            {'window_size':[100,80],'bounds':[0,20,100,80]},
            {'window_size':[100,80],'bounds':[0,30,100,80]}]
        self.text.collect.return_value = self.bundle('lesson')
        result = self.collector(self.target)
        self.assertEqual(result.image,self.visual.return_value.image)
        self.assertNotIn('image_region',result.metadata)

    def setUp(self):
        self.visual=Mock(return_value=ObservationBundle.now(source='window-visual',
            target=self.target,valid=True,image={'media_type':'image/jpeg','data_base64':'fixture'}))
        self.text=Mock()
        self.text.window_title.return_value='Lesson'
        self.ocr=Mock(return_value={'text':'','status':'empty'})
        self.collector=WindowsLearningCollector(approved=True,visual=self.visual,text=self.text,ocr=self.ocr)

    def bundle(self,text='',valid=True,target=None):
        return ObservationBundle.now(source='document-selection',target=target or self.target,
                                      valid=valid,text=text,metadata={'selected':True})

    def test_expected_pdf_path_rejects_same_name_and_preserves_unknown_fallback(self):
        from pathlib import Path
        expected = Path('E:/first/lesson.pdf').resolve()
        self.text.collect.return_value = self.bundle('visible lesson')
        identity = {'kind':'pdf', 'document':'lesson.pdf', 'page':1,
                    'document_path':str(Path('E:/second/lesson.pdf').resolve())}
        self.text.reader_context.return_value = identity
        result = self.collector(self.target, expected_document=expected)
        self.assertFalse(result.valid)
        self.assertEqual(result.text, '')
        self.assertIsNone(result.image)
        self.ocr.assert_not_called()
        self.text.reader_context.return_value = dict(identity, document_path=str(expected))
        result = self.collector(self.target, expected_document=expected)
        self.assertTrue(result.valid)
        self.assertTrue(result.metadata['document_identity_verified'])
        self.text.reader_context.return_value = {'kind':'pdf','document':'lesson.pdf','page':1}
        result = self.collector(self.target, expected_document=expected)
        self.assertTrue(result.valid)
        self.assertFalse(result.metadata['document_identity_verified'])
        for invalid in ('lesson.pdf', 'E:/first/file.txt'):
            with self.assertRaises(ValueError):
                self.collector(self.target, expected_document=invalid)

    def test_fixed_document_binding_applies_to_every_observation(self):
        from pathlib import Path
        expected = Path('E:/first/lesson.pdf').resolve()
        collector = WindowsLearningCollector(approved=True, visual=self.visual,
            text=self.text, ocr=self.ocr, expected_document=expected)
        self.text.collect.return_value = self.bundle('lesson')
        identity = {'kind':'pdf', 'document':'lesson.pdf', 'page':1,
                    'document_path':str(expected)}
        self.text.reader_context.return_value = identity
        self.assertTrue(collector(self.target).metadata['document_identity_verified'])
        self.text.reader_context.return_value = dict(identity,
            document_path=str(Path('E:/second/lesson.pdf').resolve()))
        result = collector(self.target)
        self.assertFalse(result.valid)
        self.assertIsNone(result.image)
        self.assertEqual(result.text, '')
        with self.assertRaises(ValueError):
            collector(self.target, expected_document=Path('E:/second/lesson.pdf').resolve())
        collector.start(); collector.stop()
        self.visual.start.assert_called_once()
        self.visual.stop.assert_called_once()
        self.ocr.stop.assert_called_once()

    def test_selection_preferred_and_same_visual_contract(self):
        self.text.collect.return_value=self.bundle('selected formula')
        result=self.collector(self.target)
        self.assertEqual(result.text,'selected formula')
        self.assertEqual(result.source,'window-visual')
        self.assertEqual(result.metadata['text_source'],'document-selection')
        self.assertEqual(self.text.collect.call_count,1)
        self.assertTrue(result.image)

    def test_loading_pdf_discards_chrome_image_and_does_not_run_ocr(self):
        self.text.collect.return_value = ObservationBundle.now(source='windows-uia',
            target=self.target, valid=False, metadata={'reason': 'PDF reader is not ready'})
        result = self.collector(self.target)
        self.assertFalse(result.valid)
        self.assertEqual(result.text, '')
        self.assertIsNone(result.image)
        self.assertEqual(result.metadata['text_status'], 'reader_not_ready')
        self.ocr.assert_not_called()

    def test_loaded_pdf_scan_uses_bound_page_ocr(self):
        identity = {'kind': 'pdf', 'document': 'scan.pdf', 'page': 1}
        self.text.reader_context.return_value = identity
        self.text.collect.return_value = ObservationBundle.now(source='windows-uia',
            target=self.target, valid=False, metadata={'reason': 'PDF visible text is unavailable'})
        self.ocr.return_value = {'text': 'scanned formula', 'status': 'available',
                                'regions': [], 'truncated': False}
        result = self.collector(self.target)
        self.assertTrue(result.valid)
        self.assertEqual(result.text, 'scanned formula')
        self.assertEqual(result.metadata['page'], 1)

    def test_pdf_page_is_bound_and_same_title_navigation_during_capture_rejected(self):
        first = {'kind': 'pdf', 'document': 'lesson.pdf', 'page': 1,
                 'page_source': 'edge-uia-pageselector'}
        self.text.collect.return_value = self.bundle('page one')
        self.text.reader_context.side_effect = [first, first]
        result = self.collector(self.target)
        self.assertEqual(result.metadata['page'], 1)
        self.assertEqual(result.metadata['media_identity'], first)
        self.text.reader_context.side_effect = [first, dict(first, page=2)]
        result = self.collector(self.target)
        self.assertFalse(result.valid)
        self.assertIsNone(result.image)
        self.assertEqual(result.text, '')

    def test_no_selection_reads_visible_text_and_retains_lifecycle(self):
        self.text.collect.side_effect=[self.bundle(valid=False),self.bundle('visible chapter')]
        self.assertEqual(self.collector(self.target).text,'visible chapter')
        self.assertFalse(self.text.collect.call_args.kwargs['selected'])
        self.collector.stop();self.collector.start()
        self.visual.stop.assert_called_once();self.visual.start.assert_called_once()

    def test_unavailable_text_preserves_visual_but_identity_change_invalidates(self):
        self.text.collect.side_effect=RuntimeError('UIA unavailable')
        self.assertTrue(self.collector(self.target).valid)
        self.text.collect.side_effect=ValueError('window process changed')
        result=self.collector(self.target)
        self.assertFalse(result.valid)
        self.assertIsNone(result.image)
        self.assertEqual(result.text,'')

    def test_mismatched_text_and_invalid_visual_not_used(self):
        self.text.collect.return_value=self.bundle('old',target='window:456:pid:42')
        self.assertFalse(self.collector(self.target).valid)
        self.text.collect.return_value=self.bundle('visible')
        self.visual.return_value=ObservationBundle.now(source='window-visual',target=self.target,valid=False)
        self.assertEqual(self.collector(self.target).text,'')

    def test_tab_switch_between_text_and_capture_invalidates_both(self):
        self.text.window_title.side_effect=['Tutorial','WeRead']
        self.text.collect.return_value=self.bundle('previous tutorial')
        result=self.collector(self.target)
        self.assertFalse(result.valid)
        self.assertEqual(result.text,'')
        self.assertIsNone(result.image)

    def test_title_change_reported_by_text_does_not_fallback_to_new_page(self):
        self.text.collect.return_value=ObservationBundle.now(source='windows-uia',
            target=self.target,valid=False,metadata={'reason':'window page changed during text collection'})
        result=self.collector(self.target)
        self.assertFalse(result.valid)
        self.text.collect.assert_called_once()

    def test_reader_chrome_is_supplemental_not_body(self):
        self.text.collect.return_value=ObservationBundle.now(source='document-visible',
            target=self.target,valid=True,text='1.2 章节',metadata={'text_role':'reader-navigation'})
        result=self.collector(self.target)
        self.assertEqual(result.metadata['text_status'],'navigation_only')
        self.assertTrue(result.image)

    def test_canvas_ocr_comes_from_same_image_and_stops_with_collector(self):
        self.text.collect.return_value=self.bundle(valid=False)
        self.ocr.return_value={'text':'[区域] 当前页正文','status':'available',
                              'regions':[[0,0,1,1]],'truncated':False}
        result=self.collector(self.target)
        self.assertEqual(result.metadata['text_source'],'windows-ocr')
        self.assertEqual(result.text,'[区域] 当前页正文')
        self.ocr.assert_called_once_with(result.image)
        self.collector.stop()
        self.ocr.stop.assert_called_once()
