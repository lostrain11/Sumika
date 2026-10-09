"""Opt-in push transport for the fixed collector; never executes page commands.

Grants are ephemeral and bind one extension, original tab and Bilibili origin.
This adapter does not prove an OS process/window binding or a player audio clock.
"""
from datetime import datetime, timezone
import hmac
import hashlib
import json
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

from .browser_video import browser_video_observation


class PassiveBrowserConnection:
    def __init__(self, publish, clear, *, clock=time.monotonic, utcnow=None, watchdog=True):
        self.publish, self.clear = publish, clear
        self.clock = clock
        self.utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._grant = None
        self._watchdog_enabled = watchdog
        self._wake = None
        self._requests = {}

    def _prune_requests(self):
        for key, request in tuple(self._requests.items()):
            if self.clock() >= request['expires']:
                del self._requests[key]

    @staticmethod
    def _extension_id(extension_origin):
        if not isinstance(extension_origin, str) or re.fullmatch(
                r'chrome-extension://[a-p]{32}', extension_origin) is None:
            raise PermissionError('browser extension origin required')
        return extension_origin.removeprefix('chrome-extension://')

    def request_connection(self, extension_origin, payload):
        """Register metadata only: this operation never grants collection."""
        extension = self._extension_id(extension_origin)
        if not isinstance(payload, dict) or set(payload) != {'tab_id', 'origin', 'title', 'url'}:
            raise ValueError('connection request metadata required')
        self.validate_selection(dict(consent=True, extension_id=extension,
            tab_id=payload['tab_id'], origin=payload['origin'], capture_frame=False))
        title, url = payload['title'], payload['url']
        if not isinstance(title, str) or len(title) > 512 or any(ord(c) < 32 for c in title):
            raise ValueError('bounded tab title required')
        if not isinstance(url, str) or len(url) > 512:
            raise ValueError('bounded video URL required')
        parsed = urlsplit(url)
        if (parsed.scheme + '://' + parsed.netloc != payload['origin']
                or parsed.username or parsed.password or parsed.fragment
                or re.fullmatch(r'/video/[A-Za-z0-9]+/?', parsed.path) is None
                or parsed.query and re.fullmatch(r'p=[1-9][0-9]{0,5}', parsed.query) is None):
            raise ValueError('Bilibili video URL required without tracking parameters')
        with self._lock:
            self._prune_requests()
            if len(self._requests) >= 8:
                raise ValueError('too many pending browser requests')
            identifier = secrets.token_hex(16)
            request = dict(payload, extension_id=extension, request_id=identifier,
                receipt=secrets.token_urlsafe(32), expires=self.clock()+120,
                state='pending', grant_token=None)
            self._requests[identifier] = request
            return {'request_id':identifier, 'receipt':request['receipt'],
                    'status':'pending', 'expires_in_seconds':120}

    def pending_connections(self):
        with self._lock:
            self._prune_requests()
            return [{key:request[key] for key in ('request_id','extension_id','tab_id',
                'origin','title','url')} for request in self._requests.values()
                if request['state'] == 'pending']

    def connection_receipt(self, extension_origin, payload, *, cancel=False):
        extension = self._extension_id(extension_origin)
        if not isinstance(payload, dict) or set(payload) != {'request_id','receipt'}:
            raise ValueError('connection receipt required')
        if not isinstance(payload['request_id'], str):
            raise ValueError('connection request id required')
        with self._lock:
            self._expire()
            self._prune_requests()
            request = self._requests.get(payload['request_id'])
            receipt = payload['receipt']
            if (request is None or request['extension_id'] != extension
                    or not isinstance(receipt, str)
                    or not hmac.compare_digest(receipt, request['receipt'])):
                raise PermissionError('browser connection request unavailable')
            if cancel:
                if self._grant is not None and self._grant['token'] == request['grant_token']:
                    self.stop()
                else:
                    del self._requests[request['request_id']]
                return {'status':'stopped'}
            if request['state'] == 'pending':
                return {'status':'pending'}
            if self._grant is None or self._grant['token'] != request['grant_token']:
                raise PermissionError('browser connection grant revoked')
            if self._grant['paused']:
                return {'status':'paused'}
            return {'status':'approved', 'grant':self._configuration()}

    def approve_connection(self, payload, *, before_start):
        if not isinstance(payload, dict) or set(payload) not in (
                {'action','request_id','consent','capture_frame'},
                {'action','request_id','consent','capture_frame','audio'}):
            raise ValueError('explicit connection approval required')
        if not isinstance(payload['request_id'], str):
            raise ValueError('connection request id required')
        audio = payload.get('audio', False)
        if type(audio) is not bool:
            raise ValueError('browser audio consent must be boolean')
        with self._lock:
            self._prune_requests()
            request = self._requests.get(payload['request_id'])
            if request is None or request['state'] != 'pending':
                raise PermissionError('pending connection request unavailable')
            selection = {key:request[key] for key in ('extension_id','tab_id','origin')}
            selection.update(consent=payload['consent'], capture_frame=payload['capture_frame'],
                             audio=audio)
            self.validate_selection(selection)
            before_start()  # Revoke old perception before issuing a new grant.
            if self.clock() >= request['expires']:
                raise PermissionError('browser connection request expired during approval')
            grant = self.start(selection)
            self._grant['approved_url'] = request['url']
            request.update(state='approved', grant_token=grant['token'], expires=self._grant['expires'])
            self._requests[request['request_id']] = request
            return {'status':'approved', 'target':grant['target']}

    @staticmethod
    def validate_selection(payload):
        if not isinstance(payload, dict) or payload.get('consent') is not True:
            raise PermissionError('explicit passive browser consent required')
        extension = payload.get('extension_id')
        if not isinstance(extension, str) or re.fullmatch('[a-p]{32}', extension) is None:
            raise ValueError('invalid browser extension id')
        tab = payload.get('tab_id')
        if type(tab) is not int or not 0 <= tab <= 2147483647:
            raise ValueError('invalid original browser tab')
        origin = payload.get('origin')
        if origin not in ('https://www.bilibili.com', 'https://bilibili.com'):
            raise ValueError('unsupported passive browser origin')
        capture = payload.get('capture_frame', True)
        if type(capture) is not bool:
            raise ValueError('capture_frame must be boolean')
        audio = payload.get('audio', False)
        if type(audio) is not bool:
            raise ValueError('browser audio consent must be boolean')
        return extension, tab, origin, capture, audio

    def start(self, payload):
        extension, tab, origin, capture, audio = self.validate_selection(payload)
        with self._lock:
            if self._grant is not None:
                self.stop()
            self._grant = dict(token=secrets.token_urlsafe(32), extension_id=extension,
                tab_id=tab, origin=origin, capture_frame=capture, audio=audio,
                audio_epoch=secrets.token_hex(8) if audio else None,
                target=f'browser-passive:{secrets.token_hex(16)}:tab:{tab}',
                expires=self.clock()+1800, sequence=-1, observed_at=None, received=None, signature=None, paused=False)
            if self._watchdog_enabled:
                wake = self._wake = threading.Event()
                threading.Thread(target=self._watch, args=(wake,),daemon=True,
                                 name='SumikaPassiveBrowserExpiry').start()
            return self._configuration()

    def audio_grant(self):
        """Authorization view for the bounded browser audio transport."""
        with self._lock:
            self._expire()
            grant = self._grant
            if grant is None or grant['paused'] or not grant['audio']:
                return None
            return {key: grant[key] for key in ('token', 'extension_id', 'tab_id',
                                                'origin', 'audio', 'audio_epoch')}

    def rotate_audio_epoch(self, token, extension_origin):
        """Mint a fresh audio epoch after seek/rate/pause invalidated capture.

        The user's connection consent stands; old transcripts stay fenced by
        the epoch change, so the extension restarts capture with clean state.
        """
        with self._lock:
            self._expire()
            grant = self._grant
            if (grant is None or grant['paused'] or not grant['audio']
                    or not isinstance(token, str)
                    or not hmac.compare_digest(token, grant['token'])
                    or extension_origin != 'chrome-extension://' + grant['extension_id']):
                raise PermissionError('browser audio grant unavailable')
            grant['audio_epoch'] = secrets.token_hex(8)
            return {'audio_epoch': grant['audio_epoch']}

    def _watch(self, wake):
        while not wake.wait(0.5):
            with self._lock:
                if wake is not self._wake:
                    return
                self._expire()

    def _configuration(self):
        grant = self._grant
        return {key: grant[key] for key in ('token', 'extension_id', 'tab_id', 'origin',
            'capture_frame', 'audio', 'audio_epoch', 'target')} | {'expires_in_seconds': max(0, grant['expires']-self.clock()),
                                         'approved_url':grant.get('approved_url')}

    def status(self):
        with self._lock:
            self._expire()
            if self._grant is None:
                return {'status':'stopped'}
            return {'status':'paused' if self._grant['paused'] else 'running',
                    'target':self._grant['target']}

    def _expire(self):
        if self._grant is not None:
            grant = self._grant
            if (self.clock() >= grant['expires'] or (not grant['paused']
                    and grant['received'] is not None and self.clock()-grant['received'] >= 10)):
                self.stop()

    def pause(self):
        with self._lock:
            self._expire()
            if self._grant is not None:
                self._grant['paused'] = True
                self._grant['signature'] = None
                self.clear()
            return self.status()

    def resume(self):
        with self._lock:
            self._expire()
            if self._grant is None:
                raise PermissionError('passive browser consent expired or revoked')
            # Old queued packets remain invalid after resume; a fresh token and
            # audio epoch fence transcripts from before the pause.
            old_token = self._grant['token']
            self._grant.update(token=secrets.token_urlsafe(32), paused=False,
                               sequence=-1, observed_at=None, received=None, signature=None)
            if self._grant['audio']:
                self._grant['audio_epoch'] = secrets.token_hex(8)
            for request in self._requests.values():
                if request['grant_token'] == old_token:
                    request['grant_token'] = self._grant['token']
            return self._configuration()

    def stop(self):
        with self._lock:
            self._requests.clear()
            existed = self._grant is not None
            self._grant = None
            if self._wake is not None:
                self._wake.set()
                self._wake = None
            if existed:
                self.clear()
            return {'status':'stopped'}

    def receive(self, token, extension_origin, payload):
        with self._lock:
            self._expire()
            grant = self._grant
            if (grant is None or grant['paused'] or not isinstance(token, str)
                    or not hmac.compare_digest(token, grant['token'])
                    or extension_origin != 'chrome-extension://' + grant['extension_id']):
                raise PermissionError('passive browser grant unavailable')
            if not isinstance(payload, dict):
                raise ValueError('invalid passive browser packet')
            if set(payload) not in ({'tab_id','sequence','snapshot'}, {'tab_id','sequence','heartbeat'}):
                raise ValueError('invalid passive browser packet')
            sequence = payload['sequence']
            if (type(payload['tab_id']) is not int or payload['tab_id'] != grant['tab_id']
                    or type(sequence) is not int or not grant['sequence'] < sequence <= 9007199254740991):
                raise PermissionError('wrong tab or replayed passive browser packet')
            if set(payload) == {'tab_id', 'sequence', 'heartbeat'}:
                if payload['heartbeat'] is not True:
                    raise ValueError('invalid passive browser heartbeat')
                if grant.get('observed_at') is None:
                    raise ValueError('heartbeat requires an accepted observation')
                grant.update(sequence=sequence, received=self.clock())
                return {'status': 'heartbeat', 'target': grant['target'],
                        'sequence': sequence, 'heartbeat': True}
            if set(payload) != {'tab_id','sequence','snapshot'}:
                raise ValueError('invalid passive browser packet')
            bundle = browser_video_observation(payload['snapshot'], origin=grant['origin'],
                target=grant['target'], capture_frame=grant['capture_frame'])
            snapshot = payload['snapshot']
            if (bundle.metadata['media_identity'] is None
                    or any(type(snapshot.get(key)) is not bool for key in ('paused','ended','seeking'))
                    or type(snapshot.get('ready_state')) is not int
                    or not 0 <= snapshot['ready_state'] <= 4
                    or not isinstance(snapshot.get('title'), str) or len(snapshot['title']) > 512):
                raise ValueError('incomplete passive video state')
            parsed = urlsplit(bundle.metadata['url'])
            if grant.get('approved_url') is not None and bundle.metadata['url'] != grant['approved_url']:
                raise PermissionError('approved video changed; reconnect required')
            if (parsed.username or parsed.password or parsed.fragment
                    or not parsed.path.startswith('/video/')
                    or (parsed.query and re.fullmatch('p=[1-9][0-9]{0,5}',parsed.query) is None)):
                raise ValueError('invalid passive video source')
            age = (self.utcnow()-bundle.observed_at).total_seconds()
            if (not -2 <= age <= 5 or (grant['observed_at'] is not None
                    and bundle.observed_at < grant['observed_at'])):
                raise ValueError('stale passive browser observation')
            grant.update(sequence=sequence, observed_at=bundle.observed_at, received=self.clock())
            signature = hashlib.sha256(json.dumps({
                'identity': bundle.metadata.get('media_identity'),
                'text': bundle.text,
                'image': (bundle.image or {}).get('data_base64') if bundle.image else None,
                'danmaku': bundle.metadata.get('danmaku', []),
                'paused': bundle.metadata.get('paused'),
                'ended': bundle.metadata.get('ended'),
                'seeking': bundle.metadata.get('seeking'),
            }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')).hexdigest()
            if grant.get('signature') == signature:
                return {'status': 'unchanged', 'target': grant['target'],
                        'sequence': sequence, 'heartbeat': True}
            # Only the normalized observation is published. The page cannot set
            # target, arbitrary metadata, model commands or collection consent.
            result = self.publish(bundle)
            if isinstance(result, dict) and result.get('status') != 'rejected':
                grant['signature'] = signature
            return result
