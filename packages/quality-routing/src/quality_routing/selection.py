from __future__ import annotations

import time
from decimal import Decimal
from typing import Iterable

from .contracts import Candidate, Node, Quote, RoutingError, count
from .costs import cost_order


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
