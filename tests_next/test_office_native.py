import json
from pathlib import Path
import tempfile
import unittest

from extensions.office.native import configure, payload, engine_config, REQUIRED, IDS


class NativeOfficeTests(unittest.TestCase):
    def test_relocation_refresh_and_missing_payload_remove_only_owned_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base = root/'runtime/office'
            site = base/'dependencies/python/Lib/site-packages'
            for name in REQUIRED:
                (site/name).mkdir(parents=True)
            (base/'dependencies/python/python.exe').touch()
            manifest = base/'runtime.json'
            manifest.write_text(json.dumps({'platform':'win32','arch':'x64'}))
            for name in ('dsh-skill-office','dsh-tool-workspace-dependencies'):
                path = root/'runtime/dsh/node_modules/@deepseek-ai'/name/'lib/index.js'
                path.parent.mkdir(parents=True);path.touch()
            foreign = {'id':'user-office','name':'user-custom'}
            rows = [{'insert':[foreign,{'id':IDS[0],'name':'stale'}]}]
            self.assertTrue(configure(rows,root))
            count = len(rows)
            self.assertTrue(configure(rows,root))
            self.assertEqual(len(rows),count)
            entries = [item for row in rows for item in row.get('insert',[])]
            self.assertEqual(entries.count(foreign),1)
            self.assertEqual(sum(e.get('id')==IDS[0] for e in entries),1)
            target = next(e for e in entries if e.get('id')==IDS[1])
            self.assertEqual(target['config']['source'],str(base.resolve()))
            (site/'docx').rmdir()
            self.assertIsNone(payload(root))
            self.assertFalse(configure(rows,root))
            self.assertEqual([e for r in rows for e in r.get('insert',[])],[foreign])

    def test_invalid_manifest_is_not_a_usable_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'runtime/office/runtime.json'
            path.parent.mkdir(parents=True)
            for value in ('[]','null','{broken'):
                path.write_text(value)
                self.assertIsNone(payload(folder))

    def test_native_engine_requires_complete_shipped_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            node=root/'runtime/node/node.exe'
            node.parent.mkdir(parents=True);node.touch()
            base=root/'runtime/dsh/node_modules/@deepseek-ai'
            files=[base/'libreoffice-kit/lib/cli.js',
                   base/'libreoffice-kit-win32-x64/bin/libreoffice-kit.exe',
                   base/'libreoffice-kit-win32-x64/program/program/fundamental.ini']
            for path in files:
                self.assertEqual(engine_config(root),{'cli':False})
                path.parent.mkdir(parents=True,exist_ok=True);path.touch()
            config=engine_config(root)
            self.assertEqual(config,{'node':str(node.resolve()),'cli':str(files[0].resolve())})
            files[1].unlink()
            self.assertEqual(engine_config(root),{'cli':False})
