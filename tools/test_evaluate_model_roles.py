import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sumika_core.account_routing import AccountRouting
from sumika_core.credentials import MemoryCredentialStore
from sumika_core.funding_ledger import FundingLedger
from sumika_core.provider_profiles import ProviderProfileManager
from sumika_core.route_pricing import PricingSnapshot, RoutePricingService
from sumika_core.storage import Storage
from tools.evaluate_model_roles import run
from tools.activate_model_roles import validate_report
from tools.activate_free_models import CHECKS
from tools.quality_smoke_leader import use_evaluated_executor


class RoleFundingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        storage = Storage(self.root / 'sumika.sqlite3')
        self.addCleanup(storage.close)
        profiles = ProviderProfileManager(storage, MemoryCredentialStore())
        profiles.save({'id': 'test', 'name': 'Test', 'base_url': 'https://api.deepseek.com/v1', 'model': 'fixture'})
        self.profile = profiles.get('test')
        accounts = AccountRouting(profiles, RoutePricingService(profiles, self.root), self.root)
        accounts.bind('test', 'deepseek', ['fixture'])
        accounts.close()
        self.price = PricingSnapshot('price', 'test', 'fixture', 'official', 'CNY',
            input_price_per_million=1, output_price_per_million=1, cash_currency='CNY', cash_rate=1,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        self.runtime = Mock(provider=None, timeout=60, last_usage={'input_tokens': 10, 'output_tokens': 20},
                            last_finish_reason='stop', last_response_model='fixture', last_reasoning_content_seen=False)
        self.runtime.stream.return_value = iter(['{"reuse":["a"],"pause":["b"],"wait":["c"],"run":["d"],"resubmit_unknown":false}'])
        self.args = SimpleNamespace(data_dir=self.root, credential_data_dir=self.root, profile='test',
                                    model='fixture', purpose='leader', budget='0.5', report=self.root / 'report.json')

    def evaluate(self, balance):
        with patch('tools.evaluate_model_roles.WindowsCredentialStore', return_value=MemoryCredentialStore()), \
             patch('tools.evaluate_model_roles.public_prices', return_value=([self.price], {'fixture': 'fixture'})), \
             patch('sumika_core.account_routing.read_account', return_value={'available': True, 'grant': '0', 'cash': balance}), \
             patch.object(ProviderProfileManager, 'runtime', return_value=self.runtime), \
             patch('builtins.print'):
            return run(self.args)

    def test_no_balance_prevents_paid_evaluation_send(self):
        report = self.evaluate('0')
        self.assertEqual(report['model_calls'], 0)
        self.assertEqual(report['samples'][0]['failure_class'], 'RequestNotSent')
        self.runtime.stream.assert_not_called()
        self.assertFalse(report['qualified'])

    def test_paid_evaluation_retains_usage_obligation(self):
        report = self.evaluate('1')
        self.assertEqual(report['model_calls'], 1)
        ledger = FundingLedger(self.root)
        self.addCleanup(ledger.close)
        rows = ledger.status()['reservations']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['state'], 'estimated')
        self.assertFalse(rows[0]['absorbed'])
        self.assertEqual(report['samples'][0]['funding']['source'], 'usage-priced-upper-bound')
        self.assertIsNone(report['samples'][0]['funding']['actual_cash_cny'])
        self.assertNotIn('api_key', json.dumps(report))

    def test_bounded_evidence_cannot_be_imported_as_leader_and_requires_current_binding(self):
        import time
        from sumika_core.provider_profiles import provider_execution_revision
        report = {'schema': 'sumika-role-evaluation/v1', 'purpose': 'bounded', 'profile_id': 'test',
                  'model_id': 'fixture', 'model_version': 'fixture', 'qualified': True, 'model_calls': 3,
                  'execution_revision': provider_execution_revision(self.profile, 'fixture'),
                  'samples': [{'id': name, 'passed': True, 'finish_reason': 'stop', 'observed_at': time.time(),
                               'response_digest': 'a' * 64, 'usage': {'input_tokens': 10, 'output_tokens': 10}}
                              for name, _, _ in CHECKS]}
        with self.assertRaises(ValueError):
            validate_report(report, self.profile)
        self.assertEqual(validate_report(report, self.profile, bounded=True), 'profile:test:fixture')
        service = Mock()
        service.app.storage.get_provider_profile.return_value = self.profile
        service.settings.return_value = {'candidate_pool': ['profile:test:fixture']}
        self.args.report.write_text(json.dumps(report), encoding='utf-8')
        self.assertEqual(use_evaluated_executor(service, self.args.report), 'profile:test:fixture')
        service.register_quality_evidence.assert_called_once()
        report['execution_revision'] = 'changed'
        self.args.report.write_text(json.dumps(report), encoding='utf-8')
        with self.assertRaises(ValueError):
            use_evaluated_executor(service, self.args.report)



if __name__ == '__main__':
    unittest.main()
