#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
  from openpilot.selfdrive.navd.osm_roads_db import create_speed_camera_indexes, create_speed_camera_schema, put_metadata
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads_db import create_speed_camera_indexes, create_speed_camera_schema, put_metadata


METERS_PER_DEG_LAT = 111320.0
DEFAULT_CAMERA_MATCH_RADIUS_M = 65.0
DEFAULT_CAMERA_MAX_MATCHES = 3
OPPOSITE_PARALLEL_BEARING_DIFF_DEG = 150.0
NORMAL_DISPLAY_MIN_CONFIDENCE = 0.75
NORMAL_DISPLAY_MAX_DISTANCE_M = 35.0
PARALLEL_CLEAR_PRIMARY_MAX_DISTANCE_M = 12.0
PARALLEL_CLEAR_OPPOSITE_MIN_DISTANCE_M = 20.0
PARALLEL_CLEAR_CONFIDENCE_MARGIN = 0.12
SPEED_ICON_CAMERA_TYPES = ("1", "2", "1+02")
INTERSECTION_CAMERA_KEYWORDS = ("교차로", "사거리", "삼거리", "오거리", "로터리")

ID_COLUMNS = (
  "external_id", "camera_id", "cam_id", "id", "관리번호", "번호",
  "무인교통단속카메라관리번호", "무인교통단속카메라 관리번호", "MNLSS_REGLT_CAMERA_MANAGE_NO", "manage_no",
)
LAT_COLUMNS = ("lat", "latitude", "y", "위도", "LATITUDE")
LON_COLUMNS = ("lon", "lng", "longitude", "x", "경도", "LONGITUDE")
SPEED_COLUMNS = (
  "speed_limit_kph", "speed_limit", "limit_speed", "camlimitspeed", "제한속도", "제한속도(km/h)",
  "LMTT_VE", "lmttVe",
)
TYPE_COLUMNS = (
  "camera_type", "cam_type", "type", "종류", "카메라종류", "단속구분", "단속유형", "단속종류",
  "REGLT_SE", "regltSe",
)
BEARING_COLUMNS = ("bearing_deg", "bearing", "heading", "direction_deg", "방향각")
DIRECTION_COLUMNS = ("direction", "dir", "방향", "도로노선방향", "ROAD_ROUTE_DRC")
ROAD_NAME_COLUMNS = ("road_name", "road", "roadname", "도로명", "도로노선명", "소재지도로명주소", "ROAD_ROUTE_NM", "RDNMADR")
ADDRESS_COLUMNS = ("address", "addr", "주소", "설치장소", "소재지지번주소", "ITLPC", "LNMADR", "place")
UPDATED_COLUMNS = ("source_updated_at", "updated_at", "update_date", "갱신일", "수정일", "데이터기준일자", "최종수정일", "REFERENCE_DATE")

ROAD_NAME_SUFFIXES = ("EXPRESSWAY", "HIGHWAY", "ROAD", "RO", "GIL", "DAERO", "STREET")


@dataclass(frozen=True)
class SpeedCameraImportSummary:
  csv_path: Path
  source: str
  total_rows: int
  imported_count: int
  skipped_count: int
  matched_camera_count: int
  match_count: int
  lookup_count: int


def _lon_scale(lat: float) -> float:
  return METERS_PER_DEG_LAT * max(0.1, math.cos(math.radians(lat)))


def _bounding_box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
  lat_delta = radius_m / METERS_PER_DEG_LAT
  lon_delta = radius_m / _lon_scale(lat)
  return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def _distance_point_to_segment_m(lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  lon_scale = _lon_scale(lat)
  x1 = (lon1 - lon) * lon_scale
  y1 = (lat1 - lat) * METERS_PER_DEG_LAT
  x2 = (lon2 - lon) * lon_scale
  y2 = (lat2 - lat) * METERS_PER_DEG_LAT
  dx = x2 - x1
  dy = y2 - y1
  length_sq = dx * dx + dy * dy
  if length_sq <= 0.0:
    return math.hypot(x1, y1)
  t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length_sq))
  return math.hypot(x1 + t * dx, y1 + t * dy)


