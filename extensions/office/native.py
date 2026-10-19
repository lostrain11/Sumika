"""Register upstream Office authoring using its public payload/plugin contracts."""
import json
from pathlib import Path

IDS = ('sumika-native-office', 'sumika-workspace-dependencies')
REQUIRED = ('docx', 'openpyxl', 'pptx', 'pypdf', 'reportlab',
            'numpy', 'pandas', 'xlsxwriter', 'lxml', 'PIL')


def payload(root):
    base = Path(root)/'runtime/office'
    try:
        data = json.loads((base/'runtime.json').read_text(encoding='utf8'))
        if data.get('platform')!='win32' or data.get('arch')!='x64':
            return None
        python = base/'dependencies/python/python.exe'
        site = python.parent/'Lib/site-packages'
        if not python.is_file() or any(not (site/name).is_dir() for name in REQUIRED):
            return None
        return base.resolve()
    except (OSError, ValueError, AttributeError):
        return None


def resource(root, name, relative):
    base = Path(root)/'runtime/dsh/node_modules'
    direct = base/'@deepseek-ai'/name/relative
    if direct.is_file():
        return direct.resolve()
    matches = list((base/'.pnpm').glob('*/node_modules/@deepseek-ai/'+name+'/'+relative))
    return matches[0].resolve() if len(matches)==1 else None


def plugin(root, name):
    return resource(root, name, 'lib/index.js')


def engine_config(root):
    """Expose only the shipped engine; never discover or install a host soffice."""
    node = Path(root)/'runtime/node/node.exe'
    cli = resource(root, 'libreoffice-kit', 'lib/cli.js')
    executable = resource(root, 'libreoffice-kit-win32-x64', 'bin/libreoffice-kit.exe')
    bootstrap = resource(root, 'libreoffice-kit-win32-x64', 'program/program/fundamental.ini')
    if not node.is_file() or any(path is None for path in (cli, executable, bootstrap)):
        return {'cli':False}
    return {'node':str(node.resolve()), 'cli':str(cli)}


def configure(rows, root):
    """Refresh only our two entries; preserve unrelated native/user plugins."""
    emptied = []
    for row in rows:
        if isinstance(row,dict) and isinstance(row.get('insert'),list):
            owned = any(isinstance(item,dict) and item.get('id') in IDS for item in row['insert'])
            row['insert'] = [item for item in row['insert']
                             if not isinstance(item,dict) or item.get('id') not in IDS]
            if owned and row=={'insert':[]}:
                emptied.append(row)
    rows[:] = [row for row in rows if not any(row is old for old in emptied)]
    source = payload(root)
    office = plugin(root,'dsh-skill-office')
    dependencies = plugin(root,'dsh-tool-workspace-dependencies')
    if source is None or office is None or dependencies is None:
        return False
    rows.append({'insert':[
        {'id':IDS[0],'name':str(office),'config':engine_config(root)},
        {'id':IDS[1],'name':str(dependencies),'config':{'source':str(source)}}]})
    return True
