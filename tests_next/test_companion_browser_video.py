import unittest
import base64
from unittest.mock import MagicMock

from extensions.companion.browser_video import collect_browser_video
from extensions.desktop.browser_consultation_bridge import BrowserConsultationBridge


class BrowserVideoTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.bridge = self.client.bound_bridge.return_value
        self.bridge.session_id = 'study'
        self.bridge.tab_id = 7
        self.bridge._tab.return_value = '7'
        self.bridge._expected.return_value = ('https', 'lesson.test', 443)
        self.bridge._origin.side_effect = BrowserConsultationBridge._origin
        self.value = {'ok': True, 'subtitles': 'current lesson',
                      'observed_at': '2026-10-08T00:00:00Z', 'media_time_seconds': 12,
                      'url': 'https://lesson.test/tutorial', 'paused': True}
        self.bridge._run.return_value = {'ok': True, 'value': self.value}

    def test_read_only_collector_rechecks_permission_and_keeps_provenance(self):
        observation = collect_browser_video(self.client, 'lesson.test')
        self.assertEqual(observation.text, 'current lesson')
        self.assertEqual(observation.target, 'browser:study:tab:7')
        self.assertEqual(observation.media_time_seconds, 12)
        self.assertTrue(observation.metadata['paused'])
        self.assertEqual(self.bridge._authorized_session.call_count, 2)
        self.assertEqual(self.bridge._tab.call_count, 2)
        command = self.bridge._run.call_args.args[0]
        self.assertEqual(command[0], 'evaluate')
        self.assertIn('textTracks', command[-1])

    def test_missing_cue_yields_invalid_observation(self):
        self.value['subtitles'] = ''
        self.assertFalse(collect_browser_video(self.client, 'lesson.test').valid)

    def test_danmaku_is_bounded_metadata_and_does_not_become_body(self):
        self.value['danmaku'] = [{'text': '为什么这里取负号', 'media_time_seconds': 12}]
        observation = collect_browser_video(self.client, 'lesson.test')
        self.assertEqual(observation.text, 'current lesson')
        self.assertEqual(observation.metadata['danmaku'][0]['text'], '为什么这里取负号')

    def test_media_identity_preserved_and_seek_drops_old_content(self):
        self.value['media_identity'] = {'url':self.value['url'],
            'document_started_at':12345, 'source_fingerprint':'ab12', 'part':2}
        observation = collect_browser_video(self.client, 'lesson.test')
        self.assertEqual(observation.metadata['media_identity']['part'], 2)
        self.value['seeking'] = True
        observation = collect_browser_video(self.client, 'lesson.test')
        self.assertFalse(observation.valid)
        self.assertEqual(observation.text, '')
        self.assertIsNone(observation.image)
        self.value['media_identity']['url'] = 'https://other.test'
        with self.assertRaises(ValueError):
            collect_browser_video(self.client, 'lesson.test')

    def test_opt_in_clean_frame_is_valid_without_subtitles(self):
        self.value['subtitles'] = ''
        self.value['image'] = {'media_type':'image/jpeg',
            'data_base64':base64.b64encode(b'\xff\xd8fixture\xff\xd9').decode('ascii')}
        observation = collect_browser_video(self.client, 'lesson.test', capture_frame=True)
        self.assertTrue(observation.valid)
        self.assertEqual(observation.source, 'video-frame')
        self.assertEqual(observation.image,self.value['image'])
        with self.assertRaises(ValueError):
            collect_browser_video(self.client, 'lesson.test')
        self.value['image']['data_base64']='not-base64'
        with self.assertRaises(ValueError):
            collect_browser_video(self.client, 'lesson.test', capture_frame=True)

    def test_media_timeline_requires_bounded_integer_counters(self):
        self.value['media_identity'] = {'url':self.value['url'],
            'document_started_at':12345, 'source_fingerprint':'ab12',
            'media_instance':1, 'timeline_revision':0}
        self.assertEqual(collect_browser_video(self.client, 'lesson.test').metadata[
            'media_identity']['timeline_revision'], 0)
        for field, values in (('media_instance', (0, True, 1.5, 9007199254740992)),
                              ('timeline_revision', (-1, True, 1.5, 9007199254740992))):
            original = self.value['media_identity'][field]
            for value in values:
                self.value['media_identity'][field] = value
                with self.assertRaises(ValueError):
                    collect_browser_video(self.client, 'lesson.test')
            self.value['media_identity'][field] = original

    def test_post_read_revocation_blocks_snapshot(self):
        self.bridge._authorized_session.side_effect = [None, PermissionError('revoked')]
        with self.assertRaises(PermissionError):
            collect_browser_video(self.client, 'lesson.test')

    def test_cross_origin_and_invalid_time_rejected(self):
        self.value['url'] = 'https://other.test/tutorial'
        with self.assertRaises(PermissionError):
            collect_browser_video(self.client, 'lesson.test')
        self.value['url'] = 'https://lesson.test/tutorial'
        for value in (float('nan'), float('inf'), -1, True):
            with self.subTest(value=value):
                self.value['media_time_seconds'] = value
                with self.assertRaises(ValueError):
                    collect_browser_video(self.client, 'lesson.test')

    def test_invalid_playback_rate_rejected(self):
        for value in (0, -1, 16.1, float('nan'), float('inf'), True, '1'):
            self.value['playback_rate'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                collect_browser_video(self.client, 'lesson.test')
        self.value.pop('playback_rate', None)
