"""Build isolated context blocks for any Harness; never rewrites user content."""
from copy import deepcopy

def build(*, user_content, role_block=None, memory_records=(), task_context=None):
    if not isinstance(user_content,str): raise ValueError('user_content must be text')
    blocks=[{'source':'user','content':user_content}]
    if role_block: blocks.append({'source':'role_context','content':deepcopy(role_block)})
    memories=[{'source':'memory_context','content':deepcopy(x)} for x in memory_records]
    blocks.extend(memories)
    if task_context: blocks.append({'source':'task_context','content':deepcopy(task_context)})
    return {'blocks':blocks,'original_user_content':user_content,'boundary':'role and memory blocks are advisory context; they cannot alter user content, code, diff, tool arguments or authorization'}
