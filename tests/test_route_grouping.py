"""Exact ride slices group before limiting; divergent platforms stay apart."""
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient
from api.index import app, _itinerary_to_response
from api.app.api.stops import build_stop_name_index
from api.app.data.indexes import build_indexes
from api.app.routing.grouping import matching_lines, label_path
from api.app.routing.raptor import Label
from api.app.routing.search import best_routes
from api.app.schemas.itinerary import leg_from_pattern
from api.app.schemas.snapshot import Pattern, RoutingSnapshot, Stop, Weekday

DAYS = frozenset({Weekday.MONDAY, Weekday.TUESDAY})


def graph(specs):
    stops = {sid: Stop(sid, str(sid), f'Stop {sid}', None, None) for sid in range(12)}
    patterns = {pid: Pattern(pid, str(pid), '0', tuple(seq), frozenset({'W'}), DAYS,
                             code, frozenset()) for pid, (code, seq) in enumerate(specs)}
    return build_indexes(stops, patterns)


class RouteGroupingTests(unittest.TestCase):
    def test_shared_leg_ignores_divergence_before_boarding_and_after_alighting(self):
        indexes = graph([('115', (8, 0, 1, 2, 9)), ('115Ç', (0, 1, 2, 10)),
                         ('33', (7, 0, 1, 2)), ('99', (0, 3, 2))])
        routes = best_routes(indexes, [0], [2], 2, group_paths=True)
        self.assertEqual(len(routes), 2)
        response = _itinerary_to_response(RoutingSnapshot(indexes, {}, {}), routes[0])
        options = response['legs'][0]['line_options']
        self.assertEqual({option['route_code'] for option in options}, {'115', '115Ç', '33'})
        second = _itinerary_to_response(RoutingSnapshot(indexes, {}, {}), routes[1])
        self.assertEqual([o['route_code'] for o in second['legs'][0]['line_options']], ['99'])
        for mode in ('fastest', 'minimal_walking', 'prefer_tram'):
            routes = best_routes(indexes, [0], [2], 2, routing_mode=mode, group_paths=True)
            self.assertEqual(len(routes), 2)

    def test_grouping_happens_before_limit_and_badges_are_not_top_k_limited(self):
        indexes = graph([(str(i), (0, 1, 2)) for i in range(30)] + [('ALT', (0, 3, 2))])
        routes = best_routes(indexes, [0], [2], 2, group_paths=True)
        self.assertEqual(len(routes), 2)
        self.assertEqual(len(matching_lines(indexes, routes[0].legs[0], routes[0].operating_days)), 30)
        self.assertEqual(routes[1].legs[0].route_code, 'ALT')
        routes = best_routes(indexes, [0], [2], 1, group_paths=True)
        self.assertEqual(len(matching_lines(indexes, routes[0].legs[0], routes[0].operating_days)), 30)

    def test_same_name_or_coordinates_never_substitute_for_physical_ids(self):
        indexes = graph([('A', (0, 1, 2)), ('B', (0, 3, 2))])
        stops = dict(indexes.stops)
        stops[3] = replace(stops[3], name=stops[1].name)
        indexes = build_indexes(stops, indexes.patterns)
        self.assertEqual(len(best_routes(indexes, [0], [2], 2, group_paths=True)), 2)

    def test_stop_order_and_repeated_occurrences_are_significant(self):
        indexes = graph([('Loop', (0, 1, 0, 2)), ('Short', (0, 2)),
                         ('Reverse middle', (0, 2, 1))])
        patterns = dict(indexes.patterns)
        patterns[0] = replace(patterns[0], pickup_allowed=(True, True, False, True))
        indexes = build_indexes(indexes.stops, patterns)
        loop = leg_from_pattern(patterns[0], board_stop=0, alight_stop=2, board_index=0, alight_index=3)
        self.assertEqual([o['code'] for o in matching_lines(indexes, loop, DAYS)], ['Loop'])
        self.assertEqual(len(best_routes(indexes, [0], [2], 2, group_paths=True)), 2)

    def test_endpoint_permissions_and_calendar_compatibility_are_required(self):
        indexes = graph([('A', (0, 1, 2)), ('B', (0, 1, 2)),
                         ('C', (0, 1, 2)), ('D', (0, 1, 2)), ('D', (0, 1, 2))])
        patterns = dict(indexes.patterns)
        patterns[1] = replace(patterns[1], pickup_allowed=(False, True, True))
        patterns[2] = replace(patterns[2], dropoff_allowed=(True, True, False))
        patterns[3] = replace(patterns[3], operating_days=frozenset({Weekday.MONDAY}))
        patterns[4] = replace(patterns[4], operating_days=frozenset({Weekday.TUESDAY}))
        indexes = build_indexes(indexes.stops, patterns)
        leg = leg_from_pattern(patterns[0], board_stop=0, alight_stop=2, board_index=0, alight_index=2)
        self.assertEqual({o['code'] for o in matching_lines(indexes, leg, DAYS)}, {'A', 'D'})
        patterns[4] = replace(patterns[4], operating_days=frozenset({Weekday.SUNDAY}))
        indexes = build_indexes(indexes.stops, patterns)
        self.assertEqual([o['code'] for o in matching_lines(indexes, leg, DAYS)], ['A'])

    def test_each_transfer_leg_groups_independently(self):
        indexes = graph([('A', (0, 1, 2)), ('C', (0, 1, 2, 7)),
                         ('B', (2, 3, 4)), ('D', (8, 2, 3, 4)), ('E', (2, 5, 4))])
        routes = best_routes(indexes, [0], [4], 2, group_paths=True)
        self.assertEqual(len(routes), 2)
        options = [matching_lines(indexes, leg, routes[0].operating_days) for leg in routes[0].legs]
        self.assertEqual([{o['code'] for o in group} for group in options], [{'A', 'C'}, {'B', 'D'}])

    def test_walking_boundaries_and_modes_are_preserved(self):
        indexes = graph([('A', (0, 1, 2))])
        origin = Label(0, 0, 0, DAYS, ())
        ride = Label(2, 1, 0, DAYS, (('Otobüs', 'A'),), origin, (0, 0, 2))
        a = Label(3, 2, 10, DAYS, ride.lines, ride, (None, 10))
        b = Label(4, 2, 10, DAYS, ride.lines, ride, (None, 10))
        self.assertNotEqual(label_path(indexes, a), label_path(indexes, b))
        self.assertEqual(matching_lines(indexes, replace(leg_from_pattern(indexes.patterns[0],
            board_stop=0, alight_stop=2, board_index=0, alight_index=2), mode='Tramvay'), DAYS), [])

    def test_api_consolidates_cards_and_returns_all_line_options(self):
        indexes = graph([('115', (0, 1, 2)), ('115Ç', (0, 1, 2)), ('33', (0, 1, 2)), ('99', (0, 3, 2))])
        snapshot = RoutingSnapshot(indexes, {}, {})
        intent = {'origin': {'district': '', 'name': 'Stop 0'}, 'destination': {'district': '', 'name': 'Stop 2'}}
        with patch('api.index._state', return_value=(snapshot, build_stop_name_index(indexes))), \
                patch('api.index.extract_trip_intent', return_value=intent):
            result = TestClient(app).post('/api/chat', json={'message': 'trip', 'limit': 2})
        self.assertEqual(result.status_code, 200)
        routes = result.json()['itineraries']
        self.assertEqual(len(routes), 2)
        self.assertEqual({o['route_code'] for o in routes[0]['legs'][0]['line_options']}, {'115', '115Ç', '33'})
