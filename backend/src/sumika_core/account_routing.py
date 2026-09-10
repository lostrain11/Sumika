from __future__ import annotations

import hashlib
import json
import threading
import re
from copy import copy, deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from quality_routing.costs import FundingLot, RouteQuote, quote_cost

from .funding_ledger import FundingLedger
from .integrations.account_sources import BASE_URLS, public_prices, read_account, trace_fingerprint, validate_moark_receipts
from .provider_profiles import provider_account_revision, provider_execution_revision
from .providers.guard import RequestNotSent
from .providers.openai_compatible import OpenAICompatibleProvider
from .route_pricing import _fresh


SETTINGS_KEY = "model-policy/account-routing/v1"
PORTALS_KEY = "model-policy/account-portals/v1"
PORTAL_STATES_KEY = "model-policy/account-portal-observations/v1"
PORTAL_ENDPOINTS = {"modelscope": "https://api-inference.modelscope.cn/v1", "ollama": "https://ollama.com/v1"}


class AccountRouting:
    def __init__(self, profiles, pricing, data_dir=None, *, native_reader=None, receipt_reader=None):
        self.profiles = profiles
        self.pricing = pricing
        self.storage = getattr(profiles, "storage", None)
        self._data_dir = data_dir
        self._ledger = None
        self._lock = threading.RLock()
        self._active_operations = 0
        self._ledger_closed = False
        self.errors = {}
        self._checked = {}
        self.browser_client = None
        self.native_reader = native_reader
        self.native_required = False
        self.receipt_reader = receipt_reader
        self.receipt_status = {}
        self.closed = threading.Event()
        for profile_id in self.bindings():
            self.pricing.profile_readers[profile_id] = lambda profile, key=profile_id: self.read_prices(key)

    @property
    def ledger(self):
        with self._lock:
            if self._ledger_closed or (self.closed.is_set() and not self._active_operations):
                raise RequestNotSent("account routing closed")
            if self._ledger is None:
                self._ledger = FundingLedger(self._data_dir)
            return self._ledger

    def close(self):
        with self._lock:
            self.closed.set()
            self._close_idle_ledger()

    def _close_idle_ledger(self):
        if self.closed.is_set() and not self._active_operations and not self._ledger_closed:
            if self._ledger is not None:
                self._ledger.close()
            self._ledger_closed = True

    def begin_operation(self):
        with self._lock:
            if self.closed.is_set():
                raise RequestNotSent("account routing closed")
            self._active_operations += 1

    def end_operation(self):
        with self._lock:
            self._active_operations -= 1
            self._close_idle_ledger()

    def bindings(self):
        if self.storage is None:
            return {}
        raw = self.storage.get_meta(SETTINGS_KEY)
        return json.loads(raw or "{}")

    def portal_bindings(self):
        return json.loads(self.storage.get_meta(PORTALS_KEY) or "{}") if self.storage else {}

    def bind_portal(self, profile_id, source, browser_instance_id):
        profile = self.profiles.get(profile_id)
        if source not in PORTAL_ENDPOINTS or profile["config"]["active_base_url"] != PORTAL_ENDPOINTS[source]:
            raise ValueError("exact portal provider required")
        if not isinstance(browser_instance_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", browser_instance_id):
            raise ValueError("selected browser required")
        with self._lock:
            bindings = self.portal_bindings()
            binding = {"source": source, "browser_instance_id": browser_instance_id,
                       "account_revision": provider_account_revision(profile)}
            if bindings.get(profile_id) != binding:
                observations = json.loads(self.storage.get_meta(PORTAL_STATES_KEY) or "{}")
                observations.pop(profile_id, None)
                self.storage.set_meta(PORTAL_STATES_KEY, json.dumps(observations))
            bindings[profile_id] = binding
            self.storage.set_meta(PORTALS_KEY, json.dumps(bindings, sort_keys=True))

    def portal_status(self):
        observations = json.loads(self.storage.get_meta(PORTAL_STATES_KEY) or "{}") if self.storage else {}
        rows = []
        for profile_id, binding in self.portal_bindings().items():
            observation = observations.get(profile_id, {})
            expiry = observation.get("fresh_until")
            state = observation.get("quality", {}).get("state", "never")
            fresh = bool(expiry and datetime.fromisoformat(expiry) > datetime.now(timezone.utc)
                         and state in {"verified", "observed-with-limitations"})
            try:
                current = provider_account_revision(self.profiles.get(profile_id)) == binding["account_revision"]
            except ValueError:
                current = False
            rows.append({**observation, "provider_profile_id": profile_id, "source": binding["source"],
                         "fresh": fresh and current and profile_id not in self.errors, "routable": False,
                         "state": state if current else "binding-changed",
                         "used_percent": observation.get("displayed_free_usage_percent"),
                         "reason": observation.get("quality", {}).get("blocking_reason")})
        return rows

    def bind_receipt_portal(self, profile_id, browser_instance_id):
        binding, profile = self._binding(profile_id)
        if binding["source"] != "moark":
            raise ValueError("no verified exact receipt reader for this source")
        if not isinstance(browser_instance_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", browser_instance_id):
            raise ValueError("selected receipt browser required")
        with self._lock:
            bindings = self.bindings()
            bindings[profile_id]["receipt_browser_instance_id"] = browser_instance_id
            self.storage.set_meta(SETTINGS_KEY, json.dumps(bindings, sort_keys=True))
            self._checked.pop(profile_id, None)

    def refresh_portals(self, *, force=False):
        for profile_id, binding in self.portal_bindings().items():
            if self.closed.is_set():
                return
            if not force and datetime.now(timezone.utc).timestamp() - self._checked.get(profile_id, 0) < 300:
                continue
            try:
                if provider_account_revision(self.profiles.get(profile_id)) != binding["account_revision"]:
                    raise RequestNotSent("portal account binding changed")
                from .integrations.account_portals import AccountPortalReader, _failed
                if self.native_required and binding["browser_instance_id"] != "sumika-native":
                    observation = _failed(binding["source"], "needs-review", "bind-native-browser-and-login-required", datetime.now(timezone.utc))
                elif binding["browser_instance_id"] == "sumika-native":
                    try:
                        from .embedded_browser import fixed_account_read_reason
                        observation = self.native_reader(binding["source"], "sumika-native", self.closed) if callable(self.native_reader) else None
                        quality = observation.get("quality") if isinstance(observation, dict) else None
                        if not isinstance(quality, dict) or quality.get("state") not in {"verified", "observed-with-limitations"}:
                            reason = fixed_account_read_reason(binding["source"], quality.get("blocking_reason")) if isinstance(quality, dict) else None
                            observation = _failed(binding["source"], "needs-review", reason or "native-portal-read-failed", datetime.now(timezone.utc))
                    except Exception:
                        observation = _failed(binding["source"], "needs-review", "native-portal-read-failed", datetime.now(timezone.utc))
                else:
                    if self.browser_client is None:
                        raise RequestNotSent("portal browser unavailable")
                    observation = AccountPortalReader(self.browser_client).read(binding["source"], binding["browser_instance_id"], self.closed)
                with self._lock:
                    if self.portal_bindings().get(profile_id) != binding or provider_account_revision(self.profiles.get(profile_id)) != binding["account_revision"]:
                        raise RequestNotSent("portal account binding changed during read")
                    observations = json.loads(self.storage.get_meta(PORTAL_STATES_KEY) or "{}")
                    previous = observations.get(profile_id)
                    if previous and observation.get("quality", {}).get("state") not in {"verified", "observed-with-limitations"}:
                        observation = {**previous, "quality": observation["quality"],
                                       "last_failure_at": observation["observed_at"]}
                    observations[profile_id] = observation
                    self.storage.set_meta(PORTAL_STATES_KEY, json.dumps(observations, sort_keys=True))
                self.errors.pop(profile_id, None)
            except Exception as error:
                self.errors[profile_id] = type(error).__name__
            self._checked[profile_id] = datetime.now(timezone.utc).timestamp()

    def bind(self, profile_id, source, model_ids, *, funding_kind=None, unit_value_cny=None, evidence=None, package_fingerprints=None):
        profile = self.profiles.get(profile_id)
        if source not in BASE_URLS or profile["config"]["active_base_url"] != BASE_URLS[source]:
            raise ValueError("exact official endpoint required")
        if not model_ids or not set(model_ids) <= {row["id"] for row in profile["config"]["models"]}:
            raise ValueError("registered model IDs required")
        if source == "moark" and (funding_kind not in {"grant", "purchased", "unknown"} or not evidence):
            raise ValueError("resource provenance evidence required")
        if evidence is not None and (not isinstance(evidence, str) or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,200}", evidence)):
            raise ValueError("metadata-only evidence identifier required")
        if unit_value_cny is not None:
            if funding_kind != "purchased" or not Decimal(str(unit_value_cny)).is_finite() or Decimal(str(unit_value_cny)) <= 0:
                raise ValueError("positive purchased unit value required")
            unit_value_cny = str(unit_value_cny)
        if source == "moark" and (not package_fingerprints or any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in package_fingerprints)):
            raise ValueError("verified package identities required")
        value = {"source": source, "models": sorted(set(model_ids)), "account_revision": provider_account_revision(profile),
                 "funding_kind": funding_kind, "unit_value_cny": unit_value_cny, "evidence": evidence,
                 "package_fingerprints": sorted(set(package_fingerprints or []))}
        with self._lock:
            bindings = self.bindings()
            previous = bindings.get(profile_id)
            changed_funding = previous and any(previous.get(key) != value.get(key) for key in
                ("account_revision", "funding_kind", "unit_value_cny", "package_fingerprints"))
            if changed_funding and any(row["provider"] == profile_id and row["state"] != "released" and not row["absorbed"]
                                       for row in self.ledger.status()["reservations"]):
                raise ValueError("reconcile existing reservations before rebinding funding")
            bindings[profile_id] = value
            self.storage.set_meta(SETTINGS_KEY, json.dumps(bindings, sort_keys=True))
            self.pricing.profile_readers[profile_id] = lambda profile: self.read_prices(profile_id)

    def manages(self, profile_id, model_id):
        binding = self.bindings().get(profile_id)
        return bool(binding and model_id in binding["models"])

    def _binding(self, profile_id):
        binding = self.bindings().get(profile_id)
        profile = self.profiles.get(profile_id)
        if (not binding or profile.get("archived_at") or profile["config"]["active_base_url"] != BASE_URLS[binding["source"]]
                or provider_account_revision(profile) != binding["account_revision"]):
            raise RequestNotSent("account binding changed")
        return binding, profile

    def read_prices(self, profile_id):
        binding, profile = self._binding(profile_id)
        snapshots, versions = public_prices(binding["source"], profile_id)
        identities = json.loads(self.storage.get_meta("model-policy/evaluated-model-identities/v1") or "{}")
        for row in profile["config"]["models"]:
            identity = identities.get("profile:" + profile_id + ":" + row["id"], {})
            evaluated = identity.get("model_version") if identity.get("execution_revision") == provider_execution_revision(profile, row["id"]) else None
            version = row.get("version") or evaluated
            if row["id"] in binding["models"] and version and versions.get(row["id"]) not in {None, version}:
                raise RequestNotSent("official model version changed; evaluation required")
        return [row for row in snapshots if row.model_id in binding["models"]]

    def refresh(self, *, force=False):
        for profile_id in self.bindings():
            if self.closed.is_set():
                return
            if not force and (datetime.now(timezone.utc).timestamp() - self._checked.get(profile_id, 0)) < 300:
                continue
            try:
                self.refresh_account(profile_id)
                self.errors.pop(profile_id, None)
            except Exception as error:
                self.errors[profile_id] = type(error).__name__
            self._checked[profile_id] = datetime.now(timezone.utc).timestamp()
        self.refresh_portals(force=force)

    def refresh_account(self, profile_id):
        self.begin_operation()
        try:
            return self._refresh_account(profile_id)
        finally:
            self.end_operation()

    def _refresh_account(self, profile_id):
        binding, profile = self._binding(profile_id)
        included = []
        browser = binding.get("receipt_browser_instance_id")
        if browser:
            try:
                if self.native_required and browser != "sumika-native":
                    raise ValueError("bind-native-browser-and-login-required")
                if callable(self.receipt_reader):
                    evidence = self.receipt_reader(binding["source"], browser, self.closed)
                elif browser == "sumika-native" or self.browser_client is None:
                    raise ValueError("selected receipt reader unavailable")
                else:
                    from .integrations.account_portals import AccountPortalReader
                    evidence = AccountPortalReader(self.browser_client).read_receipts(binding["source"], browser, self.closed)
                if isinstance(evidence, dict) and evidence.get("state") != "verified":
                    from .embedded_browser import fixed_account_read_reason
                    self.receipt_status[profile_id] = {"state": "needs-review",
                        "reason": fixed_account_read_reason(binding["source"], evidence.get("reason")) or "official-receipts-unavailable"}
                else:
                    included = self._reconcile_receipts(profile_id, binding, evidence)
            except Exception:
                self.receipt_status[profile_id] = {"state": "needs-review", "reason": "official-receipts-unavailable"}
        return self._observe_account(profile_id, binding, included)

    def reconcile_receipts(self, profile_id, evidence):
        """Reconcile exact trace-matched receipts, then read a causally newer balance."""
        self.begin_operation()
        try:
            binding, profile = self._binding(profile_id)
            included = self._reconcile_receipts(profile_id, binding, evidence)
            self._observe_account(profile_id, binding, included)
            return dict(self.receipt_status[profile_id])
        finally:
            self.end_operation()

    def _reconcile_receipts(self, profile_id, binding, evidence):
        if binding["source"] != "moark":
            raise ValueError("exact receipt adapter unavailable")
        receipts = validate_moark_receipts(evidence)
        matched, unmatched = [], 0
        for receipt in receipts:
            rows = self.ledger.match_request_trace(profile_id, binding["account_revision"], receipt["trace_fingerprint"], receipt["model_id"])
            if not rows:
                unmatched += 1
                continue
            if (receipt["package_fingerprint"] not in binding["package_fingerprints"] or len(rows) != 1
                    or rows[0]["pocket_id"] != "package" or rows[0]["source"] != binding["funding_kind"] or rows[0]["unit"] != "CNY"):
                raise ValueError("receipt funding pocket mismatch")
            matched.append((rows[0]["request_id"], receipt))
        included = []
        for request_id, receipt in matched:
            self.ledger.reconcile_receipt(request_id, receipt["amount"], "moark-" + receipt["evidence_id"])
            included.append(request_id)
        self.receipt_status[profile_id] = {"state": "verified", "matched": len(matched), "unmatched": unmatched,
                                          "reason": "unmatched-traces-not-guessed" if unmatched else None}
        return included

    def _observe_account(self, profile_id, binding, included):
        runtime = self.profiles.runtime(profile_id, model_id=binding["models"][0])
        while hasattr(runtime, "provider"):
            runtime = runtime.provider
        account = read_account(binding["source"], runtime)
        if binding["source"] == "deepseek" and not account["available"]:
            raise RequestNotSent("account unavailable")
        if binding["source"] == "moark" and sorted(account["package_fingerprints"]) != binding["package_fingerprints"]:
            raise RequestNotSent("resource package provenance changed")
        current, profile = self._binding(profile_id)
        if current != binding:
            raise RequestNotSent("account binding changed during read")
        now = datetime.now(timezone.utc)
        shared = {"provider": profile_id, "account_revision": binding["account_revision"], "unit": "CNY",
                  "observed_at": now.isoformat(), "expires_at": (now + timedelta(minutes=15)).isoformat()}
        if binding["source"] == "deepseek":
            for source in ("grant", "cash"):
                self.ledger.observe({**shared, "source": source, "pocket_id": source, "balance": account[source]})
        else:
            self.ledger.observe({**shared, "source": binding["funding_kind"], "pocket_id": "package", "balance": account["balance"],
                                 "unit_value_cny": binding.get("unit_value_cny"), "included_request_ids": included})
        return account

    def _pockets(self, profile_id):
        binding, profile = self._binding(profile_id)
        sources = {"grant", "cash"} if binding["source"] == "deepseek" else {binding["funding_kind"]}
        return [row for row in self.ledger.status()["projections"] if row["provider"] == profile_id
                and row["account_revision"] == binding["account_revision"] and row["source"] in sources]

    def price_snapshot(self, entry):
        snapshots = [snapshot for snapshot in self.pricing.store.list(
            provider_profile_id=entry["provider_profile_id"], model_id=entry["model_id"])
            if snapshot.billing_group == "official" and _fresh(snapshot.expires_at)]
        if len(snapshots) != 1:
            raise RequestNotSent("unique fresh official price required")
        return deepcopy(snapshots[0])

    @staticmethod
    def priced_usage(snapshot, input_tokens, output_tokens, cached_tokens=0):
        if any(type(value) is not int or value < 0 for value in (input_tokens, output_tokens, cached_tokens)) or cached_tokens > input_tokens:
            raise ValueError("invalid usage")
        charge = snapshot.estimate_charge(input_tokens=input_tokens - cached_tokens, output_tokens=output_tokens,
            cache_read_tokens=cached_tokens, context_tokens=input_tokens)
        if charge.get("cash_currency") != "CNY" or charge.get("cash_amount") is None:
            raise ValueError("known cash conversion required")
        return quote_cost(input_tokens=input_tokens, output_tokens=output_tokens,
            cash_price_cny=Decimal(str(charge["cash_amount"])), provider_charge=Decimal(str(charge["amount"])),
            provider_currency=charge["currency"])

    def quote(self, entry, input_tokens, output_tokens, cached_tokens=0, *, snapshot=None):
        profile_id = entry["provider_profile_id"]
        try:
            binding, profile = self._binding(profile_id)
            pockets = self._pockets(profile_id)
        except RequestNotSent:
            return RouteQuote(available=False, reason="account-binding-changed")
        try:
            snapshot = snapshot or self.price_snapshot(entry)
            priced = self.priced_usage(snapshot, input_tokens, output_tokens, cached_tokens)
        except (RequestNotSent, ValueError):
            return RouteQuote(available=False, reason="fresh-account-price-required")
        if priced.cash_due_cny is None:
            return RouteQuote(available=False, reason="fresh-account-price-required")
        if profile_id in self.errors or profile_id in self.pricing.errors:
            return RouteQuote(available=False, reason="account-refresh-failed")
        if not pockets or any(not row["fresh"] for row in pockets):
            return RouteQuote(available=False, reason="fresh-account-balance-required")
        if priced.cash_due_cny == 0:
            return priced
        balance = sum((row["available"] for row in pockets if row["source"] == "cash"), Decimal(0))
        lots = tuple(FundingLot(row["pocket_id"], row["source"], row["available"], "CNY",
            min(row["expires_at"], row["entitlement_expires_at"] or row["expires_at"]).timestamp(), row["unit_value_cny"])
            for row in pockets if row["source"] != "cash")
        return quote_cost(input_tokens=input_tokens, output_tokens=output_tokens, cash_price_cny=priced.cash_due_cny,
            provider_charge=priced.provider_charge, provider_currency=priced.provider_currency,
            lots=lots, funding_required=binding["source"] == "moark", cash_balance_cny=balance)

    def signature(self, profile_id):
        return hashlib.sha256(json.dumps(self.bindings().get(profile_id), sort_keys=True).encode()).hexdigest()

    def status(self):
        def encode(value):
            if isinstance(value, (Decimal, datetime)):
                return str(value)
            if isinstance(value, list):
                return [encode(row) for row in value]
            if isinstance(value, dict):
                return {key: encode(item) for key, item in value.items()}
            return value
        return encode({"bindings": self.bindings(), "funding": self.ledger.status() if self.bindings() else {"projections": [], "reservations": []},
                       "portals": self.portal_status(), "receipts": self.receipt_status, "errors": self.errors})

    def wrap(self, runtime, profile_id, model_id):
        return AccountBoundProvider(runtime, self, profile_id, model_id)


class AccountBoundProvider:
    def __init__(self, provider, accounts, profile_id, model_id):
        if isinstance(provider, OpenAICompatibleProvider):
            provider = copy(provider)
        self.provider, self.accounts, self.profile_id, self.model_id = provider, accounts, profile_id, model_id
        self.revision = provider_execution_revision(accounts.profiles.get(profile_id), model_id)
        self.last_charge_receipt = None
        self._trace_fingerprint = None
        self._stream_lock = threading.Lock()
        if isinstance(provider, OpenAICompatibleProvider):
            open_request = provider._open
            source = accounts.bindings().get(profile_id, {}).get("source")
            header = {"moark": "X-Trace-Id", "deepseek": "x-ds-trace-id"}.get(source)
            def observed_open(request):
                response = open_request(request)
                try:
                    trace = response.headers.get(header) if header else None
                    if trace:
                        self._trace_fingerprint = trace_fingerprint(trace)
                except ValueError:
                    self.accounts.receipt_status[self.profile_id] = {"state": "needs-review", "reason": "invalid-response-trace"}
                return response
            provider._open = observed_open

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def stream(self, request):
        if not self._stream_lock.acquire(blocking=False):
            raise RequestNotSent("account provider already has an active stream")
        try:
            self.accounts.begin_operation()
            try:
                yield from self._stream(request)
            finally:
                self.accounts.end_operation()
        finally:
            self._stream_lock.release()

    def _stream(self, request):
        self.last_charge_receipt = None
        self._trace_fingerprint = None
        ledger = self.accounts.ledger
        attempt = "account-" + uuid4().hex
        reservations = []
        try:
            binding, profile = self.accounts._binding(self.profile_id)
            if self.revision != provider_execution_revision(profile, self.model_id):
                raise RequestNotSent("provider execution changed")
            self.accounts.refresh()
            if type(request.max_tokens) is not int or not 0 < request.max_tokens <= 1000000:
                raise RequestNotSent("bounded output required")
            if any(not isinstance(message.content, str) for message in request.messages):
                raise RequestNotSent("account routing requires text requests")
            payload = {"messages": [row.wire_dict() if hasattr(row, "wire_dict") else {"role": row.role, "content": row.content} for row in request.messages], "tools": request.tools}
            input_bound = len(json.dumps(payload, ensure_ascii=False).encode()) + 1024
            entry = {"provider_profile_id": self.profile_id, "model_id": self.model_id, "metadata": {"billing_group": "official"}}
            snapshot = self.accounts.price_snapshot(entry)
            forecast = self.accounts.quote(entry, input_bound, request.max_tokens, snapshot=snapshot)
            if not forecast.available or forecast.effective_cost_cny is None:
                raise RequestNotSent("account quote unavailable")
            deadline = (datetime.now(timezone.utc) + timedelta(seconds=max(90, float(self.provider.timeout) + 20))).isoformat()
            allocations = [{"provider": self.profile_id, "account_revision": binding["account_revision"],
                "amount": allocation.quantity, "unit": allocation.unit, "source": allocation.kind, "pocket_id": allocation.lot_id}
                for allocation in forecast.allocations if allocation.quantity > 0]
            if forecast.cash_due_cny:
                allocations.append({"provider": self.profile_id, "account_revision": binding["account_revision"],
                    "amount": forecast.cash_due_cny, "unit": "CNY", "source": "cash", "pocket_id": "cash"})
            if allocations:
                reservations = ledger.reserve_bundle(attempt, allocations, valid_until=deadline)["allocations"]
        except Exception:
            for row in reservations:
                ledger.settle(row["request_id"], request_not_sent=True)
            raise RequestNotSent("funding preflight failed") from None
        complete = False
        definitely_not_sent = False
        response_started = False
        stream = None
        try:
            if self.accounts.closed.is_set():
                raise RequestNotSent("account routing closed before send")
            stream = iter(self.provider.stream(request))
            for chunk in stream:
                response_started = True
                yield chunk
            complete = True
        except RequestNotSent:
            definitely_not_sent = not response_started
            raise
        finally:
            try:
                if stream is not None and callable(getattr(stream, "close", None)):
                    stream.close()
            except Exception:
                complete = False
                self.accounts.errors[self.profile_id] = "stream-close-failed"
            finally:
                if reservations and self._trace_fingerprint and not definitely_not_sent:
                    try:
                        ledger.record_request_trace(attempt, self._trace_fingerprint, self.model_id)
                    except Exception:
                        self.accounts.receipt_status[self.profile_id] = {"state": "needs-review", "reason": "request-trace-recording-failed"}
                estimate = None
                try:
                    usage = self.provider.last_usage if complete else {}
                    if (type(usage.get("input_tokens")) is int and type(usage.get("output_tokens")) is int
                            and usage["input_tokens"] + usage["output_tokens"] > 0):
                        estimate = self.accounts.priced_usage(snapshot, usage["input_tokens"], usage["output_tokens"],
                                                             usage.get("cache_read_tokens", 0)).cash_due_cny
                except Exception:
                    self.accounts.errors[self.profile_id] = "usage-estimate-unavailable"
                remaining = estimate
                for index, row in enumerate(reservations):
                    estimated = min(remaining, row["amount"]) if remaining is not None else None
                    if index == len(reservations) - 1 and remaining is not None:
                        estimated = remaining
                    try:
                        ledger.settle(row["request_id"], estimated=None if definitely_not_sent else estimated,
                                      request_not_sent=definitely_not_sent)
                    except Exception:
                        self.accounts.errors[self.profile_id] = "settlement-failed"
                    if remaining is not None:
                        remaining -= estimated
                self.last_charge_receipt = {"request_id": attempt, "source": "usage-priced-upper-bound", "pricing_ref": snapshot.pricing_ref,
                    "pricing_source_version": snapshot.source_version, "estimated_provider_cny": str(estimate) if estimate is not None else None,
                    "actual_cash_cny": None, "reservation_ids": [row["request_id"] for row in reservations], "complete": complete}
