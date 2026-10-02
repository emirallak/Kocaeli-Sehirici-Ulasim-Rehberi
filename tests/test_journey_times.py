import unittest
from datetime import datetime, timedelta, timezone

from api.app.data.indexes import build_indexes
from api.index import ChatRequest, _itinerary_to_response
from api.app.routing.metrics import itinerary_minutes, journey_rank
from api.app.schemas.itinerary import Itinerary, leg_from_pattern, walking_leg
from api.app.schemas.snapshot import Pattern, RoutingSnapshot, Stop, Weekday


class JourneyTimeTests(unittest.TestCase):
    def setUp(self):
        stops = {i: Stop(i, str(i), str(i), None, None) for i in range(4)}
        self.pattern = Pattern(0, 'A', '0', (1, 2), frozenset({'W'}),
            frozenset(Weekday), 'A', frozenset(), metres_at_stop=(0, 1000))
        self.indexes = build_indexes(stops, {0: self.pattern})
        self.ride = leg_from_pattern(self.pattern, board_stop=1, alight_stop=2,
            board_index=0, alight_index=1)

    def test_walks_do_not_count_as_transfers_and_times_include_wait(self):
        journey = Itinerary((walking_leg(board_stop=0, alight_stop=1, metres=80),
            self.ride, walking_leg(board_stop=2, alight_stop=3, metres=160)))
        self.assertEqual(itinerary_minutes(self.indexes, journey), 11.25)
        self.assertEqual(journey_rank(self.indexes, journey)[0], 0)
        departure = datetime(2026, 10, 2, 23, 55, tzinfo=timezone(timedelta(hours=3)))
        response = _itinerary_to_response(RoutingSnapshot(self.indexes, {}, {}), journey, departure)
        self.assertTrue(response['is_direct'])
        self.assertEqual(response['estimated_duration_minutes'], 12)
        self.assertEqual(response['estimated_arrival_at'], '2026-10-03T00:07:00+03:00')
        self.assertEqual(response['legs'][0]['estimated_duration_minutes'], 1)

    def test_walking_only_and_default_three_results(self):
        journey = Itinerary((walking_leg(board_stop=0, alight_stop=1, metres=400),))
        self.assertEqual(itinerary_minutes(self.indexes, journey), 5)
        response = _itinerary_to_response(RoutingSnapshot(self.indexes, {}, {}), journey)
        self.assertFalse(response['is_direct'])
        self.assertEqual(response['transfers'], 0)
        self.assertEqual(ChatRequest(message='trip').limit, 3)
