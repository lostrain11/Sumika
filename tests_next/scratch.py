"""ACL-safe scratch directories for the test suite.

Python 3.14 ``tempfile.mkdtemp()`` creates directories with a protected ACL that
the restricted workspace token cannot write into on Windows (see
``docs/project/decisions.json`` D-006). A plain ``mkdir`` under the system temp
root inherits the parent ACL and works in both a normal shell and the DSH
sandbox.
"""
from pathlib import Path
import shutil
import tempfile
import uuid


class ScratchDirectory:
    """Drop-in replacement for ``tempfile.TemporaryDirectory`` in these tests."""

    def __init__(self, base=None):
        parent = Path(base) if base is not None else Path(tempfile.gettempdir())
        self.name = str(parent / f"sumika-test-{uuid.uuid4().hex}")
        Path(self.name).mkdir()

    def cleanup(self):
        shutil.rmtree(self.name, ignore_errors=True)

    def __enter__(self):
        return self.name

    def __exit__(self, *exc_info):
        self.cleanup()
        return False
