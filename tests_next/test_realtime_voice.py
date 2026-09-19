import unittest
from extensions.roles.realtime_voice import VoiceSession,VoiceState

class RealtimeVoiceTests(unittest.TestCase):
    def test_turn_lifecycle_and_cancel(self):
        s=VoiceSession();self.assertEqual(s.start_listening()['state'],'listening');s.audio_ready();s.transcribed('你好');s.responded('你好，我在。');self.assertEqual(s.playback_done()['state'],'idle');self.assertEqual(s.turn_id,1)
        s.start_listening();self.assertEqual(s.cancel()['state'],'cancelled');self.assertEqual(s.cancel()['state'],'cancelled')
    def test_invalid_transition_fails_closed(self):
        s=VoiceSession()
        with self.assertRaises(RuntimeError):s.transcribed('x')
        s.start_listening();s.audio_ready()
        with self.assertRaises(ValueError):s.transcribed('')
        s.fail('provider unavailable');self.assertEqual(s.state,VoiceState.ERROR)
