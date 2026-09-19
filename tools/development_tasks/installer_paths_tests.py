import hashlib
import json
from pathlib import Path
import subprocess
import unittest
import uuid
import zipfile

import verify_portable_staging as verifier


class InstallerPaths(unittest.TestCase):
    def test_hierarchy_conflicts_both_orders_and_case(self):
        for paths in (['ui/a','ui/a/b'], ['ui/a/b','ui/a'], ['ui/A','UI/a/b']):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                verifier.validate_inventory_paths(paths)

    def test_duplicate_and_unsafe_paths(self):
        for paths in (['ui/a','UI/A'], ['../escape'], ['ui/CON.txt']):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                verifier.validate_inventory_paths(paths)

    def test_valid_shared_directories(self):
        verifier.validate_inventory_paths(['ui/a.js','ui/a/b.js','ui/中文.png','ui/ab'])

    def test_real_installer_rejects_before_staging(self):
        root=Path.cwd()/('installer-evidence-'+uuid.uuid4().hex)
        root.mkdir()  # inherited ACL; no Python 3.14 private temp directory
        files={name:b'fixture' for name in ('Sumika.exe','tools/start_sumika.ps1',
            'tools/start_ui_bridge.ps1','ui/server.py','sumika_next/cli.py','runtime/dsh/release.json')}
        files.update({'ui/Asset':b'file','ui/asset/icon.png':b'child'})
        manifest={'kind':'portable-staging','schema_version':2,'files':[
            {'path':name,'size':len(body),'sha256':hashlib.sha256(body).hexdigest()}
            for name,body in files.items()]}
        archive=root/'conflict.zip'
        with zipfile.ZipFile(archive,'x') as z:
            for name,body in files.items(): z.writestr(name,body)
            z.writestr('package-manifest.json',json.dumps(manifest))
        checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
        result=subprocess.run(['powershell.exe','-NoProfile','-File',str(Path.cwd()/'install_sumika.ps1'),
            '-Archive',str(archive),'-Destination',str(root/'installed'),'-Sha256',checksum],
            capture_output=True,encoding='utf8',errors='replace',timeout=30)
        (root/'installer.txt').write_text(result.stdout+result.stderr,encoding='utf8')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((root/'installed').exists())
        self.assertEqual(list(root.glob('sumika-install-*')),[])


if __name__=='__main__': unittest.main()
