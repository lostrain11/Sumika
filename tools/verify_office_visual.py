"""Visual acceptance for office files: render pages to images and OCR them.

Roundtrip tests prove the file survived editing; this proves the rendered page
actually shows the expected text, which is what a user sees. Run it with the
isolated office environment interpreter.
"""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pypdfium2 as pdfium
from PIL import Image

from extensions.desktop.ocr.ocr import recognize
from extensions.office.render import convert
from extensions.office.verify_files import verify

EXPECTED = {
    "docx": ["项目周报", "任务", "状态"],
    # Sheet names are not printed on the page, so only page-visible text is asserted.
    "xlsx": ["项目", "完成量", "保留合并单元格"],
    "pptx": ["阶段进度", "读取", "保留页面"],
}


def ink_ratio(image):
    gray = image.convert("L")
    pixels = list(gray.getdata())
    dark = sum(1 for value in pixels if value < 200)
    return round(dark / len(pixels), 5)


def pages_of(path, scale=2.0):
    document = pdfium.PdfDocument(str(path))
    try:
        for index in range(len(document)):
            yield index + 1, document[index].render(scale=scale).to_pil().convert("RGB")
    finally:
        document.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soffice", required=True)
    parser.add_argument("--out", type=Path, default=Path("docs/project/office-visual-evidence.json"))
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="office-visual-", dir=".sumika-next"))
    verify(root / "files")
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "artifact": str(root), "renderer": "LibreOffice -> PDF -> pypdfium2 -> PNG -> RapidOCR",
              "documents": []}
    for kind, expected in EXPECTED.items():
        source = root / "files" / f"edited.{kind}"
        rendered = convert(source, root / kind, executable=args.soffice)
        pages, hits_all = [], set()
        for number, image in pages_of(rendered["path"]):
            png = root / kind / f"page-{number}.png"
            png.parent.mkdir(parents=True, exist_ok=True)
            image.save(png)
            result = recognize(png, provider="auto", detect=True)
            compact = "".join(result["text"].split())
            hits = [token for token in expected if token in compact]
            hits_all.update(hits)
            pages.append({"page": number, "png": str(png), "ink_ratio": ink_ratio(image),
                          "ocr_lines": len(result["lines"]), "hits": hits,
                          "text_sample": compact[:120]})
        missing = [token for token in expected if token not in hits_all]
        report["documents"].append({
            "kind": kind, "pdf": str(rendered["path"]), "pages": pages,
            "expected": expected, "missing": missing,
            "blank_pages": [page["page"] for page in pages if page["ink_ratio"] < 0.0005],
            "passed": not missing and all(page["ink_ratio"] >= 0.0005 for page in pages)})
    report["passed"] = all(document["passed"] for document in report["documents"])
    report["visual_layout_review"] = "ran_via_ocr" if report["passed"] else "partial"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    for document in report["documents"]:
        print(json.dumps({"kind": document["kind"], "pages": len(document["pages"]),
                          "missing": document["missing"], "blank": document["blank_pages"],
                          "passed": document["passed"]}, ensure_ascii=False))
    print("passed:", report["passed"])


if __name__ == "__main__":
    main()
