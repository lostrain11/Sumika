import unittest

from extensions.companion.media_clock import PlayerClockCorrelation


class MediaClockTests(unittest.TestCase):
    def setUp(self):
        self.identity = {'url':'video', 'media_instance':1, 'timeline_revision':0}
        self.clock = PlayerClockCorrelation(target='lesson',media_identity=self.identity,
                                             owner_verified=True)

    def sample(self, seconds, media=None, **changes):
        value = dict(target='lesson',media_identity=self.identity,
            qpc_before=int(seconds*10000000),qpc_after=int(seconds*10000000)+10000,
            media_time_seconds=10+seconds if media is None else media,
            playback_rate=1,paused=False,seeking=False,ended=False)
        value.update(changes)
        return self.clock.observe(**value)

    def span(self, start=0.25, end=0.75, **changes):
        value = dict(known=True,clock_scope='native-segment-audio',qpc_unit='100ns',
            start_qpc_position=int(start*10000000),end_qpc_position=int(end*10000000))
        value.update(changes)
        return self.clock.correlate(value,target='lesson',media_identity=self.identity)

    def populate(self):
        for value in (0,0.5,1):
            self.sample(value)

    def test_owner_verification_required(self):
        with self.assertRaises(PermissionError):
            PlayerClockCorrelation(target='lesson',media_identity=self.identity)

    def test_known_interval_requires_brackets_for_both_endpoints(self):
        self.populate()
        result = self.span()
        self.assertTrue(result['known'])
        for bounds, expected in ((result['start_seconds_bounds'],10.25),
                                  (result['end_seconds_bounds'],10.75)):
            self.assertLessEqual(bounds[0],expected)
            self.assertGreaterEqual(bounds[1],expected)
            self.assertLess(bounds[1]-bounds[0],0.11)
        self.assertFalse(self.span(end=1.2)['known'])
        self.assertFalse(self.span(start=0)['known'])

    def test_pause_seek_end_clear_all_old_segments(self):
        for state in ('paused','seeking','ended'):
            with self.subTest(state=state):
                self.populate()
                self.assertFalse(self.sample(1.5,**{state:True}))
                self.assertFalse(self.span()['known'])

    def test_identity_change_and_revocation_permanently_fence(self):
        self.populate()
        with self.assertRaises(PermissionError):
            self.sample(1.5,media_identity={**self.identity,'timeline_revision':1})
        self.assertFalse(self.span()['known'])
        with self.assertRaises(PermissionError):
            self.sample(2)

    def test_buffering_rate_change_gap_and_unannounced_seek_reset(self):
        for changes in ({'media_time_seconds':11},{'media_time_seconds':90},
                        {'playback_rate':2},{'qpc_before':30000000,'qpc_after':30010000}):
            with self.subTest(changes=changes):
                self.clock = PlayerClockCorrelation(target='lesson',media_identity=self.identity,
                                                     owner_verified=True)
                self.populate()
                self.sample(1.5,**changes)
                self.assertFalse(self.span()['known'])

    def test_invalid_nonmonotonic_samples_clear_old_evidence(self):
        for changes in ({'qpc_after':3000000},{'media_time_seconds':float('nan')},
                        {'paused':0},{'qpc_before':True},{'playback_rate':0}):
            with self.subTest(changes=changes):
                self.clock = PlayerClockCorrelation(target='lesson',media_identity=self.identity,
                                                     owner_verified=True)
                self.populate()
                with self.assertRaises(ValueError):
                    self.sample(1.5,**changes)
                self.assertFalse(self.span()['known'])
        self.populate()
        with self.assertRaises(ValueError):
            self.sample(0.9)
        self.assertFalse(self.span()['known'])

    def test_invalid_native_scope_or_missing_clock_is_unknown(self):
        self.populate()
        for changes in ({'known':False},{'qpc_unit':'ns'},
                        {'clock_scope':'native-packet-start'},
                        {'start_qpc_position':True},{'end_qpc_position':0}):
            with self.subTest(changes=changes):
                self.assertFalse(self.span(**changes)['known'])

    def test_double_speed_bounds_use_player_rate(self):
        for seconds in (0,0.5,1):
            self.sample(seconds,media=10+seconds*2,playback_rate=2)
        value = self.span()
        self.assertTrue(value['known'])
        self.assertLessEqual(value['end_seconds_bounds'][0],11.5)
        self.assertGreaterEqual(value['end_seconds_bounds'][1],11.5)

    def test_sample_memory_is_bounded(self):
        for index in range(300):
            self.sample(index*0.1)
        self.assertEqual(len(self.clock._samples),256)
        self.assertFalse(self.span()['known'])
