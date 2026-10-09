import unittest
from dataclasses import replace
from datetime import timedelta

from extensions.companion.context_fusion import ContextFusion
from extensions.companion.contracts import ObservationBundle
from extensions.companion.qa import CompanionQuestionService


class ContextFusionTests(unittest.TestCase):
    def test_verified_player_interval_enriches_audio_without_inventing_point_time(self):
        from extensions.companion.media_clock import PlayerClockCorrelation
        identity = {'url':'video','timeline_revision':0}
        self.fusion.visual(replace(self.visual, metadata={'media_identity':identity}))
        clock = PlayerClockCorrelation(target='lesson',media_identity=identity,owner_verified=True)
        self.fusion.bind_player_clock(clock)
        audio = replace(self.audio('spoken'), metadata={'media_identity':identity,
            'media_position_known':False, 'media_time_seconds':None,
            'capture_clock_span':{'known':True,'qpc_unit':'100ns','clock_scope':'native-segment-audio',
                                  'start_qpc_position':2500000,'end_qpc_position':7500000}})
        first = self.fusion.audio(audio)
        self.assertFalse(first.metadata['application_audio'][0]['metadata']['player_clock_span']['known'])
        for seconds in (0,0.5,1):
            clock.observe(target='lesson',media_identity=identity,qpc_before=int(seconds*10000000),
                qpc_after=int(seconds*10000000)+10000,media_time_seconds=30+seconds,
                playback_rate=1,paused=False,seeking=False,ended=False)
        metadata = self.fusion.current().metadata['application_audio'][0]['metadata']
        self.assertTrue(metadata['player_clock_span']['known'])
        self.assertFalse(metadata['media_position_known'])
        self.assertIsNone(metadata['media_time_seconds'])
        self.fusion.visual(replace(self.visual,metadata={'media_identity':identity,'paused':True}))
        self.assertFalse(self.fusion.current().metadata['application_audio'][0]['metadata']['player_clock_span']['known'])
        self.fusion.clear()
        with self.assertRaises(PermissionError):
            clock.observe(target='lesson',media_identity=identity,qpc_before=20000000,qpc_after=20010000,
                media_time_seconds=32,playback_rate=1,paused=False,seeking=False,ended=False)

    def test_player_clock_binding_rejects_unmatched_source(self):
        from extensions.companion.media_clock import PlayerClockCorrelation
        clock = PlayerClockCorrelation(target='other',media_identity={},owner_verified=True)
        with self.assertRaises(PermissionError):
            self.fusion.bind_player_clock(clock)

    def test_ask_and_proactive_send_audio_once_without_losing_provenance(self):
        import json
        prompts = []
        service = CompanionQuestionService(lambda prompt, **kwargs:
            prompts.append(prompt) or {'text':'answer'})
        combined = self.fusion.audio(self.audio('unique speech'))
        service.update(combined)
        service.ask('explain')
        service.proactive()
        for prompt in prompts:
            self.assertEqual(prompt.count('unique speech'), 1)
            raw = prompt.split('[来源定位资料] ', 1)[1].split('\n', 1)[0]
            reference = json.loads(raw)['application_audio'][0]
            self.assertEqual(reference['source'], 'application-audio-transcript')
            self.assertEqual(reference['metadata']['capture_offset_seconds'], 2)
            self.assertFalse(reference['metadata']['media_position_known'])
            self.assertIn('observed_at', reference)
        self.assertEqual(combined.metadata['application_audio'][0]['text'], 'unique speech')

    def test_audio_not_in_bounded_body_remains_in_model_metadata(self):
        prompts = []
        service = CompanionQuestionService(lambda prompt, **kwargs:
            prompts.append(prompt) or {'text':'answer'}, max_observation_chars=256)
        self.fusion.visual(replace(self.visual, text='x'*300))
        combined = self.fusion.audio(self.audio('late speech'))
        service.update(combined)
        service.ask('explain')
        self.assertIn('late speech', prompts[0])
        self.assertEqual(combined.metadata['application_audio'][0]['text'], 'late speech')

    def test_same_visual_refresh_does_not_invalidate_bound_audio_question(self):
        service = CompanionQuestionService(lambda *args, **kwargs: {'text':'answer'})
        self.fusion.audio(self.audio())
        service.update(self.fusion.current())
        binding = service.bind_question()
        refreshed = self.fusion.visual(replace(self.visual,
            observed_at=self.visual.observed_at+timedelta(seconds=2)))
        service.update(refreshed)
        self.assertEqual(service.collection_token(), binding.generation)
        self.assertEqual(service.ask('why', binding=binding)['text'], 'answer')

    def setUp(self):
        self.now = 0
        self.fusion = ContextFusion(clock=lambda: self.now, max_chars=20, max_segments=2)
        self.visual = ObservationBundle.now(source='window-visual', target='lesson', valid=True,
            text='diagram', image={'data_base64':'fixture'}, media_time_seconds=30)
        self.fusion.visual(self.visual)

    def audio(self, text='spoken lesson'):
        return ObservationBundle.now(source='application-audio-transcript', target='lesson', valid=True,
            text=text, metadata={'capture_offset_seconds':2,'media_position_known':False})

    def test_audio_augments_visual_and_preserves_distinct_time_sources(self):
        combined = self.fusion.audio(self.audio())
        self.assertEqual(combined.image, self.visual.image)
        self.assertEqual(combined.source, 'window-visual')
        self.assertEqual(combined.media_time_seconds, 30)
        self.assertIn('diagram', combined.text)
        self.assertIn('spoken lesson', combined.text)
        self.assertFalse(combined.metadata['application_audio'][0]['metadata']['media_position_known'])

    def test_expiry_and_clear_leave_original_visual(self):
        self.fusion.audio(self.audio())
        self.now = 120
        self.assertEqual(self.fusion.current(), self.visual)
        self.fusion.audio(self.audio())
        self.assertEqual(self.fusion.clear_audio(), self.visual)
        self.fusion.clear()
        self.assertIsNone(self.fusion.audio(self.audio()))

    def test_target_switch_and_video_seek_discard_old_audio(self):
        self.fusion.audio(self.audio())
        changed = replace(self.visual, media_time_seconds=90)
        self.assertEqual(self.fusion.visual(changed), changed)
        changed = replace(self.visual, target='another')
        self.fusion.visual(changed)
        self.assertIsNone(self.fusion.audio(self.audio()))

    def test_repeated_visual_refresh_preserves_audio_with_bounded_segments(self):
        for text in ('one', 'two', 'three'):
            self.fusion.audio(self.audio(text))
        combined = self.fusion.visual(replace(self.visual,
            observed_at=self.visual.observed_at+timedelta(seconds=2)))
        self.assertEqual([x['text'] for x in combined.metadata['application_audio']], ['two','three'])

    def test_normal_playback_time_advance_preserves_audio(self):
        self.fusion.audio(self.audio('spoken'))
        later = replace(self.visual, observed_at=self.visual.observed_at + timedelta(seconds=2),
                        media_time_seconds=32)
        combined = self.fusion.visual(later)
        self.assertIn('spoken', combined.text)

    def test_same_time_and_tab_new_video_identity_discards_previous_audio(self):
        first = replace(self.visual, metadata={'media_identity':{'url':'video','part':1}})
        self.fusion.visual(first)
        self.fusion.audio(self.audio('old lesson'))
        second = replace(first, metadata={'media_identity':{'url':'video','part':2}})
        self.assertEqual(self.fusion.visual(second), second)
        self.assertNotIn('application_audio', self.fusion.current().metadata)

    def test_audio_with_old_media_identity_is_rejected(self):
        first = replace(self.visual, metadata={'media_identity': {'url': 'video', 'part': 1}})
        self.fusion.visual(first)
        stale = replace(self.audio('stale'), metadata={'media_identity': {'url': 'video', 'part': 0}})
        self.assertIsNone(self.fusion.audio(stale))
        self.assertIsNone(self.fusion.audio(self.audio('unbound speech')))

    def test_tiny_seek_epoch_discards_audio_even_when_clock_delta_is_normal(self):
        identity = {'url': 'video', 'media_instance': 1, 'timeline_revision': 0}
        first = replace(self.visual, metadata={'media_identity': identity, 'playback_rate': 1})
        self.fusion.visual(first)
        self.fusion.audio(replace(self.audio('old speech'), metadata={'media_identity': identity}))
        second = replace(first, media_time_seconds=first.media_time_seconds + 0.05,
            observed_at=first.observed_at + timedelta(seconds=0.05),
            metadata={'media_identity':dict(identity, timeline_revision=1), 'playback_rate':1})
        self.assertEqual(self.fusion.visual(second), second)
        self.assertIsNone(self.fusion.audio(replace(self.audio('late old speech'),
            metadata={'media_identity':identity})))

    def test_bound_media_time_rejects_stale_audio_reference(self):
        identity = {'url': 'video', 'part': 1}
        visual = replace(self.visual, media_time_seconds=100,
            metadata={'media_identity': identity, 'playback_rate': 1.0})
        self.fusion.visual(visual)
        fresh = replace(self.audio('fresh'), metadata={
            'media_identity': identity, 'media_position_known': True,
            'media_time_seconds': 104})
        stale = replace(self.audio('stale'), metadata={
            'media_identity': identity, 'media_position_known': True,
            'media_time_seconds': 130})
        self.assertIsNotNone(self.fusion.audio(fresh))
        self.assertIsNone(self.fusion.audio(stale))
