"""Distances along GTFS shapes and stop sequences, in metres."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Mapping

from api.app.schemas.snapshot import Stop, StopId


def haversine(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    lat1, lat2 = radians(a_lat), radians(b_lat)
    dlat, dlon = lat2 - lat1, radians(b_lon - a_lon)
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 12_742_000 * asin(min(1.0, sqrt(value)))


def cumulative_shape_metres(points: tuple[tuple[float, float], ...]) -> tuple[float, ...]:
    totals = [0.0]
    for first, second in zip(points, points[1:]):
        totals.append(totals[-1] + haversine(*first, *second))
    return tuple(totals)


def stop_chain_metres(stop_ids: tuple[StopId, ...], stops: Mapping[StopId, Stop]) -> tuple[float, ...]:
    totals = [0.0]
    for previous_id, next_id in zip(stop_ids, stop_ids[1:]):
        previous, following = stops[previous_id], stops[next_id]
        distance = (
            haversine(previous.latitude, previous.longitude, following.latitude, following.longitude)
            if None not in (previous.latitude, previous.longitude, following.latitude, following.longitude)
            else 400.0
        )
        totals.append(totals[-1] + distance)
    return tuple(totals)


def stops_on_shape_metres(
    stop_ids: tuple[StopId, ...], stops: Mapping[StopId, Stop],
    points: tuple[tuple[float, float], ...], shape_metres: tuple[float, ...],
) -> tuple[float, ...]:
    """Project stops in travel order onto the polyline; fall back on bad shapes."""

    fallback = stop_chain_metres(stop_ids, stops)
    if len(points) < 2:
        return fallback
    matched: list[float] = []
    first_segment = 0
    for stop_id in stop_ids:
        stop = stops[stop_id]
        if stop.latitude is None or stop.longitude is None:
            return fallback
        latitude_scale = 111_195.0
        longitude_scale = latitude_scale * cos(radians(stop.latitude))
        best = (float("inf"), 0.0, first_segment)
        window_end = min(first_segment + 120, len(points) - 1)
        for start, end in ((first_segment, window_end), (window_end, len(points) - 1)):
            if start == window_end and best[0] <= 150**2:
                break
            for index in range(start, end):
                a_lat, a_lon = points[index]
                b_lat, b_lon = points[index + 1]
                ax = (a_lon - stop.longitude) * longitude_scale
                ay = (a_lat - stop.latitude) * latitude_scale
                vx = (b_lon - a_lon) * longitude_scale
                vy = (b_lat - a_lat) * latitude_scale
                fraction = max(0.0, min(1.0, -(ax * vx + ay * vy) / (vx * vx + vy * vy))) if vx or vy else 0.0
                error = (ax + fraction * vx) ** 2 + (ay + fraction * vy) ** 2
                candidate = (error, shape_metres[index] + fraction * (shape_metres[index + 1] - shape_metres[index]), index)
                if candidate < best:
                    best = candidate
        if best[0] > 1_000_000:  # More than 1 km away is a mismatched shape.
            return fallback
        first_segment = best[2]
        matched.append(best[1])
    if any(
        matched[index] - matched[index - 1] < (fallback[index] - fallback[index - 1]) * 0.8
        for index in range(1, len(matched))
    ):
        return fallback
    return tuple(matched)
