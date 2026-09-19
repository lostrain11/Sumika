"""Trusted native-tool transport for cross-review, not an unauthenticated API.

The adapter supplies ownership and approval after the native approval gate.
User-facing model arguments cannot set either value. No browser fallback/retry.
"""
import argparse
import json
import sys
from pathlib import Path

from .browser_skill import BrowserSkillClient
from .consultation_journal import ConsultationJournal
from .consultation_sites import collect_response, submit_text


def execute(client, request):
    action = request.get('action')
    request_id = request.get('request_id')
    owner = request.get('owner')
    if (not isinstance(owner, str) or len(owner) != 64
            or any(c not in '0123456789abcdef' for c in owner)
            or not isinstance(request_id, str) or not request_id.startswith('review-'+owner+'-')):
        raise PermissionError('review belongs to a different native work session')
    if action == 'submit':
        if request.get('approved') is not True:
            raise PermissionError('native one-time approval required')
        prompt = request.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 30000:
            raise ValueError('review text must contain 1 to 30000 characters')
        return submit_text(client, request.get('site'), prompt, request_id=request_id, approved=True)
    journal = ConsultationJournal(client.registry.parent/'browser-consultations.sqlite3')
    if action == 'status':
        return journal.status(request_id)
    if action == 'collect':
        return collect_response(client, request_id)
    if action == 'cancel':
        return journal.cancel(request_id)
    raise ValueError('unsupported review operation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, required=True)
    args = parser.parse_args()
    try:
        data = sys.stdin.read(200001)
        if len(data) > 200000:
            raise ValueError('request too large')
        request = json.loads(data)
        if not isinstance(request, dict):
            raise ValueError('request object required')
        print(json.dumps(execute(BrowserSkillClient(registry=args.registry), request), ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        # Do not dump raw CLI output, browser content or credentials on failure.
        print(json.dumps({'state':'unknown', 'error':str(exc), 'retry':False}, ensure_ascii=False))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