def _angle_diff_deg(a: float, b: float) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def _normalize_code(value: Any) -> str:
  text = str(value or "").strip()
  stripped = text.lstrip("0")
  return stripped or text


def _speed_icon_camera_type(camera_type: Any) -> bool:
  return _normalize_code(camera_type) in SPEED_ICON_CAMERA_TYPES


def _signal_speed_camera_type(camera_type: Any) -> bool:
  return _normalize_code(camera_type) in ("2", "1+02")


def _intersection_camera_context(camera: sqlite3.Row) -> bool:
  text = f"{camera['address'] or ''} {camera['road_name'] or ''}"
  return any(keyword in text for keyword in INTERSECTION_CAMERA_KEYWORDS)


def _primary_match_clearly_better_than_opposite(match: dict[str, Any],
                                                opposite_distance_m: float,
                                                opposite_confidence: float) -> bool:
  return (
    float(match["distance_m"]) <= PARALLEL_CLEAR_PRIMARY_MAX_DISTANCE_M
    and opposite_distance_m >= PARALLEL_CLEAR_OPPOSITE_MIN_DISTANCE_M
    and float(match["match_confidence"]) - opposite_confidence >= PARALLEL_CLEAR_CONFIDENCE_MARGIN
  )


def _opposite_parallel_match(match: dict[str, Any], matches: list[dict[str, Any]]) -> dict[str, Any] | None:
  opposite: list[dict[str, Any]] = []
  for other in matches:
    if int(other["road_id"]) == int(match["road_id"]):
      continue
    if _angle_diff_deg(float(match["road_bearing_deg"]), float(other["road_bearing_deg"])) >= OPPOSITE_PARALLEL_BEARING_DIFF_DEG:
      opposite.append(other)
  if not opposite:
    return None
  opposite.sort(key=lambda item: (-float(item["match_confidence"]), float(item["distance_m"]), int(item["road_id"])))
  return opposite[0]


def _classify_lookup_match(camera: sqlite3.Row, match: dict[str, Any],
                           matches: list[dict[str, Any]]) -> tuple[str, str, str, int, float, float]:
  opposite = _opposite_parallel_match(match, matches)
  opposite_road_id = int(opposite["road_id"]) if opposite is not None else 0
  opposite_distance_m = float(opposite["distance_m"]) if opposite is not None else 0.0
  opposite_confidence = float(opposite["match_confidence"]) if opposite is not None else 0.0

  if int(camera["speed_limit_kph"]) <= 0:
    return "rejected", "unknown", "speed_limit_missing", opposite_road_id, opposite_distance_m, opposite_confidence
  if not _speed_icon_camera_type(camera["camera_type"]):
    return "suspicious", "unknown", "unsupported_camera_type", opposite_road_id, opposite_distance_m, opposite_confidence
  if not int(match["primary_match"]):
    return "suspicious", "unknown", "secondary_match", opposite_road_id, opposite_distance_m, opposite_confidence
  if float(match["match_confidence"]) < NORMAL_DISPLAY_MIN_CONFIDENCE:
    return "suspicious", "unknown", "low_confidence", opposite_road_id, opposite_distance_m, opposite_confidence
  if float(match["distance_m"]) > NORMAL_DISPLAY_MAX_DISTANCE_M:
    return "suspicious", "unknown", "far_match", opposite_road_id, opposite_distance_m, opposite_confidence
  if opposite is not None and not (
    _signal_speed_camera_type(camera["camera_type"])
    and
    _intersection_camera_context(camera)
    and _primary_match_clearly_better_than_opposite(match, opposite_distance_m, opposite_confidence)
  ):
    return "suspicious", "ambiguous_parallel", "parallel_road_ambiguous", opposite_road_id, opposite_distance_m, opposite_confidence
  if _normalize_code(camera["direction"]) not in ("1", "2"):
    return "suspicious", "unknown", "unknown_direction", opposite_road_id, opposite_distance_m, opposite_confidence
  return "normal", "verified", "", opposite_road_id, opposite_distance_m, opposite_confidence


