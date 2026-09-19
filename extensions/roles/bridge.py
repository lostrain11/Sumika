"""Fixed executable entry for native plugins; request is supplied on stdin."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import argparse
import json
from extensions.roles.service import RoleSession
from extensions.memory.capture import capture


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args();session=None
    try:
        session=RoleSession(**json.loads(args.config.read_text(encoding='utf8')))
        request=json.load(sys.stdin)
        if request['operation']=='host_context':
            if not session.enabled:result={'disabled':True}
            else:
                host=request['host']
                captured=capture(session.memory,session.scope,namespace=host['namespace'],session_id=host['session_id'],messages=host['messages'])
                result=session.request('context',request['data']);result['capture']=captured
        else:result=session.request(request['operation'],request.get('data',{}))
        print(json.dumps(result,ensure_ascii=False))
    except (OSError,ValueError,KeyError,TypeError) as error:parser.exit(2,'role bridge: '+str(error)+'\n')
    finally:
        if session:session.close()

if __name__=='__main__':raise SystemExit(main())
