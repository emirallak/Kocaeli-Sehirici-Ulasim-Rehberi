"""The prebuilt snapshot cache must round-trip and never serve stale data."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from api.app.data.cache import fingerprint, load_cached_snapshot, read_cache, write_cache
from api.app.data.loader import load_snapshot


FEED = {
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                    "WK,1,1,1,1,1,0,0,20240101,20991231\n",
    "routes.txt": "route_id,route_short_name,route_long_name,route_type\nR,10,Ten,3\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n"
                 "A,Alpha,40.7600,29.9000\nB,Beta,40.7650,29.9100\nC,Gamma,40.7700,29.9200\n",
    "trips.txt": "route_id,service_id,trip_id,direction_id\nR,WK,T1,0\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                      "T1,08:00:00,08:00:00,A,1\nT1,08:05:00,08:05:00,B,2\nT1,08:10:00,08:10:00,C,3\n",
}


class SnapshotCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        for name, content in FEED.items():
            (self.raw / name).write_bytes(content.encode())
        self.cache = self.root / "snapshot.pickle.xz"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_round_trip_preserves_the_routing_graph(self) -> None:
        snapshot = load_snapshot(self.raw)
        write_cache(snapshot, self.raw, self.cache)
        cached = read_cache(self.raw, self.cache)
        self.assertEqual(dict(cached.stops), dict(snapshot.stops))
        self.assertEqual(dict(cached.patterns), dict(snapshot.patterns))
        self.assertEqual(dict(cached.indexes.walking_neighbors), dict(snapshot.indexes.walking_neighbors))
        # Read-only mappings stay read-only after unpickling.
        with self.assertRaises(TypeError):
            cached.indexes.stops[999] = None

    def test_changed_feed_makes_the_cache_stale(self) -> None:
        write_cache(load_snapshot(self.raw), self.raw, self.cache)
        with (self.raw / "stops.txt").open("a") as stops:
            stops.write("D,Delta,40.7750,29.9300\n")
        self.assertIsNone(read_cache(self.raw, self.cache))
        # The fallback rebuilds from GTFS and refreshes the cache.
        self.assertEqual(len(load_cached_snapshot(self.raw, self.cache).stops), 4)
        self.assertIsNotNone(read_cache(self.raw, self.cache))

    def test_line_endings_do_not_change_the_fingerprint(self) -> None:
        before = fingerprint(self.raw)
        for path in self.raw.iterdir():
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(fingerprint(self.raw), before)

    def test_missing_or_corrupt_cache_is_ignored(self) -> None:
        self.assertIsNone(read_cache(self.raw, self.cache))
        self.cache.write_bytes(b"garbage")
        self.assertIsNone(read_cache(self.raw, self.cache))


if __name__ == "__main__":
    unittest.main()
