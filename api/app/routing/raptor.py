"""Frequency-based, bounded multi-label RAPTOR.

Queue each route once per boarding round at its earliest marked occurrence.
Relax footpaths only from ride arrivals; parent links defer journey allocation.
The snapshot lacks timetables, so costs retain average speeds and assumed waits.
Line-history bags preserve UI alternatives with a bounded width, rather than
claiming exhaustive timetable Pareto optimality. Four rides are supported.
"""
from dataclasses import dataclass

from api.app.data.transport import public_line_code
from api.app.routing.grouping import label_path
from api.app.routing.metrics import (
    BOARDING_WAIT_MINUTES, DWELL_MINUTES_PER_STOP, FIRST_TRAM_BONUS_MINUTES,
    TRANSFER_COST, ride_minutes_per_metre, walking_cost,
)
from api.app.schemas.itinerary import Itinerary, leg_from_pattern, walking_leg
from api.app.schemas.snapshot import Weekday

WIDTH = 10
MAX_RIDES = 4


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


def retain(table, label, width):
    bucket = table.setdefault(label.stop, [])
    for old in bucket:
        if old.lines == label.lines and old.days == label.days:
            if (old.cost, old.walking) <= (label.cost, label.walking):
                return False
            bucket.remove(old)
            break
    bucket.append(label)
    bucket.sort(key=lambda x: (x.cost, x.walking, x.lines))
    del bucket[width:]
    return any(value is label for value in bucket)


def worthwhile(table, stop, cost, walking, lines, days, width):
    bucket = table.get(stop, ())
    for old in bucket:
        if old.lines == lines and old.days == days:
            return (cost, walking) < (old.cost, old.walking)
    return len(bucket) < width or (cost, walking, lines) < (
        bucket[-1].cost, bucket[-1].walking, bucket[-1].lines)


def foot_label(base, stop, metres, routing_mode):
    return Label(stop, base.cost + walking_cost(metres, routing_mode),
                 base.walking + metres, base.days, base.lines, base, (None, metres))


def relax_footpaths(indexes, labels, width, routing_mode):
    # Never chain newly generated foot labels across the city.
    result = {stop: list(bag) for stop, bag in labels.items()}
    for stop, bag in labels.items():
        for neighbor, metres in indexes.walking_neighbors[stop]:
            for base in bag:
                cost = base.cost + walking_cost(metres, routing_mode)
                if worthwhile(result, neighbor, cost, base.walking + metres,
                              base.lines, base.days, width):
                    retain(result, foot_label(base, neighbor, metres, routing_mode), width)
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
    boarding = relax_footpaths(indexes, {
        stop: [Label(stop, 0, 0, frozenset(Weekday), ())] for stop in origins
    }, width, routing_mode)
    # Reverse actual foot edges so egress does not assume symmetry.
    egress = {stop: (stop, 0) for stop in destinations}
    for stop, neighbors in indexes.walking_neighbors.items():
        if stop in destinations:
            continue
        for neighbor, metres in neighbors:
            if neighbor in destinations and metres < egress.get(stop, (None, float('inf')))[1]:
                egress[stop] = (neighbor, metres)
    answers = {}

    worst_rank = None

    def offer(label):
        nonlocal worst_rank
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
        old = answers.get(key)
        if old is not None and rank >= label_rank(old, routing_mode):
            return
        answers[key] = candidate
        if len(answers) > limit:
            worst = max(answers, key=lambda k: (label_rank(answers[k], routing_mode), k))
            del answers[worst]
        worst_rank = (max(label_rank(x, routing_mode) for x in answers.values())
                      if len(answers) == limit else None)

    def can_extend(label):
        if worst_rank is None or routing_mode == 'fewest_transfers':
            return True
        # The only negative extension cost is the one-time tram preference.
        bonus = (FIRST_TRAM_BONUS_MINUTES if routing_mode == 'prefer_tram'
                 and not any(mode == 'Tramvay' for mode, _ in label.lines) else 0)
        return label.cost - bonus <= worst_rank[0]

    for bag in boarding.values():
        for label in bag:
            offer(label)
    for round_number in range(1, MAX_RIDES + 1):
        queue = route_queue(indexes, boarding)
        if not queue:
            break
        counts['rounds'] += 1
        reached = {}
        for pid, start in sorted(queue.items()):
            counts['route_scans'] += 1
            pattern = indexes.patterns[pid]
            positions = indexes.metres_at_position[pid]
            rate = ride_minutes_per_metre(pattern.mode, routing_mode)
            line = (pattern.mode, public_line_code(pattern.route_code or pattern.route_id))
            onboard = {}
            for position in range(start, len(pattern.stop_ids)):
                counts['scanned_positions'] += 1
                stop = pattern.stop_ids[position]
                suffix_cost = positions[position] * rate + position * DWELL_MINUTES_PER_STOP
                if position in indexes.alightable_positions[pid]:
                    for base, board, offset, days, lines in onboard.values():
                        cost = offset + suffix_cost
                        useful = worthwhile(reached, stop, cost, base.walking, lines, days, width)
                        if not useful and stop not in egress:
                            continue
                        label = Label(stop, cost, base.walking, days,
                                      lines, base, (pid, board, position))
                        # Harvest destination alternatives before the stop bag cap.
                        if stop in egress:
                            offer(label)
                        if useful and can_extend(label):
                            retain(reached, label, width)
                if position not in indexes.boardable_positions[pid]:
                    continue
                for base in boarding.get(stop, ()):
                    if line in base.lines or not can_extend(base):
                        continue
                    days = base.days & pattern.operating_days
                    if not days:
                        continue
                    bonus = (FIRST_TRAM_BONUS_MINUTES
                             if routing_mode == 'prefer_tram' and pattern.mode == 'Tramvay'
                             and not any(mode == 'Tramvay' for mode, _ in base.lines) else 0)
                    offset = (base.cost + BOARDING_WAIT_MINUTES - suffix_cost - bonus
                              + (TRANSFER_COST[routing_mode] if base.lines else 0))
                    key = (base.lines, days)
                    old = onboard.get(key)
                    if old is None or (offset, base.walking) < (old[2], old[0].walking):
                        onboard[key] = (base, position, offset, days, base.lines + (line,))
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
        boarding = relax_footpaths(indexes, reached, width, routing_mode)
    for label in answers.values():
        if label.lines:
            category = ('direct', 'one_transfer', 'two_transfers', 'three_transfers')[len(label.lines) - 1]
            counts[category] += 1
    ordered = sorted(answers.values(), key=lambda label: (label_rank(label, routing_mode), label.lines))
    return [reconstruct(indexes, label) for label in ordered[:limit]]
