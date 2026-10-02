"""Parse Turkish stop-to-stop bus requests without a fixed district list."""

from __future__ import annotations

from typing import TypedDict


class StopQuery(TypedDict):
    district: str
    name: str


class TripIntent(TypedDict):
    origin: StopQuery
    destination: StopQuery


def _turkish_key(text: str) -> str:
    return text.translate(str.maketrans({"I": "ı", "İ": "i"})).lower().translate(
        str.maketrans({"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"})
    )


def extract_trip_intent(message: str) -> TripIntent | None:
    """Parse ``origin durağından destination durağına`` in Turkish."""

    folded = _turkish_key(message)
    origin_marker = _turkish_key("durağından")
    destination_marker = _turkish_key("durağına")
    origin_end = folded.find(origin_marker)
    if origin_end < 0:
        return None
    destination_start = origin_end + len(origin_marker)
    destination_end = folded.find(destination_marker, destination_start)
    if destination_end < 0:
        return None
    origin = message[:origin_end].strip(" \t.,;:")
    destination = message[destination_start:destination_end].strip(" \t.,;:")
    if not origin or not destination:
        return None
    return {
        "origin": {"district": "", "name": origin},
        "destination": {"district": "", "name": destination},
    }
