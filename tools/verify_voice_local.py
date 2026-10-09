"""Local voice acceptance: Windows SAPI synthesis -> Vosk recognition.

No microphone and no cloud service are involved. Run it with the isolated
desktop environment interpreter, which carries pywin32 and vosk.
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extensions.roles.voice import synthesize, transcribe

SENTENCE = "今天排练很顺利，我们晚上九点看动画吧"
PUNCTUATION = "，。！？、,.!? "


def char_recall(expected, recognized):
    """How many characters of the sentence the recognizer actually recovered."""
    want = Counter(ch for ch in expected if ch not in PUNCTUATION)
    got = Counter(ch for ch in recognized if ch not in PUNCTUATION)
    matched = sum((want & got).values())
    total = sum(want.values())
    return round(matched / total, 4) if total else 0.0


def pick_voice(fallback="Microsoft Huihui Desktop - Chinese (Simplified)"):
    """Use the configured voice, else the first installed zh-CN SAPI voice."""
    import win32com.client
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    descriptions = [voice.GetDescription() for voice in speaker.GetVoices()]
    if fallback in descriptions:
        return fallback
    for description in descriptions:
        if "Chinese" in description:
            return description
    raise RuntimeError("no Chinese SAPI voice installed; no fallback to another language")


def study_sample(model, wav, provider, output):
    """Actual study factory/ASR on an existing sample; no devices or model API."""
    import asyncio
    import wave
    from extensions.companion.pipecat_voice import build_local_voice_worker
    with wave.open(str(wav), 'rb') as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise ValueError('study sample must be 16kHz mono PCM16')
        audio = source.readframes(16000 * 30 + 1)
        if len(audio) > 16000 * 30 * 2:
            raise ValueError('bounded study sample required')
    async def run():
        async def unused(*args, **kwargs):
            raise AssertionError('sample verifier must not answer or play')
        began = time.perf_counter()
        worker, turn = build_local_voice_worker(model_path=model, asr_provider=provider,
            approved=True, answer=unused, speak=unused, stop_playback=async_stop)
        load_ms = (time.perf_counter() - began) * 1000
        try:
            began = time.perf_counter()
            text = await turn.transcribe(audio, sample_rate=16000)
            return {'passed': bool(text.strip()), 'recognized_text': text,
                'load_ms': round(load_ms, 1), 'asr_ms': round((time.perf_counter()-began)*1000, 1)}
        finally:
            await turn.cleanup()
    async def async_stop(): pass
    report = asyncio.run(run())
    report.update(asr_provider=provider, model=str(model), sample=str(wav),
        audio_seconds=len(audio)/32000, microphone_used=False, cloud_used=False,
        scope='Actual Pipecat study factory-selected ASR on existing PCM sample; no live VAD, microphone, answer or TTS latency claim')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(2)


def file_sample(model, wav, provider, output):
    """Verify production desktop file dispatch, without microphone or playback."""
    import tempfile
    from extensions.capabilities import CapabilityStore
    from extensions.desktop.service import execute
    from ui.readiness import service_capabilities
    candidates = service_capabilities(Path(__file__).resolve().parents[1], asr_model=str(model))
    candidate = next((row for row in candidates if row['id']=='asr' and row['provider']==provider), None)
    if candidate is None:
        raise ValueError('requested ASR provider not discovered in selected voice runtime')
    with tempfile.TemporaryDirectory(prefix='sumika-file-asr-') as directory:
        store = CapabilityStore(Path(directory)/'capabilities.db')
        try:
            store.configure('asr', provider, options=candidate['options'])
            began = time.perf_counter()
            result = execute(store, {'capability':'asr', 'operation':'transcribe',
                                     'arguments':{'audio':str(wav)}})
            elapsed = (time.perf_counter()-began)*1000
        finally:
            store.close()
    report = dict(passed=bool(result['text'].strip()), recognized_text=result['text'],
                  asr_provider=result['provider'], model=str(model), sample=str(wav),
                  load_and_asr_ms=round(elapsed, 1), microphone_used=False, cloud_used=False,
                  scope='Actual configured desktop file-ASR dispatch; no live VAD, playback or accuracy/P95 claim')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=".sumika-next/voice-models/vosk-model-small-cn-0.22")
    parser.add_argument("--out", type=Path, default=Path("docs/project/voice-local-evidence.json"))
    parser.add_argument("--artifact", type=Path, default=Path(".sumika-next/voice-acceptance"))
    parser.add_argument("--threshold", type=float, default=0.6)
    sample = parser.add_mutually_exclusive_group()
    sample.add_argument('--study-wav', type=Path, help='Existing PCM sample through study factory; no devices')
    sample.add_argument('--file-wav', type=Path, help='Existing PCM sample through desktop file-ASR dispatch; no devices')
    parser.add_argument('--provider', choices=('vosk', 'sherpa-onnx-sensevoice'), default='vosk')
    args = parser.parse_args()
    model = Path(args.model).resolve()
    if args.study_wav:
        return study_sample(model, args.study_wav.resolve(strict=True), args.provider, args.out.resolve())
    if args.file_wav:
        return file_sample(model, args.file_wav.resolve(strict=True), args.provider, args.out.resolve())
    if args.provider != 'vosk':
        parser.error('SenseVoice acceptance requires --file-wav or --study-wav with a 16kHz sample')
    if not model.is_dir():
        raise SystemExit(f"Vosk model missing: {model}")
    voice = pick_voice()
    wav = args.artifact.resolve() / "sentence.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    if wav.exists():
        wav.unlink()
    started = time.perf_counter()
    synthesized = synthesize(SENTENCE, wav, voice_name=voice)
    synth_ms = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    recognized = transcribe(wav, model=str(model), provider=args.provider)
    asr_ms = round((time.perf_counter() - started) * 1000, 1)
    recall = char_recall(SENTENCE, recognized["text"])
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "chain": "Windows SAPI synthesis -> 16-bit PCM WAV -> Vosk recognition",
        "microphone_used": False,
        "cloud_used": False,
        "voice": synthesized["voice"],
        "tts_provider": synthesized["provider"],
        "asr_provider": recognized["provider"],
        "asr_model": recognized["model"],
        "expected_text": SENTENCE,
        "recognized_text": recognized["text"],
        "char_recall": recall,
        "threshold": args.threshold,
        "tts_ms": synth_ms,
        "asr_ms": asr_ms,
        "wav": str(wav),
        "wav_bytes": wav.stat().st_size,
        "passed": recall >= args.threshold,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({k: report[k] for k in ("voice", "asr_model", "recognized_text", "char_recall",
                                             "tts_ms", "asr_ms", "passed")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
