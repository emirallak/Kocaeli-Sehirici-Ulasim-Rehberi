"""Frequency-based, bounded multi-label RAPTOR.

Queue each route once per boarding round at its earliest marked occurrence.
Relax footpaths only from ride arrivals; parent links defer journey allocation.
The snapshot lacks timetables, so costs retain average speeds and assumed waits.
Line-history bags preserve UI alternatives with a bounded width, rather than
claiming exhaustive timetable Pareto optimality. Four rides are supported.
"""
from bisect import bisect_right
from dataclasses import dataclass, replace
from math import cos, hypot, radians

from api.app.data.transport import public_line_code
from api.app.routing.grouping import label_path, PathMatcher, ride_steps
from api.app.routing.metrics import (
    BOARDING_WAIT_MINUTES, DWELL_MINUTES_PER_STOP, FIRST_TRAM_BONUS_MINUTES,
    TRANSFER_COST, ride_minutes_per_metre, walking_cost,
)
from api.app.schemas.itinerary import Itinerary, leg_from_pattern, walking_leg
from api.app.schemas.snapshot import Weekday

WIDTH = 10
MAX_RIDES = 4
# Shapes and stop projections can make a ride marginally shorter than the
# straight line; shrink the remaining-distance bound so it stays admissible.
BOUND_SCALE = 0.9
BOUND_SLACK_METRES = 300


@dataclass(frozen=True, slots=True)
class Label:
    stop: int
    cost: float
    walking: int
    days: frozenset
    lines: tuple
    parent: 'Label | None' = None
    # Ride: (pattern_id, board_index, alight_index); walk: (None, metres).
    step: tuple = ()
    # Whether ``lines`` already contains a tram; avoids rescanning per check.
    tram: bool = False


class Bag:
    """A stop's labels sorted by (cost, walking, lines), one per line history.

    ``by_key`` makes the same-history lookup O(1); ``keys`` mirrors ``labels``
    for bisect insertion. Equal keys keep insertion order, as a stable sort.
    """
    __slots__ = ('keys', 'labels', 'by_key')

    def __init__(self, keys=(), labels=(), by_key=None):
        self.keys = list(keys)
        self.labels = list(labels)
        self.by_key = dict(by_key or {})

    def copy(self):
        return Bag(self.keys, self.labels, self.by_key)

    def __iter__(self):
        return iter(self.labels)

    def __len__(self):
        return len(self.labels)


def retain(table, label, width):
    bag = table.get(label.stop)
    if bag is None:
        bag = table[label.stop] = Bag()
    history = (label.lines, label.days)
    old = bag.by_key.get(history)
    if old is not None:
        if (old.cost, old.walking) <= (label.cost, label.walking):
            return False
        index = next(i for i, value in enumerate(bag.labels) if value is old)
        del bag.keys[index], bag.labels[index]
    key = (label.cost, label.walking, label.lines)
    index = bisect_right(bag.keys, key)
    if index >= width:
        if old is not None:
            del bag.by_key[history]
        return False
    bag.keys.insert(index, key)
    bag.labels.insert(index, label)
    bag.by_key[history] = label
    if len(bag.labels) > width:
        dropped = bag.labels.pop()
        bag.keys.pop()
        del bag.by_key[(dropped.lines, dropped.days)]
    return True


def worthwhile(table, stop, cost, walking, lines, days, width):
    bag = table.get(stop)
    if bag is None:
        return True
    old = bag.by_key.get((lines, days))
    if old is not None:
        return (cost, walking) < (old.cost, old.walking)
    return len(bag.labels) < width or (cost, walking, lines) < bag.keys[-1]


def foot_label(base, stop, metres, routing_mode):
    return Label(stop, base.cost + walking_cost(metres, routing_mode),
                 base.walking + metres, base.days, base.lines, base, (None, metres), base.tram)


