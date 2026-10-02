"""Immutable value objects used by the Stage 1 routing snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from types import MappingProxyType
from typing import Mapping, NewType, TypeVar


# These are compact, process-local integer identifiers.  GTFS identifiers are
# retained separately where needed for diagnostics and display.
StopId = NewType("StopId", int)
PatternId = NewType("PatternId", int)


class Weekday(IntEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(frozen=True, slots=True)
class Stop:
    id: StopId
    gtfs_id: str
    name: str
    latitude: float | None
    longitude: float | None
    code: str | None = None
    district: str = ""


@dataclass(frozen=True, slots=True)
class Route:
    """Route metadata keyed by its source GTFS ``route_id``."""

    gtfs_id: str
    short_name: str | None
    long_name: str | None
    route_type: int | None
    # ``route_code`` is feed-specific; standard GTFS feeds fall back to the
    # familiar ``route_short_name`` when no dedicated code exists.
    code: str | None = None
    source: str = "bus"


@dataclass(frozen=True, slots=True)
class ServiceCalendar:
    """The recurring weekly portion of a GTFS service calendar."""

    service_id: str
    operating_days: frozenset[Weekday]
    start_date: date | None
    end_date: date | None


@dataclass(frozen=True, slots=True)
class Pattern:
    """One route/direction/stop-sequence/service-days/boarding-rule combination."""

    id: PatternId
    route_id: str
    direction_id: str | None
    stop_ids: tuple[StopId, ...]
    # A pattern can represent several service_ids when their weekly operating
    # days are equal.  Keeping these IDs preserves traceability to GTFS.
    service_ids: frozenset[str]
    # This is the routing engine's direct answer to "does it run Sunday?".
    operating_days: frozenset[Weekday]
    route_code: str | None
    # Identical topology/calendar trips may have distinct destination signs.
    headsigns: frozenset[str]
    source: str = "bus"
    mode: str = "Otobüs"
    # Empty tuples preserve unrestricted behaviour for hand-built patterns.
    pickup_allowed: tuple[bool, ...] = ()
    dropoff_allowed: tuple[bool, ...] = ()
    shape_id: str | None = None
    shape_points: tuple[tuple[float, float], ...] = ()
    shape_metres: tuple[float, ...] = ()
    metres_at_stop: tuple[float, ...] = ()
    shape_usable: bool = False


@dataclass(frozen=True, slots=True)
class RoutingIndexes:
    """Read-only lookup tables derived from stops and patterns.

    ``positions`` stores *all* occurrences of a stop on a pattern.  It is not
    a single position because a circular line may visit the same stop twice.
    """

    stops: Mapping[StopId, Stop]
    patterns: Mapping[PatternId, Pattern]
    routes_at_stop: Mapping[StopId, frozenset[PatternId]]
    stops_on_route: Mapping[PatternId, tuple[StopId, ...]]
    positions: Mapping[PatternId, Mapping[StopId, tuple[int, ...]]]
    occurrences_at_stop: Mapping[StopId, tuple[tuple[PatternId, int], ...]]
    boardable_positions: Mapping[PatternId, frozenset[int]]
    alightable_positions: Mapping[PatternId, frozenset[int]]
    metres_at_position: Mapping[PatternId, tuple[float, ...]]
    # Nearby, distinct stops which can be connected on foot.  Entries are
    # ``(stop_id, metres)`` and deliberately contain no self-edge.
    walking_neighbors: Mapping[StopId, tuple[tuple[StopId, int], ...]]


@dataclass(frozen=True, slots=True)
class RoutingSnapshot:
    """The complete immutable Stage 1 graph and its GTFS source metadata."""

    indexes: RoutingIndexes
    routes: Mapping[str, Route]
    service_calendars: Mapping[str, ServiceCalendar]

    @property
    def stops(self) -> Mapping[StopId, Stop]:
        return self.indexes.stops

    @property
    def patterns(self) -> Mapping[PatternId, Pattern]:
        return self.indexes.patterns


K = TypeVar("K")
V = TypeVar("V")


def read_only_mapping(values: Mapping[K, V]) -> Mapping[K, V]:
    """Copy a mapping and expose it through an immutable mapping interface."""

    return MappingProxyType(dict(values))
