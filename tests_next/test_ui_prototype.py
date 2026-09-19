from pathlib import Path
import unittest

class UIPrototypeTests(unittest.TestCase):
    def test_direction_d_snapshot_is_self_contained(self):
        root=Path('ui/prototype-d')
        html=(root/'index.html').read_text(encoding='utf8')
        self.assertIn('方向 D',html)
        self.assertGreaterEqual(len(list((root/'assets').glob('*.png'))),5)
        self.assertNotIn('node_modules',html)
