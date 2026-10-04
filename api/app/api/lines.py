"""Line information built from the same Kocaeli snapshot as routing."""

from collections import Counter
from api.app.api.stops import normalize_text
from api.app.data.transport import public_line_code, route_mode
from api.app.schemas.snapshot import RoutingSnapshot


def line_catalog(snapshot: RoutingSnapshot) -> list[dict]:
    routable = {pattern.route_id for pattern in snapshot.patterns.values()}
    lines = [{"id": route.gtfs_id,
              "code": public_line_code(route.short_name or route.code or route.gtfs_id),
              "name": route.long_name or route.short_name or route.gtfs_id,
              "mode": route_mode(route)}
             for route in snapshot.routes.values() if route.gtfs_id in routable]
    return sorted(lines, key=lambda line: (not line["code"].isdigit(),
                  int(line["code"]) if line["code"].isdigit() else 0, line["code"], line["name"]))


def line_details(snapshot: RoutingSnapshot, route_id: str) -> dict:
    route = next((line for line in line_catalog(snapshot) if line["id"] == route_id), None)
    if route is None:
        raise KeyError(route_id)
    variants = []
    variants_by_path = {}
    for pattern in snapshot.patterns.values():
        if pattern.route_id != route_id:
            continue
        pickup = pattern.pickup_allowed or (True,) * len(pattern.stop_ids)
        dropoff = pattern.dropoff_allowed or (True,) * len(pattern.stop_ids)
        stops = [{"id": int(stop.id), "name": stop.name, "code": stop.code,
                  "district": stop.district, "latitude": stop.latitude,
                  "longitude": stop.longitude,
                  "pickup_allowed": pickup[position], "dropoff_allowed": dropoff[position]}
                 for position, stop in enumerate(snapshot.stops[sid] for sid in pattern.stop_ids)]
        geometry = (pattern.shape_points if pattern.shape_usable and pattern.shape_points
                    else tuple((stop["latitude"], stop["longitude"]) for stop in stops
                               if stop["latitude"] is not None and stop["longitude"] is not None))
        timetables = []
        for service_id in sorted(pattern.service_ids):
            calendar = snapshot.service_calendars[service_id]
            times = sorted({time for sid, time in pattern.departures if sid == service_id},
                           key=lambda time: tuple(map(int, time.split(":"))))
            timetables.append({"service_id": service_id,
                               "operating_days": [int(day) for day in sorted(calendar.operating_days)],
                               "start_date": calendar.start_date.isoformat() if calendar.start_date else None,
                               "end_date": calendar.end_date.isoformat() if calendar.end_date else None,
                               "departures": times,
                               "trips": [{"trip_id": trip.trip_id, "time": trip.time,
                                          "headsign": trip.headsign, "note": trip.note,
                                          "flagged": trip.flagged}
                                         for trip in pattern.trip_departures if trip.service_id == service_id]})
        # Never combine schedules whose stop permissions differ, even when
        # their geometry matches. Permissions belong to each stop occurrence.
        path_key = (pattern.direction_id, pattern.stop_ids, pattern.shape_id, pattern.shape_usable,
                    pickup, dropoff)
        existing = variants_by_path.get(path_key)
        if existing is not None:
            for table in timetables:
                previous = next((entry for entry in existing["timetables"]
                                 if entry["service_id"] == table["service_id"]), None)
                if previous is None:
                    existing["timetables"].append(table)
                else:
                    previous["departures"] = sorted(set(previous["departures"]) | set(table["departures"]),
                                                    key=lambda time: tuple(map(int, time.split(":"))))
                    previous["trips"].extend(table["trips"])
            continue
        variant = {"id": int(pattern.id), "direction_id": pattern.direction_id,
                         "name": " / ".join(sorted(pattern.headsigns)) or stops[-1]["name"],
                         "origin": stops[0]["name"], "destination": stops[-1]["name"],
                         "stops": stops, "timetables": timetables,
                         "shape_id": pattern.shape_id,
                         "geometry_source": "shape" if pattern.shape_usable and pattern.shape_points else "stops",
                         "geometry": [{"latitude": lat, "longitude": lon} for lat, lon in geometry]}
        variants_by_path[path_key] = variant
        variants.append(variant)
    direction_timetables, conditions = _trip_conditions(variants)
    return {**route, "variants": variants, "schedule_source": "static_gtfs",
            "direction_timetables": direction_timetables, "conditions": conditions}


