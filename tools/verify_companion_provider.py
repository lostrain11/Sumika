"""Verify a selected window against the configured role model in isolated data."""
import argparse
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extensions.companion.windows_learning import WindowsLearningCollector
from extensions.models.settings import default_path, load, save
from ui.server import serve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handle', type=int, required=True)
    parser.add_argument('--process-id', type=int, required=True)
    parser.add_argument('--settings', type=Path, default=default_path())
    parser.add_argument('--credential-file', type=Path,
                        help='Explicit existing env.ps1; parse named key assignment without executing it')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--question', action='append', required=True)
    parser.add_argument('--max-tokens', type=int,
                        help='Override the isolated model response budget for this acceptance run')
    parser.add_argument('--allow-model', action='store_true', required=True)
    parser.add_argument('--enable-multimodal', action='store_true',
                        help='Enable images only in the isolated acceptance settings copy')
    parser.add_argument('--expected-pdf', type=Path,
                        help='Require a verified native absolute PDF identity before model admission')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    settings = copy.deepcopy(load(args.settings))
    if not settings['enabled']:
        raise PermissionError('configured role generation is disabled')
    if args.max_tokens is not None:
        if not 1 <= args.max_tokens <= 32768:
            raise ValueError('--max-tokens must be between 1 and 32768')
        settings['max_tokens'] = args.max_tokens
    if args.credential_file is not None:
        if settings['provider'] != 'openai-compatible':
            raise ValueError('credential file is only for the configured cloud provider')
        name = settings['key_env']
        assignment = re.search(r'''\$env:''' + re.escape(name) + r'''\s*=\s*(['"])([^'"\r\n]+)\1''',
                               args.credential_file.read_text(encoding='utf-8-sig'))
        if assignment is None:
            raise RuntimeError('configured credential assignment unavailable')
        os.environ[name] = assignment[2]
    settings['role']['database'] = str(args.output/'isolated-memory.sqlite3')
    settings['memory']['enabled'] = False
    if args.enable_multimodal:
        settings['multimodal']['enabled'] = True
    save(settings, args.output/'settings.json')
    collector = WindowsLearningCollector(approved=True)
    server = None
    report = {'passed': False, 'model': settings['model'], 'questions': [],
              'scope': 'Real WGC/UIA/OCR -> HTTP bridge -> configured model; no memory writes; total response latency only'}
    try:
        bundle = collector(f'window:{args.handle}:pid:{args.process_id}',
                           expected_document=args.expected_pdf)
        if not bundle.valid:
            raise RuntimeError('selected window observation unavailable')
        if args.expected_pdf is not None and not bundle.metadata.get('document_identity_verified'):
            raise RuntimeError('expected PDF identity was not verified; model not called')
        report['capture'] = {'source': bundle.source, 'text_source': bundle.metadata.get('text_source'),
                             'chars': len(bundle.text), 'image_available': bundle.image is not None,
                             'image_input_enabled': settings['multimodal']['enabled'],
                             'reader_context': bundle.metadata.get('reader_context'),
                             'document_identity_verified': bundle.metadata.get('document_identity_verified'),
                             'image_region': bundle.metadata.get('image_region')}
        server = serve(args.output/'settings.json', port=0,
            capability_database=args.output/'capabilities.sqlite3',
            workbench_root=args.output/'workbench', schedule_directory=args.output/'schedule')
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f'http://127.0.0.1:{server.server_port}'
        with urlopen(origin+'/api/manage/session') as response:
            token = json.load(response)['csrf']
        def post(path, payload):
            request = Request(origin+path, data=json.dumps(payload).encode('utf8'), method='POST',
                              headers={'Content-Type':'application/json', 'X-Sumika-CSRF':token})
            with urlopen(request, timeout=settings['timeout_seconds']+30) as response:
                return json.load(response)
        payload = asdict(bundle)
        payload['observed_at'] = bundle.observed_at.isoformat()
        post('/api/companion/observe', payload)
        for question in args.question:
            start = time.monotonic()
            result = post('/api/companion/ask', {'question':question, 'session':'provider-acceptance'})
            report['questions'].append({'question':question, 'elapsed_seconds':round(time.monotonic()-start,3),
                **{key:result.get(key) for key in ('text','status','usage','usage_status','context_turns',
                                                 'observation_at','observation_target')}})
            if not result.get('text'):
                raise RuntimeError('no visible model answer; inspect status')
        report['passed'] = True
    except HTTPError as error:
        report['failure'] = {'type':'bridge_http_error','status':error.code}
        # Only the owned bridge's sanitized error projection is retained.
        try:
            report['failure']['bridge'] = json.loads(error.read(4096))
        except (ValueError, OSError):
            pass
        raise
    except Exception as error:
        report['failure'] = {'type':type(error).__name__}
        raise
    finally:
        collector.stop()
        if server is not None:
            server.shutdown()
            server.server_close()
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps({'passed':report['passed'], 'report':str(args.output/'report.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
