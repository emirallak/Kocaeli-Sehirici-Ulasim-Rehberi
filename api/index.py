"""Kocaeli transit route chat API."""

from __future__ import annotations

import logging
import os
from difflib import get_close_matches
from datetime import datetime, timedelta, timezone
from math import ceil
from bisect import bisect_left, bisect_right
from functools import lru_cache
from threading import Lock

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.app.api.stops import StopNameIndex, build_stop_catalog, build_stop_name_index, normalize_text, resolve_stop_ids
from api.app.chat.intent import extract_trip_intent
from api.app.data.loader import GTFSLoadError, load_snapshot
from api.app.data.transport import public_line_code
from api.app.routing.reconstruct import reconstruct_itinerary
from api.app.routing.metrics import itinerary_metres, leg_metres, itinerary_minutes, leg_minutes, BOARDING_WAIT_MINUTES
from api.app.routing.metrics import RoutingMode
from api.app.routing.search import best_routes
from api.app.schemas.itinerary import Itinerary, Leg
from api.app.schemas.snapshot import RoutingSnapshot, Weekday


app = FastAPI(title="Kocaeli Ulaşım Rota Planlayıcı", version="0.2.0")
logger = logging.getLogger(__name__)
RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "app", "data", "raw")
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "..", "public")
_snapshot_lock = Lock()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1_000)
    limit: int = Field(default=3, ge=1, le=20)
    routing_mode: RoutingMode = "fewest_transfers"


@app.on_event("startup")
def load_static_snapshot() -> None:
    """Load the local Kocaeli routing graph once per API process."""

    try:
        snapshot = load_snapshot(RAW_DATA_DIR)
    except (GTFSLoadError, OSError, EOFError) as error:
        logger.error("Kocaeli data is unavailable: %s", error)
        app.state.load_error = str(error)
        return
    _install_snapshot(snapshot)


def _install_snapshot(snapshot: RoutingSnapshot) -> None:
    stop_name_index = build_stop_name_index(snapshot.indexes)
    if not snapshot.patterns or not stop_name_index.get(""):
        raise GTFSLoadError("GTFS feed contains no routable stops")
    app.state.snapshot = snapshot
    app.state.load_error = None
    app.state.stop_name_index = stop_name_index
    app.state.stop_catalog = (snapshot, build_stop_catalog(snapshot.indexes))
    @lru_cache(maxsize=64)
    def plan(origins, destinations, limit, routing_mode):
        counts = {}
        routes = best_routes(snapshot.indexes, origins, destinations, limit, counts, routing_mode)
        return routes, counts
    app.state.route_plan = (snapshot, plan)


@app.post("/api/chat")
@app.post("/chat", include_in_schema=False)
def chat(request: ChatRequest) -> dict[str, object]:
    """Return bus, tram, and walking routes ranked by direct priority and estimated travel time."""

    snapshot, stop_name_index = _state()
    intent = extract_trip_intent(request.message)
    logger.info("Parsed transit intent: %r", intent)
    if intent is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Örnek: Otogar durağından Seka Park durağına."
            ),
        )

    indexes = snapshot.indexes
    # Cache keys must be immutable even if a future resolver returns lists.
    origin_ids = tuple(dict.fromkeys(_resolve_query(intent["origin"], stop_name_index, indexes)))
    destination_ids = tuple(dict.fromkeys(_resolve_query(intent["destination"], stop_name_index, indexes)))
    for stop_id in origin_ids:
        _log_resolved_stop("origin candidate", stop_id, snapshot)
    for stop_id in destination_ids:
        _log_resolved_stop("destination candidate", stop_id, snapshot)
    if not origin_ids or not destination_ids:
        unresolved = []
        if not origin_ids:
            unresolved.append(intent["origin"])
        if not destination_ids:
            unresolved.append(intent["destination"])
        suggestions = {
            query["name"]: _stop_suggestions(query["name"], stop_name_index, indexes)
            for query in unresolved
        }
        names = ", ".join(query["name"] for query in unresolved)
        near = list(dict.fromkeys(name for choices in suggestions.values() for name in choices))
        message = f"Durak bulunamadı: {names}."
        if near:
            message += " Yakın duraklar: " + ", ".join(near) + "."
        raise HTTPException(status_code=422, detail={
            "message": message,
            "unresolved_queries": unresolved,
            "suggestions": suggestions,
        })

    candidate_counts: dict[str, int | None] = {}
    cached = getattr(app.state, 'route_plan', None)
    if cached is not None and cached[0] is snapshot:
        best, candidate_counts = cached[1](origin_ids, destination_ids, request.limit, request.routing_mode)
    else:
        best = best_routes(indexes, origin_ids, destination_ids, request.limit, candidate_counts, request.routing_mode)
    departure = datetime.now(timezone(timedelta(hours=3)))
    itineraries = [
        _itinerary_to_response(snapshot, reconstruct_itinerary(indexes, itinerary.legs), departure)
        for itinerary in best
    ]
    logger.info(
        "Routing candidate counts: direct=%s one_transfer=%s two_transfers=%s "
        "returned_top_k=%d",
        candidate_counts["direct"],
        candidate_counts["one_transfer"],
        candidate_counts["two_transfers"],
        len(itineraries),
    )
    if not itineraries:
        logger.warning(
            "No itinerary found within three transfers for origin_candidates=%s "
            "destination_candidates=%s",
            origin_ids,
            destination_ids,
        )

    # The summary describes the best route's actual platforms, not the first
    # arbitrary match. Every itinerary retains its own endpoint IDs in its legs.
    origin_id = best[0].legs[0].board_stop if best else origin_ids[0]
    destination_id = best[0].legs[-1].alight_stop if best else destination_ids[0]
    return {
        "origin": _stop_to_response(snapshot, origin_id),
        "destination": _stop_to_response(snapshot, destination_id),
        "routing_mode": request.routing_mode,
        "itineraries": itineraries,
    }


