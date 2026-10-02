import unittest

from api.app.data.indexes import build_indexes
from api.app.routing.ranking import route_combination, score, top_k_distinct
from api.app.routing.search import best_routes
from api.app.schemas.itinerary import Itinerary, Leg
from api.app.schemas.snapshot import Pattern, Stop, Weekday


DAYS = frozenset({Weekday.MONDAY})


def journey(codes, hops):
    return Itinerary(tuple(
        Leg(i, str(i), '0', frozenset({'W'}), DAYS, i, i + 1, 0, count,
            route_code=code)
        for i, (code, count) in enumerate(zip(codes, hops))
    ))


class DistinctRoutesTests(unittest.TestCase):
    def test_same_lines_keep_shortest_transfer_option_before_limiting(self):
        long = journey(('100', '200'), (6, 8))
        short = journey(('100', '200'), (2, 3))
        different = journey(('98', '36'), (8, 8))
        results = list(top_k_distinct(iter([long, long, short, different]), 2))
        self.assertEqual(results, [short, different])

    def test_line_order_and_transfer_priority_are_preserved(self):
        forward = journey(('A', 'B'), (1, 1))
        reverse = journey(('B', 'A'), (1, 1))
        direct = journey(('C',), (20,))
        self.assertNotEqual(route_combination(forward), route_combination(reverse))
        self.assertEqual(list(top_k_distinct([forward, reverse, direct], 3)),
                         [direct, forward, reverse])

    def test_distinct_published_line_codes_remain_distinct(self):
        normal = journey(('100',), (5,))
        variant = journey(('100A',), (2,))
        self.assertNotEqual(route_combination(normal), route_combination(variant))
        self.assertEqual(list(top_k_distinct([normal, variant], 2)), [variant, normal])

    def test_evicted_combination_can_return_with_a_better_journey(self):
        a = journey(('A',), (10,))
        b = journey(('B',), (5,))
        better_a = journey(('A',), (2,))
        self.assertEqual(list(top_k_distinct([a, b, better_a], 1)), [better_a])
        self.assertEqual(list(top_k_distinct([a], 0)), [])

    def test_duplicate_direct_patterns_do_not_hide_other_transfer_combinations(self):
        stops = {i: Stop(i, str(i), str(i), None, None) for i in range(4)}
        specs = [('A', (0, 1, 3)), ('A', (0, 2, 3)),
                 ('B', (0, 1)), ('C', (1, 3))]
        patterns = {
            i: Pattern(i, str(i), '0', seq, frozenset({'W'}), DAYS, code, frozenset())
            for i, (code, seq) in enumerate(specs)
        }
        results = best_routes(build_indexes(stops, patterns), [0], [3], 2)
        self.assertEqual(len(results), 2)
        self.assertEqual([score(r)[0] for r in results], [0, 1])
        self.assertEqual(len({route_combination(r) for r in results}), 2)


if __name__ == '__main__':
    unittest.main()
