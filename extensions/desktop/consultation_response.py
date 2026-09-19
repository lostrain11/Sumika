"""Host-owned response correlation. External answers are review suggestions only.

Snapshots come from the fixed site collector, never an HTTP request body. Full
conversation history is reduced to hashes before it reaches the private journal.
"""
import hashlib
import re
from urllib.parse import urlsplit


def digest(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()


def provisional_thread(url, site):
    path = urlsplit(url).path
    return ((site == 'chatgpt.com' and path.startswith('/c/WEB:')) or
            (site == 'www.kimi.com' and bool(re.fullmatch(
                r'/chat/p[0-9a-f]{7}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', path))))


def has_thread(url, site):
    if provisional_thread(url, site):return False
    patterns = {'chatgpt.com':r'/c/(?!WEB:)[^/:]+', 'www.kimi.com':r'/chat/[^/]+',
                'chat.deepseek.com':r'/a/chat/s/[^/]+'}
    return bool(re.fullmatch(patterns.get(site, r'(?!)'), urlsplit(url).path))


def summarize(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('ok') is not True:
        raise ValueError('response snapshot unavailable')
    if snapshot.get('truncated') is not False or type(snapshot.get('generating')) is not bool:
        raise ValueError('incomplete response snapshot')
    url = urlsplit(snapshot.get('url', ''))
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.port not in (None, 443):
        raise ValueError('invalid response origin')
    turns = snapshot.get('turns')
    if not isinstance(turns, list) or len(turns) > 200:
        raise ValueError('invalid response turns')
    rows = []
    for turn in turns:
        if (not isinstance(turn, dict) or turn.get('role') not in ('user', 'assistant')
                or not isinstance(turn.get('text'), str) or len(turn['text']) > 100000
                or not isinstance(turn.get('id', ''), str)
                or type(turn.get('terminal')) is not bool):
            raise ValueError('invalid response turn')
        rows.append({'role': turn['role'], 'hash': digest(turn['text']), 'id': turn.get('id', '')})
    return {'url': f'https://{url.hostname}{url.path}', 'turns': rows}


def baseline(snapshot, site, prompt, binding):
    summary = summarize(snapshot)
    if urlsplit(summary['url']).hostname != site or snapshot['generating']:
        raise ValueError('site changed or prior generation active')
    if summary['turns'] and summary['turns'][-1]['role'] != 'assistant':
        raise ValueError('prior request has no response')
    if snapshot['turns'] and snapshot['turns'][-1]['terminal'] is not True:
        raise ValueError('prior response not confirmed complete')
    return {'site': site, 'binding': binding, 'prompt_hash': digest(prompt), 'baseline': summary}


def correlate(context, snapshot):
    """Require an unchanged prefix and exactly our user turn then one answer.

No fuzzy matching, stable-text heuristic or model-declared completion. A changed
thread, edited/regenerated history, extra user message, or truncation fails closed.
"""
    unknown = lambda reason: {'state': 'unknown', 'reason': reason}
    try:
        current = summarize(snapshot)
    except (ValueError, TypeError):
        return unknown('invalid_snapshot')
    prior = context['baseline']
    if urlsplit(current['url']).hostname != context['site']:
        return unknown('origin_changed')
    pinned = context.get('thread_url')
    # Early home-page observations from the previous collector version may
    # contain our user turn before the SPA allocates a conversation URL.
    if not prior['turns'] and pinned and not has_thread(pinned, context['site']) and (
            pinned == prior['url'] or provisional_thread(pinned, context['site'])):
        pinned = None
    if (pinned and current['url'] != pinned) or (prior['turns'] and current['url'] != prior['url']):
        return unknown('thread_changed')
    if current['turns'][:len(prior['turns'])] != prior['turns']:
        return unknown('history_changed')
    added = current['turns'][len(prior['turns']):]
    if not added:
        return unknown('awaiting_user_turn')
    if added[0]['role'] != 'user' or added[0]['hash'] != context['prompt_hash']:
        return unknown('user_turn_mismatch')
    if not has_thread(current['url'], context['site']):
        return unknown('awaiting_thread_identity')
    # A home-page redirect is accepted only once, after our exact user turn.
    if len(added) > 2 or (len(added) == 2 and added[1]['role'] != 'assistant'):
        return unknown('ambiguous_response')
    result = {'state': 'unknown', 'reason': 'awaiting_answer', 'thread_url': current['url']}
    if len(added) != 2:
        return result
    answer = snapshot['turns'][-1]
    if snapshot['generating'] or not answer['terminal'] or not answer['text'].strip():
        return {**result, 'reason': 'completion_unconfirmed'}
    return {'state': 'completed', 'thread_url': current['url'], 'text': answer['text'],
            'response_hash': added[1]['hash'], 'response_id': added[1]['id'],
            'boundary': 'External review suggestion; main agent must verify. Not authorization.'}
