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

# Model tiers ordered by capability. Real-world tested on GTX 1060 laptop:
# LFM2.5-24B-A2B = reliable (no thinking mode issues, direct output)
# qwen3.5:9b = thinking mode cannot be disabled (enable_thinking=false fails)
# qwen3:4b = fast and accurate for classification but cannot do role-play
MODEL_TIERS = [
    {'id': 'tiny', 'tag': 'qwen3:1.7b', 'ram_gb': 1.5, 'label': 'Qwen3 1.7B',
     'use': '快速分类、意图判断（辅助任务）'},
    {'id': 'small', 'tag': 'qwen3:4b', 'ram_gb': 2.5, 'label': 'Qwen3 4B',
     'use': '辅助任务全量：分类、摘要、意图判断（不能做角色扮演）'},
    {'id': 'lfm25', 'tag': 'LFM2.5-24B-A2B-Q4_K_M', 'ram_gb': 14.5,
     'label': 'LFM2.5 24B MoE',
     'use': '角色扮演主力、翻译、复杂问答（实测无思考模式问题，直出正文）',
     'endpoint': 'http://192.168.31.227:8084/v1',
     'notes': '需 serve-lfm25.cmd 启动；qwen3.5 思考模式关不掉，此为可靠替代'},
    {'id': 'qwen35-9b', 'tag': 'qwen3.5:9b', 'ram_gb': 6.1, 'label': 'Qwen3.5 9B',
     'use': '⚠️ 思考模式关不掉，正文为空，不推荐生产使用',
     'endpoint': 'http://192.168.31.227:8082/v1',
     'notes': 'enable_thinking=false 和 /nothink 均无效'},
    {'id': 'xlarge', 'tag': 'qwen3:30b-a3b', 'ram_gb': 18.0, 'label': 'Qwen3 30B MoE',
     'use': '最强本地推理（需要充足空闲内存，本机 32GB 不可行）'},
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
    # Role-play: prefer LFM2.5-24B (reliable, no thinking issues, 24B knowledge)
    recommended_role = next(
        (tier for tier in reversed(usable)
         if tier.get('id') == 'lfm25' and tier['ram_gb'] <= usable_gb),
        None)
    if recommended_role is None:
        # Fall back to largest usable tier with >= 5GB
        recommended_role = next(
            (tier for tier in reversed(usable) if tier['ram_gb'] >= 5.0), None)
    # Auxiliary: prefer qwen3:4b (fast, 100% accurate for classification)
    recommended_aux = next(
        (tier for tier in usable if tier.get('id') == 'small'), None)
    if recommended_aux is None:
        recommended_aux = usable[0] if usable else None

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