@app.get("/api/health")
@app.get("/health", include_in_schema=False)
def health() -> dict[str, int | str]:
    snapshot, _ = _state()
    return {"status": "ok", "stops": len(snapshot.stops), "patterns": len(snapshot.patterns)}


@app.get("/api/stops")
@app.get("/stops", include_in_schema=False)
def stops(q: str = Query(default="", max_length=200),
          limit: int = Query(default=12, ge=1, le=50)) -> dict[str, object]:
    """Return a compact active-stop catalog, or ranked autocomplete matches.

    An empty query returns the full catalog for instant browser-side filtering.
    Directional platforms sharing a name/district appear as one suggestion.
    """
    snapshot, _ = _state()
    cached = getattr(app.state, "stop_catalog", None)
    if cached is None or cached[0] is not snapshot:
        cached = (snapshot, build_stop_catalog(snapshot.indexes))
        app.state.stop_catalog = cached
    query = normalize_text(q)
    if not query:
        return {"stops": cached[1] if not q.strip() else []}
    matches = [stop for stop in cached[1] if query in normalize_text(stop["name"])]
    matches.sort(key=lambda stop: (not normalize_text(stop["name"]).startswith(query),
                                   normalize_text(stop["name"]), stop["district"]))
    return {"stops": matches[:limit]}


def _resolve_query(query, stop_name_index, indexes):
    """Try the stop name before municipality text used by map search boxes."""
    name = query.get("name", "")
    short_name = normalize_text(name.split(",", 1)[0])
    for suffix in (" kocaeli merkezi", " kocaeli merkez", " kocaeli", " izmit merkez"):
        if short_name.endswith(suffix):
            short_name = short_name[:-len(suffix)].strip()
            break
    if short_name and short_name != normalize_text(name):
        matches = resolve_stop_ids({**query, "name": short_name}, stop_name_index, indexes)
        if matches:
            return matches
    return resolve_stop_ids(query, stop_name_index, indexes)


def _stop_suggestions(name, stop_name_index, indexes):
    names = stop_name_index.get("", {})
    query = normalize_text(name.split(",", 1)[0])
    matches = get_close_matches(query, names.keys(), n=3, cutoff=0.70)
    return [indexes.stops[names[key][0]].name for key in matches]


def _log_resolved_stop(
    side: str, stop_id: int | None, snapshot: RoutingSnapshot
) -> None:
    if stop_id is None:
        logger.warning("Resolved %s stop: no match", side)
        return
    stop = snapshot.stops[stop_id]
    active_patterns = len(snapshot.indexes.routes_at_stop[stop_id])
    logger.info(
        "Resolved %s: stop_id=%s gtfs_stop_id=%r stop_name=%r district=%r "
        "active_patterns=%d",
        side,
        int(stop_id),
        stop.gtfs_id,
        stop.name,
        stop.district,
        active_patterns,
    )


def _state() -> tuple[RoutingSnapshot, StopNameIndex]:
    if not hasattr(app.state, "snapshot"):
        with _snapshot_lock:
            if not hasattr(app.state, "snapshot"):
                if getattr(app.state, "load_error", None):
                    raise HTTPException(status_code=503, detail=app.state.load_error)
                try:
                    _install_snapshot(load_snapshot(RAW_DATA_DIR))
                except (GTFSLoadError, OSError, EOFError) as error:
                    app.state.load_error = str(error)
                    raise HTTPException(status_code=503, detail=str(error)) from error
    return app.state.snapshot, app.state.stop_name_index