def relax_footpaths(indexes, labels, width, routing_mode, hopeless=None):
    """Add one foot edge to each label; ``hopeless(cost, tram, stop)`` drops some.

    This is the hottest loop of a query, so ``worthwhile`` is inlined.
    """
    # Never chain newly generated foot labels across the city.
    result = {stop: bag.copy() for stop, bag in labels.items()}
    walking_neighbors = indexes.walking_neighbors
    for stop, bag in labels.items():
        bases = bag.labels
        for neighbor, metres in walking_neighbors[stop]:
            walk = walking_cost(metres, routing_mode)
            target = result.get(neighbor)
            for base in bases:
                cost = base.cost + walk
                if hopeless is not None and hopeless(cost, base.tram, neighbor):
                    continue
                walking = base.walking + metres
                if target is not None:
                    old = target.by_key.get((base.lines, base.days))
                    if old is not None:
                        if (cost, walking) >= (old.cost, old.walking):
                            continue
                    elif len(target.labels) >= width and (cost, walking, base.lines) >= target.keys[-1]:
                        continue
                retain(result, Label(neighbor, cost, walking, base.days, base.lines,
                                     base, (None, metres), base.tram), width)
                if target is None:
                    target = result[neighbor]
    return result


def route_queue(indexes, marked):
    queue = {}
    for stop in marked:
        for pid, position in indexes.occurrences_at_stop[stop]:
            if position in indexes.boardable_positions[pid]:
                queue[pid] = min(position, queue.get(pid, position))
    return queue


def label_rank(label, routing_mode):
    transfers = max(0, len(label.lines) - 1)
    if routing_mode == 'fewest_transfers':
        return transfers, label.cost, label.walking
    return label.cost, transfers, label.walking


def reconstruct(indexes, label):
    legs = []
    while label.parent is not None:
        base = label.parent
        if label.step[0] is None:
            legs.append(walking_leg(board_stop=base.stop, alight_stop=label.stop,
                                    metres=label.step[1]))
        else:
            pid, board, alight = label.step
            pattern = indexes.patterns[pid]
            legs.append(leg_from_pattern(pattern, board_stop=base.stop,
                        alight_stop=label.stop, board_index=board, alight_index=alight))
        label = base
    return Itinerary(tuple(reversed(legs)))


