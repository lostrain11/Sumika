import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from extensions.desktop.consultation_journal import ConsultationJournal
from extensions.desktop.consultation_response import baseline, correlate


def turn(role, text, terminal=True, id=''):
    return dict(role=role, text=text, terminal=terminal, id=id)


def snapshot(turns=(), **extra):
    return dict(ok=True, truncated=False, generating=False,
                url='https://chatgpt.com/c/test', turns=list(turns), **extra)


class ResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='.sumika-next')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'journal.db'
        self.journal = ConsultationJournal(self.path)
        self.binding = dict(session_id='s', tab_id=1, browser_instance_id='b', agent_window_id=2)
        self.prior = [turn('user', 'old'), turn('assistant', 'old answer')]
        self.context = baseline(snapshot(self.prior), 'chatgpt.com', 'review', self.binding)
        self.answer = snapshot(self.prior+[turn('user', 'review'), turn('assistant', 'possible problem')])
        self.dispatch = Mock(return_value={'submitted': True})

    def submit(self, **extra):
        return self.journal.submit('r', site='chatgpt.com', prompt='review', binding=self.binding,
                                   approved=True, preflight=lambda:None, dispatch=self.dispatch,
                                   capture=lambda:snapshot(self.prior), **extra)

    def test_old_answer_never_completes(self):
        self.assertEqual(correlate(self.context, snapshot(self.prior))['state'], 'unknown')

    def test_streaming_missing_marker_and_truncation(self):
        for mutation in ({'generating': True}, {'truncated': True}, {'ok': False}):
            self.assertEqual(correlate(self.context, {**self.answer, **mutation})['state'], 'unknown')
        self.answer['turns'][-1]['terminal'] = False
        for _ in range(3):
            self.assertEqual(correlate(self.context, self.answer)['state'], 'unknown')

    def test_wrong_user_extra_turn_and_edited_history(self):
        for turns in (
            self.prior+[turn('user', 'wrong'), turn('assistant', 'answer')],
            self.answer['turns']+[turn('user', 'next')],
            [turn('user', 'edited')]+self.answer['turns'][1:],
            self.prior+[turn('assistant', 'review')],
        ):
            self.assertEqual(correlate(self.context, snapshot(turns))['state'], 'unknown')

    def test_thread_and_origin_changes(self):
        for url in ('https://chatgpt.com/c/other', 'https://evil.test/c/test', 'http://chatgpt.com/c/test'):
            self.assertEqual(correlate(self.context, {**self.answer, 'url':url})['state'], 'unknown')

    def test_baseline_committed_before_dispatch_and_no_raw_history(self):
        def dispatch():
            context = ConsultationJournal(self.path).response_context('r')
            self.assertEqual(context, self.context)
            return {'submitted': True}
        self.dispatch.side_effect = dispatch
        self.submit()
        raw = self.path.read_bytes()
        self.assertNotIn(b'old answer', raw)
        self.assertNotIn(b'"text": "old"', raw)

    def test_restart_collect_and_duplicate_do_not_resend(self):
        self.submit()
        restored = ConsultationJournal(self.path)
        result = restored.collect('r', binding=self.binding, capture=lambda:self.answer)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['response']['text'], 'possible problem')
        self.assertIn('Not authorization', result['response']['boundary'])
        self.assertEqual(self.submit()['state'], 'completed')
        self.dispatch.assert_called_once()

    def test_read_timeout_unknown_and_cancel_persisted(self):
        self.submit()
        result = self.journal.collect('r', binding=self.binding, capture=Mock(side_effect=TimeoutError()))
        self.assertEqual(result['response']['state'], 'unknown')
        self.journal.cancel('r')
        capture = Mock(return_value=self.answer)
        result = ConsultationJournal(self.path).collect('r', binding=self.binding, capture=capture)
        self.assertEqual(result['state'], 'cancelled')
        capture.assert_not_called()
        self.assertEqual(self.submit()['state'], 'cancelled')
        self.dispatch.assert_called_once()

    def test_changed_binding_and_legacy_baseline_refused(self):
        self.submit()
        with self.assertRaises(PermissionError):
            self.journal.collect('r', binding={**self.binding, 'tab_id':2}, capture=lambda:self.answer)
        with self.assertRaises(ValueError):
            self.journal.response_context('legacy-request')

    def test_homepage_redirect_pinned_on_user_turn(self):
        context = baseline(snapshot(), 'chatgpt.com', 'review', self.binding)
        user = {**snapshot([turn('user', 'review')]), 'url':'https://chatgpt.com/c/new'}
        result = correlate(context, user)
        context['thread_url'] = result['thread_url']
        self.assertEqual(correlate(context, {**user, 'url':'https://chatgpt.com/c/other'})['reason'], 'thread_changed')

    def test_user_turn_before_spa_redirect_does_not_pin_homepage(self):
        home = {**snapshot(), 'url':'https://chatgpt.com/'}
        context = baseline(home, 'chatgpt.com', 'review', self.binding)
        early = {**home, 'turns':[turn('user','review')]}
        self.assertEqual(correlate(context, early), {'state':'unknown','reason':'awaiting_thread_identity'})
        context['thread_url'] = home['url']  # Recover earlier home-page pin without replay.
        answer = {**self.answer, 'turns':[turn('user','review'),turn('assistant','answer')]}
        self.assertEqual(correlate(context, answer)['state'], 'completed')
        provisional = {**early, 'url':'https://chatgpt.com/c/WEB:local-id'}
        self.assertEqual(correlate(context, provisional)['reason'], 'awaiting_thread_identity')
        context['thread_url'] = provisional['url']
        self.assertEqual(correlate(context, answer)['state'], 'completed')

    def test_prior_incomplete_answer_rejects_before_send(self):
        for snap in ({**snapshot(self.prior), 'generating':True}, snapshot([turn('user','old')]),
                     snapshot([turn('assistant','unfinished',terminal=False)])):
            with self.assertRaises(ValueError):
                baseline(snap, 'chatgpt.com', 'review', self.binding)

    def test_kimi_provisional_thread_is_not_a_final_identity(self):
        home={**snapshot(),'url':'https://www.kimi.com/'}
        context=baseline(home,'www.kimi.com','review',self.binding)
        provisional={**home,'url':'https://www.kimi.com/chat/pd5dc799-76da-4b6e-bfa2-71b54d3f9f33',
                     'turns':[turn('user','review')]}
        self.assertEqual(correlate(context,provisional)['reason'],'awaiting_thread_identity')
        context['thread_url']=provisional['url']
        answer={**home,'url':'https://www.kimi.com/chat/1a0ae6e6-33b2-86c8-8000-09e494331d2c',
                'turns':[turn('user','review'),turn('assistant','answer')]}
        self.assertEqual(correlate(context,answer)['state'],'completed')
        context['thread_url']=answer['url']
        self.assertEqual(correlate(context,{**answer,'url':answer['url']+'x'})['reason'],'thread_changed')
