"""Managed loopback SSH tunnel for a local auxiliary model.

The tunnel is an explicitly enabled transport, not a second model provider.
It never stores credentials, never binds a LAN address, and never falls back
to the remote laptop's HTTP port directly. Configuration validation lives in
``extensions.models.settings``; this module owns the process lifecycle.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class TunnelError(ValueError):
    pass


def _iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tunnel_config(settings):
    """Derive the transport from the settings that the UI already saved."""
    auxiliary = settings["auxiliary"]
    tunnel = auxiliary.get("tunnel") or {}
    endpoint = urlparse(auxiliary["endpoint"])
    health_path = "/api/tags" if auxiliary["provider"] == "ollama" else "/v1/models"
    local_port = endpoint.port
    return {
        "enabled": tunnel.get("enabled") is True and auxiliary.get("enabled") is True,
        "host": tunnel.get("host", ""),
        "user": tunnel.get("user", ""),
        "ssh_port": tunnel.get("ssh_port", 22),
        "remote_port": tunnel.get("remote_port", 11434),
        "local_port": local_port,
        "provider": auxiliary["provider"],
        "model": auxiliary.get("model", ""),
        "preload": tunnel.get("preload") is True,
        "api_url": f"http://127.0.0.1:{local_port}" if local_port else None,
        "health_path": health_path,
        "health_url": (f"http://127.0.0.1:{local_port}{health_path}"
                       if local_port else None),
    }


def _fingerprint(config):
    return json.dumps(config, sort_keys=True, ensure_ascii=False)


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class LocalTunnel:
    """One SSH child plus one supervisor; status is always observed, never invented."""

    def __init__(self, settings_path, *, data_directory=None, ssh_executable=None,
                 start_timeout=10.0, poll_seconds=2.0):
        self.settings_path = Path(settings_path)
        self.data_directory = Path(data_directory) if data_directory else self.settings_path.parent / "tunnel"
        self.ssh_executable = (ssh_executable if ssh_executable is not None
                               else shutil.which("ssh"))
        self.start_timeout = start_timeout
        self.poll_seconds = poll_seconds
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._stop.set()
        self._config = None
        self._fingerprint = None
        self._proc = None
        self._log = None
        self._log_path = self.data_directory / "tunnel.log"
        self._supervisor = None
        self._healthy = False
        self._error = ""
        self._restarts = 0
        self._started_at = None
        self._last_check = None
        self._preload_state = "idle"
        self._preload_error = ""
        self._preloaded_at = None

    # -- configuration -------------------------------------------------
    def configure(self, settings):
        config = tunnel_config(settings)
        fingerprint = _fingerprint(config)
        with self._lock:
            previous = self._fingerprint
            self._config = config
            self._fingerprint = fingerprint
            running = self._running_locked()
            if previous != fingerprint:
                self._preload_state = "idle"
                self._preload_error = ""
                self._preloaded_at = None
        if not config["enabled"]:
            self.stop()
        elif previous is not None and previous != fingerprint:
            self.restart_async()
        elif not running:
            self.start_async()
        return self.status()

    def autostart(self):
        try:
            settings = json.loads(self.settings_path.read_text(encoding="utf8"))
            self.configure(settings)
        except (OSError, ValueError, KeyError) as error:
            with self._lock:
                self._error = f"tunnel configuration unavailable: {error}"
        return self.status()

    # -- lifecycle -----------------------------------------------------
    def start(self):
        with self._lock:
            if self._running_locked():
                return self.status()
            if self._config is None:
                self._config = tunnel_config(json.loads(self.settings_path.read_text(encoding="utf8")))
            config = self._config
            if not config["enabled"]:
                raise TunnelError("SSH tunnel is not enabled")
            if not config.get("local_port"):
                raise TunnelError("tunnel endpoint must include a port")
            if not self.ssh_executable or not Path(self.ssh_executable).is_file():
                raise TunnelError("OpenSSH client is not available")
            if not _port_free(config["local_port"]):
                raise TunnelError(f"local port {config['local_port']} is already in use")
            self._stop.clear()
            self._error = ""
            if not self._launch_locked():
                raise TunnelError(self._error or "SSH tunnel failed to start")
            self._supervisor = threading.Thread(
                target=self._supervise, name="sumika-local-tunnel", daemon=True)
            self._supervisor.start()
            return self.status()

    def start_async(self):
        threading.Thread(target=self._start_quiet, name="sumika-local-tunnel-start",
                         daemon=True).start()

    def restart_async(self):
        def run():
            self.stop()
            try:
                self.start()
            except (OSError, ValueError, TunnelError):
                pass
        threading.Thread(target=run, name="sumika-local-tunnel-restart", daemon=True).start()

    def _start_quiet(self):
        try:
            self.start()
        except (OSError, ValueError, TunnelError) as error:
            with self._lock:
                self._error = str(error)

    def stop(self):
        with self._lock:
            self._stop.set()
            proc = self._proc
            self._proc = None
            log = self._log
            self._log = None
            self._healthy = False
            supervisor = self._supervisor
            self._supervisor = None
            self._started_at = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass
        if log is not None:
            try:
                log.close()
            except OSError:
                pass
        if supervisor is not None and supervisor is not threading.current_thread():
            supervisor.join(timeout=5)
        return self.status()

    close = stop

    # -- process/health ------------------------------------------------
    def _running_locked(self):
        return self._proc is not None and self._proc.poll() is None

    def _launch_locked(self):
        config = self._config
        if config is None or self._stop.is_set():
            return False
        with self._lock:
            previous_log = self._log
            self._log = None
        if previous_log is not None:
            try:
                previous_log.close()
            except OSError:
                pass
        self.data_directory.mkdir(parents=True, exist_ok=True)
        try:
            if self._log_path.exists() and self._log_path.stat().st_size > 1_000_000:
                self._log_path.replace(self._log_path.with_suffix(".log.1"))
            log = open(self._log_path, "ab", buffering=0)
        except OSError as error:
            self._error = f"tunnel log unavailable: {error}"
            return False
        command = [
            self.ssh_executable, "-N",
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-o", "ConnectTimeout=8",
            "-L", f"127.0.0.1:{config['local_port']}:127.0.0.1:{config['remote_port']}",
            "-p", str(config["ssh_port"]),
            f"{config['user']}@{config['host']}",
        ]
        try:
            proc = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError as error:
            log.close()
            self._error = f"SSH tunnel failed: {error}"
            return False
        if self._stop.is_set():
            try:
                proc.terminate()
            except OSError:
                pass
            log.close()
            return False
        with self._lock:
            self._proc = proc
            self._log = log
            self._started_at = _iso_now()
            self._healthy = False
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if self._stop.is_set():
                return False
            if proc.poll() is not None:
                self._error = self._tail() or "SSH tunnel exited before it was ready"
                log.close()
                with self._lock:
                    self._proc = None
                    self._log = None
                    self._healthy = False
                return False
            if config.get("health_url") and self._probe(config["health_url"]):
                with self._lock:
                    self._healthy = True
                    self._error = ""
                self._maybe_preload()
                return True
            time.sleep(0.25)
        with self._lock:
            self._healthy = False
            self._error = "SSH tunnel started, but the local health check did not pass"
        return True

    def _maybe_preload(self):
        config = self._config
        if (not config or not config.get("preload") or config.get("provider") != "ollama"
                or not config.get("model") or not config.get("api_url")):
            return
        with self._lock:
            if self._preload_state in ("warming", "ready"):
                return
            self._preload_state = "warming"
            self._preload_error = ""
        threading.Thread(target=self._preload_worker, name="sumika-tunnel-preload",
                         daemon=True).start()

    def _preload_worker(self):
        config = self._config
        if not config:
            return
        body = json.dumps({"model": config["model"], "prompt": "", "stream": False,
                           "keep_alive": "30m"}).encode("utf8")
        request = Request(config["api_url"] + "/api/generate", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=240) as response:
                if not 200 <= response.status < 300:
                    raise OSError(f"preload HTTP {response.status}")
            with self._lock:
                self._preload_state = "ready"
                self._preloaded_at = _iso_now()
        except (OSError, ValueError) as error:
            with self._lock:
                self._preload_state = "error"
                self._preload_error = str(error)[:300]

    def _supervise(self):
        backoff = 2
        while not self._stop.is_set():
            proc = self._proc
            if proc is None or proc.poll() is not None:
                if self._stop.is_set():
                    break
                self._healthy = False
                self._error = self._tail() or "SSH tunnel exited; reconnecting"
                self._restarts += 1
                if self._stop.wait(backoff):
                    break
                if not self._launch_locked():
                    backoff = min(30, backoff * 2)
                    continue
                backoff = 2
            else:
                config = self._config
                if config is None:
                    break
                healthy = bool(config.get("health_url")) and self._probe(config["health_url"])
                self._healthy = healthy
                self._last_check = _iso_now()
                if healthy:
                    self._error = ""
                elif not self._error:
                    self._error = "local health check failed"
            if self._stop.wait(self.poll_seconds):
                break

    @staticmethod
    def _probe(url):
        try:
            with urlopen(url, timeout=2) as response:
                return 200 <= response.status < 300
        except (OSError, ValueError):
            return False

    def _tail(self):
        try:
            with open(self._log_path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 4096))
                text = handle.read().decode("utf8", "replace")
        except OSError:
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1][:500] if lines else ""

    # -- observable status --------------------------------------------
    def status(self):
        with self._lock:
            config = self._config or {}
            running = self._running_locked()
            return {
                "enabled": config.get("enabled") is True,
                "running": running,
                "healthy": bool(running and self._healthy),
                "pid": self._proc.pid if running else None,
                "local_port": config.get("local_port"),
                "remote": (f"{config.get('host')}:{config.get('remote_port')}"
                           if config.get("host") else None),
                "ssh_available": bool(self.ssh_executable and Path(self.ssh_executable).is_file()),
                "last_error": self._error,
                "restarts": self._restarts,
                "started_at": self._started_at,
                "last_check": self._last_check,
                "preload": self._preload_state,
                "preload_error": self._preload_error,
                "preloaded_at": self._preloaded_at,
            }
