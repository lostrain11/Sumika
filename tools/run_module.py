"""Run a packaged Python module after explicitly adding the product root.

Bundled Python uses an isolated ``_pth`` file and intentionally ignores
PYTHONPATH. The product root is therefore supplied by the launcher itself.
"""
import runpy
import sys
from pathlib import Path

if len(sys.argv) < 2:
    raise SystemExit('usage: run_module.py MODULE [args...]')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
module = sys.argv[1]
sys.argv = [module, *sys.argv[2:]]
runpy.run_module(module, run_name='__main__')
