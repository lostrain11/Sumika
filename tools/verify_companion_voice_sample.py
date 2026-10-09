"""Actual prerecorded VAD/ASR/study pipeline, without microphone or speaker use.

The reply is an explicit local fixture. SAPI writes generated speech to files;
the consumer holds its first segment to exercise second-speech cancellation.
This verifies pipeline integration, not a hardware player's stop or model quality.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import threading
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def verify(model, sample, output, voice):
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level='WARNING')
    from extensions.companion import CompanionQuestionService, webpage
    from extensions.companion.pipecat_voice import build_study_voice_worker
    from extensions.models.cancellation import _CURRENT
    from extensions.roles.voice import synthesize
    from pipecat.frames.frames import InputAudioRawFrame
    from pipecat.workers.runner import WorkerRunner

    with wave.open(str(sample), 'rb') as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth(),
                source.getcomptype()) != (16000, 1, 2, 'NONE'):
            raise ValueError('16kHz mono PCM16 sample required')
        audio = source.readframes(16000 * 30 + 1)
        if not audio or len(audio) > 16000 * 30 * 2:
            raise ValueError('nonempty sample up to 30 seconds required')
    began = time.perf_counter()
    events, prompts, segments = [], [], []
    first_segment = asyncio.Event()
    completed = asyncio.Event()
    model_cancelled = threading.Event()
    counts = {'replies':0, 'stops':0}

    def reply(prompt, *, on_delta, **kwargs):
        counts['replies'] += 1
        prompts.append(prompt)
        if counts['replies'] == 1:
            release = threading.Event()
            unregister = _CURRENT.get().register(release.set)
            try:
                on_delta('当前教程说明导数代表变化率。')
                if not release.wait(15):
                    raise TimeoutError('second speech did not cancel fixture model')
                model_cancelled.set()
                return {'text':'当前教程说明导数代表变化率。过期句子不应生成。'}
            finally:
                unregister()
        text = '我们继续讨论当前教程。请指出不理解的公式。'
        on_delta(text)
        return {'text':text}

    service = CompanionQuestionService(reply)
    service.update(webpage(target='owned-voice-lesson',
                           text='VOICE_LESSON_MARKER：导数表示函数的瞬时变化率。'))

    def event(name, detail):
        events.append({'name':name, **detail, 'elapsed_ms':round((time.perf_counter()-began)*1000,1)})
        if name == 'playback_ended':
            completed.set()

    async def play(text):
        index = len(segments)
        path = output/f'synthesized-segment-{index}.wav'
        result = synthesize(text, path, voice_name=voice)
        with wave.open(str(path), 'rb') as file:
            frames = file.getnframes()
        segments.append({'text':text, 'path':str(path), 'frames':frames,
                         'provider':result['provider']})
        if index == 0:
            first_segment.set()
            await asyncio.Event().wait()  # Bounded by the interrupt/outer timeout.

    async def stop():
        counts['stops'] += 1

    worker, turn = build_study_voice_worker(model_path=model,
        asr_provider='sherpa-onnx-sensevoice', question_service=service,
        approved=True, play_segment=play, stop_playback=stop, on_event=event)
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    report = {'passed':False, 'scope':'Actual Silero VAD -> SenseVoice -> production '
        'bound QA with local reply fixture -> streamed segments -> real SAPI file '
        'synthesis; second prerecorded speech interrupts pending reply/consumer. '
        'No hardware microphone/speaker, external model, quality or P95 claim.',
        'sample':str(sample), 'sample_seconds':len(audio)/32000,
        'microphone_used':False, 'cloud_used':False, 'audible_playback':False}

    async def feed(pcm):
        # Match the actual microphone's 20ms packets; no injected VAD events.
        for offset in range(0, len(pcm), 640):
            chunk = pcm[offset:offset+640]
            await worker.queue_frame(InputAudioRawFrame(audio=chunk,
                                         sample_rate=16000, num_channels=1))
            if not await worker.flush_pipeline(timeout=1):
                raise RuntimeError('sample pipeline stopped consuming')
            await asyncio.sleep(len(chunk)/32000)

    try:
        await feed(b'\0'*32000 + audio + b'\0'*32000)
        await asyncio.wait_for(first_segment.wait(), 10)
        await feed(b'\0'*16000 + audio + b'\0'*32000)
        await asyncio.wait_for(completed.wait(), 10)
        transcripts = [entry['text'] for entry in events if entry['name']=='transcribed']
        report['checks'] = {
            'two_real_vad_starts':sum(entry['name']=='user_started' for entry in events) == 2,
            'two_nonempty_transcripts':len(transcripts) == 2 and all(transcripts),
            'two_bound_questions':len(prompts) == 2 and all('VOICE_LESSON_MARKER' in p for p in prompts),
            'pending_fixture_model_cancelled':model_cancelled.is_set(),
            'first_consumer_interrupted':any(entry['name']=='interrupted' for entry in events),
            'no_stale_segment':not any('过期句子' in entry['text'] for entry in segments),
            'actual_sapi_files':len(segments) >= 3 and all(entry['frames'] > 0 for entry in segments),
            'worker_alive_until_stop':not running.done(),
        }
        report['passed'] = all(report['checks'].values())
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {str(error)[:256]}'
    finally:
        await worker.cancel(reason='sample verifier finished')
        await asyncio.wait_for(running, 10)
        report.update(events=events, segments=segments, counts=counts,
                      turn_pcm_cleared=not turn._audio and not turn._preroll,
                      worker_stopped=running.done())
        report['passed'] = report['passed'] and report['turn_pcm_cleared'] and report['worker_stopped']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--sample', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--voice', default='Microsoft Huihui Desktop - Chinese (Simplified)')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = asyncio.run(verify(args.model.resolve(strict=True),
        args.sample.resolve(strict=True), output, args.voice))
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
