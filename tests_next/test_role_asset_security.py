from pathlib import Path
import tempfile
import unittest
import zipfile
import json
from unittest.mock import patch
from extensions.roles.roles import import_package,import_card,load_role
from extensions.roles.assets import inspect_vrm


class AssetTests(unittest.TestCase):
    def test_publication_conflict_does_not_replace_concurrent_role(self):
        base=Path('.sumika-next/test-role-publication');base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as d:
            root=Path(d);card=root/'card.json'
            card.write_text(json.dumps({'spec':'chara_card_v2','data':{'name':'Test'}}),encoding='utf8')
            rename=Path.rename
            def competing_role(source,destination):
                destination=Path(destination)
                destination.mkdir()
                (destination/'owner.txt').write_text('concurrent owner',encoding='utf8')
                return rename(source,destination)
            with patch.object(Path,'rename',competing_role):
                with self.assertRaises(OSError):import_card(card,root/'store','test')
            self.assertEqual((root/'store/test/owner.txt').read_text(encoding='utf8'),'concurrent owner')
            self.assertFalse((root/'store/test/role.json').exists())
            self.assertEqual(list((root/'store').glob('.role-*')),[])

    def test_user_card_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);card=root/'card.json'
            original=json.dumps({'spec':'chara_card_v2','data':{'name':'用户角色','description':'原始描述','character_book':{'entries':[{'keys':['游戏'],'content':'世界书内容','enabled':True}]}}},ensure_ascii=False).encode('utf8')
            card.write_bytes(original)
            imported=import_card(card,root/'users','user-role')
            self.assertEqual((imported/'card/original-card.json').read_bytes(),original)
            self.assertEqual(load_role(imported)['verified']['status'],'ok')
            with self.assertRaises(ValueError):import_card(card,root/'users','user-role')

    def test_windows_paths_and_duplicate_manifests_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ('card/x:stream','card/../outside','card/CON','card/x.'):
                p=root/'test.zip'
                with zipfile.ZipFile(p,'w') as z:
                    z.writestr('role.json','{"schema_version":1,"id":"test","name":"test"}')
                    z.writestr(name,'test')
                with self.assertRaises(ValueError):import_package(p,root/'store')
                self.assertFalse((root/'store/test').exists())

    def test_real_builtin_vrm_metadata(self):
        root=Path(__file__).resolve().parents[1]
        r=inspect_vrm(root/'extensions/roles/defaults/sampleA/AvatarSample_A.vrm')
        self.assertEqual(r['format'],'vrm0')
        self.assertFalse(r['external_resources'])

    def test_truncated_vrm_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.vrm';p.write_bytes(b'glTF')
            with self.assertRaises(ValueError):inspect_vrm(p)
