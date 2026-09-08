#!/usr/bin/env python3
"""Build the public, browser-friendly Europe trip dataset from Google Timeline JSON.

The original Timeline JSON stays in source/ (private repo). Only site/data/trip-data.json
is deployed by GitHub Pages.

Country labels are resolved offline from a small set of bundled country polygons, so the
site does not need a geocoding API or an API key at runtime.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "Europe_trip_2017_timeline.json"
OUTPUT = ROOT / "site" / "data" / "trip-data.json"
COUNTRY_BOUNDARIES = ROOT / "scripts" / "data" / "trip_country_boundaries.json"

# Deliberately broad Europe bounding box for this 2017 road trip. It excludes Israel,
# where the Timeline export begins/ends, while retaining the Balkans and eastern Europe.
EUROPE_BOUNDS = {
    "minLat": 34.5,
    "maxLat": 72.0,
    "minLon": -25.0,
    "maxLon": 45.0,
}

POINT_RE = re.compile(r"\s*(-?\d+(?:\.\d+)?)°?\s*,\s*(-?\d+(?:\.\d+)?)°?\s*")


def parse_latlon(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    match = POINT_RE.fullmatch(value)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def in_europe(point: tuple[float, float] | None) -> bool:
    if not point:
        return False
    lat, lon = point
    return (
        EUROPE_BOUNDS["minLat"] <= lat <= EUROPE_BOUNDS["maxLat"]
        and EUROPE_BOUNDS["minLon"] <= lon <= EUROPE_BOUNDS["maxLon"]
    )


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0088
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def parse_time(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def duration_minutes(start: str, end: str) -> float:
    try:
        return max(0.0, (parse_time(end) - parse_time(start)).total_seconds() / 60.0)
    except Exception:
        return 0.0


def local_hhmm(iso: str, utc_offset_minutes: int | None) -> str:
    """Display the intended local wall-clock time when the segment provides its offset."""
    try:
        dt = parse_time(iso)
        if utc_offset_minutes is None:
            return iso[11:16]
        utc_ts = dt.timestamp()
        local_ts = datetime.fromtimestamp(utc_ts + utc_offset_minutes * 60, UTC)
        return local_ts.strftime("%H:%M")
    except Exception:
        return iso[11:16] if len(iso) >= 16 else iso


def normalize_activity(raw_type: str | None, distance_m: float, minutes: float) -> tuple[str, str]:
    """Normalize Google's activity guesses.

    The user confirmed there were no bicycles. CYCLING is therefore reclassified as
    walking when its pace/distance is plausible on foot, otherwise generic riding.
    MOTORCYCLING is also displayed as generic riding.
    """
    raw = raw_type or "UNKNOWN_ACTIVITY_TYPE"
    hours = minutes / 60.0 if minutes > 0 else 0.0
    speed_kmh = (distance_m / 1000.0) / hours if hours > 0 else 0.0

    if raw == "CYCLING":
        if distance_m <= 5000 and speed_kmh <= 9.0:
            return "walking", "Walking"
        return "riding", "Riding"

    mapping = {
        "WALKING": ("walking", "Walking"),
        "IN_PASSENGER_VEHICLE": ("car", "Car / ride"),
        "IN_BUS": ("bus", "Bus"),
        "IN_TRAIN": ("train", "Train"),
        "IN_TRAM": ("tram", "Tram"),
        "IN_SUBWAY": ("subway", "Subway"),
        "MOTORCYCLING": ("riding", "Riding"),
        "FLYING": ("flight", "Flight"),
        "UNKNOWN_ACTIVITY_TYPE": ("other", "Movement"),
    }
    return mapping.get(raw, ("other", raw.replace("_", " ").title()))


def _walk_coordinates(value: Any):
    if isinstance(value, list):
        if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
            yield float(value[0]), float(value[1])
        else:
            for item in value:
                yield from _walk_coordinates(item)


def _geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    coords = list(_walk_coordinates(geometry.get("coordinates")))
    if not coords:
        return (-180.0, -90.0, 180.0, 90.0)
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test for one linear ring."""
    if len(ring) < 3:
        return False
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_intersection = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-30) + xi
            if lon < x_intersection:
                inside = not inside
        j = i
    return inside


