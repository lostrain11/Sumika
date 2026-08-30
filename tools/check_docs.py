"""Validate Sumika documentation navigation and status metadata.

The checker is deliberately read-only and uses only the Python standard library.
It validates repository-local Markdown links, the documentation index, the
status matrix, current execution contract, and references to archived documents.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")
FENCE = re.compile(r"^\s*(```|~~~)")
STATUS_VALUES = {"已实现", "部分实现", "规划中"}
REQUIREMENT_PROVENANCE = {"confirmed", "normalized", "inferred", "external"}
REQUIREMENT_INTENT_STATES = {"active", "deferred", "superseded", "historical"}
REQUIREMENT_ID = re.compile(r"^(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{3}|HISTORY-[A-Z0-9-]+)$")
REQUIREMENT_SENSITIVE = (
    (re.compile(r"(?i)\b[a-z]:[\\/]+users[\\/]"), "Windows user path"),
    (
        re.compile(r"(?i)(?<![a-z0-9])/(?:users|home)/[^\s`\"'<>]+"),
        "Unix user path",
    ),
    (
        re.compile(r"(?i)(?<![a-z0-9])\\\\[^\s`\"'<>]+"),
        "UNC path",
    ),
    (re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"), "API key-like token"),
    (re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"), "Bearer token-like value"),
    (
        re.compile(r"(?i)\beyj[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}"),
        "JWT-like token",
    ),
    (
        re.compile(
            r"(?i)(?<![a-z0-9])['\"]?(?:api[-_ ]?key|token|cookie|authorization)['\"]?"
            r"\s*[:=]\s*['\"]?[^\s`\"',}]{8,}"
        ),
        "credential assignment",
    ),
)
REQUIRED_STATUS_IDS = {
    "local-llm",
    "provider-profiles",
    "ccswitch-import",
    "chat",
    "characters",
    "modules",
    "desktop-automation",
    "tasks",
    "avatar-vrm-desktop",
    "plugins-manifest",
    "audio",
    "memory",
    "vision",
    "snapshots",
    "live2d",
    "virtual-world",
    "life-agent",
    "remote-runner",
    "android-client",
}
CURRENT_EXECUTION_HEADINGS = (
    "# Sumika 当前执行契约",
    "## 目标",
    "## Definition of Done",
    "## 当前基线",
    "## 当前里程碑",
    "## 接下来的三个动作",
    "## 固定决策",
    "## 明确暂缓",
    "## 当前阻塞",
    "## 验证记录",
    "## 恢复顺序",
    "## 更新规则",
)
CURRENT_EXECUTION_BASELINE_FIELDS = (
    "- Branch:",
    "- Baseline commit:",
    "- Last verified commit:",
)
CURRENT_EXECUTION_SENSITIVE = (
    (re.compile(r"(?i)\b[a-z]:\\users\\"), "Windows user path"),
    (re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"), "API key-like token"),
    (re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"), "Bearer token-like value"),
)


def product_markdown(root: Path) -> list[Path]:
    """Return Markdown files that are part of the active product docs."""

    excluded = {".git", "node_modules", "deprecated"}
    result: list[Path] = []
    for path in root.rglob("*.md"):
        relative_parts = path.relative_to(root).parts
        if any(part in excluded for part in relative_parts):
            continue
        result.append(path)
    return sorted(result)


def active_docs(root: Path) -> list[Path]:
    docs_root = root / "docs"
    return sorted(
        path
        for path in docs_root.rglob("*.md")
        if "deprecated" not in path.relative_to(root).parts
    )


def _without_code(lines: list[str]) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    for line_number, line in enumerate(lines, start=1):
        match = FENCE.match(line)
        if match:
            marker = match.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
            continue
        if not in_fence:
            # Inline code is usually used for command/path examples, not links.
            result.append((line_number, re.sub(r"`[^`]*`", "", line)))
    return result


def _destination(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")]
    return raw.split(maxsplit=1)[0]


def extract_links(text: str) -> list[tuple[int, str]]:
    links: list[tuple[int, str]] = []
    for line_number, line in _without_code(text.splitlines()):
        for match in MARKDOWN_LINK.finditer(line):
            links.append((line_number, _destination(match.group(1))))
    return links


def resolve_local(root: Path, source: Path, target: str) -> Path | None:
    target = unquote(target.split("#", 1)[0].split("?", 1)[0]).strip()
    if not target or re.match(r"^[a-z][a-z0-9+.-]*://", target, re.I):
        return None
    if target.startswith("/"):
        return root / target.lstrip("/")
    return (source.parent / target).resolve()


def check_local_links(root: Path, paths: list[Path] | None = None) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for source in paths or product_markdown(root):
        relative = source.relative_to(root).as_posix()
        for line_number, target in extract_links(source.read_text(encoding="utf-8")):
            resolved = resolve_local(root, source, target)
            if resolved is None:
                continue
            try:
                resolved.relative_to(root)
            except ValueError:
                errors.append(f"{relative}:{line_number}: link escapes repository: {target}")
                continue
            if not resolved.exists():
                errors.append(
                    f"{relative}:{line_number}: broken local link {target} "
                    f"(resolved to {resolved.relative_to(root).as_posix()})"
                )
    return errors


def _cell_values(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def check_index_coverage(root: Path) -> list[str]:
    root = root.resolve()
    index = root / "docs" / "README.md"
    if not index.exists():
        return ["docs/README.md: documentation index is missing"]
    linked = set()
    for _, target in extract_links(index.read_text(encoding="utf-8")):
        resolved = resolve_local(root, index, target)
        if resolved and resolved.exists():
            linked.add(resolved.resolve())
    errors: list[str] = []
    for document in active_docs(root):
        if document.resolve() == index.resolve():
            continue
        if document.resolve() not in linked:
            errors.append(
                f"docs/README.md: missing index link for {document.relative_to(root)}"
            )
    return errors


def check_status_matrix(root: Path) -> list[str]:
    root = root.resolve()
    matrix = root / "docs" / "status-matrix.md"
    if not matrix.exists():
        return ["docs/status-matrix.md: status matrix is missing"]
    lines = matrix.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("| ID |")),
        None,
    )
    if header_index is None:
        return ["docs/status-matrix.md: missing status table header"]
    headers = _cell_values(lines[header_index])
    expected = ["ID", "状态", "当前入口", "主文档", "验证证据", "下一步"]
    if headers != expected:
        return [
            "docs/status-matrix.md: expected columns "
            + ", ".join(expected)
            + "; got "
            + ", ".join(headers)
        ]
    errors: list[str] = []
    seen: set[str] = set()
    rows: dict[str, int] = {}
    for index in range(header_index + 2, len(lines)):
        line = lines[index]
        if not line.strip().startswith("|"):
            break
        cells = _cell_values(line)
        if len(cells) != len(expected) or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        row_number = index + 1
        identifier = cells[0].strip("`")
        rows[identifier] = row_number
        if identifier in seen:
            errors.append(f"docs/status-matrix.md:{row_number}: duplicate ID {identifier}")
        seen.add(identifier)
        if cells[1] not in STATUS_VALUES:
            errors.append(
                f"docs/status-matrix.md:{row_number}: invalid status {cells[1]!r}"
            )
        for column_index, label in ((3, "主文档"), (4, "验证证据")):
            links = extract_links(cells[column_index])
            if not links:
                errors.append(
                    f"docs/status-matrix.md:{row_number}: {label} must contain a local link"
                )
                continue
            for _, target in links:
                resolved = resolve_local(root, matrix, target)
                if resolved is None or not resolved.exists():
                    errors.append(
                        f"docs/status-matrix.md:{row_number}: invalid {label} link {target}"
                    )
    missing = sorted(REQUIRED_STATUS_IDS - seen)
    for identifier in missing:
        errors.append(f"docs/status-matrix.md: missing required status ID {identifier}")
    return errors


def _status_matrix_ids(root: Path) -> set[str]:
    """Return IDs from the primary status table without duplicating validation."""

    matrix = root / "docs" / "status-matrix.md"
    if not matrix.exists():
        return set()
    lines = matrix.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("| ID |")),
        None,
    )
    if header_index is None:
        return set()
    identifiers: set[str] = set()
    for line in lines[header_index + 2 :]:
        if not line.strip().startswith("|"):
            break
        cells = _cell_values(line)
        if cells and cells[0] not in {"---", ""}:
            identifiers.add(cells[0].strip("`"))
    return identifiers


def _resolve_requirement_reference(root: Path, source: Path, target: str) -> Path | None:
    """Resolve a requirement evidence path and reject paths outside the repo."""

    if not isinstance(target, str) or not target.strip():
        return None
    candidate = (source.parent / target.split("#", 1)[0].split("?", 1)[0]).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _requirement_excerpt_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(re.findall(r"`(EX-[A-Z0-9-]+)`", path.read_text(encoding="utf-8")))


def _requirement_mapping(root: Path) -> tuple[set[str], dict[str, set[str]], list[str]]:
    """Read the optional status-to-requirement mapping below the main table."""

    path = root / "docs" / "status-matrix.md"
    if not path.exists():
        return set(), {}, ["docs/status-matrix.md: status matrix is missing"]
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == "## 需求基线映射")
    except StopIteration:
        return set(), {}, ["docs/status-matrix.md: missing 需求基线映射 section"]
    header = next(
        (index for index in range(start + 1, len(lines)) if lines[index].strip().startswith("| 状态 ID |")),
        None,
    )
    if header is None:
        return set(), {}, ["docs/status-matrix.md: requirement mapping table header is missing"]
    mapping: dict[str, set[str]] = {}
    errors: list[str] = []
    for index in range(header + 2, len(lines)):
        line = lines[index]
        if not line.strip().startswith("|"):
            break
        cells = _cell_values(line)
        if len(cells) != 2:
            errors.append(f"docs/status-matrix.md:{index + 1}: invalid requirement mapping row")
            continue
        status_id = cells[0].strip("`")
        requirement_ids = set(re.findall(r"`?([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{3})`?", cells[1]))
        if not status_id or not requirement_ids:
            errors.append(f"docs/status-matrix.md:{index + 1}: mapping row must contain a status and requirement ID")
        mapping[status_id] = requirement_ids
    return _status_matrix_ids(root), mapping, errors


def check_requirements(root: Path) -> list[str]:
    """Validate the machine-readable requirements ledger and its evidence graph."""

    root = root.resolve()
    ledger = root / "docs" / "requirements" / "requirements.json"
    if not ledger.exists():
        return ["docs/requirements/requirements.json: requirements ledger is missing"]
    errors: list[str] = []
    try:
        payload = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [f"docs/requirements/requirements.json: invalid JSON ({error})"]
    if not isinstance(payload, dict) or payload.get("schema") != "sumika-requirements/v1":
        errors.append("docs/requirements/requirements.json: schema must be sumika-requirements/v1")
    rows = payload.get("requirements") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return errors + ["docs/requirements/requirements.json: requirements must be a non-empty list"]

    required_fields = {
        "id",
        "category",
        "statement",
        "acceptance",
        "provenance",
        "intent_state",
        "source_refs",
        "excerpt_refs",
        "implementation_refs",
        "test_refs",
    }
    records: dict[str, dict] = {}
    for index, row in enumerate(rows, start=1):
        location = f"docs/requirements/requirements.json: requirement[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{location} must be an object")
            continue
        missing = sorted(required_fields - set(row))
        if missing:
            errors.append(f"{location} missing fields: {', '.join(missing)}")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not REQUIREMENT_ID.fullmatch(identifier):
            errors.append(f"{location}: invalid requirement ID {identifier!r}")
            continue
        if identifier in records:
            errors.append(f"{location}: duplicate requirement ID {identifier}")
        records[identifier] = row
        if row.get("provenance") not in REQUIREMENT_PROVENANCE:
            errors.append(f"{location}: invalid provenance {row.get('provenance')!r}")
        if row.get("intent_state") not in REQUIREMENT_INTENT_STATES:
            errors.append(f"{location}: invalid intent_state {row.get('intent_state')!r}")
        if not isinstance(row.get("statement"), str) or not row.get("statement", "").strip():
            errors.append(f"{location}: statement must be a non-empty string")
        acceptance = row.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance or not all(isinstance(item, str) and item.strip() for item in acceptance):
            errors.append(f"{location}: acceptance must be a non-empty list of strings")
        for field in ("implementation_refs", "test_refs", "source_refs", "excerpt_refs", "supersedes", "superseded_by"):
            value = row.get(field, [])
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"{location}: {field} must be a list of strings")
            elif field == "source_refs" and not value:
                errors.append(f"{location}: source_refs must not be empty")
        if row.get("intent_state") != "historical" and not isinstance(row.get("status_ref"), str):
            errors.append(f"{location}: active/deferred/superseded records require status_ref")

    status_ids = _status_matrix_ids(root)
    excerpt_path = root / "docs" / "requirements" / "original-excerpts.md"
    excerpt_ids = _requirement_excerpt_ids(excerpt_path)
    content_paths = [
        root / "docs" / "requirements" / "README.md",
        root / "docs" / "requirements" / "baseline.md",
        root / "docs" / "requirements" / "model-policy.md",
        excerpt_path,
        ledger,
    ]
    human_paths = content_paths[:-1]
    combined_content = "\n".join(path.read_text(encoding="utf-8") for path in human_paths if path.exists())
    for path in content_paths:
        if not path.exists():
            errors.append(f"{path.relative_to(root).as_posix()}: requirements document is missing")
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern, label in REQUIREMENT_SENSITIVE:
                if pattern.search(line):
                    errors.append(f"{path.relative_to(root).as_posix()}:{line_number}: contains {label}")

    for identifier, row in records.items():
        location = f"docs/requirements/requirements.json: {identifier}"
        status_ref = row.get("status_ref")
        if status_ref is not None:
            if not isinstance(status_ref, str) or not status_ref.startswith("status-matrix:"):
                errors.append(f"{location}: status_ref must start with status-matrix:")
            elif status_ref.removeprefix("status-matrix:") not in status_ids:
                errors.append(f"{location}: unknown status_ref {status_ref}")
        for field in ("implementation_refs", "test_refs"):
            for reference in row.get(field, []) if isinstance(row.get(field), list) else []:
                resolved = _resolve_requirement_reference(root, ledger, reference)
                if resolved is None or not resolved.exists():
                    errors.append(f"{location}: missing {field} reference {reference}")
        for excerpt in row.get("excerpt_refs", []) if isinstance(row.get("excerpt_refs"), list) else []:
            if excerpt not in excerpt_ids:
                errors.append(f"{location}: unknown excerpt_ref {excerpt}")
        if not re.search(rf"`{re.escape(identifier)}`", combined_content):
            errors.append(f"{location}: ID is not present in the human-readable requirements documents")

    relation_graph: dict[str, set[str]] = {identifier: set() for identifier in records}
    for identifier, row in records.items():
        supersedes = row.get("supersedes", []) if isinstance(row.get("supersedes"), list) else []
        superseded_by = row.get("superseded_by", []) if isinstance(row.get("superseded_by"), list) else []
        for field, targets in (("supersedes", supersedes), ("superseded_by", superseded_by)):
            for target in targets:
                if target not in records:
                    errors.append(f"docs/requirements/requirements.json: {identifier}: unknown relation target {target}")
                elif target == identifier:
                    errors.append(f"docs/requirements/requirements.json: {identifier}: self-referencing relation")
        # Only ``supersedes`` is a directed edge.  ``superseded_by`` is its
        # reverse declaration and must not create a false cycle.
        for target in supersedes:
            if target in records and identifier not in (records[target].get("superseded_by") or []):
                errors.append(
                    f"docs/requirements/requirements.json: {identifier}: relation is missing reverse superseded_by on {target}"
                )
            if target in records:
                relation_graph[identifier].add(target)
        for target in superseded_by:
            if target in records and identifier not in (records[target].get("supersedes") or []):
                errors.append(
                    f"docs/requirements/requirements.json: {identifier}: relation is missing reverse supersedes on {target}"
                )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            errors.append(f"docs/requirements/requirements.json: supersession cycle includes {identifier}")
            return
        if identifier in visited:
            return
        visiting.add(identifier)
        for target in relation_graph.get(identifier, set()):
            visit(target)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in relation_graph:
        visit(identifier)

    matrix_ids, mapping, mapping_errors = _requirement_mapping(root)
    errors.extend(mapping_errors)
    if matrix_ids:
        for status_id in sorted(matrix_ids):
            if status_id not in mapping:
                errors.append(f"docs/status-matrix.md: missing requirement mapping for {status_id}")
        for status_id, requirement_ids in mapping.items():
            if status_id not in matrix_ids:
                errors.append(f"docs/status-matrix.md: mapping references unknown status ID {status_id}")
            for requirement_id in requirement_ids:
                if requirement_id not in records:
                    errors.append(f"docs/status-matrix.md: mapping references unknown requirement ID {requirement_id}")
    return errors


def check_current_execution(root: Path) -> list[str]:
    root = root.resolve()
    document = root / "docs" / "current-execution.md"
    if not document.exists():
        return ["docs/current-execution.md: current execution contract is missing"]
    lines = document.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []
    if len(lines) > 150:
        errors.append(
            f"docs/current-execution.md: expected at most 150 lines; got {len(lines)}"
        )

    stripped = {line.strip() for line in lines}
    for heading in CURRENT_EXECUTION_HEADINGS:
        if heading not in stripped:
            errors.append(f"docs/current-execution.md: missing heading {heading}")
    for field in CURRENT_EXECUTION_BASELINE_FIELDS:
        if not any(line.strip().startswith(field) for line in lines):
            errors.append(f"docs/current-execution.md: missing baseline field {field}")

    try:
        action_start = next(
            index
            for index, line in enumerate(lines)
            if line.strip() == "## 接下来的三个动作"
        ) + 1
    except StopIteration:
        action_start = len(lines)
    action_end = next(
        (
            index
            for index in range(action_start, len(lines))
            if lines[index].strip().startswith("## ")
        ),
        len(lines),
    )
    action_numbers = [
        match.group(1)
        for line in lines[action_start:action_end]
        if (match := re.match(r"^\s*([1-9]\d*)\.\s+", line))
    ]
    if action_numbers != ["1", "2", "3"]:
        errors.append(
            "docs/current-execution.md: next actions must contain exactly numbered items 1, 2, 3"
        )

    for line_number, line in enumerate(lines, start=1):
        for pattern, label in CURRENT_EXECUTION_SENSITIVE:
            if pattern.search(line):
                errors.append(
                    f"docs/current-execution.md:{line_number}: contains {label}"
                )
    return errors


def check_archived_references(root: Path) -> list[str]:
    # Only an archive subtree that mirrors the product ``docs/`` directory is
    # a documentation archive.  Runtime profiles can contain dependency
    # READMEs and other Markdown files that are not product documents.
    archived_root = root / "deprecated"
    archived = {
        path.name
        for path in archived_root.rglob("*.md")
        if path.is_file()
        and path.name != "ARCHIVE_RECORD.md"
        and "docs" in path.relative_to(archived_root).parts
    }
    if not archived:
        return []
    errors: list[str] = []
    for source in product_markdown(root):
        text = source.read_text(encoding="utf-8")
        for name in sorted(archived):
            if name in text:
                errors.append(
                    f"{source.relative_to(root)}: references archived document {name}"
                )
    return errors


def run_checks(root: Path) -> list[str]:
    return (
        check_local_links(root)
        + check_index_coverage(root)
        + check_status_matrix(root)
        + check_requirements(root)
        + check_current_execution(root)
        + check_archived_references(root)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors = run_checks(root)
    if errors:
        print("Documentation check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Documentation check passed for {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
