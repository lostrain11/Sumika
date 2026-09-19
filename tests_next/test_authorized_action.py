import unittest
from extensions.desktop.control.authorized_action import execute

class FakeController:
    def act(self,*args,**kwargs):return {'status':'performed','verification_hash':'h'}

class AuthorizedActionTests(unittest.TestCase):
    def test_without_post_check_preserves_execution_result(self):
        self.assertEqual(execute(FakeController(),handle=1,process_id=2,action='invoke',approved=True)['status'],'performed')
    def test_expected_text_requires_image(self):
        with self.assertRaises(ValueError):execute(FakeController(),handle=1,process_id=2,action='invoke',approved=True,expected_text='ok')
