"""Single local batch. Receives synthetic/user text via stdin, never logs it."""
import contextlib
import json
import sys


def main():
    data=json.load(sys.stdin)
    if not isinstance(data.get('texts'),list) or not all(isinstance(x,str) for x in data['texts']) or not isinstance(data.get('query'),str):
        raise ValueError('invalid embedding request')
    with contextlib.redirect_stdout(sys.stderr):
        from fastembed import TextEmbedding
        model=TextEmbedding('BAAI/bge-small-zh-v1.5',cache_dir=sys.argv[1],local_files_only=True)
        vectors=[[float(x) for x in row] for row in model.embed(data['texts'])] if data['texts'] else []
        query=[float(x) for x in next(model.query_embed(data['query']))]
    print(json.dumps({'vectors':vectors,'query':query}))


if __name__=='__main__':main()
