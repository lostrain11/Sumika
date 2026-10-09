"""Segmented, cancellable TTS playback over the existing local player."""
import asyncio
import re
import inspect


def split_speech(text, *, max_chars=180):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('speech text required')
    if type(max_chars) is not int or not 20 <= max_chars <= 1000:
        raise ValueError('invalid speech segment limit')
    chunks = []
    for paragraph in re.split(r'\n+', text.strip()):
        words = re.split(r'(?<=[。！？；.!?;])\s*', paragraph)
        for word in words:
            word = word.strip()
            while len(word) > max_chars:
                cut = word.rfind(' ', 0, max_chars + 1)
                if cut < 20:
                    cut = max_chars
                chunks.append(word[:cut].strip())
                word = word[cut:].strip()
            if word:
                chunks.append(word)
    return chunks


class SegmentedPlayback:
    """Call one async player per segment and fence old playback by epoch."""

    def __init__(self, play_segment, stop_playback, *, max_chars=180, on_event=None):
        if not callable(play_segment) or not callable(stop_playback):
            raise TypeError('play and stop providers required')
        self.play_segment = play_segment
        self.stop_playback = stop_playback
        self.max_chars = max_chars
        self.on_event = on_event or (lambda event, detail: None)
        self._epoch = 0
        self._task = None

    async def _notify(self, event, detail):
        result = self.on_event(event, detail)
        if inspect.isawaitable(result):
            await result

    async def __call__(self, text):
        if self._task is not None:
            await self.cancel()
        epoch = self._epoch
        segments = split_speech(text, max_chars=self.max_chars)
        self._task = asyncio.current_task()
        try:
            for index, segment in enumerate(segments):
                if epoch != self._epoch:
                    raise asyncio.CancelledError
                await self._notify('segment_started', {'index': index, 'count': len(segments)})
                if epoch != self._epoch:
                    raise asyncio.CancelledError
                await self.play_segment(segment)
                if epoch != self._epoch:
                    raise asyncio.CancelledError
                await self._notify('segment_ended', {'index': index, 'count': len(segments)})
        except BaseException:
            await self.stop_playback()
            raise
        finally:
            if self._task is asyncio.current_task():
                self._task = None

    async def cancel(self):
        self._epoch += 1
        task = self._task
        self._task = None
        try:
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            await self.stop_playback()

    async def stream(self, deltas, *, on_start=None):
        """Play completed sentences while the model continues producing deltas."""
        if self._task is not None:
            await self.cancel()
        epoch = self._epoch
        self._task = asyncio.current_task()
        buffer, index = '', 0
        started = False

        async def play(text):
            nonlocal index, started
            if epoch != self._epoch:
                raise asyncio.CancelledError
            if not started:
                started = True
                if on_start is not None:
                    await on_start()
            await self._notify('segment_started', {'index': index, 'count': None})
            if epoch != self._epoch:
                raise asyncio.CancelledError
            await self.play_segment(text)
            if epoch != self._epoch:
                raise asyncio.CancelledError
            await self._notify('segment_ended', {'index': index, 'count': None})
            index += 1

        try:
            async for delta in deltas:
                if not isinstance(delta, str) or len(delta) > 64000:
                    raise ValueError('invalid speech delta')
                buffer += delta
                while buffer:
                    boundary = re.search(r'[。！？；.!?;\n]', buffer)
                    if boundary and boundary.end() <= self.max_chars:
                        cut = boundary.end()
                    elif len(buffer) >= self.max_chars:
                        cut = self.max_chars
                    else:
                        break
                    segment, buffer = buffer[:cut].strip(), buffer[cut:]
                    if segment:
                        await play(segment)
            if buffer.strip():
                await play(buffer.strip())
        except BaseException:
            await self.stop_playback()
            raise
        finally:
            close = getattr(deltas, 'aclose', None)
            if close is not None:
                await close()
            if self._task is asyncio.current_task():
                self._task = None
