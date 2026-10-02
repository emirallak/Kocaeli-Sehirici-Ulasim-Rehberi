import unittest
from api.app.data.indexes import build_indexes
from api.app.routing.search import best_routes
from api.app.schemas.snapshot import Stop, Pattern, Weekday


class RoundSearchTests(unittest.TestCase):
    def graph(self, specs):
        stops = {i: Stop(i,str(i),str(i),None,None) for i in range(40)}
        patterns = {i: Pattern(i,str(i),'0',seq,frozenset({'W'}),
            frozenset(Weekday),code,frozenset(),mode=mode)
            for i,(seq,code,mode) in enumerate(specs)}
        return build_indexes(stops,patterns)

    def test_long_direct_bus_beats_short_transfer(self):
        graph = self.graph([(tuple(range(31)),'BUS','Otobüs'),
            ((0,31),'FEED','Otobüs'),((31,32,33,34,30),'SECOND','Otobüs')])
        results = best_routes(graph,[0],[30],1)
        self.assertEqual([l.route_code for l in results[0].legs],['BUS'])

    def test_tram_filter_can_displace_direct_bus_but_fewest_transfers_does_not(self):
        graph = self.graph([(tuple(range(31)), 'BUS', 'Otobüs'),
            ((0,31), 'FEED', 'Otobüs'), ((31,30), 'T1', 'Tramvay')])
        self.assertEqual(best_routes(graph, [0], [30], 3)[0].transit_leg_count, 1)
        routes = best_routes(graph, [0], [30], 3, routing_mode="prefer_tram")
        self.assertEqual(routes[0].transit_leg_count, 2)
        self.assertTrue(any(route.transit_leg_count == 2 for route in routes))

    def test_three_distinct_direct_lines_survive_shorter_transfers(self):
        graph = self.graph([(tuple(range(31)), code, 'Otobüs') for code in ('A','B','C','D')]
            + [((0,31), 'FEED', 'Otobüs'), ((31,30), 'SECOND', 'Otobüs')])
        routes = best_routes(graph, [0], [30], 3)
        self.assertEqual(len(routes), 3)
        self.assertTrue(all(route.transit_leg_count == 1 for route in routes))
        self.assertEqual(len({route.legs[0].route_code for route in routes}), 3)

    def test_four_rides_are_searched_if_three_cannot_reach_destination(self):
        graph=self.graph([((i,i+1),str(i),'Otobüs') for i in range(4)])
        self.assertEqual(best_routes(graph,[0],[4],1)[0].transit_leg_count,4)

    def test_direction_and_unreachable(self):
        graph=self.graph([((0,1,2),'A','Otobüs')])
        self.assertEqual(best_routes(graph,[2],[0],5),[])

    def test_shorter_kilometres_keep_direct_33_ahead_of_170(self):
        stops = {i: Stop(i, str(i), str(i), None, None) for i in range(5)}
        patterns = {
            0: Pattern(0, '33', '0', (0, 1, 2, 3, 4), frozenset({'W'}),
                       frozenset(Weekday), '33', frozenset(),
                       metres_at_stop=(0, 250, 500, 750, 1_000)),
            1: Pattern(1, '170', '0', (0, 4), frozenset({'W'}),
                       frozenset(Weekday), '170', frozenset(),
                       metres_at_stop=(0, 3_000)),
        }
        routes = best_routes(build_indexes(stops, patterns), [0], [4], 2)
        self.assertEqual([route.legs[0].route_code for route in routes], ['33', '170'])

    def test_tram_preference_promotes_available_tram(self):
        stops = {i: Stop(i, str(i), str(i), None, None) for i in range(2)}
        patterns = {
            0: Pattern(0, 'BUS', '0', (0, 1), frozenset({'W'}),
                       frozenset(Weekday), '33', frozenset(),
                       metres_at_stop=(0, 1_000)),
            1: Pattern(1, 'TRAM', '0', (0, 1), frozenset({'W'}),
                       frozenset(Weekday), 'T1', frozenset(), mode='Tramvay',
                       metres_at_stop=(0, 3_000)),
        }
        graph = build_indexes(stops, patterns)
        self.assertEqual(best_routes(graph, [0], [1], 1)[0].legs[0].route_code, '33')
        self.assertEqual(best_routes(graph, [0], [1], 1, routing_mode="prefer_tram")[0].legs[0].route_code, 'T1')
