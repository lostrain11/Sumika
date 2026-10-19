"""P15 routing engine: manual lock, debounce, qualification, rate limits,
garbage responses, epochs — all with an injected fake classifier."""
import unittest

from extensions.behavior.profiles import CompanionProfileStore
from extensions.behavior.routing import RoutingEngine


class Harness(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory(prefix='p15-routing-')
        self.addCleanup(self._tmp.cleanup)
        from pathlib import Path
        self.root = Path(self._tmp.name)
        self.store = CompanionProfileStore(self.root)
        state = self.store.load()
        self.revision = state['revision']
        # Auto policy is the routing path under test; the study template's
        # 300s interval etc. stay template defaults.
        self.store.select('auto', expected_revision=self.revision)
        self.study_id, self.game_id = (state['profiles'][0]['id'],
                                       state['profiles'][1]['id'])
        self.clock = {'now': 1000.0}
        self.classifications = []
        self.responses = {}  # target_key -> raw classifier response

        def classifier(request):
            self.classifications.append(request)
            key = self._last_key
            response = self.responses.get(key)
            if isinstance(response, Exception):
                raise response
            return response
        self._last_key = None
        engine_view = {}

        # Wrap the engine's target key extraction to know the current target.
        self.engine = RoutingEngine(
            store=self.store, classifier=classifier,
            clock=lambda: self.clock['now'])
        original = self.engine._target_key
        def tracked(material):
            self._last_key = original(material)
            return original(material)
        self.engine._target_key = tracked
        self.identity = {'handle': 1, 'process_id': 2, 'process_creation': 'c'}

    def material(self, key='lesson.pdf', title='教材'):
        return {'identity_key': key, 'title': title}

    def respond(self, response, target_key='lesson.pdf'):
        self.responses[target_key] = response
        self._last_key = target_key

    def classifier_requests(self):
        return len(self.classifications)

    def classify(self, material=None):
        material = material or self.material()
        self.engine.on_foreground(self.identity, material=material)
        self.clock['now'] += 2.01
        return self.engine.on_foreground(self.identity, material=material)

    def apply(self, material=None):
        self.classify(material)
        self.clock['now'] += 8.01
        return self.engine.on_foreground(self.identity, material=material or self.material())


class ManualAndControlTests(Harness):
    def test_manual_never_calls_the_classifier(self):
        self.store.select('manual', self.study_id,
                          expected_revision=self.store.load()['revision'])
        self.respond({'profile_id': self.study_id, 'score': 0.99})
        view = self.engine.on_foreground(self.identity,
                                         material=self.material())
        self.assertEqual(view['reason'], 'manual')
        self.assertEqual(view['effective_profile_id'], self.study_id)
        self.assertEqual(self.classifier_requests(), 0)

    def test_suspended_reports_and_cancels_in_flight(self):
        self.engine.set_suspended(True)
        self.respond({'profile_id': self.study_id, 'score': 0.99})
        view = self.engine.on_foreground(self.identity,
                                         material=self.material())
        self.assertEqual(view['reason'], 'suspended')
        self.assertIsNone(view['effective_profile_id'])
        self.assertEqual(self.classifier_requests(), 0)

    def test_config_change_advances_routing_epoch(self):
        # Advance past any classification bookkeeping first.
        self.engine.on_config_changed()
        before = self.engine.view()['routing_epoch']
        self.engine.on_config_changed()
        self.assertEqual(self.engine.view()['routing_epoch'], before + 1)

    def test_no_enabled_profiles_is_unknown(self):
        self.store.delete(self.study_id,
                          expected_revision=self.store.load()['revision'])
        self.store.delete(self.game_id,
                          expected_revision=self.store.load()['revision'])
        self.respond({'profile_id': 'x', 'score': 1.0})
        view = self.engine.on_foreground(self.identity,
                                         material=self.material())
        self.assertEqual(view['reason'], 'unknown')
        self.assertEqual(self.classifier_requests(), 0)


class DebounceTests(Harness):
    def test_new_identity_binds_after_two_stable_seconds(self):
        identity_a = self.identity
        identity_b = {'handle': 9, 'process_id': 9, 'process_creation': 'c9'}
        self.engine.on_foreground(identity_a, material=self.material())
        before = self.engine.view()['foreground_epoch']
        self.clock['now'] += 1
        self.engine.on_foreground(identity_b, material=self.material('game'))
        self.assertEqual(self.engine.view()['foreground_epoch'], before)
        self.clock['now'] += 2.1  # >2s stable on identity_b
        self.engine.on_foreground(identity_b, material=self.material('game'))
        self.assertGreater(self.engine.view()['foreground_epoch'], before)

    def test_unavailable_foreground_immediately_unbinds(self):
        self.engine.on_foreground(self.identity, material=self.material())
        bound = self.engine.view()['foreground_epoch']
        view = self.engine.on_foreground(None, material=self.material())
        self.assertEqual(view['reason'], 'suspended')
        # Returning re-binds only after the stable window again.
        self.clock['now'] += 0.5
        self.engine.on_foreground(self.identity, material=self.material())
        self.assertEqual(self.engine.view()['foreground_epoch'], bound)


class QualificationTests(Harness):
    def test_top_and_lead_qualified(self):
        self.respond({'profile_id': self.study_id, 'score': 0.9,
                      'scores': {self.study_id: 0.9, self.game_id: 0.4}})
        view = self.apply()
        self.assertEqual(view['reason'], 'matched')
        self.assertEqual(view['effective_profile_id'], self.study_id)
        self.assertEqual(view['score'], 0.9)

    def test_small_lead_is_ambiguous(self):
        self.respond({'profile_id': self.study_id, 'score': 0.9,
                      'scores': {self.study_id: 0.9, self.game_id: 0.85}})
        view = self.classify()
        self.assertEqual(view['reason'], 'ambiguous')
        self.assertIsNone(view['effective_profile_id'])
        self.assertEqual(view['candidate_profile_id'], self.study_id)

    def test_low_top_is_unknown(self):
        self.respond({'profile_id': self.study_id, 'score': 0.6,
                      'scores': {self.study_id: 0.6, self.game_id: 0.1}})
        view = self.classify()
        self.assertEqual(view['reason'], 'unknown')
        self.assertEqual(self.classifier_requests(), 1)

    def test_garbage_responses_are_unknown_without_fallback(self):
        cases = [
            {'profile_id': 'missing-id', 'score': 0.99},
            {'profile_id': self.study_id, 'score': float('nan')},
            {'profile_id': self.study_id, 'score': 1.5},
            {'profile_id': self.study_id, 'score': '0.9'},
            {'no_profile_id': True},
            None,
        ]
        for index, response in enumerate(cases):
            self.respond(response, target_key=f'target-{index}')
            self.clock['now'] += 100  # bypass the repeat window per case
            view = self.classify(self.material(f'target-{index}'))
            self.assertEqual(view['reason'], 'unknown', msg=response)

    def test_raising_classifier_is_unknown(self):
        self.respond(RuntimeError('model exploded'), target_key='lesson.pdf')
        view = self.classify()
        self.assertEqual(view['reason'], 'unknown')
        self.assertEqual(self.classifier_requests(), 1)


class RateLimitTests(Harness):
    def setUp(self):
        super().setUp()
        self.respond({'scores': {self.study_id: .95, self.game_id: .1}})

    def test_first_foreground_waits_then_candidate_waits_eight_seconds(self):
        view = self.engine.on_foreground(self.identity, material=self.material())
        self.assertEqual(self.classifier_requests(), 0)
        self.clock['now'] += 1.99
        self.engine.on_foreground(self.identity, material=self.material())
        self.assertEqual(self.classifier_requests(), 0)
        self.clock['now'] += .02
        view = self.engine.on_foreground(self.identity, material=self.material())
        self.assertEqual(self.classifier_requests(), 1)
        self.assertIsNone(view['effective_profile_id'])
        self.clock['now'] += 7.99
        self.assertIsNone(self.engine.on_foreground(self.identity,
            material=self.material())['effective_profile_id'])
        self.clock['now'] += .02
        self.assertEqual(self.engine.on_foreground(self.identity,
            material=self.material())['effective_profile_id'], self.study_id)

    def test_unchanged_scene_never_reclassifies_periodically(self):
        self.apply()
        for seconds in (31, 61, 600, 3600):
            self.clock['now'] += seconds
            self.engine.on_foreground(self.identity, material=self.material())
        self.assertEqual(self.classifier_requests(), 1)

    def test_changed_evidence_same_target_waits_minimum_thirty_seconds(self):
        self.classify()
        self.clock['now'] += 5
        self.engine.on_foreground(self.identity, material=self.material(title='新章节'))
        self.assertEqual(self.classifier_requests(), 1)
        self.clock['now'] += 25.01
        self.engine.on_foreground(self.identity, material=self.material(title='新章节'))
        self.assertEqual(self.classifier_requests(), 2)

    def test_new_material_cancels_candidate_and_waits_for_application(self):
        self.apply()
        self.respond({'scores': {self.study_id: .1, self.game_id: .95}}, 'game.exe')
        self.clock['now'] += 1
        material = self.material('game.exe')
        view = self.engine.on_foreground(self.identity, material=material)
        self.assertIsNone(view['effective_profile_id'])
        self.assertEqual(self.classifier_requests(), 2)
        self.clock['now'] += 8.01
        self.assertEqual(self.engine.on_foreground(self.identity,
            material=material)['effective_profile_id'], self.game_id)


class LateResponseTests(Harness):
    def run_race(self, mutation):
        import threading
        entered, release = threading.Event(), threading.Event()
        def classifier(request):
            entered.set()
            self.assertTrue(release.wait(3))
            return {'scores': {self.study_id: .99, self.game_id: .01}}
        self.engine._classifier = classifier
        self.engine.on_foreground(self.identity, material=self.material())
        self.clock['now'] += 2.01
        worker = threading.Thread(target=lambda: self.engine.on_foreground(
            self.identity, material=self.material()))
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            mutation()
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.clock['now'] += 10
        return self.engine.view()

    def test_pause_rejects_late_result(self):
        self.assertEqual(self.run_race(lambda: self.engine.set_suspended(True))['reason'], 'suspended')

    def test_unavailable_foreground_rejects_late_result(self):
        self.assertEqual(self.run_race(lambda: self.engine.on_foreground(None))['reason'], 'suspended')

    def test_manual_revision_rejects_late_auto_result(self):
        def manual():
            self.store.select('manual', self.game_id, expected_revision=self.store.load()['revision'])
            self.engine.on_foreground(self.identity, material=self.material())
        self.assertEqual(self.run_race(manual)['effective_profile_id'], self.game_id)

    def test_changed_config_rejects_late_result(self):
        def change():
            self.store.update(self.study_id, {'name': '改名'}, expected_revision=self.store.load()['revision'])
            self.engine.on_config_changed()
        self.assertIsNone(self.run_race(change)['effective_profile_id'])

    def test_target_change_rejects_late_result(self):
        self.assertIsNone(self.run_race(lambda: self.engine.on_foreground(
            {'handle': 3}, material=self.material('new')))['effective_profile_id'])

    def test_single_physical_request_even_when_cancel_is_ignored(self):
        def change():
            self.engine.on_foreground({'handle': 3}, material=self.material('new'))
            self.clock['now'] += 2.1
            self.engine.on_foreground({'handle': 3}, material=self.material('new'))
            self.assertIsNotNone(self.engine._request)
        self.run_race(change)


if __name__ == '__main__':
    unittest.main()
