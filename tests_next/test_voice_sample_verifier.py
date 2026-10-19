"""The acceptance report must measure completed synthesis, not playback admission."""
import unittest

from tools.verify_companion_voice_sample import decompose


class SampleTimingTests(unittest.TestCase):
    def test_waits_for_actual_synthesis_and_uses_first_segment_only(self):
        events = [
            {'name': 'user_started', 'elapsed_ms': 0},
            {'name': 'user_stopped', 'elapsed_ms': 100},
            {'name': 'transcribed', 'elapsed_ms': 150},
            {'name': 'playback_started', 'elapsed_ms': 151},
            {'name': 'synthesis_ready', 'elapsed_ms': 350},
            {'name': 'synthesis_ready', 'elapsed_ms': 500},
            {'name': 'playback_ended', 'elapsed_ms': 550},
        ]
        report = decompose(events, [160])
        self.assertEqual(report['turns'][0]['asr_to_first_synthesis_ready_ms'], 200)
        self.assertEqual(report['turns'][0]['asr_to_first_char_ms'], 10)
        self.assertNotIn('asr_to_first_audio_ms', report['turns'][0])

    def test_no_synthesis_event_does_not_claim_ready_audio(self):
        events = [{'name': name, 'elapsed_ms': at} for name, at in [
            ('user_started', 0), ('transcribed', 100),
            ('playback_started', 101), ('interrupted', 200)]]
        report = decompose(events, [])
        self.assertIsNone(report['summary']['asr_to_first_synthesis_ready_ms'])

    def test_two_turn_summary_uses_arithmetic_median(self):
        events = []
        for start, delay in [(0, 100), (1000, 300)]:
            events.extend({'name': name, 'elapsed_ms': at} for name, at in [
                ('user_started', start), ('transcribed', start + 10),
                ('synthesis_ready', start + 10 + delay),
                ('playback_ended', start + 500)])
        self.assertEqual(decompose(events, [])['summary'][
            'asr_to_first_synthesis_ready_ms']['median'], 200)
