"""Checked text-only chat entry points, not arbitrary page selector authority.

Selectors are deliberately narrow. DOM changes fail closed in consultation_guard;
the adapter does not fall back to arbitrary buttons or submit with Enter.
Real submission and answer collection remain separate acceptance gates.
"""
SITES = {
    'chat.deepseek.com': {
        'prompt_selector': 'textarea',
        'submit_selector': '[role="button"].ds-button--primary.ds-button--circle',
    },
    'www.kimi.com': {
        'prompt_selector': '.chat-input-editor[contenteditable="true"]',
        'submit_selector': '.send-button-container',
    },
    'chatgpt.com': {
        'prompt_selector': '#prompt-textarea[contenteditable="true"]',
        'submit_selector': 'button[data-testid="send-button"]',
    },
}


def submit_text(client, site, prompt, *, request_id, approved=False):
    if site not in SITES:
        raise ValueError('unsupported consultation site')
    if approved is not True:
        raise PermissionError('explicit submission approval required')
    bridge = client.bound_bridge(site)
    return bridge.submit(site, prompt, request_id=request_id,
                         approved=True, capture=lambda:capture_response(bridge, site), **SITES[site])


def capture_response(bridge, site):
    """Collect only the bound site using a shipped read-only script."""
    import json
    from pathlib import Path
    if site not in SITES:
        raise ValueError('unsupported consultation site')
    bridge._authorized_session(site, 'read')
    tab = bridge._tab(site)
    script = Path(__file__).with_name('consultation_snapshot.js').read_text(encoding='utf8')
    result = bridge._run(['evaluate','--json','--session',bridge.session_id,'--tab-id',tab,
                          '('+script+')('+json.dumps({'origin':'https://'+site})+')'])
    bridge._authorized_session(site, 'read')
    bridge._tab(site)
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise RuntimeError('response snapshot unavailable')
    value = result.get('value')
    if not isinstance(value, dict) or value.get('ok') is not True:
        raise RuntimeError('site response adapter unavailable')
    return value


def collect_response(client, request_id):
    """Recover by persisted request identity; never navigate, rebind or resend."""
    from .consultation_journal import ConsultationJournal
    journal = ConsultationJournal(client.registry.parent/'browser-consultations.sqlite3')
    context = journal.response_context(request_id)
    site = context['site']
    bridge = client.bound_bridge(site)
    binding = {**bridge.identity, **SITES[site]}
    return journal.collect(request_id, binding=binding, capture=lambda:capture_response(bridge, site))
