import unittest
from ui.state_snapshot import snapshot,validate_state

class UIStateTests(unittest.TestCase):
    def test_projection_is_bounded_and_valid(self):
        state=snapshot(session={'status':'running','id':'s'},modules=[{'id':'memory','enabled':True,'provider':'semantic','health':'ready'}])
        self.assertEqual(validate_state(state)['session']['status'],'running')
    def test_rejects_secrets_and_unknown_status(self):
        with self.assertRaises(ValueError):validate_state(snapshot(session={'status':'bogus'}))
        with self.assertRaises(ValueError):validate_state({'schema_version':1,'session':{'token':'x'}})
