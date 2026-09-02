"""Local OCR evidence that never exports page text or screenshot paths."""

from __future__ import annotations

import difflib
import json
import os
import re
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


VISUAL_EVIDENCE_SCHEMA = "browser-visual-evidence/v1"
_MAX_IMAGE_BYTES = 64 * 1024 * 1024
_MATCH_TEXT_RE = re.compile(r"[\W_]+", flags=re.UNICODE)
_BLOCKING_MARKERS = (
    "captcha",
    "verification required",
    "verify you are human",
    "sign in to continue",
    "log in to continue",
    "验证码",
    "人机验证",
    "安全验证",
    "请先登录",
    "登录后继续",
    "购买套餐",
    "立即升级",
    "付款",
)


class VisualEvidenceError(RuntimeError):
    """Raised when local visual evidence cannot be obtained safely."""

    def __init__(self, message: str, *, code: str = "visual-probe-failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class OcrLine:
    text: str
    score: float
    box: tuple[float, float, float, float] | None


@dataclass(frozen=True, slots=True)
class VisualObservation:
    lines: tuple[OcrLine, ...]
    width: int | None
    height: int | None


class VisualEvidenceProbe:
    """Replaceable local visual probe boundary."""

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    def observe(self, image_path: str | Path) -> VisualObservation:
        raise NotImplementedError

    def evaluate(
        self,
        observation: VisualObservation,
        *,
        baseline: VisualObservation | None = None,
        expected_text: str | None = None,
        scope: str = "page",
    ) -> dict[str, Any]:
        raise NotImplementedError


def _normalize_match_text(value: Any, *, limit: int = 8_000) -> str:
    text = str(value or "").casefold()[:limit]
    return _MATCH_TEXT_RE.sub("", text)


def _png_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
        if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
            width, height = struct.unpack(">II", header[16:24])
            if 0 < width <= 32_768 and 0 < height <= 32_768:
                return int(width), int(height)
    except OSError:
        pass
    return None, None


def _box_bounds(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)):
        return None
    points: list[tuple[float, float]] = []
    for point in list(value)[:8]:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            points.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _parse_ocr_output(stdout: str) -> tuple[OcrLine, ...]:
    payload: Mapping[str, Any] | None = None
    for raw_line in reversed(str(stdout or "").splitlines()):
        try:
            candidate = json.loads(raw_line)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(candidate, Mapping) and "code" in candidate:
            payload = candidate
            break
    if payload is None:
        raise VisualEvidenceError("RapidOCR returned no JSON result", code="ocr-invalid-output")
    try:
        code = int(payload.get("code"))
    except (TypeError, ValueError) as error:
        raise VisualEvidenceError("RapidOCR returned an invalid result code", code="ocr-invalid-output") from error
    if code == 101:
        return ()
    if code != 100 or not isinstance(payload.get("data"), list):
        raise VisualEvidenceError("RapidOCR could not inspect the screenshot", code=f"ocr-{code}")
    result: list[OcrLine] = []
    for item in list(payload["data"])[:512]:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text") or "").strip()[:2_000]
        if not text:
            continue
        try:
            score = max(0.0, min(1.0, float(item.get("score", 0.0))))
        except (TypeError, ValueError):
            score = 0.0
        result.append(OcrLine(text=text, score=score, box=_box_bounds(item.get("box"))))
    return tuple(result)


