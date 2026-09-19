"""Real-time translation core: text tracking, dedupe, cache and stale-result drop.

The pipeline is deliberately independent of screen capture and of any specific
translator. A caller feeds OCR lines; the tracker decides what is new, stable,
changed or gone, and only stable text becomes a translation request. A slow
answer that arrives after the on-screen text changed is discarded instead of
overwriting the newer line.
"""
import re
import time

_SPACE = re.compile(r"\s+")


def normalize_text(text):
    if not isinstance(text, str):
        raise ValueError("text required")
    return _SPACE.sub("", text).strip()


def cache_key(*, region, text, target_language, provider, glossary_version=0):
    """Cache identity: same text in another region/language/provider is different."""
    if not isinstance(target_language, str) or not target_language.strip():
        raise ValueError("target language required")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("provider required")
    return (tuple(region) if region else None, normalize_text(text),
            target_language.strip(), provider.strip(), int(glossary_version))


class TranslationCache:
    def __init__(self, *, max_entries=500):
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("invalid cache size")
        self.max_entries = max_entries
        self._entries = {}
        self.hits = 0
        self.misses = 0

    def get(self, key):
        if key in self._entries:
            value = self._entries.pop(key)
            self._entries[key] = value
            self.hits += 1
            return value
        self.misses += 1
        return None

    def put(self, key, value):
        if not isinstance(value, str):
            raise ValueError("translation must be text")
        self._entries.pop(key, None)
        self._entries[key] = value
        while len(self._entries) > self.max_entries:
            self._entries.pop(next(iter(self._entries)))
        return value

    def __len__(self):
        return len(self._entries)


class TextTracker:
    """Turns a stream of OCR frames into stable text lines worth translating."""

    def __init__(self, *, stable_frames=2, target_language="zh-CN", provider="provider",
                 glossary_version=0, cache=None):
        if type(stable_frames) is not int or stable_frames < 1:
            raise ValueError("invalid stability threshold")
        self.stable_frames = stable_frames
        self.target_language = target_language
        self.provider = provider
        self.glossary_version = glossary_version
        self.cache = cache or TranslationCache()
        self._frames = {}
        self._current = {}
        self.sequence = 0

    def _key(self, region, text):
        return cache_key(region=region, text=text, target_language=self.target_language,
                         provider=self.provider, glossary_version=self.glossary_version)

    def observe(self, lines, *, region=None):
        """Feed one frame; returns requests plus stable/changed/gone bookkeeping."""
        if not isinstance(lines, (list, tuple)):
            raise ValueError("lines must be a list")
        scope = tuple(region) if region else None
        seen_keys = set()
        requests, stable = [], []
        for line in lines:
            if not isinstance(line, dict):
                raise ValueError("invalid line")
            text = normalize_text(line.get("text", ""))
            if not text:
                continue
            key = self._key(region, text)
            seen_keys.add(key)
            entry = self._frames.get(key)
            if entry is None:
                entry = {"text": text, "box": line.get("box"), "count": 1, "translated": False}
                self._frames[key] = entry
            else:
                entry["count"] += 1
                entry["box"] = line.get("box") or entry["box"]
            cached = self.cache.get(key)
            if cached is not None:
                entry["translated"] = True
                stable.append({"key": key, "text": text, "box": entry["box"],
                               "status": "cached", "translation": cached})
                continue
            if entry["count"] >= self.stable_frames and not entry["translated"]:
                self.sequence += 1
                request_id = f"{self.sequence}-{abs(hash(key))}"
                entry["translated"] = True
                self._current[request_id] = key
                requests.append({"request_id": request_id, "key": key, "text": text,
                                 "box": entry["box"]})
                stable.append({"key": key, "text": text, "box": entry["box"], "status": "stable"})
        gone = []
        for key in list(self._frames):
            if key[0] == scope and key not in seen_keys:
                gone.append({"key": key, "text": self._frames[key]["text"]})
                del self._frames[key]
                for request_id, mapped in list(self._current.items()):
                    if mapped == key:
                        del self._current[request_id]
        return {"requests": requests, "stable": stable, "gone": gone}

    def accept(self, request_id, translation, *, now=None):
        """Accept a translator answer only if that line is still on screen."""
        if request_id not in self._current:
            return {"accepted": False, "reason": "stale or unknown request"}
        key = self._current.pop(request_id)
        if key not in self._frames:
            return {"accepted": False, "reason": "line left the screen"}
        self.cache.put(key, translation)
        return {"accepted": True, "key": key, "translation": translation,
                "box": self._frames[key]["box"], "at": now or time.time()}

    def pending(self):
        return sorted(self._current)
