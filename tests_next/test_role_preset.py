import json
import tempfile
import unittest
from pathlib import Path
from extensions.roles.preset import install


class PresetTests(unittest.TestCase):
    def test_explicit_selection_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config=root/'role.json';config.write_text(json.dumps({'role_model':'role'}))
            kwargs=dict(provider='p',model='role',runtime_entry=config,role_config=config,workspace=root,python=config)
            preset=install(root/'preset',**kwargs)
            original=(preset/'agent.cordis.yml').read_bytes()
            with self.assertRaises(FileExistsError):install(root/'preset',**kwargs)
            self.assertEqual((preset/'agent.cordis.yml').read_bytes(),original)
            kwargs['model']='different'
            with self.assertRaises(ValueError):install(root/'invalid',**kwargs)
            self.assertFalse((root/'invalid').exists())
