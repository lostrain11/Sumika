"""Save Spark Lite or Moark HTTP credentials without exposing them."""
import argparse
import getpass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
from sumika_core.provider_profiles import ProviderProfileManager
from sumika_core.storage import Storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=("spark-lite", "moark"), default="spark-lite")
    args = parser.parse_args()
    directory = args.data_dir.resolve()
    storage = Storage(directory / "sumika.sqlite3")
    vault = WindowsCredentialStore(credential_namespace_for_data_dir(directory))
    profiles = ProviderProfileManager(storage, vault)
    credential = getpass.getpass(args.provider + " HTTP credential (hidden): ")
    try:
        if not credential or len(credential) > 512 or any(ord(character) < 33 for character in credential):
            raise ValueError("invalid APIPassword")
        settings = ({"id": "spark-lite-free-candidates", "name": "讯飞 Spark Lite 免费",
                     "base_url": "https://spark-api-open.xf-yun.com/v1", "models": ["lite"], "headers": {}}
                    if args.provider == "spark-lite" else
                    {"id": "moark-free-candidates", "name": "Moark 官方 API",
                     "base_url": "https://api.moark.com/v1", "models": ["Qwen3-8B", "DeepSeek-R1-Distill-Qwen-14B", "GLM-4-9B-0414"],
                     "headers": {"X-Failover-Enabled": "false"}})
        profile = profiles.save({"id": settings["id"], "name": settings["name"],
            "template_id": "openai-compatible", "processing_location": "cloud",
            "base_url": settings["base_url"], "model": settings["models"][0], "timeout": 40, "headers": settings["headers"],
            "models": [{"id": model, "enabled": True, "quality_tier": "unknown", "capabilities": ["chat"]} for model in settings["models"]],
            "api_key": credential})
        verified = vault.read(profile["id"]).get("api_key") == credential
        print(json.dumps({"profile_id": profile["id"], "credential_saved_and_verified": verified, "routable": False}))
    finally:
        credential = None
        storage.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"ok": False, "failure_class": type(error).__name__}))
        raise SystemExit(1) from None
