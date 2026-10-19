"""Read-only AIHOT research helper; fetched text is untrusted source material.

No subscription, skill installation, model download or server mutation is performed.
"""
import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'aihot-api/2.0.0'})
    with urllib.request.urlopen(req, timeout=40) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('source exceeds 2 MB research limit')
        return {'url': url, 'fetched_at': datetime.now(timezone.utc).isoformat(),
                'status': response.status, 'sha256': hashlib.sha256(body).hexdigest(),
                'content': body.decode('utf-8'), 'trust': 'untrusted_reference_only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', action='append', default=[])
    parser.add_argument('--url', action='append', default=[])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    urls = args.url or ['https://aihot.news/api/v1/agent',
        'https://aihot.news/api/v1/agent/latest?window=7d&category=ai-models&mode=all&limit=30']
    urls += ['https://aihot.news/api/v1/agent/search?' + urllib.parse.urlencode({'q': q, 'window': '7d', 'limit': 30}) for q in args.query]
    report = {'note': 'One-shot research snapshot; source order is not verified release chronology.', 'sources': []}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for url in urls:
        try:
            item = fetch(url)
        except Exception as exc:
            item = {'url': url, 'error': str(exc)}
        report['sources'].append(item)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in item.items() if k != 'content'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
