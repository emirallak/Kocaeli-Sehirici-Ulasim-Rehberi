"""GTFS ingestion for the immutable bus and tram routing snapshot."""

from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from api.app.data.indexes import build_indexes
from api.app.data.geometry import cumulative_shape_metres, stop_chain_metres, stops_on_shape_metres
from api.app.data.transport import public_line_code, route_mode
from api.app.schemas.snapshot import (
    Pattern,
    PatternId,
    Route,
    RoutingSnapshot,
    ServiceCalendar,
    Stop,
    StopId,
    Weekday,
    read_only_mapping,
)


_DAY_COLUMNS: tuple[tuple[str, Weekday], ...] = (
    ("monday", Weekday.MONDAY),
    ("tuesday", Weekday.TUESDAY),
    ("wednesday", Weekday.WEDNESDAY),
    ("thursday", Weekday.THURSDAY),
    ("friday", Weekday.FRIDAY),
    ("saturday", Weekday.SATURDAY),
    ("sunday", Weekday.SUNDAY),
)


class GTFSLoadError(ValueError):
    """Raised when the feed cannot form a safe, canonical routing graph."""


def load_snapshot(data_dir: str | Path) -> RoutingSnapshot:
    """Parse a GTFS directory into a fully immutable routing snapshot.

    Required files are ``stops``, ``routes``, ``trips``, ``stop_times``, and
    ``calendar`` with either the normal ``.txt`` suffix or ``.csv`` suffix.
    ``calendar_dates`` is intentionally out of Stage 1 scope.
    """

    root = Path(data_dir)
    if not root.is_dir():
        raise GTFSLoadError(f"GTFS data directory does not exist: {root}")
    return _load_feed(root)


def _load_feed(root: Path) -> RoutingSnapshot:
    """Load one GTFS source without changing its local fixture identifiers."""

    calendars = _load_calendars(_find_feed_file(root, "calendar"))
    routes = _load_routes(_find_feed_file(root, "routes"))
    stops, stop_id_by_gtfs_id = _load_stops(_find_feed_file(root, "stops"))
    trips = _load_trips(_find_feed_file(root, "trips"), routes, calendars)
    trip_stops = _load_trip_stop_sequences(
        _find_feed_file(root, "stop_times"), trips, stop_id_by_gtfs_id
    )
    shapes = _load_shapes(root)
    patterns = _make_patterns(trips, trip_stops, calendars, routes, stops, shapes)
    routes = {
        route_id: route for route_id, route in routes.items()
        if route.route_type is None or route.route_type in (0, 3)
        or 700 <= route.route_type <= 716 or 900 <= route.route_type <= 906
    }
    patterns = {
        pattern_id: pattern for pattern_id, pattern in patterns.items()
        if pattern.route_id in routes
    }

    return RoutingSnapshot(
        indexes=build_indexes(stops, patterns),
        routes=read_only_mapping(routes),
        service_calendars=read_only_mapping(calendars),
    )


def _find_feed_file(data_dir: Path, stem: str) -> Path:
    for suffix in (".txt.gz", ".csv.gz", ".txt", ".csv"):
        candidate = data_dir / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    raise GTFSLoadError(f"Missing required GTFS file: {data_dir / (stem + '.txt')}")


def _load_shapes(root: Path) -> dict[str, tuple[tuple[tuple[float, float], ...], tuple[float, ...]]]:
    """Read optional shape polylines for distance and map geometry."""

    path = next((root / f"shapes{suffix}" for suffix in (".txt", ".csv") if (root / f"shapes{suffix}").is_file()), None)
    if path is None:
        return {}
    rows: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for line_number, row in enumerate(_rows(path), start=2):
        context = f"{path}:{line_number}"
        shape_id = _required(row, "shape_id", context)
        sequence = _optional_int(_required(row, "shape_pt_sequence", context))
        latitude = _optional_float(_required(row, "shape_pt_lat", context), maximum_absolute_value=90)
        longitude = _optional_float(_required(row, "shape_pt_lon", context), maximum_absolute_value=180)
        assert sequence is not None and latitude is not None and longitude is not None
        rows[shape_id].append((sequence, latitude, longitude))
    shapes = {}
    for shape_id, entries in rows.items():
        points = tuple((lat, lon) for _, lat, lon in sorted(entries))
        shapes[shape_id] = (points, cumulative_shape_metres(points))
    return shapes


