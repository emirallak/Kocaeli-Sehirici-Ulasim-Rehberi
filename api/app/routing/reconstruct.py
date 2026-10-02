"""Convert compact routing legs into display-ready itinerary responses."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from api.app.schemas.itinerary import Itinerary, Leg, leg_from_pattern
from api.app.schemas.snapshot import RoutingIndexes


class ReconstructionError(ValueError):
    """Raised when a raw leg does not refer to the canonical snapshot."""


def reconstruct_itinerary(indexes: RoutingIndexes, legs: Iterable[Leg]) -> Itinerary:
    """Return an itinerary whose legs contain route, headsign, and stop labels.

    ``Leg`` retains compact integer IDs for routing, while this boundary step
    resolves human-facing fields solely from the immutable Stage 1 indexes.
    """

    rich_legs: list[Leg] = []
    for raw_leg in legs:
        try:
            board_stop = indexes.stops[raw_leg.board_stop]
            alight_stop = indexes.stops[raw_leg.alight_stop]
        except KeyError as error:
            raise ReconstructionError(
                f"Leg references an unknown pattern or stop: {raw_leg!r}"
            ) from error

        if raw_leg.is_walking:
            rich_legs.append(replace(
                raw_leg,
                board_stop_name=board_stop.name,
                alight_stop_name=alight_stop.name,
            ))
            continue

        # Rebuild from the snapshot rather than trusting a caller-provided
        # route/headsign payload, then attach the resolved display names.
        assert raw_leg.pattern_id is not None
        pattern = indexes.patterns[raw_leg.pattern_id]
        canonical_leg = leg_from_pattern(
            pattern,
            board_stop=raw_leg.board_stop,
            alight_stop=raw_leg.alight_stop,
            board_index=raw_leg.board_index,
            alight_index=raw_leg.alight_index,
        )
        rich_legs.append(
            replace(
                canonical_leg,
                board_stop_name=board_stop.name,
                alight_stop_name=alight_stop.name,
            )
        )
    return Itinerary(tuple(rich_legs))
