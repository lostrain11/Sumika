import asyncio
from dataclasses import replace
from datetime import timedelta
import threading
import unittest

from extensions.companion import CompanionQuestionService, ObservationBundle, webpage
from extensions.companion.voice_answer import VoiceQuestionProvider
from extensions.models.cancellation import _CURRENT


class VoiceAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_progress_during_recognition_and_speech_keeps_question_snapshot(self):
        from extensions.companion.segmented_playback import SegmentedPlayback
        first = ObservationBundle.now(source='video-frame', target='browser:lesson', valid=True,
            text='first formula', media_time_seconds=10,
            metadata={'url': 'https://www.bilibili.com/video/BVfixture', 'paused': False,
                'seeking': False, 'ended': False, 'playback_rate': 1,
                'media_identity': {'url': 'https://www.bilibili.com/video/BVfixture',
                    'document_started_at': 1234, 'source_fingerprint': 'abc',
                    'media_instance': 1, 'timeline_revision': 0}})
        prompts, played = [], []
        def reply(prompt, *, on_delta, **kwargs):
            prompts.append(prompt)
            on_delta('first.')
            return {'text': 'first. second.'}
        service = CompanionQuestionService(reply)
        service.update(first)
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        service.update(replace(first, observed_at=first.observed_at + timedelta(seconds=1),
                               media_time_seconds=11, text='recognition frame'))
        async def play(text):
            played.append(text)
            service.update(replace(first, observed_at=first.observed_at + timedelta(seconds=2),
                                   media_time_seconds=12, text='playback frame'))
        async def stop(): pass
        await asyncio.wait_for(provider.answer_and_play('why', SegmentedPlayback(play, stop)), 3)
        self.assertEqual(played, ['first.', 'second.'])
        self.assertIn(first.observed_at.isoformat(), prompts[0])
        self.assertIn('first formula', prompts[0])
        self.assertNotIn('recognition frame', prompts[0])
        self.assertEqual(service._histories['companion-voice'][0]['media_time_seconds'], 10)

    async def test_final_only_answer_uses_bounded_delta_packets(self):
        final = '学习内容' * 3000
        service = CompanionQuestionService(lambda *args, **kwargs: {'text': final})
        service.update(webpage(target='lesson', text='page one'))
        deltas = []
        provider = VoiceQuestionProvider(service, on_delta=deltas.append)
        provider.voice_event('user_started', {'turn': 4})
        chunks = [chunk async for chunk in provider.stream('why')]
        self.assertEqual(''.join(chunks), final)
        self.assertEqual(''.join(packet['text'] for packet in deltas), final)
        self.assertTrue(all(len(packet['text']) <= 4096 for packet in deltas))
        self.assertTrue(all(packet['turn'] == 4 for packet in deltas))

    async def test_oversized_final_answer_is_rejected_before_projection_or_playback(self):
        service = CompanionQuestionService(lambda *args, **kwargs: {'text': 'x' * 64001})
        service.update(webpage(target='lesson', text='page one'))
        deltas, played = [], []
        provider = VoiceQuestionProvider(service, on_delta=deltas.append)
        provider.begin_turn()
        with self.assertRaisesRegex(ValueError, 'buffer limit'):
            async for chunk in provider.stream('why'):
                played.append(chunk)
        self.assertEqual(deltas, [])
        self.assertEqual(played, [])

    async def test_stream_publishes_final_suffix_with_bound_turn(self):
        def reply(prompt, *, on_delta, **kwargs):
            on_delta('first')
            return {'text': 'first final'}
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='page one'))
        deltas = []
        provider = VoiceQuestionProvider(service, on_delta=deltas.append)
        provider.voice_event('user_started', {'turn': 7})
        chunks = [chunk async for chunk in provider.stream('why')]
        self.assertEqual(''.join(chunks), 'first final')
        self.assertEqual(''.join(packet['text'] for packet in deltas), 'first final')
        self.assertTrue(all(packet['turn'] == 7 for packet in deltas))
        self.assertTrue(all(packet['observation_target'] == 'lesson' for packet in deltas))

    async def test_revoke_after_model_completion_interrupts_playback(self):
        from extensions.companion.segmented_playback import SegmentedPlayback
        playing = asyncio.Event()
        stopped = []
        async def play(text):
            playing.set()
            await asyncio.Event().wait()
        async def stop(): stopped.append(True)
        service = CompanionQuestionService(lambda *args, **kwargs: {'text': 'completed answer.'})
        service.update(webpage(target='lesson', text='page one'))
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        player = SegmentedPlayback(play, stop)
        task = asyncio.create_task(provider.answer_and_play('why', player))
        await asyncio.wait_for(playing.wait(), 3)
        self.assertEqual(service._active_requests, set())
        self.assertTrue(service._binding_watchers)
        service.revoke()
        with self.assertRaisesRegex(RuntimeError, 'invalidated during playback'):
            await asyncio.wait_for(task, 3)
        self.assertTrue(stopped)
        self.assertIsNone(player._task)
        self.assertEqual(service._binding_watchers, set())
        self.assertEqual(service._histories, {})

    async def test_model_failure_interrupts_current_sentence(self):
        from extensions.companion.segmented_playback import SegmentedPlayback
        released, exited = threading.Event(), threading.Event()
        playing = asyncio.Event()
        stopped = []
        def reply(prompt, *, on_delta, **kwargs):
            try:
                on_delta('first sentence.')
                if not released.wait(3): raise TimeoutError('playback did not start')
                raise OSError('model disconnected during playback')
            finally:
                exited.set()
        async def play(text):
            playing.set()
            released.set()
            await asyncio.Event().wait()
        async def stop(): stopped.append(True)
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='page one'))
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        player = SegmentedPlayback(play, stop)
        try:
            with self.assertRaisesRegex(OSError, 'disconnected'):
                await asyncio.wait_for(provider.answer_and_play('why', player), 3)
        finally:
            released.set()
        self.assertTrue(playing.is_set())
        self.assertTrue(exited.is_set())
        self.assertTrue(stopped)
        self.assertIsNone(player._task)
        self.assertEqual(service._histories, {})

    async def test_sentence_plays_before_model_finishes(self):
        from extensions.companion.segmented_playback import SegmentedPlayback
        released = threading.Event()
        finished = threading.Event()
        played = []
        def reply(prompt, *, on_delta, **kwargs):
            on_delta('first.')
            if not released.wait(3):
                raise TimeoutError('speech waited for full answer')
            on_delta(' second.')
            finished.set()
            return {'text': 'first. second.'}
        async def play(text):
            played.append(text)
            if len(played) == 1:
                self.assertFalse(finished.is_set())
                released.set()
        async def stop(): pass
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='page one'))
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        try:
            await asyncio.wait_for(SegmentedPlayback(play, stop).stream(provider.stream('why')), 5)
        finally:
            released.set()
        self.assertEqual(played, ['first.', 'second.'])
        self.assertTrue(service._histories)

    async def test_cancel_with_full_delta_queue_stops_model_and_player(self):
        from extensions.companion.segmented_playback import SegmentedPlayback
        playing = asyncio.Event()
        exited = threading.Event()
        stopped, played = [], []
        def reply(prompt, *, on_delta, **kwargs):
            try:
                for _ in range(100):
                    on_delta('sentence.')
                return {'text': 'sentence.' * 100}
            finally:
                exited.set()
        async def play(text):
            played.append(text)
            playing.set()
            await asyncio.Event().wait()
        async def stop(): stopped.append(True)
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='page one'))
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        player = SegmentedPlayback(play, stop)
        task = asyncio.create_task(player.stream(provider.stream('why')))
        await asyncio.wait_for(playing.wait(), 3)
        # The producer is blocked behind the bounded queue while playback waits.
        await asyncio.sleep(0.1)
        self.assertFalse(exited.is_set())
        await asyncio.wait_for(player.cancel(), 3)
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(exited.is_set())
        self.assertEqual(len(played), 1)
        self.assertTrue(stopped)
        self.assertEqual(service._histories, {})
        self.assertEqual(service._active_requests, set())

    async def test_failed_stream_discards_unfinished_sentence(self):
        from extensions.companion.segmented_playback import SegmentedPlayback
        def reply(prompt, *, on_delta, **kwargs):
            on_delta('unfinished')
            raise OSError('connection lost')
        played, stopped = [], []
        async def play(text): played.append(text)
        async def stop(): stopped.append(True)
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='page one'))
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        with self.assertRaisesRegex(OSError, 'connection lost'):
            await SegmentedPlayback(play, stop).stream(provider.stream('why'))
        self.assertEqual(played, [])
        self.assertTrue(stopped)
        self.assertEqual(service._histories, {})

    async def test_binds_screen_before_recognition_with_same_content_refresh(self):
        service = CompanionQuestionService(lambda *args, **kwargs: {'text': 'answer'})
        first = webpage(target='lesson', text='page one')
        service.update(first)
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        service.update(replace(first, observed_at=first.observed_at + timedelta(seconds=2)))
        calls = []
        service._role_chat = lambda prompt, **kwargs: calls.append(prompt) or {'text': 'answer'}
        self.assertEqual(await provider.answer('why'), 'answer')
        self.assertIn(first.observed_at.isoformat(), calls[0])

    async def test_page_change_during_recognition_refuses_model(self):
        calls = []
        service = CompanionQuestionService(lambda *args, **kwargs: calls.append(1) or {'text': 'answer'})
        service.update(webpage(target='lesson', text='page one'))
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        service.update(webpage(target='lesson', text='page two'))
        with self.assertRaisesRegex(RuntimeError, 'invalidated'):
            await provider.answer('why')
        self.assertEqual(calls, [])

    async def test_interrupt_cancels_model_and_does_not_commit_history(self):
        entered, released = threading.Event(), threading.Event()
        def reply(prompt, **kwargs):
            token = _CURRENT.get()
            unregister = token.register(released.set)
            entered.set()
            try:
                if not released.wait(3): raise TimeoutError('cancel did not reach model')
                return {'text': 'late answer'}
            finally: unregister()
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='page one'))
        provider = VoiceQuestionProvider(service)
        provider.begin_turn()
        task = asyncio.create_task(provider.answer('why'))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        finally:
            released.set()
        self.assertEqual(service._histories, {})
        self.assertEqual(service._active_requests, set())
        self.assertIsNotNone(service.latest)

    async def test_stream_deltas_keep_bound_provenance(self):
        def reply(prompt, *, on_delta, **kwargs):
            on_delta('first')
            return {'text': 'first final'}
        service = CompanionQuestionService(reply)
        observation = webpage(target='lesson', text='page one')
        service.update(observation)
        deltas = []
        provider = VoiceQuestionProvider(service, on_delta=deltas.append)
        provider.begin_turn()
        self.assertEqual(await provider.answer('why'), 'first final')
        self.assertEqual(deltas[0]['observation_target'], 'lesson')
        self.assertEqual(deltas[0]['observation_at'], observation.observed_at.isoformat())
