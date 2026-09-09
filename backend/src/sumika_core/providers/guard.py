from __future__ import annotations


class RequestNotSent(ValueError):
    """A host preflight rejected the request before any provider submission."""


class GuardedProvider:
    def __init__(self, provider, recheck):
        self.provider = provider
        self.recheck = recheck

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def stream(self, request):
        checked_request = self.recheck(request)
        yield from self.provider.stream(checked_request or request)
