"""Optional Pipecat adapter; microphone PCM never enters application audio routes."""
import asyncio
from collections import deque
import inspect
import queue

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    CancelFrame, EndFrame, InputAudioRawFrame, InterruptionFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class CompanionTurnProcessor(FrameProcessor):
    """Bridge VAD turns to cancellable async providers, with bounded PCM lifetime.

    All providers must be asynchronous and propagate cancellation. ``stop_playback``
    must stop and clear the actual player's queue before returning; cancelling a
    coroutine alone does not prove that a hardware player stopped.
    """

    def __init__(self, *, transcribe, answer, speak, stop_playback,
                 on_event=None, sample_rate=16000, max_seconds=30,
                 answer_and_speak=None, **kwargs):
        super().__init__(**kwargs)
        for provider in (transcribe, answer, speak, stop_playback):
            if not inspect.iscoroutinefunction(provider):
                raise TypeError('voice providers must be async and cancellable')
        if sample_rate != 16000 or type(max_seconds) is not int or not 1 <= max_seconds <= 120:
            raise ValueError('16kHz mono PCM and bounded turn duration required')
        self.transcribe, self.answer, self.speak = transcribe, answer, speak
        self.stop_playback = stop_playback
        if answer_and_speak is not None and not inspect.iscoroutinefunction(answer_and_speak):
            raise TypeError('streaming response provider must be async')
        self.answer_and_speak = answer_and_speak
        self.on_event = on_event or (lambda event, detail: None)
        self.sample_rate = sample_rate
        self._limit = max_seconds * sample_rate * 2
        self._preroll = deque()
        self._preroll_bytes = 0
        self._audio = bytearray()
        self._speaking = False
        self._epoch = 0
        self._turn_task = None
        self._closed = False
        self._text_question = False
        self._turn_lock = asyncio.Lock()

    async def begin_text_question(self):
        async with self._turn_lock:
            self._text_question = True
            self._clear_audio()
            await self._interrupt()

    async def end_text_question(self):
        async with self._turn_lock:
            if self._text_question:
                self._clear_audio()
                self._text_question = False

    async def _event(self, name, **detail):
        result = self.on_event(name, {'turn': self._epoch, **detail})
        if inspect.isawaitable(result):
            await result

    async def _interrupt(self):
        previous_epoch = self._epoch
        self._epoch += 1
        task, self._turn_task = self._turn_task, None
        try:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            await self.stop_playback()
            if task is not None:
                await self._event('interrupted', turn=previous_epoch)

    def _clear_audio(self):
        self._audio.clear()
        self._preroll.clear()
        self._preroll_bytes = 0
        self._speaking = False

    async def process_frame(self, frame, direction):
        async with self._turn_lock:
            await self._process_turn_frame(frame, direction)

    async def _process_turn_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, (EndFrame, CancelFrame)):
            self._closed = True
            self._clear_audio()
            await self._interrupt()
        elif isinstance(frame, InterruptionFrame):
            self._clear_audio()
            await self._interrupt()
        elif isinstance(frame, VADUserStartedSpeakingFrame) and not self._closed:
            if self._text_question:
                self._text_question = False
                await self._event('text_interrupted')
            await self._interrupt()
            self._audio = bytearray(b''.join(self._preroll))
            self._preroll.clear()
            self._preroll_bytes = 0
            self._speaking = True
            await self._event('user_started')
        elif isinstance(frame, InputAudioRawFrame) and not self._closed:
            if frame.sample_rate != self.sample_rate or frame.num_channels != 1 or len(frame.audio) % 2:
                self._clear_audio()
                await self._interrupt()
                await self._event('error', reason='invalid microphone PCM format')
            elif self._speaking:
                if len(self._audio) + len(frame.audio) > self._limit:
                    self._clear_audio()
                    await self._interrupt()
                    await self._event('error', reason='microphone turn exceeded duration limit')
                else:
                    self._audio.extend(frame.audio)
            else:
                self._preroll.append(bytes(frame.audio))
                self._preroll_bytes += len(frame.audio)
                while self._preroll and self._preroll_bytes > self.sample_rate:
                    self._preroll_bytes -= len(self._preroll.popleft())
        elif isinstance(frame, VADUserStoppedSpeakingFrame) and self._speaking:
            audio = bytes(self._audio)
            self._clear_audio()
            if audio:
                self._turn_task = asyncio.create_task(self._respond(audio, self._epoch))
        # Raw PCM terminates here: it must not accidentally reach logs or context.
        if not isinstance(frame, InputAudioRawFrame):
            await self.push_frame(frame, direction)

    @property
    def busy(self):
        return self._closed or self._text_question or self._speaking or (self._turn_task is not None and not self._turn_task.done())

    def start_discussion(self, prompt):
        """Use the same cancellable turn/player as user questions."""
        if self.busy:
            return None
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 500:
            raise ValueError('bounded discussion prompt required')
        self._epoch += 1
        self._turn_task = asyncio.create_task(self._respond(None, self._epoch, text=prompt))
        return self._epoch

    async def _respond(self, audio, epoch, *, text=None):
        try:
            proactive = text is not None
            if proactive:
                await self._event('proactive_started')
            else:
                text = await self.transcribe(audio, sample_rate=self.sample_rate)
            del audio
            if epoch != self._epoch or self._closed:
                return
            if not isinstance(text, str) or not text.strip():
                await self._event('empty_transcript')
                return
            if not proactive:
                await self._event('transcribed', text=text)
            if self.answer_and_speak is not None:
                await self.answer_and_speak(text, self._event)
                return
            response = await self.answer(text)
            if epoch != self._epoch or self._closed:
                return
            if not isinstance(response, str) or not response.strip():
                raise ValueError('valid companion response required')
            await self._event('playback_started')
            if epoch != self._epoch or self._closed:
                return
            # On this event loop there is no await between the epoch check and
            # entering speak. Interruption cancels speak and then clears playback.
            await self.speak(response)
            if epoch == self._epoch and not self._closed:
                await self._event('playback_ended')
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if epoch == self._epoch and not self._closed:
                await self.stop_playback()
                await self._event('error', reason=type(error).__name__)

    async def cleanup(self):
        self._closed = True
        self._clear_audio()
        try:
            await self._interrupt()
        finally:
            await super().cleanup()


