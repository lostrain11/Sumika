"""P12 sequence detection: episode freshness, per-episode signature dedup,
promotion thresholds, ask-candidate selection, robust anomaly honesty."""
import unittest

from extensions.behavior.sequences import (
    EpisodeTracker, merge_actions, robust_anomaly, select_ask_candidate)


class MergeTests(unittest.TestCase):
    def test_consecutive_same_kind_merges(self):
        self.assertEqual(merge_actions(['typing', 'typing', 'scroll',
                                        'scroll', 'enter']),
                         ['typing_run', 'scroll_run', 'enter'])

    def test_actions_are_bounded_kind_names(self):
        with self.assertRaises(ValueError):
            merge_actions(['x' * 65])
        with self.assertRaises(ValueError):
            merge_actions([42])


class EpisodeTests(unittest.TestCase):
    def tracker(self, now=None):
        clock = {'now': 1000.0}
        tracker = EpisodeTracker(clock=lambda: clock['now'])
        return tracker, clock

    def feed(self, tracker, clock, action, target='lesson-a', **kwargs):
        return tracker.observe(action, target=target, **kwargs)

    def test_idle_gap_ends_the_episode(self):
        tracker, clock = self.tracker()
        tracker.observe('typing', target='lesson-a')
        clock['now'] += 61
        finished = self.feed(tracker, clock, 'click')
        # The idle gap closed one episode; a single action has no
        # 2-gram candidate yet, and the next action started episode 2.
        self.assertEqual(finished, [])
        self.assertEqual(tracker.episode_count, 2)
        clock['now'] += 1
        finished = self.feed(tracker, clock, 'scroll')
        tracker.observe('enter', target='lesson-a')
        found = tracker.end()
        self.assertTrue(any(item['signature'] == 'click|scroll|enter'
                            for item in found))

    def test_target_change_ends_the_episode(self):
        tracker = EpisodeTracker(
            clock=lambda: 0.0,
            same_session=lambda old, new: old == new)
        tracker.observe('typing', target='lesson-a')
        finished = tracker.observe('click', target='lesson-b')
        self.assertEqual(tracker.episode_count, 2)
        self.assertEqual(finished, [])  # single action, no 2-gram yet

    def test_same_target_page_turns_stay_one_session(self):
        tracker, clock = self.tracker()
        tracker.observe('typing', target='lesson-a')
        finished = self.feed(tracker, clock, 'click', target='lesson-a#p2')
        self.assertEqual(finished, [])  # page turns are not a new session

    def test_paused_stream_ends_without_recording_the_action(self):
        tracker, clock = self.tracker()
        tracker.observe('typing', target='lesson-a')
        finished = self.feed(tracker, clock, 'click', paused=True)
        # The paused action is dropped: episode 1 ended, nothing started.
        self.assertEqual((finished, tracker.episode_count), ([], 1))

    def test_capture_gap_ends_the_episode(self):
        tracker, clock = self.tracker()
        tracker.observe('typing', target='lesson-a')
        finished = self.feed(tracker, clock, 'click', gap=True)
        # Same: the gapped action never starts a new episode.
        self.assertEqual((finished, tracker.episode_count), ([], 1))


