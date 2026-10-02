"""Bounded multi-label route scanning; never joins three frontier products.

Keep several distinct line combinations per stop and scan every useful pattern
once per boarding round. This is a bounded alternative search, not enumeration
of every possible journey. Calendar intersections and real platforms survive.
"""
from dataclasses import dataclass

from api.app.data.transport import public_line_code
from api.app.routing.direct import direct
from api.app.routing.metrics import (
    BOARDING_WAIT_MINUTES, DWELL_MINUTES_PER_STOP, FIRST_TRAM_BONUS_MINUTES,
    TRANSFER_COST, journey_rank, ride_minutes_per_metre, walking_cost,
)
from api.app.schemas.itinerary import Itinerary, leg_from_pattern, walking_leg
from api.app.schemas.snapshot import Weekday

WIDTH = 10


@dataclass(frozen=True, slots=True)
class Label:
    cost: float
    legs: tuple
    days: frozenset
    lines: tuple


def retain(table, stop, label, width):
    bucket = table.setdefault(stop, [])
    for old in bucket:
        if old.lines == label.lines and old.days == label.days:
            if old.cost <= label.cost:
                return
            bucket.remove(old)
            break
    bucket.append(label)
    bucket.sort(key=lambda x: (x.cost, x.lines))
    del bucket[width:]


def worthwhile(table, stop, cost, lines, days, width):
    bucket = table.get(stop, ())
    for old in bucket:
        if old.lines == lines and old.days == days:
            return cost < old.cost
    return len(bucket) < width or cost < bucket[-1].cost


def walk_connections(indexes, labels, width, routing_mode):
    result = {s: list(values) for s, values in labels.items()}
    # Only one foot edge per round: no unlimited chains through the city.
    for stop, values in labels.items():
        for neighbor, metres in indexes.walking_neighbors[stop]:
            foot = walking_leg(board_stop=stop, alight_stop=neighbor, metres=metres)
            for label in values:
                cost = label.cost + walking_cost(metres, routing_mode)
                if not worthwhile(result, neighbor, cost, label.lines, label.days, width):
                    continue
                retain(result, neighbor, Label(cost,
                    label.legs + (foot,), label.days, label.lines), width)
    return result


def _nearby(indexes, endpoints):
    """Map each accessible stop to its closest requested endpoint."""

    result = {}
    for endpoint in endpoints:
        for stop, metres in ((endpoint, 0),) + indexes.walking_neighbors[endpoint]:
            if stop not in result or metres < result[stop][1]:
                result[stop] = (endpoint, metres)
    return result


def _direct_answers(indexes, origins, destinations, routing_mode, answers, counts):
    """Keep every direct line before bounded transfer labels can prune it."""

    access = _nearby(indexes, origins)
    egress = _nearby(indexes, destinations)
    for board_stop, (origin, access_metres) in access.items():
        candidate_patterns = indexes.routes_at_stop[board_stop]
        for alight_stop, (destination, egress_metres) in egress.items():
            if not candidate_patterns.intersection(indexes.routes_at_stop[alight_stop]):
                continue
            for ride in direct(indexes, board_stop, alight_stop):
                legs = list(ride.legs)
                if board_stop != origin:
                    legs.insert(0, walking_leg(board_stop=origin, alight_stop=board_stop, metres=access_metres))
                if alight_stop != destination:
                    legs.append(walking_leg(board_stop=alight_stop, alight_stop=destination, metres=egress_metres))
                journey = Itinerary(tuple(legs))
                line = (ride.legs[0].mode, public_line_code(ride.legs[0].route_code or ride.legs[0].route_id))
                cost = journey_rank(indexes, journey, routing_mode)
                old = answers.get((line,))
                if old is None or cost < old[0]:
                    answers[(line,)] = (cost, journey)
                counts["direct"] += 1


