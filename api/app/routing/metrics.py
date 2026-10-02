"""Shared travel-time estimates and routing-mode costs."""

from __future__ import annotations

from typing import Literal

from api.app.schemas.itinerary import Itinerary, Leg
from api.app.schemas.snapshot import RoutingIndexes

RoutingMode = Literal["fastest", "fewest_transfers", "minimal_walking", "prefer_tram"]
ROUTING_MODES = ("fastest", "fewest_transfers", "minimal_walking", "prefer_tram")
BOARDING_WAIT_MINUTES = 5
DWELL_MINUTES_PER_STOP = 0.25
TRANSFER_COST = {
    "fastest": 0,
    "fewest_transfers": 10_000,  # Strictly prioritize transfer count.
    "minimal_walking": 2,
    "prefer_tram": 2,
}
WALK_COST_MULTIPLIER = {
    "fastest": 1,
    "fewest_transfers": 1,
    "minimal_walking": 5,
    "prefer_tram": 1,
}
TRAM_RIDE_COST_MULTIPLIER = 0.55
FIRST_TRAM_BONUS_MINUTES = 8


def leg_metres(indexes: RoutingIndexes, leg: Leg) -> float:
    if leg.is_walking:
        return float(leg.walking_metres or 0)
    assert leg.pattern_id is not None
    positions = indexes.metres_at_position[leg.pattern_id]
    return max(0.0, positions[leg.alight_index] - positions[leg.board_index])


def itinerary_metres(indexes: RoutingIndexes, itinerary: Itinerary) -> float:
    return sum(leg_metres(indexes, leg) for leg in itinerary.legs)


def ride_minutes_per_metre(mode: str, routing_mode: RoutingMode) -> float:
    minutes_per_metre = 1 / (400 if mode == "Tramvay" else 1000 / 3)
    if routing_mode == "prefer_tram" and mode == "Tramvay":
        minutes_per_metre *= TRAM_RIDE_COST_MULTIPLIER
    return minutes_per_metre


def walking_cost(metres: float, routing_mode: RoutingMode) -> float:
    return metres / 80 * WALK_COST_MULTIPLIER[routing_mode]


def leg_minutes(indexes: RoutingIndexes, leg: Leg) -> float:
    metres = leg_metres(indexes, leg)
    if leg.is_walking:
        return metres / 80
    return metres * ride_minutes_per_metre(leg.mode, "fastest") + (leg.alight_index - leg.board_index) * DWELL_MINUTES_PER_STOP


def itinerary_minutes(indexes: RoutingIndexes, itinerary: Itinerary) -> float:
    return sum(leg_minutes(indexes, leg) for leg in itinerary.legs) + itinerary.transit_leg_count * BOARDING_WAIT_MINUTES


def journey_cost(indexes: RoutingIndexes, itinerary: Itinerary, routing_mode: RoutingMode = "fewest_transfers") -> float:
    cost = 0.0
    tram_seen = False
    ride_count = 0
    for leg in itinerary.legs:
        if leg.is_walking:
            cost += walking_cost(leg.walking_metres or 0, routing_mode)
            continue
        if ride_count:
            cost += TRANSFER_COST[routing_mode]
        cost += BOARDING_WAIT_MINUTES
        cost += leg_metres(indexes, leg) * ride_minutes_per_metre(leg.mode, routing_mode)
        cost += (leg.alight_index - leg.board_index) * DWELL_MINUTES_PER_STOP
        if routing_mode == "prefer_tram" and leg.mode == "Tramvay" and not tram_seen:
            cost -= FIRST_TRAM_BONUS_MINUTES
            tram_seen = True
        ride_count += 1
    return cost


def journey_rank(indexes: RoutingIndexes, itinerary: Itinerary, routing_mode: RoutingMode = "fewest_transfers") -> tuple:
    transfers = max(0, itinerary.transit_leg_count - 1)
    cost = journey_cost(indexes, itinerary, routing_mode)
    walking = sum(leg.walking_metres or 0 for leg in itinerary.legs)
    if routing_mode == "fewest_transfers":
        return transfers, cost, walking
    return cost, transfers, walking
