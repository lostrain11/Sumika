from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .benefit_sources import SOURCE_SPECS, collect
from .browser import looks_like_secret_text
from .provider_profiles import provider_account_revision


SCHEMA = "free-benefits/v1"
MODELSCOPE_PROFILE = "modelscope-free-candidates"
CHINA_TIME = timezone(timedelta(hours=8))
CHECKIN_STATES = {"never", "running", "verified", "login-required", "challenge", "needs-review", "unavailable", "interrupted"}


class BenefitsError(ValueError):
    pass


class BenefitsBusy(BenefitsError):
    pass


@contextmanager
def _file_lock(path: Path | None, *, wait_seconds: float = 0):
    if path is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise BenefitsBusy("benefits operation is busy") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def _text(value: Any, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or looks_like_secret_text(value):
        raise BenefitsError("invalid benefit text")
    if any(ord(char) < 32 for char in value):
        raise BenefitsError("invalid benefit text")
    return value.strip()


def _browser_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value) or value.startswith("-") or looks_like_secret_text(value):
        raise BenefitsError("select an explicit connected browser")
    return value


def _empty_checkin() -> dict[str, Any]:
    return {"state": "never", "checked_at": None, "available_balance": None, "unit": "magicube",
            "grants": [], "error": None, "account_binding_verified": False,
            "automatic_routing_authorized": False, "exact_expiry_verified": False}


class _CheckinCancellation:
    def __init__(self, revoked: Callable):
        self.signal = threading.Event()
        self.revoked = revoked

    def set(self):
        self.signal.set()

    def is_set(self):
        try:
            return self.signal.is_set() or self.revoked()
        except Exception:
            return True

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.signal.wait(min(remaining, 0.1))
        return True