def scan_routes(indexes, origins, destinations, limit, counts, routing_mode="fewest_transfers"):
    width = max(WIDTH, min(limit * 2, 20))
    labels = {s: [Label(0, (), frozenset(Weekday), ())] for s in origins}
    destinations = set(destinations)
    answers = {}
    counts.update(direct=0, one_transfer=0, two_transfers=0)
    # Nearby named stops can be reached entirely on foot, without boarding a bus.
    for origin in origins:
        for neighbor, metres in indexes.walking_neighbors[origin]:
            if neighbor in destinations:
                journey = Itinerary((walking_leg(
                    board_stop=origin, alight_stop=neighbor, metres=metres,
                ),))
                current = answers.get(())
                cost = journey_rank(indexes, journey, routing_mode)
                if current is None or cost < current[0]:
                    answers[()] = (cost, journey)
    _direct_answers(indexes, origins, destinations, routing_mode, answers, counts)
    for round_number in range(1, 5):
        category = ('direct', 'one_transfer', 'two_transfers', 'three_transfers')[round_number - 1]
        counts.setdefault(category, 0)
        boarding = walk_connections(indexes, labels, width, routing_mode)
        useful = set()
        for stop in boarding:
            useful.update(indexes.routes_at_stop[stop])
        reached = {}
        for pid in sorted(useful):
            pattern = indexes.patterns[pid]
            boardable = indexes.boardable_positions[pid]
            alightable = indexes.alightable_positions[pid]
            metres_at_stop = indexes.metres_at_position[pid]
            ride_cost_per_metre = ride_minutes_per_metre(pattern.mode, routing_mode)
            line = (pattern.mode, public_line_code(pattern.route_code or pattern.route_id))
            onboard = []
            for position, stop in enumerate(pattern.stop_ids):
                for base, board_position, offset, days in (onboard if position in alightable else ()):
                    cost = offset + metres_at_stop[position] * ride_cost_per_metre + position * DWELL_MINUTES_PER_STOP
                    lines = base.lines + (line,)
                    if not worthwhile(reached, stop, cost, lines, days, width):
                        continue
                    leg = leg_from_pattern(pattern, board_stop=pattern.stop_ids[board_position],
                        alight_stop=stop, board_index=board_position, alight_index=position)
                    retain(reached, stop, Label(cost,
                        base.legs + (leg,), days, lines), width)
                for base in (boarding.get(stop, ()) if position in boardable else ()):
                    if line in base.lines:
                        continue
                    days = base.days & pattern.operating_days
                    if not days:
                        continue
                    tram_bonus = (
                        FIRST_TRAM_BONUS_MINUTES if routing_mode == "prefer_tram" and pattern.mode == "Tramvay"
                        and not any(mode == "Tramvay" for mode, _ in base.lines) else 0
                    )
                    offset = (base.cost + BOARDING_WAIT_MINUTES
                              + (TRANSFER_COST[routing_mode] if base.lines else 0)
                              - metres_at_stop[position] * ride_cost_per_metre
                              - position * DWELL_MINUTES_PER_STOP - tram_bonus)
                    candidate = (base, position, offset, days)
                    # Multiple GTFS occurrences of the same history need only
                    # the cheapest boarding for the remaining suffix.
                    equivalent = next((x for x in onboard if x[0].lines == base.lines and x[3] == days), None)
                    if equivalent is not None:
                        if equivalent[2] <= offset:
                            continue
                        onboard.remove(equivalent)
                    onboard.append(candidate)
                    onboard.sort(key=lambda x: x[2])
                    del onboard[width:]
        # Egress uses the same single-edge walking rule, including zero-metre
        # edges between distinct, co-located platform IDs.
        for dest in destinations:
            for stop, metres in ((dest, None),) + tuple(indexes.walking_neighbors[dest]):
                for label in reached.get(stop, ()):
                    legs = label.legs
                    cost = label.cost
                    if metres is not None:
                        legs += (walking_leg(board_stop=stop, alight_stop=dest, metres=metres),)
                        cost += walking_cost(metres, routing_mode)
                    journey = Itinerary(legs)
                    cost = journey_rank(indexes, journey, routing_mode)
                    current = answers.get(label.lines)
                    if current is None or cost < current[0]:
                        answers[label.lines] = (cost, journey)
                    if round_number > 1:  # direct candidates were counted above
                        counts[category] += 1
        labels = reached
        if not labels:
            break
    # Use the same rank for representatives and the final top K. A distance-only
    # re-sort here used to discard the search's transfer penalty.
    ordered = sorted(answers.items(), key=lambda item: (item[1][0], item[0]))
    return [entry[1] for _, entry in ordered[:limit]]
