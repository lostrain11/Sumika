"""Compatibility exports for the host-neutral quality-routing selection core."""

from quality_routing.selection import (
    FixedEvaluationSample,
    QualityPrior,
    SELECTION_SCHEMA,
    SelectionCohort,
    SelectionEvidenceStore,
    SelectionMetadataStore,
    metadata_identifier,
    qualify_candidate,
    resolve_binding,
)

__all__ = [
    "FixedEvaluationSample",
    "QualityPrior",
    "SELECTION_SCHEMA",
    "SelectionCohort",
    "SelectionEvidenceStore",
    "SelectionMetadataStore",
    "metadata_identifier",
    "qualify_candidate",
    "resolve_binding",
]
