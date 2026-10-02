"""Each UI filter must change which feasible route wins."""
import unittest

from pydantic import ValidationError

from api.app.data.indexes import build_indexes
from api.index import ChatRequest
from api.app.routing.search import best_routes
from api.app.schemas.snapshot import Pattern, Stop, Weekday


DAYS = frozenset(Weekday)


def graph(specs, coordinates=None):
    coordinates = coordinates or {}
    stops = {
        i: Stop(i, str(i), str(i), *coordinates.get(i, (None, None)))
        for i in range(10)
    }
    patterns = {
        i: Pattern(i, code, '0', tuple(stops), frozenset({'W'}), DAYS,
                   code, frozenset(), mode=mode,
                   metres_at_stop=tuple(metres))
        for i, (code, stops, metres, mode) in enumerate(specs)
    }
    return build_indexes(stops, patterns)


class RoutingModeTests(unittest.TestCase):
    def test_fastest_can_choose_short_transfer_over_slow_direct(self):
        indexes = graph([
            ('DIRECT', (0, 3), (0, 8000), 'Otobüs'),
            ('A', (0, 1), (0, 1000), 'Otobüs'),
            ('B', (1, 3), (0, 1000), 'Otobüs'),
        ])
        self.assertEqual(best_routes(indexes, [0], [3], 1)[0].transit_leg_count, 1)
        self.assertEqual(best_routes(indexes, [0], [3], 1, routing_mode='fastest')[0].transit_leg_count, 2)

    def test_minimal_walking_chooses_closer_boarding(self):
        indexes = graph([
            ('SHORT', (1, 3), (0, 100), 'Otobüs'),
            ('NO_WALK', (0, 3), (0, 2500), 'Otobüs'),
        ], coordinates={0: (40.0, 29.0), 1: (40.0035, 29.0)})
        fastest = best_routes(indexes, [0], [3], 1, routing_mode='fastest')[0]
        least_walk = best_routes(indexes, [0], [3], 1, routing_mode='minimal_walking')[0]
        self.assertEqual(fastest.legs[-1].route_code, 'SHORT')
        self.assertEqual(least_walk.legs[0].route_code, 'NO_WALK')

    def test_tram_mode_discounts_tram_travel(self):
        indexes = graph([
            ('BUS', (0, 3), (0, 1000), 'Otobüs'),
            ('T1', (0, 3), (0, 3000), 'Tramvay'),
        ])
        self.assertEqual(best_routes(indexes, [0], [3], 1, routing_mode='fastest')[0].legs[0].route_code, 'BUS')
        self.assertEqual(best_routes(indexes, [0], [3], 1, routing_mode='prefer_tram')[0].legs[0].route_code, 'T1')

    def test_api_accepts_only_four_modes(self):
        for mode in ('fastest', 'fewest_transfers', 'minimal_walking', 'prefer_tram'):
            self.assertEqual(ChatRequest(message='trip', routing_mode=mode).routing_mode, mode)
        with self.assertRaises(ValidationError):
            ChatRequest(message='trip', routing_mode='unknown')


if __name__ == '__main__':
    unittest.main()