def build_voice_worker(*, approved=False, transcribe, answer, speak, stop_playback,
                       on_event=None, answer_and_speak=None):
    """Build the actual native VAD pipeline; host supplies authorized mic frames."""
    if approved is not True:
        raise PermissionError('explicit microphone consent required')
    turn = CompanionTurnProcessor(transcribe=transcribe, answer=answer, speak=speak,
                                  stop_playback=stop_playback, on_event=on_event,
                                  answer_and_speak=answer_and_speak)
    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(
        sample_rate=16000, params=VADParams(stop_secs=0.5)))
    worker = PipelineWorker(Pipeline([vad, turn]),
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=16000),
        enable_rtvi=False, enable_turn_tracking=False, idle_timeout_secs=None)
    return worker, turn


async def run_microphone(worker, *, approved=False, device=None, stop_event=None, on_started=None):
    """Feed authorized sounddevice PCM with a one-second bounded memory queue.

    The device must accept 16kHz mono; no implicit device or rate fallback. Device
    overflow aborts the session rather than transcribing a silently truncated turn.
    The host sets stop_event on pause/revoke, and retains the task until it exits.
    """
    if approved is not True:
        raise PermissionError('explicit microphone consent required')
    import sounddevice as sd
    from pipecat.workers.runner import WorkerRunner
    sd.check_input_settings(device=device, channels=1, samplerate=16000, dtype='int16')
    chunks = queue.Queue(maxsize=50)
    failures = queue.Queue(maxsize=1)
    stop_event = stop_event or asyncio.Event()

    def callback(data, frames, timing, status):
        try:
            if status:
                raise RuntimeError('microphone input overflow or device error')
            chunks.put_nowait(bytes(data))
        except (RuntimeError, queue.Full):
            try: failures.put_nowait('microphone queue overflow or device error')
            except queue.Full: pass

    def next_chunk():
        try: return chunks.get(timeout=0.1)
        except queue.Empty: return None

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    try:
        with sd.RawInputStream(device=device, channels=1, samplerate=16000,
                               dtype='int16', blocksize=320, callback=callback):
            if on_started is not None:
                result = on_started()
                if inspect.isawaitable(result):
                    await result
            while not stop_event.is_set() and not running.done():
                if not failures.empty():
                    raise RuntimeError(failures.get_nowait())
                audio = await asyncio.to_thread(next_chunk)
                if audio is not None and not stop_event.is_set():
                    await worker.queue_frame(InputAudioRawFrame(
                        audio=audio, sample_rate=16000, num_channels=1))
                    if not await asyncio.wait_for(worker.flush_pipeline(timeout=0.5), 0.5):
                        raise RuntimeError('microphone pipeline stopped consuming audio')
    finally:
        await worker.cancel(reason='microphone stopped')
        await running
        while not chunks.empty(): chunks.get_nowait()


