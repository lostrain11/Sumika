"""Build a relocatable payload for the official DSH workspace dependency tool.

Copies an existing standalone Python and installs the existing hash-locked wheels
into a new directory. Never changes a shared interpreter, profile or upstream.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-python',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args = parser.parse_args()
    base = args.base_python.resolve(strict=True)
    destination = args.destination.absolute()
    if destination.exists() or not (base/'python.exe').is_file() or (base/'pyvenv.cfg').exists():
        raise ValueError('new destination and physical standalone Windows Python required')
    if any(p.is_symlink() or p.is_junction() for p in base.rglob('*')):
        raise ValueError('base interpreter must contain physical files')
    python = destination/'dependencies/python'
    # A standalone bridge can already contain third-party packages. Start the
    # Office library layer empty, so old dist-info cannot shadow locked versions.
    shutil.copytree(base,python,ignore=lambda directory,names:
                    ['site-packages'] if Path(directory)==base/'Lib' else [])
    # The official payload is a library runtime, not a checkout import bridge.
    for p in python.glob('*._pth'):
        p.write_text('Lib\nDLLs\nLib/site-packages\n',encoding='utf8')
    site = python/'Lib/site-packages'
    site.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check',
        '--require-hashes','--only-binary=:all:','--no-compile','--upgrade','--target',str(site),
        '-r',str(ROOT/'extensions/office/requirements.lock')],check=True)
    probe = subprocess.run([str(python/'python.exe'),'-X','utf8','-B','-c',
        'import sys,json,importlib.metadata as m; '
        'import docx,openpyxl,pptx,pypdf,reportlab,pypdfium2,xlsxwriter,numpy,pandas; '
        'distributions=list(m.distributions()); '
        'names=[d.metadata["Name"].lower().replace("_","-") for d in distributions]; '
        'assert len(names)==len(set(names)), "duplicate distribution metadata"; '
        'print(json.dumps({"python":sys.version.split()[0],'
        '"pythonPackages":{d.metadata["Name"]:d.version for d in distributions}}))'],
        capture_output=True,text=True,encoding='utf8',check=True)
    manifest = {'desktopVersion':'0.0.1','platform':'win32','arch':'x64',**json.loads(probe.stdout)}
    (destination/'runtime.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'payload':str(destination),'manifest':manifest}))


if __name__=='__main__':
    main()
