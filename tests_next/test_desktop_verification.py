import unittest
from extensions.desktop.control.verification import verify_text

class DesktopVerificationTests(unittest.TestCase):
    def test_disabled_and_input_boundaries(self):
        self.assertTrue(verify_text('missing','x',enabled=False)['disabled'])
        with self.assertRaises(ValueError):verify_text('missing','')
        with self.assertRaises(ValueError):verify_text('missing','x',min_similarity=2)