def _point_in_geometry(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates if geometry_type == "MultiPolygon" else []
    for polygon in polygons:
        if not polygon or not _point_in_ring(lon, lat, polygon[0]):
            continue
        # A point is in the polygon when it is inside the exterior ring and not in a hole.
        if not any(_point_in_ring(lon, lat, hole) for hole in polygon[1:]):
            return True
    return False


def load_country_boundaries() -> list[dict[str, Any]]:
    if not COUNTRY_BOUNDARIES.exists():
        raise SystemExit(f"Missing country boundary data: {COUNTRY_BOUNDARIES}")
    payload = json.loads(COUNTRY_BOUNDARIES.read_text(encoding="utf-8"))
    countries = []
    for item in payload.get("countries", []):
        country = dict(item)
        country["bbox"] = _geometry_bbox(country["geometry"])
        countries.append(country)
    return countries


COUNTRIES = load_country_boundaries()


def country_for_point(point: tuple[float, float] | None) -> dict[str, str] | None:
    if not point:
        return None
    lat, lon = point
    for country in COUNTRIES:
        min_lon, min_lat, max_lon, max_lat = country["bbox"]
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            continue
        if _point_in_geometry(lon, lat, country["geometry"]):
            return {"name": country["name"], "code": country["code"]}
    return None


def _country_tuple(point: dict[str, Any]) -> tuple[str, str] | None:
    if point.get("country") and point.get("countryCode"):
        return point["country"], point["countryCode"]
    return None


def annotate_country_sequence(points: list[dict[str, Any]]) -> None:
    """Attach country names/codes to a chronological point list.

    Coastlines and islands in the compact boundary set can leave some GPS points just
    outside a polygon. Those gaps are filled from the nearest known countries in time.
    Small one/two-point border jitters are then smoothed.
    """
    if not points:
        return

    labels: list[dict[str, str] | None] = [country_for_point((p["lat"], p["lon"])) for p in points]
    known = [i for i, label in enumerate(labels) if label]
    if not known:
        return

    first = known[0]
    for i in range(0, first):
        labels[i] = labels[first]

    for left, right in zip(known, known[1:]):
        if right <= left + 1:
            continue
        left_label = labels[left]
        right_label = labels[right]
        if left_label == right_label:
            for i in range(left + 1, right):
                labels[i] = left_label
        else:
            midpoint = (left + right) / 2.0
            for i in range(left + 1, right):
                labels[i] = left_label if i <= midpoint else right_label

    last = known[-1]
    for i in range(last + 1, len(labels)):
        labels[i] = labels[last]

    # Smooth brief A-B-A border jitter where B is only one or two samples long.
    for _ in range(2):
        i = 1
        while i < len(labels) - 1:
            run_start = i
            run_label = labels[i]
            while i + 1 < len(labels) and labels[i + 1] == run_label:
                i += 1
            run_end = i
            if (
                run_end - run_start + 1 <= 2
                and labels[run_start - 1]
                and run_end + 1 < len(labels)
                and labels[run_start - 1] == labels[run_end + 1]
                and run_label != labels[run_start - 1]
            ):
                for j in range(run_start, run_end + 1):
                    labels[j] = labels[run_start - 1]
            i += 1

    for point, label in zip(points, labels):
        if label:
            point["country"] = label["name"]
            point["countryCode"] = label["code"]


def country_timeline(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for point in points:
        country = _country_tuple(point)
        if not country:
            continue
        name, code = country
        if timeline and timeline[-1]["country"] == name:
            timeline[-1]["end"] = point["time"]
            timeline[-1]["endTime"] = point["time"][11:16]
            timeline[-1]["endLat"] = point["lat"]
            timeline[-1]["endLon"] = point["lon"]
        else:
            timeline.append(
                {
                    "country": name,
                    "code": code,
                    "start": point["time"],
                    "end": point["time"],
                    "startTime": point["time"][11:16],
                    "endTime": point["time"][11:16],
                    "lat": point["lat"],
                    "lon": point["lon"],
                    "endLat": point["lat"],
                    "endLon": point["lon"],
                }
            )
    return timeline


def unique_countries(timeline: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in timeline:
        if item["country"] in seen:
            continue
        seen.add(item["country"])
        result.append({"name": item["country"], "code": item["code"]})
    return result


def nearest_point_country(
    raw_points: list[dict[str, Any]],
    point: tuple[float, float] | None,
    time: str | None = None,
) -> dict[str, str] | None:
    candidates = [p for p in raw_points if p.get("country") and p.get("countryCode")]
    if not candidates:
        return None

    if point:
        best = min(candidates, key=lambda p: haversine_km(point, (p["lat"], p["lon"])))
        if haversine_km(point, (best["lat"], best["lon"])) <= 80:
            return {"name": best["country"], "code": best["countryCode"]}

    if time:
        try:
            target = parse_time(time)
            best = min(candidates, key=lambda p: abs((parse_time(p["time"]) - target).total_seconds()))
            return {"name": best["country"], "code": best["countryCode"]}
        except Exception:
            pass

    first = candidates[0]
    return {"name": first["country"], "code": first["countryCode"]}


def clean_path(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate points and obvious isolated GPS jumps without smoothing real roads."""
    if len(points) <= 2:
        return points[:]

    deduped: list[dict[str, Any]] = []
    seen = set()
    for point in points:
        key = (round(point["lat"], 7), round(point["lon"], 7), point["time"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(point)

    if len(deduped) <= 2:
        return deduped

    keep = [deduped[0]]
    for i in range(1, len(deduped) - 1):
        prev = keep[-1]
        cur = deduped[i]
        nxt = deduped[i + 1]
        p_prev = (prev["lat"], prev["lon"])
        p_cur = (cur["lat"], cur["lon"])
        p_next = (nxt["lat"], nxt["lon"])
        d_prev = haversine_km(p_prev, p_cur)
        d_next = haversine_km(p_cur, p_next)
        d_bridge = haversine_km(p_prev, p_next)

        try:
            minutes = max(0.01, (parse_time(cur["time"]) - parse_time(prev["time"])).total_seconds() / 60.0)
            speed = d_prev / (minutes / 60.0)
        except Exception:
            speed = 0.0

        # Remove an isolated spike that jumps far away and straight back.
        isolated_spike = d_prev > 25 and d_next > 25 and d_bridge < 8
        # Remove an implausible road-speed hop if it also bridges cleanly to the next point.
        implausible_hop = speed > 260 and d_prev > 20 and d_bridge < d_prev * 0.45
        if isolated_spike or implausible_hop:
            continue
        keep.append(cur)
    keep.append(deduped[-1])
    return keep


def split_on_large_gaps(points: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not points:
        return []
    result: list[list[dict[str, Any]]] = [[points[0]]]
    for cur in points[1:]:
        prev = result[-1][-1]
        dist = haversine_km((prev["lat"], prev["lon"]), (cur["lat"], cur["lon"]))
        try:
            mins = abs((parse_time(cur["time"]) - parse_time(prev["time"])).total_seconds()) / 60.0
        except Exception:
            mins = 0
        # Do not draw straight lines over large gaps in recording.
        if (dist > 80 and mins < 45) or mins > 240:
            result.append([cur])
        else:
            result[-1].append(cur)
    return [segment for segment in result if segment]


def point_payload(point: tuple[float, float], time: str) -> dict[str, Any]:
    return {"lat": round(point[0], 7), "lon": round(point[1], 7), "time": time}


def build() -> dict[str, Any]:
    with SOURCE.open("r", encoding="utf-8") as handle:
        source = json.load(handle)

    routes_by_date: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    raw_points_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    visits_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    activities_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for segment in source.get("semanticSegments", []):
        # Timeline path: use it for the actual traced route.
        if "timelinePath" in segment:
            previous_was_outside = False
            chunks: list[list[dict[str, Any]]] = []
            current_chunk: list[dict[str, Any]] = []

            for item in segment.get("timelinePath", []):
                point = parse_latlon(item.get("point"))
                time = item.get("time") or segment.get("startTime")
                if not point or not time:
                    continue
                date = time[:10]
                if in_europe(point):
                    payload = point_payload(point, time)
                    raw_points_by_date[date].append(payload)
                    if previous_was_outside and current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = []
                    current_chunk.append(payload)
                    previous_was_outside = False
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = []
                    previous_was_outside = True
            if current_chunk:
                chunks.append(current_chunk)

            # Split a Timeline path crossing midnight so each day remains self-contained.
            for chunk in chunks:
                by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for point in chunk:
                    by_day[point["time"][:10]].append(point)
                for date, day_points in by_day.items():
                    cleaned = clean_path(day_points)
                    for piece in split_on_large_gaps(cleaned):
                        if len(piece) >= 2:
                            routes_by_date[date].append(piece)

        # Visits/stops: only hierarchy level 0 to avoid duplicate nested place candidates.
        visit = segment.get("visit")
        if visit and visit.get("hierarchyLevel", 0) == 0:
            candidate = visit.get("topCandidate", {})
            point = parse_latlon(candidate.get("placeLocation", {}).get("latLng"))
            if in_europe(point):
                start = segment.get("startTime")
                end = segment.get("endTime")
                if start and end:
                    mins = duration_minutes(start, end)
                    if mins >= 8.0:
                        offset = segment.get("startTimeTimezoneUtcOffsetMinutes")
                        visits_by_date[start[:10]].append(
                            {
                                "lat": round(point[0], 7),
                                "lon": round(point[1], 7),
                                "start": start,
                                "end": end,
                                "startLocal": local_hhmm(start, offset),
                                "endLocal": local_hhmm(end, segment.get("endTimeTimezoneUtcOffsetMinutes")),
                                "durationMinutes": round(mins),
                                "placeId": candidate.get("placeId"),
                                "semanticType": candidate.get("semanticType"),
                                "probability": round(float(candidate.get("probability", 0.0)), 4),
                            }
                        )

        # Activity segments provide the movement-mode timeline and distance totals.
        activity = segment.get("activity")
        if activity:
            start_point = parse_latlon(activity.get("start", {}).get("latLng"))
            end_point = parse_latlon(activity.get("end", {}).get("latLng"))
            # Require both ends in Europe so Israel<->Europe flight lines never enter the site.
            if in_europe(start_point) and in_europe(end_point):
                start = segment.get("startTime")
                end = segment.get("endTime")
                if start and end:
                    mins = duration_minutes(start, end)
                    distance_m = float(activity.get("distanceMeters") or 0.0)
                    raw_type = activity.get("topCandidate", {}).get("type")
                    mode, label = normalize_activity(raw_type, distance_m, mins)
                    activities_by_date[start[:10]].append(
                        {
                            "start": start,
                            "end": end,
                            "startLocal": local_hhmm(start, segment.get("startTimeTimezoneUtcOffsetMinutes")),
                            "endLocal": local_hhmm(end, segment.get("endTimeTimezoneUtcOffsetMinutes")),
                            "startPoint": {"lat": round(start_point[0], 7), "lon": round(start_point[1], 7)},
                            "endPoint": {"lat": round(end_point[0], 7), "lon": round(end_point[1], 7)},
                            "distanceKm": round(distance_m / 1000.0, 2),
                            "durationMinutes": round(mins),
                            "mode": mode,
                            "label": label,
                            "sourceType": raw_type,
                        }
                    )

    all_dates = sorted(set(routes_by_date) | set(raw_points_by_date) | set(visits_by_date) | set(activities_by_date))

    # Resolve countries once across the complete chronological trip as well as per-day.
    # This lets compact coastline polygons correctly inherit the surrounding country on
    # island/coastal days where every sampled point happens to fall just outside land.
    all_raw_points: list[dict[str, Any]] = []
    for date in all_dates:
        all_raw_points.extend(sorted(raw_points_by_date.get(date, []), key=lambda p: p["time"]))
    annotate_country_sequence(all_raw_points)

    days: list[dict[str, Any]] = []

    for index, date in enumerate(all_dates, start=1):
        routes = routes_by_date.get(date, [])
        raw_points = sorted(raw_points_by_date.get(date, []), key=lambda p: p["time"])
        visits = sorted(visits_by_date.get(date, []), key=lambda v: v["start"])
        activities = sorted(activities_by_date.get(date, []), key=lambda a: a["start"])

        annotate_country_sequence(raw_points)
        country_by_point = {
            (p["time"], p["lat"], p["lon"]): (p.get("country"), p.get("countryCode"))
            for p in raw_points
            if p.get("country")
        }
        for route in routes:
            for point in route:
                label = country_by_point.get((point["time"], point["lat"], point["lon"]))
                if label:
                    point["country"], point["countryCode"] = label
                else:
                    exact = country_for_point((point["lat"], point["lon"]))
                    if exact:
                        point["country"], point["countryCode"] = exact["name"], exact["code"]

        day_country_timeline = country_timeline(raw_points)
        day_countries = unique_countries(day_country_timeline)

        for visit in visits:
            country = country_for_point((visit["lat"], visit["lon"])) or nearest_point_country(
                raw_points, (visit["lat"], visit["lon"]), visit["start"]
            )
            if country:
                visit["country"] = country["name"]
                visit["countryCode"] = country["code"]

        for activity in activities:
            start_tuple = (activity["startPoint"]["lat"], activity["startPoint"]["lon"])
            end_tuple = (activity["endPoint"]["lat"], activity["endPoint"]["lon"])
            start_country = country_for_point(start_tuple) or nearest_point_country(raw_points, start_tuple, activity["start"])
            end_country = country_for_point(end_tuple) or nearest_point_country(raw_points, end_tuple, activity["end"])
            if start_country:
                activity["startCountry"] = start_country["name"]
                activity["startCountryCode"] = start_country["code"]
            if end_country:
                activity["endCountry"] = end_country["name"]
                activity["endCountryCode"] = end_country["code"]

        route_km = 0.0
        route_points: list[dict[str, Any]] = []
        for route in routes:
            route_points.extend(route)
            for a, b in zip(route, route[1:]):
                route_km += haversine_km((a["lat"], a["lon"]), (b["lat"], b["lon"]))

        activity_km = sum(a["distanceKm"] for a in activities)
        mode_totals: dict[str, dict[str, Any]] = {}
        for activity in activities:
            key = activity["mode"]
            if key not in mode_totals:
                mode_totals[key] = {"mode": key, "label": activity["label"], "distanceKm": 0.0, "minutes": 0}
            mode_totals[key]["distanceKm"] += activity["distanceKm"]
            mode_totals[key]["minutes"] += activity["durationMinutes"]
        for mode in mode_totals.values():
            mode["distanceKm"] = round(mode["distanceKm"], 1)

        first_point = route_points[0] if route_points else (raw_points[0] if raw_points else None)
        last_point = route_points[-1] if route_points else (raw_points[-1] if raw_points else None)

        def endpoint_payload(point: dict[str, Any] | None) -> dict[str, Any] | None:
            if not point:
                return None
            payload = {"lat": point["lat"], "lon": point["lon"], "time": point["time"]}
            if point.get("country"):
                payload["country"] = point["country"]
                payload["countryCode"] = point.get("countryCode")
            return payload

        days.append(
            {
                "index": index,
                "date": date,
                "routes": routes,
                "rawPoints": raw_points,
                "visits": visits,
                "activities": activities,
                "countries": day_countries,
                "countryTimeline": day_country_timeline,
                "stats": {
                    "routeKm": round(route_km, 1),
                    "activityKm": round(activity_km, 1),
                    "rawPointCount": len(raw_points),
                    "stopCount": len(visits),
                    "countryCount": len(day_countries),
                    "modes": sorted(mode_totals.values(), key=lambda m: (-m["minutes"], m["label"])),
                },
                "start": endpoint_payload(first_point),
                "end": endpoint_payload(last_point),
            }
        )

    total_activity_km = round(sum(day["stats"]["activityKm"] for day in days), 1)
    total_route_km = round(sum(day["stats"]["routeKm"] for day in days), 1)
    total_stops = sum(day["stats"]["stopCount"] for day in days)
    total_points = sum(day["stats"]["rawPointCount"] for day in days)

    trip_countries: list[dict[str, str]] = []
    seen_trip_countries: set[str] = set()
    for day in days:
        for country in day["countries"]:
            if country["name"] not in seen_trip_countries:
                seen_trip_countries.add(country["name"])
                trip_countries.append(country)

    return {
        "meta": {
            "title": "Europe Trip 2017",
            "sourceTripStart": source.get("extractionInfo", {}).get("tripStart"),
            "sourceTripEnd": source.get("extractionInfo", {}).get("tripEnd"),
            "europeStart": days[0]["date"] if days else None,
            "europeEnd": days[-1]["date"] if days else None,
            "dayCount": len(days),
            "totalActivityKm": total_activity_km,
            "totalRouteKm": total_route_km,
            "totalStops": total_stops,
            "totalRawPoints": total_points,
            "countryCount": len(trip_countries),
            "countries": trip_countries,
            "semanticSegmentCount": source.get("extractionInfo", {}).get("semanticSegmentCount"),
            "europeBounds": EUROPE_BOUNDS,
            "cleaning": "Obvious isolated GPS spikes removed; raw Europe-only points retained for the Raw GPS toggle.",
            "countryMethod": "Offline country polygons with coastline/border gaps filled from adjacent recorded points.",
            "cyclingRule": "Google CYCLING guesses are shown as Walking when <=5 km and <=9 km/h, otherwise Riding. No bicycle mode is displayed.",
        },
        "days": days,
    }


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source file: {SOURCE}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {OUTPUT}")
    print(
        f"{data['meta']['dayCount']} Europe days, "
        f"{data['meta']['countryCount']} countries, "
        f"{data['meta']['totalRawPoints']} raw points, "
        f"{data['meta']['totalStops']} significant stops"
    )


if __name__ == "__main__":
    main()
