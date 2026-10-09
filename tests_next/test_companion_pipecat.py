"""Run with the isolated voice environment to exercise actual Pipecat workers."""
import asyncio
import importlib.util
import unittest
import threading
from unittest.mock import patch
from types import SimpleNamespace


@unittest.skipUnless(importlib.util.find_spec('pipecat'), 'optional voice environment required')
class PipecatVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_sensevoice_preloads_on_owner_and_does_not_fallback(self):
        from extensions.companion.pipecat_voice import build_local_voice_worker
        async def provider(*args, **kwargs): return ''
        class ASR:
            owner = None
            def load_model(self): self.owner = threading.get_ident()
            async def __call__(self, *args, **kwargs): return 'question'
        asr = ASR()
        with patch('extensions.companion.audio_providers.SenseVoicePcmProvider', return_value=asr), \
             patch('extensions.companion.audio_providers.VoskPcmProvider') as vosk, \
             patch('extensions.companion.pipecat_voice.build_voice_worker', return_value=('worker','turn')) as build:
            result = build_local_voice_worker(model_path='fixture', approved=True,
                asr_provider='sherpa-onnx-sensevoice', answer=provider,
                speak=provider, stop_playback=provider)
            self.assertEqual(result, ('worker','turn'))
            self.assertEqual(asr.owner, threading.get_ident())
            self.assertEqual(build.call_args.kwargs['transcribe'], asr.__call__)
            vosk.assert_not_called()
        with patch('extensions.companion.audio_providers.SenseVoicePcmProvider') as sense, \
             patch('extensions.companion.audio_providers.VoskPcmProvider') as vosk:
            sense.return_value.load_model.side_effect = RuntimeError('model unavailable')
            with self.assertRaisesRegex(RuntimeError, 'model unavailable'):
                build_local_voice_worker(model_path='fixture', approved=True,
                    asr_provider='sherpa-onnx-sensevoice', answer=provider,
                    speak=provider, stop_playback=provider)
            vosk.assert_not_called()
            with self.assertRaises(ValueError):
                build_local_voice_worker(model_path='fixture', approved=True,
                    asr_provider='unsupported', answer=provider, speak=provider, stop_playback=provider)

    async def test_text_turn_cancels_playback_and_resumes_same_pipeline(self):
        from extensions.companion.pipecat_voice import build_voice_worker
        from pipecat.frames.frames import InputAudioRawFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
        from pipecat.workers.runner import WorkerRunner
        playing, cancelled, transcribed, text_interrupted = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
        stopped = []
        async def asr(audio, **kwargs): transcribed.set(); return 'next voice question'
        async def answer(text): return 'answer'
        async def speak(text):
            playing.set()
            try: await asyncio.Event().wait()
            finally: cancelled.set()
        async def stop(): stopped.append(True)
        def event(name, detail):
            if name == 'text_interrupted': text_interrupted.set()
        worker, turn = build_voice_worker(approved=True, transcribe=asr, answer=answer,
            speak=speak, stop_playback=stop, on_event=event)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        def utterance():
            return [VADUserStartedSpeakingFrame(),
                InputAudioRawFrame(audio=b'\0'*640, sample_rate=16000, num_channels=1),
                VADUserStoppedSpeakingFrame()]
        try:
            turn.start_discussion('Discuss this lesson')
            await asyncio.wait_for(playing.wait(), 3)
            await turn.begin_text_question()
            self.assertTrue(cancelled.is_set())
            self.assertTrue(stopped)
            self.assertFalse(running.done())
            await worker.queue_frame(InputAudioRawFrame(audio=b'\0'*640, sample_rate=16000, num_channels=1))
            self.assertTrue(await worker.flush_pipeline(timeout=1))
            self.assertFalse(transcribed.is_set())
            self.assertIsNone(turn.start_discussion('competing discussion'))
            # Speech supersedes text; the text HTTP finalizer must not clear
            # the already-started microphone utterance.
            await worker.queue_frame(VADUserStartedSpeakingFrame())
            await asyncio.wait_for(text_interrupted.wait(), 3)
            await turn.end_text_question()
            await worker.queue_frames(utterance()[1:])
            await asyncio.wait_for(transcribed.wait(), 3)
            self.assertFalse(running.done())
        finally:
            await worker.cancel()
            await asyncio.wait_for(running, 8)

    async def test_proactive_uses_same_player_and_user_interrupt_without_asr_or_history(self):
        from extensions.companion import CompanionQuestionService, webpage
        from extensions.companion.pipecat_voice import build_study_voice_worker
        from pipecat.frames.frames import VADUserStartedSpeakingFrame
        from pipecat.workers.runner import WorkerRunner
        playing, interrupted = asyncio.Event(), asyncio.Event()
        events = []
        class ASR:
            async def __call__(self, *args, **kwargs):
                raise AssertionError('proactive must not transcribe')
        def reply(prompt, on_delta, **kwargs):
            on_delta('discussion point.')
            return {'text':'discussion point.'}
        async def play(text): playing.set(); await asyncio.Event().wait()
        async def stop(): pass
        def event(name, detail):
            events.append(name)
            if name == 'user_started': interrupted.set()
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='diagram'))
        with patch('extensions.companion.audio_providers.VoskPcmProvider', return_value=ASR()):
            worker, turn = build_study_voice_worker(model_path='fixture', question_service=service,
                approved=True, play_segment=play, stop_playback=stop, on_event=event)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        try:
            self.assertIsNotNone(turn.start_discussion('Discuss this lesson'))
            await asyncio.wait_for(playing.wait(), 3)
            self.assertIsNone(turn.start_discussion('second discussion'))
            await worker.queue_frame(VADUserStartedSpeakingFrame())
            await asyncio.wait_for(interrupted.wait(), 3)
            self.assertIn('proactive_started', events)
            self.assertIn('interrupted', events)
            self.assertNotIn('transcribed', events)
            self.assertEqual(service._histories, {})
        finally:
            await worker.cancel()
            await asyncio.wait_for(running, 8)

    async def test_study_worker_streams_first_sentence_then_interrupts_model(self):
        from extensions.companion import CompanionQuestionService, webpage
        from extensions.companion.pipecat_voice import build_study_voice_worker
        from extensions.models.cancellation import _CURRENT
        from pipecat.frames.frames import (
            InputAudioRawFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
        )
        from pipecat.workers.runner import WorkerRunner
        playing, interrupted = asyncio.Event(), asyncio.Event()
        released, model_exited = threading.Event(), threading.Event()
        events, played, delta_threads = [], [], []
        def reply(prompt, *, on_delta, **kwargs):
            remove = _CURRENT.get().register(released.set)
            try:
                on_delta('first sentence.')
                if not released.wait(3): raise TimeoutError('model was not interrupted')
                return {'text': 'first sentence. late answer'}
            finally:
                remove()
                model_exited.set()
        class ASR:
            async def __call__(self, audio, *, sample_rate): return 'why'
        async def play(text):
            played.append(text)
            self.assertFalse(model_exited.is_set())
            playing.set()
            await asyncio.Event().wait()
        async def stop(): events.append('stopped')
        def event(name, detail):
            events.append(name)
            if name == 'user_started' and playing.is_set(): interrupted.set()
        service = CompanionQuestionService(reply)
        service.update(webpage(target='lesson', text='page one'))
        from extensions.companion import ObservationScheduler, PerceptionService
        now = [0.0]
        perception = PerceptionService(lambda target: service.latest)
        perception.select_target('lesson'); perception.start()
        proactive = []
        scheduler = ObservationScheduler(perception, on_proactive=proactive.append,
            clock=lambda:now[0], playback_gap=2)
        with patch('extensions.companion.audio_providers.VoskPcmProvider', return_value=ASR()):
            worker, processor = build_study_voice_worker(model_path='fixture-only',
                question_service=service, approved=True, play_segment=play, stop_playback=stop,
                on_event=event, on_delta=lambda packet: delta_threads.append(threading.get_ident()),
                observation_scheduler=scheduler)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        try:
            await worker.queue_frames([VADUserStartedSpeakingFrame(),
                InputAudioRawFrame(audio=b'\0' * 1024, sample_rate=16000, num_channels=1),
                VADUserStoppedSpeakingFrame()])
            await asyncio.wait_for(playing.wait(), 5)
            now[0] = 10
            self.assertFalse(scheduler.tick()['proactive'])
            await worker.queue_frame(VADUserStartedSpeakingFrame())
            await asyncio.wait_for(interrupted.wait(), 5)
            self.assertTrue(model_exited.is_set())
            self.assertEqual(played, ['first sentence.'])
            self.assertEqual(delta_threads, [threading.get_ident()])
            self.assertIn('playback_started', events)
            self.assertNotIn('playback_ended', events)
            self.assertIn('interrupted', events)
            self.assertIsNone(scheduler._playback_token)
            self.assertFalse(scheduler.tick()['proactive'])
            now[0] = 16
            self.assertTrue(scheduler.tick()['proactive'])
            self.assertEqual(service._histories, {})
            self.assertEqual(service._active_requests, set())
        finally:
            released.set()
            await worker.cancel()
            await asyncio.wait_for(running, 8)
        self.assertIsNone(processor._turn_task)

    async def test_native_worker_turn_and_interrupt_stop_playback(self):
        from extensions.companion.pipecat_voice import build_voice_worker
        from pipecat.frames.frames import (
            InputAudioRawFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
        )
        from pipecat.workers.runner import WorkerRunner
        speaking, cancelled, next_turn = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events, captures = [], []
        async def transcribe(audio, *, sample_rate):
            captures.append((len(audio), sample_rate))
            return 'question'
        async def answer(text): return 'answer'
        async def speak(text):
            speaking.set()
            try: await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        async def stop(): events.append('player_stopped')
        def event(name, detail):
            events.append(name)
            if name == 'user_started' and speaking.is_set(): next_turn.set()
        worker, processor = build_voice_worker(approved=True, transcribe=transcribe,
            answer=answer, speak=speak, stop_playback=stop, on_event=event)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        try:
            await worker.queue_frames([
                VADUserStartedSpeakingFrame(),
                InputAudioRawFrame(audio=b'\0' * 1024, sample_rate=16000, num_channels=1),
                VADUserStoppedSpeakingFrame(),
            ])
            await asyncio.wait_for(speaking.wait(), 5)
            await worker.queue_frame(VADUserStartedSpeakingFrame())
            await asyncio.wait_for(next_turn.wait(), 5)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(captures, [(1024, 16000)])
            self.assertNotIn('playback_ended', events)
            self.assertEqual(events[-3:], ['player_stopped', 'interrupted', 'user_started'])
        finally:
            await worker.cancel()
            await asyncio.wait_for(running, 8)
        self.assertFalse(processor._audio)
        self.assertIsNone(processor._turn_task)

    async def test_consent_and_sync_provider_rejected(self):
        from extensions.companion.pipecat_voice import build_voice_worker, CompanionTurnProcessor
        async def provider(*args, **kwargs): pass
        with self.assertRaises(PermissionError):
            build_voice_worker(transcribe=provider, answer=provider, speak=provider,
                               stop_playback=provider)
        with self.assertRaises(TypeError):
            CompanionTurnProcessor(transcribe=lambda audio: 'text', answer=provider,
                                   speak=provider, stop_playback=provider)

    async def test_microphone_stop_closes_stream_and_native_worker(self):
        from extensions.companion.pipecat_voice import build_voice_worker, run_microphone
        stopped = asyncio.Event()
        opened, closed = [], []
        async def provider(*args, **kwargs): return ''
        class Stream:
            def __init__(self, **options): self.options = options
            def __enter__(self):
                opened.append(self.options)
                self.options['callback'](b'\0' * 640, 320, None, False)
                asyncio.get_running_loop().call_later(0.1, stopped.set)
                return self
            def __exit__(self, *args): closed.append(True)
        sd = SimpleNamespace(check_input_settings=lambda **options: None, RawInputStream=Stream)
        worker, processor = build_voice_worker(approved=True, transcribe=provider,
            answer=provider, speak=provider, stop_playback=provider)
        with patch.dict('sys.modules', sounddevice=sd):
            await asyncio.wait_for(run_microphone(worker, approved=True, device=7,
                                                  stop_event=stopped), 5)
        self.assertEqual(opened[0]['device'], 7)
        self.assertEqual(closed, [True])
        self.assertTrue(processor._closed)
        self.assertFalse(processor._audio)