def _driving_heading_diff_deg(road_bearing_deg: float, oneway: int, camera_bearing_deg: float) -> float:
  if camera_bearing_deg < 0.0:
    return -1.0
  if oneway > 0:
    return _angle_diff_deg(road_bearing_deg, camera_bearing_deg)
  if oneway < 0:
    return _angle_diff_deg((road_bearing_deg + 180.0) % 360.0, camera_bearing_deg)
  return min(
    _angle_diff_deg(road_bearing_deg, camera_bearing_deg),
    _angle_diff_deg((road_bearing_deg + 180.0) % 360.0, camera_bearing_deg),
  )


def _clamp(value: float, low: float, high: float) -> float:
  return max(low, min(high, value))


def _normalized_keys(row: dict[str, str]) -> dict[str, str]:
  return {str(key).strip().lower().replace(" ", "").replace("_", ""): value for key, value in row.items()}


def _column_value(row: dict[str, str], columns: tuple[str, ...]) -> str:
  normalized = _normalized_keys(row)
  for column in columns:
    value = normalized.get(column.strip().lower().replace(" ", "").replace("_", ""))
    if value is not None and str(value).strip():
      return str(value).strip()
  return ""


def _parse_float(value: str, default: float = 0.0) -> float:
  if not value:
    return default
  cleaned = re.sub(r"[^0-9.+-]", "", value)
  try:
    return float(cleaned)
  except ValueError:
    return default


def _parse_int(value: str, default: int = 0) -> int:
  return int(round(_parse_float(value, float(default))))


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
  data = csv_path.read_bytes()
  for encoding in ("utf-8-sig", "cp949", "euc-kr"):
    try:
      text = data.decode(encoding)
      break
    except UnicodeDecodeError:
      continue
  else:
    text = data.decode("utf-8", errors="replace")
  return list(csv.DictReader(io.StringIO(text)))


def _normalize_road_name(value: str) -> str:
  normalized = (value or "").strip().upper()
  normalized = re.sub(r"\s+", "", normalized)
  normalized = re.sub(r"[\(\)\[\]\{\},._\-]", "", normalized)
  for suffix in ROAD_NAME_SUFFIXES:
    if normalized.endswith(suffix) and len(normalized) > len(suffix):
      normalized = normalized[: -len(suffix)]
  return normalized


def _road_name_matches(camera_road_name: str, road_name: str, road_ref: str) -> bool:
  camera = _normalize_road_name(camera_road_name)
  if not camera:
    return False
  for candidate in (_normalize_road_name(road_name), _normalize_road_name(road_ref)):
    if not candidate:
      continue
    if camera == candidate:
      return True
    if len(camera) >= 3 and len(candidate) >= 3 and (camera in candidate or candidate in camera):
      return True
  return False


def _clear_speed_camera_tables(conn: sqlite3.Connection) -> None:
  conn.execute("DELETE FROM route_camera_lookup")
  conn.execute("DELETE FROM speed_camera_road_matches")
  conn.execute("DELETE FROM speed_cameras")


