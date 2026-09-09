"""Opt-in free routes with account-bound evidence and a send-time guard."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.error import HTTPError
from uuid import uuid4

from .provider_profiles import configured_models, provider_account_revision, provider_execution_revision
from .providers.guard import RequestNotSent


SCHEMA = "free-model-routing/v1"
SUITE = "bounded-text-v1"
QUALITY_TTL = 7 * 86400
HEALTH_TTL = 86400
TASK_KINDS = {"chat", "greeting", "classification", "extraction", "transform", "summarize"}


class FreeModelRouting:
    def __init__(self, profiles, data_dir=None, *, collector=None, clock=time.time):
        self.profiles = profiles
        self.clock = clock
        self.collector = collector
        self._lock = threading.RLock()
        self._closed = False
        path = ":memory:" if data_dir is None else str(Path(data_dir) / "free-model-routing.sqlite3")
        if data_dir is not None:
            Path(data_dir).mkdir(parents=True, exist_ok=True)
        self._path = path
        self._db = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS records (profile_id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._db.commit()
        if path != ":memory:":
            self._db.close()
            self._db = None

    @contextmanager
    def _transaction(self):
        with self._lock:
            if self._closed:
                raise RequestNotSent("free routing host closed")
            if self._path != ":memory:":
                self._db = sqlite3.connect(self._path, timeout=10, check_same_thread=False)
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise
            finally:
                if self._path != ":memory:":
                    self._db.close()
                    self._db = None

    def _read(self, profile_id):
        row = self._db.execute("SELECT value FROM records WHERE profile_id=?", (profile_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _write(self, profile_id, row):
        self._db.execute("INSERT OR REPLACE INTO records VALUES (?, ?)",
                         (profile_id, json.dumps(row, allow_nan=False, sort_keys=True)))

    def enroll(self, profile_id, provider_id, *, free_key_confirmed=False, entitlement_expires_at=None):
        from .integrations.free_model_sources import PROVIDER_ENDPOINTS
        profile = self.profiles.get(profile_id)
        if provider_id not in PROVIDER_ENDPOINTS or not self._endpoint_matches(profile, PROVIDER_ENDPOINTS[provider_id]):
            raise ValueError("free source requires its exact official endpoint")
        if not profile.get("has_secrets") or profile.get("archived_at"):
            raise ValueError("active authenticated profile required")
        if set(profile.get("secret_fields") or []) - {"api_key"}:
            raise ValueError("free route does not support additional secret headers")
        if type(free_key_confirmed) is not bool:
            raise ValueError("free key confirmation must be boolean")
        if entitlement_expires_at is not None:
            expiration = datetime.fromisoformat(entitlement_expires_at)
            if expiration.tzinfo is None or expiration.timestamp() <= self.clock():
                raise ValueError("future account entitlement expiry required")
        revision = provider_account_revision(profile)
        with self._transaction():
            previous = self._read(profile_id)
            if previous and previous["revision"] == revision and previous["provider_id"] == provider_id:
                return
            self._write(profile_id, {"provider_id": provider_id, "revision": revision,
                "free_key_confirmed": free_key_confirmed, "snapshot": None,
                "entitlement_expires_at": entitlement_expires_at,
                "state": "pending-refresh", "next_refresh": 0, "models": {}, "busy_until": 0})

    @staticmethod
    def _endpoint_matches(profile, endpoint):
        config = profile.get("config") or {}
        headers = {"X-Failover-Enabled": "false"} if endpoint == "https://api.moark.com/v1" else {}
        return (str(config.get("active_base_url") or "").rstrip("/") == endpoint.rstrip("/")
                and (config.get("headers") or {}) == headers and not config.get("organization") and not config.get("project"))

    def _binding_matches(self, profile, row):
        from .integrations.free_model_sources import PROVIDER_ENDPOINTS
        return (not profile.get("archived_at") and profile.get("has_secrets") is True
                and provider_account_revision(profile) == row["revision"]
                and self._endpoint_matches(profile, PROVIDER_ENDPOINTS[row["provider_id"]]))

    def manages(self, profile_id):
        with self._transaction():
            return self._read(profile_id) is not None

    def refresh(self, profile_id=None, *, force=False):
        from .integrations.free_model_sources import fetch_free_models
        with self._transaction():
            identifiers = [profile_id] if profile_id else [row[0] for row in self._db.execute("SELECT profile_id FROM records")]
        for current_id in identifiers:
            with self._transaction():
                row = self._read(current_id)
                if row is None or (not force and self.clock() < row["next_refresh"]):
                    continue
                if row.get("refresh_until", 0) > self.clock():
                    continue
                row["refresh_until"] = self.clock() + 180
                row["refresh_id"] = uuid4().hex
                row["next_refresh"] = self.clock() + 900
                self._write(current_id, row)
            try:
                profile = self.profiles.get(current_id)
                if not self._binding_matches(profile, row):
                    raise ValueError("account-binding-changed")
                snapshot = (self.collector or fetch_free_models)(row["provider_id"])
                observed = datetime.fromisoformat(snapshot["observed_at"])
                if observed.tzinfo is None:
                    raise ValueError("source timestamp requires timezone")
                stamp = observed.timestamp()
                models = snapshot["models"]
                if (snapshot["provider_id"] != row["provider_id"] or snapshot["mode"] not in {"zero-price", "free-key", "allowance"}
                        or type(snapshot["complete"]) is not bool or type(snapshot["ttl_seconds"]) is not int
                        or not 0 < snapshot["ttl_seconds"] <= 43200 or not isinstance(models, list)
                        or len(models) > 4096 or any(not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,240}", model) for model in models)
                        or len(set(models)) != len(models) or not math.isfinite(stamp)
                        or not stamp <= self.clock() < stamp + snapshot["ttl_seconds"]):
                    raise ValueError("invalid source evidence")
                with self._transaction():
                    current = self._read(current_id)
                    if current["revision"] != row["revision"] or current.get("refresh_id") != row["refresh_id"] or not self._binding_matches(self.profiles.get(current_id), current):
                        raise ValueError("account-binding-changed")
                    current.update(snapshot={key: snapshot[key] for key in ("provider_id", "source_url", "observed_at", "models", "complete", "mode", "ttl_seconds")},
                                   state="ready", next_refresh=stamp + snapshot["ttl_seconds"], refresh_until=0)
                    self._write(current_id, current)
            except Exception as error:
                with self._transaction():
                    current = self._read(current_id)
                    if current["revision"] != row["revision"] or current.get("refresh_id") != row["refresh_id"]:
                        continue
                    current.update(state="needs-review", failure_class=type(error).__name__, refresh_until=0)
                    self._write(current_id, current)
        return self.status()

    def projection(self, profile_id, model_id, *, evaluation=False):
        with self._transaction():
            row = self._read(profile_id)
        if row is None:
            return None
        return self._project(self.profiles.get(profile_id), row, model_id, evaluation=evaluation)

    def _project(self, profile, row, model_id, *, evaluation=False):
        result = {"managed": True, "routable": False, "reason": "refresh-required", "zero_cash": False,
                  "remaining": None, "quota_basis": "recent-authenticated-request", "suite": SUITE}
        if not self._binding_matches(profile, row):
            return {**result, "reason": "account-binding-changed"}
        if row.get("entitlement_expires_at") and self.clock() >= datetime.fromisoformat(row["entitlement_expires_at"]).timestamp():
            return {**result, "reason": "account-entitlement-expired"}
        configured = next((item for item in configured_models(profile.get("config")) if item["id"] == model_id), None)
        if not configured or not configured.get("enabled", True):
            return {**result, "reason": "model-disabled"}
        snapshot = row.get("snapshot")
        if not snapshot or row["state"] != "ready":
            return result
        expires = datetime.fromisoformat(snapshot["observed_at"]).timestamp() + snapshot["ttl_seconds"]
        result.update(source_url=snapshot["source_url"], observed_at=snapshot["observed_at"], expires_at=expires)
        if self.clock() >= expires:
            return {**result, "reason": "price-stale"}
        if snapshot["mode"] == "allowance":
            return {**result, "reason": "account-allowance-binding-required"}
        if model_id not in snapshot["models"]:
            return {**result, "reason": "free-evidence-withdrawn" if snapshot["complete"] else "free-evidence-missing"}
        if snapshot["mode"] == "free-key" and not row["free_key_confirmed"]:
            return {**result, "reason": "free-key-confirmation-required"}
        result["zero_cash"] = True
        evidence = row["models"].get(model_id, {})
        if evidence.get("cooldown_until", 0) > self.clock():
            return {**result, "reason": evidence.get("failure_class", "cooldown"), "retry_at": evidence["cooldown_until"]}
        if evidence.get("blocked"):
            return {**result, "reason": evidence["blocked"]}
        if not evaluation:
            if profile.get("status") != "available":
                return {**result, "reason": "profile-unavailable"}
            if evidence.get("execution_revision") != provider_execution_revision(profile, model_id):
                return {**result, "reason": "execution-binding-changed"}
            if evidence.get("suite") != SUITE or self.clock() >= evidence.get("quality_until", 0):
                return {**result, "reason": "fixed-evaluation-required"}
            if self.clock() >= evidence.get("healthy_until", 0):
                return {**result, "reason": "authenticated-health-expired"}
        return {**result, "routable": True, "reason": "qualified-bounded-text", "quality_until": evidence.get("quality_until")}

    def record_evaluation(self, profile_id, model_id, *, passed, revision):
        if type(passed) is not bool:
            raise ValueError("evaluation result must be boolean")
        with self._transaction():
            row = self._read(profile_id)
            if row is None or row["revision"] != revision or not self._binding_matches(self.profiles.get(profile_id), row):
                raise ValueError("evaluation account changed")
            previous = row["models"].get(model_id, {})
            row["models"][model_id] = {**previous, "suite": SUITE, "quality_until": self.clock() + QUALITY_TTL if passed else 0,
                "execution_revision": provider_execution_revision(self.profiles.get(profile_id), model_id),
                "healthy_until": self.clock() + HEALTH_TTL if passed else 0}
            self._write(profile_id, row)

    def feedback(self, profile_id, model_id, *, successful=False, status=None, uncertain=False, revision=None, lease=None):
        with self._transaction():
            row = self._read(profile_id)
            if (revision is not None and row["revision"] != revision) or (lease is not None and row.get("busy_id") != lease):
                return
            evidence = row["models"].setdefault(model_id, {})
            if successful:
                evidence["healthy_until"] = self.clock() + HEALTH_TTL
            elif status in {401, 402, 403}:
                evidence.update(blocked="account-entitlement-required", healthy_until=0)
            elif status in {404, 410}:
                evidence.update(blocked="model-unavailable", healthy_until=0)
            else:
                evidence.update(cooldown_until=self.clock() + (900 if status == 429 else 300),
                                failure_class="rate-limited" if status == 429 else "submission-uncertain" if uncertain else "invalid-response")
            self._write(profile_id, row)

    def acquire(self, profile_id, model_id, request, *, evaluation=False, revision=None, execution_revision=None):
        self.refresh(profile_id)
        if (request.tools or request.reasoning_effort is not None or type(request.max_tokens) is not int
                or not 0 < request.max_tokens <= 2048 or any(not isinstance(message.content, str) for message in request.messages)
                or sum(len(message.content.encode("utf-8")) for message in request.messages) > 16000):
            raise RequestNotSent("free route requires bounded text and verified reasoning settings")
        result = self.projection(profile_id, model_id, evaluation=evaluation)
        if not result or not result["routable"]:
            raise RequestNotSent("free route blocked: " + (result or {}).get("reason", "not-enrolled"))
        with self._transaction():
            row = self._read(profile_id)
            if revision is not None and row["revision"] != revision:
                raise RequestNotSent("free route account changed")
            profile = self.profiles.get(profile_id)
            if not self._binding_matches(profile, row):
                raise RequestNotSent("free route account changed")
            if execution_revision is not None and execution_revision != provider_execution_revision(profile, model_id):
                raise RequestNotSent("free route execution changed")
            current_projection = self._project(profile, row, model_id, evaluation=evaluation)
            if not current_projection["routable"]:
                raise RequestNotSent("free evidence changed: " + current_projection["reason"])
            snapshot = row.get("snapshot") or {}
            if row["state"] != "ready" or snapshot.get("observed_at") != result.get("observed_at"):
                raise RequestNotSent("free price evidence changed before submission")
            evidence = row["models"].get(model_id, {})
            if evidence.get("blocked") or evidence.get("cooldown_until", 0) > self.clock():
                raise RequestNotSent("free route state changed before submission")
            if row.get("busy_until", 0) > self.clock():
                raise RequestNotSent("free account busy or cooling down")
            row["busy_until"] = self.clock() + 360
            row["busy_id"] = uuid4().hex
            self._write(profile_id, row)
            return row["busy_id"]

    def release(self, profile_id, *, revision=None, lease=None):
        with self._transaction():
            row = self._read(profile_id)
            if (revision is not None and row["revision"] != revision) or (lease is not None and row.get("busy_id") != lease):
                return
            row["busy_until"] = self.clock() + 4
            self._write(profile_id, row)

    def status(self):
        with self._transaction():
            rows = [(profile_id, json.loads(value)) for profile_id, value in self._db.execute("SELECT profile_id, value FROM records")]
        return {"schema": SCHEMA, "refresh_model_calls": 0, "profiles": [
            {"provider_profile_id": profile_id, "provider_id": row["provider_id"], "state": row["state"],
             "next_refresh": row["next_refresh"], "source": row.get("snapshot"),
             "entitlement_expires_at": row.get("entitlement_expires_at"),
             "models": [{"model_id": model["id"], **self.projection(profile_id, model["id"])}
                        for model in configured_models(self.profiles.get(profile_id).get("config"))]}
            for profile_id, row in rows]}

    def wrap(self, provider, profile_id, model_id, *, evaluation=False):
        if not self.manages(profile_id):
            return provider
        return FreeModelProvider(provider, self, profile_id, model_id, evaluation=evaluation)

    def close(self):
        with self._lock:
            self._closed = True
            if self._db is not None:
                self._db.close()
                self._db = None

    def __del__(self):
        if getattr(self, "_db", None) is not None:
            self._db.close()


class FreeModelProvider:
    def __init__(self, provider, manager, profile_id, model_id, *, evaluation=False):
        self.provider, self.manager = provider, manager
        self.provider.disallow_redirects = True
        self.profile_id, self.model_id, self.evaluation = profile_id, model_id, evaluation
        profile = manager.profiles.get(profile_id)
        self.revision = provider_account_revision(profile)
        self.execution_revision = provider_execution_revision(profile, model_id)

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def health_check(self, *, allow_chat_probe=False):
        result = self.manager.projection(self.profile_id, self.model_id)
        return {"ok": bool(result and result["routable"]), "status": "available" if result and result["routable"] else "unavailable",
                "health_evidence": "account-bound-fixed-evaluation", "model": self.model_id,
                "chat_probe_blocked": True, "reason": (result or {}).get("reason")}

    def stream(self, request):
        if self.execution_revision != provider_execution_revision(self.manager.profiles.get(self.profile_id), self.model_id):
            raise RequestNotSent("free runtime binding changed")
        lease = self.manager.acquire(self.profile_id, self.model_id, request, evaluation=self.evaluation,
                                     revision=self.revision, execution_revision=self.execution_revision)
        completed = False
        failure_recorded = False
        stream = None
        try:
            stream = iter(self.provider.stream(request))
            size = 0
            for piece in stream:
                size += len(piece)
                if size > 32000:
                    raise ValueError("free response limit exceeded")
                yield piece
            identity_matches = getattr(self.provider, "last_response_model", None) == self.model_id
            if getattr(self.provider, "base_url", None) == "https://api.moark.com/v1":
                identity_matches = self.provider.response_model_matches(getattr(self.provider, "last_response_model", None))
            if (self.model_id == "lite" and getattr(self.provider, "base_url", None) == "https://spark-api-open.xf-yun.com/v1"
                    and getattr(self.provider, "last_response_model", None) is None
                    and getattr(self.provider, "last_model_identity_basis", None) == "spark-lite-request-and-completion"):
                identity_matches = True
            completed = bool(size and getattr(self.provider, "last_finish_reason", None) == "stop" and identity_matches
                             and not getattr(self.provider, "last_response_model_mismatch", False))
            if not completed:
                raise ValueError("incomplete free response")
            self.manager.feedback(self.profile_id, self.model_id, successful=True, revision=self.revision, lease=lease)
        except RequestNotSent:
            failure_recorded = True
            raise
        except Exception as error:
            cause = error.__cause__
            status = error.code if isinstance(error, HTTPError) else cause.code if isinstance(cause, HTTPError) else None
            if isinstance(error, HTTPError):
                error.close()
            self.manager.feedback(self.profile_id, self.model_id, status=status, uncertain=status is None,
                                  revision=self.revision, lease=lease)
            failure_recorded = True
            raise RuntimeError("free provider failed: " + ("HTTP " + str(status) if status else "response-unconfirmed")) from None
        finally:
            try:
                if stream is not None and callable(getattr(stream, "close", None)):
                    stream.close()
            finally:
                if not completed and not failure_recorded:
                    self.manager.feedback(self.profile_id, self.model_id, uncertain=True, revision=self.revision, lease=lease)
                self.manager.release(self.profile_id, revision=self.revision, lease=lease)
