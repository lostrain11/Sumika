import json,tempfile,unittest
from pathlib import Path
from extensions.models.library import scan

class LibraryTests(unittest.TestCase):
    def test_readonly_discovery_overlap_and_incomplete_manifest(self):
        with tempfile.TemporaryDirectory(dir='.sumika-next') as folder:
            root=Path(folder).resolve();(root/'model.gguf').write_bytes(b'fixture')
            manifest=root/'manifests/registry.ollama.ai/library/test/latest';manifest.parent.mkdir(parents=True)
            descriptor={'digest':'sha256:'+'a'*64,'size':10}
            manifest.write_text(json.dumps({'config':descriptor,'layers':[]}),encoding='utf8')
            out=scan([str(root),str(root)])
            self.assertEqual(len(out['models']),2)
            self.assertEqual({m['status'] for m in out['models']},{'discovered','incomplete'})
            self.assertEqual((root/'model.gguf').read_bytes(),b'fixture')
            self.assertFalse(scan([str(root)],max_files=1)['complete'])

    def test_bad_roots_and_missing_path(self):
        with self.assertRaises(ValueError):scan(['relative'])
        with self.assertRaises(ValueError):scan(['E:/Models']*17)
        with tempfile.TemporaryDirectory(dir='.sumika-next') as folder:
            out=scan([str(Path(folder,'missing').resolve())])
            self.assertEqual(out['issues'][0]['status'],'missing')

    def test_manifest_traversal_is_not_followed(self):
        with tempfile.TemporaryDirectory(dir='.sumika-next') as folder:
            root=Path(folder).resolve();p=root/'manifests/x/y/z/tag';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'config':{'digest':'../../outside','size':1},'layers':[]}))
            out=scan([str(root)])
            self.assertEqual(out['models'],[]);self.assertEqual(len(out['issues']),1)
