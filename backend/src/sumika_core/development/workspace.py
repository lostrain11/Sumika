from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

from quality_routing import RoutingError


_EXCLUDED = {".git", ".sumika", ".env", ".ssh", ".aws", "node_modules", "target", "__pycache__",
             ".venv", "venv", "artifacts", "dist", "coverage", "deprecated"}
_SECRET = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ms-[0-9a-f-]{36})")
_MAX_FILE = 256 * 1024


def _relative(path):
    if not isinstance(path, str) or not path or "\\" in path or ":" in path or any(ord(char) < 32 for char in path):
        raise RoutingError("invalid source path")
    value = PurePosixPath(path)
    if value.is_absolute() or any(part in {"..", "."} for part in path.split("/")):
        raise RoutingError("source path escapes workspace")
    if any(part.lower() in _EXCLUDED or part.lower().startswith(".env.") for part in value.parts):
        raise RoutingError("runtime or private path is not available")
    if value.suffix.lower() in {".pem", ".key", ".p12", ".sqlite", ".db", ".vrm", ".exe", ".dll"}:
        raise RoutingError("private or binary assets are not available")
    return value.as_posix()


def _checked(root, path):
    path = _relative(path)
    target = root / path
    for parent in [root, *[root.joinpath(*PurePosixPath(path).parts[:index]) for index in range(1, len(PurePosixPath(path).parts) + 1)]]:
        if parent.exists() or parent.is_symlink():
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise RoutingError("linked source paths are not supported")
    if not target.resolve().is_relative_to(root.resolve()):
        raise RoutingError("source path escapes workspace")
    return target


def _read(path):
    if not path.is_file() or path.stat().st_size > _MAX_FILE:
        raise RoutingError("source file is missing or exceeds 256 KiB")
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if "\x00" in text or _SECRET.search(text):
        raise RoutingError("binary or credential-like source content is not available")
    return raw, text


def _git(root, *args, input=None):
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=", "-C", str(root), *args],
                            input=input, capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RoutingError("Git source inspection failed")
    return result.stdout


def development_spec(directory, params):
    if not isinstance(directory, str) or not Path(directory).is_absolute():
        raise RoutingError("bind an absolute Git project directory before development")
    root = Path(directory).resolve(strict=True)
    if Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root:
        raise RoutingError("development requires the project repository root")
    commands = params.get("test_commands", [])
    if not isinstance(commands, list) or len(commands) > 8:
        raise RoutingError("provide at most eight explicit test commands")
    for command in commands:
        if (not isinstance(command, list) or not command or len(command) > 40
                or any(not isinstance(arg, str) or not arg or len(arg) > 2048 or any(ord(char) < 32 for char in arg) for arg in command)
                or _SECRET.search(json.dumps(command))):
            raise RoutingError("each test command must be an argument array without credentials")
    return {"schema_version": "sumika.development/v1", "directory": str(root), "test_commands": commands,
            "max_calls": 20, "max_input_tokens": 64000, "max_output_tokens": 4096, "test_timeout_seconds": 120,
            "isolation": "source-copy-not-os-sandbox"}


class DevelopmentWorkspace:
    def __init__(self, base, spec, checkpoints, cancelled):
        self.spec = spec
        self.checkpoints = checkpoints
        self.cancelled = cancelled
        self.base = Path(base)
        self.root = None
        self.checkpoint_id = None
        self.skipped = []

    def prepare(self):
        source = Path(self.spec["directory"])
        self.base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="development-", dir=self.base))
        paths = sorted(set(_git(source, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode("utf-8").split("\x00")) - {""})
        if len(paths) > 10000:
            raise RoutingError("source inventory exceeds 10000 files")
        copied, total = [], 0
        for path in paths:
            if self.cancelled():
                raise RoutingError("development cancelled before source copy")
            try:
                origin = _checked(source, path)
                raw, content = _read(origin)
            except (RoutingError, UnicodeError, OSError):
                self.skipped.append(path)
                continue
            total += len(raw)
            if total > 64 * 1024 * 1024:
                raise RoutingError("source copy exceeds 64 MiB")
            target = _checked(self.root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            shutil.copymode(origin, target)
            copied.append(path)
        _git(self.root, "init", "--template=")
        if copied:
            _git(self.root, "add", "--force", "--pathspec-from-file=-", "--pathspec-file-nul",
                 input=("\x00".join(copied) + "\x00").encode("utf-8"))
        self.checkpoint_id = self.checkpoints.create_checkpoint(self.root, name="Development source baseline")["checkpoint"]["id"]
        return {"path": str(self.root), "checkpoint_id": self.checkpoint_id, "files": copied, "skipped": self.skipped,
                "isolation": self.spec["isolation"]}

    def execute(self, name, arguments):
        if self.cancelled():
            raise RoutingError("development is cancelled")
        if name == "list_files" and not arguments:
            return {"files": self.inventory()}
        if name == "get_diff" and not arguments:
            return self.diff()
        if name == "read_file" and set(arguments) == {"path"}:
            raw, content = _read(_checked(self.root, arguments["path"]))
            return {"path": arguments["path"], "content": content, "sha256": hashlib.sha256(raw).hexdigest()}
        if name == "write_file" and set(arguments) == {"path", "content", "expected_sha256"}:
            target = _checked(self.root, arguments["path"])
            content = arguments["content"]
            if not isinstance(content, str) or len(content.encode()) > _MAX_FILE or _SECRET.search(content) or "\x00" in content:
                raise RoutingError("invalid source content")
            current = hashlib.sha256(_read(target)[0]).hexdigest() if target.exists() else ""
            if current != arguments["expected_sha256"]:
                raise RoutingError("file changed since read; read it again")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))
            return {"path": arguments["path"], "sha256": hashlib.sha256(content.encode()).hexdigest()}
        if name == "run_test" and set(arguments) == {"index"}:
            index = arguments["index"]
            if type(index) is not int or not 0 <= index < len(self.spec["test_commands"]):
                raise RoutingError("test command is not authorized")
            return self.run_test(index)
        raise RoutingError("unknown tool or invalid arguments")

    def inventory(self):
        return sorted(path for path in set(_git(self.root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\x00")) if path)

    def diff(self):
        return self.checkpoints.patch_checkpoint(self.checkpoint_id, path=self.root)

    def run_test(self, index):
        command = self.spec["test_commands"][index]
        environment = {key: value for key, value in os.environ.items() if key.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "SYSTEMDRIVE"}}
        environment.update(PYTHONIOENCODING="utf-8", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
        environment["PYTHONPATH"] = os.pathsep.join(str(self.root / path) for path in ("backend/src", "packages/quality-routing/src", "backend/tests"))
        environment["SUMIKA_DATA_DIR"] = str(self.root / ".sumika")
        started = time.monotonic()
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(command, cwd=self.root, env=environment, stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, shell=False, start_new_session=os.name != "nt",
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            reason = None
            while process.poll() is None:
                if self.cancelled() or time.monotonic() - started > self.spec["test_timeout_seconds"] or output.tell() > 1024 * 1024:
                    reason = "cancelled" if self.cancelled() else "limit-reached"
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                    else:
                        import signal
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    break
                time.sleep(.05)
            output.seek(0)
            text = output.read(16000).decode("utf-8", errors="replace")
        text = _SECRET.sub("[redacted]", text)
        return {"index": index, "command": command, "exit_code": process.returncode, "status": reason or "finished",
                "output": text, "duration_seconds": round(time.monotonic() - started, 3)}
