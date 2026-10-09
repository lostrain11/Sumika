"""Cooperative cancellation using HTTPX async transport for role requests."""
from contextlib import contextmanager
from contextvars import ContextVar
import asyncio
import io
import threading
import urllib.request
import urllib.error

_CURRENT = ContextVar('sumika_model_cancellation', default=None)


def _trust_context():
    opener = urllib.request._opener
    return next((handler._context for handler in getattr(opener, 'handlers', ())
                 if isinstance(handler, urllib.request.HTTPSHandler)), None)


def model_events(request, *, timeout, on_event):
    """Decode provider SSE with the established parser and cancel its transport."""
    token = _CURRENT.get() or CancellationToken()
    async def consume():
        import httpx
        from httpx_sse import EventSource
        loop, task = asyncio.get_running_loop(), asyncio.current_task()
        def cancel_task():
            try: loop.call_soon_threadsafe(task.cancel)
            except RuntimeError: pass
        remove = token.register(cancel_task)
        try:
            token.check()
            context = _trust_context()
            async with httpx.AsyncClient(verify=context if context is not None else True,
                                         timeout=timeout, follow_redirects=True) as client:
                async with client.stream(request.get_method(), request.full_url,
                    content=request.data, headers=dict(request.header_items())) as response:
                    if response.status_code >= 400:
                        raise urllib.error.HTTPError(request.full_url, response.status_code,
                            response.reason_phrase, response.headers, io.BytesIO(await response.aread()))
                    async for event in EventSource(response).aiter_sse():
                        token.check()
                        if on_event(event.data) is False:
                            break
                    token.check()
        except asyncio.CancelledError:
            raise RequestCancelled('model stream cancelled locally; remote outcome unknown') from None
        except httpx.HTTPError as error:
            raise urllib.error.URLError(type(error).__name__) from error
        finally:
            remove()
    asyncio.run(consume())


class RequestCancelled(RuntimeError):
    pass


class CancellationToken:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancelled = False
        self._callbacks = set()

    def check(self):
        with self._lock:
            if self._cancelled:
                raise RequestCancelled('model request cancelled locally; remote outcome unknown')

    def cancel(self):
        with self._lock:
            self._cancelled = True
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            callback()

    def register(self, callback):
        with self._lock:
            cancelled = self._cancelled
            if not cancelled:
                self._callbacks.add(callback)
        if cancelled:
            callback()
        return lambda: self._unregister(callback)

    def _unregister(self, callback):
        with self._lock:
            self._callbacks.discard(callback)

    @contextmanager
    def activate(self):
        reset = _CURRENT.set(self)
        try:
            self.check()
            yield
        finally:
            _CURRENT.reset(reset)


@contextmanager
def model_response(request, *, timeout):
    token = _CURRENT.get()
    if token is None:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield response
        return
    token.check()
    # Preserve the configured HTTPS trust context (including isolated fixtures).
    context = _trust_context()
    async def fetch():
        import httpx
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        def cancel_task():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # The completed request may already have closed its loop.
        remove = token.register(cancel_task)
        try:
            token.check()
            async with httpx.AsyncClient(verify=context if context is not None else True,
                                         timeout=timeout, follow_redirects=True) as client:
                response = await client.request(request.get_method(), request.full_url,
                    content=request.data, headers=dict(request.header_items()))
                token.check()
                if response.status_code >= 400:
                    raise urllib.error.HTTPError(request.full_url, response.status_code,
                        response.reason_phrase, response.headers, io.BytesIO(response.content))
                return response.content
        except asyncio.CancelledError:
            raise RequestCancelled('model request cancelled locally; remote outcome unknown') from None
        except httpx.HTTPError as error:
            raise urllib.error.URLError(type(error).__name__) from error
        finally:
            remove()
    try:
        content = asyncio.run(fetch())
        with io.BytesIO(content) as response:
            token.check()
            yield response
            token.check()
    except Exception:
        token.check()
        raise
