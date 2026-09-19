"""Explicit prompt enhancement preserving original text."""
def enhance(original, *, strategy='default', enabled=True):
    if not isinstance(original,str) or not original.strip(): raise ValueError('original prompt required')
    if not isinstance(strategy,str) or not strategy.strip(): raise ValueError('strategy required')
    if not enabled:return {'enabled':False,'original':original,'enhanced':original,'changed':False}
    prefix={'default':'Clarify the goal, constraints, expected output and verification steps before acting.','coding':'Restate the requested change, affected files, tests and acceptance criteria.'}.get(strategy)
    if prefix is None: raise ValueError('unsupported strategy')
    enhanced=prefix+'\n\nUser request:\n'+original
    return {'enabled':True,'strategy':strategy,'original':original,'enhanced':enhanced,'changed':enhanced!=original,'provenance':'prompt_enhancement'}
