"""One-transfer routing by joining Stage 2 frontiers at shared stops."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterator

from api.app.routing.frontiers import BackwardFrontier, ForwardFrontier
from api.app.schemas.itinerary import Itinerary, Leg, leg_from_pattern, walking_leg
from api.app.schemas.snapshot import PatternId, RoutingIndexes, StopId


def one_transfer(
    forward: ForwardFrontier, backward: BackwardFrontier, indexes: RoutingIndexes
) -> Iterator[Itinerary]:
    """Yield valid two-leg itineraries at transfer-stop intersections.

    The function joins only matching frontier keys; it never scans all
    patterns.  Reusing the same pattern is omitted because it is a direct ride
    and belongs in :func:`app.routing.direct.direct`, not a transfer result.
    """

    for transfer_stop, first_legs in forward.items():
        # A same-platform handover does not need a separate foot leg. Nearby
        # stops can be joined by a short walk.
        connections = ((transfer_stop, 0),) + indexes.walking_neighbors[transfer_stop]
        for final_board_stop, walking_metres in connections:
            for first_leg in first_legs:
                for final_leg in backward.get(final_board_stop, ()):
                    if first_leg.pattern_id == final_leg.pattern_id:
                        continue
                    # A physically possible transfer must be possible on at least
                    # one shared day; Itinerary validates and exposes that set.
                    if not first_leg.operating_days.intersection(final_leg.operating_days):
                        continue
                    if transfer_stop != final_board_stop:
                        yield Itinerary((first_leg, walking_leg(
                            board_stop=transfer_stop,
                            alight_stop=final_board_stop,
                            metres=walking_metres,
                        ), final_leg))
                    else:
                        yield Itinerary((first_leg, final_leg))


def two_transfers(
    forward: ForwardFrontier,
    backward: BackwardFrontier,
    indexes: RoutingIndexes,
) -> Iterator[Itinerary]:
    """Yield valid origin -> middle -> destination itineraries with two transfers.

    Both frontiers are first grouped by the middle patterns serving their keys.
    Consequently the expensive work is limited to middle patterns which can
    actually board at a forward boundary *and* exit at a backward boundary;
    it never scans every possible three-pattern combination.
    """

    forward_by_middle = _group_by_middle_pattern(forward, indexes, forward_direction=True)
    backward_by_middle = _group_by_middle_pattern(backward, indexes, forward_direction=False)

    for middle_pattern_id in forward_by_middle.keys() & backward_by_middle.keys():
        middle_pattern = indexes.patterns[middle_pattern_id]
        first_legs_by_board = forward_by_middle[middle_pattern_id]
        final_legs_by_exit = backward_by_middle[middle_pattern_id]

        for middle_board_stop, first_connections in first_legs_by_board.items():
            board_positions = indexes.positions[middle_pattern_id][middle_board_stop]
            for middle_exit_stop, final_connections in final_legs_by_exit.items():
                exit_positions = indexes.positions[middle_pattern_id][middle_exit_stop]
                for middle_board_index in board_positions:
                    if middle_board_index not in indexes.boardable_positions[middle_pattern_id]:
                        continue
                    first_valid_exit = bisect_right(exit_positions, middle_board_index)
                    for middle_exit_index in exit_positions[first_valid_exit:]:
                        if middle_exit_index not in indexes.alightable_positions[middle_pattern_id]:
                            continue
                        middle_leg = leg_from_pattern(
                            middle_pattern,
                            board_stop=middle_board_stop,
                            alight_stop=middle_exit_stop,
                            board_index=middle_board_index,
                            alight_index=middle_exit_index,
                        )
                        for first_leg, first_walk in first_connections:
                            if first_leg.pattern_id == middle_pattern_id:
                                continue
                            common_first_days = first_leg.operating_days.intersection(
                                middle_leg.operating_days
                            )
                            if not common_first_days:
                                continue
                            for final_leg, final_walk in final_connections:
                                if final_leg.pattern_id == middle_pattern_id:
                                    continue
                                if not common_first_days.intersection(final_leg.operating_days):
                                    continue
                                legs = [first_leg]
                                if first_walk is not None:
                                    legs.append(first_walk)
                                legs.append(middle_leg)
                                if final_walk is not None:
                                    legs.append(final_walk)
                                legs.append(final_leg)
                                yield Itinerary(tuple(legs))


def _group_by_middle_pattern(
    frontier: ForwardFrontier | BackwardFrontier,
    indexes: RoutingIndexes,
    *,
    forward_direction: bool,
) -> dict[PatternId, dict[StopId, list[tuple[Leg, Leg | None]]]]:
    """Index frontier legs by patterns that can serve each boundary stop."""

    grouped: dict[PatternId, dict[StopId, list[tuple[Leg, Leg | None]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for boundary_stop, outer_legs in frontier.items():
        connections = ((boundary_stop, 0),) + indexes.walking_neighbors[boundary_stop]
        for middle_stop, metres in connections:
            foot = None
            if boundary_stop != middle_stop:
                foot = walking_leg(
                    board_stop=boundary_stop if forward_direction else middle_stop,
                    alight_stop=middle_stop if forward_direction else boundary_stop,
                    metres=metres,
                )
            # This hash lookup is the only way middle patterns are discovered.
            for middle_pattern_id in indexes.routes_at_stop[middle_stop]:
                grouped[middle_pattern_id][middle_stop].extend(
                    (outer_leg, foot) for outer_leg in outer_legs
                )
    return grouped
