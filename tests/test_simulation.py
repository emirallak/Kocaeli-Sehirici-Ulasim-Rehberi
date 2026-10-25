"""Simulated vehicles follow the timetable at a line-kind and clock dependent speed."""
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from api.app.data.loader import load_snapshot
from api.app.routing.simulation import (
    SPEEDS_KMH, TURKEY, active_vehicles, arrivals_at, average_speed_kmh, line_kind)
from api.index import app

MONDAY = datetime(2026, 3, 2, tzinfo=TURKEY)
CITY_RUSH, CITY_FREE = SPEEDS_KMH['city']
DISTRICT_RUSH, DISTRICT_FREE = SPEEDS_KMH['district']


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        tables = {
            # A-B-C are ~420 m apart (a city line); X-Y ~7 km (a district line).
            'stops': 'stop_id,stop_name,stop_lat,stop_lon\n'
                     'A,İskele,40.700,29.900\nB,Otogar,40.703,29.903\nC,Merkez,40.706,29.906\n'
                     'X,Köy,40.750,29.950\nY,İskele,40.800,30.000\n',
            'routes': 'route_id,route_short_name,route_long_name,route_type\n'
                      'R,100,İskele - Merkez,3\nK,KM1,Köy - İskele,3\n',
            'calendar': 'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n'
                        'W,1,1,1,1,1,0,0,20260101,20261231\n',
            'trips': 'route_id,service_id,trip_id,direction_id\nR,W,T1,0\nR,W,T2,0\nR,W,T3,0\nK,W,K1,0\n',
            'stop_times': 'trip_id,stop_id,stop_sequence,departure_time\n'
                          'T1,A,1,08:00:00\nT1,B,2,08:02:00\nT1,C,3,08:04:00\n'
                          'T2,A,1,12:00:00\nT2,B,2,12:02:00\nT2,C,3,12:04:00\n'
                          'T3,A,1,24:15:00\nT3,B,2,24:17:00\nT3,C,3,24:19:00\n'
                          'K1,X,1,07:55:00\nK1,Y,2,08:10:00\n',
        }
        for name, content in tables.items():
            (root / f'{name}.txt').write_text(content, encoding='utf-8')
        self.snapshot = load_snapshot(root)
        self.pid = next(pid for pid, pattern in self.snapshot.patterns.items() if pattern.route_id == 'R')
        self.village = next(pid for pid, pattern in self.snapshot.patterns.items() if pattern.route_id == 'K')
        self.metres = self.snapshot.indexes.metres_at_position[self.pid]

    def tearDown(self):
        self.temp.cleanup()

    def at(self, hour, minute, second=0, day=0):
        return MONDAY.replace(hour=hour, minute=minute, second=second) + timedelta(days=day)

    def test_speed_depends_on_line_kind_rush_hours_and_weekday(self):
        self.assertEqual(line_kind(self.snapshot, self.pid), 'city')
        self.assertEqual(line_kind(self.snapshot, self.village), 'district')
        self.assertEqual(average_speed_kmh(self.at(8, 0)), CITY_RUSH)
        self.assertEqual(average_speed_kmh(self.at(17, 0)), CITY_RUSH)
        self.assertEqual(average_speed_kmh(self.at(12, 0)), CITY_FREE)
        self.assertEqual(average_speed_kmh(self.at(8, 0, day=5)), CITY_FREE)  # Saturday
        self.assertEqual(average_speed_kmh(self.at(12, 0), 'district'), DISTRICT_FREE)
        self.assertEqual(average_speed_kmh(self.at(8, 0), 'tram'), average_speed_kmh(self.at(12, 0), 'tram'))
        [village] = active_vehicles(self.snapshot, self.village, self.at(8, 0))
        self.assertEqual(village['speed_kmh'], DISTRICT_RUSH)

    def test_vehicle_position_follows_departure_and_speed(self):
        [vehicle] = active_vehicles(self.snapshot, self.pid, self.at(8, 1))
        self.assertAlmostEqual(vehicle['metres'] - self.metres[0], 60 * CITY_RUSH / 3.6, places=3)
        self.assertEqual(vehicle['speed_kmh'], CITY_RUSH)
        self.assertEqual(vehicle['next_stop'], 'Otogar')
        self.assertTrue(40.700 < vehicle['latitude'] < 40.703)
        # Before the first departure and after the end there is no vehicle.
        self.assertEqual(active_vehicles(self.snapshot, self.pid, self.at(7, 59)), [])
        self.assertEqual(active_vehicles(self.snapshot, self.pid, self.at(8, 10)), [])
        # A leg ending at the second stop excludes vehicles past it.
        self.assertEqual(active_vehicles(self.snapshot, self.pid, self.at(8, 2, 30), last_position=1), [])

    def test_after_midnight_trips_belong_to_the_previous_service_day(self):
        [vehicle] = active_vehicles(self.snapshot, self.pid, self.at(0, 16, day=1))
        self.assertTrue(vehicle['departed_at'].startswith('2026-03-03T00:15'))
        # Friday's 24:15 trip runs early Saturday; Saturday's never runs.
        self.assertEqual(len(active_vehicles(self.snapshot, self.pid, self.at(0, 16, day=5))), 1)
        self.assertEqual(active_vehicles(self.snapshot, self.pid, self.at(0, 16, day=6)), [])

    def test_arrivals_use_the_speed_of_each_departure(self):
        offset = self.metres[2] - self.metres[0]
        arrivals = arrivals_at(self.snapshot, self.pid, 2, self.at(7, 0), self.at(14, 0))
        self.assertEqual(len(arrivals), 2)
        self.assertAlmostEqual((arrivals[0] - self.at(8, 0)).total_seconds(), offset / (CITY_RUSH / 3.6), places=3)
        self.assertAlmostEqual((arrivals[1] - self.at(12, 0)).total_seconds(), offset / (CITY_FREE / 3.6), places=3)

    def client(self, now):
        state = patch('api.index._state', return_value=(self.snapshot, {}))
        clock = patch('api.index._now', return_value=now)
        state.start(), clock.start()
        self.addCleanup(state.stop)
        self.addCleanup(clock.stop)
        return TestClient(app)

    def test_vehicle_endpoint_filters_legs_and_rejects_bad_specs(self):
        client = self.client(self.at(8, 1))
        response = client.get(f'/api/vehicles?patterns={self.pid}')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        [vehicle] = response.json()['vehicles']
        self.assertEqual(vehicle['route_code'], '100')
        self.assertIsNone(vehicle['minutes_to_board'])
        self.assertFalse(vehicle['passed_board'])
        self.assertNotIn('metres', vehicle)
        self.assertNotIn('previous_position', vehicle)
        # The vehicle is approaching the second stop of a 1 → 2 leg.
        [approaching] = client.get(f'/vehicles?patterns={self.pid}:1:2').json()['vehicles']
        self.assertIsNotNone(approaching['minutes_to_board'])
        [riding] = client.get(f'/api/vehicles?patterns={self.pid}:0:2').json()['vehicles']
        self.assertTrue(riding['passed_board'])
        for bad in ('x', '999', f'{self.pid}:2:1', f'{self.pid}:1'):
            self.assertEqual(client.get(f'/api/vehicles?patterns={bad}').status_code, 422)

    def test_stop_arrivals_cover_every_platform_with_remaining_stops(self):
        client = self.client(self.at(7, 59))
        # "İskele" is the city line's first stop and the village line's last.
        payload = client.get('/api/stop-arrivals?name=iskele').json()
        self.assertEqual(len(payload['stop']['platforms']), 2)
        self.assertEqual([line['route_code'] for line in payload['lines']], ['100'])
        first = payload['arrivals'][0]
        self.assertEqual((first['route_code'], first['minutes'], first['destination']), ('100', 1, 'Merkez'))
        self.assertIsNone(first['vehicle'])  # Not yet departed.
        self.assertTrue(first['departs_at'].startswith('2026-03-02T08:00'))

        client = self.client(self.at(8, 0, 30))
        # Merkez is the terminal; nobody boards there.
        self.assertEqual(client.get('/stop-arrivals?name=MERKEZ').json()['arrivals'], [])
        [arrival, *_] = client.get('/api/stop-arrivals?name=Otogar').json()['arrivals']
        self.assertEqual(arrival['remaining_stops'], 1)
        self.assertEqual(arrival['vehicle']['next_stop'], 'Otogar')
        self.assertNotIn('metres', arrival['vehicle'])
        self.assertEqual(client.get('/api/stop-arrivals?name=yok').status_code, 404)
        self.assertEqual(client.get('/stop-info').status_code, 200)


if __name__ == '__main__':
    unittest.main()
