"""Bounded-memory ranking for streamed routing results."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from collections.abc import Iterable, Iterator

from api.app.schemas.itinerary import Itinerary
from api.app.data.transport import public_line_code


Score = tuple[int, float]


def route_combination(itinerary: Itinerary) -> tuple[tuple[str, str], ...]:
    """Ordered public line codes, ignoring walking transfers."""
    return tuple(
        ("code", _public_line_code(leg.route_code))
        if leg.route_code and leg.route_code.strip()
        else ("route_id", leg.route_id)
        for leg in itinerary.legs
        if not leg.is_walking
    )


def _public_line_code(route_code: str) -> str:
    """Normalize a published line code for distinct-route comparisons."""

    return public_line_code(route_code).upper()


def top_k_distinct(itineraries: Iterable[Itinerary], limit: int) -> Iterator[Itinerary]:
    """Keep only the best journey for each line combination, before limiting K.

    Retain at most K representatives. An evicted combination may re-enter if a
    better journey arrives later. Ties keep the earlier candidate. For the API's
    small K (at most 20), scanning K entries on replacement keeps memory bounded
    without a growing heap of stale entries or an unbounded seen-combinations set.
    """
    if limit <= 0:
        return
    best: dict[tuple[tuple[str, str], ...], tuple[Score, int, Itinerary]] = {}
    for sequence, itinerary in enumerate(itineraries):
        key = route_combination(itinerary)
        candidate_score = score(itinerary)
        previous = best.get(key)
        if previous is not None:
            if candidate_score < previous[0]:
                best[key] = (candidate_score, sequence, itinerary)
            continue
        if len(best) == limit:
            worst_key = max(best, key=lambda k: best[k][:2])
            if candidate_score >= best[worst_key][0]:
                continue
            del best[worst_key]
        best[key] = (candidate_score, sequence, itinerary)
    for _, _, itinerary in sorted(best.values(), key=lambda entry: entry[:2]):
        yield itinerary


def score(itinerary: Itinerary) -> Score:
    """Prefer fewer transfers, then hops with a walking-distance penalty.

    The second term is a ranking heuristic, not a journey time estimate.
    """

    return (
        itinerary.transit_leg_count - 1,
        sum(leg.alight_index - leg.board_index for leg in itinerary.legs)
        + sum(leg.walking_metres or 0 for leg in itinerary.legs) / 80,
    )


@dataclass(frozen=True)
class _ReverseScore:
    """Invert score ordering so Python's min-heap keeps the worst item on top."""

    value: Score

    def __lt__(self, other: _ReverseScore) -> bool:
        return self.value > other.value


def top_k(itineraries: Iterable[Itinerary], limit: int) -> Iterator[Itinerary]:
    """Yield the best ``limit`` itineraries, using O(limit) working memory.

    The input may be any generator, including direct, one-transfer, and
    two-transfer results chained together.  It is consumed once; only the
    current top-K heap is retained.
    """

    if limit <= 0:
        return

    heap: list[tuple[_ReverseScore, int, Itinerary]] = []
    for sequence, itinerary in enumerate(itineraries):
        itinerary_score = score(itinerary)
        entry = (_ReverseScore(itinerary_score), sequence, itinerary)
        if len(heap) < limit:
            heapq.heappush(heap, entry)
        elif itinerary_score < heap[0][0].value:
            heapq.heapreplace(heap, entry)

    for _, _, itinerary in sorted(heap, key=lambda entry: (entry[0].value, entry[1])):
        yield itinerary
