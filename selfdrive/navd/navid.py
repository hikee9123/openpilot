#!/usr/bin/env python3
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
try:
  from openpilot.selfdrive.navd.osm_roads import (
    DEFAULT_LOOKUP_RADIUS_M,
    DEFAULT_OSM_ROADS_DB_PATH,
    forward_road_segments,
    latlon_to_car_space_m,
    nearby_road_segments,
    road_name_matches,
  )
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import (
    DEFAULT_LOOKUP_RADIUS_M,
    DEFAULT_OSM_ROADS_DB_PATH,
    forward_road_segments,
    latlon_to_car_space_m,
    nearby_road_segments,
    road_name_matches,
  )
from openpilot.selfdrive.navd.speed_camera import (
  DEFAULT_CSV_PATH,
  DEFAULT_DB_PATH,
  DB_VERSION,
  camera_type_code,
  create_database_from_csv,
  find_lead_cameras,
  init_db,
  normalize_camera_category,
  normalize_road_class,
  road_class_code,
  update_camera_position,
)
from openpilot.selfdrive.ui.custom import read_custom_params


DB_RETRY_SECONDS = 60.0
LOOKUP_INTERVAL_SECONDS = 1.0
OSM_ROAD_LOOKUP_INTERVAL_SECONDS = 2.0
OSM_ROAD_OVERLAY_INTERVAL_SECONDS = 1.0
OSM_ROAD_OVERLAY_RADIUS_M = 140.0
OSM_CACHE_MIN_QUERY_RADIUS_M = OSM_ROAD_OVERLAY_RADIUS_M * 2.0
OSM_CACHE_MIN_REFRESH_INTERVAL_SECONDS = 1.0
OSM_CURRENT_ROAD_MAX_HEADING_DIFF_DEG = 60.0
OSM_FORWARD_ROAD_MAX_HEADING_DIFF_DEG = 50.0
OSM_FORWARD_ROAD_BACK_MARGIN_M = 20.0
OSM_FORWARD_ROAD_DEFAULT_SIDE_M = 45.0
OSM_FORWARD_ROAD_MAJOR_SIDE_M = 80.0
OSM_MINIMAP_CACHE_MAX_AGE_SECONDS = 120.0
OSM_MINIMAP_CACHE_MAX_SEGMENTS = 1000
OSM_MINIMAP_RENDER_MAX_SEGMENTS = 500
OSM_MINIMAP_CURRENT_ROAD_MAX_SEGMENTS = 150
OSM_MINIMAP_CURRENT_ROAD_RADIUS_FACTOR = 1.15
OSM_MINIMAP_MIN_RADIUS_M = 300.0
OSM_MINIMAP_REFRESH_MARGIN_FRACTION = 0.9
OSM_MINIMAP_FORWARD_EXTRA_M = 1000.0
OSM_MINIMAP_FORWARD_MAX_M = 6000.0
OSM_MINIMAP_FORWARD_START_M = -100.0
OSM_MINIMAP_CORRIDOR_SIDE_M = 70.0
OSM_MINIMAP_CORRIDOR_MAJOR_SIDE_M = 140.0
OSM_MINIMAP_HEADING_REFRESH_DEG = 25.0
OSM_OVERLAY_MODE_MINIMAP = 1
KPH_TO_MPS = 1000.0 / 3600.0
MAX_CAMERA_CANDIDATES = 3


@dataclass
class OsmRoadCache:
  center_lat: float = 0.0
  center_lon: float = 0.0
  heading_deg: float = 0.0
  query_radius_m: float = 0.0
  forward_start_m: float = 0.0
  forward_end_m: float = 0.0
  side_limit_m: float = 0.0
  major_side_limit_m: float = 0.0
  refresh_distance_m: float = 0.0
  loaded_at: float = 0.0
  db_mtime: float = 0.0
  cache_kind: str = ""
  segments: list = field(default_factory=list)


def _clip(value: float, min_value: float, max_value: float) -> float:
  return max(min_value, min(max_value, value))