class CandidateTests(unittest.TestCase):
    def candidates_for(self, actions, clock_step=1.0):
        tracker = EpisodeTracker(clock=lambda: 0.0)
        found = []
        for index, action in enumerate(actions):
            found.extend(tracker.observe(action, target='lesson'))
        found.extend(tracker.end())
        return found

    def test_ngram_lengths_and_tail_window(self):
        found = self.candidates_for(['a', 'b', 'c', 'd'])
        lengths = sorted(item['length'] for item in found)
        # n-grams 2..6 ending at the tail; 4 actions -> lengths 2,3,4.
        self.assertEqual(lengths, [2, 3, 4])
        long_sequence = [f'kind{index}' for index in range(10)]
        found = self.candidates_for(long_sequence)
        self.assertTrue(all(item['length'] <= 6 for item in found))

    def test_per_episode_signature_counted_once(self):
        found = self.candidates_for(['typing', 'scroll', 'typing', 'scroll'])
        signatures = [item['signature'] for item in found]
        self.assertEqual(len(signatures), len(set(signatures)))

    def test_max_five_new_candidates_per_episode(self):
        found = self.candidates_for([f'kind{index}' for index in range(8)])
        self.assertLessEqual(len(found), 5)

    def test_merged_runs_form_one_kind(self):
        found = self.candidates_for(['typing', 'typing', 'scroll'])
        signatures = ' '.join(item['signature'] for item in found)
        self.assertIn('typing_run|scroll', signatures)
        self.assertNotIn('typing|typing', signatures)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory(prefix='p12-promo-')
        self.addCleanup(self._tmp.cleanup)
        from extensions.behavior.library import BehaviorLibrary
        self.library = BehaviorLibrary(Path(self._tmp.name)/'behavior.sqlite3')
        self.scope = {'user': 'project-1', 'session': None}

    def test_candidate_needs_three_episodes_across_two_sessions(self):
        signature = 'typing|scroll|enter'
        def record(episode_id, session):
            return self.library.record_episode({
                'episode_id': episode_id, 'pattern': signature,
                'started_at': '2026-10-14T00:00:00+00:00',
                'ended_at': '2026-10-14T00:01:00+00:00',
                'session': session}, scope=self.scope)
        record('ep1', 'session-1')
        record('ep2', 'session-1')
        support = self.library.pattern_candidates(signature, scope=self.scope)
        self.assertEqual(support['episodes'], 2)
        self.assertEqual(support['sessions'], 1)
        record('ep3', 'session-2')
        support = self.library.pattern_candidates(signature, scope=self.scope)
        self.assertEqual((support['episodes'], support['sessions']), (3, 2))
        # Promotion threshold met: the candidate can be recorded (active=0
        # until a user confirms it — never self-confirmed).
        promoted = self.library.promote_pattern(
            signature, scope=self.scope, derived_version='seq-v1',
            supports=self.library.pattern_supports(signature, scope=self.scope))
        self.assertEqual(promoted['status'], 'promoted')
        self.assertNotIn(signature, self.library.confirmed_patterns(
            scope=self.scope))

    def test_duplicate_episode_and_pattern_are_idempotent(self):
        episode = {'episode_id': 'ep1', 'pattern': 'typing|scroll',
                   'started_at': '2026-10-14T00:00:00+00:00',
                   'ended_at': '2026-10-14T00:01:00+00:00', 'session': 's1'}
        first = self.library.record_episode(episode, scope=self.scope)
        second = self.library.record_episode(dict(episode), scope=self.scope)
        self.assertEqual(first['status'], 'recorded')
        self.assertEqual(second['status'], 'duplicate')
        self.library.promote_pattern('typing|scroll', scope=self.scope,
                                     derived_version='seq-v1')
        again = self.library.promote_pattern('typing|scroll', scope=self.scope,
                                             derived_version='seq-v1')
        self.assertEqual(again['status'], 'duplicate')


class AskCandidateTests(unittest.TestCase):
    def test_confirmed_pattern_wins_over_longer_supported(self):
        candidates = [{'signature': 'a|b', 'length': 2, 'supported': True},
                      {'signature': 'c|d|e', 'length': 3, 'supported': True}]
        choice = select_ask_candidate(confirmed_patterns=['a|b'],
                                      candidates=candidates,
                                      episode_id='ep1')
        self.assertEqual(choice['signature'], 'a|b')
        self.assertEqual(choice['reason'], 'confirmed')

    def test_longest_supported_breaks_by_stable_id(self):
        candidates = [{'signature': 'b|c|d', 'length': 3, 'supported': True},
                      {'signature': 'a|b|c', 'length': 3, 'supported': True}]
        choice = select_ask_candidate(confirmed_patterns=[], candidates=candidates,
                                      episode_id='ep1')
        self.assertEqual(choice['signature'], 'b|c|d')

    def test_no_candidate_without_support(self):
        choice = select_ask_candidate(
            confirmed_patterns=[], episode_id='ep1',
            candidates=[{'signature': 'a|b', 'length': 2,
                         'supported': False}])
        self.assertIsNone(choice)


class AnomalyTests(unittest.TestCase):
    def sample(self, session):
        return {'value': 10.0, 'session': session}

    def test_refuses_thin_data_and_degenerate_mad(self):
        values = [self.sample(f's{i}') for i in range(2)]
        self.assertIsNone(robust_anomaly(values, 99))
        flat = [self.sample(f's{i // 10}') for i in range(20)]
        self.assertIsNone(robust_anomaly(flat, 99))  # MAD == 0

    def test_requires_three_sessions(self):
        values = [self.sample('s1') for _ in range(10)] + \
                 [self.sample('s2') for _ in range(10)]
        self.assertIsNone(robust_anomaly(values, 99))

    def test_robust_z_flags_and_keeps_baseline(self):
        values = []
        for index, value in enumerate(list(range(20))):
            values.append({'value': float(value),
                           'session': f's{index % 4}'})
        result = robust_anomaly(values, 60.0, baseline='seq-v1')
        self.assertIsNotNone(result)
        self.assertGreater(result['z'], 3.5)
        self.assertEqual(result['baseline'], 'seq-v1')
        # A value inside the distribution is not flagged: novel is not
        # abnormal.
        self.assertIsNone(robust_anomaly(values, 19.0))


if __name__ == '__main__':
    unittest.main()