def raptor_routes(indexes, origins, destinations, limit, counts, routing_mode="fewest_transfers", *, group_paths=False):
    width = max(WIDTH, min(limit * 2, 20))
    counts.update(direct=0, one_transfer=0, two_transfers=0, three_transfers=0,
                  rounds=0, route_scans=0, scanned_positions=0)
    if limit <= 0 or not origins or not destinations:
        return []
    origins, destinations = set(origins), set(destinations)
    boarding = {}
    for stop in origins:
        retain(boarding, Label(stop, 0, 0, frozenset(Weekday), ()), width)
    boarding = relax_footpaths(indexes, boarding, width, routing_mode)
    # Reverse actual foot edges so egress does not assume symmetry.
    egress = {stop: (stop, 0) for stop in destinations}
    for stop, neighbors in indexes.walking_neighbors.items():
        if stop in destinations:
            continue
        for neighbor, metres in neighbors:
            if neighbor in destinations and metres < egress.get(stop, (None, float('inf')))[1]:
                egress[stop] = (neighbor, metres)
    answers = {}
    matcher = PathMatcher(indexes) if group_paths else None
    anchors = {}

    worst_rank = None
    # Cost a label may still spend in cost-ranked modes; only shrinks.
    budget = float('inf')
    prunes_by_cost = routing_mode != 'fewest_transfers'

    def offer(label):
        nonlocal worst_rank, budget
        if not label.parent or label.stop not in egress:
            return
        dest, metres = egress[label.stop]
        if dest != label.stop:
            if label.step[0] is None:
                return  # No two consecutive foot edges.
            candidate = foot_label(label, dest, metres, routing_mode)
        else:
            candidate = label
        rank = label_rank(candidate, routing_mode)
        if worst_rank is not None and rank > worst_rank:
            return
        key = label_path(indexes, candidate) if group_paths else candidate.lines
        if group_paths and key not in answers:
            # Compare against a stable anchor to avoid transitive A≈B≈C
            # grouping when A and C are substantially different.
            key = next((old_key for old_key, anchor in anchors.items()
                        if matcher.same_journey(anchor, candidate)), key)
        old = answers.get(key)
        if old is not None and rank >= label_rank(old, routing_mode):
            return
        answers[key] = candidate
        if group_paths:
            anchors.setdefault(key, candidate)
        if len(answers) > limit:
            worst = max(answers, key=lambda k: (label_rank(answers[k], routing_mode), k))
            del answers[worst]
            anchors.pop(worst, None)
        worst_rank = (max(label_rank(x, routing_mode) for x in answers.values())
                      if len(answers) == limit else None)
        if prunes_by_cost and worst_rank is not None:
            budget = worst_rank[0]

    prefer_tram = routing_mode == 'prefer_tram'
    transfer_cost = TRANSFER_COST[routing_mode]
    # Riding is the cheapest way to cover distance (walking costs more per
    # metre in every mode), so this rate times the straight-line distance to
    # the nearest destination never overestimates the remaining cost.
    cheapest_rate = min(ride_minutes_per_metre(mode, routing_mode) for mode in ('Otobüs', 'Tramvay'))
    targets = [(stop.latitude, stop.longitude) for stop_id in destinations
               if (stop := indexes.stops[stop_id]).latitude is not None and stop.longitude is not None]
    remaining = {}

    def lower_bound(stop_id):
        value = remaining.get(stop_id)
        if value is None:
            stop = indexes.stops[stop_id]
            value = 0.0
            if targets and stop.latitude is not None and stop.longitude is not None:
                scale = cos(radians(stop.latitude))
                metres = min(hypot(stop.latitude - lat, (stop.longitude - lon) * scale)
                             for lat, lon in targets) * 111_195
                value = max(0.0, metres * BOUND_SCALE - BOUND_SLACK_METRES) * cheapest_rate
            remaining[stop_id] = value
        return value

    def least_cost(cost, tram, stop):
        """The least final cost any extension of such a label could reach."""
        # The only negative extension cost is the one-time tram preference.
        bonus = FIRST_TRAM_BONUS_MINUTES if prefer_tram and not tram else 0
        return cost - bonus + lower_bound(stop)

    def need(label):
        return least_cost(label.cost, label.tram, label.stop)

    def hopeless(cost, tram, stop):
        return budget != float('inf') and least_cost(cost, tram, stop) > budget

    def can_extend(label):
        return not prunes_by_cost or not hopeless(label.cost, label.tram, label.stop)

    for bag in boarding.values():
        for label in bag:
            offer(label)
    for round_number in range(1, MAX_RIDES + 1):
        if budget != float('inf'):
            # The budget only shrinks, so a label over it now stays unusable
            # for the whole round; leave its routes out of the queue.
            boarding = {stop: kept for stop, bag in boarding.items()
                        if (kept := [base for base in bag if need(base) <= budget])}
        queue = route_queue(indexes, boarding)
        if not queue:
            break
        counts['rounds'] += 1
        final_round = round_number == MAX_RIDES
        reached = {}
        # Evaluate each boarding label once per round, not once per route.
        boarders = {stop: [(base, need(base) if prunes_by_cost else 0) for base in bag]
                    for stop, bag in boarding.items()}
        for pid, start in sorted(queue.items()):
            counts['route_scans'] += 1
            pattern = indexes.patterns[pid]
            positions = indexes.metres_at_position[pid]
            alightable = indexes.alightable_positions[pid]
            boardable = indexes.boardable_positions[pid]
            stop_ids = pattern.stop_ids
            is_tram = pattern.mode == 'Tramvay'
            rate = ride_minutes_per_metre(pattern.mode, routing_mode)
            line = (pattern.mode, public_line_code(pattern.route_code or pattern.route_id))
            onboard = {}
            counts['scanned_positions'] += len(stop_ids) - start
            for position in range(start, len(stop_ids)):
                stop = stop_ids[position]
                suffix_cost = positions[position] * rate + position * DWELL_MINUTES_PER_STOP
                at_egress = stop in egress
                # Arrivals of the final round are never boarded again.
                if onboard and position in alightable and (at_egress or not final_round):
                    if budget != float('inf'):
                        # Ride cost only grows along the route, so an entry over
                        # the K-th answer now can never produce a useful label.
                        for key in [key for key, entry in onboard.items()
                                    if entry[2] + suffix_cost - (0 if entry[5] or not prefer_tram
                                                                 else FIRST_TRAM_BONUS_MINUTES)
                                    > budget]:
                            del onboard[key]
                    target = reached.get(stop)
                    for base, board, offset, days, lines, tram in onboard.values():
                        cost = offset + suffix_cost
                        if final_round:
                            offer(Label(stop, cost, base.walking, days,
                                        lines, base, (pid, board, position), tram))
                            continue
                        # Inlined ``worthwhile``: this runs per stop and onboard entry.
                        useful = True
                        if target is not None:
                            old = target.by_key.get((lines, days))
                            if old is not None:
                                useful = (cost, base.walking) < (old.cost, old.walking)
                            elif len(target.labels) >= width:
                                useful = (cost, base.walking, lines) < target.keys[-1]
                        if not useful and not at_egress:
                            continue
                        label = Label(stop, cost, base.walking, days,
                                      lines, base, (pid, board, position), tram)
                        # Harvest destination alternatives before the stop bag cap.
                        if at_egress:
                            offer(label)
                        if useful and can_extend(label):
                            retain(reached, label, width)
                            if target is None:
                                target = reached[stop]
                if position not in boardable:
                    continue
                for base, least in boarders.get(stop, ()):
                    if least > budget or line in base.lines:
                        continue
                    days = base.days & pattern.operating_days
                    if not days:
                        continue
                    bonus = (FIRST_TRAM_BONUS_MINUTES
                             if prefer_tram and is_tram and not base.tram else 0)
                    offset = (base.cost + BOARDING_WAIT_MINUTES - suffix_cost - bonus
                              + (transfer_cost if base.lines else 0))
                    key = (base.lines, days)
                    old = onboard.get(key)
                    if old is None or (offset, base.walking) < (old[2], old[0].walking):
                        onboard[key] = (base, position, offset, days, base.lines + (line,),
                                        base.tram or is_tram)
                    # Bound the onboard bag as well as each stop bag.
                    if len(onboard) > width:
                        worst = max(onboard, key=lambda k: (onboard[k][2], onboard[k][0].walking, k))
                        del onboard[worst]
        # Future rounds necessarily add a ride. Once K lower-round answers
        # exist, fewest-transfers cannot improve them (all direct lines were
        # harvested without the bag cap during the complete first scan).
        if routing_mode == 'fewest_transfers' and len(answers) >= limit:
            break
        if not reached:
            break
        boarding = relax_footpaths(indexes, reached, width, routing_mode,
                                   hopeless if prunes_by_cost else None)
    for label in answers.values():
        if label.lines:
            category = ('direct', 'one_transfer', 'two_transfers', 'three_transfers')[len(label.lines) - 1]
            counts[category] += 1
    ordered = sorted(answers.items(), key=lambda item: (label_rank(item[1], routing_mode), item[1].lines))
    result = []
    for key, label in ordered[:limit]:
        journey = reconstruct(indexes, label)
        if group_paths:
            references = iter(ride_steps(anchors[key]))
            journey = replace(journey, legs=tuple(
                replace(leg, grouping_reference=next(references)) if not leg.is_walking else leg
                for leg in journey.legs))
        result.append(journey)
    return result
