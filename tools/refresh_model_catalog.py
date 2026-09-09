"""Zero-AI refresh client and explicit offline observation importer.

Scheduled use: --all --noninteractive --core-url http://127.0.0.1:<port>.
Only an already-running, identity-checked Core may fetch upstream or write live
state. Offline imports require --data-dir and --resource-file/--model-file;
timestamps must come from the input. --dry-run never writes or uses the network.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import http.client
import ipaddress
import json
import math
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sumika_core import __version__
from sumika_core.integrations.zhipu_pricing import ALLOWED_PRICING_URLS, NoRedirect, read_bounded
from sumika_core.model_refresh import RefreshCoordinator

MAX_JSON_BYTES = 2_000_000


def _read_json(path: Path) -> object:
    if str(path).startswith(("\\\\", "//")) or not path.is_file():
        raise ValueError("observation input must be a local regular file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("observation file exceeds the byte limit")
    return json.loads(raw.decode("utf-8-sig"))


def validate_core_url(value: str) -> str:
    if not value or any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise ValueError("an explicit loopback Core URL is required")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or "?" in value or "#" in value or parsed.path not in {"", "/"}
            or parsed.port is None or parsed.port == 0):
        raise ValueError("Core URL must be a loopback origin with an explicit port and no credentials")
    host = parsed.hostname
    if host == "localhost":
        host = "127.0.0.1"
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        raise ValueError("Core URL must use localhost or a literal loopback address") from None
    if not address.is_loopback or "%" in str(address):
        raise ValueError("Core URL must be loopback")
    host = f"[{address}]" if address.version == 6 else str(address)
    return f"{parsed.scheme}://{host}:{parsed.port}"


class CoreClient:
    def __init__(self, url: str) -> None:
        self.url = validate_core_url(url) + "/rpc"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.request_id = 0

    def rpc(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.request_id += 1
        payload = {"jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params}
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), headers={
            "Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity",
        }, method="POST")
        timeout = 3 if method == "core.health" else 45
        try:
            with self.opener.open(request, timeout=timeout) as response:
                if response.status != 200 or response.geturl() != self.url:
                    raise ValueError("unexpected Core response")
                if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Core did not return JSON")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("encoded Core response is unsupported")
                result = json.loads(read_bounded(response, MAX_JSON_BYTES, timeout))
        except urllib.error.HTTPError as error:
            error.close()
            raise ValueError("Core RPC rejected; no fallback was attempted") from None
        except (OSError, ValueError, http.client.HTTPException):
            raise ValueError("Core unavailable or invalid; no fallback was attempted") from None
        if (not isinstance(result, dict) or result.get("jsonrpc") != "2.0"
                or type(result.get("id")) is not int or result["id"] != self.request_id
                or "error" in result or not isinstance(result.get("result"), dict)):
            raise ValueError("Core RPC response failed validation")
        return result["result"]

    def verify_identity(self) -> None:
        health = self.rpc("core.health", {})
        uptime = health.get("uptime_seconds")
        if (health.get("ok") is not True or health.get("version") != __version__
                or health.get("transport") != ["http", "websocket"]
                or isinstance(uptime, bool) or not isinstance(uptime, (int, float))
                or not math.isfinite(uptime) or uptime < 0):
            raise ValueError("endpoint does not match the expected Sumika core.health identity")


def _require_observed_at(value: object) -> None:
    if not isinstance(value, str):
        raise ValueError("import requires the original timezone-aware observed_at")
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.utcoffset() is None:
            raise ValueError
    except ValueError:
        raise ValueError("import requires the original timezone-aware observed_at") from None


def _import_observations(args: argparse.Namespace) -> dict[str, object]:
    resources = _read_json(args.resource_file) if args.resource_file else None
    models = _read_json(args.model_file) if args.model_file else None
    if args.resource_file:
        if not isinstance(resources, dict):
            raise ValueError("resource observation must be an object")
        _require_observed_at(resources.get("observed_at"))
    if args.model_file:
        models = models.get("observations") if isinstance(models, dict) else models
        if not isinstance(models, list) or not models or len(models) > 512:
            raise ValueError("model observations must be a nonempty bounded array or envelope")
        for row in models:
            if not isinstance(row, dict):
                raise ValueError("model observation row must be an object")
            _require_observed_at(row.get("observed_at"))
    probe = RefreshCoordinator(None)
    counts = {}
    if resources is not None:
        counts["resources"] = len(probe.ingest_resources(resources, args.provider_profile_id))
    if models is not None:
        counts["catalog"] = len(probe.ingest_models(models))
    if not args.dry_run:
        coordinator = RefreshCoordinator(args.data_dir)
        if resources is not None:
            coordinator.ingest_resources(resources, args.provider_profile_id)
        if models is not None:
            coordinator.ingest_models(models)
    return {"ok": True, "mode": "offline-import", "counts": counts, "dry_run": args.dry_run}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resources", nargs="?", const=True, type=Path, help="refresh resources; legacy JSON path accepted")
    group.add_argument("--pricing", action="store_true")
    group.add_argument("--catalog", action="store_true")
    group.add_argument("--all", action="store_true")
    group.add_argument("--status", action="store_true")
    parser.add_argument("--resource-file", type=Path)
    parser.add_argument("--model-file", "--models", dest="model_file", type=Path)
    parser.add_argument("--pricing-url", help="legacy alias: only the fixed public URL is accepted; Core performs the fetch")
    parser.add_argument("--data-dir", type=Path, help="explicit offline import/status directory; never used in Core mode")
    parser.add_argument("--core-url", help="configured loopback Core origin (or SUMIKA_CORE_URL)")
    parser.add_argument("--provider-profile-id", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--noninteractive", action="store_true", help="Core-only scheduled operation, no local imports")
    parser.add_argument("--dry-run", action="store_true", help="validate/plan without writes or network")
    args = parser.parse_args(argv)
    exit_code = 0
    try:
        if isinstance(args.resources, Path):
            if args.resource_file:
                raise ValueError("provide only one resource file")
            args.resource_file = args.resources
        if args.pricing_url:
            if args.pricing_url not in ALLOWED_PRICING_URLS:
                raise ValueError("pricing URL is not allowlisted")
            if args.resources or args.catalog or args.all or args.status:
                raise ValueError("pricing URL cannot be combined with another operation")
            args.pricing = True
        files = args.resource_file is not None or args.model_file is not None
        if args.data_dir is not None or files:
            if (args.core_url or args.noninteractive or args.pricing or args.all or not args.data_dir
                    or (args.status and files) or (not args.status and not files)):
                raise ValueError("offline mode requires an explicit data directory and files (or status), without Core/scheduled options")
            if (args.resources and args.model_file) or (args.catalog and args.resource_file):
                raise ValueError("import files do not match the requested operation")
            if args.status:
                result = {"ok": True, "mode": "offline-status", "dry_run": args.dry_run}
                if not args.dry_run:
                    result["status"] = RefreshCoordinator(args.data_dir).status()
            else:
                result = _import_observations(args)
        else:
            kind = next((name for name in ("resources", "pricing", "catalog", "all", "status") if getattr(args, name)), None)
            if kind is None:
                raise ValueError("select --resources, --pricing, --catalog, --all, or --status")
            if args.provider_profile_id:
                raise ValueError("provider profile override is only supported for offline resource imports")
            url = validate_core_url(args.core_url or os.environ.get("SUMIKA_CORE_URL", ""))
            if args.dry_run:
                result = {"ok": True, "dry_run": True, "mode": "core", "kind": kind, "core_url": url, "force": args.force}
            else:
                client = CoreClient(url)
                client.verify_identity()
                method = "model.policy.refresh.status" if kind == "status" else "model.policy.refresh"
                result = client.rpc(method, {} if kind == "status" else {"kind": kind, "force": args.force})
                if kind != "status":
                    refresh = result.get("refresh", {})
                    jobs = refresh.get("jobs", {}) if isinstance(refresh, dict) else {}
                    requested = ("resources", "pricing", "catalog") if kind == "all" else (kind,)
                    if result.get("ok") is False or any(
                        not isinstance(jobs.get(name), dict) or jobs[name].get("state") != "ready"
                        for name in requested
                    ):
                        exit_code = 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code
    except (OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({"ok": False, "state": "needs-review", "detail": "refresh stopped: invalid input or unavailable/unverified Core; no upstream fallback"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
