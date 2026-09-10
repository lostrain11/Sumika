from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .contracts import Candidate, Node, Quote, RoutingError, amount, count, identifier
from .costs import cost_order
from .privacy import looks_like_secret_text


SELECTION_SCHEMA = "quality-routing/selection/v1"
_PURPOSES = {"leader", "role"}


class SelectionMetadataStore(Protocol):
    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...


def metadata_identifier(value: Any) -> str:
    identifier(value)
    if ".." in value or looks_like_secret_text(value):
        raise RoutingError("invalid selection metadata identifier")
    return value


def _score(value: Any) -> Decimal:
    result = amount(value)
    if result > 1:
        raise RoutingError("quality score must be between zero and one")
    return result


def _model_version(value: Any) -> str:
    metadata_identifier(value)
    if value.lower() in {"unknown", "unspecified", "auto"}:
        raise RoutingError("explicit model version required")
    return value


def _cohort_identity(value: Any) -> None:
    if value.purpose not in _PURPOSES:
        raise RoutingError("invalid selection purpose")
    metadata_identifier(value.cohort_id)
    metadata_identifier(value.cohort_version)


def _evidence_identity(value: Any) -> None:
    _cohort_identity(value)
    metadata_identifier(value.candidate_id)
    _model_version(value.model_version)
    for timestamp in (value.observed_at, value.expires_at):
        if type(timestamp) not in {int, float} or not math.isfinite(timestamp) or timestamp < 0:
            raise RoutingError("invalid selection evidence timestamp")
    if value.expires_at <= value.observed_at:
        raise RoutingError("selection evidence must have a positive lifetime")
    object.__setattr__(value, "score", _score(value.score))


def _record(value: Any) -> dict[str, Any]:
    return {key: str(item) if isinstance(item, Decimal) else item for key, item in asdict(value).items()}


@dataclass(frozen=True)
class SelectionCohort:
    """Host-defined fixed evaluation suite, score floor and common cost workload."""

    purpose: str
    cohort_id: str
    cohort_version: str
    minimum_score: Decimal
    input_tokens: int = 4000
    output_tokens: int = 1000
    minimum_samples: int = 3

    def __post_init__(self) -> None:
        _cohort_identity(self)
        object.__setattr__(self, "minimum_score", _score(self.minimum_score))
        if count(self.minimum_samples, 4096) < 3:
            raise RoutingError("at least three successful fixed samples are required")
        if not count(self.input_tokens) or not count(self.output_tokens):
            raise RoutingError("selection cohort requires positive token bounds")


@dataclass(frozen=True)
class QualityPrior:
    """Host-imported ranking hint, never authorization or SDK quality equivalence."""

    candidate_id: str
    model_version: str
    purpose: str
    cohort_id: str
    cohort_version: str
    source_id: str
    source_version: str
    score: Decimal
    observed_at: float
    expires_at: float

    def __post_init__(self) -> None:
        _evidence_identity(self)
        metadata_identifier(self.source_id)
        metadata_identifier(self.source_version)


@dataclass(frozen=True)
class FixedEvaluationSample:
    """Host-scored fixed evaluation metadata; sample IDs are unique per assistant."""

    sample_id: str
    candidate_id: str
    model_version: str
    purpose: str
    cohort_id: str
    cohort_version: str
    score: Decimal
    successful: bool
    observed_at: float
    expires_at: float
    applied_reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        _evidence_identity(self)
        metadata_identifier(self.sample_id)
        if type(self.successful) is not bool:
            raise RoutingError("fixed sample success must be boolean")
        if self.applied_reasoning_effort is not None:
            metadata_identifier(self.applied_reasoning_effort)