class BenefitsService:
    def __init__(self, data_dir: Path | None, *, profile_reader: Callable, browser_reader: Any,
                 collector: Callable = collect, sources: list | None = None, now: Callable | None = None):
        self.root = Path(data_dir) / "benefits" if data_dir is not None else None
        self.path = self.root / "state.json" if self.root else None
        self.sources = copy.deepcopy(SOURCE_SPECS if sources is None else sources)
        self.profile_reader = profile_reader
        self.browser_reader = browser_reader
        self.collector = collector
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self._stop = threading.Event()
        self._checkin_stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._store_error = False
        self._state = {"schema": SCHEMA, "enabled": False, "checkin_enabled": False,
                       "browser_instance_id": "", "account_revision": "", "sources": {}, "offers": {},
                       "checkin": _empty_checkin(), "checkin_attempt_date": None}
        try:
            self._load()
        except BenefitsError:
            self._store_error = True

    def _load(self) -> None:
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > 4_000_000:
                    raise ValueError
                state = json.loads(self.path.read_text(encoding="utf-8"))
                if state.get("schema") != SCHEMA or any(not isinstance(state.get(key), dict) for key in ("sources", "offers", "checkin")):
                    raise ValueError
                if any(type(state.get(key)) is not bool for key in ("enabled", "checkin_enabled")):
                    raise ValueError
                if len(state["offers"]) > 2000 or len(state["sources"]) > 100:
                    raise ValueError
                self._state = state
            except (OSError, ValueError, TypeError, AttributeError):
                raise BenefitsError("benefits store needs review; retained without overwrite") from None

    @contextmanager
    def _transaction(self):
        if self._store_error:
            raise BenefitsError("benefits store needs review; retained without overwrite")
        with self._lock, _file_lock(self.root / "state.lock" if self.root else None, wait_seconds=10):
            self._load()
            previous = copy.deepcopy(self._state)
            try:
                yield
                if self.path and self._state != previous:
                    encoded = json.dumps(self._state, ensure_ascii=False, allow_nan=False).encode("utf-8")
                    while len(encoded) > 3_800_000 and self._state["offers"]:
                        offers = self._state["offers"]
                        oldest = sorted(offers, key=lambda key: (offers[key]["state"] != "withdrawn", offers[key]["kind"] != "lead", offers[key]["last_seen_at"]))
                        for key in oldest[:50]:
                            del offers[key]
                        encoded = json.dumps(self._state, ensure_ascii=False, allow_nan=False).encode("utf-8")
                    if len(encoded) > 3_800_000:
                        raise BenefitsError("benefits store capacity exceeded")
                    temporary = self.path.with_suffix("." + uuid4().hex + ".tmp")
                    try:
                        with temporary.open("wb") as stream:
                            stream.write(encoded)
                            stream.flush()
                            os.fsync(stream.fileno())
                        temporary.replace(self.path)
                    finally:
                        temporary.unlink(missing_ok=True)
            except BaseException:
                self._state = previous
                raise

    def _running(self) -> bool:
        if self._operation.locked() or self._thread and self._thread.is_alive():
            return True
        try:
            with _file_lock(self.root / "run.lock" if self.root else None):
                return False
        except BenefitsBusy:
            return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            if not self._store_error:
                self._load()
            state = copy.deepcopy(self._state)
        now = self.now()
        sources = []
        for spec in self.sources:
            item = {**spec, **state["sources"].get(spec["id"], {})}
            observed = _instant(item.get("last_success_at"))
            item["stale"] = not observed or now >= observed + timedelta(seconds=spec["interval_seconds"])
            item.setdefault("status", "never")
            item.setdefault("error", None)
            item.setdefault("last_success_at", None)
            item.setdefault("item_count", 0)
            sources.append(item)
        source_map = {item["id"]: item for item in sources}
        offers = []
        for item in state["offers"].values():
            source = source_map.get(item["source_id"], {})
            observed = _instant(item.get("last_seen_at"))
            item["stale"] = (source.get("stale", True) or source.get("status") != "ready" or
                not observed or now >= observed + timedelta(seconds=source.get("interval_seconds", 0)) or
                item.get("last_seen_at") != source.get("last_success_at"))
            expires = _instant(item.get("expires_at"))
            item["expired"] = expires is not None and expires <= now
            offers.append(item)
        checkin = state["checkin"]
        checked = _instant(checkin.get("checked_at"))
        checkin["stale"] = not checked or checked.astimezone(CHINA_TIME).date() != now.astimezone(CHINA_TIME).date()
        checkin["balance_observed_at"] = checkin.get("checked_at") if checkin.get("state") == "verified" else None
        running = self._running()
        if checkin.get("state") == "running" and not running:
            checkin.update(state="interrupted", error="previous-run-interrupted", stale=True)
        if state.get("account_revision") and self._revision() != state["account_revision"]:
            checkin.update(state="needs-review", error="provider-binding-changed", stale=True)
        return {"schema": SCHEMA, "enabled": state["enabled"], "checkin_enabled": state["checkin_enabled"],
                "browser_instance_id": state["browser_instance_id"], "running": running,
                "sources": sources, "offers": sorted(offers, key=lambda item: item["last_seen_at"], reverse=True),
                "checkin": checkin, "error": "store-needs-review" if self._store_error else None}

    def _revision(self) -> str:
        profile = self.profile_reader(MODELSCOPE_PROFILE)
        if not profile or not profile.get("credential_ref") or profile.get("archived_at"):
            return ""
        return provider_account_revision(profile)

    def browsers(self) -> dict[str, Any]:
        return {"browsers": self.browser_reader.browsers()}

    def configure(self, params: dict) -> dict[str, Any]:
        if set(params) - {"enabled", "checkin_enabled", "browser_instance_id"}:
            raise BenefitsError("unsupported benefits setting")
        for key in ("enabled", "checkin_enabled"):
            if key in params and type(params[key]) is not bool:
                raise BenefitsError("benefits switches must be boolean")
        if "browser_instance_id" in params and params["browser_instance_id"] != "":
            _browser_id(params["browser_instance_id"])
        params = dict(params)
        if params.get("enabled") is False:
            params["checkin_enabled"] = False
        with self._lock:
            self._load()
            desired_browser = params.get("browser_instance_id", self._state["browser_instance_id"])
            confirm = desired_browser != self._state["browser_instance_id"] or params.get("checkin_enabled") is True
        revision = None
        if desired_browser and confirm:
            revision = self._revision()
            if not revision:
                raise BenefitsError("save the ModelScope provider profile before check-in")
            connected = {item["instance_id"] for item in self.browsers()["browsers"]}
            if desired_browser not in connected:
                raise BenefitsError("selected browser is not connected")
        with self._transaction():
            desired = {**self._state, **params}
            if desired["checkin_enabled"] and not desired["enabled"]:
                raise BenefitsError("enable background discovery before automatic check-in")
            changed = desired["browser_instance_id"] != self._state["browser_instance_id"]
            binding = self._state.get("account_revision", "")
            if desired["browser_instance_id"] != desired_browser:
                raise BenefitsBusy("benefits binding changed; retry configuration")
            if revision:
                if revision != self._revision():
                    raise BenefitsError("provider binding changed during confirmation")
                binding = revision
            if desired["checkin_enabled"] and (not desired["browser_instance_id"] or not binding):
                raise BenefitsError("select a browser before enabling check-in")
            if changed or binding != self._state.get("account_revision"):
                self._state["checkin"] = _empty_checkin()
                self._state["checkin_attempt_date"] = None
                self._state.pop("last_verified_checkin", None)
            if changed or binding != self._state.get("account_revision") or params.get("checkin_enabled") is False:
                self._checkin_stop.set()
                self._state["cancel_revision"] = self._state.get("cancel_revision", 0) + 1
            if params.get("checkin_enabled") is True and not self._state["checkin_enabled"]:
                if self._state["checkin"].get("state") != "verified":
                    self._state["checkin"] = _empty_checkin()
                    self._state["checkin_attempt_date"] = None
            self._state.update(params)
            self._state["account_revision"] = binding if desired["browser_instance_id"] else ""
        self._wake.set()
        return self.status()

    def request(self, kind: str) -> dict[str, Any]:
        if kind not in {"refresh", "checkin"} or self._stop.is_set():
            raise BenefitsError("benefits service is closed or request is invalid")
        if self._store_error:
            raise BenefitsError("benefits store needs review")
        if kind == "checkin":
            self._check_binding()
        with self._lock:
            lease = self._claim_operation()
            try:
                self._thread = threading.Thread(target=self._run_owned, args=(lease, kind, True),
                                               name="sumika-benefits-request", daemon=True)
                self._thread.start()
            except BaseException:
                lease.__exit__(None, None, None)
                self._operation.release()
                raise
        return self.status()

    def _check_binding(self) -> tuple[str, str]:
        with self._lock:
            self._load()
            browser = self._state["browser_instance_id"]
            revision = self._state.get("account_revision")
        if not browser or not revision or revision != self._revision():
            raise BenefitsError("confirm the browser and current ModelScope provider before check-in")
        return _browser_id(browser), revision

    def _refresh(self, manual: bool) -> None:
        for spec in self.sources:
            if self._stop.is_set():
                break
            with self._transaction():
                if not manual and not self._state["enabled"]:
                    break
                job = self._state["sources"].setdefault(spec["id"], {})
                now = self.now()
                last = _instant(job.get("last_attempt_at"))
                retry = min(6 * 3600, 300 * 2 ** min(job.get("failure_count", 0), 6))
                interval = 60 if manual else retry if job.get("status") == "unavailable" else spec["interval_seconds"]
                if last and now < last + timedelta(seconds=interval):
                    continue
                job["last_attempt_at"] = now.isoformat()
            try:
                rows = self.collector(spec["id"])
                projected = self._project(rows, spec, now.isoformat())
                with self._transaction():
                    current = self._state["offers"]
                    for item in current.values():
                        if (spec["kind"] in {"public-catalog", "public-pricing", "official"} and
                                item["source_id"] == spec["id"] and item["id"] not in projected):
                            item["state"] = "withdrawn"
                    current.update(projected)
                    if len(current) > 2000:
                        oldest = sorted(current, key=lambda key: (current[key]["state"] != "withdrawn", current[key]["last_seen_at"]))
                        for key in oldest[:len(current) - 2000]:
                            del current[key]
                    self._state["sources"][spec["id"]].update(status="ready", error=None,
                        last_success_at=now.isoformat(), item_count=len(projected), failure_count=0)
            except Exception:
                with self._transaction():
                    job = self._state["sources"][spec["id"]]
                    job.update(status="unavailable", error="source-unavailable-or-schema-changed",
                               failure_count=job.get("failure_count", 0) + 1)

    @staticmethod
    def _project(rows: Any, spec: dict, observed: str) -> dict:
        from urllib.parse import urlsplit
        import ipaddress
        if not isinstance(rows, list) or len(rows) > 200:
            raise BenefitsError("invalid benefits collection")
        result = {}
        for row in rows:
            url = _text(row.get("url"), 2048)
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
                raise BenefitsError("invalid benefit link")
            if "." not in parts.hostname or parts.hostname.endswith((".local", ".localhost", ".internal")):
                raise BenefitsError("invalid benefit link")
            try:
                if not ipaddress.ip_address(parts.hostname).is_global:
                    raise BenefitsError("invalid benefit link")
            except ValueError as error:
                if isinstance(error, BenefitsError):
                    raise
            kind = row.get("kind")
            if kind not in {"lead", "free-model", "credit-program"}:
                raise BenefitsError("invalid benefit kind")
            expires = row.get("expires_at")
            if expires is not None and _instant(expires) is None:
                raise BenefitsError("invalid benefit expiry")
            model = _text(row["model_id"], 180) if row.get("model_id") else None
            provider = _text(row["provider_id"], 80) if row.get("provider_id") else None
            identity = hashlib.sha256((spec["id"] + "\0" + url + "\0" + (model or "")).encode()).hexdigest()[:24]
            result[identity] = {"id": identity, "source_id": spec["id"], "title": _text(row.get("title"), 300),
                "url": url, "provider_id": provider, "model_id": model, "kind": kind,
                "evidence": _text(row.get("evidence"), 800), "expires_at": expires, "state": "active",
                "last_seen_at": observed, "automatic_routing_authorized": False,
                "claim_strategy": "modelscope-daily-visit" if provider == "modelscope" and row.get("claim_strategy") == "modelscope-daily-visit" else "none"}
        return result

    def _checkin(self, manual: bool) -> None:
        today = self.now().astimezone(CHINA_TIME).date().isoformat()
        try:
            browser, revision = self._check_binding()
        except BenefitsError:
            with self._transaction():
                self._state["checkin"].update(state="needs-review", error="provider-binding-changed")
            return
        with self._transaction():
            if self._state["browser_instance_id"] != browser or self._state.get("account_revision") != revision:
                return
            if not manual and (not self._state["enabled"] or not self._state["checkin_enabled"]):
                return
            checked = _instant(self._state["checkin"].get("checked_at"))
            if self._state["checkin"].get("state") == "verified" and checked and checked.astimezone(CHINA_TIME).date().isoformat() == today:
                return
            if not manual and (self._state.get("checkin_attempt_date") == today or self._state["checkin"].get("state") in {"challenge", "login-required", "needs-review", "interrupted", "running"}):
                return
            attempted = _instant(self._state["checkin"].get("attempted_at"))
            if attempted and self.now() < attempted + timedelta(seconds=60):
                return
            cancel_revision = self._state.get("cancel_revision", 0)
            def revoked():
                with self._lock:
                    self._load()
                    return (self._stop.is_set() or self._state.get("cancel_revision", 0) != cancel_revision or
                            self._state["browser_instance_id"] != browser or self._revision() != revision)
            self._checkin_stop = _CheckinCancellation(revoked)
            cancellation = self._checkin_stop
            if self._stop.is_set():
                cancellation.set()
                return
            self._state["checkin_attempt_date"] = today
            self._state["checkin"].update(state="running", error=None, attempted_at=self.now().isoformat())
        try:
            raw = self.browser_reader.read(browser, cancellation)
            if cancellation.is_set():
                raw = {"state": "interrupted", "error": "check-in-cancelled"}
            if raw.get("state") not in CHECKIN_STATES - {"never", "running"}:
                raise BenefitsError("invalid check-in result")
            if self._revision() != revision:
                raw = {"state": "needs-review", "error": "provider-binding-changed"}
            result = {**_empty_checkin(), **raw}
            result["account_binding_verified"] = False
            result["automatic_routing_authorized"] = False
            if result["state"] == "verified":
                if not any(grant.get("kind") == "daily-login" and grant.get("granted_date_display") == today for grant in result["grants"]):
                    result.update(state="needs-review", error="today-grant-not-observed")
            if result["state"] != "verified":
                result.update(available_balance=None, grants=[], checked_at=None)
        except Exception:
            result = {**_empty_checkin(), "state": "interrupted" if self._stop.is_set() else "unavailable", "error": "check-in-unavailable"}
        with self._transaction():
            if self._state.get("account_revision") != revision or self._state["browser_instance_id"] != browser:
                return
            result["attempted_at"] = self._state["checkin"].get("attempted_at")
            self._state["checkin"] = result
            if result["state"] == "verified":
                self._state["last_verified_checkin"] = copy.deepcopy(result)

    def run_once(self, *, kind: str = "all", manual: bool = False) -> None:
        try:
            lease = self._claim_operation()
        except BenefitsError:
            return
        self._run_owned(lease, kind, manual)

    def _claim_operation(self):
        if self._stop.is_set() or self._store_error:
            raise BenefitsError("benefits service is unavailable")
        if not self._operation.acquire(blocking=False):
            raise BenefitsBusy("benefits operation is busy; retry after completion")
        lease = _file_lock(self.root / "run.lock" if self.root else None)
        try:
            lease.__enter__()
        except BaseException:
            self._operation.release()
            raise
        return lease

    def _run_owned(self, lease, kind: str, manual: bool) -> None:
        try:
            if kind in {"refresh", "all"}:
                self._refresh(manual)
            if not self._stop.is_set() and kind in {"checkin", "all"}:
                with self._lock:
                    self._load()
                    enabled = self._state["enabled"] and self._state["checkin_enabled"]
                if manual or enabled:
                    self._checkin(manual)
        except (BenefitsError, OSError):
            pass
        finally:
            lease.__exit__(None, None, None)
            self._operation.release()

    def start(self) -> None:
        if self.root is None or self._worker is not None or self._stop.is_set():
            return
        def work():
            while not self._stop.is_set():
                self.run_once()
                self._wake.wait(60)
                self._wake.clear()
        self._worker = threading.Thread(target=work, name="sumika-benefits-maintenance", daemon=True)
        self._worker.start()

    def close(self) -> None:
        self._stop.set()
        self._checkin_stop.set()
        self._wake.set()
        for thread in (self._thread, self._worker):
            if thread is not None and thread is not threading.current_thread():
                thread.join()
