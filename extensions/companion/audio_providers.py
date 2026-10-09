"""In-memory speech providers for the optional continuous companion pipeline."""
import asyncio
import json
from pathlib import Path
import threading


class SileroSpeechDetector:
    """Reuse Pipecat's bundled CPU VAD for exact 512-sample application frames."""

    frame_bytes = 1024

    def __init__(self):
        self._analyzer = None

    def load_model(self):
        if self._analyzer is None:
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            analyzer = SileroVADAnalyzer(sample_rate=16000)
            analyzer.set_sample_rate(16000)
            self._analyzer = analyzer

    def __call__(self, pcm):
        if not isinstance(pcm, bytes) or len(pcm) != self.frame_bytes:
            raise ValueError('Silero requires 512 samples of 16kHz mono PCM')
        self.load_model()
        return bool(self._analyzer.voice_confidence(pcm) >= 0.5)

    def reset(self):
        # A resumed observation must not inherit the previous audio stream's
        # recurrent model state. The small bundled model is reloaded at start.
        self._analyzer = None


class VoskPcmProvider:
    """Recognize bounded 16-bit mono PCM without creating an audio file."""

    def __init__(self, model_path, *, max_bytes=16000 * 2 * 30):
        self.model_path = Path(model_path).resolve()
        if not self.model_path.is_dir():
            raise ValueError('local Vosk model missing')
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError('invalid PCM limit')
        self.max_bytes = max_bytes
        self._model = None
        self._lock = threading.Lock()

    def load_model(self):
        from vosk import Model
        with self._lock:
            if self._model is None:
                self._model = Model(str(self.model_path))
            return self._model

    def _recognize(self, audio, sample_rate, cancelled):
        if len(audio) > self.max_bytes or len(audio) % 2:
            raise ValueError('PCM exceeds limit or is not 16-bit aligned')
        from vosk import KaldiRecognizer
        if cancelled.is_set():
            return ''
        model = self.load_model()
        if cancelled.is_set():
            return ''
        recognizer = KaldiRecognizer(model, sample_rate)
        pieces = []
        for offset in range(0, len(audio), 8000):
            if cancelled.is_set():
                return ''
            chunk = audio[offset:offset + 8000]
            if recognizer.AcceptWaveform(chunk):
                pieces.append(json.loads(recognizer.Result()).get('text', ''))
        if cancelled.is_set():
            return ''
        pieces.append(json.loads(recognizer.FinalResult()).get('text', ''))
        return ' '.join(part for part in pieces if part).strip()

    async def __call__(self, audio, *, sample_rate=16000):
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            raise ValueError('PCM audio required')
        if sample_rate != 16000:
            raise ValueError('Vosk companion input must be 16kHz')
        if len(audio) > self.max_bytes or len(audio) % 2:
            raise ValueError('PCM exceeds limit or is not 16-bit aligned')
        cancelled = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(
            self._recognize, bytes(audio), sample_rate, cancelled))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            # Wait for the current native chunk/model load to return, so the
            # owner cannot start another turn while old recognition still runs.
            try:
                await asyncio.shield(task)
            except Exception:
                pass
            raise


class SenseVoicePcmProvider:
    """Optional CPU SenseVoice provider backed by sherpa-onnx.

    It deliberately exposes the same bounded async contract as Vosk. The
    current model is offline, so callers should use it for bounded segments;
    it is not silently substituted for the streaming Vosk capability.
    """

    def __init__(self, model_path, *, max_bytes=16000 * 2 * 30, num_threads=4):
        self.model_path = Path(model_path).resolve()
        if not self.model_path.is_dir():
            raise ValueError('local SenseVoice model missing')
        if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > 16000 * 2 * 30:
            raise ValueError('invalid PCM limit')
        if type(num_threads) is not int or not 1 <= num_threads <= 8:
            raise ValueError('invalid ASR thread limit')
        self.max_bytes = max_bytes
        self.num_threads = num_threads
        self._recognizer = None
        self._lock = threading.Lock()

    def load_model(self):
        # Initialize native numeric dependencies on the lifecycle owner before
        # sherpa starts its native workers. First import from the PCM decoding
        # thread stalled in NumPy's native loader on the Windows runtime.
        import numpy
        import sherpa_onnx
        with self._lock:
            if self._recognizer is None:
                model = self.model_path / 'model.int8.onnx'
                if not model.is_file():
                    model = self.model_path / 'model.onnx'
                tokens = self.model_path / 'tokens.txt'
                if not model.is_file() or not tokens.is_file():
                    raise ValueError('SenseVoice model files missing')
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(model), tokens=str(tokens),
                    num_threads=self.num_threads, provider='cpu',
                    language='zh', use_itn=True)
            return self._recognizer

    def _recognize(self, audio, sample_rate, cancelled):
        if len(audio) > self.max_bytes or len(audio) % 2:
            raise ValueError('PCM exceeds limit or is not 16-bit aligned')
        if cancelled.is_set():
            return ''
        import numpy as np
        recognizer = self.load_model()
        if cancelled.is_set():
            return ''
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        if cancelled.is_set():
            return ''
        return str(stream.result.text).strip()

    async def __call__(self, audio, *, sample_rate=16000):
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            raise ValueError('PCM audio required')
        if sample_rate != 16000:
            raise ValueError('SenseVoice companion input must be 16kHz')
        if len(audio) > self.max_bytes or len(audio) % 2:
            raise ValueError('PCM exceeds limit or is not 16-bit aligned')
        cancelled = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(
            self._recognize, bytes(audio), sample_rate, cancelled))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            try:
                await asyncio.shield(task)
            except Exception:
                pass
            raise