def _prompt_line_indexes(lines: Iterable[OcrLine], expected_text: str | None) -> tuple[int, ...]:
    expected = _normalize_match_text(expected_text)
    if len(expected) < 4:
        return ()
    matches: list[int] = []
    for index, line in enumerate(lines):
        candidate = _normalize_match_text(line.text, limit=2_000)
        if len(candidate) < 3:
            continue
        exact = candidate in expected or expected in candidate
        comparable = min(len(candidate), len(expected)) >= 6
        ratio = difflib.SequenceMatcher(None, candidate[:320], expected[:2_000]).ratio() if comparable else 0.0
        if exact or ratio >= 0.70:
            matches.append(index)
    if matches:
        return tuple(matches)

    joined = "".join(_normalize_match_text(line.text, limit=1_000) for line in lines)
    if not joined:
        return ()
    samples = []
    sample_size = min(32, max(8, len(expected) // 4))
    for start in {0, max(0, (len(expected) - sample_size) // 2), max(0, len(expected) - sample_size)}:
        sample = expected[start : start + sample_size]
        if len(sample) >= 8:
            samples.append(sample)
    if samples and sum(sample in joined for sample in samples) >= min(2, len(samples)):
        return tuple(
            index
            for index, line in enumerate(lines)
            if any(_normalize_match_text(line.text) in sample or sample in _normalize_match_text(line.text) for sample in samples)
        )
    return ()


def _same_region(
    first: tuple[float, float, float, float] | None,
    second: tuple[float, float, float, float] | None,
    *,
    width: int | None,
    height: int | None,
) -> bool:
    if first is None or second is None:
        return False
    first_x = (first[0] + first[2]) / 2
    first_y = (first[1] + first[3]) / 2
    second_x = (second[0] + second[2]) / 2
    second_y = (second[1] + second[3]) / 2
    x_limit = max(32.0, float(width or 800) * 0.08)
    y_limit = max(24.0, float(height or 600) * 0.08)
    return abs(first_x - second_x) <= x_limit and abs(first_y - second_y) <= y_limit


class RapidOcrJsonProbe(VisualEvidenceProbe):
    """One-shot RapidOCR-json adapter with a strictly bounded public result."""

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        runner: Callable[..., Any] | None = None,
        timeout: float = 20.0,
        tooling_registry: str | Path | None = None,
    ) -> None:
        self._runner_injected = runner is not None
        self.runner = runner or self._run
        self.timeout = max(1.0, min(60.0, float(timeout)))
        self.executable = Path(executable) if executable else self._discover(tooling_registry)

    @staticmethod
    def _discover(tooling_registry: str | Path | None) -> Path | None:
        configured = str(os.getenv("SUMIKA_RAPID_OCR_EXECUTABLE") or "").strip()
        if configured:
            return Path(configured)
        registry_path = Path(
            tooling_registry
            or os.getenv("SUMIKA_TOOLING_REGISTRY")
            or r"D:\Caches\tooling\registry.json"
        )
        try:
            if registry_path.stat().st_size > 1_000_000:
                return None
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError):
            return None
        tools = payload.get("tools") if isinstance(payload, Mapping) else None
        for item in tools if isinstance(tools, list) else []:
            if not isinstance(item, Mapping) or item.get("id") != "umi-ocr-rapid" or item.get("status") != "available":
                continue
            entrypoint = str(item.get("entrypoint") or "").strip()
            return Path(entrypoint) if entrypoint else None
        return None

    @property
    def available(self) -> bool:
        return bool(self.executable and (self._runner_injected or self.executable.is_file()))

    def status(self) -> dict[str, Any]:
        return {
            "schema": VISUAL_EVIDENCE_SCHEMA,
            "available": self.available,
            "implementation": "rapidocr-json",
            "local_only": True,
            "exports_text": False,
        }

    @staticmethod
    def _run(args: list[str], *, cwd: str, timeout: float) -> subprocess.CompletedProcess[str]:
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=creationflags,
        )

    def observe(self, image_path: str | Path) -> VisualObservation:
        if not self.available or self.executable is None:
            raise VisualEvidenceError("RapidOCR is unavailable", code="ocr-unavailable")
        path = Path(image_path)
        try:
            stat = path.stat()
        except OSError as error:
            raise VisualEvidenceError("Screenshot is unavailable", code="screenshot-unavailable") from error
        if not path.is_file() or path.suffix.lower() != ".png" or stat.st_size > _MAX_IMAGE_BYTES:
            raise VisualEvidenceError("Screenshot is not a bounded PNG", code="screenshot-invalid")
        executable = str(self.executable)
        args = [
            executable,
            f"--image_path={path}",
            "--models=models",
            "--det=ch_PP-OCRv4_det_infer.onnx",
            "--cls=ch_ppocr_mobile_v2.0_cls_infer.onnx",
            "--rec=rec_ch_PP-OCRv4_infer.onnx",
            "--keys=dict_chinese.txt",
            "--ensureAscii=0",
            "--ensureLogger=0",
            "--maxSideLen=1600",
        ]
        try:
            completed = self.runner(
                args,
                cwd=str(self.executable.parent),
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise VisualEvidenceError("RapidOCR process is unavailable", code="ocr-process-unavailable") from error
        if int(getattr(completed, "returncode", 1)) != 0:
            raise VisualEvidenceError("RapidOCR process failed", code="ocr-process-failed")
        lines = _parse_ocr_output(str(getattr(completed, "stdout", "")))
        width, height = _png_dimensions(path)
        return VisualObservation(lines=lines, width=width, height=height)

    def evaluate(
        self,
        observation: VisualObservation,
        *,
        baseline: VisualObservation | None = None,
        expected_text: str | None = None,
        scope: str = "page",
    ) -> dict[str, Any]:
        lines = observation.lines
        average = sum(line.score for line in lines) / len(lines) if lines else 0.0
        confidence = "high" if average >= 0.85 else "medium" if average >= 0.60 else "low"
        current_prompt = _prompt_line_indexes(lines, expected_text)
        baseline_prompt = _prompt_line_indexes(baseline.lines, expected_text) if baseline else ()

        prompt_in_input: bool | None = None
        if str(scope or "page") == "input":
            if lines and average >= 0.55:
                prompt_in_input = bool(current_prompt)
        elif baseline is not None and baseline_prompt:
            comparable = bool(lines and average >= 0.50)
            if comparable:
                prompt_in_input = any(
                    _same_region(
                        baseline.lines[before_index].box,
                        lines[after_index].box,
                        width=observation.width or baseline.width,
                        height=observation.height or baseline.height,
                    )
                    for before_index in baseline_prompt
                    for after_index in current_prompt
                )

        assistant_visible: bool | None = None
        if baseline is not None and lines:
            old_lines = {_normalize_match_text(line.text) for line in baseline.lines}
            new_chars = 0
            prompt_indexes = set(current_prompt)
            for index, line in enumerate(lines):
                normalized = _normalize_match_text(line.text)
                if index in prompt_indexes or line.score < 0.50 or len(normalized) < 4 or normalized in old_lines:
                    continue
                new_chars += len(normalized)
            assistant_visible = new_chars >= 10

        folded_page = " ".join(str(line.text).casefold() for line in lines[:512])
        blocking = any(marker in folded_page for marker in _BLOCKING_MARKERS) if folded_page else False
        evidence = ["ocr-available"]
        if baseline is not None:
            evidence.append("baseline-compared")
        if prompt_in_input is True:
            evidence.append("prompt-location-match")
        elif prompt_in_input is False:
            evidence.append("prompt-location-cleared")
        if assistant_visible:
            evidence.append("new-visible-text")
        if blocking:
            evidence.append("blocking-marker")
        return {
            "available": True,
            "confidence": confidence,
            "prompt_in_input": prompt_in_input,
            "assistant_response_visible": assistant_visible,
            "blocking_surface_visible": blocking,
            "evidence": evidence,
            "error_code": None,
            "line_count": min(len(lines), 512),
        }
