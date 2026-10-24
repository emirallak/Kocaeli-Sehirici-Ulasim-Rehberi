"""Occurrence-aware grouping with ordered stop overlap and GTFS shapes."""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from functools import lru_cache
from math import ceil, isfinite

from api.app.data.geometry import haversine
from api.app.data.transport import public_line_code
from api.app.schemas.itinerary import leg_from_pattern

STOP_OVERLAP = .90
SHAPE_TOLERANCE_METRES = 35
SHAPE_LENGTH_RATIO = 1.05


def ordered_overlap(first, second):
    """Longest common ordered subsequence, retaining duplicate occurrences."""
    positions = defaultdict(list)
    for index, stop in enumerate(second):
        positions[stop].append(index)
    tails = []
    for stop in first:
        for position in reversed(positions[stop]):
            index = bisect_left(tails, position)
            if index == len(tails):
                tails.append(position)
            else:
                tails[index] = position
    return len(tails)


def _point_at(pattern, metres):
    index = max(0, min(len(pattern.shape_points) - 2, bisect_right(pattern.shape_metres, metres) - 1))
    start, end = pattern.shape_metres[index:index + 2]
    fraction = max(0, min(1, (metres - start) / (end - start))) if end > start else 0
    a, b = pattern.shape_points[index:index + 2]
    return (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)


class PathMatcher:
    """Query-local caches; geometry is clipped to the boarding/alighting leg."""
    def __init__(self, indexes):
        self.indexes = indexes
        self.same_ride = lru_cache(maxsize=4096)(self._same_ride)

    def _same_ride(self, first, second):
        a, b = self.indexes.patterns[first[0]], self.indexes.patterns[second[0]]
        stops_a = a.stop_ids[first[1]:first[2] + 1]
        stops_b = b.stop_ids[second[1]:second[2] + 1]
        if (a.mode != b.mode or len(stops_a) < 2 or len(stops_b) < 2
                or stops_a[0] != stops_b[0] or stops_a[-1] != stops_b[-1]):
            return False
        if stops_a == stops_b:
            return True
        # Missing a loop occurrence changes the ride, rather than a stop label.
        loops_a = {sid: count for sid, count in Counter(stops_a).items() if count > 1}
        loops_b = {sid: count for sid, count in Counter(stops_b).items() if count > 1}
        if loops_a != loops_b:
            return False
        overlap = ordered_overlap(stops_a, stops_b)
        # Endpoints alone are a subset of every competing path between them;
        # require shared interior evidence or corroborating route geometry.
        if ((overlap >= 3 and overlap == min(len(stops_a), len(stops_b)))
                or overlap / max(len(stops_a), len(stops_b)) >= STOP_OVERLAP):
            return True
        return self._same_geometry(a, first[1:], b, second[1:])

    @staticmethod
    def _same_geometry(a, indices_a, b, indices_b):
        for pattern in (a, b):
            if (not pattern.shape_usable or len(pattern.shape_points) < 2
                    or len(pattern.shape_metres) != len(pattern.shape_points)
                    or len(pattern.metres_at_stop) != len(pattern.stop_ids)):
                return False
        start_a, end_a = (a.metres_at_stop[index] for index in indices_a)
        start_b, end_b = (b.metres_at_stop[index] for index in indices_b)
        length_a, length_b = end_a - start_a, end_b - start_b
        if not all(isfinite(value) for value in (start_a, end_a, start_b, end_b)):
            return False
        if min(length_a, length_b) <= 0 or max(length_a, length_b) / min(length_a, length_b) > SHAPE_LENGTH_RATIO:
            return False
        samples = min(2000, max(2, ceil(max(length_a, length_b) / 25)))
        for index in range(samples + 1):
            fraction = index / samples
            point_a = _point_at(a, start_a + fraction * length_a)
            point_b = _point_at(b, start_b + fraction * length_b)
            if not all(isfinite(value) for value in (*point_a, *point_b)):
                return False
            if haversine(*point_a, *point_b) > SHAPE_TOLERANCE_METRES:
                return False
        return True

    def same_journey(self, first, second):
        def steps(label):
            result = []
            while label.parent is not None:
                if label.step[0] is None:
                    result.append(('walk', (label.parent.stop, label.stop, label.step[1])))
                else:
                    result.append(('ride', label.step))
                label = label.parent
            return tuple(reversed(result))
        a, b = steps(first), steps(second)
        return len(a) == len(b) and all(
            kind_a == kind_b and (step_a == step_b if kind_a == 'walk' else self.same_ride(step_a, step_b))
            for (kind_a, step_a), (kind_b, step_b) in zip(a, b))


def label_path(indexes, label):
    """Exact signature used as an answer key alongside similarity matching.

    This is used before the answer limit, so parallel lines use one card slot.
    Mode remains distinct because bus/tram costs and preferences differ.
    """
    steps = []
    while label.parent is not None:
        if label.step[0] is None:
            steps.append(('walk', (label.parent.stop, label.stop), label.step[1]))
        else:
            pid, board, alight = label.step
            pattern = indexes.patterns[pid]
            steps.append((pattern.mode, pattern.stop_ids[board:alight + 1], 0))
        label = label.parent
    return tuple(reversed(steps))


def ride_steps(label):
    steps = []
    while label.parent is not None:
        if label.step[0] is not None:
            steps.append(label.step)
        label = label.parent
    return tuple(reversed(steps))


def matching_lines(indexes, leg, journey_days):
    """Find similar slices with legal boarding/alighting and compatible days.

    Union service patterns for each published line before checking its days.
    Every advertised choice must cover the representative journey's days;
    mixing incompatible calendars between transfers is never offered.
    """
    if leg.is_walking or leg.pattern_id is None:
        return []
    matcher = PathMatcher(indexes)
    source_slice = leg.grouping_reference or (leg.pattern_id, leg.board_index, leg.alight_index)
    groups = {}
    for pid in sorted(indexes.routes_at_stop[leg.board_stop]):
        pattern = indexes.patterns[pid]
        if pattern.mode != leg.mode:
            continue
        for board in indexes.positions[pid][leg.board_stop]:
            if board not in indexes.boardable_positions[pid]:
                continue
            for alight in indexes.positions[pid].get(leg.alight_stop, ()):
                if (alight <= board or alight not in indexes.alightable_positions[pid]
                        or not matcher.same_ride(source_slice, (pid, board, alight))):
                    continue
                code = public_line_code(pattern.route_code or pattern.route_id)
                group = groups.setdefault(code, {'code': code, 'days': set(), 'legs': []})
                group['days'].update(pattern.operating_days)
                group['legs'].append(leg_from_pattern(pattern, board_stop=leg.board_stop,
                    alight_stop=leg.alight_stop, board_index=board, alight_index=alight))
    return sorted((group for group in groups.values() if journey_days <= group['days']),
                  key=lambda group: (group['code'] != public_line_code(leg.route_code or leg.route_id),
                                     group['code']))
