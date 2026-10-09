import unittest
from unittest.mock import Mock
from extensions.companion.windows_text import WindowsTextCollector


class WindowsTextTests(unittest.TestCase):
    def test_pdf_identity_uses_native_toolbar_and_rejects_page_input(self):
        from pathlib import Path
        collector, window, _ = self.collector()
        entry, toolbar, root = Mock(), Mock(), Mock()
        entry.is_visible.return_value = True
        entry.parent.return_value = toolbar
        toolbar.element_info.control_type = 'ToolBar'
        toolbar.parent.return_value = root
        root.element_info.control_type = 'Window'
        window.descendants.return_value = [entry]
        expected = Path('E:/fixtures/same name.pdf').resolve()
        for address in (str(expected), expected.as_uri() + '#page=2'):
            entry.get_value.return_value = address
            self.assertEqual(collector._document_identity(window)['document_path'], str(expected))
        root.element_info.control_type = 'Document'
        self.assertEqual(collector._document_identity(window), {'document_identity':'unknown'})
        root.element_info.control_type = 'Window'
        for address in ('https://example.org/lesson.pdf', 'lesson.pdf', 'file://server/share/lesson.pdf'):
            entry.get_value.return_value = address
            self.assertEqual(collector._document_identity(window), {'document_identity':'unknown'})
        window.descendants.return_value = [entry, entry]
        self.assertEqual(collector._document_identity(window), {'document_identity':'unknown'})

    def test_pdf_loading_document_does_not_expose_toolbar_as_body(self):
        from unittest.mock import patch
        collector, window, document = self.collector('lesson.pdf toolbar')
        document.window_text.return_value = 'lesson.pdf'
        window.window_text.return_value = 'lesson.pdf - Microsoft Edge'
        with patch.object(collector, 'reader_context', return_value=None):
            for selected in (True, False):
                result = collector.collect(handle=123, process_id=456, selected=selected)
                self.assertFalse(result.valid)
                self.assertEqual(result.metadata['reason'], 'PDF reader is not ready')
                self.assertEqual(result.text, '')
        document.iface_text.GetVisibleRanges.assert_not_called()
        document.iface_text.GetSelection.assert_not_called()
        window.descendants.return_value = []
        result = collector.collect(handle=123, process_id=456)
        self.assertFalse(result.valid)
        self.assertEqual(result.metadata['reason'], 'PDF reader is not ready')

    def test_pdf_scan_without_native_prose_never_falls_back_to_toolbar(self):
        from unittest.mock import patch
        collector, window, document = self.collector('toolbar')
        document.window_text.return_value = 'lesson.pdf'
        window.window_text.return_value = 'lesson.pdf - Microsoft Edge'
        document.descendants.return_value = []
        with patch.object(collector, 'reader_context', return_value={'document': 'lesson.pdf', 'page': 1}):
            result = collector.collect(handle=123, process_id=456)
        self.assertFalse(result.valid)
        self.assertEqual(result.metadata['reason'], 'PDF visible text is unavailable')
        document.iface_text.GetVisibleRanges.assert_not_called()

    def test_pdf_native_text_excludes_hidden_page_and_rejects_page_race(self):
        from unittest.mock import patch
        collector, window, document = self.collector()
        document.window_text.return_value = 'lesson.pdf'
        window.window_text.return_value = 'lesson.pdf - Microsoft Edge'
        visible, hidden = Mock(), Mock()
        visible.is_visible.return_value = True
        visible.window_text.return_value = 'CURRENT PAGE'
        hidden.is_visible.return_value = False
        hidden.window_text.return_value = 'UNSEEN PAGE'
        document.descendants.return_value = [visible, hidden]
        identity = {'document': 'lesson.pdf', 'page': 1}
        with patch.object(collector, 'reader_context', return_value=identity):
            result = collector.collect(handle=123, process_id=456)
            self.assertEqual(result.text, 'CURRENT PAGE')
            self.assertEqual(result.metadata['text_source'], 'pdf-visible-uia')
            hidden.window_text.assert_not_called()
        with patch.object(collector, 'reader_context', side_effect=[identity, dict(identity, page=2)]):
            result = collector.collect(handle=123, process_id=456)
            self.assertFalse(result.valid)
            self.assertEqual(result.text, '')

    def test_pdf_selector_requires_unique_visible_control_and_document_ancestry(self):
        collector, window, document = self.collector()
        window.window_text.return_value = 'lesson.pdf - Microsoft Edge'
        document.window_text.return_value = 'lesson.pdf'
        document.element_info.control_type = 'Document'
        selector = Mock()
        selector.element_info.automation_id = 'pageselector'
        selector.is_visible.return_value = True
        selector.get_value.return_value = '2'
        selector.parent.return_value = document
        window.descendants.return_value = [selector]
        self.assertEqual(collector.reader_context(handle=123, process_id=456)['page'], 2)
        selector.get_value.return_value = '2 / 10'
        self.assertIsNone(collector.reader_context(handle=123, process_id=456))
        selector.get_value.return_value = '2'
        window.descendants.return_value = [selector, selector]
        self.assertIsNone(collector.reader_context(handle=123, process_id=456))
        window.descendants.return_value = [selector]
        window.window_text.return_value = 'another.pdf - Microsoft Edge'
        self.assertIsNone(collector.reader_context(handle=123, process_id=456))

    def test_continuous_selection_clips_to_visible_range(self):
        class Range:
            def __init__(self,start,end): self.points=[start,end]
            def Clone(self): return Range(*self.points)
            def CompareEndpoints(self,endpoint,other,other_endpoint):
                return self.points[endpoint]-other.points[other_endpoint]
            def MoveEndpointByRange(self,endpoint,other,other_endpoint):
                self.points[endpoint]=other.points[other_endpoint]
                if self.points[0]>self.points[1]: self.points[1-endpoint]=self.points[endpoint]
            def GetText(self,maximum): return 'oldNEWnext'[self.points[0]:self.points[1]][:maximum]
        collector,_,document=self.collector()
        selected=document.iface_text.GetSelection.return_value
        selected.Length=1
        selected.GetElement.return_value=Range(0,6)
        visible=document.iface_text.GetVisibleRanges.return_value
        visible.Length=1
        visible.GetElement.return_value=Range(3,6)
        result=collector.collect(handle=123,process_id=456,selected=True,visible_selection_only=True)
        self.assertEqual(result.text,'NEW')
        visible.GetElement.return_value=Range(6,10)
        result=collector.collect(handle=123,process_id=456,selected=True,visible_selection_only=True)
        self.assertFalse(result.valid)
        self.assertEqual(result.text,'')
    def collector(self, text='当前可见教程'):
        controller = Mock()
        window = controller._window.return_value
        window.is_visible.return_value = True
        window.is_minimized.return_value = False
        window.window_text.return_value = '教程网页'
        document = Mock()
        document.is_visible.return_value = True
        document.window_text.return_value = '教程网页'
        window.descendants.return_value = [document]
        ranges = document.iface_text.GetVisibleRanges.return_value
        ranges.Length = 1
        ranges.GetElement.return_value.GetText.return_value = text
        return WindowsTextCollector(controller), window, document

    def test_only_visible_ranges_of_exact_window_are_read(self):
        collector, window, document = self.collector()
        result = collector.collect(handle=123, process_id=456)
        self.assertTrue(result.valid)
        self.assertEqual(result.text, '当前可见教程')
        self.assertEqual(result.target, 'window:123:pid:456')
        self.assertEqual(collector.controller._window.call_count, 2)
        document.iface_text.GetSelection.assert_not_called()

    def test_selection_mode_does_not_read_entire_document(self):
        collector, _, document = self.collector()
        ranges = document.iface_text.GetSelection.return_value
        ranges.Length = 1
        ranges.GetElement.return_value.GetText.return_value = '选中公式'
        result = collector.collect(handle=123, process_id=456, selected=True, kind='ebook')
        self.assertEqual(result.source, 'ebook-selection')
        document.iface_text.GetVisibleRanges.assert_not_called()

    def test_minimized_and_ambiguous_documents_are_not_collected(self):
        collector, window, document = self.collector()
        window.is_minimized.return_value = True
        self.assertFalse(collector.collect(handle=123, process_id=456).valid)
        window.descendants.assert_not_called()
        window.is_minimized.return_value = False
        window.descendants.return_value = [document, document]
        self.assertFalse(collector.collect(handle=123, process_id=456).valid)
        document.iface_text.GetVisibleRanges.assert_not_called()

    def test_identity_change_during_read_rejects_result(self):
        collector, window, _ = self.collector()
        collector.controller._window.side_effect = [window, ValueError('window process changed')]
        with self.assertRaisesRegex(ValueError, 'changed'):
            collector.collect(handle=123, process_id=456)

    def test_tab_title_change_during_text_read_discards_text(self):
        collector, window, _ = self.collector()
        window.window_text.side_effect = ['Tutorial', 'WeRead']
        result = collector.collect(handle=123, process_id=456)
        self.assertFalse(result.valid)
        self.assertEqual(result.text, '')
        self.assertEqual(result.metadata['reason'], 'window page changed during text collection')

    def test_background_document_requires_selected_tab_and_matching_title(self):
        collector, window, document = self.collector()
        background = Mock()
        background.window_text.return_value = '后台视频'
        background.is_visible.return_value = True
        tab = Mock()
        tab.is_visible.return_value = True
        tab.window_text.return_value = '教程网页 - 内存使用率 - 100 MB'
        tab.iface_selection_item.CurrentIsSelected = True
        window.window_text.return_value = '教程网页 和另外 1 个页面 - Microsoft Edge'
        window.descendants.side_effect = lambda **kw: ([tab] if kw['control_type']=='TabItem'
                                                     else [background, document])
        result = collector.collect(handle=123, process_id=456)
        self.assertTrue(result.valid)
        self.assertEqual(result.text, '当前可见教程')
        background.iface_text.GetVisibleRanges.assert_not_called()
        tab.window_text.return_value = '后台视频'
        self.assertFalse(collector.collect(handle=123, process_id=456).valid)

    def test_duplicate_active_documents_remain_ambiguous(self):
        collector, window, document = self.collector()
        tab = Mock()
        tab.is_visible.return_value = True
        tab.window_text.return_value = '教程网页'
        tab.iface_selection_item.CurrentIsSelected = True
        window.descendants.side_effect = lambda **kw: ([tab] if kw['control_type']=='TabItem'
                                                     else [document, document])
        self.assertFalse(collector.collect(handle=123, process_id=456).valid)

    def test_reader_navigation_not_labeled_body(self):
        collector, window, document = self.collector('1.2 章节\n\ufffc\n下一页')
        document.window_text.return_value = '一本书 - 微信读书'
        result = collector.collect(handle=123, process_id=456, kind='ebook')
        self.assertEqual(result.metadata['text_role'], 'reader-navigation')
        self.assertEqual(result.text, '1.2 章节\n下一页')
