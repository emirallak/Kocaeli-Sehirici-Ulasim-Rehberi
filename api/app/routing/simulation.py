"""Simulated vehicle positions from the static timetable.

Kocaeli publishes no live vehicle feed, so every scheduled trip is assumed to
leave its first stop on time and to travel at one constant average speed,
chosen by the line's kind and the clock at its departure: slower in weekday
rush hours, faster otherwise. Trams run on their own track and always use
one speed.

The feed has no district data, so a line's kind is inferred from its stop
spacing, which is what limits a bus's average speed most: district and
village lines (KM, 4xx, SH, TF …) stop every 600 m or more on average,
city lines every 300–450 m.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from api.app.schemas.snapshot import Pattern, PatternId, RoutingSnapshot, ServiceCalendar

TURKEY = timezone(timedelta(hours=3))
LineKind = Literal["city", "district", "tram"]
# (rush hour, other hours) average speeds in km/h, stops included.
SPEEDS_KMH: dict[str, tuple[float, float]] = {
    "city": (16.0, 23.0),
    "district": (25.0, 35.0),
    "tram": (25.0, 25.0),
}
MIN_SPEED_KMH = min(min(speeds) for speeds in SPEEDS_KMH.values())
MAX_SPEED_KMH = max(max(speeds) for speeds in SPEEDS_KMH.values())
DISTRICT_STOP_SPACING_METRES = 600
# Weekday rush hours as [start, end) minutes after midnight.
PEAK_WINDOWS = ((7 * 60, 9 * 60 + 30), (16 * 60 + 30, 19 * 60 + 30))


def is_rush_hour(moment: datetime) -> bool:
    minute = moment.hour * 60 + moment.minute
    return moment.weekday() < 5 and any(start <= minute < end for start, end in PEAK_WINDOWS)


def average_speed_kmh(moment: datetime, kind: LineKind = "city") -> float:
    rush, other = SPEEDS_KMH[kind]
    return rush if is_rush_hour(moment) else other


def line_kind(snapshot: RoutingSnapshot, pattern_id: PatternId) -> LineKind:
    pattern = snapshot.patterns[pattern_id]
    if pattern.mode == "Tramvay":
        return "tram"
    metres = snapshot.indexes.metres_at_position[pattern_id]
    if len(metres) < 2:
        return "city"
    spacing = (metres[-1] - metres[0]) / (len(metres) - 1)
    return "district" if spacing >= DISTRICT_STOP_SPACING_METRES else "city"


def _clock_seconds(value: str) -> int | None:
    try:
        parts = [int(part) for part in value.split(":")]
    except ValueError:
        return None
    if len(parts) < 2:
        return None
    return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)


def _runs_on(calendar: ServiceCalendar | None, day: date) -> bool:
    if calendar is None or day.weekday() not in calendar.operating_days:
        return False
    if calendar.start_date and day < calendar.start_date:
        return False
    return not (calendar.end_date and day > calendar.end_date)


@dataclass(frozen=True, slots=True)
class SimulatedTrip:
    pattern_id: PatternId
    departure: datetime
    speed_kmh: float

    @property
    def metres_per_second(self) -> float:
        return self.speed_kmh / 3.6

    def travelled(self, moment: datetime) -> float:
        """Metres covered since leaving the first stop (negative before)."""
        return (moment - self.departure).total_seconds() * self.metres_per_second

    def time_at(self, metres: float) -> datetime:
        return self.departure + timedelta(seconds=metres / self.metres_per_second)


def scheduled_trips(snapshot: RoutingSnapshot, pattern_id: PatternId,
                    start: datetime, end: datetime) -> list[SimulatedTrip]:
    """Trips of one pattern leaving the first stop within ``[start, end]``.

    GTFS times may exceed 24:00, so the service day before ``start`` is
    scanned too.
    """
    pattern = snapshot.patterns[pattern_id]
    kind = line_kind(snapshot, pattern_id)
    trips: dict[datetime, SimulatedTrip] = {}
    day = (start - timedelta(days=1)).date()
    while day <= end.date():
        midnight = datetime(day.year, day.month, day.day, tzinfo=start.tzinfo or TURKEY)
        for service_id, clock in pattern.departures:
            seconds = _clock_seconds(clock)
            if seconds is None or not _runs_on(snapshot.service_calendars.get(service_id), day):
                continue
            departure = midnight + timedelta(seconds=seconds)
            # Identical clocks from overlapping calendars are one vehicle.
            if start <= departure <= end and departure not in trips:
                trips[departure] = SimulatedTrip(pattern_id, departure, average_speed_kmh(departure, kind))
        day += timedelta(days=1)
    return sorted(trips.values(), key=lambda trip: trip.departure)


def _point_at(snapshot: RoutingSnapshot, pattern: Pattern, metres: tuple[float, ...],
              along: float) -> tuple[float, float] | None:
    """Coordinates ``along`` metres on the pattern, on the shape when usable."""
    if (pattern.shape_usable and len(pattern.shape_points) >= 2
            and len(pattern.shape_metres) == len(pattern.shape_points)):
        points, cumulative = pattern.shape_points, pattern.shape_metres
    else:
        located = [(distance, snapshot.stops[stop_id]) for distance, stop_id in zip(metres, pattern.stop_ids)]
        located = [(distance, (stop.latitude, stop.longitude)) for distance, stop in located
                   if stop.latitude is not None and stop.longitude is not None]
        if not located:
            return None
        if len(located) == 1:
            return located[0][1]
        cumulative = tuple(distance for distance, _ in located)
        points = tuple(point for _, point in located)
    index = max(0, min(len(points) - 2, bisect_right(cumulative, along) - 1))
    start, end = cumulative[index], cumulative[index + 1]
    fraction = max(0.0, min(1.0, (along - start) / (end - start))) if end > start else 0.0
    (lat_a, lon_a), (lat_b, lon_b) = points[index], points[index + 1]
    return lat_a + (lat_b - lat_a) * fraction, lon_a + (lon_b - lon_a) * fraction


def vehicle_state(snapshot: RoutingSnapshot, trip: SimulatedTrip, now: datetime) -> dict | None:
    """Where a departed, unfinished trip is at ``now``; ``None`` otherwise."""
    pattern = snapshot.patterns[trip.pattern_id]
    metres = snapshot.indexes.metres_at_position[trip.pattern_id]
    travelled = trip.travelled(now)
    if len(metres) < 2 or travelled < 0 or metres[0] + travelled > metres[-1]:
        return None
    along = metres[0] + travelled
    # The vehicle has passed ``previous``; with a zero-length hop the later
    # of two equal positions is the one it has reached.
    previous = min(len(metres) - 2, bisect_right(metres, along) - 1)
    point = _point_at(snapshot, pattern, metres, along)
    if point is None:
        return None
    next_time = trip.time_at(metres[previous + 1] - metres[0])
    return {
        "id": f"{int(trip.pattern_id)}-{trip.departure.isoformat()}",
        "pattern_id": int(trip.pattern_id),
        "latitude": point[0],
        "longitude": point[1],
        "metres": along,
        "previous_position": previous,
        "speed_kmh": trip.speed_kmh,
        "departed_at": trip.departure.isoformat(),
        "next_position": previous + 1,
        "next_stop": snapshot.stops[pattern.stop_ids[previous + 1]].name,
        "minutes_to_next_stop": max(0, round((next_time - now).total_seconds() / 60)),
    }


def _longest_trip(metres: tuple[float, ...]) -> timedelta:
    length = metres[-1] - metres[0] if metres else 0.0
    return timedelta(seconds=length / (MIN_SPEED_KMH / 3.6))


def active_vehicles(snapshot: RoutingSnapshot, pattern_id: PatternId, now: datetime,
                    last_position: int | None = None) -> list[dict]:
    """Vehicles currently between the first stop and ``last_position``."""
    metres = snapshot.indexes.metres_at_position[pattern_id]
    if len(metres) < 2:
        return []
    last = len(metres) - 1 if last_position is None else min(last_position, len(metres) - 1)
    vehicles = []
    for trip in scheduled_trips(snapshot, pattern_id, now - _longest_trip(metres), now):
        state = vehicle_state(snapshot, trip, now)
        if state is not None and state["metres"] <= metres[last]:
            vehicles.append(state)
    return vehicles


def trips_reaching(snapshot: RoutingSnapshot, pattern_id: PatternId, position: int,
                   start: datetime, end: datetime) -> list[tuple[SimulatedTrip, datetime]]:
    """Trips and their simulated arrival at ``position`` within ``[start, end]``."""
    metres = snapshot.indexes.metres_at_position[pattern_id]
    if not metres:
        return []
    offset = metres[position] - metres[0]
    # Departures are bounded by the slowest and fastest possible speeds.
    earliest = start - timedelta(seconds=offset / (MIN_SPEED_KMH / 3.6))
    latest = end - timedelta(seconds=offset / (MAX_SPEED_KMH / 3.6))
    reached = ((trip, trip.time_at(offset)) for trip in scheduled_trips(snapshot, pattern_id, earliest, latest))
    return [(trip, time) for trip, time in reached if start <= time <= end]


def arrivals_at(snapshot: RoutingSnapshot, pattern_id: PatternId, position: int,
                start: datetime, end: datetime) -> list[datetime]:
    """Simulated arrival times at ``position`` within ``[start, end]``."""
    return [time for _, time in trips_reaching(snapshot, pattern_id, position, start, end)]
