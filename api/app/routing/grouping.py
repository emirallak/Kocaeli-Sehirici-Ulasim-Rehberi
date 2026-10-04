"""Exact, occurrence-aware journey-leg paths and interchangeable lines."""
from api.app.data.transport import public_line_code
from api.app.schemas.itinerary import leg_from_pattern


def label_path(indexes, label):
    """Walking boundaries and each ride's complete ordered physical stop IDs.

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


def matching_lines(indexes, leg, journey_days):
    """Find every line with this exact slice and legal boarding/alighting.

    Union service patterns for each published line before checking its days.
    Every advertised choice must cover the representative journey's days;
    mixing incompatible calendars between transfers is never offered.
    """
    if leg.is_walking or leg.pattern_id is None:
        return []
    source = indexes.patterns[leg.pattern_id]
    stop_ids = source.stop_ids[leg.board_index:leg.alight_index + 1]
    groups = {}
    for pid in sorted(indexes.routes_at_stop[leg.board_stop]):
        pattern = indexes.patterns[pid]
        if pattern.mode != leg.mode:
            continue
        for board in indexes.positions[pid][leg.board_stop]:
            alight = board + len(stop_ids) - 1
            if (board not in indexes.boardable_positions[pid]
                    or alight not in indexes.alightable_positions[pid]
                    or pattern.stop_ids[board:alight + 1] != stop_ids):
                continue
            code = public_line_code(pattern.route_code or pattern.route_id)
            group = groups.setdefault(code, {'code': code, 'days': set(), 'legs': []})
            group['days'].update(pattern.operating_days)
            group['legs'].append(leg_from_pattern(pattern, board_stop=leg.board_stop,
                alight_stop=leg.alight_stop, board_index=board, alight_index=alight))
    return sorted((group for group in groups.values() if journey_days <= group['days']),
                  key=lambda group: (group['code'] != public_line_code(leg.route_code or leg.route_id),
                                     group['code']))