def _speed_camera_tuning() -> dict[str, float | bool]:
  try:
    values = read_custom_params()
  except Exception:
    cloudlog.exception("navid: failed to read speed camera tuning params")
    values = {}

  return {
    "lookahead_distance_m": _clip(float(values.get("SpeedCameraLookaheadDistance", 1000)), 500.0, 3000.0),
    "lookahead_angle_deg": _clip(float(values.get("SpeedCameraLookaheadAngle", 35)), 15.0, 60.0),
    "camera_direction_angle_deg": _clip(float(values.get("SpeedCameraDirectionAngle", 60)), 30.0, 90.0),
    "passing_distance_m": _clip(float(values.get("SpeedCameraPassingDistance", 30)), 10.0, 80.0),
    "passed_ignore_seconds": _clip(float(values.get("SpeedCameraPassedIgnoreSeconds", 8)), 3.0, 30.0),
    "min_gps_speed_mps": _clip(float(values.get("SpeedCameraMinGpsSpeed", 3)), 0.0, 10.0) * KPH_TO_MPS,
    "use_local_osm_roads": bool(values.get("UseLocalOsmRoads", False)),
    "osm_road_overlay_mode": 1 if int(values.get("OsmRoadOverlayMode", 0) or 0) > 0 else 0,
    "local_osm_road_radius_m": _clip(float(values.get("LocalOsmRoadRadius", DEFAULT_LOOKUP_RADIUS_M)), 20.0, 100.0),
  }


def _db_path() -> Path:
  return Path(os.getenv("SPEED_CAMERA_DB", str(DEFAULT_DB_PATH)))


def _csv_path() -> Path:
  return Path(os.getenv("SPEED_CAMERA_CSV", str(DEFAULT_CSV_PATH)))


def _osm_roads_db_path() -> Path:
  return Path(os.getenv("OSM_ROADS_DB", str(DEFAULT_OSM_ROADS_DB_PATH)))


def _ensure_database(db_path: Path, csv_path: Path) -> bool:
  if db_path.exists():
    try:
      with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key = ?", ("version",)).fetchone()
        version = int(row[0]) if row and row[0] else 0
        if version < DB_VERSION:
          init_db(conn)
          cloudlog.warning(f"navid: migrated speed camera DB from version {version} to {DB_VERSION}")
      return True
    except (sqlite3.Error, TypeError, ValueError):
      cloudlog.exception("navid: failed to migrate speed camera DB")
      return False

  if not csv_path.exists():
    cloudlog.warning(f"navid: speed camera DB missing ({db_path}); put CSV at {csv_path} or set SPEED_CAMERA_CSV")
    return False

  try:
    count = create_database_from_csv(csv_path, db_path)
    cloudlog.warning(f"navid: imported {count} speed cameras from {csv_path}")
    return count > 0
  except Exception:
    cloudlog.exception("navid: failed to import speed camera CSV")
    return False


def _send_inactive(pm: messaging.PubMaster, osm_road_overlay_text: str = "") -> None:
  msg = messaging.new_message("naviCustom")
  nav = msg.naviCustom.naviData
  nav.active = 0
  nav.camCategory = ""
  nav.camCategoryCode = 0
  nav.roadClass = ""
  nav.roadClassCode = 0
  nav.camBearingDeg = 0.0
  nav.camRelativeAngleDeg = 0.0
  nav.camCandidatesText = ""
  nav.osmRoadOverlayText = osm_road_overlay_text
  nav.camDebugText = ""
  pm.send("naviCustom", msg)


def _candidate_category_label(camera) -> str:
  category = str(getattr(camera, "camera_category", ""))
  type_code = int(getattr(camera, "camera_type_code", 0))
  if category == "SECTION_SPEED" or type_code == 4:
    return "AVG"
  if category in ("SPEED", "SPEED_SIGNAL") or type_code in (1, 3):
    return "SPD"
  if category == "SIGNAL" or type_code == 2:
    return "SIG"
  if category == "PROTECTED_ZONE" or type_code == 10:
    return "ZON"
  if category == "SECURITY" or type_code == 8:
    return "SEC"
  return "CAM"


def _format_candidate_distance(distance_m: float) -> str:
  if distance_m >= 1000.0:
    return f"{distance_m / 1000.0:.1f}k"
  return f"{int(distance_m)}m"


def _candidate_corridor_marker(camera) -> str:
  angle = abs(float(getattr(camera, "relative_angle_deg", 0.0)))
  if angle <= 15.0:
    return " R"
  if bool(getattr(camera, "is_expressway", False)) and angle <= 25.0:
    return " R"
  return ""


def _format_candidate_projection(camera) -> str:
  forward_m = float(getattr(camera, "forward_m", 0.0))
  side_m = float(getattr(camera, "side_m", 0.0))
  return f" f{int(forward_m)} s{int(side_m):+d}"


def _candidate_local_road_marker(camera) -> str:
  return " O" if bool(getattr(camera, "local_road_match", False)) else ""


def _candidate_forward_road_marker(camera) -> str:
  return " F" if bool(getattr(camera, "forward_road_match", False)) else ""


