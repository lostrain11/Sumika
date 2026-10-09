"""Small bounded WebVTT cue parser for player adapters."""
import re
from html import unescape

_TIME = re.compile(r"^(\d{2,}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})\s+-->\s+(\d{2,}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})")
_TAG = re.compile(r"<[^>]+>")


def _seconds(value):
    value = value.replace(',', '.')
    parts = [float(part) for part in value.split(':')]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    hours, minutes, seconds = parts
    return hours * 3600 + minutes * 60 + seconds


def cues(text, *, at_seconds=None, max_chars=12000):
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ValueError('invalid WebVTT text')
    rows = []
    block = []
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n') + ['']:
        if line.strip():
            block.append(line.strip())
            continue
        if block:
            timing = next(((index, _TIME.match(item)) for index, item in enumerate(block)
                           if _TIME.match(item)), None)
            if timing:
                index, match = timing
                start, end = _seconds(match.group(1)), _seconds(match.group(2))
                body = ' '.join(block[index + 1:])
                body = unescape(_TAG.sub('', body)).strip()
                if body and (at_seconds is None or start <= at_seconds <= end):
                    rows.append({'start': start, 'end': end, 'text': body})
        block = []
    joined = '\n'.join(row['text'] for row in rows)
    return joined[:max_chars], rows