def build_local_voice_worker(*, model_path, approved=False, answer, speak,
                             stop_playback, on_event=None, answer_and_speak=None,
                             asr_provider='vosk'):
    """Use the explicitly selected local ASR; never fall back on load failure."""
    if approved is not True:
        raise PermissionError('explicit microphone consent required')
    from extensions.companion.audio_providers import VoskPcmProvider, SenseVoicePcmProvider
    if asr_provider == 'vosk':
        asr = VoskPcmProvider(model_path)
    elif asr_provider == 'sherpa-onnx-sensevoice':
        asr = SenseVoicePcmProvider(model_path)
        # Load native numeric dependencies on the owner thread before recording.
        asr.load_model()
    else:
        raise ValueError('unsupported microphone ASR provider')
    return build_voice_worker(approved=True, transcribe=asr.__call__, answer=answer,
                             speak=speak, stop_playback=stop_playback, on_event=on_event,
                             answer_and_speak=answer_and_speak)


def build_study_voice_worker(*, model_path, question_service, approved=False,
                             play_segment, stop_playback, on_event=None, on_delta=None,
                             max_speech_chars=180, observation_scheduler=None,
                             asr_provider='vosk'):
    """Connect local ASR and existing bound/cancellable screen question service."""
    from extensions.companion.voice_answer import VoiceQuestionProvider
    from extensions.companion.segmented_playback import SegmentedPlayback
    answer = VoiceQuestionProvider(question_service, on_delta=on_delta)
    speak = SegmentedPlayback(play_segment, stop_playback, max_chars=max_speech_chars,
                              on_event=on_event)
    async def event(name, detail):
        answer.voice_event(name, detail)
        if observation_scheduler is not None:
            observation_scheduler.voice_event(name, detail.get('turn'))
        if on_event is not None and name not in ('segment_started', 'segment_ended'):
            result = on_event(name, detail)
            if inspect.isawaitable(result):
                await result
    async def answer_and_speak(text, emit):
        async def started():
            await emit('playback_started')
        await answer.answer_and_play(text, speak, on_start=started)
        await emit('playback_ended')
    return build_local_voice_worker(model_path=model_path, approved=approved,
        asr_provider=asr_provider,
        answer=answer.answer, speak=speak.__call__, stop_playback=speak.cancel, on_event=event,
        answer_and_speak=answer_and_speak)


def build_sapi_study_worker(*, model_path, question_service, playback, role_id,
                            approved=False, on_event=None, on_delta=None,
                            max_speech_chars=180, observation_scheduler=None,
                            asr_provider='vosk'):
    """Use the existing SpeechPlayback owner with the segmented study worker."""
    from extensions.companion.sapi_playback import SapiPlaybackProvider
    sapi = SapiPlaybackProvider(playback, role_id)
    return build_study_voice_worker(model_path=model_path, question_service=question_service,
        asr_provider=asr_provider,
        approved=approved, play_segment=sapi.play_segment, stop_playback=sapi.stop,
        on_event=on_event, on_delta=on_delta, max_speech_chars=max_speech_chars,
        observation_scheduler=observation_scheduler)
