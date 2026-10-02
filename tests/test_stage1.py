"""Stage 1 tests for canonical GTFS snapshot and routing indexes.

Run from ``backend`` with:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from api.app.data.loader import load_snapshot
from api.app.schemas.snapshot import Weekday


class Stage1SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.feed_dir = Path(self.temp_dir.name)
        self._write_feed()
        self.snapshot = load_snapshot(self.feed_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_groups_identical_trips_but_keeps_service_days_distinct(self) -> None:
        """Same route/direction/stops/days form one pattern; Sunday does not."""

        self.assertEqual(len(self.snapshot.patterns), 3)

        weekday_outbound = self._pattern(
            route_id="R1",
            direction_id="0",
            stop_gtfs_ids=("S1", "S2", "S3"),
        )
        self.assertEqual(weekday_outbound.service_ids, frozenset({"WEEKDAY"}))
        self.assertEqual(
            weekday_outbound.operating_days,
            frozenset(
                {
                    Weekday.MONDAY,
                    Weekday.TUESDAY,
                    Weekday.WEDNESDAY,
                    Weekday.THURSDAY,
                    Weekday.FRIDAY,
                }
            ),
        )

        sunday_loop = self._pattern(
            route_id="R1",
            direction_id="0",
            stop_gtfs_ids=("S1", "S2", "S1"),
        )
        self.assertEqual(sunday_loop.operating_days, frozenset({Weekday.SUNDAY}))

    def test_compact_stop_ids_and_repeated_stop_positions_are_preserved(self) -> None:
        """Circular patterns record each occurrence rather than overwriting it."""

        stop_id_by_gtfs = {stop.gtfs_id: stop_id for stop_id, stop in self.snapshot.stops.items()}
        self.assertEqual(set(self.snapshot.stops), {0, 1, 2})

        sunday_loop = self._pattern(
            route_id="R1",
            direction_id="0",
            stop_gtfs_ids=("S1", "S2", "S1"),
        )
        loop_positions = self.snapshot.indexes.positions[sunday_loop.id]
        self.assertEqual(loop_positions[stop_id_by_gtfs["S1"]], (0, 2))
        self.assertEqual(loop_positions[stop_id_by_gtfs["S2"]], (1,))

        s1_occurrences = self.snapshot.indexes.occurrences_at_stop[stop_id_by_gtfs["S1"]]
        self.assertIn((sunday_loop.id, 0), s1_occurrences)
        self.assertIn((sunday_loop.id, 2), s1_occurrences)

    def test_core_indexes_are_complete_and_immutable(self) -> None:
        """Every stop has safe empty/non-empty lookups and mappings cannot mutate."""

        indexes = self.snapshot.indexes
        self.assertEqual(set(indexes.routes_at_stop), set(self.snapshot.stops))
        self.assertEqual(set(indexes.occurrences_at_stop), set(self.snapshot.stops))

        stop_id_by_gtfs = {stop.gtfs_id: stop_id for stop_id, stop in self.snapshot.stops.items()}
        s3_routes = indexes.routes_at_stop[stop_id_by_gtfs["S3"]]
        self.assertEqual(len(s3_routes), 2)  # weekday outbound + weekday inbound

        with self.assertRaises(TypeError):
            indexes.stops[0] = None  # type: ignore[index]
        with self.assertRaises(TypeError):
            indexes.positions[0] = {}  # type: ignore[index]

    def _pattern(
        self,
        *,
        route_id: str,
        direction_id: str,
        stop_gtfs_ids: tuple[str, ...],
    ):
        for pattern in self.snapshot.patterns.values():
            actual_stop_gtfs_ids = tuple(
                self.snapshot.stops[stop_id].gtfs_id for stop_id in pattern.stop_ids
            )
            if (
                pattern.route_id == route_id
                and pattern.direction_id == direction_id
                and actual_stop_gtfs_ids == stop_gtfs_ids
            ):
                return pattern
        self.fail(f"Pattern not found: {route_id=}, {direction_id=}, {stop_gtfs_ids=}")

    def _write_feed(self) -> None:
        self._write(
            "stops.txt",
            """stop_id,stop_name,stop_lat,stop_lon
S1,First stop,41.0000,29.0000
S2,Second stop,41.0100,29.0100
S3,Third stop,41.0200,29.0200
""",
        )
        self._write(
            "routes.txt",
            """route_id,route_short_name,route_long_name,route_type
R1,1,Test route,3
""",
        )
        self._write(
            "calendar.txt",
            """service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date
WEEKDAY,1,1,1,1,1,0,0,20260101,20261231
SUNDAY,0,0,0,0,0,0,1,20260101,20261231
""",
        )
        self._write(
            "trips.txt",
            """route_id,service_id,trip_id,direction_id
R1,WEEKDAY,T1,0
R1,WEEKDAY,T2,0
R1,SUNDAY,T3,0
R1,WEEKDAY,T4,1
""",
        )
        self._write(
            "stop_times.txt",
            """trip_id,arrival_time,departure_time,stop_id,stop_sequence
T1,08:00:00,08:00:00,S1,1
T1,08:05:00,08:05:00,S2,2
T1,08:10:00,08:10:00,S3,3
T2,09:00:00,09:00:00,S1,1
T2,09:05:00,09:05:00,S2,2
T2,09:10:00,09:10:00,S3,3
T3,10:00:00,10:00:00,S1,1
T3,10:05:00,10:05:00,S2,2
T3,10:10:00,10:10:00,S1,3
T4,11:00:00,11:00:00,S3,1
T4,11:05:00,11:05:00,S2,2
T4,11:10:00,11:10:00,S1,3
""",
        )

    def _write(self, filename: str, contents: str) -> None:
        (self.feed_dir / filename).write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
