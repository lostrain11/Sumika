"""Window capture planning for real-time translation, with overlay exclusion.

The translator must never OCR its own overlay, or it would translate its own
translation. This module therefore captures a target window's own rectangle
instead of the whole screen, reports when an overlay overlaps the target, and
flags unusable frames (blank/black, common with exclusive fullscreen) instead of
passing them to OCR.
"""
from pathlib import Path


def resolve_window(title_contains, windows):
    """Pick exactly one window from an injected inventory; ambiguity fails closed."""
    if not isinstance(title_contains, str) or not title_contains.strip():
        raise ValueError("window title fragment required")
    if not isinstance(windows, (list, tuple)):
        raise ValueError("window inventory required")
    needle = title_contains.casefold()
    matches = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        title = window.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        if window.get("visible") is False:
            continue
        if needle in title.casefold():
            matches.append(window)
    if not matches:
        return {"status": "not_found"}
    if len(matches) > 1:
        return {"status": "ambiguous", "candidates": [m.get("title") for m in matches]}
    window = matches[0]
    handle = window.get("handle")
    rect = window.get("rect")
    if handle is None or not _valid_rect(rect):
        return {"status": "invalid_window"}
    return {"status": "ok", "handle": handle, "title": window.get("title"),
            "rect": tuple(int(v) for v in rect)}


def _valid_rect(rect):
    return (isinstance(rect, (list, tuple)) and len(rect) == 4
            and all(isinstance(v, (int, float)) for v in rect) and rect[2] > 0 and rect[3] > 0)


def _overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def plan_capture(window, *, overlay=None, min_side=64):
    """Decide how to capture and whether the overlay can contaminate the frame."""
    if not _valid_rect(window.get("rect")):
        raise ValueError("invalid window rectangle")
    rect = tuple(int(v) for v in window["rect"])
    if rect[2] < min_side or rect[3] < min_side:
        return {"status": "unknown", "reason": "window is smaller than the minimum capture size"}
    plan = {"status": "ok", "method": "window", "handle": window.get("handle"), "rect": rect,
            "warnings": []}
    if overlay and _valid_rect(overlay.get("rect")):
        overlay_rect = tuple(int(v) for v in overlay["rect"])
        plan["overlay_excluded"] = True
        if _overlaps(rect, overlay_rect):
            plan["warnings"].append(
                "overlay overlaps the captured window; it must be a separate top-level window "
                "(WS_EX_TRANSPARENT/WS_EX_LAYERED) so window capture does not include it")
    else:
        plan["overlay_excluded"] = True
    return plan


def frame_is_usable(statistics, *, min_stddev=2.0):
    """Reject blank or black frames before OCR: stat = (mean, stddev) of pixels."""
    if not isinstance(statistics, (list, tuple)) or len(statistics) != 2:
        raise ValueError("statistics must be (mean, stddev)")
    mean, stddev = statistics
    if not all(isinstance(v, (int, float)) for v in (mean, stddev)):
        raise ValueError("statistics must be numeric")
    if mean <= 1.0:
        return {"usable": False, "reason": "frame is black; exclusive fullscreen may block capture"}
    if stddev < min_stddev:
        return {"usable": False, "reason": "frame has no contrast; capture may be blocked"}
    return {"usable": True}


def grab_window(rect, output):
    """Capture one window rectangle. Requires the desktop extension environment."""
    if not _valid_rect(rect):
        raise ValueError("invalid capture rectangle")
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    from PIL import ImageGrab
    x, y, width, height = (int(v) for v in rect)
    image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return {"path": str(output), "rect": (x, y, width, height)}
