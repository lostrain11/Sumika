"""Hardware-aware local model recommendation (P16, per user request).

Detects the machine's RAM, GPU and available resources, then recommends
which Ollama model tier the user should install for the best experience.
Recommendations are tiered: role-play needs a larger model; auxiliary
tasks (classification, summarization) need a smaller, faster one.

Never downloads anything — only reports what would fit and suggests the
``ollama pull`` command for the user to run.
"""
import ctypes
import shutil
import subprocess

# Model tiers: (name, ollama_tag, ram_needed_gb, params_label, use_case)
MODEL_TIERS = [
    {'id': 'tiny', 'tag': 'qwen3:1.7b', 'ram_gb': 1.5, 'label': '1.7B',
     'use': '快速分类、意图判断（辅助任务）'},
    {'id': 'small', 'tag': 'qwen3:4b', 'ram_gb': 2.5, 'label': '4B',
     'use': '辅助任务全量：分类、摘要、建议、翻译、弹幕总结'},
    {'id': 'medium', 'tag': 'qwen3:8b', 'ram_gb': 5.0, 'label': '8B',
     'use': '角色扮演对话、上下文问答（较好质量）'},
    {'id': 'large', 'tag': 'qwen3:14b', 'ram_gb': 9.0, 'label': '14B',
     'use': '高质量角色扮演、长文分析'},
    {'id': 'xlarge', 'tag': 'qwen3:30b-a3b', 'ram_gb': 18.0, 'label': '30B MoE',
     'use': '最强本地推理（需要充足空闲内存）'},
]

# Custom fine-tuned models (if already pulled)
CUSTOM_HINTS = {
    'sumika-qwen3-8b-heretic': '角色扮演专用微调（推荐用于陪伴对话）',
}

RESERVE_GB = 4.0  # Keep this much RAM for the OS + Sumika + browser


def _system_ram_gb():
    kernel32 = ctypes.WinDLL('kernel32')
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullTotalPhys / (1024 ** 3), m.ullAvailPhys / (1024 ** 3)


def _gpu_info():
    """Best-effort GPU detection via WMI (no external deps)."""
    try:
        result = subprocess.run(
            ['wmic', 'path', 'win32_VideoController', 'get', 'name',
             'AdapterRAM', '/format:csv'],
            capture_output=True, text=True, timeout=10)
        gpus = []
        for line in result.stdout.strip().splitlines()[1:]:
            parts = line.strip().split(',')
            if len(parts) >= 3 and parts[1]:
                name = parts[1].strip()
                ram = int(parts[2]) / (1024 ** 3) if parts[2].isdigit() else 0
                if name and 'microsoft basic' not in name.lower():
                    gpus.append({'name': name, 'vram_gb': round(ram, 1)})
        return gpus
    except Exception:
        return []


def _has_nvidia(gpus):
    return any('nvidia' in g['name'].lower() or 'geforce' in g['name'].lower()
               or 'rtx' in g['name'].lower() for g in gpus)


def recommend(*, installed_models=None):
    """Return hardware info + recommended model tiers.

    ``installed_models`` is a list of already-pulled Ollama model names
    (from /api/tags). Recommendations that are already installed are marked.
    """
    total_ram, free_ram = _system_ram_gb()
    gpus = _gpu_info()
    has_gpu = _has_nvidia(gpus)
    usable_gb = total_ram - RESERVE_GB
    installed = set(installed_models or [])

    usable = [tier for tier in MODEL_TIERS
              if tier['ram_gb'] <= usable_gb]
    recommended_role = None
    recommended_aux = None
    for tier in reversed(usable):  # largest first
        if recommended_role is None and tier['ram_gb'] >= 5.0:
            recommended_role = tier
        if recommended_aux is None and tier['ram_gb'] >= 2.0:
            recommended_aux = tier
    if recommended_aux is None and usable:
        recommended_aux = usable[0]

    def mark(tier):
        if tier is None:
            return None
        result = dict(tier)
        full_tag = tier['tag']
        result['installed'] = any(full_tag in m or m.endswith('/' + full_tag)
                                  or full_tag in m for m in installed)
        # Check custom fine-tunes that serve the same purpose
        if not result['installed']:
            for hint, desc in CUSTOM_HINTS.items():
                if any(hint in m for m in installed):
                    result['installed'] = True
                    result['custom_match'] = hint
                    result['custom_desc'] = desc
                    break
        result['pull_command'] = f'ollama pull {tier["tag"]}'
        return result

    return {
        'hardware': {
            'total_ram_gb': round(total_ram, 1),
            'free_ram_gb': round(free_ram, 1),
            'usable_for_model_gb': round(usable_gb, 1),
            'has_nvidia_gpu': has_gpu,
            'gpus': gpus,
        },
        'recommended': {
            'role_play': mark(recommended_role),
            'auxiliary': mark(recommended_aux),
        },
        'all_tiers': [mark(tier) for tier in MODEL_TIERS],
        'policy': '准确性优先，速度其次；模式配置中的模型只是偏好，不构成授权',
    }
