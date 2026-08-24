"""Validate Sumika documentation navigation and status metadata.

The checker is deliberately read-only and uses only the Python standard library.
It validates repository-local Markdown links, the documentation index, the
status matrix, and references to archived documents.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote


MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")
FENCE = re.compile(r"^\s*(```|~~~)")
STATUS_VALUES = {"已实现", "部分实现", "规划中"}
REQUIRED_STATUS_IDS = {
    "local-llm",
    "provider-profiles",
    "ccswitch-import",
    "chat",
    "characters",
    "modules",
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


def check_archived_references(root: Path) -> list[str]:
    archived = {
        path.name
        for path in (root / "deprecated").rglob("*")
        if path.is_file() and path.suffix.lower() == ".md"
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
