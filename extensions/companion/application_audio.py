"""Application transcription is reference data, never microphone questions."""
import json
import inspect
import threading
import time
from collections import deque

from extensions.companion.audio_providers import VoskPcmProvider, SenseVoicePcmProvider, SileroSpeechDetector
from extensions.companion.contracts import ObservationBundle
from extensions.desktop.process_audio import ProcessAudioCapture


class _CaptureClockCoverage:
    """Bounded packet metadata only; audio sample offsets are not player time.

    Call under the track's existing lock. A span interpolates within native
    16kHz packets, checking available device positions and QPC at each join.
    Missing/dropped metadata is never extrapolated from a previous packet.
    """
    def __init__(self):
        self.packets = deque(maxlen=4096)

    def clear(self):
        self.packets.clear()

    def add(self, offset, size, timing):
        clock = dict(timing) if timing else None
        self.packets.append((offset, offset + size, clock))
        # The longest admitted Vosk segment is 30s; keep a little preroll.
        while self.packets and self.packets[0][1] < offset + size - 32 * 32000:
            self.packets.popleft()

    def span(self, start, end):
        result = {'known': False, 'clock_scope': 'native-segment-audio',
                  'qpc_unit': '100ns', 'sample_rate': 16000}
        def unknown(reason):
            return {**result, 'reason': reason}
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or start % 2 or end % 2:
            return unknown('invalid_segment_range')
        cursor, previous, count = start, None, 0
        previous_qpc = None
        first_qpc = first_device = last_qpc = last_device = None
        device_positions_known = True
        for packet_start, packet_end, timing in self.packets:
            if packet_end <= start:
                continue
            if packet_start >= end:
                break
            if packet_start > cursor:
                return unknown('packet_coverage_missing')
            if timing is None:
                return unknown('packet_clock_missing')
            if (timing.get('timestamp_valid') is not True
                    or timing.get('data_discontinuity') is not False
                    or timing.get('sample_rate') != 16000
                    or timing.get('qpc_unit') != '100ns'
                    or timing.get('clock_scope') != 'native-packet-start'):
                return unknown('packet_clock_invalid')
            device, qpc = timing.get('device_position'), timing.get('qpc_position')
            if any(type(value) is not int or not 0 <= value < 2**64 for value in (device, qpc)):
                return unknown('packet_clock_invalid')
            if previous is not None:
                if qpc <= previous_qpc:
                    return unknown('qpc_nonmonotonic')
                expected_device, expected_qpc, previous_device = previous
                # Windows process loopback on this host reports device position
                # zero for every packet, despite a valid progressing QPC clock.
                # Retain QPC coverage without inventing sample positions.
                if previous_device == device == 0:
                    device_positions_known = False
                elif device != expected_device:
                    return unknown('device_position_discontinuity')
                if abs(qpc - expected_qpc) > 10000:
                    return unknown('qpc_discontinuity')
            local_start, local_end = max(cursor, packet_start), min(end, packet_end)
            # One mono PCM16 sample is 2 bytes and 625 QPC ticks at 16kHz.
            if first_qpc is None:
                first_qpc = qpc + (local_start - packet_start) // 2 * 625
                first_device = device + (local_start - packet_start) // 2
            last_qpc = qpc + (local_end - packet_start) // 2 * 625
            last_device = device + (local_end - packet_start) // 2
            previous = (device + (packet_end - packet_start) // 2,
                        qpc + (packet_end - packet_start) // 2 * 625, device)
            previous_qpc = qpc
            count += 1
            cursor = local_end
            if cursor == end:
                break
        if cursor != end:
            return unknown('packet_coverage_missing')
        return {**result, 'known': True, 'start_qpc_position': first_qpc,
                'end_qpc_position': last_qpc,
                'device_position_known': device_positions_known and count > 1,
                'start_device_position': first_device if device_positions_known and count > 1 else None,
                'end_device_position': last_device if device_positions_known and count > 1 else None,
                'packet_count': count,
                'qpc_join_tolerance_100ns': 10000}


class ApplicationAudioTrack:
    """One process-bound PCM recognizer with no retained audio or disk recording."""

    def __init__(self, capture, provider, *, target, on_transcript, max_segment_seconds=30,
                 media_time_seconds=None, playback_rate=1.0):
        if not isinstance(target, str) or not target.strip():
            raise ValueError('application target required')
        if not callable(on_transcript):
            raise TypeError('transcript callback required')
        if type(max_segment_seconds) is not int or not 1 <= max_segment_seconds <= 30:
            raise ValueError('invalid application segment duration')
        self.capture, self.provider = capture, provider
        self.target, self.on_transcript = target, on_transcript
        self._media_time = media_time_seconds if type(media_time_seconds) in (int, float) else None
        self._playback_rate = playback_rate if type(playback_rate) in (int, float) and playback_rate > 0 else 1.0
        self._limit = max_segment_seconds * 16000 * 2
        self._recognizer = None
        self._lock = threading.RLock()
        self._lifecycle = threading.RLock()
        self._stopping = threading.Event()
        self._stopping.set()
        self._segment_bytes = self._total_bytes = 0
        self._timing = None
        self._pending_timing = None
        self._clock_coverage = _CaptureClockCoverage()
        self._result_start = 0

    @classmethod
    def configured(cls, *, helper, process_id, creation_time, model_path, target,
                   approved=False, on_transcript, provider='vosk', media_time_seconds=None,
                   playback_rate=1.0):
        if provider not in ('vosk', 'sherpa-onnx-sensevoice'):
            raise ValueError('unsupported application ASR provider')
        capture = ProcessAudioCapture(helper, process_id=process_id,
                                      creation_time=creation_time, approved=approved)
        if provider == 'sherpa-onnx-sensevoice':
            return SegmentedApplicationAudioTrack(capture, SenseVoicePcmProvider(model_path),
                target=target, on_transcript=on_transcript, speech_detector=SileroSpeechDetector(),
                media_time_seconds=media_time_seconds, playback_rate=playback_rate)
        return cls(capture, VoskPcmProvider(model_path), target=target,
                   on_transcript=on_transcript, media_time_seconds=media_time_seconds,
                   playback_rate=playback_rate)

    def _new_recognizer(self):
        from vosk import KaldiRecognizer
        return KaldiRecognizer(self.provider.load_model(), 16000)

    def start(self):
        with self._lifecycle:
            with self._lock:
                if self._recognizer is not None:
                    raise RuntimeError('application transcription already active')
                self._recognizer = self._new_recognizer()
                self._segment_bytes = self._total_bytes = 0
                self._result_start = 0
                self._timing = self._pending_timing = None
                self._clock_coverage.clear()
                self._stopping.clear()
            try:
                start = self.capture.start
                if 'on_timing' in inspect.signature(start).parameters:
                    return start(self._pcm, on_timing=self._on_timing)
                return start(self._pcm)
            except BaseException:
                self.stop()
                raise

    def _publish(self, result):
        text = json.loads(result).get('text', '')
        if not isinstance(text, str) or len(text) > 12000:
            raise ValueError('invalid application transcript')
        start = self._result_start
        self._result_start = self._total_bytes
        if text.strip() and not self._stopping.is_set():
            self.on_transcript(ObservationBundle.now(
                source='application-audio-transcript', target=self.target, valid=True,
                text=text.strip(), metadata={
                    'process_id': self.capture.process_id,
                    'process_creation': self.capture.creation_time,
                    'track': 'application', 'capture_offset_seconds': self._total_bytes / 32000,
                    'capture_start_offset_seconds': start / 32000,
                    # Process loopback exposes PCM packets, not the player's
                    # media clock. Silence/paused playback can omit packets,
                    # so PCM offset must never be advertised as video time.
                    'media_position_known': False,
                    'media_time_seconds': None, 'transcription': 'vosk',
                    'capture_clock': dict(self._timing) if self._timing else None,
                    'capture_clock_span': self._clock_coverage.span(start, self._total_bytes),
                }))

    def _on_timing(self, timing):
        with self._lock:
            if not self._stopping.is_set():
                self._timing = dict(timing) if timing is not None else None
                self._pending_timing = self._timing

    def _pcm(self, pcm):
        if not isinstance(pcm, bytes) or not pcm or len(pcm) > 64000 or len(pcm) % 2:
            raise ValueError('bounded 16kHz mono PCM required')
        with self._lock:
            if self._stopping.is_set() or self._recognizer is None:
                return
            self._clock_coverage.add(self._total_bytes, len(pcm), self._pending_timing)
            self._pending_timing = None
            # Smaller native calls let stop fence results between calls.
            offset = 0
            while offset < len(pcm):
                if self._stopping.is_set():
                    return
                chunk = pcm[offset:offset + min(8000, self._limit - self._segment_bytes)]
                offset += len(chunk)
                self._segment_bytes += len(chunk)
                self._total_bytes += len(chunk)
                if self._recognizer.AcceptWaveform(chunk):
                    self._publish(self._recognizer.Result())
                if self._segment_bytes >= self._limit:
                    self._publish(self._recognizer.FinalResult())
                    self._recognizer = self._new_recognizer()
                    self._segment_bytes = 0

    def stop(self):
        self._stopping.set()
        with self._lifecycle:
            try:
                self.capture.stop()
            finally:
                with self._lock:
                    # Do not finalize a revoked or paused fragment.
                    self._recognizer = None
                    self._segment_bytes = self._total_bytes = 0
                    self._timing = None
                    self._pending_timing = None
                    self._clock_coverage.clear()
                    self._result_start = 0

    def status(self):
        return self.capture.status()


class SegmentedApplicationAudioTrack:
    """Offline recognition outside the native capture callback, bounded in RAM.

    Queue overflow is an explicit failure rather than silently losing tutorial
    speech. A pause/stop discards partial PCM and fences in-flight results.
    """

    def __init__(self, capture, provider, *, target, on_transcript, segment_seconds=5,
                 speech_detector=None, media_time_seconds=None, playback_rate=1.0):
        if not isinstance(target, str) or not target.strip() or not callable(on_transcript):
            raise ValueError('application target and callback required')
        if type(segment_seconds) is not int or not 1 <= segment_seconds <= 10:
            raise ValueError('invalid segment duration')
        self.capture, self.provider = capture, provider
        self.target, self.on_transcript = target, on_transcript
        self._media_time = media_time_seconds if type(media_time_seconds) in (int, float) else None
        self._playback_rate = playback_rate if type(playback_rate) in (int, float) and playback_rate > 0 else 1.0
        self._limit = segment_seconds * 32000
        self._condition = threading.Condition(threading.RLock())
        self._lifecycle = threading.RLock()
        self._stop = threading.Event()
        self._stop.set()
        self._buffer = bytearray()
        self._queue = deque()
        self._thread = None
        self._total = 0
        self._error = None
        self._decode_started = None
        self._decoded_end = 0
        self._timing = None
        self._pending_timing = None
        self._clock_coverage = _CaptureClockCoverage()
        if speech_detector is not None and (not callable(speech_detector)
                or getattr(speech_detector, 'frame_bytes', None) != 1024
                or not callable(getattr(speech_detector, 'load_model', None))
                or not callable(getattr(speech_detector, 'reset', None))):
            raise ValueError('512-sample speech detector required')
        self._detector = speech_detector
        self._frames = bytearray()
        self._preroll = bytearray()
        self._processed = self._segment_start = self._silence = self._voiced = 0

    def prepare(self):
        self.provider.load_model()
        if self._detector is not None:
            self._detector.load_model()

    def start(self):
        with self._lifecycle:
            if self._thread is not None:
                raise RuntimeError('application transcription already active')
            self.prepare()
            with self._condition:
                self._stop.clear()
                self._error = None
                self._total = 0
                self._timing = self._pending_timing = None
                self._clock_coverage.clear()
                self._decode_started = None
                self._decoded_end = 0
                self._buffer.clear()
                self._queue.clear()
                self._frames.clear()
                self._preroll.clear()
                self._processed = self._segment_start = self._silence = self._voiced = 0
                self._thread = threading.Thread(target=self._decode,
                    name='sumika-application-asr', daemon=True)
                self._thread.start()
            try:
                start = self.capture.start
                if 'on_timing' in inspect.signature(start).parameters:
                    return start(self._pcm, on_timing=self._on_timing)
                return start(self._pcm)
            except BaseException:
                self.stop()
                raise

    def _on_timing(self, timing):
        with self._condition:
            if not self._stop.is_set():
                self._timing = dict(timing) if timing is not None else None
                self._pending_timing = self._timing

    def _pcm(self, pcm):
        if not isinstance(pcm, bytes) or not pcm or len(pcm) > 64000 or len(pcm) % 2:
            raise ValueError('bounded 16kHz mono PCM required')
        with self._condition:
            if self._stop.is_set():
                return
            self._clock_coverage.add(self._total, len(pcm), self._pending_timing)
            self._pending_timing = None
            self._total += len(pcm)
            if self._detector is not None:
                # Small CPU VAD frames only; offline ASR stays on _decode.
                self._frames.extend(pcm)
                while len(self._frames) >= 1024 and not self._stop.is_set():
                    frame = bytes(self._frames[:1024])
                    del self._frames[:1024]
                    self._processed += 1024
                    speaking = self._detector(frame)
                    if not self._buffer and not speaking:
                        self._preroll.extend(frame)
                        del self._preroll[:-8192]
                        continue
                    if not self._buffer:
                        self._segment_start = self._processed-1024-len(self._preroll)
                        self._buffer.extend(self._preroll)
                        self._preroll.clear()
                    self._buffer.extend(frame)
                    self._voiced += 1024 if speaking else 0
                    self._silence = 0 if speaking else self._silence+1024
                    if self._silence >= 15360 or len(self._buffer) >= self._limit:
                        reason = 'silence' if self._silence >= 15360 else 'duration_limit'
                        if self._voiced >= 5120:
                            self._enqueue(bytes(self._buffer), self._segment_start/32000,
                                          self._processed/32000, reason)
                        self._buffer.clear()
                        self._silence = self._voiced = 0
                self._condition.notify_all()
                return
            self._buffer.extend(pcm)
            while len(self._buffer) >= self._limit:
                audio = bytes(self._buffer[:self._limit])
                del self._buffer[:self._limit]
                end = (self._total-len(self._buffer))/32000
                if not self._enqueue(audio, end-len(audio)/32000, end, 'fixed_duration'):
                    return
            self._condition.notify_all()

    def _enqueue(self, audio, start, end, reason):
        if len(self._queue) >= 2:
            self._error = 'asr_queue_overflow'
            self._stop.set()
            self._buffer.clear()
            self._frames.clear()
            self._preroll.clear()
            self._queue.clear()
            self._condition.notify_all()
            return False
        self._queue.append((audio, start, end, reason,
                            dict(self._timing) if self._timing else None,
                            self._clock_coverage.span(round(start * 32000), round(end * 32000))))
        return True

    def _decode(self):
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._stop.is_set() or self._queue)
                    if self._stop.is_set():
                        return
                    audio, start, end, reason, capture_clock, capture_span = self._queue.popleft()
                    self._decode_started = time.monotonic()
                text = self.provider._recognize(audio, 16000, self._stop)
                del audio
                if not isinstance(text, str) or len(text) > 12000:
                    raise ValueError('invalid application transcript')
                with self._condition:
                    if self._stop.is_set():
                        return
                    self._decode_started = None
                    self._decoded_end = end
                    if text.strip():
                        self.on_transcript(ObservationBundle.now(
                            source='application-audio-transcript', target=self.target,
                            valid=True, text=text.strip(), metadata={
                                'process_id': self.capture.process_id,
                                'process_creation': self.capture.creation_time,
                                'track': 'application', 'capture_offset_seconds': end,
                                'capture_start_offset_seconds': start,
                                'segmentation': 'silero-vad' if self._detector is not None else 'fixed-duration',
                                'segment_end_reason': reason,
                                'media_position_known': False,
                                'media_time_seconds': None,
                                'capture_clock': capture_clock,
                                'capture_clock_span': capture_span,
                                'transcription': 'sherpa-onnx-sensevoice'}))
        except Exception as error:
            with self._condition:
                self._error = type(error).__name__
                self._stop.set()
                self._buffer.clear()
                self._frames.clear()
                self._preroll.clear()
                self._queue.clear()
                self._condition.notify_all()

    def stop(self):
        self._stop.set()
        with self._condition:
            self._buffer.clear()
            self._frames.clear()
            self._preroll.clear()
            self._queue.clear()
            self._condition.notify_all()
        with self._lifecycle:
            try:
                self.capture.stop()
            finally:
                if self._thread is not None:
                    self._thread.join()
                    self._thread = None
                self._total = 0
                self._timing = None
                self._pending_timing = None
                self._clock_coverage.clear()
                if self._detector is not None:
                    self._detector.reset()

    def status(self):
        with self._condition:
            progress = {'capture_seconds': self._total/32000,
                        'decoded_seconds': self._decoded_end,
                        'pending_segments': len(self._queue),
                        'decode_elapsed_seconds': (time.monotonic()-self._decode_started
                            if self._decode_started is not None else None)}
            if self._error:
                return {**self.capture.status(), **progress, 'state': 'error', 'error': self._error}
        return {**self.capture.status(), **progress}


class PipePcmCapture:
    """PCM source adapter fed by the host over the worker pipe.

    Used for opt-in browser tab audio: the extension captures the selected
    media element and the bridge relays bounded packets. There is no native
    process binding, so process identity stays absent and PCM offsets never
    claim a player media clock.
    """

    process_id = None
    creation_time = None

    def __init__(self):
        self._lock = threading.Lock()
        self._sink = None
        self._state = 'stopped'
        self._packets = 0

    def start(self, sink, on_timing=None):
        if not callable(sink):
            raise ValueError('pcm sink required')
        with self._lock:
            if self._state != 'stopped':
                raise RuntimeError('pipe capture already active')
            self._sink = sink
            self._state = 'recording'
            self._packets = 0

    def feed(self, pcm):
        """Deliver one bounded PCM packet from the pipe reader thread."""
        sink = None
        with self._lock:
            if self._state == 'recording':
                sink = self._sink
                self._packets += 1
        if sink is not None:
            sink(pcm)

    def stop(self):
        with self._lock:
            self._sink = None
            self._state = 'stopped'
        return {'state': 'stopped'}

    def status(self):
        with self._lock:
            return {'state': self._state, 'packets': self._packets,
                    'process_isolation': False, 'source': 'browser-tab-pipe'}
