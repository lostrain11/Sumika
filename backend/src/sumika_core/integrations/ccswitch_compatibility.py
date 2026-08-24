"""Read-only CC Switch compatibility monitor."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener, urlopen

from ..provider_imports import ProviderImportRegistry


class CCSwitchCompatibilityChecker:
    _REPOSITORY = "farion1231/cc-switch"
    _USER_AGENT = "Sumika-compatibility-check/0.1"

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)

    def manifest(self) -> dict[str, Any]:
        value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("integration") != "ccswitch-v1":
            raise ValueError("Invalid CC Switch compatibility manifest")
        return value

    def check(self, *, timeout: float = 12.0) -> dict[str, Any]:
        manifest = self.manifest()
        try:
            release = self._json(
                f"https://api.github.com/repos/{self._REPOSITORY}/releases/latest",
                timeout,
            )
            if not isinstance(release, dict):
                raise ValueError("GitHub latest release response is not an object")
            tags_value = self._json(
                f"https://api.github.com/repos/{self._REPOSITORY}/tags?per_page=10",
                timeout,
            )
            releases_value = self._json(
                f"https://api.github.com/repos/{self._REPOSITORY}/releases?per_page=10",
                timeout,
            )
            tags = [
                str(item.get("name"))
                for item in tags_value
                if isinstance(item, dict) and item.get("name")
            ] if isinstance(tags_value, list) else []
            recent_releases = [
                {
                    "tag": str(item.get("tag_name")),
                    "published_at": item.get("published_at"),
                    "url": item.get("html_url"),
                }
                for item in releases_value
                if isinstance(item, dict) and item.get("tag_name")
            ] if isinstance(releases_value, list) else []
            latest_tag = str(release.get("tag_name") or (tags[0] if tags else ""))
            if not latest_tag:
                raise ValueError("Latest GitHub release has no tag_name")
            changes: list[dict[str, Any]] = []
            parser_text = ""
            for entry in manifest.get("monitored_files", []):
                path = str(entry["path"])
                data = self._bytes(
                    f"https://raw.githubusercontent.com/farion1231/cc-switch/{latest_tag}/{path}",
                    timeout,
                )
                digest = hashlib.sha256(data).hexdigest()
                changed = digest != entry.get("sha256")
                changes.append(
                    {
                        "path": path,
                        "category": entry.get("category", "review"),
                        "baseline_sha256": entry.get("sha256"),
                        "latest_sha256": digest,
                        "changed": changed,
                    }
                )
                if path.endswith("deeplink/parser.rs"):
                    parser_text = data.decode("utf-8", errors="replace")
            incompatible = not all(
                marker in parser_text
                for marker in ("ccswitch://v1/import", 'version != "v1"', '"provider" => parse_provider_deeplink')
            )
            critical_changes = [item for item in changes if item["changed"] and item["category"] == "protocol"]
            review_changes = [
                item for item in changes
                if item["changed"] and item["category"] not in {"release", "protocol"}
            ]
            any_changes = any(item["changed"] for item in changes)
            if incompatible:
                status = "protocol_incompatible"
            elif critical_changes:
                status = "review_required"
            elif review_changes:
                status = "review_required"
            elif latest_tag != manifest.get("upstream_tag") or any_changes:
                status = "release_only"
            else:
                status = "up_to_date"
            fixtures = self._run_local_fixtures()
            return {
                "ok": status in {"up_to_date", "release_only"} and fixtures["failed"] == 0,
                "status": status,
                "baseline_tag": manifest.get("upstream_tag"),
                "baseline_commit": manifest.get("upstream_commit"),
                "latest_tag": latest_tag,
                "latest_tags": tags,
                "recent_releases": recent_releases,
                "release_url": release.get("html_url"),
                "published_at": release.get("published_at"),
                "changes": changes,
                "review_changes": review_changes,
                "fixtures": fixtures,
                "automatic_changes": False,
            }
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "status": "check_failed",
                "baseline_tag": manifest.get("upstream_tag"),
                "baseline_commit": manifest.get("upstream_commit"),
                "latest_tags": [],
                "recent_releases": [],
                "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                "automatic_changes": False,
            }

    @staticmethod
    def _bytes(url: str, timeout: float) -> bytes:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": CCSwitchCompatibilityChecker._USER_AGENT,
        }
        # An optional token avoids shared-IP limits without ever entering a
        # compatibility report or error message.
        token = os.getenv("GITHUB_TOKEN") or os.getenv("SUMIKA_GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token.strip()}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            # Shared local proxies can exhaust their GitHub API bucket while
            # the user's direct route still has capacity. Retry only the
            # explicit rate-limit response; authentication and other 403s
            # must remain visible to the caller.
            if exc.code != 403:
                raise
            body = exc.read(512).decode("utf-8", errors="replace").lower()
            if "rate limit" not in body and "rate_limit" not in body:
                raise
            direct = build_opener(ProxyHandler({}))
            # Rebuild the request because urllib may attach proxy response
            # bookkeeping to the object that raised the HTTPError.
            direct_request = Request(url, headers=headers)
            with direct.open(direct_request, timeout=timeout) as response:
                return response.read()

    @classmethod
    def _json(cls, url: str, timeout: float) -> Any:
        value = json.loads(cls._bytes(url, timeout).decode("utf-8"))
        return value

    @staticmethod
    def _run_local_fixtures() -> dict[str, int]:
        registry = ProviderImportRegistry()
        fixtures = (
            "ccswitch://v1/import?resource=provider&app=codex&name=Minimal&endpoint=https%3A%2F%2Fexample.invalid%2Fv1&apiKey=sk-test&model=test-model",
            "ccswitch://v1/import?resource=provider&app=codex&name=Multi&endpoint=https%3A%2F%2Fa.invalid%2Fv1%2Chttps%3A%2F%2Fb.invalid%2Fv1&model=test-model",
            "ccswitch://v1/import?resource=provider&app=codex&name=Unknown&endpoint=https%3A%2F%2Fexample.invalid%2Fv1&model=test-model&futureField=value",
        )
        passed = 0
        for raw in fixtures:
            try:
                registry.preview(raw)
                passed += 1
            except Exception:
                pass
        return {"passed": passed, "failed": len(fixtures) - passed, "total": len(fixtures)}
