"""Route evidence contract and resolver.

This import module keeps the ``route-evidence/v1`` API discoverable for
adapters and plugins while the implementation remains shared with the route
supervisor.
"""

from .supervisor import (
    DynamicRouteEvidence,
    EvidenceResolver,
    RouteEvidence,
    RouteEvidenceV1,
)

ROUTE_EVIDENCE_SCHEMA = "route-evidence/v1"

__all__ = [
    "ROUTE_EVIDENCE_SCHEMA",
    "DynamicRouteEvidence",
    "RouteEvidence",
    "RouteEvidenceV1",
    "EvidenceResolver",
]
