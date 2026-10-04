import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from api.index import app
from api.app.api.stops import build_stop_name_index
from api.app.data.indexes import build_indexes
from api.app.schemas.snapshot import Stop, Pattern, Weekday, RoutingSnapshot


class StopAutocompleteTests(unittest.TestCase):
    def setUp(self):
        names = ['ÜNİVERSİTE', 'ÜNİVERSİTE', 'UZUNÇİFTLİK', 'YENİ CUMA DOĞU', 'Inactive']
        stops = {i: Stop(i, str(i), name, None, None, district='İzmit')
                 for i, name in enumerate(names)}
        patterns = {0: Pattern(0, 'A', '0', (0, 1, 2, 3), frozenset({'W'}),
                               frozenset(Weekday), 'A', frozenset())}
        indexes = build_indexes(stops, patterns)
        self.snapshot = RoutingSnapshot(indexes, {}, {})
        self.names = build_stop_name_index(indexes)

    def request(self, path, params=None):
        with patch('api.index._state', return_value=(self.snapshot, self.names)):
            return TestClient(app).get(path, params=params)

    def test_catalog_excludes_inactive_stops_and_groups_platforms(self):
        response = self.request('/api/stops')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['stops']), 3)
        self.assertNotIn('Inactive', [stop['name'] for stop in response.json()['stops']])

    def test_single_character_and_turkish_case_accent_matching(self):
        for query in ('U', 'ü', 'u'):
            names = [stop['name'] for stop in self.request('/api/stops', {'q': query}).json()['stops']]
            self.assertEqual(names[:2], ['ÜNİVERSİTE', 'UZUNÇİFTLİK'])
        self.assertEqual(self.request('/stops', {'q': 'yeni cuma dogu'}).json()['stops'][0]['name'],
                         'YENİ CUMA DOĞU')

    def test_limit_no_match_and_validation(self):
        self.assertEqual(len(self.request('/api/stops', {'q': 'U', 'limit': 1}).json()['stops']), 1)
        for query in ('zzzz', '!!!'):
            self.assertEqual(self.request('/api/stops', {'q': query}).json()['stops'], [])
        self.assertEqual(self.request('/api/stops', {'limit': 0}).status_code, 422)
        self.assertEqual(self.request('/api/stops', {'q': 'x' * 201}).status_code, 422)
