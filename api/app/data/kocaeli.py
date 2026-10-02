"""Load the Kocaeli GTFS feed bundled with the application."""

from __future__ import annotations

from pathlib import Path

from api.app.data.loader import load_snapshot
from api.app.schemas.snapshot import RoutingSnapshot


RAW_DATA_DIR = Path(__file__).resolve().parent / "raw"


def load_kocaeli_snapshot() -> RoutingSnapshot:
    """Build the routing graph from local GTFS tables without a network request."""

    return load_snapshot(RAW_DATA_DIR)
