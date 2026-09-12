"""Validate project continuity without modifying records."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sumika_next.continuity import validate
if __name__ == "__main__":
    validate(ROOT)
    print("continuity records: ok")
