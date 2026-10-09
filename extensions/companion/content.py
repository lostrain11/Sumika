"""Normalize web, video and ebook context before it reaches the question loop."""
import hashlib
import json
import re
from .contracts import ObservationBundle

_SPACE = re.compile(r"\s+")


def _text(value, name='text'):
    if not isinstance(value, str):
        raise ValueError(f'{name} must be text')
    return _SPACE.sub(' ', value).strip()


def webpage(*, target, text, title=None, url=None, selected=False):
    body = _text(text)
    return ObservationBundle.now(source='web-selection' if selected else 'web-visible', target=_text(target, 'target'),
        valid=bool(body), text=body, metadata={k:v for k,v in {'title':title, 'url':url, 'selected':selected}.items() if v is not None})


def video(*, target, subtitles, media_time_seconds=None, title=None, audio_transcript=None):
    # Subtitle text is preferred; an audio transcript supplements it only when present.
    parts = [_text(subtitles, 'subtitles')] if subtitles else []
    if audio_transcript:
        parts.append(_text(audio_transcript, 'audio_transcript'))
    body = '\n'.join(dict.fromkeys(p for p in parts if p))
    return ObservationBundle.now(source='video-subtitle' if subtitles else 'video-audio', target=_text(target, 'target'),
        valid=bool(body), text=body, media_time_seconds=media_time_seconds,
        metadata={'title': title} if title else {})


def ebook(*, target, page_text, page=None, chapter=None, selected=False):
    body = _text(page_text, 'page_text')
    metadata = {k:v for k,v in {'page':page, 'chapter':chapter, 'selected':selected}.items() if v is not None}
    return ObservationBundle.now(source='ebook-selection' if selected else 'ebook-page', target=_text(target, 'target'),
        valid=bool(body), text=body, metadata=metadata)


class ContentChangeTracker:
    """Deduplicate observations and reject late results from an older target."""
    def __init__(self):
        self._latest = {}

    def accept(self, observation):
        if not isinstance(observation, ObservationBundle):
            raise TypeError('observation must be ObservationBundle')
        key = (observation.source, observation.target)
        content = {'text': observation.text, 'image': observation.image,
                   'valid': observation.valid,
                   'metadata': {key:value for key,value in observation.metadata.items()
                                if key not in ('visual_observed_at', 'text_observed_at', 'danmaku')}}
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        previous = self._latest.get(key)
        if previous and observation.observed_at < previous['at']:
            return {'accepted': False, 'changed': False, 'reason': 'stale observation', 'digest': digest}
        changed = previous is None or previous['digest'] != digest
        self._latest[key] = {'at': observation.observed_at, 'digest': digest}
        return {'accepted': True, 'changed': changed, 'digest': digest}
