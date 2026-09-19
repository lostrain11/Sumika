import unittest
from extensions.desktop.consultation import ConsultationBrowser

class ConsultationStateTests(unittest.TestCase):
    def test_status_machine_and_no_unknown_retry(self):
        c=ConsultationBrowser(object())
        c.requests['r']={'source_id':'s','status':'submitted'}
        self.assertEqual(c.status('r')['status'],'submitted')
        self.assertEqual(c.cancel('r')['status'],'cancelled')
        self.assertEqual(c.cancel('r')['status'],'cancelled')
        with self.assertRaises(KeyError):c.status('missing')
