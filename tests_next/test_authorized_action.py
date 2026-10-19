import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from extensions.desktop.control.authorized_action import execute

class FakeController:
    def act(self,*args,**kwargs):return {'status':'performed','verification_hash':'h'}

class AuthorizedActionTests(unittest.TestCase):
    def test_without_post_check_preserves_execution_result(self):
        self.assertEqual(execute(FakeController(),handle=1,process_id=2,action='invoke',approved=True)['status'],'performed')
    def test_expected_text_requires_image(self):
        controller=Mock()
        with self.assertRaises(ValueError):execute(controller,handle=1,process_id=2,action='invoke',approved=True,expected_text='ok')
        controller.act.assert_not_called()

    def test_invalid_requests_never_reach_controller(self):
        for changes in ({'approved':False},{'handle':True},{'process_id':0},{'action':'unknown'},
                        {'action':'set_text'}, {'action':'hotkey','keys':['']},
                        {'expected_text':''}, {'verification_image':'missing'},
                        {'capture_verification':'not callable'}, {'automation_id':3}):
            with self.subTest(changes=changes):
                controller=Mock()
                args=dict(handle=1,process_id=2,action='invoke',approved=True);args.update(changes)
                with self.assertRaises((ValueError,PermissionError)):execute(controller,**args)
                controller.act.assert_not_called()

    def test_exact_action_parameters_forwarded(self):
        controller=Mock();controller.act.return_value={'status':'performed'}
        execute(controller,handle=1,process_id=2,action='set_text',approved=True,
                automation_id='edit',control_type='Edit',text='你好',expected_snapshot_hash='snapshot')
        controller.act.assert_called_once_with(1,2,'set_text',approved=True,
                automation_id='edit',control_type='Edit',text='你好',keys=None,expected_snapshot_hash='snapshot')

    def test_supplied_image_matches_cannot_prove_post_action_state(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'old.png';image.touch()
            with patch('extensions.desktop.control.authorized_action.verify_text',return_value={'status':'verified'}):
                result=execute(FakeController(),handle=1,process_id=2,action='invoke',approved=True,
                               expected_text='ok',verification_image=image)
            self.assertEqual(result['status'],'unknown')
            self.assertTrue(result['action_executed'])
            self.assertFalse(result['retry_allowed'])
            self.assertEqual(result['post_verification']['freshness'],'not_established')

    def test_capture_occurs_after_action_and_ocr_failure_does_not_reexecute(self):
        calls=[]
        controller=Mock()
        def action(*a,**k):calls.append('action');return {'status':'performed'}
        def capture(**kwargs):
            self.assertEqual(kwargs,{'handle':1,'process_id':2})
            calls.append('capture');return 'fresh.png'
        controller.act.side_effect=action
        with patch('extensions.desktop.control.authorized_action.verify_text',side_effect=RuntimeError('OCR unavailable')):
            result=execute(controller,handle=1,process_id=2,action='invoke',approved=True,
                           expected_text='ok',capture_verification=capture)
        self.assertEqual(calls,['action','capture']);controller.act.assert_called_once()
        self.assertEqual(result['status'],'unknown');self.assertFalse(result['retry_allowed'])

    def test_fresh_host_capture_and_match_preserve_action_result(self):
        with patch('extensions.desktop.control.authorized_action.verify_text',return_value={'status':'verified'}):
            result=execute(FakeController(),handle=1,process_id=2,action='invoke',approved=True,
                           expected_text='ok',capture_verification=lambda **kwargs:'fresh.png')
        self.assertEqual(result['status'],'performed')
        self.assertEqual(result['post_verification']['freshness'],'host_capture_after_action')

    def test_controller_uncertainty_does_not_start_capture(self):
        controller=Mock();controller.act.return_value={'status':'unknown','retry_allowed':False}
        capture=Mock()
        result=execute(controller,handle=1,process_id=2,action='invoke',approved=True,
                       expected_text='ok',capture_verification=capture)
        capture.assert_not_called();self.assertEqual(result['status'],'unknown')