def _format_candidate_text(candidates) -> str:
  lines = []
  for idx, camera in enumerate(candidates[:MAX_CAMERA_CANDIDATES], start=1):
    lines.append(
      f"{idx} {_candidate_category_label(camera)} "
      f"{_format_candidate_distance(float(getattr(camera, 'distance_m', 0.0)))} "
      f"{float(getattr(camera, 'relative_angle_deg', 0.0)):+.0f}"
      f"{_format_candidate_projection(camera)}"
      f"{_candidate_forward_road_marker(camera)}"
      f"{_candidate_local_road_marker(camera)}"
      f"{_candidate_corridor_marker(camera)}"
    )
  return "\n".join(lines)


def _format_debug_road_name(road_name: str, max_len: int = 22) -> str:
  road_name = (road_name or "").strip()
  if not road_name:
    return ""
  if len(road_name) > max_len:
    road_name = f"{road_name[:max_len - 3]}..."
  return f"ROAD {road_name}"


def _format_camera_debug_text(candidates, current_road_name: str = "") -> str:
  lines = []
  road_line = _format_debug_road_name(current_road_name)
  if road_line:
    lines.append(road_line)
  candidate_text = _format_candidate_text(candidates)
  if candidate_text:
    lines.extend(candidate_text.splitlines())
  return "\n".join(lines)


def _format_camera_classification_debug_text(camera, category: str, type_code: int, road_class: str, current_road_name: str = "") -> str:
  def short_raw(value, max_len: int = 32) -> str:
    text = str(value or "-").strip() or "-"
    return text if len(text) <= max_len else f"{text[:max_len - 3]}..."

  raw_type = short_raw(getattr(camera, "camera_type", ""), 30)
  section_type = short_raw(getattr(camera, "section_type", ""), 18)
  section_length_m = int(getattr(camera, "section_length_m", 0) or 0)
  speed_limit = int(getattr(camera, "speed_limit", 0) or 0)
  distance_m = int(max(0.0, float(getattr(camera, "distance_m", 0.0))))
  angle_deg = float(getattr(camera, "relative_angle_deg", 0.0))
  bearing_deg = float(getattr(camera, "bearing_deg", 0.0))
  forward_m = int(float(getattr(camera, "forward_m", 0.0)))
  side_m = int(float(getattr(camera, "side_m", 0.0)))
  road_type = short_raw(getattr(camera, "road_type_raw", ""), 16)
  road_name = short_raw(getattr(camera, "road_name", ""), 26)
  place = short_raw(getattr(camera, "place", ""), 42)
  raw_direction = short_raw(getattr(camera, "direction", ""), 8)
  direction_kind = short_raw(getattr(camera, "direction_kind", ""), 6)
  current_road = short_raw(current_road_name, 22)
  camera_id = short_raw(getattr(camera, "id", ""), 20)
  flags = []
  if speed_limit <= 0:
    flags.append("ZERO")
  if raw_type == "99":
    flags.append("99")
  if not category or category == "UNKNOWN":
    flags.append("UNK")
  flags_text = ",".join(flags) if flags else "-"
  osm_text = "Y" if bool(getattr(camera, "local_road_match", False)) else "N"
  corridor_text = "Y" if _candidate_corridor_marker(camera) else "N"

  return "\n".join((
    f"CAM {category or 'UNKNOWN'} c={type_code} v={speed_limit} id={camera_id}",
    f"POS {distance_m}m f={forward_m} s={side_m:+d} a={angle_deg:+.0f} bear={bearing_deg:.0f}",
    f"RAW type={raw_type} dir={raw_direction}/{direction_kind} sect={section_type} len={section_length_m}",
    f"ROAD {road_class or road_type or 'UNKNOWN'} | {road_name}",
    f"PLACE {place}",
    f"WHY osm={osm_text} cur={current_road} corr={corridor_text} flags={flags_text}",
  ))


def _osm_db_mtime(db_path: Path) -> float:
  try:
    return db_path.stat().st_mtime
  except OSError:
    return 0.0


def _heading_delta_deg(a: float, b: float) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def _minimap_speed_scale(speed_mps: float) -> float:
  speed_kph = speed_mps / KPH_TO_MPS
  if speed_kph < 30.0:
    return 0.5
  if speed_kph < 80.0:
    return 0.75
  return 1.0


def _minimap_display_radius_m(gps, tuning: dict[str, float | bool]) -> float:
  lookahead = float(tuning["lookahead_distance_m"])
  return _clip(lookahead * _minimap_speed_scale(float(gps.speed)), OSM_MINIMAP_MIN_RADIUS_M, lookahead)