class SelectionEvidenceStore:
    """Metadata-only evidence persistence over a narrow host-supplied store."""

    def __init__(self, storage: SelectionMetadataStore, lock: Any = None) -> None:
        self.storage = storage
        self._lock = lock if lock is not None else threading.RLock()

    def _key(self, assistant_id: str) -> str:
        return SELECTION_SCHEMA + ":" + metadata_identifier(assistant_id)

    def read(self, assistant_id: str) -> tuple[dict[str, SelectionCohort], tuple[QualityPrior, ...], tuple[FixedEvaluationSample, ...]]:
        with self._lock:
            raw = self.storage.get_meta(self._key(assistant_id))
            if raw is None:
                return {}, (), ()
            try:
                data = json.loads(raw)
                if set(data) != {"schema", "cohorts", "priors", "samples"} or data["schema"] != SELECTION_SCHEMA:
                    raise RoutingError("invalid selection evidence schema")
                if any(not isinstance(data[key], list) for key in ("cohorts", "priors", "samples")):
                    raise RoutingError("invalid selection evidence collections")
                if len(data["cohorts"]) > 2 or len(data["priors"]) > 1024 or len(data["samples"]) > 4096:
                    raise RoutingError("selection evidence capacity exceeded")
                cohorts = [SelectionCohort(**row) for row in data["cohorts"]]
                priors = tuple(QualityPrior(**row) for row in data["priors"])
                samples = tuple(FixedEvaluationSample(**row) for row in data["samples"])
                if len({row.purpose for row in cohorts}) != len(cohorts) or len({row.sample_id for row in samples}) != len(samples):
                    raise RoutingError("duplicate selection evidence")
                return {row.purpose: row for row in cohorts}, priors, samples
            except (TypeError, ValueError, KeyError):
                raise RoutingError("invalid stored selection evidence") from None

    def _save(self, assistant_id: str, cohorts: Mapping[str, SelectionCohort],
              priors: Sequence[QualityPrior], samples: Sequence[FixedEvaluationSample]) -> None:
        if len(priors) > 1024 or len(samples) > 4096:
            raise RoutingError("selection evidence capacity exceeded")
        data = {"schema": SELECTION_SCHEMA, "cohorts": [_record(cohorts[key]) for key in sorted(cohorts)],
                "priors": [_record(row) for row in priors], "samples": [_record(row) for row in samples]}
        self.storage.set_meta(self._key(assistant_id), json.dumps(data, allow_nan=False, sort_keys=True))

    def register_cohort(self, assistant_id: str, cohort: SelectionCohort) -> None:
        if type(cohort) is not SelectionCohort:
            raise RoutingError("host selection cohort must use the typed contract")
        with self._lock:
            cohorts, priors, samples = self.read(assistant_id)
            previous = cohorts.get(cohort.purpose)
            if previous and (previous.cohort_id, previous.cohort_version) == (cohort.cohort_id, cohort.cohort_version) and previous != cohort:
                raise RoutingError("changed cohort requires a new version")
            cohorts[cohort.purpose] = cohort
            self._save(assistant_id, cohorts, priors, samples)

    def register_prior(self, assistant_id: str, prior: QualityPrior) -> None:
        if type(prior) is not QualityPrior:
            raise RoutingError("host quality prior must use the typed contract")
        with self._lock:
            cohorts, priors, samples = self.read(assistant_id)
            key = lambda row: (row.candidate_id, row.model_version, row.purpose, row.cohort_id, row.cohort_version, row.source_id)
            self._save(assistant_id, cohorts, [row for row in priors if key(row) != key(prior)] + [prior], samples)

    def record_sample(self, assistant_id: str, sample: FixedEvaluationSample) -> bool:
        if type(sample) is not FixedEvaluationSample:
            raise RoutingError("host fixed sample must use the typed contract")
        with self._lock:
            cohorts, priors, samples = self.read(assistant_id)
            previous = next((row for row in samples if row.sample_id == sample.sample_id), None)
            if previous is not None:
                if previous != sample:
                    raise RoutingError("sample ID already records different evidence")
                return False
            self._save(assistant_id, cohorts, priors, (*samples, sample))
            return True

    def qualification(self, assistant_id: str, candidate_id: str, *, model_version: str | None,
                      purpose: str = "leader", reasoning_effort: str | None = None, now: float | None = None) -> dict[str, Any]:
        """Read quality eligibility without catalog refresh, availability or authorization."""
        cohorts, priors, samples = self.read(assistant_id)
        return qualify_candidate(candidate_id, model_version, purpose, reasoning_effort, cohorts.get(purpose), priors, samples,
                                 now=time.time() if now is None else now)


