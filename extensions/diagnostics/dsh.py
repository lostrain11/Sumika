"""DSH rc.2 journal projection. No persistence, dispatch or raw-text export."""
from .query import identifier

# Protocol labels are useful diagnostic metadata, unlike arbitrary strings that
# may contain file paths. Keep the allowlist local to the DSH adapter.
_EVENT_KINDS = frozenset({
    'tool/call', 'tool/result', 'user/message', 'assistant/message',
    'turn/start', 'turn/end', 'step/start', 'step/end',
    'request/header', 'session/header', 'agent/inbox/spliced',
    'approval/asked', 'approval/decided', 'approval/policy',
    'compaction/start', 'compaction/end',
})


def project_page(page, *, session, version, through_seq, before_seq=None):
    """Project one native message-aligned page; preserve its exclusive cursor."""
    if (not isinstance(page, dict) or type(page.get('hasMore')) is not bool
            or not isinstance(page.get('records'), list)):
        raise ValueError('invalid native diagnostic page')
    events = []
    previous = -1
    for entry in page['records']:
        event = entry.get('event') if isinstance(entry, dict) and entry.get('type') == 'event' else None
        if not isinstance(event, dict):
            raise ValueError('invalid native diagnostic event')
        seq = event.get('seq')
        if (type(seq) is not int or seq <= previous or seq > through_seq
                or (before_seq is not None and seq >= before_seq)):
            raise ValueError('invalid native diagnostic sequence')
        previous = seq
        kind = event.get('type')
        data = event.get('data')
        if not isinstance(kind, str) or not isinstance(data, dict):
            raise ValueError('invalid native diagnostic payload')
        ids, status, code = [], 'unknown', None
        if kind in ('tool/call', 'approval/asked') and isinstance(data.get('callId'), str):
            ids.append(identifier(data['callId']))
        if kind == 'tool/result':
            message = data.get('message')
            blocks = message.get('content') if isinstance(message, dict) else None
            if isinstance(blocks, list) and len(blocks) == 1 and isinstance(blocks[0], dict):
                block = blocks[0]
                if block.get('type') == 'tool-result':
                    if isinstance(block.get('toolCallId'), str):
                        ids.append(identifier(block['toolCallId']))
                    if type(block.get('isError')) is bool:
                        status = 'error' if block['isError'] else 'reported_success'
                    error = data.get('error')
                    if status == 'error' and isinstance(error, dict):
                        code = identifier(error.get('code'))
        events.append({'seq': seq, 'kind': kind if kind in _EVENT_KINDS else identifier(kind), 'session': identifier(session),
                       'call_ids': ids, 'status': status, 'error_code': code,
                       'source': 'dsh.session/page', 'dsh_version': identifier(version),
                       'provenance': 'observed_record_metadata'})
        if kind in ('approval/asked', 'approval/decided'):
            events[-1]['approval_id'] = identifier(data.get('id'))
        if kind == 'approval/decided':
            outcome = data.get('outcome')
            events[-1]['approval_outcome'] = outcome if outcome in (
                'allowed-once', 'rejected', 'cancelled', 'unavailable') else 'unknown'
    if page['hasMore'] and not events:
        raise ValueError('native diagnostic page cannot advance')
    return {'events': events, 'through_seq': through_seq,
            'next_before': events[0]['seq'] if page['hasMore'] else None,
            'boundary': 'Recorded tool outcomes are not independent verification; omitted content is not inspected.'}