def _stop_to_response(snapshot: RoutingSnapshot, stop_id: int) -> dict[str, object]:
    stop = snapshot.stops[stop_id]
    return {
        "id": int(stop.id),
        "name": stop.name,
        "code": stop.code,
        "district": stop.district,
        "latitude": stop.latitude,
        "longitude": stop.longitude,
    }


def _weekday_names(days: frozenset[Weekday]) -> list[str]:
    return [day.name.lower() for day in sorted(days)]


def _itinerary_to_response(snapshot: RoutingSnapshot, itinerary: Itinerary, departure=None) -> dict[str, object]:
    departure = departure or datetime.now(timezone(timedelta(hours=3)))
    duration = ceil(itinerary_minutes(snapshot.indexes, itinerary))
    return {
        "estimated_duration_minutes": duration,
        "estimated_arrival_at": (departure + timedelta(minutes=duration)).isoformat(),
        "estimated_departure_at": departure.isoformat(),
        "time_estimate_basis": "static_distance_and_average_speed",
        "assumed_wait_minutes_per_boarding": BOARDING_WAIT_MINUTES,
        "is_direct": itinerary.transit_leg_count == 1,
        "transfers": max(0, itinerary.transit_leg_count - 1),
        "total_distance_metres": round(itinerary_metres(snapshot.indexes, itinerary)),
        "walking_metres": sum(leg.walking_metres or 0 for leg in itinerary.legs),
        "has_tram": any(leg.mode == "Tramvay" for leg in itinerary.legs),
        "total_stop_hops": sum(
            leg.alight_index - leg.board_index for leg in itinerary.legs
        ),
        "operating_days": _weekday_names(itinerary.operating_days),
        "legs": [
            {
                "pattern_id": int(leg.pattern_id) if leg.pattern_id is not None else None,
                "is_walking": leg.is_walking,
                "walking_metres": leg.walking_metres,
                "distance_metres": round(leg_metres(snapshot.indexes, leg)),
                "estimated_duration_minutes": ceil(leg_minutes(snapshot.indexes, leg)),
                "mode": leg.mode,
                "route_id": leg.route_id,
                "route_code": public_line_code(leg.route_code or leg.route_id),
                "direction_id": leg.direction_id,
                "headsigns": sorted(leg.headsigns),
                "operating_days": _weekday_names(leg.operating_days),
                "board_stop": {
                    "id": int(leg.board_stop),
                    "name": leg.board_stop_name,
                    "latitude": snapshot.indexes.stops[leg.board_stop].latitude,
                    "longitude": snapshot.indexes.stops[leg.board_stop].longitude,
                },
                "alight_stop": {
                    "id": int(leg.alight_stop),
                    "name": leg.alight_stop_name,
                    "latitude": snapshot.indexes.stops[leg.alight_stop].latitude,
                    "longitude": snapshot.indexes.stops[leg.alight_stop].longitude,
                },
                "board_index": leg.board_index,
                "alight_index": leg.alight_index,
                "geometry": _leg_geometry(snapshot, leg),
            }
            for leg in itinerary.legs
        ],
    }


def _leg_geometry(snapshot: RoutingSnapshot, leg: Leg) -> list[dict[str, float]]:
    """Return ordered Kocaeli stop coordinates for drawing a ride on a map."""

    if leg.is_walking or leg.pattern_id is None:
        stop_ids = (leg.board_stop, leg.alight_stop)
    else:
        pattern = snapshot.patterns[leg.pattern_id]
        if pattern.shape_usable and pattern.shape_points and pattern.shape_metres and pattern.metres_at_stop:
            start = bisect_left(pattern.shape_metres, pattern.metres_at_stop[leg.board_index])
            end = bisect_right(pattern.shape_metres, pattern.metres_at_stop[leg.alight_index])
            if end > start:
                board = snapshot.stops[leg.board_stop]
                alight = snapshot.stops[leg.alight_stop]
                points = [(board.latitude, board.longitude)] + list(pattern.shape_points[start:end]) + [(alight.latitude, alight.longitude)]
                return [
                    {"latitude": lat, "longitude": lon}
                    for lat, lon in points if lat is not None and lon is not None
                ]
        stop_ids = pattern.stop_ids[leg.board_index : leg.alight_index + 1]
    return [
        {"latitude": stop.latitude, "longitude": stop.longitude}
        for stop_id in stop_ids
        if (stop := snapshot.stops[stop_id]).latitude is not None
        and stop.longitude is not None
    ]


# Vercel serves public/ from its CDN. Keep a same-origin local development
# server so the browser can call /api/chat without a separate proxy.
if not os.getenv("VERCEL") and os.path.isdir(PUBLIC_DIR):
    app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
