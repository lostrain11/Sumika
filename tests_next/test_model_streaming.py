import json
import unittest
from unittest.mock import patch

from extensions.models.cloud import CloudProvider, CloudError
from extensions.models.cancellation import RequestCancelled
from extensions.companion import CompanionQuestionService, webpage


class ModelStreamingTests(unittest.TestCase):
    def provider(self):
        return CloudProvider('https://fixture.invalid', key_env='SUMIKA_STREAM_TEST_KEY')

    def test_fragment_usage_and_images_use_same_request(self):
        seen, fragments = [], []
        def events(request, *, timeout, on_event):
            seen.append(json.loads(request.data))
            for value in ({'choices':[{'delta':{'content':'first '}}]},
                          {'choices':[{'delta':{'content':'second'},'finish_reason':'stop'}]},
                          {'choices':[], 'usage':{'prompt_tokens':5,'completion_tokens':2}}):
                on_event(json.dumps(value))
            self.assertFalse(on_event('[DONE]'))
        with patch.dict('os.environ', {'SUMIKA_STREAM_TEST_KEY':'fixture'}), \
             patch('extensions.models.cloud.model_events', events):
            result = self.provider().generate(model='fixture', messages=[{'role':'user','content':'explain'}],
                images=[{'media_type':'image/jpeg','data_base64':'fixture'}], on_delta=fragments.append)
        self.assertEqual(fragments, ['first ', 'second'])
        self.assertEqual(result['text'], 'first second')
        self.assertEqual(result['usage_status'], 'reported')
        self.assertTrue(seen[0]['stream'])
        self.assertEqual(seen[0]['messages'][-1]['content'][1]['type'], 'image_url')

    def test_incomplete_stream_is_not_success_and_is_not_retried(self):
        calls = []
        def events(request, *, timeout, on_event):
            calls.append(1)
            on_event(json.dumps({'choices':[{'delta':{'content':'partial'}}]}))
        with patch.dict('os.environ', {'SUMIKA_STREAM_TEST_KEY':'fixture'}), \
             patch('extensions.models.cloud.model_events', events):
            with self.assertRaises(CloudError) as caught:
                self.provider().generate(model='fixture', messages=[{'role':'user','content':'question'}], on_delta=lambda text:None)
        self.assertEqual(caught.exception.kind, 'incomplete_stream')
        self.assertEqual(calls, [1])

    def test_revoke_between_deltas_stops_delivery_and_history(self):
        seen = []
        def reply(prompt, *, session_id, images, on_delta):
            on_delta('partial')
            service.revoke()
            on_delta('late')
            self.fail('revoked stream continued')
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='content'))
        result = service.ask('explain', on_delta=seen.append)
        self.assertEqual([event['text'] for event in seen], ['partial'])
        self.assertEqual(result['status'], 'stale_response')
        self.assertNotIn('text', result)
        self.assertFalse(service._histories)