def _trip_conditions(variants: list[dict]) -> tuple[list[dict], list[dict]]:
    """Compare trips only within a direction and preserve exact note/time pairs.

    The most frequent unflagged path is the reference, not a promise that it
    is the full route. Claim early termination only for a strict stop prefix.
    """
    directions = {}
    for variant in variants:
        # A missing direction ID does not prove two paths share a direction.
        key = variant["direction_id"] if variant["direction_id"] is not None else (None, variant["id"])
        directions.setdefault(key, []).append(variant)
    conditions, condition_ids, result = [], {}, []
    for paths in directions.values():
        direction = paths[0]["direction_id"]
        def trip_list(path):
            return [trip for table in path["timetables"] for trip in table["trips"]]

        reference = max(paths, key=lambda path: (
            sum(not trip["flagged"] for trip in trip_list(path)),
            len(path["stops"]), -path["id"]))
        reference_trips = [trip for trip in trip_list(reference) if not trip["flagged"]] or trip_list(reference)
        def common(field):
            return Counter(normalize_text(trip[field]) for trip in reference_trips).most_common(1)[0][0] if reference_trips else ""
        common_note, common_headsign = common("note"), common("headsign")
        reference_stops = [stop["id"] for stop in reference["stops"]]
        calendars = {}
        for path_index, path in enumerate(paths):
            stop_ids = [stop["id"] for stop in path["stops"]]
            for table in path["timetables"]:
                target = calendars.setdefault(table["service_id"], {
                    **{key: value for key, value in table.items() if key not in ("departures", "trips")},
                    "departures": [], "trips": []})
                # Hand-built snapshots without per-trip metadata still work.
                trips = table["trips"] or [{"time": time, "trip_id": "", "headsign": "", "note": "", "flagged": False}
                                            for time in table["departures"]]
                for trip in trips:
                    explanations = []
                    if trip["note"] and (trip["flagged"] or normalize_text(trip["note"]) != common_note):
                        explanations.append(trip["note"])
                    if stop_ids != reference_stops:
                        if len(stop_ids) < len(reference_stops) and stop_ids == reference_stops[:len(stop_ids)]:
                            explanations.append(f'Sadece {path["destination"]} durağına kadar gider.')
                        elif path["destination"] != reference["destination"]:
                            explanations.append(f'Son durak: {path["destination"]}.')
                        else:
                            explanations.append(f'Alternatif güzergâh: {path["origin"]} → {path["destination"]} (seçenek {path_index + 1}).')
                    elif (path["geometry_source"] == reference["geometry_source"] == "shape"
                          and path["geometry"] != reference["geometry"]):
                        explanations.append(f'Alternatif güzergâh çizgisi (seçenek {path_index + 1}).')
                    if [(s["pickup_allowed"], s["dropoff_allowed"]) for s in path["stops"]] != [
                            (s["pickup_allowed"], s["dropoff_allowed"]) for s in reference["stops"]] and stop_ids == reference_stops:
                        explanations.append('Bu seferde bazı durakların biniş/iniş izinleri farklıdır.')
                    if trip["headsign"] and normalize_text(trip["headsign"]) != common_headsign:
                        explanations.append(f'Sefer tabelası: {trip["headsign"]}.')
                    label = " · ".join(explanations)
                    condition_id = None
                    if label:
                        key = (direction, normalize_text(label))
                        if key not in condition_ids:
                            condition_ids[key] = f"condition-{len(conditions) + 1}"
                            conditions.append({"id": condition_ids[key], "explanation": label,
                                               "direction_id": direction})
                        condition_id = condition_ids[key]
                    target["trips"].append({**trip, "variant_id": path["id"], "condition_id": condition_id})
        for table in calendars.values():
            # Same clock with different conditions or paths remains distinct.
            unique = {(t["time"], t["condition_id"], t["variant_id"]): t for t in table["trips"]}
            table["trips"] = sorted(unique.values(), key=lambda t: (tuple(map(int, t["time"].split(":"))), t["variant_id"], t["condition_id"] or ""))
            table["departures"] = [trip["time"] for trip in table["trips"]]
        result.append({"direction_id": direction, "variant_ids": [path["id"] for path in paths],
                       "timetables": list(calendars.values())})
    return result, conditions
