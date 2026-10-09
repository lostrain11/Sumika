"""Read current HTML video context through an explicitly bound BrowserSkill tab.

BrowserSkill (including reviewed upstream head) only evaluates Agent Window
tabs. Validation is shared with the opt-in passive normal-browser transport.
"""
from datetime import datetime
import json
import math
import base64
from pathlib import Path

from .contracts import ObservationBundle


def collect_browser_video(client, site, *, capture_frame=False):
    if type(capture_frame) is not bool:
        raise ValueError('capture_frame must be boolean')
    bridge = client.bound_bridge(site)
    bridge._authorized_session(site, 'read')
    tab = bridge._tab(site)
    scheme, host, port = bridge._expected(site)
    default_port = 443 if scheme == 'https' else 80
    origin = f'{scheme}://{host}' + (f':{port}' if port != default_port else '')
    script = Path(__file__).with_name('browser_video_snapshot.js').read_text(encoding='utf8')
    result = bridge._run(['evaluate', '--json', '--session', bridge.session_id, '--tab-id', tab,
                          '(' + script + ')(' + json.dumps({'origin': origin, 'capture_frame': capture_frame}) + ')'])
    bridge._authorized_session(site, 'read')
    bridge._tab(site)
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise RuntimeError('browser video snapshot unavailable')
    value = result.get('value')
    if not isinstance(value, dict) or value.get('ok') is not True:
        raise RuntimeError('browser video unavailable: ' + str(value.get('reason') if isinstance(value, dict) else 'invalid snapshot'))
    return browser_video_observation(value, origin=origin,
        target=f'browser:{bridge.session_id}:tab:{bridge.tab_id}', capture_frame=capture_frame)


def browser_video_observation(value, *, origin, target, capture_frame=False):
    """Validate the fixed collector output independently of its transport."""
    from urllib.parse import urlsplit
    if not isinstance(value, dict) or value.get('ok') is not True:
        raise ValueError('browser video snapshot unavailable')
    if type(capture_frame) is not bool:
        raise ValueError('capture_frame must be boolean')
    if len(json.dumps(value).encode('utf8')) > 500_000:
        raise ValueError('browser video snapshot exceeds budget')
    text, media_time = value.get('subtitles'), value.get('media_time_seconds')
    if not isinstance(text, str) or len(text) > 12000:
        raise ValueError('invalid browser subtitles')
    if type(media_time) not in (int, float) or not math.isfinite(media_time) or media_time < 0:
        raise ValueError('invalid browser media time')
    url = value.get('url')
    if not isinstance(url, str):
        raise ValueError('invalid browser URL')
    parsed = urlsplit(url)
    expected = urlsplit(origin)
    def origin_parts(part):
        return part.scheme, part.hostname, part.port or (443 if part.scheme == 'https' else 80)
    if parsed.username or parsed.password or origin_parts(parsed) != origin_parts(expected):
        raise PermissionError('snapshot origin changed')
    identity = value.get('media_identity')
    if identity is not None:
        if (not isinstance(identity, dict) or identity.get('url') != url
                or type(identity.get('document_started_at')) not in (int, float)
                or not math.isfinite(identity['document_started_at'])
                or identity['document_started_at'] <= 0
                or not isinstance(identity.get('source_fingerprint'), str)
                or not 1 <= len(identity['source_fingerprint']) <= 8
                or any(char not in '0123456789abcdef' for char in identity['source_fingerprint'])
                or ('part' in identity and (type(identity['part']) is not int or not 1 <= identity['part'] <= 999999))):
            raise ValueError('invalid browser media identity')
        for field, minimum in (('media_instance', 1), ('timeline_revision', 0)):
            if field in identity and (type(identity[field]) is not int
                                     or not minimum <= identity[field] <= 9007199254740991):
                raise ValueError('invalid browser media timeline')
    seeking = value.get('seeking', False)
    if type(seeking) is not bool:
        raise ValueError('invalid browser seeking state')
    playback_rate = value.get('playback_rate', 1.0)
    if (type(playback_rate) not in (int, float) or not math.isfinite(playback_rate)
            or not 0 < playback_rate <= 16):
        raise ValueError('invalid browser playback rate')
    observed_at = datetime.fromisoformat(value['observed_at'].replace('Z', '+00:00'))
    danmaku = value.get('danmaku', [])
    if not isinstance(danmaku, list) or len(danmaku) > 24:
        raise ValueError('invalid browser danmaku')
    normalized_danmaku = []
    for item in danmaku:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            raise ValueError('invalid browser danmaku item')
        item_time = item.get('media_time_seconds')
        if (not item['text'].strip() or len(item['text']) > 240
                or type(item_time) not in (int, float) or not math.isfinite(item_time)
                or item_time < 0):
            raise ValueError('invalid browser danmaku item')
        normalized_danmaku.append({'text': item['text'].strip(),
                                  'media_time_seconds': item_time})
    image = value.get('image')
    if image is not None:
        if (not capture_frame or not isinstance(image, dict)
                or set(image) != {'media_type', 'data_base64'}
                or image['media_type'] != 'image/jpeg'
                or not isinstance(image['data_base64'], str)
                or not 1 <= len(image['data_base64']) <= 400000):
            raise ValueError('invalid browser video frame')
        try:
            raw = base64.b64decode(image['data_base64'], validate=True)
        except ValueError as error:
            raise ValueError('invalid browser video frame') from error
        if not raw.startswith(b'\xff\xd8') or not raw.endswith(b'\xff\xd9'):
            raise ValueError('invalid browser JPEG frame')
    return ObservationBundle(observed_at, 'video-frame' if capture_frame else 'video-subtitle',
        target, not seeking and bool(text.strip() or image),
        '' if seeking else text, image=None if seeking else image,
        media_time_seconds=media_time,
        metadata={**{key: value.get(key) for key in ('url', 'title', 'paused', 'ended', 'playback_rate', 'ready_state', 'reason', 'frame_status', 'media_identity', 'seeking')},
                  'danmaku': normalized_danmaku})
