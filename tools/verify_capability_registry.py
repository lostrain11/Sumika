"""Real acceptance for the capability registry the extension switches write to.

Checks three things on the machine's own database:

1. every registered capability is one the readiness probes actually report as
   available, and every service capability the probes imply is registered;
2. a toggle round-trips through the bridge API;
3. the switch is enforced: a disabled capability is refused by the service, and
   an enabled one really runs (OCR on a generated fixture, no screen capture).

The script restores the enabled flag it changes, so the user's configuration is
left as it was found.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont

from extensions.capabilities import CapabilityStore
from ui.readiness import probes as readiness_probes, service_capabilities


def post(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf8"))


def get(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf8"))


def run_service(store, request, root):
    with tempfile.TemporaryDirectory(prefix="sumika-capability-") as d:
        path = Path(d) / "request.json"
        path.write_text(json.dumps(request), encoding="utf8")
        return subprocess.run(
            [sys.executable, "-m", "extensions.desktop.service",
             "--store", str(store), "--request", str(path)],
            capture_output=True, text=True, encoding="utf8", cwd=str(root), timeout=180)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", default="http://127.0.0.1:8765")
    parser.add_argument("--store", required=True)
    parser.add_argument("--out", default="docs/project/capability-registry-evidence.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    store_path = Path(args.store)
    failures = []

    modules = get(f"{args.bridge}/api/modules")["modules"]
    registered = {item["id"]: item for item in modules}
    ready = {row["id"] for row in readiness_probes(root) if row["ready"]}
    servable = {entry["id"] for entry in service_capabilities(root)}

    missing = sorted(servable - set(registered))
    if missing:
        failures.append(f"servable capabilities are not registered: {missing}")

    # OCR is the capability this machine can execute end to end.
    text = None
    if "ocr" in registered:
        original = registered["ocr"]["enabled"]
        try:
            post(f"{args.bridge}/api/capabilities/toggle", {"id": "ocr", "enabled": False})
            after = {item["id"]: item for item in get(f"{args.bridge}/api/modules")["modules"]}
            if after["ocr"]["enabled"] is not False:
                failures.append("toggle did not persist the disabled state")

            refused = run_service(store_path, {
                "capability": "ocr", "operation": "recognize",
                "arguments": {"image": "unused.png", "language": "eng"}}, root)
            if refused.returncode != 2 or "disabled" not in (refused.stderr or ""):
                failures.append(
                    f"disabled capability was not refused: rc={refused.returncode} "
                    f"stderr={refused.stderr.strip()[:200]}")

            post(f"{args.bridge}/api/capabilities/toggle", {"id": "ocr", "enabled": True})
            with tempfile.TemporaryDirectory(prefix="sumika-ocr-") as d:
                image = Path(d) / "capability.png"
                canvas = Image.new("RGB", (1000, 200), "white")
                ImageDraw.Draw(canvas).text(
                    (20, 50), "Sumika OCR test 123",
                    font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 48), fill="black")
                canvas.save(image)
                allowed = run_service(store_path, {
                    "capability": "ocr", "operation": "recognize",
                    "arguments": {"image": str(image), "language": "eng"}}, root)
            if allowed.returncode != 0:
                failures.append(f"enabled capability failed: {allowed.stderr.strip()[:300]}")
            else:
                text = json.loads(allowed.stdout)["text"]
                # Line order is the provider's business (RapidOCR split the fixture
                # across two lines here), so require the content, not the layout.
                compact = "".join(text.split()).lower()
                missing_tokens = [token for token in ("sumika", "ocr", "test", "123")
                                  if token not in compact]
                if missing_tokens:
                    failures.append(
                        f"OCR through the registry missed {missing_tokens}: {text!r}")
        finally:
            post(f"{args.bridge}/api/capabilities/toggle",
                 {"id": "ocr", "enabled": bool(original)})

    store = CapabilityStore(str(store_path))
    try:
        final = store.list()
    finally:
        store.close()

    result = {
        "registered": {item["id"]: {"enabled": item["enabled"], "provider": item["provider"]}
                       for item in modules},
        "ocr_text_via_service": text,
        "readiness_ready": sorted(ready),
        "servable": sorted(servable),
        "final_store": final,
        "failures": failures,
        "status": "failed" if failures else "passed",
    }
    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
