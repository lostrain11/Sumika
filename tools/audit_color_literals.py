"""Inventory literal colours outside the token definitions.

Tokens are the single source of truth for colour; every literal hex outside
`:root` / `[data-theme]` blocks is a future dark-theme hole. This reports them
per file with line numbers so Phase 1 can retire them one by one.
"""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path("D:/Code/Sumika")
TARGETS = [
    "ui/app/index.html",
    "ui/app/layout.css",
    "ui/app/bind.js",
    "ui/app/management.js",
    "ui/app/theme.js",
    "ui/app/appearance.js",
    "ui/app/speech-input.js",
    "ui/app/speech-playback.js",
    "ui/app/model-library.js",
    "ui/app/handoff.js",
    "ui/app/bridge-client.js",
    "ui/app/task-intent.js",
]

HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
# rgba()/rgb() literals are equally theme-bound.
RGB = re.compile(r"rgba?\([^)]*\)")
TOKEN_BLOCK = re.compile(r":root\s*\{[^}]*\}|html\[data-theme=['\"]dark['\"]\]\s*\{[^}]*\}", re.S)

report = {}
total = Counter()
for rel in TARGETS:
    path = ROOT / rel
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # Skip characters inside token declaration blocks.
    masked = list(text)
    for match in TOKEN_BLOCK.finditer(text):
        for i in range(match.start(), match.end()):
            if masked[i] != "\n":
                masked[i] = " "
    masked_text = "".join(masked)
    offset_to_line = []
    for index, line in enumerate(lines, start=1):
        offset_to_line.extend([index] * (len(line) + 1))
    while len(offset_to_line) < len(masked_text):
        offset_to_line.append(len(lines))

    hits = []
    for match in HEX.finditer(masked_text):
        hits.append({"line": offset_to_line[match.start()], "value": match.group(0)})
    rgbs = []
    for match in RGB.finditer(masked_text):
        rgbs.append({"line": offset_to_line[match.start()], "value": match.group(0)[:48]})

    # Token definitions that do exist (for the "is this colour already a token?" check).
    tokens = sorted(set(HEX.findall("".join(TOKEN_BLOCK.findall(text)))))
    if hits or rgbs:
        report[rel] = {
            "hex_count": len(hits),
            "rgb_count": len(rgbs),
            "hex_by_value": dict(Counter(h["value"].lower() for h in hits).most_common()),
            "hex_lines": [f"{h['line']}: {h['value']}" for h in hits],
            "rgb_samples": [f"{r['line']}: {r['value']}" for r in rgbs[:20]],
        }
        total["hex"] += len(hits)
        total["rgb"] += len(rgbs)

out = ROOT / ".sumika-next/baseline/color-inventory.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"per_file": report, "totals": dict(total)}, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"files with literals: {len(report)}")
print(f"total hex outside tokens: {total['hex']}, rgb: {total['rgb']}")
for rel, data in report.items():
    print(f"  {rel}: {data['hex_count']} hex, {data['rgb_count']} rgb")
print("written:", out)
