"""Real device acceptance for camera and microphone capture.

Metadata only: this never prints, uploads or commits the picture or the audio.
Captured files are deleted unless --keep is passed. Run it with the isolated
desktop environment interpreter (cv2, sounddevice).
"""
import argparse
import json
import math
import struct
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extensions.desktop.perception import capture_audio, capture_camera


def frame_metadata(path):
    import cv2
    image = cv2.imread(str(path))
    if image is None:
        return {"readable": False}
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean, stddev = float(gray.mean()), float(gray.std())
    return {"readable": True, "width": width, "height": height,
            "mean_brightness": round(mean, 2), "stddev": round(stddev, 2),
            "looks_blank": mean < 1.0 or stddev < 2.0}


def wav_metadata(path):
    with wave.open(str(path), "rb") as handle:
        channels, width, rate = handle.getnchannels(), handle.getsampwidth(), handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = struct.unpack("<" + "h" * (len(frames) // 2), frames) if width == 2 else ()
    if samples:
        rms = math.sqrt(sum(value * value for value in samples) / len(samples))
        peak = max(abs(value) for value in samples)
    else:
        rms = peak = 0
    return {"channels": channels, "sample_width": width, "sample_rate": rate,
            "seconds": round(len(samples) / (rate * channels), 2) if samples else 0,
            "rms": round(rms, 1), "peak": peak, "silent": peak < 50}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/project/perception-local-evidence.json"))
    parser.add_argument("--artifact", type=Path, default=Path(".sumika-next/perception"))
    parser.add_argument("--keep", action="store_true", help="Keep the captured frame and audio file")
    parser.add_argument("--camera-device", type=int, default=0)
    parser.add_argument("--audio-device", type=int, default=None,
                        help="Explicit input device index; None uses the system default")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--skip-camera", action="store_true")
    parser.add_argument("--skip-microphone", action="store_true")
    parser.add_argument("--settings", type=Path, default=None,
                        help="Read voice.input_device / voice.sample_rate from a settings file")
    args = parser.parse_args()
    if args.settings and args.audio_device is None:
        from extensions.models.settings import load as load_settings
        voice = load_settings(args.settings).get("voice", {})
        args.audio_device = voice.get("input_device")
        args.sample_rate = voice.get("sample_rate") or args.sample_rate
        print(json.dumps({"settings_voice": {"enabled": voice.get("enabled"),
                                            "input_device": args.audio_device,
                                            "sample_rate": voice.get("sample_rate")}},
                         ensure_ascii=False))
    artifact = args.artifact.resolve()
    artifact.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "privacy": "metadata only; no image or audio is printed, uploaded or committed",
              "kept_files": bool(args.keep), "results": {}}

    if not args.skip_camera:
        target = artifact / "camera-acceptance.png"
        if target.exists():
            target.unlink()
        started = time.perf_counter()
        try:
            # approved=True is the caller's explicit, in-session authorization.
            result = capture_camera(target, device=args.camera_device, approved=True)
            report["results"]["camera"] = {
                "status": "ok", "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                **frame_metadata(target), "bytes": target.stat().st_size}
        except Exception as error:  # device blocked, busy or denied by the OS
            report["results"]["camera"] = {"status": "unknown", "error": type(error).__name__,
                                           "message": str(error)[:200]}
        finally:
            if not args.keep and target.exists():
                target.unlink()

    if not args.skip_microphone:
        target = artifact / "microphone-acceptance.wav"
        if target.exists():
            target.unlink()
        started = time.perf_counter()
        try:
            result = capture_audio(target, seconds=args.seconds, device=args.audio_device,
                                   approved=True, sample_rate=args.sample_rate)
            report["results"]["microphone"] = {
                "status": "ok", "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                **wav_metadata(target), "bytes": target.stat().st_size}
        except Exception as error:
            report["results"]["microphone"] = {"status": "unknown", "error": type(error).__name__,
                                               "message": str(error)[:200]}
        finally:
            if not args.keep and target.exists():
                target.unlink()

    def usable(name, item):
        if item.get("status") != "ok":
            return False
        if name == "camera":
            return item.get("readable") and not item.get("looks_blank")
        if name == "microphone":
            return not item.get("silent")
        return False

    for name, item in report["results"].items():
        item["usable"] = usable(name, item)
        if item.get("status") == "ok" and not item["usable"]:
            item["note"] = ("capture succeeded but the device delivered no usable signal; "
                            "check the OS privacy setting, device mute or physical cover")
    report["passed"] = bool(report["results"]) and all(
        item["usable"] for item in report["results"].values())
    report["capture_api_works"] = all(item.get("status") == "ok" for item in report["results"].values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(report["results"], ensure_ascii=False, indent=1))
    print("passed:", report["passed"])


if __name__ == "__main__":
    main()
