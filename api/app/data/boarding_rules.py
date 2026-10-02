"""Supplement GTFS pickup/drop-off flags with published location rules.

Source: https://www.ulasimpark.com.tr/otobus/indi-bindi-kurallari
The feed already marks most restricted stops. These entries cover rules that
are absent from its pickup_type/drop_off_type columns. A named landmark is
snapped only to a stop on the same directional pattern, within 800 metres.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Mapping

from api.app.schemas.snapshot import Pattern, Stop, StopId


logger = logging.getLogger(__name__)
MAX_SNAP_METRES = 800


@dataclass(frozen=True)
class LocationRule:
    line: str
    direction: str
    landmark_stop_id: str
    permission: str  # "board" or "alight"
    side: str  # "before", "through", "from", or "after"


# The website's place names are linked to the nearest matching feed stop.
# "From" includes that stop; "after" starts at its next occurrence.
LOCATION_RULES = (
    LocationRule("405", "0", "98179", "board", "from"),  # Hereke Kahveler
    LocationRule("435", "0", "98179", "board", "from"),
    LocationRule("530", "0", "98179", "board", "from"),
    LocationRule("305", "1", "98029", "alight", "before"),  # 95 Evler kavşağı
    LocationRule("305", "1", "41239", "board", "after"),  # Dilovası D-100 eski ışıklar
    LocationRule("KM77", "0", "94182", "board", "after"),  # 109. Cadde 1
    LocationRule("KM77", "0", "94025", "alight", "before"),  # Çamçukur Tepe Camii
    LocationRule("KM26", "0", "10188", "alight", "through"),  # Hamdi Taşdemir Caddesi
    LocationRule("KM26", "0", "10378", "board", "after"),  # Yuvacık Merkez
)


def published_permissions(
    pattern: Pattern, stops: Mapping[StopId, Stop]
) -> tuple[frozenset[int], frozenset[int]]:
    """Intersect GTFS flags with location rules for this line and direction."""

    count = len(pattern.stop_ids)
    boardable = {i for i in range(count) if not pattern.pickup_allowed or pattern.pickup_allowed[i]}
    alightable = {i for i in range(count) if not pattern.dropoff_allowed or pattern.dropoff_allowed[i]}
    for rule in LOCATION_RULES:
        if rule.line != pattern.route_code or rule.direction != pattern.direction_id:
            continue
        anchor = _nearest_pattern_position(pattern, stops, rule.landmark_stop_id)
        if anchor is None:
            logger.warning("No stop on %s/%s near published landmark %s", rule.line, rule.direction, rule.landmark_stop_id)
            continue
        prohibited = (
            range(anchor) if rule.side == "before" else
            range(anchor + 1) if rule.side == "through" else
            range(anchor, count) if rule.side == "from" else
            range(anchor + 1, count)
        )
        (boardable if rule.permission == "board" else alightable).difference_update(prohibited)
    return frozenset(boardable), frozenset(alightable)


def _nearest_pattern_position(
    pattern: Pattern, stops: Mapping[StopId, Stop], landmark_gtfs_id: str
) -> int | None:
    for position, stop_id in enumerate(pattern.stop_ids):
        if stops[stop_id].gtfs_id == landmark_gtfs_id:
            return position
    landmark = next((stop for stop in stops.values() if stop.gtfs_id == landmark_gtfs_id), None)
    if landmark is None or landmark.latitude is None or landmark.longitude is None:
        return None
    candidates = (
        (_metres(landmark, stops[stop_id]), position)
        for position, stop_id in enumerate(pattern.stop_ids)
        if stops[stop_id].latitude is not None and stops[stop_id].longitude is not None
    )
    closest = min(candidates, default=None)
    return closest[1] if closest is not None and closest[0] <= MAX_SNAP_METRES else None


def _metres(first: Stop, second: Stop) -> float:
    lat1, lon1 = radians(first.latitude), radians(first.longitude)
    lat2, lon2 = radians(second.latitude), radians(second.longitude)
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 12_742_000 * asin(sqrt(a))