def qualify_candidate(candidate_id: str, model_version: str | None, purpose: str, reasoning_effort: str | None,
                      cohort: SelectionCohort | None, priors: Sequence[QualityPrior], samples: Sequence[FixedEvaluationSample],
                      *, now: float) -> dict[str, Any]:
    """Quality-only query, usable before a host's observation routability gate."""
    metadata_identifier(candidate_id)
    if purpose not in _PURPOSES:
        raise RoutingError("invalid selection purpose")
    _base, separator, suffix = candidate_id.rpartition(":effort:")
    if separator:
        metadata_identifier(suffix)
        if reasoning_effort is not None and reasoning_effort != suffix:
            raise RoutingError("candidate ID and reasoning effort disagree")
        reasoning_effort = suffix
    elif reasoning_effort is not None:
        raise RoutingError("explicit effort requires the full candidate ID including effort")
    result: dict[str, Any] = {"authority": "quality-only", "candidate_id": candidate_id, "purpose": purpose,
                              "model_version": None, "reasoning_effort": reasoning_effort, "qualified": False,
                              "reason": "model-version-required", "successful_samples": 0}
    try:
        _model_version(model_version)
    except RoutingError:
        return result
    result["model_version"] = model_version
    if cohort is None or cohort.purpose != purpose:
        result["reason"] = "selection-cohort-missing"
        return result
    result.update(cohort_id=cohort.cohort_id, cohort_version=cohort.cohort_version)

    def matches(row: Any) -> bool:
        return (row.candidate_id == candidate_id and row.model_version == model_version
                and row.purpose == purpose and row.cohort_id == cohort.cohort_id
                and row.cohort_version == cohort.cohort_version and row.observed_at <= now < row.expires_at)

    matching = [sample for sample in samples if matches(sample)]
    if reasoning_effort is not None:
        matching = [sample for sample in matching if sample.applied_reasoning_effort == reasoning_effort
                    and sample.applied_reasoning_effort not in {"unknown", "auto"}]
    successful = sum(sample.successful for sample in matching)
    result["successful_samples"] = successful
    if successful < cohort.minimum_samples:
        result["reason"] = "successful-fixed-samples-required"
        return result
    score = sum((sample.score for sample in matching), Decimal(0)) / len(matching)
    result["score"] = str(score)
    if score < cohort.minimum_score:
        result["reason"] = "below-cohort-quality-floor"
        return result
    hints = [prior.score for prior in priors if matches(prior)]
    prior_score = sum(hints, Decimal(0)) / len(hints) if hints else None
    result.update(qualified=True, reason="qualified", prior_score=str(prior_score) if prior_score is not None else None)
    return result


def resolve_binding(purpose: str, mode: str, fixed_id: str | None, pool: Sequence[str],
                    candidates: Sequence[Candidate], model_versions: Mapping[str, str | None],
                    health_states: Mapping[str, str], cohort: SelectionCohort | None,
                    priors: Sequence[QualityPrior], samples: Sequence[FixedEvaluationSample], *, now: float) -> dict[str, Any]:
    """Rank exact identities without treating quality, price, or a suggestion as authorization."""
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    result: dict[str, Any] = {"selection_mode": mode, "candidate_id": None, "reason": "no-qualified-candidate", "candidates": []}
    if mode == "fixed":
        if fixed_id is None:
            result["reason"] = "fixed-unset"
        elif fixed_id not in by_id or not by_id[fixed_id].available or not by_id[fixed_id].authorized:
            result["reason"] = "fixed-unavailable-or-unauthorized"
        elif health_states.get(fixed_id) not in {None, "unknown", "healthy", "ready", "available"}:
            result["reason"] = "fixed-unhealthy"
        else:
            result.update(candidate_id=fixed_id, reason="fixed-configured")
        return result
    if mode != "auto" or purpose not in _PURPOSES:
        raise RoutingError("invalid binding selection mode or purpose")
    if not pool:
        result["reason"] = "candidate-pool-empty"
        return result
    if cohort is None or cohort.purpose != purpose:
        result["reason"] = "selection-cohort-missing"
        return result

    ranked = []
    for candidate_id in sorted(set(pool)):
        candidate = by_id.get(candidate_id)
        row: dict[str, Any] = {"candidate_id": candidate_id, "reason": "candidate-missing"}
        result["candidates"].append(row)
        if candidate is None:
            continue
        if not candidate.authorized or not candidate.available:
            row["reason"] = "unavailable-or-unauthorized"
            continue
        if health_states.get(candidate_id) not in {"healthy", "ready", "available"}:
            row["reason"] = "explicit-health-required"
            continue
        if "text" not in candidate.capabilities:
            row["reason"] = "text-capability-required"
            continue
        qualification = qualify_candidate(candidate_id, model_versions.get(candidate_id), purpose, candidate.reasoning_effort,
                                          cohort, priors, samples, now=now)
        row.update(qualification)
        if not qualification["qualified"]:
            continue
        quote = candidate.quote(cohort.input_tokens, cohort.output_tokens)
        cost = quote.effective_cost_cny
        row["cost_quote"] = quote.to_dict()
        if not quote.available:
            row["reason"] = quote.reason
            continue
        row["estimated_cash_cny"] = str(quote.cash_due_cny) if quote.cash_due_cny is not None else None
        row["estimated_effective_cost_cny"] = str(cost) if cost is not None else None
        if purpose == "role" and cost is None:
            row["reason"] = "known-role-price-required"
            continue
        score = Decimal(qualification["score"])
        prior_score = Decimal(qualification["prior_score"]) if qualification["prior_score"] is not None else None
        hint_key = (prior_score is None, -prior_score if prior_score is not None else Decimal(0))
        quality_key = (-score, *hint_key, candidate_id != fixed_id, candidate_id)
        ranking_key = (*cost_order(quote), candidate_id) if purpose == "role" else quality_key
        ranked.append((ranking_key, candidate_id, quote))
    if not ranked:
        return result
    if purpose == "leader":
        winning_key, winning_id, _quote = min(ranked)
        result.update(candidate_id=winning_id, reason="highest-qualified-score")
        result["preference_broke_tie"] = winning_id == fixed_id and sum(key[:3] == winning_key[:3] for key, _, _ in ranked) > 1
        return result
    _winning_key, winning_id, _quote = min(ranked)
    result.update(candidate_id=winning_id, reason="cheapest-qualified-role")
    return result


