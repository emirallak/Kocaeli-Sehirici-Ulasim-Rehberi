"""Build candidate first- and final-leg boundaries for transfer routing."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from api.app.schemas.itinerary import Leg, leg_from_pattern
from api.app.schemas.snapshot import RoutingIndexes, StopId


# A key is a possible transfer stop.  Each tuple preserves every valid
# occurrence-specific leg that reaches/leaves that stop.
ForwardFrontier = Mapping[StopId, tuple[Leg, ...]]
BackwardFrontier = Mapping[StopId, tuple[Leg, ...]]


def build_forward(indexes: RoutingIndexes, origin: StopId) -> ForwardFrontier:
    """Return all transfer stops reachable after boarding at ``origin``.

    Only patterns that serve the origin are examined.  For every occurrence of
    the origin, each strictly later stop occurrence is a possible alighting
    boundary for the first leg.
    """

    boundaries: dict[StopId, list[Leg]] = defaultdict(list)
    for pattern_id in indexes.routes_at_stop[origin]:
        pattern = indexes.patterns[pattern_id]
        stop_sequence = indexes.stops_on_route[pattern_id]
        for board_index in indexes.positions[pattern_id][origin]:
            if board_index not in indexes.boardable_positions[pattern_id]:
                continue
            for alight_index in range(board_index + 1, len(stop_sequence)):
                if alight_index not in indexes.alightable_positions[pattern_id]:
                    continue
                transfer_stop = stop_sequence[alight_index]
                boundaries[transfer_stop].append(
                    leg_from_pattern(
                        pattern,
                        board_stop=origin,
                        alight_stop=transfer_stop,
                        board_index=board_index,
                        alight_index=alight_index,
                    )
                )
    return {stop_id: tuple(legs) for stop_id, legs in boundaries.items()}


def build_backward(
    indexes: RoutingIndexes, destination: StopId
) -> BackwardFrontier:
    """Return all transfer stops that can ride forward into ``destination``.

    Only patterns that serve the destination are examined.  Each strictly
    earlier stop occurrence is a possible boarding boundary for the final leg.
    """

    boundaries: dict[StopId, list[Leg]] = defaultdict(list)
    for pattern_id in indexes.routes_at_stop[destination]:
        pattern = indexes.patterns[pattern_id]
        stop_sequence = indexes.stops_on_route[pattern_id]
        for alight_index in indexes.positions[pattern_id][destination]:
            if alight_index not in indexes.alightable_positions[pattern_id]:
                continue
            for board_index in range(alight_index):
                if board_index not in indexes.boardable_positions[pattern_id]:
                    continue
                transfer_stop = stop_sequence[board_index]
                boundaries[transfer_stop].append(
                    leg_from_pattern(
                        pattern,
                        board_stop=transfer_stop,
                        alight_stop=destination,
                        board_index=board_index,
                        alight_index=alight_index,
                    )
                )
    return {stop_id: tuple(legs) for stop_id, legs in boundaries.items()}
