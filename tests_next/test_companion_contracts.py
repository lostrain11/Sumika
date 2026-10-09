import unittest
from dataclasses import replace
from datetime import timedelta
from extensions.companion import ObservationBundle, PerceptionService, CompanionQuestionService, ContentChangeTracker, webpage, video, ebook, cues


class CompanionContractTests(unittest.TestCase):
    @staticmethod
    def playing_video():
        return ObservationBundle.now(source='video-frame', target='browser:lesson', valid=True,
            text='original subtitle', image={'media_type': 'image/jpeg', 'data_base64': 'first'},
            media_time_seconds=10, metadata={'url': 'https://www.bilibili.com/video/BVfixture',
                'paused': False, 'ended': False, 'seeking': False, 'playback_rate': 1,
                'media_identity': {'url': 'https://www.bilibili.com/video/BVfixture',
                    'document_started_at': 1234, 'source_fingerprint': 'abc',
                    'media_instance': 1, 'timeline_revision': 0, 'part': 1}})

    def test_playing_video_keeps_frozen_stream_and_playback_binding(self):
        from extensions.models.cancellation import CancellationToken
        first = self.playing_video()
        next_frame = replace(first, observed_at=first.observed_at + timedelta(seconds=1),
            media_time_seconds=11, text='next subtitle',
            image={'media_type': 'image/jpeg', 'data_base64': 'next'})
        calls, deltas = [], []
        def reply(prompt, *, on_delta, **kwargs):
            calls.append((prompt, kwargs['images']))
            on_delta('first part')
            service.update(next_frame)
            on_delta('second part')
            return {'text': 'answer'}
        service = CompanionQuestionService(reply)
        service.update(first)
        binding = service.bind_question()
        playback = CancellationToken()
        remove = service.watch_binding(binding, playback)
        try:
            answer = service.ask('explain', binding=binding, on_delta=deltas.append)
            self.assertEqual(answer['text'], 'answer')
            self.assertEqual(answer['observation_at'], first.observed_at.isoformat())
            self.assertEqual(calls[0][1], [dict(first.image)])
            self.assertNotIn('next subtitle', calls[0][0])
            self.assertEqual(len(deltas), 2)
            self.assertEqual(answer['context_turns'], 1)
            playback.check()
            service.revoke()
            from extensions.models.cancellation import RequestCancelled
            with self.assertRaises(RequestCancelled):
                playback.check()
        finally:
            remove()

    def test_video_discontinuities_still_cancel_frozen_answer(self):
        first = self.playing_video()
        base = replace(first, observed_at=first.observed_at + timedelta(seconds=1),
                       media_time_seconds=11, text='next')
        variants = [replace(base, target='other'), replace(base, source='window-visual'),
                    replace(base, valid=False), replace(base, media_time_seconds=9),
                    replace(base, media_time_seconds=40),
                    replace(base, observed_at=first.observed_at + timedelta(seconds=11))]
        for key, value in [('paused', None), ('ended', True), ('seeking', True),
                           ('playback_rate', 2)]:
            variants.append(replace(base, metadata=dict(base.metadata, **{key: value})))
        for key, value in [('timeline_revision', 1), ('media_instance', 2), ('part', 2),
                           ('document_started_at', 2345), ('source_fingerprint', 'def')]:
            variants.append(replace(base, metadata=dict(base.metadata,
                media_identity=dict(base.metadata['media_identity'], **{key: value}))))
        for key in ['media_instance', 'timeline_revision', 'document_started_at', 'source_fingerprint']:
            identity = dict(first.metadata['media_identity'])
            identity.pop(key)
            # Missing identity is unsafe even when absent on both observations.
            old = replace(first, metadata=dict(first.metadata, media_identity=identity))
            new = replace(base, metadata=dict(base.metadata, media_identity=identity))
            variants.append((old, new))
        for variant in variants:
            old, new = variant if isinstance(variant, tuple) else (first, variant)
            with self.subTest(metadata=new.metadata, time=new.media_time_seconds):
                def reply(*args, **kwargs):
                    service.update(new)
                    return {'text': 'obsolete'}
                service = CompanionQuestionService(reply)
                service.update(old)
                self.assertEqual(service.ask('why')['status'], 'stale_response')

    def test_playing_video_still_invalidates_proactive_suggestion(self):
        first = self.playing_video()
        def reply(*args, **kwargs):
            service.update(replace(first, observed_at=first.observed_at + timedelta(seconds=1),
                                   media_time_seconds=11, text='next lesson'))
            return {'text': 'obsolete suggestion'}
        service = CompanionQuestionService(reply)
        service.update(first)
        self.assertEqual(service.proactive()['status'], 'stale_response')

    def test_video_discussion_retains_old_time_without_becoming_current_evidence(self):
        prompts = []
        service = CompanionQuestionService(lambda prompt, **kwargs:
            prompts.append(prompt) or {'text': 'previous explanation'})
        first = self.playing_video()
        service.update(first)
        service.ask('old formula question')
        second = replace(first, observed_at=first.observed_at + timedelta(seconds=1),
                         media_time_seconds=11, text='next formula')
        service.update(second)
        answer = service.ask('follow up')
        self.assertEqual(answer['context_turns'], 2)
        self.assertIn('old formula question', prompts[-1])
        self.assertIn('[视频时间] 10', prompts[-1])
        self.assertIn('角色回答不是课程事实或当前画面的证据', prompts[-1])
        self.assertIn('[媒体时间] 11', prompts[-1])
        self.assertEqual(answer['observation_at'], second.observed_at.isoformat())
        service.update(replace(second, observed_at=second.observed_at + timedelta(seconds=1),
            metadata=dict(second.metadata, media_identity=dict(
                second.metadata['media_identity'], timeline_revision=1))))
        self.assertEqual(service.ask('new location')['context_turns'], 1)
        self.assertNotIn('old formula question', prompts[-1])

    def test_video_pause_and_resume_keep_question_and_timestamped_discussion(self):
        first = self.playing_video()
        paused = replace(first, observed_at=first.observed_at + timedelta(seconds=1),
                         media_time_seconds=11, metadata=dict(first.metadata, paused=True))
        later_pause = replace(paused, observed_at=first.observed_at + timedelta(seconds=2))
        resumed = replace(first, observed_at=first.observed_at + timedelta(seconds=3),
                          media_time_seconds=12)
        def reply(*args, **kwargs):
            for observation in (paused, later_pause, resumed):
                service.update(observation)
            return {'text': 'answer'}
        service = CompanionQuestionService(reply)
        service.update(first)
        binding = service.bind_question()
        self.assertEqual(service.ask('why', binding=binding)['text'], 'answer')
        self.assertEqual(service._histories['companion'][0]['media_time_seconds'], 10)
        self.assertFalse(service._normal_video_progress(paused,
            replace(later_pause, media_time_seconds=12)))

    def test_bound_video_question_excludes_discussion_from_later_frames(self):
        prompts = []
        service = CompanionQuestionService(lambda prompt, **kwargs:
            prompts.append(prompt) or {'text': 'answer'})
        first = self.playing_video()
        service.update(first)
        binding = service.bind_question()
        service.update(replace(first, observed_at=first.observed_at + timedelta(seconds=1),
                               media_time_seconds=11, text='next formula'))
        service.ask('FUTURE_FRAME_QUESTION')
        service.ask('earlier speech', binding=binding)
        self.assertNotIn('FUTURE_FRAME_QUESTION', prompts[-1])
        self.assertIn('[媒体时间] 10', prompts[-1])
        self.assertEqual([item['media_time_seconds'] for item in service._histories['companion']], [10, 11])

    def test_video_discussion_budget_includes_timestamp_provenance_and_expires(self):
        now = [0]
        prompts = []
        service = CompanionQuestionService(lambda prompt, **kwargs:
            prompts.append(prompt) or {'text': 'a' * 300}, history_ttl_seconds=10,
            max_history_chars=256, clock=lambda: now[0])
        first = self.playing_video()
        service.update(first)
        service.ask('q' * 300)
        for tick in range(1, 5):
            service.update(replace(first, observed_at=first.observed_at + timedelta(seconds=tick),
                                   media_time_seconds=10 + tick, text=f'frame {tick}'))
            service.ask('q' * 300)
            self.assertLessEqual(sum(len(service._history_entry(item))
                for item in service._histories['companion']), 256)
        now[0] = 11
        self.assertEqual(service.ask('after expiry')['context_turns'], 1)
        self.assertNotIn('前序讨论', prompts[-1])

    def test_danmaku_refresh_preserves_question_binding_and_stays_out_of_prompt(self):
        calls = []
        service = CompanionQuestionService(lambda prompt, **kw:
            (calls.append(prompt) or {'text': 'fixture'}))
        first = ObservationBundle.now(source='video-subtitle', target='lesson', valid=True,
            text='course formula', metadata={'danmaku': [{'text': 'OLD_COMMENT'}]})
        service.update(first)
        binding = service.bind_question()
        service.update(replace(first, observed_at=first.observed_at + timedelta(seconds=1),
                               metadata={'danmaku': [{'text': 'NEW_COMMENT'}]}))
        result = service.ask('explain', binding=binding)
        self.assertNotEqual(result.get('status'), 'stale_response')
        self.assertIn('course formula', calls[0])
        self.assertNotIn('OLD_COMMENT', calls[0])
        self.assertNotIn('NEW_COMMENT', calls[0])

    def test_text_model_gets_ocr_without_image_and_rejects_chrome_only(self):
        calls=[]
        service=CompanionQuestionService(lambda prompt, **kw: calls.append((prompt,kw)) or {'text':'fixture'})
        observation=ObservationBundle.now(source='window-visual',target='reader',valid=True,
            text='OCR正文',image={'media_type':'image/jpeg','data_base64':'fixture'},
            metadata={'text_status':'ocr_available'})
        service.update(observation)
        service.ask('解释',include_images=False)
        self.assertIsNone(calls[0][1]['images'])
        self.assertIn('未附图',calls[0][0])
        service.update(replace(observation,text='下一页',metadata={'text_status':'navigation_only'}))
        self.assertEqual(service.ask('解释',include_images=False)['status'],'insufficient_context')
        self.assertEqual(len(calls),1)

    def test_text_only_voice_policy_applies_to_proactive_too(self):
        calls=[]
        service=CompanionQuestionService(lambda prompt, **kw: calls.append((prompt,kw)) or {'text':'fixture'},
                                        include_images=False)
        service.update(ObservationBundle.now(source='window-visual',target='reader',valid=True,
            text='OCR正文',image={'media_type':'image/jpeg','data_base64':'fixture'}))
        service.ask('解释');service.proactive()
        self.assertTrue(all(call[1]['images'] is None for call in calls))
        service.update(ObservationBundle.now(source='window-visual',target='reader',valid=True,
            metadata={'text_status':'navigation_only'},text='下一页'))
        self.assertEqual(service.proactive()['status'],'insufficient_context')
        self.assertEqual(len(calls),2)

    def test_navigation_only_context_is_explicit_in_questions_and_proactive(self):
        prompts=[]
        service=CompanionQuestionService(lambda prompt, **kw: prompts.append(prompt) or {'text':'fixture'})
        service.update(ObservationBundle.now(source='window-visual',target='reader',valid=True,
            text='1.2 章节',metadata={'text_status':'navigation_only'}))
        service.ask('这页讲什么')
        service.proactive()
        for prompt in prompts:
            self.assertIn('navigation_only',prompt)
            self.assertIn('导航',prompt)

    def test_learning_text_refresh_timestamp_does_not_cancel_reply(self):
        first=ObservationBundle.now(source='window-visual',target='lesson',valid=True,text='formula',
            metadata={'text_source':'document-visible','text_observed_at':'first','width':300})
        def reply(*args,**kwargs):
            service.update(replace(first,observed_at=first.observed_at+timedelta(seconds=1),
                metadata=dict(first.metadata,text_observed_at='refreshed')))
            return {'text':'answer'}
        service=CompanionQuestionService(reply)
        service.update(first)
        self.assertEqual(service.ask('explain')['text'],'answer')

    def test_identical_refresh_during_reply_keeps_answer_bound_to_question_time(self):
        first = webpage(target='lesson', text='same content')
        refreshed = replace(first, observed_at=first.observed_at + timedelta(seconds=2))
        def reply(*args, **kwargs):
            service.update(refreshed)
            return {'text': 'answer'}
        service = CompanionQuestionService(reply)
        service.update(first)
        answer = service.ask('explain')
        self.assertEqual(answer['text'], 'answer')
        self.assertEqual(answer['observation_at'], first.observed_at.isoformat())
        self.assertIs(service.latest, refreshed)
        self.assertEqual(answer['context_turns'], 1)

    def test_validity_or_location_change_invalidates_inflight_answer(self):
        first = ebook(target='reader', page_text='same content', page=1)
        for changes in ({'valid': False}, {'metadata': {'page': 2}},
                        {'media_time_seconds': 20}):
            with self.subTest(changes=changes):
                def reply(*args, **kwargs):
                    service.update(replace(first, **changes))
                    return {'text': 'old answer'}
                service = CompanionQuestionService(reply)
                service.update(first)
                self.assertEqual(service.ask('explain')['status'], 'stale_response')

    def test_visual_question_uses_bound_image_and_revoke_removes_it(self):
        calls = []
        service = CompanionQuestionService(lambda prompt, **kw: calls.append(kw) or {'text': 'answer'})
        image = {'media_type': 'image/jpeg', 'data_base64': 'fixture'}
        service.update(ObservationBundle.now(source='window-visual', target='lesson', valid=True, image=image))
        service.ask('解释图表')
        self.assertEqual(calls[0]['images'], [image])
        service.update(ObservationBundle.now(source='window-visual', target='lesson', valid=True,
            image={'media_type':'image/jpeg','data_base64':'changed'}))
        self.assertEqual(service.ask('新图')['context_turns'], 1)
        service.revoke()
        with self.assertRaises(RuntimeError): service.ask('继续')
    def test_lifecycle_requires_target_and_stops_observation(self):
        service = PerceptionService(lambda target: ObservationBundle.now(source='window', target=target, valid=True, text='lesson'))
        with self.assertRaises(RuntimeError): service.start()
        self.assertEqual(service.select_target('browser:lesson')['status'], 'selected')
        self.assertEqual(service.start()['status'], 'running')
        self.assertEqual(service.observe().text, 'lesson')
        self.assertEqual(service.pause()['status'], 'paused')
        with self.assertRaises(RuntimeError): service.observe()
        self.assertEqual(service.stop()['status'], 'stopped')

    def test_bundle_requires_timezone_and_valid_metadata(self):
        with self.assertRaises(ValueError):
            ObservationBundle.now(source='', target='x', valid=True)
        with self.assertRaises(ValueError):
            ObservationBundle.now(source='window', target='x', valid=True, media_time_seconds=-1)
        with self.assertRaises(ValueError):
            ObservationBundle.now(source='window', target='x', valid=True, media_time_seconds=True)

    def test_question_binds_latest_observation_as_reference_data(self):
        calls = []
        service = CompanionQuestionService(lambda prompt, **kwargs: calls.append((prompt, kwargs)) or {'text': 'answer'})
        service.update(ObservationBundle.now(source='web', target='lesson', valid=True, text='二次函数顶点在此处'))
        result = service.ask('为什么？')
        self.assertEqual(result['observation_source'], 'web')
        self.assertIn('[参考内容开始]', calls[0][0])
        self.assertIn('二次函数顶点', calls[0][0])

    def test_invalid_observation_does_not_call_model(self):
        called = []
        service = CompanionQuestionService(lambda *args, **kwargs: called.append(1))
        service.update(ObservationBundle.now(source='window', target='x', valid=False))
        self.assertEqual(service.ask('解释'), {'status': 'insufficient_context', 'reason': 'observation is not valid', 'observed_at': service.latest.observed_at.isoformat()})
        self.assertEqual(called, [])

    def test_revoke_discards_observation_and_discussion(self):
        service = CompanionQuestionService(lambda *a, **kw: {'text': 'answer'})
        service.update(webpage(target='lesson', text='正文'))
        service.ask('解释', session_id='study')
        self.assertEqual(service.revoke(), {'status': 'revoked', 'had_context': True})
        with self.assertRaisesRegex(RuntimeError, 'consent'):
            service.ask('继续', session_id='study')

    def test_question_keeps_page_and_chapter_provenance(self):
        calls = []
        service = CompanionQuestionService(lambda prompt, **kw: calls.append(prompt) or {'text': 'answer'})
        service.update(ebook(target='reader', page_text='二次函数', page=3, chapter='第一章'))
        service.ask('这里是什么意思？')
        self.assertIn('"page": 3', calls[0])
        self.assertIn('第一章', calls[0])

    def test_old_observation_cannot_replace_current_target(self):
        service = CompanionQuestionService(lambda *a, **kw: {'text': 'answer'})
        current = webpage(target='new-tab', text='current')
        service.update(current)
        old = ObservationBundle(current.observed_at.replace(year=2020), 'web', 'old-tab', True, 'old')
        self.assertEqual(service.update(old)['status'], 'rejected')
        self.assertIs(service.latest, current)

    def test_changed_content_discards_in_flight_answer(self):
        def reply(*a, **kw):
            service.update(webpage(target='chapter-two', text='new chapter'))
            return {'text': 'answer about old chapter'}
        service = CompanionQuestionService(reply)
        service.update(webpage(target='chapter-one', text='old chapter'))
        result = service.ask('解释这段')
        self.assertEqual(result['status'], 'stale_response')
        self.assertNotIn('text', result)

    def test_short_term_discussion_is_bound_to_current_observation(self):
        calls = []
        service = CompanionQuestionService(
            lambda prompt, **kw: calls.append(prompt) or {'text': f'答复{len(calls)}'})
        service.update(webpage(target='chapter-one', text='函数教程'))
        first = service.ask('函数是什么？', session_id='study')
        second = service.ask('那它和变化率有什么关系？', session_id='study')
        self.assertEqual(first['context_turns'], 1)
        self.assertEqual(second['context_turns'], 2)
        self.assertIn('函数是什么？', calls[1])
        service.update(webpage(target='chapter-two', text='积分教程'))
        third = service.ask('这页讲什么？', session_id='study')
        self.assertEqual(third['context_turns'], 1)
        self.assertNotIn('函数是什么？', calls[2])

    def test_content_adapters_and_late_result_rejection(self):
        web = webpage(target='tab-1', text='  第一   段  ', title='教程')
        self.assertEqual(web.source, 'web-visible')
        clip = video(target='player-1', subtitles='字幕一', media_time_seconds=12.5)
        self.assertEqual(clip.media_time_seconds, 12.5)
        book = ebook(target='reader-1', page_text='正文', page=3, chapter='第一章')
        self.assertEqual(book.metadata['page'], 3)
        tracker = ContentChangeTracker()
        self.assertTrue(tracker.accept(web)['changed'])
        self.assertFalse(tracker.accept(web)['changed'])
        late = ObservationBundle(web.observed_at.replace(year=2020), web.source, web.target, True, '旧内容')
        self.assertFalse(tracker.accept(late)['accepted'])

    def test_webvtt_selects_current_cue_only(self):
        text, rows = cues('''WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n第一句 <b>字幕</b>\n\n00:00:10.000 --> 00:00:12.000\n第二句''', at_seconds=2)
        self.assertEqual(text, '第一句 字幕')
        self.assertEqual(rows[0]['start'], 1)
        self.assertEqual(cues('WEBVTT\n\n00:00:10.000 --> 00:00:12.000\n第二句', at_seconds=2)[0], '')

    def test_webvtt_ignores_cue_identifier_and_settings(self):
        text, rows = cues('''WEBVTT\n\ncue-7\n00:01.000 --> 00:03.000 position:50% line:80%\n带编号字幕''', at_seconds=2)
        self.assertEqual(text, '带编号字幕')
        self.assertEqual(rows[0]['start'], 1)

    def test_revoke_during_reply_cannot_restore_history(self):
        service = None
        def reply(*args, **kwargs):
            service.revoke()
            return {'text': 'late'}
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='正文'))
        result = service.ask('解释', session_id='study')
        self.assertEqual(result['status'], 'stale_response')
        self.assertEqual(service.revoke()['had_context'], False)

    def test_late_capture_after_revoke_is_rejected(self):
        service = CompanionQuestionService(lambda *a, **kw: {'text': 'answer'})
        token = service.collection_token()
        service.revoke()
        result = service.update(webpage(target='lesson', text='late'), collection_token=token)
        self.assertEqual(result['status'], 'rejected')
        self.assertIsNone(service.latest)

    def test_history_expires_and_session_count_is_bounded(self):
        now = [0]
        prompts = []
        service = CompanionQuestionService(lambda prompt, **kw: prompts.append(prompt) or {'text': 'answer'},
            history_ttl_seconds=10, max_history_sessions=2, clock=lambda: now[0])
        service.update(webpage(target='lesson', text='lesson'))
        service.ask('old question', session_id='a')
        now[0] = 1
        service.ask('second', session_id='b')
        now[0] = 2
        service.ask('third', session_id='c')
        service.ask('new question', session_id='a')
        self.assertNotIn('old question', prompts[-1])
        now[0] = 13
        result = service.ask('after expiry', session_id='a')
        self.assertEqual(result['context_turns'], 1)
        self.assertNotIn('new question', prompts[-1])

    def test_history_character_budget_bounds_large_replies(self):
        prompts = []
        service = CompanionQuestionService(lambda prompt, **kw: prompts.append(prompt) or {'text': 'A' * 5000},
            max_history_chars=256)
        service.update(webpage(target='lesson', text='lesson'))
        service.ask('Q' * 5000)
        result = service.ask('follow up')
        self.assertEqual(result['context_turns'], 1)
        self.assertNotIn('A' * 129, prompts[-1])
        self.assertNotIn('Q' * 129, prompts[-1])

    def test_proactive_discussion_is_ephemeral_and_stale_safe(self):
        calls = []
        service = None
        def reply(prompt, **kwargs):
            calls.append(prompt)
            service.update(webpage(target='new', text='new content'))
            return {'text': '提示'}
        service = CompanionQuestionService(reply)
        service.update(webpage(target='old', text='old content'))
        result = service.proactive()
        self.assertEqual(result['status'], 'stale_response')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('提示', service._histories)


if __name__ == '__main__':
    unittest.main()
