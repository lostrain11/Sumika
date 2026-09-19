import json
from pathlib import Path
import unittest

class UIContractTests(unittest.TestCase):
    def test_contract_has_backend_states_and_boundaries(self):
        data=json.loads(Path('ui/ui-contract.json').read_text(encoding='utf8'))
        self.assertIn('unknown',data['states']);self.assertIn('UI-only success state',data['prohibited'])
    def test_prototype_integration_is_separate_module(self):
        text=Path('ui/prototype-d/integration.js').read_text(encoding='utf8')
        self.assertIn('sumika:backend-state',text);self.assertIn('publishBackendState',text)
