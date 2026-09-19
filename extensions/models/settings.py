"""Role-model settings contract with explicit switches and no stored secrets.

Settings live in the user profile, never in the repository. Any value that looks
like an API key is rejected so a working credential cannot be committed by
accident.
"""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from sumika_next.paths import user_data_directory

SCHEMA_VERSION = 1
PROVIDERS = ("ollama", "openai-compatible")
KEY_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
SECRET_PATTERN = re.compile(r"(^sk-[A-Za-z0-9])|(api[_-]?key\s*[:=])|(bearer\s+[A-Za-z0-9._-]{16,})", re.IGNORECASE)
SECRET_FIELDS = ("key", "api_key", "apikey", "token", "secret", "password", "authorization")


def default_path():
    return user_data_directory() / "role-model-settings.json"


def _reject_secrets(value, trail="settings"):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.strip().casefold() in SECRET_FIELDS:
                raise ValueError(f"{trail}.{key} must not hold a credential; use key_env instead")
            _reject_secrets(item, f"{trail}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{trail}[{index}]")
    elif isinstance(value, str) and SECRET_PATTERN.search(value):
        raise ValueError(f"{trail} looks like a credential; store only an environment variable name")


def _required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value.strip()


def validate(settings):
    if not isinstance(settings, dict) or settings.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid settings schema")
    _reject_secrets(settings)
    if type(settings.get("enabled")) is not bool:
        raise ValueError("enabled must be boolean")
    provider = settings.get("provider")
    if provider not in PROVIDERS:
        raise ValueError("unsupported provider; no fallback is applied")
    _required_text(settings.get("model"), "model")
    endpoint = _required_text(settings.get("endpoint"), "endpoint")
    parsed = urlparse(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("invalid endpoint")
    if parsed.username or parsed.password:
        raise ValueError("endpoint must not embed credentials")
    if provider == "openai-compatible":
        if parsed.scheme != "https":
            raise ValueError("cloud provider requires https")
        key_env = _required_text(settings.get("key_env"), "key_env")
        if not KEY_ENV_PATTERN.match(key_env):
            raise ValueError("key_env must be an environment variable name")
    if provider == "ollama":
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1") and parsed.scheme != "https":
            raise ValueError("local provider must use loopback or https")
    for name, low, high in (("timeout_seconds", 1, 900), ("max_tokens", 1, 32768),
                            ("context_length", 512, 1_000_000)):
        value = settings.get(name)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"invalid {name}")
    temperature = settings.get("temperature")
    if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError("invalid temperature")
    language = settings.get("language")
    if not isinstance(language, dict):
        raise ValueError("language section required")
    _required_text(language.get("target"), "language.target")
    policy = language.get("policy")
    if policy is not None and (not isinstance(policy, str) or not policy.strip()):
        raise ValueError("language.policy must be null or nonempty text")
    if type(language.get("allow_card_policy")) is not bool:
        raise ValueError("language.allow_card_policy must be boolean")
    usage = settings.get("usage")
    if not isinstance(usage, dict) or type(usage.get("enabled")) is not bool:
        raise ValueError("usage.enabled must be boolean")
    role = settings.get("role")
    if not isinstance(role, dict):
        raise ValueError("role section required")
    _required_text(role.get("role_dir"), "role.role_dir")
    _required_text(role.get("database"), "role.database")
    _required_text(role.get("user_id"), "role.user_id")
    _required_text(role.get("project_id"), "role.project_id")
    if role.get("memory_provider") not in ("embedded", "semantic"):
        raise ValueError("unsupported memory provider")
    if type(role.get("card_context_enabled")) is not bool:
        raise ValueError("role.card_context_enabled must be boolean")
    if type(role.get("card_context_budget_chars")) is not int or role["card_context_budget_chars"] < 1:
        raise ValueError("invalid card context budget")
    # Defaults keep older settings files loadable; the switch still starts off.
    multimodal = settings.setdefault("multimodal", {"enabled": False, "max_images": 4,
                                                    "max_image_bytes": 4_000_000})
    if not isinstance(multimodal, dict):
        raise ValueError("multimodal section required")
    if type(multimodal.get("enabled")) is not bool:
        raise ValueError("multimodal.enabled must be boolean")
    if type(multimodal.get("max_images")) is not int or not 1 <= multimodal["max_images"] <= 8:
        raise ValueError("multimodal.max_images must be between 1 and 8")
    if type(multimodal.get("max_image_bytes")) is not int or not 1024 <= multimodal["max_image_bytes"] <= 20_000_000:
        raise ValueError("multimodal.max_image_bytes out of range")
    # Voice starts disabled and never relies on the system default input device:
    # on machines with virtual audio devices the default is often silent.
    voice = settings.setdefault("voice", {
        "enabled": False, "input_device": None, "sample_rate": 16000,
        "tts_voice": "Microsoft Huihui Desktop - Chinese (Simplified)",
        "asr_model": ".sumika-next/voice-models/vosk-model-small-cn-0.22"})
    if not isinstance(voice, dict):
        raise ValueError("voice section required")
    if type(voice.get("enabled")) is not bool:
        raise ValueError("voice.enabled must be boolean")
    device = voice.get("input_device")
    if device is not None and (type(device) is not int or device < 0):
        raise ValueError("voice.input_device must be null or a non-negative index")
    if type(voice.get("sample_rate")) is not int or not 8000 <= voice["sample_rate"] <= 192000:
        raise ValueError("voice.sample_rate out of range")
    for name in ("tts_voice", "asr_model"):
        if not isinstance(voice.get(name), str) or not voice[name].strip():
            raise ValueError(f"voice.{name} must be nonempty text")
    # Playback does not need an input device. Recording validates the explicit
    # device and microphone authorization at execution, never guesses a default.
    # Automatic extraction is off unless the user turns it on: ordinary chat
    # should not silently start writing to long-term memory.
    memory = settings.setdefault("memory", {"auto_extract": False, "extract_threshold": 0.8,
                                            "max_extracts_per_turn": 3})
    if not isinstance(memory, dict):
        raise ValueError("memory section required")
    memory.setdefault('enabled',True)
    memory.setdefault('model_proposals',False)
    if type(memory['model_proposals']) is not bool:
        raise ValueError('memory.model_proposals must be boolean')
    if type(memory['enabled']) is not bool:
        raise ValueError('memory.enabled must be boolean')
    if type(memory.get("auto_extract")) is not bool:
        raise ValueError("memory.auto_extract must be boolean")
    if not isinstance(memory.get("extract_threshold"), (int, float)) \
            or not 0 <= memory["extract_threshold"] <= 1:
        raise ValueError("memory.extract_threshold out of range")
    if type(memory.get("max_extracts_per_turn")) is not int \
            or not 1 <= memory["max_extracts_per_turn"] <= 10:
        raise ValueError("memory.max_extracts_per_turn out of range")
    startup = settings.setdefault("startup", {"auto_start": False, "tray": True})
    if not isinstance(startup, dict):
        raise ValueError("startup section required")
    for key in ("auto_start", "tray"):
        if type(startup.get(key)) is not bool:
            raise ValueError(f"startup.{key} must be boolean")
    enhancement = settings.setdefault('prompt_enhancement', {'enabled': True})
    auxiliary = settings.setdefault('auxiliary', {
        'enabled': False, 'provider': 'ollama', 'model': 'qwen3:1.7b',
        'endpoint': 'http://127.0.0.1:11434', 'key_env': 'AUXILIARY_MODEL_API_KEY',
        'timeout_seconds': 60, 'max_tokens': 512, 'temperature': 0.2,
        'context_length': 4096,
    })
    if not isinstance(auxiliary, dict):
        raise ValueError('auxiliary section required')
    auxiliary.setdefault('capabilities', ['prompt_enhancement'])
    if (not isinstance(auxiliary['capabilities'], list) or
            any(c not in ('prompt_enhancement', 'task_intent') for c in auxiliary['capabilities']) or
            len(set(auxiliary['capabilities'])) != len(auxiliary['capabilities'])):
        raise ValueError('invalid auxiliary capabilities')
    if type(auxiliary.get('enabled')) is not bool:
        raise ValueError('auxiliary.enabled must be boolean')
    aux_provider = auxiliary.get('provider')
    if aux_provider not in PROVIDERS:
        raise ValueError('unsupported auxiliary provider; no fallback is applied')
    _required_text(auxiliary.get('model'), 'auxiliary.model')
    aux_endpoint = _required_text(auxiliary.get('endpoint'), 'auxiliary.endpoint')
    aux_parsed = urlparse(aux_endpoint)
    if aux_parsed.scheme not in ('http', 'https') or not aux_parsed.hostname:
        raise ValueError('invalid auxiliary endpoint')
    if aux_parsed.username or aux_parsed.password:
        raise ValueError('auxiliary endpoint must not embed credentials')
    if aux_provider == 'openai-compatible':
        if aux_parsed.scheme != 'https':
            raise ValueError('auxiliary cloud provider requires https')
        aux_key_env = _required_text(auxiliary.get('key_env'), 'auxiliary.key_env')
        if not KEY_ENV_PATTERN.match(aux_key_env):
            raise ValueError('invalid auxiliary key_env')
    elif aux_parsed.hostname not in ('127.0.0.1', 'localhost', '::1') and aux_parsed.scheme != 'https':
        raise ValueError('auxiliary local provider must use loopback or https')
    for name, low, high in (('timeout_seconds', 1, 900), ('max_tokens', 1, 32768),
                            ('context_length', 512, 1_000_000)):
        value = auxiliary.get(name)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'invalid auxiliary {name}')
    if not isinstance(auxiliary.get('temperature'), (int, float)) or not 0 <= auxiliary['temperature'] <= 2:
        raise ValueError('invalid auxiliary temperature')
    library=settings.setdefault('model_library',{'roots':[],'auto_scan':False})
    if not isinstance(library,dict) or type(library.get('auto_scan')) is not bool:
        raise ValueError('invalid model library settings')
    roots=library.get('roots')
    if not isinstance(roots,list) or len(roots)>16 or any(not isinstance(p,str) or not Path(p).is_absolute() for p in roots):
        raise ValueError('model roots must be absolute paths, maximum 16')
    if not isinstance(enhancement, dict) or type(enhancement.get('enabled')) is not bool:
        raise ValueError('prompt_enhancement.enabled must be boolean')
    return settings


