"""Local Kocaeli GTFS source regression tests."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from api.app.chat.intent import extract_trip_intent
from api.app.data.kocaeli import load_kocaeli_snapshot
from api.app.data.loader import GTFSLoadError
from api.index import _leg_geometry
from api.app.routing.search import best_routes


TABLES = {
    "stops": "stop_id,stop_name,stop_lat,stop_lon\nA,OTOGAR,40.776242,29.97576606\nB,SEKA PARK,40.76133208,29.91089154\nC,GEBZE OTOGAR 2,40.7951573,29.4584938\n",
    "routes": "route_id,route_short_name,route_type\nBUS,100,3\nRAIL,T1,0\n",
    "calendar": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday\nW,1,1,1,1,1,1,1\n",
    "trips": "route_id,service_id,trip_id,direction_id\nBUS,W,B1,0\nRAIL,W,R1,0\n",
    "stop_times": "trip_id,stop_id,stop_sequence\nB1,A,1\nB1,B,2\nB1,C,3\nR1,A,1\nR1,C,2\n",
}


class KocaeliSourceTests(unittest.TestCase):
    def test_local_feed_includes_tram_and_renders_stop_geometry(self):
        with TemporaryDirectory() as directory:
            for table, csv_text in TABLES.items():
                (Path(directory) / f"{table}.txt").write_text(csv_text, encoding="utf-8")
            with patch("api.app.data.kocaeli.RAW_DATA_DIR", Path(directory)):
                snapshot = load_kocaeli_snapshot()
        self.assertEqual(set(snapshot.routes), {"BUS", "RAIL"})
        self.assertEqual(len(snapshot.patterns), 2)
        route = next(
            item for item in best_routes(snapshot.indexes, [0], [2], 2)
            if item.legs[0].mode == "Otobüs"
        )
        geometry = _leg_geometry(snapshot, route.legs[0])
        self.assertEqual(len(geometry), 3)
        self.assertEqual(geometry[0], {"latitude": 40.776242, "longitude": 29.97576606})

    def test_missing_local_feed_is_reported(self):
        with TemporaryDirectory() as directory:
            with patch("api.app.data.kocaeli.RAW_DATA_DIR", Path(directory) / "missing"):
                with self.assertRaisesRegex(GTFSLoadError, "GTFS data directory does not exist"):
                    load_kocaeli_snapshot()

    def test_chat_intent_accepts_kocaeli_names_without_fixed_districts(self):
        intent = extract_trip_intent("Otogar durağından Seka Park durağına")
        self.assertEqual(intent["origin"], {"district": "", "name": "Otogar"})
        self.assertEqual(intent["destination"], {"district": "", "name": "Seka Park"})


if __name__ == "__main__":
    unittest.main()
