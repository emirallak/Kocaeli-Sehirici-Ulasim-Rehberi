import unittest
from unittest.mock import patch
from api.app.data.indexes import build_indexes
from api.app.routing.raptor import route_queue
from api.app.routing.search import best_routes
from api.app.schemas.snapshot import Stop, Pattern, Weekday


class RaptorTests(unittest.TestCase):
    def graph(self, sequences, days=None):
        stops = {i: Stop(i, str(i), str(i), None, None) for i in range(101)}
        patterns = {pid: Pattern(pid, str(pid), '0', seq, frozenset({'W'}),
                    days[pid] if days else frozenset(Weekday), str(pid), frozenset())
                    for pid, seq in enumerate(sequences)}
        return build_indexes(stops, patterns)

    def test_scan_starts_at_first_marked_occurrence_and_skips_disconnected_routes(self):
        graph = self.graph([tuple(range(100)), (100, 0)])
        self.assertEqual(route_queue(graph, {90: [], 95: []}), {0: 90})
        counts = {}
        result = best_routes(graph, [90], [99], 1, counts)
        self.assertEqual(result[0].legs[0].board_index, 90)
        # Later rounds may inspect reachable patterns, but never the long prefix.
        self.assertLess(counts['scanned_positions'], 40)

    def test_calendar_intersections_block_impossible_transfer(self):
        graph = self.graph([(0, 1), (1, 2)],
                           [frozenset({Weekday.MONDAY}), frozenset({Weekday.TUESDAY})])
        self.assertEqual(best_routes(graph, [0], [2], 3), [])

    def test_repeated_stop_uses_the_cheapest_valid_boarding_occurrence(self):
        graph = self.graph([(0, 1, 0, 2)])
        leg = best_routes(graph, [0], [2], 1)[0].legs[0]
        self.assertEqual((leg.board_index, leg.alight_index), (2, 3))

    def test_many_direct_lines_survive_stop_bag_cap(self):
        graph = self.graph([(0, 1)] * 30)
        result = best_routes(graph, [0], [1], 20)
        self.assertEqual(len(result), 20)
        self.assertEqual(len({route.legs[0].route_code for route in result}), 20)

    def test_reconstructs_only_requested_results(self):
        graph = self.graph([(0, 1)] * 30)
        from api.app.routing.raptor import reconstruct
        with patch('api.app.routing.raptor.reconstruct', wraps=reconstruct) as spy:
            self.assertEqual(len(best_routes(graph, [0], [1], 3)), 3)
            self.assertEqual(spy.call_count, 3)

    def test_pickup_and_dropoff_rules_are_preserved(self):
        graph = self.graph([(0, 1, 2)])
        from dataclasses import replace
        restricted = replace(graph.patterns[0], pickup_allowed=(False, True, True),
                             dropoff_allowed=(True, False, True))
        graph = build_indexes(graph.stops, {0: restricted})
        self.assertEqual(best_routes(graph, [0], [2], 3), [])
        self.assertEqual(best_routes(graph, [1], [2], 3)[0].legs[0].board_stop, 1)

    def test_alighting_early_to_walk_where_the_ride_goes_is_not_an_alternative(self):
        # Stops ~330 m apart, so 2 → 3 is also walkable.
        stops = {i: Stop(i, str(i), str(i), 40.70 + i * 0.003, 29.90) for i in range(4)}
        pattern = Pattern(0, 'R', '0', (0, 1, 2, 3), frozenset({'W'}), frozenset(Weekday), '100', frozenset())
        graph = build_indexes(stops, {0: pattern})
        self.assertTrue(graph.walking_neighbors[2])
        for mode in ('fastest', 'fewest_transfers', 'minimal_walking', 'prefer_tram'):
            with self.subTest(mode=mode):
                [route] = best_routes(graph, [0], [3], 3, routing_mode=mode, group_paths=True)
                self.assertEqual([leg.alight_stop for leg in route.legs], [3])

    def test_same_vehicle_from_another_origin_or_to_another_destination_platform(self):
        # A line 0-1-2-3 every ~330 m; platforms 4 and 5 sit beside stops 1 and 2.
        stops = {i: Stop(i, str(i), str(i), 40.70 + i * 0.003, 29.90) for i in range(4)}
        stops[4] = Stop(4, '4', '4', 40.703, 29.9015)
        stops[5] = Stop(5, '5', '5', 40.706, 29.9015)
        pattern = Pattern(0, 'R', '0', (0, 1, 2, 3), frozenset({'W'}), frozenset(Weekday), '100', frozenset())
        graph = build_indexes(stops, {0: pattern})
        for mode in ('fastest', 'fewest_transfers', 'minimal_walking', 'prefer_tram'):
            with self.subTest(mode=mode):
                # Riding to 3 beats alighting at 2 to walk to the other platform 5.
                [route] = best_routes(graph, [0], [3, 5], 3, routing_mode=mode, group_paths=True)
                self.assertEqual([(leg.board_stop, leg.alight_stop) for leg in route.legs], [(0, 3)])
                # Boarding at origin 0 beats walking from origin 4 to board at 1.
                [route] = best_routes(graph, [0, 4], [3], 3, routing_mode=mode, group_paths=True)
                self.assertEqual([(leg.board_stop, leg.alight_stop) for leg in route.legs], [(0, 3)])

    def test_small_networks_match_exhaustive_journey_enumeration(self):
        import random
        from api.app.routing.metrics import journey_rank
        from api.app.schemas.itinerary import Itinerary, leg_from_pattern
        randomizer = random.Random(42)
        for case in range(20):
            sequences = [tuple(randomizer.sample(range(5), randomizer.randint(2, 5)))
                         for _ in range(3)]
            graph = self.graph(sequences)
            exhaustive = []

            def enumerate_journeys(stop, legs, used):
                if stop == 4 and legs:
                    exhaustive.append(Itinerary(tuple(legs)))
                if len(used) == 3:
                    return
                for pid in graph.routes_at_stop[stop]:
                    if pid in used:
                        continue
                    pattern = graph.patterns[pid]
                    for board in graph.positions[pid][stop]:
                        for alight in range(board + 1, len(pattern.stop_ids)):
                            leg = leg_from_pattern(pattern, board_stop=stop,
                                alight_stop=pattern.stop_ids[alight],
                                board_index=board, alight_index=alight)
                            enumerate_journeys(leg.alight_stop, legs + [leg], used | {pid})

            def is_roundabout(journey):
                stops = [journey.legs[0].board_stop, *(leg.alight_stop for leg in journey.legs)]
                if len(set(stops)) < len(stops):
                    return True
                # Stops have no coordinates here, so every detour is short.
                for index, leg in enumerate(journey.legs):
                    stop_ids = graph.patterns[leg.pattern_id].stop_ids
                    later = {other.alight_stop for other in journey.legs[index + 1:]}
                    if any(stop in later for stop in stop_ids[leg.board_index + 1:]):
                        return True
                    # Could this vehicle have been boarded earlier on the journey?
                    earlier = set(stops[:index])
                    if index and any(stop in earlier for stop in stop_ids[:leg.board_index]):
                        return True
                return False

            enumerate_journeys(0, [], set())
            exhaustive = [journey for journey in exhaustive if not is_roundabout(journey)]
            for mode in ('fastest', 'fewest_transfers', 'minimal_walking', 'prefer_tram'):
                expected = {}
                for journey in exhaustive:
                    lines = tuple((leg.mode, leg.route_code) for leg in journey.legs)
                    rank = journey_rank(graph, journey, mode)
                    if lines not in expected or rank < expected[lines]:
                        expected[lines] = rank
                expected = sorted(expected.items(), key=lambda item: (item[1], item[0]))[:3]
                actual = best_routes(graph, [0], [4], 3, routing_mode=mode)
                with self.subTest(case=case, mode=mode):
                    self.assertEqual([tuple((leg.mode, leg.route_code) for leg in r.legs) for r in actual],
                                     [lines for lines, rank in expected])
                    for journey, (_, rank) in zip(actual, expected):
                        for left, right in zip(journey_rank(graph, journey, mode), rank):
                            self.assertAlmostEqual(left, right)