def _minimap_forward_end_m(display_radius_m: float) -> float:
  return min(display_radius_m + OSM_MINIMAP_FORWARD_EXTRA_M, OSM_MINIMAP_FORWARD_MAX_M)


def _minimap_refresh_distance_m(display_radius_m: float, query_radius_m: float) -> float:
  return max(1.0, (query_radius_m - display_radius_m) * OSM_MINIMAP_REFRESH_MARGIN_FRACTION)


def _osm_cache_needs_refresh(
  cache: OsmRoadCache,
  db_path: Path,
  gps,
  query_radius_m: float,
  now: float,
) -> bool:
  if cache.loaded_at <= 0.0:
    return True
  if now - cache.loaded_at < OSM_CACHE_MIN_REFRESH_INTERVAL_SECONDS:
    return False
  if _osm_db_mtime(db_path) != cache.db_mtime:
    return True
  if cache.cache_kind != "radius":
    return True
  if cache.query_radius_m + 1.0 < query_radius_m:
    return True
  moved_m = math.hypot(
    (gps.latitude - cache.center_lat) * 111320.0,
    (gps.longitude - cache.center_lon) * 111320.0 * max(0.1, math.cos(math.radians(gps.latitude))),
  )
  if moved_m >= cache.refresh_distance_m:
    return True
  return now - cache.loaded_at > OSM_MINIMAP_CACHE_MAX_AGE_SECONDS


def _ensure_osm_cache(
  cache: OsmRoadCache,
  db_path: Path,
  gps,
  display_radius_m: float,
  query_radius_m: float,
  now: float,
) -> None:
  query_radius_m = max(query_radius_m, OSM_CACHE_MIN_QUERY_RADIUS_M)
  if not _osm_cache_needs_refresh(cache, db_path, gps, query_radius_m, now):
    return

  cache.center_lat = gps.latitude
  cache.center_lon = gps.longitude
  cache.query_radius_m = query_radius_m
  cache.refresh_distance_m = _minimap_refresh_distance_m(display_radius_m, query_radius_m)
  cache.loaded_at = now
  cache.db_mtime = _osm_db_mtime(db_path)
  cache.cache_kind = "radius"
  cache.segments = nearby_road_segments(
    db_path,
    gps.latitude,
    gps.longitude,
    query_radius_m,
    OSM_MINIMAP_CACHE_MAX_SEGMENTS,
  )


def _osm_corridor_cache_needs_refresh(
  cache: OsmRoadCache,
  db_path: Path,
  gps,
  forward_start_m: float,
  forward_end_m: float,
  side_limit_m: float,
  major_side_limit_m: float,
  refresh_distance_m: float,
  now: float,
) -> bool:
  if cache.loaded_at <= 0.0:
    return True
  if now - cache.loaded_at < OSM_CACHE_MIN_REFRESH_INTERVAL_SECONDS:
    return False
  if _osm_db_mtime(db_path) != cache.db_mtime:
    return True
  if cache.cache_kind != "corridor":
    return True
  if cache.forward_start_m > forward_start_m + 1.0 or cache.forward_end_m + 1.0 < forward_end_m:
    return True
  if cache.side_limit_m + 1.0 < side_limit_m or cache.major_side_limit_m + 1.0 < major_side_limit_m:
    return True
  if _heading_delta_deg(cache.heading_deg, float(gps.bearingDeg)) >= OSM_MINIMAP_HEADING_REFRESH_DEG:
    return True
  moved_m = math.hypot(
    (gps.latitude - cache.center_lat) * 111320.0,
    (gps.longitude - cache.center_lon) * 111320.0 * max(0.1, math.cos(math.radians(gps.latitude))),
  )
  if moved_m >= refresh_distance_m:
    return True
  return now - cache.loaded_at > OSM_MINIMAP_CACHE_MAX_AGE_SECONDS


