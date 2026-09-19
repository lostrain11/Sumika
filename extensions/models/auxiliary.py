"""Optional, fail-closed helper-model operations.

The helper is advisory only. It never dispatches a task, grants permission, or
silently changes provider routing. When disabled or unavailable callers receive
an explicit unavailable/unknown result.
"""
import json
import re
import difflib

from .ollama import OllamaProvider, OllamaError
from .cloud import CloudProvider, CloudError


def _provider(settings):
    cfg = settings['auxiliary']
    if not cfg['enabled']:
        return None
    common = {'enabled': True, 'timeout': cfg['timeout_seconds']}
    if cfg['provider'] == 'ollama':
        return OllamaProvider(cfg['endpoint'], **common)
    return CloudProvider(cfg['endpoint'], key_env=cfg['key_env'],
                         enabled=True, timeout=cfg['timeout_seconds'])


def health(settings):
    provider = _provider(settings)
    if provider is None:
        return {'status': 'disabled', 'provider': settings['auxiliary']['provider']}
    try:
        return provider.health()
    except (OllamaError, CloudError, OSError, ValueError) as exc:
        return {'status': 'unavailable', 'reason': str(exc)}


def _generate(settings, messages, schema=None):
    cfg = settings['auxiliary']
    provider = _provider(settings)
    if provider is None:
        return {'status': 'disabled'}
    try:
        if cfg['provider'] == 'ollama':
            result = provider.generate(model=cfg['model'], messages=messages,
                                       options={'num_ctx': cfg['context_length'],
                                                'num_predict': cfg['max_tokens'],
                                                'temperature': cfg['temperature']}, format=schema)
        else:
            result = provider.generate(model=cfg['model'], messages=messages,
                                       max_tokens=cfg['max_tokens'], temperature=cfg['temperature'])
        return {'status': 'reported', 'text': result['text'], 'finish_reason':result.get('finish_reason'), 'provider': result.get('provider'),
                'model': result.get('model'), 'usage': result.get('usage', {})}
    except (OllamaError, CloudError, OSError, ValueError) as exc:
        return {'status': 'unknown', 'reason': str(exc)}


def enhance_prompt(settings, original, strategy='default'):
    if not isinstance(original, str) or not original.strip() or len(original)>6000:
        raise ValueError('prompt must contain 1-6000 characters')
    if strategy != 'default':
        raise ValueError('unsupported enhancement strategy')
    if not settings.get('prompt_enhancement',{}).get('enabled',False):
        return {'status':'disabled','original':original,'enhanced':original,'changed':False}
    if 'prompt_enhancement' not in settings['auxiliary'].get('capabilities', []):
        return {'status': 'disabled', 'original': original, 'enhanced': original, 'changed': False,
                'reason': 'auxiliary capability not enabled'}
    # Complex executable payloads are outside this small editor's remit.
    if '```' in original or re.search(r'(?m)^(?:diff --git|@@ |[+-]{3} )',original):
        return {'status':'skipped','original':original,'enhanced':original,'changed':False,
                'reason':'代码块或 diff 保留原文，不进行模型改写。'}
    result = _generate(settings, [
        {'role': 'system', 'content': '你是中文需求文字编辑器，不回答或执行需求。只输出 JSON 对象，唯一字段 enhanced 是润色后的需求原文。只调整语序和表达，不补充方案、步骤、验收标准、文件名、权限或事实。不解释改写。含有否定、限制、预算、授权的分句必须逐字保留。代码、路径、数字逐字保留。不增加标题。原文已经清楚则原样返回。'},
        {'role': 'user', 'content': json.dumps({'待润色原文':original},ensure_ascii=False)},
    ], schema={'type':'object','properties':{'enhanced':{'type':'string'}},'required':['enhanced'],'additionalProperties':False})
    if result['status'] != 'reported' or not isinstance(result.get('text'), str) or not result['text'].strip():
        return {'status': result['status'], 'original': original, 'enhanced': original,
                'changed': False, 'reason': result.get('reason')}
    try:
        parsed=json.loads(result['text'])
        if not isinstance(parsed,dict) or set(parsed)!={'enhanced'}:raise ValueError()
        enhanced=parsed['enhanced']
        if not isinstance(enhanced,str) or not enhanced.strip():raise ValueError()
        enhanced=enhanced.strip()
        protected=re.findall(r'`[^`]*`|“[^”]*”|「[^」]*」|[A-Za-z]:[\\/][^\s，。；]+|https?://[^\s，。；]+|\d+(?:\.\d+)?',original)
        clauses=re.split(r'[，。；\n]',original)
        protected += [c.strip() for c in clauses if re.search(r'不|只|禁止|保留|必须|预算|授权|确认|权限|费用|付费',c)]
        if any(p not in enhanced for p in protected):raise ValueError()
        if result.get('finish_reason')=='length' or len(enhanced)>max(100,len(original)*2):raise ValueError()
        # Extra sensitive actions cannot be introduced by the editor.
        for term in ('授权','删除','安装','执行','部署','付费','云端','工具','终端','权限'):
            if term in enhanced and term not in original:raise ValueError()
    except (ValueError,TypeError):
        return {'status':'rejected','original':original,'enhanced':original,'changed':False,
                'reason':'改写未通过格式或原文保护检查，已保留原文。','usage':result.get('usage',{})}
    return {k:v for k,v in result.items() if k!='text'} | {'original': original, 'enhanced':enhanced,
            'changed': enhanced != original,'requires_confirmation':True,
            'diff':'\n'.join(difflib.unified_diff(original.splitlines(),enhanced.splitlines(),fromfile='原文',tofile='改写',lineterm=''))}


def classify_task(settings, message, project_index=None):
    if 'task_intent' not in settings['auxiliary'].get('capabilities', []):
        return {'status': 'disabled', 'classification': {'kind': 'unknown', 'confidence': 'low',
                'project_id': None, 'evidence': ''}, 'reason': 'auxiliary capability not enabled'}
    if not isinstance(message, str) or not message.strip():
        raise ValueError('message required')
    projects = json.dumps(project_index or [], ensure_ascii=False)
    result = _generate(settings, [
        {'role': 'system', 'content': 'Classify only the current user message. Return JSON with kind chat|discussion|task|unknown, confidence high|medium|low, project_id string or null, evidence exact quote. Do not infer authorization or claim execution.'},
        {'role': 'user', 'content': f'Projects index:\n{projects}\nMessage:\n{message}'},
    ])
    unknown = {'kind': 'unknown', 'confidence': 'low', 'project_id': None, 'evidence': ''}
    if result['status'] != 'reported':
        return {**result, 'classification': unknown}
    try:
        value = json.loads(result['text'])
        if not isinstance(value, dict) or value.get('kind') not in ('chat', 'discussion', 'task', 'unknown'):
            raise ValueError
        confidence = value.get('confidence')
        if confidence not in ('high', 'medium', 'low'):
            raise ValueError
        evidence = value.get('evidence', '')
        if not isinstance(evidence, str) or len(evidence) > len(message) or (evidence and evidence not in message):
            raise ValueError
        return {**result, 'classification': {'kind': value['kind'], 'confidence': confidence,
                'project_id': value.get('project_id') if isinstance(value.get('project_id'), str) else None,
                'evidence': evidence}}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {**result, 'status': 'unknown', 'classification': unknown, 'reason': 'invalid classifier response'}
