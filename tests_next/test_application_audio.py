import json
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from extensions.companion.application_audio import ApplicationAudioTrack
from extensions.companion.audio_providers import VoskPcmProvider
from extensions.companion.application_audio import SegmentedApplicationAudioTrack, _CaptureClockCoverage


class ApplicationAudioTests(unittest.TestCase):
    def test_tiny_packets_still_require_strictly_monotonic_qpc(self):
        timing = {'device_position':0,'qpc_position':1000000,'sample_rate':16000,
                  'timestamp_valid':True,'data_discontinuity':False,
                  'clock_scope':'native-packet-start','qpc_unit':'100ns'}
        for second in (1000000,999999):
            coverage = _CaptureClockCoverage()
            coverage.add(0,2,timing)
            coverage.add(2,2,{**timing,'qpc_position':second})
            self.assertEqual(coverage.span(0,4)['reason'],'qpc_nonmonotonic')

    def test_capture_clock_coverage_requires_contiguous_valid_packets(self):
        coverage = _CaptureClockCoverage()
        timing = {'device_position': 0, 'qpc_position': 100000,
                  'sample_rate': 16000, 'timestamp_valid': True,
                  'data_discontinuity': False, 'clock_scope': 'native-packet-start',
                  'qpc_unit': '100ns'}
        coverage.add(0, 3200, timing)
        next_timing = dict(timing, device_position=1600, qpc_position=1100000)
        coverage.add(3200, 3200, next_timing)
        span = coverage.span(0, 6400)
        self.assertTrue(span['known'])
        self.assertEqual(span['packet_count'], 2)
        self.assertEqual(span['start_device_position'], 0)
        self.assertEqual(span['end_device_position'], 3200)
        broken = _CaptureClockCoverage()
        broken.add(0, 3200, timing)
        broken.add(6400, 3200, next_timing)
        self.assertEqual(broken.span(0, 9600)['reason'], 'packet_coverage_missing')
        invalid = _CaptureClockCoverage()
        invalid.add(0, 3200, dict(timing, timestamp_valid=False))
        self.assertEqual(invalid.span(0, 3200)['reason'], 'packet_clock_invalid')

    def test_capture_span_slices_packets_and_rejects_unproven_joins(self):
        timing = {'device_position': 100, 'qpc_position': 1000000,
                  'sample_rate': 16000, 'timestamp_valid': True,
                  'data_discontinuity': False, 'clock_scope': 'native-packet-start',
                  'qpc_unit': '100ns'}
        coverage = _CaptureClockCoverage()
        coverage.add(0, 3200, timing)
        coverage.add(3200, 3200, dict(timing, device_position=1700, qpc_position=2000000))
        span = coverage.span(320, 3520)
        self.assertTrue(span['known'])
        self.assertEqual((span['start_device_position'], span['end_device_position']), (260, 1860))
        self.assertEqual((span['start_qpc_position'], span['end_qpc_position']), (1100000, 2100000))
        for change, reason in (({'device_position': 1701}, 'device_position_discontinuity'),
                               ({'qpc_position': 2200000}, 'qpc_discontinuity'),
                               ({'data_discontinuity': True}, 'packet_clock_invalid')):
            broken = _CaptureClockCoverage()
            broken.add(0, 3200, timing)
            broken.add(3200, 3200, {**timing, 'device_position': 1700,
                                   'qpc_position': 2000000, **change})
            with self.subTest(change=change):
                self.assertEqual(broken.span(0, 6400)['reason'], reason)
        missing = _CaptureClockCoverage()
        missing.add(0, 3200, timing)
        missing.add(3200, 3200, None)
        self.assertEqual(missing.span(0, 6400)['reason'], 'packet_clock_missing')
        missing.clear()
        self.assertEqual(missing.span(0, 3200)['reason'], 'packet_coverage_missing')

    def test_process_loopback_zero_device_positions_require_contiguous_qpc(self):
        timing = {'device_position': 0, 'qpc_position': 1000000,
                  'sample_rate': 16000, 'timestamp_valid': True,
                  'data_discontinuity': False, 'clock_scope': 'native-packet-start',
                  'qpc_unit': '100ns'}
        coverage = _CaptureClockCoverage()
        coverage.add(0, 3200, timing)
        coverage.add(3200, 3200, dict(timing, qpc_position=2000000))
        span = coverage.span(0, 6400)
        self.assertTrue(span['known'])
        self.assertFalse(span['device_position_known'])
        self.assertIsNone(span['start_device_position'])
        self.assertIsNone(span['end_device_position'])
        coverage.add(6400, 3200, dict(timing, qpc_position=5000000))
        self.assertEqual(coverage.span(0, 9600)['reason'], 'qpc_discontinuity')

    def vad_track(self, seconds=5):
        self.decoded = []
        self.emitted = threading.Event()
        owner = self
        class Detector:
            frame_bytes = 1024
            def load_model(self): pass
            def reset(self): pass
            def __call__(self, pcm): return pcm != b'\0'*1024
        class Provider:
            def load_model(self): pass
            def _recognize(self, audio, rate, cancelled):
                owner.decoded.append(audio)
                return 'sentence'
        def publish(item): self.transcripts.append(item); self.emitted.set()
        track = SegmentedApplicationAudioTrack(self.capture, Provider(), target='lesson',
            on_transcript=publish, segment_seconds=seconds, speech_detector=Detector())
        self.addCleanup(track.stop)
        track.start()
        return track

    def test_vad_silence_never_decodes_and_preroll_is_bounded(self):
        track = self.vad_track()
        for _ in range(10): self.capture.callback(b'\0'*32000)
        self.assertEqual(self.decoded, [])
        self.assertLessEqual(len(track._preroll),8192)
        self.assertLess(len(track._frames),1024)
        self.assertEqual(len(track._buffer),0)

    def test_vad_endpoint_preserves_pcm_and_variable_capture_offsets(self):
        self.vad_track()
        silence = b'\0'*1024
        voiced = b'\x11\x00'*512
        audio = silence*12 + voiced*10 + silence*15
        # Deliberately split inside VAD frames and native callback packets.
        for offset in range(0,len(audio),730): self.capture.callback(audio[offset:offset+730])
        self.assertTrue(self.emitted.wait(2))
        self.assertEqual(self.decoded,[silence*8+voiced*10+silence*15])
        item = self.transcripts[0]
        self.assertAlmostEqual(item.metadata['capture_start_offset_seconds'],4*.032)
        self.assertAlmostEqual(item.metadata['capture_offset_seconds'],37*.032)
        self.assertEqual(item.metadata['segment_end_reason'],'silence')
        self.assertEqual(item.metadata['segmentation'],'silero-vad')

    def test_vad_continuous_speech_is_capped_and_stop_discards_partial(self):
        track = self.vad_track(seconds=1)
        for _ in range(32): self.capture.callback(b'\x11\x00'*512)
        self.assertTrue(self.emitted.wait(2))
        self.assertEqual(self.transcripts[0].metadata['segment_end_reason'],'duration_limit')
        self.assertLessEqual(len(self.decoded[0]),32000+1024)
        self.capture.callback(b'\x11\x00'*512)
        track.stop()
        self.assertEqual(len(self.transcripts),1)

    def test_vad_overflow_fences_late_decode_and_reclaims_buffers(self):
        track = self.vad_track(seconds=1)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def recognize(audio, rate, cancelled):
            entered.set(); release.wait(3); return 'late'
        track.provider._recognize = recognize
        for _ in range(32): self.capture.callback(b'\x11\x00'*512)
        self.assertTrue(entered.wait(2))
        for _ in range(96): self.capture.callback(b'\x11\x00'*512)
        self.assertEqual(track.status()['error'],'asr_queue_overflow')
        self.assertFalse(track._buffer or track._frames or track._preroll or track._queue)
        release.set()
        track.stop()
        self.assertFalse(self.transcripts)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.chunks, self.created, self.transcripts = [], [], []
        owner = self
        class Recognizer:
            def __init__(self, model, rate): owner.created.append(rate)
            def AcceptWaveform(self, pcm): owner.chunks.append(pcm); return True
            def Result(self): return json.dumps({'text': 'tutorial words'})
            def FinalResult(self): return json.dumps({'text': ''})
        class Capture:
            process_id = 5
            creation_time = '7'
            def start(self, callback): self.callback = callback; return {'state':'recording'}
            def stop(self): pass
            def status(self): return {'state':'recording'}
        fake = types.SimpleNamespace(Model=lambda path: object(), KaldiRecognizer=Recognizer)
        self.patch = patch.dict('sys.modules', vosk=fake)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.capture = Capture()
        self.track = ApplicationAudioTrack(self.capture, VoskPcmProvider(self.folder.name),
            target='lesson', on_transcript=self.transcripts.append, max_segment_seconds=1)

    def test_continuous_segment_reset_preserves_all_pcm_and_provenance(self):
        self.track.start()
        audio = bytes(range(256)) * 180
        self.capture.callback(audio)
        self.assertEqual(b''.join(self.chunks), audio)
        self.assertEqual(self.created, [16000,16000])
        item = self.transcripts[-1]
        self.assertEqual(item.source, 'application-audio-transcript')
        self.assertEqual(item.metadata['track'], 'application')
        self.assertEqual(item.metadata['process_creation'], '7')
        self.assertAlmostEqual(item.metadata['capture_offset_seconds'], len(audio)/32000)
        self.assertIsNone(item.media_time_seconds)
        self.track.stop()
        before = len(self.transcripts)
        self.capture.callback(b'\0'*320)
        self.assertEqual(len(self.transcripts), before)

    def test_optional_capture_clock_is_carried_without_claiming_media_time(self):
        def start(callback, on_timing=None):
            self.capture.callback=callback
            on_timing({'device_position':32000,'qpc_position':998877,'sample_rate':16000,
                       'timestamp_valid':True,'data_discontinuity':False,
                       'clock_scope':'native-packet-start','qpc_unit':'100ns'})
            return {'state':'recording'}
        self.capture.start=start
        self.track.start()
        self.capture.callback(bytes(range(256))*180)
        item=self.transcripts[-1]
        self.assertEqual(item.metadata['capture_clock']['qpc_position'],998877)
        self.assertTrue(item.metadata['capture_clock_span']['known'])
        self.assertFalse(item.metadata['media_position_known'])
        self.assertIsNone(item.media_time_seconds)
        self.track.stop()

    def test_offline_decode_freezes_clock_before_future_packet_and_clears_missing_clock(self):
        entered, release, emitted=threading.Event(),threading.Event(),threading.Event()
        class Provider:
            def load_model(self): pass
            def _recognize(self,audio,rate,cancelled):
                entered.set();release.wait(2);return 'sentence'
        def start(callback,on_timing=None):
            self.capture.callback=callback;self.capture.timing=on_timing
            return {'state':'recording'}
        self.capture.start=start
        track=SegmentedApplicationAudioTrack(self.capture,Provider(),target='lesson',
            on_transcript=lambda item:(self.transcripts.append(item),emitted.set()),segment_seconds=1)
        self.addCleanup(track.stop);self.addCleanup(release.set)
        track.start()
        first={'device_position':100,'qpc_position':1000,'timestamp_valid':True}
        self.capture.timing(first);self.capture.callback(b'\0'*32000)
        self.assertTrue(entered.wait(2))
        self.capture.timing({'device_position':200,'qpc_position':2000,'timestamp_valid':True})
        self.capture.callback(b'\0'*320)
        release.set();self.assertTrue(emitted.wait(2))
        self.assertEqual(self.transcripts[0].metadata['capture_clock'],first)
        self.capture.timing(None)
        self.assertIsNone(track._timing)
        self.assertFalse(self.transcripts[0].metadata['media_position_known'])

    def test_stop_during_native_recognition_rejects_late_transcript(self):
        entered, release = threading.Event(), threading.Event()
        self.track.start()
        original = self.track._recognizer.AcceptWaveform
        def blocked(pcm): entered.set(); release.wait(3); return original(pcm)
        self.track._recognizer.AcceptWaveform = blocked
        reading = threading.Thread(target=self.capture.callback, args=(b'\0'*320,))
        reading.start()
        self.assertTrue(entered.wait(2))
        stopping = threading.Thread(target=self.track.stop)
        stopping.start()
        self.assertTrue(self.track._stopping.wait(2))
        release.set()
        reading.join(3); stopping.join(3)
        self.assertFalse(reading.is_alive() or stopping.is_alive())
        self.assertEqual(self.transcripts, [])
        self.assertIsNone(self.track._recognizer)

    def test_vosk_start_anchor_does_not_make_pcm_offset_a_media_clock(self):
        track = ApplicationAudioTrack(self.capture, VoskPcmProvider(self.folder.name),
            target='lesson', on_transcript=self.transcripts.append,
            media_time_seconds=120, playback_rate=2)
        self.addCleanup(track.stop)
        track.start()
        self.capture.callback(b'\0'*320)
        # A gap without PCM can represent silence, pause or buffering. Neither
        # this packet nor a subsequent one proves a player-clock position.
        self.capture.callback(b'\0'*320)
        for item in self.transcripts:
            self.assertFalse(item.metadata['media_position_known'])
            self.assertIsNone(item.metadata['media_time_seconds'])
            self.assertIsNone(item.media_time_seconds)
        self.assertAlmostEqual(self.transcripts[-1].metadata['capture_offset_seconds'], .02)

    def test_restart_discards_old_recognizer_and_offset(self):
        self.track.start()
        self.capture.callback(b'\0'*320)
        self.track.stop()
        self.track.start()
        self.capture.callback(b'\0'*320)
        self.assertEqual(self.created, [16000,16000])
        self.assertEqual(self.transcripts[-1].metadata['capture_offset_seconds'], 0.01)
        self.track.stop()

    def test_start_failure_cleans_recognizer(self):
        def fail(callback): raise OSError('helper failed')
        self.capture.start = fail
        with self.assertRaises(OSError): self.track.start()
        self.assertIsNone(self.track._recognizer)
        self.assertTrue(self.track._stopping.is_set())

    def test_segmented_offline_provider_decodes_outside_capture_callback(self):
        owner = self
        class Provider:
            def load_model(self): pass
            def _recognize(self, audio, rate, cancelled):
                owner.assertEqual(len(audio), 160000); return 'sensevoice text'
        track = SegmentedApplicationAudioTrack(self.capture, Provider(), target='lesson',
            on_transcript=self.transcripts.append, segment_seconds=5,
            media_time_seconds=120, playback_rate=2)
        self.addCleanup(track.stop)
        track.start()
        for _ in range(5): self.capture.callback(b'\0' * 32000)
        for _ in range(30):
            if self.transcripts: break
            threading.Event().wait(.01)
        self.assertEqual(self.transcripts[-1].text, 'sensevoice text')
        self.assertEqual(self.transcripts[-1].metadata['transcription'], 'sherpa-onnx-sensevoice')
        self.assertFalse(self.transcripts[-1].metadata['media_position_known'])
        self.assertIsNone(self.transcripts[-1].metadata['media_time_seconds'])
        self.assertIsNone(self.transcripts[-1].media_time_seconds)
        track.stop()

    def test_segmented_stop_discards_queued_result(self):
        entered, release = threading.Event(), threading.Event()
        class Provider:
            def load_model(self): pass
            def _recognize(self, audio, rate, cancelled):
                entered.set(); release.wait(2); return 'late'
        track = SegmentedApplicationAudioTrack(self.capture, Provider(), target='lesson',
            on_transcript=self.transcripts.append, segment_seconds=5)
        self.addCleanup(track.stop)
        track.start()
        for _ in range(5): self.capture.callback(b'\0' * 32000)
        self.assertTrue(entered.wait(2)); stopper=threading.Thread(target=track.stop);stopper.start()
        release.set();stopper.join(3)
        self.assertFalse(self.transcripts)

    def test_sensevoice_factory_selects_segmented_track_and_rejects_unknown(self):
        with patch('extensions.companion.application_audio.ProcessAudioCapture', return_value=self.capture), \
             patch('extensions.companion.application_audio.SenseVoicePcmProvider') as provider:
            track = ApplicationAudioTrack.configured(helper='fixture', process_id=5,
                creation_time='7', model_path=self.folder.name, target='lesson',
                approved=True, on_transcript=self.transcripts.append,
                provider='sherpa-onnx-sensevoice')
            self.assertIsInstance(track, SegmentedApplicationAudioTrack)
            self.assertIs(track.provider, provider.return_value)
            with self.assertRaises(ValueError):
                ApplicationAudioTrack.configured(helper='fixture', process_id=5,
                    creation_time='7', model_path=self.folder.name, target='lesson',
                    approved=True, on_transcript=self.transcripts.append, provider='unknown')

    def test_slow_decode_does_not_block_capture_and_overflow_is_explicit(self):
        entered, release, sent = threading.Event(), threading.Event(), threading.Event()
        class Provider:
            def load_model(self): pass
            def _recognize(self, audio, rate, cancelled):
                entered.set(); release.wait(3); return 'late'
        track = SegmentedApplicationAudioTrack(self.capture, Provider(), target='lesson',
            on_transcript=self.transcripts.append, segment_seconds=1)
        self.addCleanup(track.stop)
        self.addCleanup(release.set)
        track.start()
        self.capture.callback(b'\0'*32000)
        self.assertTrue(entered.wait(2))
        def feed():
            for _ in range(3): self.capture.callback(b'\0'*32000)
            sent.set()
        feeder = threading.Thread(target=feed)
        feeder.start()
        try:
            self.assertTrue(sent.wait(1), 'capture waited for blocked decoder')
            self.assertEqual(track.status()['error'], 'asr_queue_overflow')
            self.assertEqual(track.status()['state'], 'error')
        finally:
            release.set(); feeder.join(3); track.stop()
        self.assertEqual(self.transcripts, [])

    def test_segmented_start_failure_reclaims_thread_and_restart_discards_partial(self):
        emitted = threading.Event()
        class Provider:
            def load_model(self): pass
            def _recognize(self, audio, rate, cancelled): return 'new'
        def publish(item): self.transcripts.append(item); emitted.set()
        track = SegmentedApplicationAudioTrack(self.capture, Provider(), target='lesson',
            on_transcript=publish, segment_seconds=1)
        self.addCleanup(track.stop)
        start = self.capture.start
        def fail(callback): raise OSError('helper failure')
        self.capture.start = fail
        with self.assertRaises(OSError): track.start()
        self.assertIsNone(track._thread)
        self.capture.start = start
        track.start(); self.capture.callback(b'\0'*16000); track.stop()
        track.start(); self.capture.callback(b'\0'*32000)
        self.assertTrue(emitted.wait(2))
        self.assertEqual(len(self.transcripts), 1)
        self.assertEqual(self.transcripts[0].metadata['capture_start_offset_seconds'], 0)
        self.assertEqual(self.transcripts[0].metadata['capture_offset_seconds'], 1)
