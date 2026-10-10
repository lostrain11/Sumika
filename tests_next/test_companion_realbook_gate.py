"""Real-book acceptance gate: strong-majority default, declared weak variant."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

from verify_companion_realbook import PageTextIndex, evaluate_gate


def gate_report(*, flips_ok=22, flips=22, jump=True, identity=True, strong=12):
    return {'flips_ok': flips_ok, 'jump_back': {'page_matches': jump},
            'absolute_document_identity': identity,
            'strong_page_verifications': strong}


class RealBookGateTests(unittest.TestCase):
    def test_strong_majority_default(self):
        self.assertTrue(evaluate_gate(gate_report(strong=11), flips_requested=22))
        self.assertFalse(evaluate_gate(gate_report(strong=10), flips_requested=22))

    def test_structural_failures_are_not_rescued(self):
        self.assertFalse(evaluate_gate(gate_report(flips_ok=21, strong=22),
                                        flips_requested=22))
        self.assertFalse(evaluate_gate(gate_report(jump=False, strong=22),
                                        flips_requested=22))
        self.assertFalse(evaluate_gate(gate_report(identity=False, strong=22),
                                        flips_requested=22))

    def test_weak_declared_variant_accepts_without_strong_checks(self):
        # An all-image book: zero strong verifications, tracking still proven.
        self.assertTrue(evaluate_gate(gate_report(strong=0), flips_requested=22,
                                      expect_weak=True))
        self.assertFalse(evaluate_gate(gate_report(flips_ok=20, strong=0),
                                        flips_requested=22, expect_weak=True))
        self.assertFalse(evaluate_gate(gate_report(jump=False, strong=0),
                                        flips_requested=22, expect_weak=True))

    def test_verification_mode_is_recorded(self):
        data = gate_report(strong=0)
        evaluate_gate(data, flips_requested=22, expect_weak=True)
        self.assertEqual(data['content_verification'], 'weak-declared')
        data = gate_report(strong=12)
        evaluate_gate(data, flips_requested=22)
        self.assertEqual(data['content_verification'], 'strong-majority')


try:
    import pypdf  # noqa: F401  (bundled runtime ships it; dev python may not)
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


@unittest.skipUnless(HAS_PYPDF, 'pypdf is only bundled with the packaged runtime')
class PageTextIndexTests(unittest.TestCase):
    def test_image_only_pdf_honestly_downgrades(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=612, height=792)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'image-only.pdf'
            writer.write(str(path))
            index = PageTextIndex(path)
            self.assertEqual(index.verify(1, 'any visible text'), ('none', 0.0))
            self.assertEqual(index.verify(2, ''), ('none', 0.0))


if __name__ == '__main__':
    unittest.main()
