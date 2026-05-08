#!/usr/bin/env python3
import json
import os
import sqlite3
import time
from pathlib import Path

import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
try:
  from openpilot.selfdrive.navd.osm_roads import (
    DEFAULT_LOOKUP_RADIUS_M,
    DEFAULT_OSM_ROADS_DB_PATH,
    find_current_road,
    latlon_to_car_space_m,
    nearby_road_segments,
    road_name_matches,
  )
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import (
    DEFAULT_LOOKUP_RADIUS_M,
    DEFAULT_OSM_ROADS_DB_PATH,
    find_current_road,
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
OSM_ROAD_OVERLAY_MAX_SEGMENTS = 90
KPH_TO_MPS = 1000.0 / 3600.0
MAX_CAMERA_CANDIDATES = 3


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
    "osm_road_overlay_mode": int(_clip(float(values.get("OsmRoadOverlayMode", 0)), 0.0, 3.0)),
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


def _candidate_local_road_marker(camera) -> str:
  return " O" if bool(getattr(camera, "local_road_match", False)) else ""


def _format_candidate_text(candidates) -> str:
  lines = []
  for idx, camera in enumerate(candidates[:MAX_CAMERA_CANDIDATES], start=1):
    lines.append(
      f"{idx} {_candidate_category_label(camera)} "
      f"{_format_candidate_distance(float(getattr(camera, 'distance_m', 0.0)))} "
      f"{float(getattr(camera, 'relative_angle_deg', 0.0)):+.0f}"
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


def _format_camera_classification_debug_text(camera, category: str, type_code: int, road_class: str) -> str:
  def short_raw(value, max_len: int = 32) -> str:
    text = str(value or "-").strip() or "-"
    return text if len(text) <= max_len else f"{text[:max_len - 3]}..."

  raw_type = short_raw(getattr(camera, "camera_type", ""), 30)
  section_type = short_raw(getattr(camera, "section_type", ""), 18)
  section_length_m = int(getattr(camera, "section_length_m", 0) or 0)
  speed_limit = int(getattr(camera, "speed_limit", 0) or 0)
  distance_m = int(max(0.0, float(getattr(camera, "distance_m", 0.0))))
  angle_deg = float(getattr(camera, "relative_angle_deg", 0.0))
  road_type = short_raw(getattr(camera, "road_type_raw", ""), 16)
  road_name = short_raw(getattr(camera, "road_name", ""), 26)
  place = short_raw(getattr(camera, "place", ""), 34)
  camera_id = short_raw(getattr(camera, "id", ""), 20)
  flags = []
  if speed_limit <= 0:
    flags.append("!ZERO")
  if raw_type == "99":
    flags.append("!99")
  if not category or category == "UNKNOWN":
    flags.append("!UNK")
  flag_text = f" {' '.join(flags)}" if flags else ""
  return "\n".join((
    f"CAM {category or 'UNKNOWN'} c={type_code} v={speed_limit}{flag_text} id={camera_id}",
    f"TYPE {raw_type}",
    f"SECT {section_type} LEN {section_length_m}",
    f"ROAD {road_type} | {road_name}",
    f"TEXT {place} d={distance_m}m a={angle_deg:+.0f}",
  ))


def _camera_overlay_label(camera) -> str:
  label = _candidate_category_label(camera)
  speed_limit = int(getattr(camera, "speed_limit", 0) or 0)
  return f"{label} {speed_limit}" if speed_limit > 0 else label


def _build_osm_road_overlay_text(db_path: Path, gps, candidates=(), current_road_name: str = "") -> str:
  try:
    segments = nearby_road_segments(
      db_path,
      gps.latitude,
      gps.longitude,
      OSM_ROAD_OVERLAY_RADIUS_M,
      OSM_ROAD_OVERLAY_MAX_SEGMENTS,
    )
    roads = []
    for segment in segments:
      x1, y1 = latlon_to_car_space_m(gps.latitude, gps.longitude, gps.bearingDeg, segment.lat1, segment.lon1)
      x2, y2 = latlon_to_car_space_m(gps.latitude, gps.longitude, gps.bearingDeg, segment.lat2, segment.lon2)
      if max(x1, x2) < -20.0 or min(x1, x2) > OSM_ROAD_OVERLAY_RADIUS_M + 30.0:
        continue
      if min(abs(y1), abs(y2)) > OSM_ROAD_OVERLAY_RADIUS_M:
        continue
      roads.append({
        "x1": round(x1, 1),
        "y1": round(y1, 1),
        "x2": round(x2, 1),
        "y2": round(y2, 1),
        "n": segment.display_name[:28],
        "h": segment.highway,
        "c": road_name_matches(current_road_name, segment.name, segment.ref),
      })

    cameras = []
    for camera in candidates[:MAX_CAMERA_CANDIDATES]:
      x, y = latlon_to_car_space_m(gps.latitude, gps.longitude, gps.bearingDeg, camera.lat, camera.lon)
      if -20.0 <= x <= float(max(OSM_ROAD_OVERLAY_RADIUS_M, getattr(camera, "distance_m", 0.0) + 20.0)):
        cameras.append({
          "x": round(x, 1),
          "y": round(y, 1),
          "d": int(max(0.0, float(getattr(camera, "distance_m", 0.0)))),
          "s": int(getattr(camera, "speed_limit", 0) or 0),
          "t": _camera_overlay_label(camera),
        })

    if not roads and not cameras:
      return ""
    return json.dumps({
      "road": (current_road_name or "")[:32],
      "roads": roads,
      "cameras": cameras,
    }, ensure_ascii=False, separators=(",", ":"))
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
    category = normalize_camera_category(camera.camera_type, camera.section_type)
  if type_code == 0:
    type_code = camera_type_code(camera.camera_type, camera.section_type)

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
  nav.camDebugText = _format_camera_classification_debug_text(camera, category, type_code, road_class)
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
              _osm_roads_db_path(), gps, [], current_road_name
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
        match = find_current_road(
          _osm_roads_db_path(),
          gps.latitude,
          gps.longitude,
          gps.bearingDeg,
          float(tuning["local_osm_road_radius_m"]),
          previous_name=current_road_name,
        )
        current_road_name = match.display_name if match is not None else ""
      elif not bool(tuning["use_local_osm_roads"]):
        current_road_name = ""

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
      )
      active_camera = active_candidates[0] if active_candidates else None

      if int(tuning["osm_road_overlay_mode"]) > 0:
        if now - last_osm_overlay_t >= OSM_ROAD_OVERLAY_INTERVAL_SECONDS:
          last_osm_overlay_t = now
          osm_road_overlay_text = _build_osm_road_overlay_text(
            _osm_roads_db_path(), gps, active_candidates, current_road_name
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