def _ensure_osm_corridor_cache(
  cache: OsmRoadCache,
  db_path: Path,
  gps,
  display_radius_m: float,
  now: float,
) -> None:
  forward_start_m = OSM_MINIMAP_FORWARD_START_M
  forward_end_m = _minimap_forward_end_m(display_radius_m)
  refresh_distance_m = _minimap_refresh_distance_m(display_radius_m, forward_end_m)
  if not _osm_corridor_cache_needs_refresh(
    cache,
    db_path,
    gps,
    forward_start_m,
    forward_end_m,
    OSM_MINIMAP_CORRIDOR_SIDE_M,
    OSM_MINIMAP_CORRIDOR_MAJOR_SIDE_M,
    refresh_distance_m,
    now,
  ):
    return

  cache.center_lat = gps.latitude
  cache.center_lon = gps.longitude
  cache.heading_deg = float(gps.bearingDeg)
  cache.query_radius_m = forward_end_m
  cache.forward_start_m = forward_start_m
  cache.forward_end_m = forward_end_m
  cache.side_limit_m = OSM_MINIMAP_CORRIDOR_SIDE_M
  cache.major_side_limit_m = OSM_MINIMAP_CORRIDOR_MAJOR_SIDE_M
  cache.refresh_distance_m = refresh_distance_m
  cache.loaded_at = now
  cache.db_mtime = _osm_db_mtime(db_path)
  cache.cache_kind = "corridor"
  cache.segments = forward_road_segments(
    db_path,
    gps.latitude,
    gps.longitude,
    gps.bearingDeg,
    forward_start_m,
    forward_end_m,
    OSM_MINIMAP_CORRIDOR_SIDE_M,
    OSM_MINIMAP_CORRIDOR_MAJOR_SIDE_M,
    OSM_MINIMAP_CACHE_MAX_SEGMENTS,
  )


def _road_payload(segment, gps, current_road_name: str, include_distance: bool = False) -> dict:
  x1, y1 = latlon_to_car_space_m(gps.latitude, gps.longitude, gps.bearingDeg, segment.lat1, segment.lon1)
  x2, y2 = latlon_to_car_space_m(gps.latitude, gps.longitude, gps.bearingDeg, segment.lat2, segment.lon2)
  forward_info = _forward_road_info(segment, gps, x1, y1, x2, y2, current_road_name)
  payload = {
    "x1": round(x1, 1),
    "y1": round(y1, 1),
    "x2": round(x2, 1),
    "y2": round(y2, 1),
    "n": segment.display_name[:28],
    "h": segment.highway,
    "c": road_name_matches(current_road_name, segment.name, segment.ref),
  }
  if forward_info["f"]:
    payload.update(forward_info)
  if include_distance:
    payload["d"] = round(_point_to_segment_distance_m(x1, y1, x2, y2), 1)
  return payload


def _angle_diff_deg(a: float, b: float) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def _bidirectional_heading_diff_deg(segment_bearing_deg: float, heading_deg: float) -> float:
  return min(_angle_diff_deg(segment_bearing_deg, heading_deg), _angle_diff_deg((segment_bearing_deg + 180.0) % 360.0, heading_deg))


def _point_to_segment_distance_m(x1: float, y1: float, x2: float, y2: float) -> float:
  closest_x, closest_y = _closest_point_on_segment_m(x1, y1, x2, y2)
  return math.hypot(closest_x, closest_y)


def _closest_point_on_segment_m(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
  dx = x2 - x1
  dy = y2 - y1
  length_sq = dx * dx + dy * dy
  if length_sq <= 0.0:
    return x1, y1
  t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length_sq))
  return x1 + t * dx, y1 + t * dy


def _forward_side_limit_m(highway: str) -> float:
  if highway in ("motorway", "trunk", "primary", "secondary"):
    return OSM_FORWARD_ROAD_MAJOR_SIDE_M
  return OSM_FORWARD_ROAD_DEFAULT_SIDE_M


def _segment_forward_m(x1: float, x2: float, closest_x: float) -> float:
  forward_points = [x for x in (x1, x2, closest_x) if x >= -OSM_FORWARD_ROAD_BACK_MARGIN_M]
  return min(forward_points) if forward_points else max(x1, x2, closest_x)


def _forward_road_info(segment, gps, x1: float, y1: float, x2: float, y2: float, current_road_name: str) -> dict:
  closest_x, closest_y = _closest_point_on_segment_m(x1, y1, x2, y2)
  forward_m = _segment_forward_m(x1, x2, closest_x)
  side_m = min((y1, y2, closest_y), key=abs)
  heading_diff = _bidirectional_heading_diff_deg(float(segment.bearing_deg), float(gps.bearingDeg))
  same_name = road_name_matches(current_road_name, segment.name, segment.ref)
  side_limit_m = _forward_side_limit_m(str(segment.highway or ""))
  is_forward = (
    max(x1, x2, closest_x) >= -OSM_FORWARD_ROAD_BACK_MARGIN_M and
    abs(side_m) <= side_limit_m and
    heading_diff <= OSM_FORWARD_ROAD_MAX_HEADING_DIFF_DEG and
    (same_name or forward_m > OSM_FORWARD_ROAD_BACK_MARGIN_M)
  )
  return {
    "f": is_forward,
    "fm": round(forward_m, 1),
    "sm": round(side_m, 1),
    "a": round(heading_diff, 1),
  }


