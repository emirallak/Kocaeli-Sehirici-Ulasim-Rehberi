"""Occurrence-aware, direct-ride routing."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator

from api.app.schemas.itinerary import Itinerary, leg_from_pattern
from api.app.schemas.snapshot import RoutingIndexes, StopId


def direct(
    indexes: RoutingIndexes, origin: StopId, destination: StopId
) -> Iterator[Itinerary]:
    """Yield every valid direct itinerary from ``origin`` to ``destination``.

    Candidate patterns are found with a hash-set intersection.  For a shared
    pattern, ``bisect_right`` skips every destination occurrence at or before
    each boarding occurrence, which enforces strict travel direction even when
    a circular route visits either stop more than once.
    """

    shared_pattern_ids = indexes.routes_at_stop[origin].intersection(
        indexes.routes_at_stop[destination]
    )
    for pattern_id in shared_pattern_ids:
        board_indexes = (
            index for index in indexes.positions[pattern_id][origin]
            if index in indexes.boardable_positions[pattern_id]
        )
        alight_indexes = tuple(
            index for index in indexes.positions[pattern_id][destination]
            if index in indexes.alightable_positions[pattern_id]
        )
        pattern = indexes.patterns[pattern_id]

        for board_index in board_indexes:
            first_valid_alight = bisect_right(alight_indexes, board_index)
            for alight_index in alight_indexes[first_valid_alight:]:
                yield Itinerary(
                    (
                        leg_from_pattern(
                            pattern,
                            board_stop=origin,
                            alight_stop=destination,
                            board_index=board_index,
                            alight_index=alight_index,
                        ),
                    )
                )
