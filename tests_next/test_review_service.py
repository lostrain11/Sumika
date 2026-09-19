import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from extensions.desktop.review_service import execute


class ReviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='.sumika-next')
        self.addCleanup(self.temp.cleanup)
        self.client = Mock(registry=Path(self.temp.name)/'auth.json')
        self.request = dict(owner='a'*64, request_id='review-'+'a'*64+'-call', action='submit',
                            site='chatgpt.com', prompt='Find flaws in this finished plan.', approved=True)

    @patch('extensions.desktop.review_service.submit_text')
    def test_only_trusted_approved_request_dispatches(self, submit):
        execute(self.client, self.request)
        submit.assert_called_once_with(self.client, 'chatgpt.com', self.request['prompt'],
                                       request_id=self.request['request_id'], approved=True)

    @patch('extensions.desktop.review_service.submit_text')
    def test_reject_scope_permission_and_budget_before_browser(self, submit):
        for change in ({'approved':False}, {'request_id':'review-other-call'}, {'owner':''}, {'prompt':'x'*30001}):
            with self.assertRaises((PermissionError, ValueError)):
                execute(self.client, {**self.request, **change})
        submit.assert_not_called()

    @patch('extensions.desktop.review_service.collect_response')
    @patch('extensions.desktop.review_service.submit_text')
    def test_collect_cannot_turn_into_send(self, submit, collect):
        execute(self.client, {**self.request, 'action':'collect', 'approved':False})
        collect.assert_called_once_with(self.client, self.request['request_id'])
        submit.assert_not_called()