def select_candidate(node: Node, candidates: Iterable[Candidate], allowed_ids: set[str],
                     *, external_allowed: bool = False, now: float | None = None) -> Candidate:
    timestamp = time.time() if now is None else now
    eligible = []
    for candidate in candidates:
        if not candidate.authorized or not candidate.available or candidate.candidate_id not in allowed_ids:
            continue
        if candidate.external and not external_allowed:
            continue
        if not set(node.capabilities) <= set(candidate.capabilities):
            continue
        equivalent = candidate.candidate_id == node.baseline_id or any(
            item.task_type == node.task_type and item.baseline_id == node.baseline_id and item.expires_at > timestamp
            for item in candidate.quality
        )
        if equivalent:
            eligible.append(candidate)
    if not eligible:
        raise RoutingError("no authorized quality-equivalent candidate")
    quoted = [(candidate.quote(node.input_tokens, node.output_tokens), candidate) for candidate in eligible]
    quoted = [(quote, candidate) for quote, candidate in quoted if quote.available]
    if not quoted:
        raise RoutingError("no funded quality-equivalent candidate")
    return min(quoted, key=lambda item: (*cost_order(item[0]),
                                       item[1].candidate_id != node.baseline_id if item[0].effective_cost_cny is None else False,
                                       item[1].candidate_id))[1]


def estimate_quote(nodes: Iterable[Node], candidates: Iterable[Candidate], allowed_ids: set[str],
                   *, external_allowed: bool, review_calls: int = 1, review_candidate_id: str | None = None,
                   review_output_tokens: int = 1000) -> Quote:
    rows = list(nodes)
    pool = list(candidates)
    count(review_output_tokens)
    reviewer = next((candidate for candidate in pool if candidate.candidate_id == review_candidate_id), None)
    if review_candidate_id is not None and (reviewer is None or not reviewer.authorized or not reviewer.available
                                           or review_candidate_id not in allowed_ids or reviewer.external and not external_allowed):
        raise RoutingError("reviewer is not authorized and available")
    costs = []
    reviews = []
    for node in rows:
        selected = select_candidate(node, pool, allowed_ids, external_allowed=external_allowed)
        costs.append(selected.estimate(node.input_tokens, node.output_tokens))
        baseline = reviewer or next((candidate for candidate in pool if candidate.candidate_id == node.baseline_id), None)
        reviews.append(baseline.estimate(node.input_tokens + node.output_tokens + 1024, review_output_tokens) if baseline else None)
    total_tokens = sum(node.input_tokens + node.output_tokens for node in rows)
    max_calls = len(rows) * 2 + review_calls + 1
    if any(cost is None for cost in costs) or review_calls and any(cost is None for cost in reviews):
        return Quote(None, None, None, max_calls, max(1, total_tokens * 3))
    execution = sum(costs, Decimal(0))
    review = sum(reviews[:review_calls], Decimal(0)) if review_calls else Decimal(0)
    extra_reviews = max(0, review_calls - len(reviews))
    review += max(reviews, default=Decimal(0)) * extra_reviews
    low = execution + review
    largest = max([*costs, *(reviews if review_calls else [])], default=Decimal(0))
    return Quote(low, low + largest, low * 2 + largest, max_calls, max(1, total_tokens * 3))
