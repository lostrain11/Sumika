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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=".sumika-next/voice-models/vosk-model-small-cn-0.22")
    parser.add_argument("--out", type=Path, default=Path("docs/project/voice-local-evidence.json"))
    parser.add_argument("--artifact", type=Path, default=Path(".sumika-next/voice-acceptance"))
    parser.add_argument("--threshold", type=float, default=0.6)
    args = parser.parse_args()
    model = Path(args.model).resolve()
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
    recognized = transcribe(wav, model=str(model))
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