def _insert_speed_cameras(conn: sqlite3.Connection, rows: list[dict[str, str]], source: str) -> tuple[int, int]:
  imported = 0
  skipped = 0
  for idx, row in enumerate(rows, start=1):
    lat = _parse_float(_column_value(row, LAT_COLUMNS))
    lon = _parse_float(_column_value(row, LON_COLUMNS))
    if lat == 0.0 or lon == 0.0:
      skipped += 1
      continue
    external_id = _column_value(row, ID_COLUMNS) or str(idx)
    cursor = conn.execute(
      """
      INSERT OR IGNORE INTO speed_cameras(
        external_id, camera_type, lat, lon, speed_limit_kph, bearing_deg, direction,
        road_name, address, source, source_updated_at, raw_json, map_confidence
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      (
        external_id,
        _column_value(row, TYPE_COLUMNS),
        lat,
        lon,
        _parse_int(_column_value(row, SPEED_COLUMNS)),
        _parse_float(_column_value(row, BEARING_COLUMNS), -1.0),
        _column_value(row, DIRECTION_COLUMNS),
        _column_value(row, ROAD_NAME_COLUMNS),
        _column_value(row, ADDRESS_COLUMNS),
        source,
        _column_value(row, UPDATED_COLUMNS),
        json.dumps(row, ensure_ascii=False, sort_keys=True),
        1.0,
      ),
    )
    if cursor.rowcount > 0:
      imported += 1
    else:
      skipped += 1
  return imported, skipped


def _candidate_roads(conn: sqlite3.Connection, lat: float, lon: float, radius_m: float) -> list[sqlite3.Row]:
  lat_min, lat_max, lon_min, lon_max = _bounding_box(lat, lon, radius_m)
  return conn.execute(
    """
    SELECT roads.*
    FROM roads
    JOIN roads_rtree ON roads.id = roads_rtree.id
    WHERE roads_rtree.min_lat <= ?
      AND roads_rtree.max_lat >= ?
      AND roads_rtree.min_lon <= ?
      AND roads_rtree.max_lon >= ?
    """,
    (lat_max, lat_min, lon_max, lon_min),
  ).fetchall()


def _match_speed_cameras_to_roads(conn: sqlite3.Connection, radius_m: float, max_matches_per_camera: int) -> tuple[int, int, int]:
  conn.row_factory = sqlite3.Row
  matched_camera_ids: set[int] = set()
  match_count = 0
  lookup_count = 0
  cameras = conn.execute("SELECT * FROM speed_cameras ORDER BY id").fetchall()
  for camera in cameras:
    candidates: list[tuple[float, float, float, int, int, sqlite3.Row]] = []
    camera_bearing = float(camera["bearing_deg"])
    for road in _candidate_roads(conn, float(camera["lat"]), float(camera["lon"]), radius_m):
      distance_m = _distance_point_to_segment_m(
        float(camera["lat"]), float(camera["lon"]),
        float(road["lat1"]), float(road["lon1"]), float(road["lat2"]), float(road["lon2"]),
      )
      if distance_m > radius_m:
        continue
      heading_diff = _driving_heading_diff_deg(float(road["bearing_deg"]), int(road["oneway"]), camera_bearing)
      if heading_diff > 105.0:
        continue
      same_name = 1 if _road_name_matches(str(camera["road_name"]), str(road["name"]), str(road["ref"])) else 0
      priority = min(100.0, max(0.0, float(road["road_priority"])))
      heading_cost = 0.0 if heading_diff < 0.0 else heading_diff * 0.35
      score = distance_m + heading_cost - priority * 0.08 - same_name * 12.0
      confidence = 1.0 - min(1.0, distance_m / max(1.0, radius_m))
      confidence += 0.15 if same_name else 0.0
      confidence += 0.12 if 0.0 <= heading_diff <= 35.0 else 0.0
      confidence += min(0.10, priority / 1000.0)
      candidates.append((score, distance_m, heading_diff, same_name, int(road["id"]), road))
    candidates.sort(key=lambda item: (item[0], item[1], item[4]))
    selected_matches: list[dict[str, Any]] = []
    for index, (score, distance_m, heading_diff, same_name, road_id, road) in enumerate(candidates[:max(1, max_matches_per_camera)]):
      primary_match = 1 if index == 0 else 0
      confidence = 1.0 - min(1.0, distance_m / max(1.0, radius_m))
      confidence += 0.15 if same_name else 0.0
      confidence += 0.12 if 0.0 <= heading_diff <= 35.0 else 0.0
      confidence += min(0.10, max(0.0, float(road["road_priority"])) / 1000.0)
      confidence = _clamp(confidence, 0.0, 1.0)
      selected_matches.append({
        "score": score,
        "distance_m": distance_m,
        "heading_diff": heading_diff,
        "same_name": same_name,
        "road_id": road_id,
        "road": road,
        "road_bearing_deg": float(road["bearing_deg"]),
        "primary_match": primary_match,
        "match_confidence": confidence,
      })

    for match in selected_matches:
      road_id = int(match["road_id"])
      distance_m = float(match["distance_m"])
      heading_diff = float(match["heading_diff"])
      score = float(match["score"])
      same_name = int(match["same_name"])
      confidence = float(match["match_confidence"])
      primary_match = int(match["primary_match"])
      display_class, direction_verdict, reject_reason, opposite_road_id, opposite_distance_m, opposite_confidence = _classify_lookup_match(
        camera, match, selected_matches
      )
      cursor = conn.execute(
        """
        INSERT INTO speed_camera_road_matches(
          camera_id, road_id, distance_m, heading_diff_deg, match_score, match_confidence,
          same_road_name, primary_match, matched_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (int(camera["id"]), road_id, distance_m, heading_diff, score, confidence, same_name, primary_match, "nearest_road"),
      )
      match_id = int(cursor.lastrowid)
      conn.execute(
        """
        INSERT OR REPLACE INTO route_camera_lookup(
          road_id, camera_id, match_id, match_distance_m, match_confidence, primary_match,
          speed_limit_kph, camera_type, camera_bearing_deg, display_class, direction_verdict,
          reject_reason, opposite_road_id, opposite_match_distance_m, opposite_match_confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
          road_id,
          int(camera["id"]),
          match_id,
          distance_m,
          confidence,
          primary_match,
          int(camera["speed_limit_kph"]),
          str(camera["camera_type"]),
          camera_bearing,
          display_class,
          direction_verdict,
          reject_reason,
          opposite_road_id,
          opposite_distance_m,
          opposite_confidence,
        ),
      )
      matched_camera_ids.add(int(camera["id"]))
      match_count += 1
      lookup_count += 1
  return len(matched_camera_ids), match_count, lookup_count


def import_speed_cameras_from_csv(
  conn: sqlite3.Connection,
  csv_path: Path,
  *,
  source: str = "",
  match_radius_m: float = DEFAULT_CAMERA_MATCH_RADIUS_M,
  max_matches_per_camera: int = DEFAULT_CAMERA_MAX_MATCHES,
  clear_existing: bool = True,
) -> SpeedCameraImportSummary:
  csv_path = Path(csv_path).expanduser()
  if not csv_path.exists():
    raise RuntimeError(f"speed camera CSV missing: {csv_path}")
  source = source or csv_path.stem
  create_speed_camera_schema(conn)
  if clear_existing:
    _clear_speed_camera_tables(conn)
  rows = _read_csv_rows(csv_path)
  imported, skipped = _insert_speed_cameras(conn, rows, source)
  matched_camera_count, match_count, lookup_count = _match_speed_cameras_to_roads(
    conn,
    max(1.0, float(match_radius_m)),
    max(1, int(max_matches_per_camera)),
  )
  create_speed_camera_indexes(conn)
  put_metadata(conn, {
    "speed_camera_source": source,
    "speed_camera_csv": str(csv_path),
    "speed_camera_count": imported,
    "speed_camera_skipped_count": skipped,
    "speed_camera_matched_count": matched_camera_count,
    "speed_camera_match_count": match_count,
    "route_camera_lookup_count": lookup_count,
    "speed_camera_match_radius_m": float(match_radius_m),
  })
  conn.commit()
  return SpeedCameraImportSummary(
    csv_path=csv_path,
    source=source,
    total_rows=len(rows),
    imported_count=imported,
    skipped_count=skipped,
    matched_camera_count=matched_camera_count,
    match_count=match_count,
    lookup_count=lookup_count,
  )
