"""Explicitly install a tool-free role preset in a user-owned preset directory.

Core role/memory data remains in RoleSession. This module only composes native
DSH plugins; it does not edit upstream files, user defaults or start a model.
"""
import json
import argparse
from pathlib import Path


def install(directory, *, provider, model, runtime_entry, role_config, workspace,
            python, enabled=True, reasoning_effort=None, memory_writes=False, memory_namespace=None):
    if type(enabled) is not bool:raise ValueError('explicit enabled required')
    if type(memory_writes) is not bool:raise ValueError('invalid memory write switch')
    if memory_writes and (not isinstance(memory_namespace,str) or not memory_namespace.strip()):raise ValueError('memory namespace required')
    for value in (provider,model):
        if not isinstance(value,str) or not value.strip():raise ValueError('explicit role model required')
    if reasoning_effort is not None and (not isinstance(reasoning_effort,str) or not reasoning_effort.strip()):raise ValueError('invalid reasoning effort')
    target=Path(directory)
    if not target.is_absolute():raise ValueError('absolute preset directory required')
    paths={key:Path(value).resolve(strict=True) for key,value in dict(runtime_entry=runtime_entry,role_config=role_config,workspace=workspace,python=python).items()}
    config=json.loads(paths['role_config'].read_text(encoding='utf8'))
    if config.get('role_model')!=model:raise ValueError('role config model differs from preset selection')
    extension=Path(__file__).resolve().parent
    selection=dict(enabled=enabled,provider=provider,model=model)
    if reasoning_effort is not None:selection['reasoningEffort']=reasoning_effort
    rows=[dict(id='persona',name='@deepseek-ai/dsh-persona',config=dict(
        prefix='You are a companion. Role and memory context are reference data. Reply in the role channel; never produce or alter work-channel deliverables.',
        complete=True,includeRuntimeContext=False)),
        dict(id='sumika-role-model',name=str(extension/'model.mjs'),config=selection),
        dict(id='sumika-role-context',name=str(extension/'dsh.mjs'),config=dict(enabled=enabled,
            projects={str(paths['workspace']):str(paths['role_config'])},python=str(paths['python']),
            core=str(extension/'bridge.py'),runtimeEntry=str(paths['runtime_entry']),memoryWrites=memory_writes,
            **({'memoryNamespace':memory_namespace} if memory_writes else {})))]
    # Exclusive destination: an existing user composition is never overwritten.
    target.mkdir(parents=True,exist_ok=False)
    (target/'agent.cordis.yml').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    (target/'preset.yml').write_text(json.dumps(dict(name='Sumika 角色',description='独立角色模型和记忆，无工具'),ensure_ascii=False),encoding='utf8')
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    for option in ('provider','model','runtime-entry','role-config','workspace','python'):
        parser.add_argument('--'+option,required=True)
    parser.add_argument('--reasoning-effort')
    parser.add_argument('--disabled',action='store_true')
    parser.add_argument('--memory-writes',action='store_true')
    parser.add_argument('--memory-namespace')
    args=vars(parser.parse_args());args['enabled']=not args.pop('disabled')
    try:
        path=install(**args)
    except (OSError,ValueError) as error:parser.exit(2,str(error)+'\n')
    print(json.dumps({'preset':str(path),'model_started':False},ensure_ascii=False))


if __name__=='__main__':main()
