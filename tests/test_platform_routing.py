"""Regression: a busier wrong-direction platform must not hide a direct ride."""

import unittest
from unittest.mock import patch

from api.app.api.stops import build_stop_name_index, resolve_stop_ids
from api.app.data.indexes import build_indexes
from api.index import ChatRequest, chat
from api.app.routing.direct import direct
from api.app.routing.ranking import score
from api.app.routing.search import best_routes
from api.app.schemas.snapshot import Pattern, RoutingSnapshot, Stop, Weekday


class PlatformRoutingTests(unittest.TestCase):
    def setUp(self):
        names = ('Alpha', 'Alpha', 'Transfer', 'Beta', 'Beta', 'Middle', 'Other')
        stops = {
            sid: Stop(sid, str(sid), name, None, None, district='Izmit')
            for sid, name in enumerate(names)
        }
        # The first platform in each name group has more patterns. Choosing
        # those first IDs alone gives a transfer even though IDs 1 -> 4 are direct.
        sequences = [(0, 2), (2, 3), (1, 5, 4), (3, 6, 0), (0, 6), (6, 3)]
        patterns = {
            pid: Pattern(pid, str(pid), '0', tuple(sequence), frozenset({'W'}),
                         frozenset({Weekday.MONDAY}), str(pid), frozenset())
            for pid, sequence in enumerate(sequences)
        }
        self.indexes = build_indexes(stops, patterns)
        self.name_index = build_stop_name_index(self.indexes)
        self.origins = resolve_stop_ids(
            {'district': 'Izmit', 'name': 'Alpha'}, self.name_index, self.indexes
        )
        self.destinations = resolve_stop_ids(
            {'district': 'Izmit', 'name': 'Beta'}, self.name_index, self.indexes
        )

    def test_global_ranking_checks_nonpreferred_platforms(self):
        self.assertEqual(self.origins, (0, 1))
        self.assertEqual(self.destinations, (3, 4))
        routes = best_routes(self.indexes, self.origins, self.destinations, 5)
        self.assertEqual(score(routes[0]), (0, 2))
        self.assertEqual(routes[0].legs[0].board_stop, 1)
        self.assertEqual(routes[0].legs[0].alight_stop, 4)
        scores = [score(route) for route in routes]
        self.assertEqual(scores, sorted(scores))
        self.assertTrue(any(s[0] == 1 for s in scores))

    def test_reverse_query_uses_reverse_platform_not_reversed_sequence(self):
        routes = best_routes(self.indexes, self.destinations, self.origins, 1)
        self.assertEqual(score(routes[0]), (0, 2))
        self.assertEqual(routes[0].legs[0].board_stop, 3)
        self.assertEqual(routes[0].legs[0].alight_stop, 0)
        self.assertEqual(list(direct(self.indexes, 4, 1)), [])

    def test_direct_results_do_not_skip_preferred_transfer_search(self):
        counts = {}
        routes = best_routes(self.indexes, self.origins, self.destinations, 1, counts)
        self.assertEqual(len(routes), 1)
        self.assertEqual(counts['direct'], 1)
        self.assertIsNotNone(counts['one_transfer'])
        self.assertIsNotNone(counts['two_transfers'])

    def test_nearby_platforms_create_a_displayable_walking_transfer(self):
        stops = {
            0: Stop(0, 'A', 'Origin', 40.9900, 29.0000),
            1: Stop(1, 'B', 'Bus alight', 41.0001, 29.0000),
            2: Stop(2, 'C', 'Second bus board', 41.0002, 29.0000),
            3: Stop(3, 'D', 'Destination', 41.0100, 29.0000),
        }
        patterns = {
            0: Pattern(0, 'bus', '0', (0, 1), frozenset({'W'}),
                       frozenset({Weekday.MONDAY}), '89K', frozenset()),
            1: Pattern(1, 'bus2', '0', (2, 3), frozenset({'W'}),
                       frozenset({Weekday.MONDAY}), 'B2', frozenset()),
        }
        route = best_routes(build_indexes(stops, patterns), [0], [3], 1)[0]
        self.assertEqual(route.transit_leg_count, 2)
        self.assertEqual(len(route.legs), 3)
        self.assertTrue(route.legs[1].is_walking)
        self.assertGreater(route.legs[1].walking_metres, 0)

    def test_api_uses_all_candidates_and_reports_actual_selected_platform(self):
        snapshot = RoutingSnapshot(self.indexes, {}, {})
        intent = {
            'origin': {'district': 'Izmit', 'name': 'Alpha'},
            'destination': {'district': 'Izmit', 'name': 'Beta'},
        }
        with patch('api.index._state', return_value=(snapshot, self.name_index)), \
                patch('api.index.extract_trip_intent', return_value=intent):
            response = chat(ChatRequest(message='trip', limit=1))
        self.assertEqual(response['origin']['id'], 1)
        self.assertEqual(response['destination']['id'], 4)
        self.assertEqual(response['itineraries'][0]['transfers'], 0)


if __name__ == '__main__':
    unittest.main()
