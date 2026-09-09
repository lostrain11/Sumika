"""Bounded ModelScope community-credit tests, with no commercial API fallback."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.evaluate_siliconflow_candidates import main


if __name__ == "__main__":
    try:
        raise SystemExit(main(provider="modelscope"))
    except Exception as error:
        print(json.dumps({"ok": False, "failure_class": type(error).__name__}))
        raise SystemExit(1) from None
