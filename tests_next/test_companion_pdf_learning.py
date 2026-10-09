import tempfile
import unittest
from pathlib import Path

from extensions.companion.pdf_learning import extract_page_text, page_observation


class PdfLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('reportlab fixture dependency unavailable')

    def make_pdf(self, folder):
        from reportlab.pdfgen import canvas
        path = Path(folder) / 'lesson.pdf'
        doc = canvas.Canvas(str(path))
        doc.drawString(40, 760, 'FIRST PAGE')
        doc.showPage()
        doc.drawString(40, 760, 'SECOND PAGE')
        doc.save()
        return path

    def test_extracts_only_explicit_page(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_pdf(folder)
            first = extract_page_text(path, 1)
            second = extract_page_text(path, 2)
            self.assertIn('FIRST PAGE', first['text'])
            self.assertNotIn('SECOND PAGE', first['text'])
            self.assertIn('SECOND PAGE', second['text'])

    def test_page_observation_keeps_file_and_page_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_pdf(folder)
            result = page_observation(pdf_path=path, page_number=2, target='window:1:pid:2')
            self.assertTrue(result.valid)
            self.assertIn('SECOND PAGE', result.text)
            self.assertEqual(result.metadata['page'], 2)
            self.assertEqual(Path(result.metadata['file']), path.resolve())

    def test_missing_page_or_implicit_page_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_pdf(folder)
            with self.assertRaises(ValueError): extract_page_text(path, 3)
            with self.assertRaises(ValueError): extract_page_text(path, None)

    def test_relative_file_rejected_and_selection_bounded(self):
        with self.assertRaises(ValueError):
            extract_page_text('lesson.pdf', 1)
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_pdf(folder)
            result = page_observation(pdf_path=path, page_number=1, target='reader',
                                      selected_text='x' * 300, max_chars=100)
            self.assertEqual(len(result.text), 100)
            self.assertEqual(result.metadata['text_source'], 'pdf-selection')
            self.assertTrue(result.metadata['truncated'])

    def test_page_change_cancels_bound_question_same_page_deduplicates(self):
        from extensions.companion.qa import CompanionQuestionService
        from extensions.companion.content import ContentChangeTracker
        from extensions.models.cancellation import CancellationToken, RequestCancelled
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_pdf(folder)
            first = page_observation(pdf_path=path, page_number=1, target='reader')
            service = CompanionQuestionService(lambda *args, **kwargs: {'text':'fixture'})
            tracker = ContentChangeTracker()
            self.assertTrue(tracker.accept(first)['changed'])
            service.update(first)
            token = CancellationToken()
            remove = service.watch_binding(service.bind_question(), token)
            same = page_observation(pdf_path=path, page_number=1, target='reader')
            self.assertFalse(tracker.accept(same)['changed'])
            service.update(same)
            token.check()
            second = page_observation(pdf_path=path, page_number=2, target='reader')
            service.update(second)
            with self.assertRaises(RequestCancelled):
                token.check()
            remove()