def _current_road_name_from_cache(cache: OsmRoadCache, gps, radius_m: float, previous_name: str = "") -> str:
  best_name = ""
  best_score: float | None = None
  for segment in cache.segments:
    x1, y1 = latlon_to_car_space_m(gps.latitude, gps.longitude, gps.bearingDeg, segment.lat1, segment.lon1)
    x2, y2 = latlon_to_car_space_m(gps.latitude, gps.longitude, gps.bearingDeg, segment.lat2, segment.lon2)
    distance_m = _point_to_segment_distance_m(x1, y1, x2, y2)
    if distance_m > radius_m:
      continue

    heading_diff = _bidirectional_heading_diff_deg(float(segment.bearing_deg), float(gps.bearingDeg))
    if heading_diff > OSM_CURRENT_ROAD_MAX_HEADING_DIFF_DEG:
      continue

    name_bonus = -8.0 if road_name_matches(previous_name, segment.name, segment.ref) else 0.0
    highway_bonus = -4.0 if segment.highway in ("motorway", "trunk", "primary") else 0.0
    score = distance_m + heading_diff * 0.8 + name_bonus + highway_bonus
    if best_score is None or score < best_score:
      best_score = score
      best_name = segment.display_name
  return best_name


def _minimap_road_priority(road: dict) -> tuple[int, float]:
  highway = str(road.get("h", ""))
  if road.get("c"):
    return 0, float(road.get("d", 0.0))
  if road.get("f"):
    return 1, float(road.get("fm", 0.0)) + abs(float(road.get("sm", 0.0))) * 0.8
  if highway in ("motorway", "trunk", "primary", "secondary"):
    return 2, float(road.get("d", 0.0))
  if highway in ("tertiary", "residential"):
    return 3, float(road.get("d", 0.0))
  return 4, float(road.get("d", 0.0))


def _minimap_roads(cache: OsmRoadCache, gps, current_road_name: str, display_radius_m: float) -> list[dict]:
  current_roads = []
  other_roads = []
  for segment in cache.segments:
    road = _road_payload(segment, gps, current_road_name, include_distance=True)
    is_current = bool(road.get("c"))
    radius_limit_m = display_radius_m * OSM_MINIMAP_CURRENT_ROAD_RADIUS_FACTOR if is_current else display_radius_m
    if float(road["d"]) > radius_limit_m:
      continue
    if is_current:
      current_roads.append(road)
    else:
      other_roads.append(road)

  current_roads = sorted(current_roads, key=lambda road: float(road.get("d", 0.0)))[:OSM_MINIMAP_CURRENT_ROAD_MAX_SEGMENTS]
  remaining_segments = max(0, OSM_MINIMAP_RENDER_MAX_SEGMENTS - len(current_roads))
  other_roads = sorted(other_roads, key=_minimap_road_priority)[:remaining_segments]
  return current_roads + other_roads


def _osm_overlay_cameras(gps, candidates=()) -> list[dict]:
  cameras = []
  for camera in candidates[:MAX_CAMERA_CANDIDATES]:
    x, y = latlon_to_car_space_m(gps.latitude, gps.longitude, gps.bearingDeg, camera.lat, camera.lon)
    if -20.0 <= x <= float(max(OSM_ROAD_OVERLAY_RADIUS_M, getattr(camera, "distance_m", 0.0) + 20.0)):
      cameras.append({
        "x": round(x, 1),
        "y": round(y, 1),
        "d": int(max(0.0, float(getattr(camera, "distance_m", 0.0)))),
        "s": int(getattr(camera, "speed_limit", 0) or 0),
      })
  return cameras


