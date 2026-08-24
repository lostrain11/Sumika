"""Deterministic test-only provider implementations.

These fixtures are intentionally outside the installable ``sumika_core``
package so the production provider catalog can never present a fake backend.
"""

from .providers import (
    FakeASRProvider,
    FakeMemoryProvider,
    FakeProvider,
    FakeTTSProvider,
    FakeVADProvider,
    FakeVisionProvider,
)

__all__ = [
    "FakeASRProvider",
    "FakeMemoryProvider",
    "FakeProvider",
    "FakeTTSProvider",
    "FakeVADProvider",
    "FakeVisionProvider",
]
