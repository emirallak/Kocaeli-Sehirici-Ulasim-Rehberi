"""Line schedules must match the selected topology and service calendar."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from api.app.data.loader import load_snapshot
from api.app.api.lines import line_catalog, line_details
from api.index import app


class LineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        tables = {
            'stops': 'stop_id,stop_name,stop_lat,stop_lon\nA,İskele,40.7,29.9\nB,Otogar,40.8,30.0\n',
            'routes': 'route_id,route_short_name,route_long_name,route_type\nR,100,İskele - Otogar,3\n',
            'calendar': 'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nW,1,1,1,1,1,0,0,20260101,20261231\nS,0,0,0,0,0,0,1,20260101,20261231\n',
            'trips': 'route_id,service_id,trip_id,direction_id,shape_id\nR,W,T1,0,SH\nR,W,T2,0,SH\nR,S,T3,1,\n',
            # Unsorted rows verify departure is taken from the first stop.
            'stop_times': 'trip_id,stop_id,stop_sequence,departure_time\nT1,B,2,08:20:00\nT1,A,1,08:00:00\nT2,A,1,24:15:00\nT2,B,2,24:30:00\nT3,B,1,\nT3,A,2,09:30:00\n',
            'shapes': 'shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\nSH,40.7,29.9,1\nSH,40.75,29.95,2\nSH,40.8,30.0,3\n',
        }
        for name, content in tables.items():
            (root / f'{name}.txt').write_text(content, encoding='utf-8')
        self.snapshot = load_snapshot(root)

    def tearDown(self):
        self.temp.cleanup()

    def test_directions_have_ordered_stops_shapes_and_correct_departures(self):
        data = line_details(self.snapshot, 'R')
        self.assertEqual(line_catalog(self.snapshot)[0]['code'], '100')
        outbound, inbound = data['variants']
        self.assertEqual([s['name'] for s in outbound['stops']], ['İskele', 'Otogar'])
        self.assertEqual(outbound['geometry_source'], 'shape')
        self.assertEqual(len(outbound['geometry']), 3)
        self.assertEqual(outbound['timetables'][0]['departures'], ['08:00:00', '24:15:00'])
        self.assertEqual(outbound['timetables'][0]['operating_days'], [0, 1, 2, 3, 4])
        self.assertEqual(outbound['timetables'][0]['end_date'], '2026-12-31')
        self.assertEqual([s['name'] for s in inbound['stops']], ['Otogar', 'İskele'])
        self.assertEqual(inbound['geometry_source'], 'stops')
        self.assertEqual(inbound['timetables'][0]['departures'], [])
        self.assertEqual(inbound['timetables'][0]['operating_days'], [6])

    def test_endpoints_search_unknown_line_and_page(self):
        with patch('api.index._state', return_value=(self.snapshot, {})):
            client = TestClient(app)
            self.assertEqual(client.get('/api/lines?q=iskele').json()['lines'][0]['id'], 'R')
            self.assertEqual(client.get('/api/lines?q=unknown').json()['lines'], [])
            self.assertEqual(client.get('/api/lines/R').status_code, 200)
            self.assertEqual(client.get('/lines/R').json(), client.get('/api/lines/R').json())
            self.assertEqual(client.get('/api/lines/missing').status_code, 404)
            self.assertEqual(client.get('/line-info').status_code, 200)

    def test_calendar_variants_merge_without_mixing_directions_or_paths(self):
        root = Path(self.temp.name)
        with (root / 'calendar.txt').open('a', encoding='utf-8') as file:
            file.write('SA,0,0,0,0,0,1,0,20260101,20261231\n')
        with (root / 'trips.txt').open('a', encoding='utf-8') as file:
            file.write('R,SA,T4,0,SH\nR,S,T5,0,SH\nR,W,T6,0,\n')
        with (root / 'stop_times.txt').open('a', encoding='utf-8') as file:
            file.write('T4,A,1,10:00:00\nT4,B,2,10:20:00\n'
                       'T5,A,1,11:00:00\nT5,B,2,11:20:00\n'
                       'T6,A,1,12:00:00\nT6,B,2,12:20:00\n')
        data = line_details(load_snapshot(root), 'R')
        self.assertEqual(len(data['variants']), 3)
        outbound = next(variant for variant in data['variants']
                        if variant['direction_id'] == '0' and variant['geometry_source'] == 'shape')
        schedules = {tuple(table['operating_days']): table['departures']
                     for table in outbound['timetables']}
        self.assertEqual(schedules, {(0, 1, 2, 3, 4): ['08:00:00', '24:15:00'],
                                     (5,): ['10:00:00'], (6,): ['11:00:00']})
        alternate = next(variant for variant in data['variants']
                         if variant['direction_id'] == '0' and variant['geometry_source'] == 'stops')
        self.assertEqual(alternate['timetables'][0]['departures'], ['12:00:00'])


if __name__ == '__main__':
    unittest.main()