def load(path=None):
    target = Path(path) if path is not None else default_path()
    value = json.loads(Path(target).read_text(encoding="utf8"))
    return validate(value)


def save(settings, path=None):
    validate(settings)
    target = Path(path) if path is not None else default_path()
    # Resolve the parent first: sandboxed and redirected profiles can point the
    # friendly path at another volume, which makes os.replace report EXDEV.
    parent = target.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    resolved = parent / target.name
    temporary = parent / (target.name + ".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    os.replace(temporary, resolved)
    return resolved


def example(role_dir, database):
    """A valid starting point; the user chooses provider, model and switches."""
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": False,
        "provider": "openai-compatible",
        "model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "timeout_seconds": 180,
        "max_tokens": 1024,
        "temperature": 0.7,
        "context_length": 8192,
        "language": {"target": "zh-Hans", "policy": None, "allow_card_policy": True},
        "usage": {"enabled": True},
        "multimodal": {"enabled": False, "max_images": 4, "max_image_bytes": 4_000_000},
        "voice": {"enabled": False, "input_device": None, "sample_rate": 16000,
                  "tts_voice": "Microsoft Huihui Desktop - Chinese (Simplified)",
                  "asr_model": ".sumika-next/voice-models/vosk-model-small-cn-0.22"},
        "memory": {"auto_extract": False, "extract_threshold": 0.8, "max_extracts_per_turn": 3},
        "startup": {"auto_start": False, "tray": True},
        "auxiliary": {"enabled": False, "provider": "ollama", "model": "sumika-minicpm5-2b:latest",
                       "endpoint": "http://127.0.0.1:11434", "key_env": "AUXILIARY_MODEL_API_KEY",
                       "timeout_seconds": 60, "max_tokens": 512, "temperature": 0.2,
                       "context_length": 4096, "capabilities": ["prompt_enhancement"]},
        "role": {
            "role_dir": str(role_dir),
            "database": str(database),
            "user_id": "local-user",
            "project_id": "sumika",
            "memory_provider": "embedded",
            "card_context_enabled": True,
            "card_context_budget_chars": 10000,
        },
    }
