"""Line information built from the same Kocaeli snapshot as routing."""

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
        stops = [{"id": int(stop.id), "name": stop.name, "code": stop.code,
                  "district": stop.district, "latitude": stop.latitude,
                  "longitude": stop.longitude}
                 for stop in (snapshot.stops[sid] for sid in pattern.stop_ids)]
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
                               "departures": times})
        path_key = (pattern.direction_id, pattern.stop_ids, pattern.shape_id, pattern.shape_usable)
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
            continue
        variant = {"id": int(pattern.id), "direction_id": pattern.direction_id,
                         "name": " / ".join(sorted(pattern.headsigns)) or stops[-1]["name"],
                         "origin": stops[0]["name"], "destination": stops[-1]["name"],
                         "stops": stops, "timetables": timetables,
                         "geometry_source": "shape" if pattern.shape_usable and pattern.shape_points else "stops",
                         "geometry": [{"latitude": lat, "longitude": lon} for lat, lon in geometry]}
        variants_by_path[path_key] = variant
        variants.append(variant)
    return {**route, "variants": variants, "schedule_source": "static_gtfs"}