def _open_feed(path: Path, encoding: str):
    opener = gzip.open if path.suffix == ".gz" else open
    return opener(path, "rt", encoding=encoding, newline="")


def _rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield normalized rows, accepting comma, semicolon, or tab delimiters."""

    # Municipal feeds may use UTF-8 or Windows-1254 for Turkish text.
    try:
        source = _open_feed(path, "utf-8-sig")
        source.read(4096)
        source.seek(0)
    except UnicodeDecodeError:
        source.close()
        source = _open_feed(path, "cp1254")
    with source:
        header = source.readline()
        if not header:
            raise GTFSLoadError(f"Empty GTFS file: {path}")
        try:
            dialect = csv.Sniffer().sniff(header, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        source.seek(0)
        reader = csv.DictReader(source, dialect=dialect)
        if not reader.fieldnames:
            raise GTFSLoadError(f"Missing header row: {path}")
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise GTFSLoadError(f"Too many columns in {path}:{line_number}")
            normalized = {
                key.strip(): (value.strip() if value is not None else "")
                for key, value in row.items()
                if key is not None
            }
            # A few real-world exports contain delimiter-only spacer rows.
            if any(normalized.values()):
                yield normalized


def _required(row: dict[str, str], field: str, context: str) -> str:
    value = row.get(field, "")
    if not value:
        raise GTFSLoadError(f"Missing {field!r} in {context}")
    return value


def _optional_float(value: str, *, maximum_absolute_value: float) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if abs(parsed) > maximum_absolute_value:
        raise GTFSLoadError(f"Coordinate out of range {value!r}")
    return parsed


def _optional_int(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise GTFSLoadError(f"Invalid integer {value!r}") from error


def _optional_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as error:
        raise GTFSLoadError(f"Invalid GTFS date {value!r}") from error


def _load_calendars(path: Path) -> dict[str, ServiceCalendar]:
    calendars: dict[str, ServiceCalendar] = {}
    for line_number, row in enumerate(_rows(path), start=2):
        service_id = _required(row, "service_id", f"{path}:{line_number}")
        if service_id in calendars:
            raise GTFSLoadError(f"Duplicate service_id {service_id!r} in {path}")
        operating_days = frozenset(
            weekday for column, weekday in _DAY_COLUMNS if row.get(column) == "1"
        )
        calendars[service_id] = ServiceCalendar(
            service_id=service_id,
            operating_days=operating_days,
            start_date=_optional_date(row.get("start_date", "")),
            end_date=_optional_date(row.get("end_date", "")),
        )
    return calendars


def _load_routes(path: Path) -> dict[str, Route]:
    routes: dict[str, Route] = {}
    for line_number, row in enumerate(_rows(path), start=2):
        # Ignore non-record rows emitted by a few CSV exporters (for example,
        # ``;;route_code;;;;`` between valid route rows).
        if not row.get("route_id"):
            continue
        route_id = _required(row, "route_id", f"{path}:{line_number}")
        if route_id in routes:
            raise GTFSLoadError(f"Duplicate route_id {route_id!r} in {path}")
        routes[route_id] = Route(
            gtfs_id=route_id,
            short_name=row.get("route_short_name") or None,
            long_name=row.get("route_long_name") or None,
            route_type=_optional_int(row.get("route_type", "")),
            code=row.get("route_code") or row.get("route_short_name") or None,
        )
    return routes


def _load_stops(path: Path) -> tuple[dict[StopId, Stop], dict[str, StopId]]:
    raw_stops: list[tuple[str, dict[str, str], int]] = []
    seen_ids: set[str] = set()
    for line_number, row in enumerate(_rows(path), start=2):
        gtfs_id = _required(row, "stop_id", f"{path}:{line_number}")
        if gtfs_id in seen_ids:
            raise GTFSLoadError(f"Duplicate stop_id {gtfs_id!r} in {path}")
        seen_ids.add(gtfs_id)
        raw_stops.append((gtfs_id, row, line_number))

    # Stable allocation makes compact IDs deterministic regardless of row order.
    raw_stops.sort(key=lambda item: item[0])
    stops: dict[StopId, Stop] = {}
    stop_id_by_gtfs_id: dict[str, StopId] = {}
    for integer_id, (gtfs_id, row, line_number) in enumerate(raw_stops):
        stop_id = StopId(integer_id)
        stops[stop_id] = Stop(
            id=stop_id,
            gtfs_id=gtfs_id,
            name=_required(row, "stop_name", f"{path}:{line_number}"),
            latitude=_optional_float(row.get("stop_lat", ""), maximum_absolute_value=90),
            longitude=_optional_float(row.get("stop_lon", ""), maximum_absolute_value=180),
            code=row.get("stop_code") or None,
            district=row.get("stop_district", "").strip(),
        )
        stop_id_by_gtfs_id[gtfs_id] = stop_id
    return stops, stop_id_by_gtfs_id


# trip_id -> (route_id, direction_id, service_id, trip_headsign, shape_id)
Trip = tuple[str, str | None, str, str | None, str | None]


def _load_trips(
    path: Path, routes: dict[str, Route], calendars: dict[str, ServiceCalendar]
) -> dict[str, Trip]:
    trips: dict[str, Trip] = {}
    for line_number, row in enumerate(_rows(path), start=2):
        trip_id = _required(row, "trip_id", f"{path}:{line_number}")
        route_id = _required(row, "route_id", f"{path}:{line_number}")
        service_id = _required(row, "service_id", f"{path}:{line_number}")
        if trip_id in trips:
            raise GTFSLoadError(f"Duplicate trip_id {trip_id!r} in {path}")
        if route_id not in routes:
            raise GTFSLoadError(f"Trip {trip_id!r} references unknown route_id {route_id!r}")
        if service_id not in calendars:
            raise GTFSLoadError(
                f"Trip {trip_id!r} references unknown service_id {service_id!r}"
            )
        trips[trip_id] = (
            route_id,
            row.get("direction_id") or None,
            service_id,
            row.get("trip_headsign") or None,
            row.get("shape_id") or None,
        )
    return trips


def _load_trip_stop_sequences(
    path: Path, trips: dict[str, Trip], stop_id_by_gtfs_id: dict[str, StopId]
) -> dict[str, tuple[tuple[StopId, bool, bool], ...]]:
    # The ordinal is a deterministic tie breaker for non-conformant feeds that
    # repeat a stop_sequence value.
    rows_by_trip: dict[str, list[tuple[int, int, StopId, bool, bool]]] = defaultdict(list)
    for ordinal, row in enumerate(_rows(path)):
        context = f"{path}:{ordinal + 2}"
        trip_id = _required(row, "trip_id", context)
        gtfs_stop_id = _required(row, "stop_id", context)
        sequence = _optional_int(_required(row, "stop_sequence", context))
        assert sequence is not None
        if trip_id not in trips:
            raise GTFSLoadError(f"stop_times references unknown trip {trip_id!r} at {context}")
        try:
            stop_id = stop_id_by_gtfs_id[gtfs_stop_id]
        except KeyError as error:
            raise GTFSLoadError(
                f"stop_times references unknown stop {gtfs_stop_id!r} at {context}"
            ) from error
        rows_by_trip[trip_id].append((
            sequence, ordinal, stop_id,
            row.get("pickup_type", "0") in ("", "0"),
            row.get("drop_off_type", "0") in ("", "0"),
        ))

    trip_stops: dict[str, tuple[tuple[StopId, bool, bool], ...]] = {}
    for trip_id in trips:
        entries = rows_by_trip.get(trip_id)
        if not entries:
            # Feeds are often published while schedules are being updated.
            # A trip without topology cannot contribute to a routing graph.
            continue
        entries.sort(key=lambda entry: (entry[0], entry[1]))
        trip_stops[trip_id] = tuple((entry[2], entry[3], entry[4]) for entry in entries)
    return trip_stops


def _make_patterns(
    trips: dict[str, Trip],
    trip_stops: dict[str, tuple[tuple[StopId, bool, bool], ...]],
    calendars: dict[str, ServiceCalendar],
    routes: dict[str, Route],
    stops: dict[StopId, Stop],
    shapes: dict[str, tuple[tuple[tuple[float, float], ...], tuple[float, ...]]],
) -> dict[PatternId, Pattern]:
    # A pattern keeps its own boarding/alighting flags; trips with the same
    # stops but different restrictions must never be merged.
    groups: dict[
        tuple[str, str | None, str | None, tuple[StopId, ...], tuple[bool, ...], tuple[bool, ...], frozenset[Weekday]],
        dict[str, set[str]],
    ] = defaultdict(lambda: {"service_ids": set(), "headsigns": set()})
    for trip_id, (route_id, direction_id, service_id, headsign, shape_id) in trips.items():
        stop_data = trip_stops.get(trip_id)
        if stop_data is None:
            continue
        operating_days = calendars[service_id].operating_days
        # An inactive calendar row is common in archived GTFS exports. It
        # cannot form a usable itinerary and would violate Itinerary's
        # non-empty operating-day invariant.
        if not operating_days:
            continue
        stop_ids = tuple(item[0] for item in stop_data)
        pickup_allowed = tuple(item[1] for item in stop_data)
        dropoff_allowed = tuple(item[2] for item in stop_data)
        group = groups[(route_id, direction_id, shape_id, stop_ids, pickup_allowed, dropoff_allowed, operating_days)]
        group["service_ids"].add(service_id)
        if headsign:
            group["headsigns"].add(headsign)

    def sort_key(
        item: tuple[
            tuple[str, str | None, str | None, tuple[StopId, ...], tuple[bool, ...], tuple[bool, ...], frozenset[Weekday]],
            dict[str, set[str]],
        ]
    ) -> tuple[str, str, str, tuple[int, ...], tuple[bool, ...], tuple[bool, ...], tuple[int, ...]]:
        (route_id, direction_id, shape_id, stop_ids, pickup, dropoff, days), _ = item
        return route_id, direction_id or "", shape_id or "", tuple(stop_ids), pickup, dropoff, tuple(sorted(int(day) for day in days))

    patterns: dict[PatternId, Pattern] = {}
    distances_by_path = {}
    for integer_id, (key, metadata) in enumerate(sorted(groups.items(), key=sort_key)):
        route_id, direction_id, shape_id, stop_ids, pickup_allowed, dropoff_allowed, operating_days = key
        shape_points, shape_metres = shapes.get(shape_id, ((), ()))
        distance_key = (shape_id, stop_ids)
        if distance_key not in distances_by_path:
            distances = stops_on_shape_metres(
                stop_ids, stops, shape_points, shape_metres
            )
            distances_by_path[distance_key] = (
                distances, bool(shape_points) and distances != stop_chain_metres(stop_ids, stops)
            )
        pattern_id = PatternId(integer_id)
        patterns[pattern_id] = Pattern(
            id=pattern_id,
            route_id=route_id,
            direction_id=direction_id,
            stop_ids=stop_ids,
            service_ids=frozenset(metadata["service_ids"]),
            operating_days=operating_days,
            route_code=public_line_code(routes[route_id].short_name or routes[route_id].code or route_id),
            headsigns=frozenset(metadata["headsigns"]),
            mode=route_mode(routes[route_id]),
            pickup_allowed=pickup_allowed,
            dropoff_allowed=dropoff_allowed,
            shape_id=shape_id,
            shape_points=shape_points,
            shape_metres=shape_metres,
            metres_at_stop=distances_by_path[distance_key][0],
            shape_usable=distances_by_path[distance_key][1],
        )
    return patterns