def _build_osm_road_overlay_text(
  db_path: Path,
  gps,
  candidates=(),
  current_road_name: str = "",
  mode: int = 0,
  tuning: dict[str, float | bool] | None = None,
  osm_cache: OsmRoadCache | None = None,
  now: float | None = None,
) -> str:
  try:
    map_roads = []
    map_radius_m = 0.0

    if mode != OSM_OVERLAY_MODE_MINIMAP:
      return ""

    if osm_cache is not None and tuning is not None:
      now = time.monotonic() if now is None else now
      map_radius_m = _minimap_display_radius_m(gps, tuning)
      display_radius_m = map_radius_m

      _ensure_osm_corridor_cache(osm_cache, db_path, gps, display_radius_m, now)
      map_roads = _minimap_roads(osm_cache, gps, current_road_name, map_radius_m)

    cameras = _osm_overlay_cameras(gps, candidates)
    if not map_roads and not cameras:
      return ""
    payload = {
      "road": (current_road_name or "")[:32],
      "cameras": cameras,
      "mapRoads": map_roads,
      "mapRadius": int(map_radius_m),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
  except Exception:
    cloudlog.exception("navid: failed to build OSM road overlay")
    return ""


def _send_camera(pm: messaging.PubMaster, camera, candidates=(), current_road_name: str = "", osm_road_overlay_text: str = "") -> None:
  msg = messaging.new_message("naviCustom")
  nav = msg.naviCustom.naviData

  nav.active = 1
  nav.roadLimitSpeed = camera.speed_limit

  category = getattr(camera, "camera_category", "")
  type_code = int(getattr(camera, "camera_type_code", 0))
  if not category or category == "UNKNOWN":
    category = normalize_camera_category(
      camera.camera_type, camera.section_type, f"{camera.road_name} {camera.place}", camera.speed_limit
    )
  if type_code == 0:
    type_code = camera_type_code(
      camera.camera_type, camera.section_type, f"{camera.road_name} {camera.place}", camera.speed_limit
    )

  road_class = getattr(camera, "road_class", "")
  road_class_code_value = int(getattr(camera, "road_class_code", 0))
  if not road_class or road_class == "UNKNOWN":
    road_class = normalize_road_class("", camera.road_name, camera.place)
  if road_class_code_value == 0:
    road_class_code_value = road_class_code(road_class)

  nav.camType = type_code
  nav.camCategory = category
  nav.camCategoryCode = type_code
  nav.roadClass = road_class
  nav.roadClassCode = road_class_code_value
  nav.camBearingDeg = float(getattr(camera, "bearing_deg", 0.0))
  nav.camRelativeAngleDeg = float(getattr(camera, "relative_angle_deg", 0.0))
  nav.camCandidatesText = _format_camera_debug_text(candidates, current_road_name)
  nav.osmRoadOverlayText = osm_road_overlay_text
  nav.camDebugText = _format_camera_classification_debug_text(camera, category, type_code, road_class, current_road_name)
  nav.camLimitSpeed = camera.speed_limit
  nav.camLimitSpeedLeftDist = max(0, int(camera.distance_m))
  nav.sectionLimitSpeed = camera.speed_limit if type_code == 4 else 0
  nav.sectionLeftDist = max(0, int(camera.distance_m + camera.section_length_m)) if type_code == 4 else 0
  nav.sectionAvgSpeed = 0
  nav.sectionLeftTime = 0
  nav.sectionAdjustSpeed = False
  nav.camSpeedFactor = 1.0
  nav.currentRoadName = current_road_name or camera.road_name or camera.place
  nav.isHighway = bool(getattr(camera, "is_expressway", False)) or "고속" in camera.road_name or "고속" in camera.place
  nav.isNda2 = False

  pm.send("naviCustom", msg)


def _select_gps(sm: messaging.SubMaster):
  if sm.valid["gpsLocationExternal"] and sm["gpsLocationExternal"].hasFix:
    return sm["gpsLocationExternal"]
  if sm.valid["gpsLocation"] and sm["gpsLocation"].hasFix:
    return sm["gpsLocation"]
  return None


def main() -> None:
  pm = messaging.PubMaster(["naviCustom"])
  sm = messaging.SubMaster(["gpsLocationExternal", "gpsLocation"])
  rk = Ratekeeper(20.0, print_delay_threshold=None)

  db_path = _db_path()
  csv_path = _csv_path()
  db_ready = _ensure_database(db_path, csv_path)
  next_db_retry_t = time.monotonic() + DB_RETRY_SECONDS

  ignored_until: dict[str, float] = {}
  active_camera_id: str | None = None
  active_camera = None
  active_candidates = []
  tuning = _speed_camera_tuning()
  last_lookup_t = 0.0
  last_osm_lookup_t = 0.0
  last_osm_overlay_t = 0.0
  current_road_name = ""
  osm_road_overlay_text = ""
  local_osm_cache = OsmRoadCache()
  osm_corridor_cache = OsmRoadCache()

  while True:
    sm.update(0)

    now = time.monotonic()
    if not db_ready:
      if now >= next_db_retry_t:
        db_ready = _ensure_database(db_path, csv_path)
        next_db_retry_t = now + DB_RETRY_SECONDS
      _send_inactive(pm)
      rk.keep_time()
      continue

    gps = _select_gps(sm)
    if gps is None:
      active_camera_id = None
      active_camera = None
      active_candidates = []
      current_road_name = ""
      osm_road_overlay_text = ""
      _send_inactive(pm)
      rk.keep_time()
      continue

    if gps.speed < tuning["min_gps_speed_mps"]:
      active_camera_id = None
      active_camera = None
      active_candidates = []
      if now - last_lookup_t >= LOOKUP_INTERVAL_SECONDS:
        last_lookup_t = now
        tuning = _speed_camera_tuning()
        if int(tuning["osm_road_overlay_mode"]) > 0:
          if now - last_osm_overlay_t >= OSM_ROAD_OVERLAY_INTERVAL_SECONDS:
            last_osm_overlay_t = now
            osm_road_overlay_text = _build_osm_road_overlay_text(
              _osm_roads_db_path(),
              gps,
              [],
              current_road_name,
              int(tuning["osm_road_overlay_mode"]),
              tuning,
              osm_corridor_cache,
              now,
            )
        else:
          osm_road_overlay_text = ""
      _send_inactive(pm, osm_road_overlay_text)
      rk.keep_time()
      continue

    if now - last_lookup_t >= LOOKUP_INTERVAL_SECONDS:
      last_lookup_t = now
      tuning = _speed_camera_tuning()
      ignored_ids = {camera_id for camera_id, until in ignored_until.items() if until > now}
      ignored_until = {camera_id: until for camera_id, until in ignored_until.items() if until > now}

      if bool(tuning["use_local_osm_roads"]) and now - last_osm_lookup_t >= OSM_ROAD_LOOKUP_INTERVAL_SECONDS:
        last_osm_lookup_t = now
        local_radius_m = float(tuning["local_osm_road_radius_m"])
        _ensure_osm_cache(
          local_osm_cache,
          _osm_roads_db_path(),
          gps,
          local_radius_m,
          max(OSM_CACHE_MIN_QUERY_RADIUS_M, local_radius_m * 2.0),
          now,
        )
        current_road_name = _current_road_name_from_cache(local_osm_cache, gps, local_radius_m, current_road_name)
      elif not bool(tuning["use_local_osm_roads"]):
        current_road_name = ""

      osm_context_segments = []
      if bool(tuning["use_local_osm_roads"]) or int(tuning["osm_road_overlay_mode"]) > 0:
        map_radius_m = _minimap_display_radius_m(gps, tuning)
        _ensure_osm_corridor_cache(osm_corridor_cache, _osm_roads_db_path(), gps, map_radius_m, now)
        osm_context_segments = osm_corridor_cache.segments

      active_candidates = find_lead_cameras(
        db_path,
        gps.latitude,
        gps.longitude,
        gps.bearingDeg,
        tuning["lookahead_distance_m"],
        tuning["lookahead_angle_deg"],
        tuning["camera_direction_angle_deg"],
        ignored_ids,
        limit=MAX_CAMERA_CANDIDATES,
        current_road_name=current_road_name,
        osm_road_segments=osm_context_segments,
      )
      active_camera = active_candidates[0] if active_candidates else None

      if int(tuning["osm_road_overlay_mode"]) > 0:
        if now - last_osm_overlay_t >= OSM_ROAD_OVERLAY_INTERVAL_SECONDS:
          last_osm_overlay_t = now
          osm_road_overlay_text = _build_osm_road_overlay_text(
            _osm_roads_db_path(),
            gps,
            active_candidates,
            current_road_name,
            int(tuning["osm_road_overlay_mode"]),
            tuning,
            osm_corridor_cache,
            now,
          )
      else:
        osm_road_overlay_text = ""

    if active_camera is None:
      active_camera_id = None
      _send_inactive(pm, osm_road_overlay_text)
      rk.keep_time()
      continue

    active_candidates = [update_camera_position(camera, gps.latitude, gps.longitude, gps.bearingDeg) for camera in active_candidates]
    active_camera = active_candidates[0]
    if active_camera.distance_m <= tuning["passing_distance_m"]:
      ignored_until[active_camera.id] = now + tuning["passed_ignore_seconds"]
      active_camera = None
      active_camera_id = None
      active_candidates = []
      _send_inactive(pm, osm_road_overlay_text)
      rk.keep_time()
      continue

    if active_camera_id != active_camera.id:
      active_camera_id = active_camera.id
      cloudlog.warning(
        f"navid: lead speed camera {active_camera.id} {int(active_camera.distance_m)}m "
        f"{active_camera.camera_type} limit={active_camera.speed_limit}"
      )

    _send_camera(pm, active_camera, active_candidates, current_road_name, osm_road_overlay_text)
    rk.keep_time()


if __name__ == "__main__":
  main()
