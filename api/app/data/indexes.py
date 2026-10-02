"""Construction of immutable, query-oriented routing indexes."""

from __future__ import annotations

from collections import defaultdict
from math import asin, cos, radians, sin, sqrt
from typing import Mapping

from api.app.data.boarding_rules import published_permissions
from api.app.data.geometry import stop_chain_metres

from api.app.schemas.snapshot import (
    Pattern,
    PatternId,
    RoutingIndexes,
    Stop,
    StopId,
    read_only_mapping,
)


def build_indexes(
    stops: Mapping[StopId, Stop], patterns: Mapping[PatternId, Pattern]
) -> RoutingIndexes:
    """Build every Stage 1 lookup table from canonical stops and patterns.

    All mutable intermediate containers are discarded before returning, so a
    caller can safely share the resulting graph across FastAPI requests.
    """

    # Every canonical stop is present, including a stop currently not used by
    # any trip, so callers never need special handling for an empty lookup.
    routes_at_stop: dict[StopId, set[PatternId]] = {
        stop_id: set() for stop_id in stops
    }
    stops_on_route: dict[PatternId, tuple[StopId, ...]] = {}
    positions: dict[PatternId, Mapping[StopId, tuple[int, ...]]] = {}
    occurrences_at_stop: dict[StopId, list[tuple[PatternId, int]]] = {
        stop_id: [] for stop_id in stops
    }

    for pattern_id, pattern in patterns.items():
        stop_sequence = pattern.stop_ids
        stops_on_route[pattern_id] = stop_sequence

        positions_for_pattern: dict[StopId, list[int]] = defaultdict(list)
        for position, stop_id in enumerate(stop_sequence):
            # Do not use a plain stop -> position mapping: repeated stops on a
            # loop are meaningful distinct boarding/alighting occurrences.
            positions_for_pattern[stop_id].append(position)
            routes_at_stop[stop_id].add(pattern_id)
            occurrences_at_stop[stop_id].append((pattern_id, position))

        positions[pattern_id] = read_only_mapping(
            {
                stop_id: tuple(indexes)
                for stop_id, indexes in positions_for_pattern.items()
            }
        )

    permissions = {
        pattern_id: published_permissions(pattern, stops)
        for pattern_id, pattern in patterns.items()
    }

    return RoutingIndexes(
        stops=read_only_mapping(stops),
        patterns=read_only_mapping(patterns),
        routes_at_stop=read_only_mapping(
            {
                stop_id: frozenset(pattern_ids)
                for stop_id, pattern_ids in routes_at_stop.items()
            }
        ),
        stops_on_route=read_only_mapping(stops_on_route),
        positions=read_only_mapping(positions),
        occurrences_at_stop=read_only_mapping(
            {
                stop_id: tuple(occurrences)
                for stop_id, occurrences in occurrences_at_stop.items()
            }
        ),
        boardable_positions=read_only_mapping({pid: allowed[0] for pid, allowed in permissions.items()}),
        alightable_positions=read_only_mapping({pid: allowed[1] for pid, allowed in permissions.items()}),
        metres_at_position=read_only_mapping({
            pid: pattern.metres_at_stop or stop_chain_metres(pattern.stop_ids, stops)
            for pid, pattern in patterns.items()
        }),
        walking_neighbors=read_only_mapping(_build_walking_neighbors(stops)),
    )


def _build_walking_neighbors(
    stops: Mapping[StopId, Stop], maximum_metres: int = 500
) -> dict[StopId, tuple[tuple[StopId, int], ...]]:
    """Create bounded foot-transfer edges with a small geographic grid.

    A full all-pairs comparison is prohibitively expensive for a city bus
    feed. Latitude/longitude cells keep comparisons local while still
    inspecting the surrounding cells needed for a 500 metre radius.
    """

    cell_size = 0.005  # roughly 550 m latitude near Kocaeli
    cells: dict[tuple[int, int], list[StopId]] = defaultdict(list)
    for stop_id, stop in stops.items():
        if stop.latitude is not None and stop.longitude is not None:
            cells[(int(stop.latitude / cell_size), int(stop.longitude / cell_size))].append(stop_id)

    neighbors: dict[StopId, list[tuple[StopId, int]]] = {stop_id: [] for stop_id in stops}
    for stop_id, stop in stops.items():
        if stop.latitude is None or stop.longitude is None:
            continue
        cell = (int(stop.latitude / cell_size), int(stop.longitude / cell_size))
        for latitude_cell in range(cell[0] - 1, cell[0] + 2):
            for longitude_cell in range(cell[1] - 2, cell[1] + 3):
                for other_id in cells.get((latitude_cell, longitude_cell), ()):
                    if int(other_id) <= int(stop_id):
                        continue
                    other = stops[other_id]
                    metres = _distance_metres(stop.latitude, stop.longitude, other.latitude, other.longitude)
                    if metres <= maximum_metres:
                        neighbors[stop_id].append((other_id, metres))
                        neighbors[other_id].append((stop_id, metres))
    return {
        stop_id: tuple(sorted(values, key=lambda item: (item[1], int(item[0]))))
        for stop_id, values in neighbors.items()
    }


def _distance_metres(latitude: float, longitude: float, other_latitude: float | None, other_longitude: float | None) -> int:
    assert other_latitude is not None and other_longitude is not None
    lat_1, lon_1, lat_2, lon_2 = map(radians, (latitude, longitude, other_latitude, other_longitude))
    a = sin((lat_2 - lat_1) / 2) ** 2 + cos(lat_1) * cos(lat_2) * sin((lon_2 - lon_1) / 2) ** 2
    return round(6_371_000 * 2 * asin(sqrt(a)))
