"""Audio runtime boundary for permission-gated ASR, TTS and VAD calls."""

from .runtime import AudioRuntime, AudioRuntimeError

__all__ = ["AudioRuntime", "AudioRuntimeError"]
