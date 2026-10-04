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
    def _trip_variant_feed(self):
        root = Path(self.temp.name)
        (root / 'stops.txt').write_text('stop_id,stop_name,stop_lat,stop_lon\n'
            'A,İskele,40.7,29.9\nB,Otogar,40.8,30.0\nC,Merkez,40.9,30.1\nD,Hastane,40.85,30.05\n', encoding='utf-8')
        specs = [
            ('R1', 'W', '0', 'Merkez', '#', '08:00:00', 'ABC'),
            ('R2', 'W', '0', 'Merkez', '#', '09:00:00', 'ABC'),
            ('R3', 'W', '0', 'Merkez', '#', '10:00:00', 'ABC'),
            ('HEAD', 'W', '0', 'Otogar', '#', '08:00:00', 'ABC'),
            ('SHORT', 'W', '0', 'Otogar', '#', '11:00:00', 'AB'),
            ('ALT', 'W', '0', 'Merkez', '#', '12:00:00', 'ADC'),
            ('NOTE', 'W', '0', 'Merkez', 'VADİKENT GİDER.#2150de', '26:00:00', 'ABC'),
            ('WEEKEND', 'S', '0', 'Merkez', 'VADİKENT GİDER.#2150de', '09:00:00', 'ABC'),
            ('MISSING', 'W', '0', 'Merkez', 'Eksik saat#ff0000', '', 'ABC'),
            ('BACK', 'W', '1', 'İskele', '#', '07:00:00', 'CBA'),
        ]
        (root / 'trips.txt').write_text('route_id,service_id,trip_id,direction_id,shape_id,trip_headsign,trip_short_name\n' +
            ''.join(f'R,{service},{tid},{direction},,{headsign},{note}\n'
                    for tid, service, direction, headsign, note, time, path in specs), encoding='utf-8')
        (root / 'stop_times.txt').write_text('trip_id,stop_id,stop_sequence,departure_time\n' +
            ''.join(f'{tid},{sid},{i+1},{time}\n' for tid, service, direction, headsign, note, time, path in specs
                    for i, sid in enumerate(path)), encoding='utf-8')
        return line_details(load_snapshot(root), 'R')

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

    def test_restrictions_are_exposed_and_not_merged_with_unrestricted_trips(self):
        root = Path(self.temp.name)
        (root / 'stop_times.txt').write_text(
            'trip_id,stop_id,stop_sequence,departure_time,pickup_type,drop_off_type\n'
            'T1,A,1,08:00:00,0,1\nT1,B,2,08:20:00,1,0\n'
            'T2,A,1,24:15:00,0,0\nT2,B,2,24:30:00,0,0\n'
            'T3,B,1,,,\nT3,A,2,09:30:00,,\n', encoding='utf-8')
        snapshot = load_snapshot(root)
        with patch('api.index._state', return_value=(snapshot, {})):
            data = TestClient(app).get('/api/lines/R').json()
        self.assertEqual(len(data['variants']), 3)
        restricted = next(v for v in data['variants'] if not v['stops'][0]['dropoff_allowed'])
        self.assertEqual([(s['pickup_allowed'], s['dropoff_allowed']) for s in restricted['stops']],
                         [(True, False), (False, True)])
        self.assertEqual(restricted['timetables'][0]['departures'], ['08:00:00'])
        unrestricted = next(v for v in data['variants']
                            if v['direction_id'] == '0' and v['stops'][0]['dropoff_allowed'])
        self.assertEqual(unrestricted['timetables'][0]['departures'], ['24:15:00'])

    def test_loop_permissions_belong_to_each_stop_occurrence(self):
        root = Path(self.temp.name)
        (root / 'stop_times.txt').write_text(
            'trip_id,stop_id,stop_sequence,departure_time,pickup_type,drop_off_type\n'
            'T1,A,1,08:00:00,0,1\nT1,B,2,08:20:00,0,0\nT1,A,3,08:40:00,1,0\n'
            'T2,A,1,24:15:00,0,0\nT2,B,2,24:30:00,0,0\n'
            'T3,B,1,,,\nT3,A,2,09:30:00,,\n', encoding='utf-8')
        variants = line_details(load_snapshot(root), 'R')['variants']
        loop = next(v for v in variants if len(v['stops']) == 3)
        self.assertEqual(loop['stops'][0]['id'], loop['stops'][2]['id'])
        self.assertEqual((loop['stops'][0]['pickup_allowed'], loop['stops'][0]['dropoff_allowed']), (True, False))
        self.assertEqual((loop['stops'][2]['pickup_allowed'], loop['stops'][2]['dropoff_allowed']), (False, True))

    def test_departure_notes_headsigns_and_time_collisions_are_preserved(self):
        data = self._trip_variant_feed()
        tables = next(g for g in data['direction_timetables'] if g['direction_id'] == '0')['timetables']
        weekday = next(t for t in tables if t['service_id'] == 'W')
        trips = {trip['trip_id']: trip for trip in weekday['trips']}
        conditions = {c['id']: c['explanation'] for c in data['conditions']}
        self.assertIsNone(trips['R1']['condition_id'])
        self.assertEqual(len([t for t in weekday['trips'] if t['time'] == '08:00:00']), 2)
        self.assertIn('Sefer tabelası: Otogar', conditions[trips['HEAD']['condition_id']])
        self.assertNotIn('Sadece', conditions[trips['HEAD']['condition_id']])
        self.assertEqual(trips['NOTE']['time'], '26:00:00')
        self.assertEqual(conditions[trips['NOTE']['condition_id']], 'VADİKENT GİDER.')
        self.assertNotIn('#2150de', str(data['conditions']))
        self.assertNotIn('MISSING', trips)
        sunday = next(t for t in tables if t['service_id'] == 'S')
        self.assertEqual(sunday['trips'][0]['condition_id'], trips['NOTE']['condition_id'])

    def test_short_turn_and_alternate_paths_link_to_correct_map_variants(self):
        data = self._trip_variant_feed()
        trips = {trip['trip_id']: trip for group in data['direction_timetables']
                 for table in group['timetables'] for trip in table['trips']}
        conditions = {c['id']: c['explanation'] for c in data['conditions']}
        self.assertIn('Sadece Otogar durağına kadar gider.', conditions[trips['SHORT']['condition_id']])
        self.assertIn('Alternatif güzergâh', conditions[trips['ALT']['condition_id']])
        short_path = next(v for v in data['variants'] if v['id'] == trips['SHORT']['variant_id'])
        self.assertEqual([s['name'] for s in short_path['stops']], ['İskele', 'Otogar'])
        alternate = next(v for v in data['variants'] if v['id'] == trips['ALT']['variant_id'])
        self.assertEqual([s['name'] for s in alternate['stops']], ['İskele', 'Hastane', 'Merkez'])
        self.assertIsNone(trips['BACK']['condition_id'])

    def test_regular_line_has_no_special_legend_conditions(self):
        self.assertEqual(line_details(self.snapshot, 'R')['conditions'], [])

    def test_unknown_directions_do_not_mix_unrelated_path_timetables(self):
        self._trip_variant_feed()
        root = Path(self.temp.name)
        path = root / 'trips.txt'
        path.write_text(path.read_text(encoding='utf-8').replace(',0,', ',,').replace(',1,', ',,'), encoding='utf-8')
        data = line_details(load_snapshot(root), 'R')
        self.assertTrue(all(len(group['variant_ids']) == 1 for group in data['direction_timetables']))


if __name__ == '__main__':
    unittest.main()
