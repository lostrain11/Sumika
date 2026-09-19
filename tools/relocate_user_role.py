"""Manage active-role relocation through a running Bridge. Default is read-only."""
import argparse,json,urllib.request,urllib.error
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--target',type=Path)
    parser.add_argument('--apply',action='store_true')
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--resume',metavar='RECEIPT_ID')
    actions.add_argument('--rollback',metavar='RECEIPT_ID')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('invalid port')
    if args.target and (args.resume or args.rollback):parser.error('target cannot accompany recovery')
    base=f'http://127.0.0.1:{args.port}'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def call(path,payload=None,token=''):
        request=urllib.request.Request(base+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Origin':base,'Content-Type':'application/json','X-Sumika-CSRF':token})
        try:
            with opener.open(request,timeout=900) as response:return json.load(response)
        except urllib.error.HTTPError as error:
            with error:raise RuntimeError(json.load(error).get('error','request refused')) from None
    state=call('/api/manage/role-relocation')
    if not args.apply:
        print(json.dumps({'state':state,'proposed_target':str(args.target) if args.target else None,'applied':False},ensure_ascii=False));return
    token=call('/api/manage/session')['csrf']
    if args.resume or args.rollback:
        action='resume' if args.resume else 'rollback'
        result=call('/api/manage/role-relocation/'+action,{'id':args.resume or args.rollback,'confirmed':True},token)
    else:
        if not args.target:parser.error('--apply requires --target or a recovery receipt')
        settings=call('/api/manage/settings')
        result=call('/api/manage/role-relocation',{'expected_revision':settings['revision'],'target':str(args.target),'confirmed':True},token)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
