"""Read public free text-price rows without credentials or model requests."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.request import Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/src")]

from sumika_core.integrations.zhipu_pricing import read_bounded
from tools.register_openrouter_free_candidates import NoRedirect

SOURCE_URL = "https://www.siliconflow.cn/pricing"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class PricingRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        row_id = dict(attrs).get("id", "")
        if not self.stack and not (tag == "div" and row_id.startswith("pricing-row-text-")):
            return
        node = {"tag": tag, "children": []}
        if self.stack:
            self.stack[-1]["children"].append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        if self.stack[-1]["tag"] != tag:
            raise ValueError("unbalanced pricing row")
        node = self.stack.pop()
        if not self.stack:
            self.rows.append(node)

    def handle_data(self, value):
        if self.stack and value.strip():
            self.stack[-1]["children"].append(value.strip())


def leaf_text(node):
    if isinstance(node, str):
        return [node]
    if node["tag"] in {"script", "style"}:
        return []
    return [value for child in node["children"] for value in leaf_text(child)]


def free_text_rows(html):
    parser = PricingRows()
    parser.feed(html)
    parser.close()
    if parser.stack:
        raise ValueError("incomplete pricing row")
    result = {}
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._:-"
    for row in parser.rows:
        cells = [child for child in row["children"] if isinstance(child, dict)]
        if len(cells) != 4:
            continue
        labels = [" ".join(leaf_text(cell)) for cell in cells[1:]]
        if labels[:2] != ["\u514d\u8d39", "\u514d\u8d39"] or labels[2] not in {"-", "\u514d\u8d39"}:
            continue
        model_ids = {value for value in leaf_text(cells[0]) if "/" in value
                     and 1 <= len(value) <= 200 and all(character in allowed for character in value)}
        if len(model_ids) != 1:
            raise ValueError("ambiguous model identity")
        model_id = model_ids.pop()
        if model_id in result:
            raise ValueError("duplicate model price")
        result[model_id] = {"model_id": model_id, "input_price_label": "free", "output_price_label": "free",
                            "cache_price_label": "not-quoted" if labels[2] == "-" else "free"}
    if not 1 <= len(result) <= 128:
        raise ValueError("no bounded explicit free text prices")
    return sorted(result.values(), key=lambda row: row["model_id"])


def fetch_prices():
    request = Request(SOURCE_URL, headers={"Accept": "text/html", "Accept-Encoding": "identity"})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != SOURCE_URL:
            raise ValueError("unexpected pricing response")
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "text/html":
            raise ValueError("HTML pricing page required")
        html = read_bounded(response, 2000000, 20).decode("utf-8")
    return {"schema": "siliconflow-public-price-observation/v1", "source_url": SOURCE_URL,
            "observed_at": datetime.now(timezone.utc).isoformat(), "model_calls": 0,
            "authority": "public-price-observation-only", "models": free_text_rows(html)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError("report exists; no overwrite")
    report = fetch_prices()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=True)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"ok": False, "failure_class": type(error).__name__}))
        raise SystemExit(1) from None
