#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

try:
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_DB_DIR
except ModuleNotFoundError:
  from selfdrive.navd.paths import DEFAULT_NAVD_DB_DIR


DEFAULT_OSM_ROADS_DB_PATH = Path(os.getenv("OSM_ROADS_DB", str(DEFAULT_NAVD_DB_DIR / "osm_roads_kr.sqlite3")))
METERS_PER_DEG_LAT = 111320.0
DEFAULT_LOOKUP_RADIUS_M = 50.0
MAX_HEADING_DIFF_DEG = 60.0
PREVIOUS_ROAD_BONUS = -18.0
PREVIOUS_OSM_BONUS = -8.0
MAJOR_HIGHWAYS = {
  "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
  "secondary", "secondary_link",
}
DbSource = Path | sqlite3.Connection

ROAD_NAME_SUFFIXES = ("EXPRESSWAY", "HIGHWAY", "ROAD", "RO", "GIL", "DAERO", "STREET")


@dataclass(frozen=True)
class OSMRoadMatch:
  road_id: int
  osm_id: int
  name: str
  ref: str
  highway: str
  road_class: str
  oneway: int
  distance_m: float
  heading_diff_deg: float
  bearing_deg: float
  driving_bearing_deg: float
  score: float

  @property
  def display_name(self) -> str:
    return self.name or self.ref


@dataclass(frozen=True)
class OSMRoadSegment:
  road_id: int
  osm_id: int
  name: str
  ref: str
  highway: str
  road_class: str
  oneway: int
  lat1: float
  lon1: float
  lat2: float
  lon2: float
  bearing_deg: float
  distance_m: float

  @property
  def display_name(self) -> str:
    return self.name or self.ref


@dataclass(frozen=True)
class OSMRoadTransition:
  road: OSMRoadSegment
  turn_angle_deg: float


def normalize_road_name(value: str) -> str:
  normalized = (value or "").strip().upper()
  normalized = re.sub(r"\s+", "", normalized)
  normalized = re.sub(r"[\(\)\[\]\{\},._\-]", "", normalized)
  for suffix in ROAD_NAME_SUFFIXES:
    if normalized.endswith(suffix) and len(normalized) > len(suffix):
      normalized = normalized[: -len(suffix)]
  return normalized


def road_name_matches(current_road_name: str, *candidate_names: str) -> bool:
  current = normalize_road_name(current_road_name)
  if not current:
    return False
  for candidate_name in candidate_names:
    candidate = normalize_road_name(candidate_name)
    if not candidate:
      continue
    if current == candidate:
      return True
    if len(current) >= 3 and len(candidate) >= 3 and (current in candidate or candidate in current):
      return True
  return False


def angle_diff_deg(a: float, b: float) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def bidirectional_heading_diff_deg(segment_bearing_deg: float, heading_deg: float) -> float:
  return min(angle_diff_deg(segment_bearing_deg, heading_deg), angle_diff_deg((segment_bearing_deg + 180.0) % 360.0, heading_deg))


def align_bearing_to_heading(segment_bearing_deg: float, heading_deg: float | None) -> float:
  if heading_deg is None:
    return segment_bearing_deg % 360.0
  opposite_bearing = (segment_bearing_deg + 180.0) % 360.0
  return opposite_bearing if angle_diff_deg(opposite_bearing, heading_deg) < angle_diff_deg(segment_bearing_deg, heading_deg) else segment_bearing_deg % 360.0


def driving_bearing_for_oneway(segment_bearing_deg: float, oneway: int, heading_deg: float | None) -> float:
  if oneway > 0:
    return segment_bearing_deg % 360.0
  if oneway < 0:
    return (segment_bearing_deg + 180.0) % 360.0
  return align_bearing_to_heading(segment_bearing_deg, heading_deg)


def road_heading_diff_deg(segment_bearing_deg: float, oneway: int, heading_deg: float) -> float:
  if oneway != 0:
    return angle_diff_deg(driving_bearing_for_oneway(segment_bearing_deg, oneway, heading_deg), heading_deg)
  return bidirectional_heading_diff_deg(segment_bearing_deg, heading_deg)


def _lon_scale(lat: float) -> float:
  return METERS_PER_DEG_LAT * max(0.1, math.cos(math.radians(lat)))


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


def _point_to_segment_distance_xy(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
  dx = x2 - x1
  dy = y2 - y1
  length_sq = dx * dx + dy * dy
  if length_sq <= 0.0:
    return math.hypot(px - x1, py - y1)
  t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
  return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _bounding_box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
  lat_delta = radius_m / METERS_PER_DEG_LAT
  lon_delta = radius_m / _lon_scale(lat)
  return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def latlon_to_car_space_m(origin_lat: float, origin_lon: float, heading_deg: float, lat: float, lon: float) -> tuple[float, float]:
  north_m = (lat - origin_lat) * METERS_PER_DEG_LAT
  east_m = (lon - origin_lon) * _lon_scale(origin_lat)
  heading_rad = math.radians(heading_deg)
  forward_m = north_m * math.cos(heading_rad) + east_m * math.sin(heading_rad)
  right_m = east_m * math.cos(heading_rad) - north_m * math.sin(heading_rad)
  return forward_m, right_m


def _car_space_to_latlon(origin_lat: float, origin_lon: float, heading_deg: float, forward_m: float, right_m: float) -> tuple[float, float]:
  heading_rad = math.radians(heading_deg)
  north_m = forward_m * math.cos(heading_rad) - right_m * math.sin(heading_rad)
  east_m = forward_m * math.sin(heading_rad) + right_m * math.cos(heading_rad)
  return origin_lat + north_m / METERS_PER_DEG_LAT, origin_lon + east_m / _lon_scale(origin_lat)


def _corridor_bounding_box(
  lat: float,
  lon: float,
  heading_deg: float,
  forward_start_m: float,
  forward_end_m: float,
  side_limit_m: float,
) -> tuple[float, float, float, float]:
  points = [
    _car_space_to_latlon(lat, lon, heading_deg, forward_start_m, -side_limit_m),
    _car_space_to_latlon(lat, lon, heading_deg, forward_start_m, side_limit_m),
    _car_space_to_latlon(lat, lon, heading_deg, forward_end_m, -side_limit_m),
    _car_space_to_latlon(lat, lon, heading_deg, forward_end_m, side_limit_m),
  ]
  return min(p[0] for p in points), max(p[0] for p in points), min(p[1] for p in points), max(p[1] for p in points)


def _segment_intersects_rect(x1: float, y1: float, x2: float, y2: float,
                             min_x: float, max_x: float, min_y: float, max_y: float) -> bool:
  if min_x <= x1 <= max_x and min_y <= y1 <= max_y:
    return True
  if min_x <= x2 <= max_x and min_y <= y2 <= max_y:
    return True
  dx = x2 - x1
  dy = y2 - y1
  p = (-dx, dx, -dy, dy)
  q = (x1 - min_x, max_x - x1, y1 - min_y, max_y - y1)
  u1, u2 = 0.0, 1.0
  for pi, qi in zip(p, q, strict=False):
    if pi == 0.0:
      if qi < 0.0:
        return False
      continue
    t = qi / pi
    if pi < 0.0:
      if t > u2:
        return False
      u1 = max(u1, t)
    else:
      if t < u1:
        return False
      u2 = min(u2, t)
  return True


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
  return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ? LIMIT 1", (name,)).fetchone() is not None


def _db_source_exists(db_source: DbSource) -> bool:
  return isinstance(db_source, sqlite3.Connection) or Path(db_source).exists()


def connect_readonly_db(db_path: Path = DEFAULT_OSM_ROADS_DB_PATH) -> sqlite3.Connection:
  conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
  conn.row_factory = sqlite3.Row
  return conn


def _connect_read_db(db_source: DbSource):
  if isinstance(db_source, sqlite3.Connection):
    db_source.row_factory = sqlite3.Row
    return None, db_source
  conn = connect_readonly_db(Path(db_source))
  return conn, conn


def _row_to_segment(row) -> OSMRoadSegment:
  return OSMRoadSegment(
    road_id=int(row["id"]),
    osm_id=int(row["osm_id"]),
    name=str(row["name"] or ""),
    ref=str(row["ref"] or ""),
    highway=str(row["highway"] or ""),
    road_class=str(row["road_class"] or ""),
    oneway=int(row["oneway"]),
    lat1=float(row["lat1"]),
    lon1=float(row["lon1"]),
    lat2=float(row["lat2"]),
    lon2=float(row["lon2"]),
    bearing_deg=float(row["bearing_deg"]),
    distance_m=float(row["distance_m"]) if "distance_m" in row.keys() else 0.0,
  )


def _metadata_value(db_path: Path, key: str) -> str:
  try:
    if not db_path.exists():
      return ""
    with closing(sqlite3.connect(db_path)) as conn:
      row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
      return str(row[0]) if row and row[0] is not None else ""
  except sqlite3.Error:
    return ""


def database_segment_count(db_path: Path = DEFAULT_OSM_ROADS_DB_PATH) -> int:
  value = _metadata_value(db_path, "segment_count")
  try:
    return max(0, int(value))
  except ValueError:
    return 0


def database_built_at(db_path: Path = DEFAULT_OSM_ROADS_DB_PATH) -> str:
  value = _metadata_value(db_path, "built_at")
  try:
    timestamp = int(value)
  except ValueError:
    return ""
  return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def road_successors(db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH, road_id: int = 0, limit: int = 16) -> list[OSMRoadTransition]:
  if not _db_source_exists(db_path):
    return []
  close_conn, conn = _connect_read_db(db_path)
  try:
    if not _table_exists(conn, "roads") or not _table_exists(conn, "road_adjacency"):
      return []
    rows = conn.execute("""
      SELECT roads.id, roads.osm_id, roads.name, roads.ref, roads.highway, roads.road_class, roads.oneway,
             roads.lat1, roads.lon1, roads.lat2, roads.lon2, roads.bearing_deg,
             0.0 AS distance_m,
             road_adjacency.turn_angle_deg
      FROM road_adjacency
      JOIN roads ON roads.id = road_adjacency.to_road_id
      WHERE road_adjacency.from_road_id = ?
      ORDER BY road_adjacency.turn_angle_deg ASC, roads.id ASC
      LIMIT ?
    """, (road_id, max(0, limit))).fetchall()
  except sqlite3.Error:
    return []
  finally:
    if close_conn is not None:
      close_conn.close()
  return [OSMRoadTransition(_row_to_segment(row), float(row["turn_angle_deg"])) for row in rows]


def find_current_road(
  db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH,
  lat: float = 0.0,
  lon: float = 0.0,
  heading_deg: float | None = 0.0,
  radius_m: float = DEFAULT_LOOKUP_RADIUS_M,
  previous_name: str = "",
  previous_road_id: int | None = None,
  previous_osm_id: int | None = None,
  max_heading_diff_deg: float = MAX_HEADING_DIFF_DEG,
) -> OSMRoadMatch | None:
  if not _db_source_exists(db_path):
    return None
  lat_min, lat_max, lon_min, lon_max = _bounding_box(lat, lon, radius_m)
  close_conn, conn = _connect_read_db(db_path)
  try:
    if not _table_exists(conn, "roads") or not _table_exists(conn, "roads_rtree"):
      return None
    rows = conn.execute("""
      SELECT roads.*
      FROM roads
      JOIN roads_rtree ON roads.id = roads_rtree.id
      WHERE roads_rtree.min_lat <= ?
        AND roads_rtree.max_lat >= ?
        AND roads_rtree.min_lon <= ?
        AND roads_rtree.max_lon >= ?
    """, (lat_max, lat_min, lon_max, lon_min)).fetchall()
  except sqlite3.Error:
    return None
  finally:
    if close_conn is not None:
      close_conn.close()

  best: OSMRoadMatch | None = None
  for row in rows:
    distance_m = _distance_point_to_segment_m(lat, lon, row["lat1"], row["lon1"], row["lat2"], row["lon2"])
    if distance_m > radius_m:
      continue
    road_id = int(row["id"])
    osm_id = int(row["osm_id"])
    oneway = int(row["oneway"])
    heading_diff = 0.0
    if heading_deg is not None:
      heading_diff = road_heading_diff_deg(float(row["bearing_deg"]), oneway, heading_deg)
      if heading_diff > max_heading_diff_deg:
        continue
    name = str(row["name"] or "")
    ref = str(row["ref"] or "")
    name_bonus = -8.0 if road_name_matches(previous_name, name, ref) else 0.0
    previous_road_bonus = PREVIOUS_ROAD_BONUS if previous_road_id is not None and road_id == previous_road_id else 0.0
    previous_osm_bonus = PREVIOUS_OSM_BONUS if previous_osm_id is not None and osm_id == previous_osm_id else 0.0
    highway_bonus = -4.0 if str(row["highway"] or "") in ("motorway", "trunk", "primary") else 0.0
    score = distance_m + heading_diff * 0.9 + name_bonus + previous_road_bonus + previous_osm_bonus + highway_bonus
    match = OSMRoadMatch(
      road_id=road_id,
      osm_id=osm_id,
      name=name,
      ref=ref,
      highway=str(row["highway"] or ""),
      road_class=str(row["road_class"] or ""),
      oneway=oneway,
      distance_m=distance_m,
      heading_diff_deg=heading_diff,
      bearing_deg=float(row["bearing_deg"]),
      driving_bearing_deg=driving_bearing_for_oneway(float(row["bearing_deg"]), oneway, heading_deg),
      score=score,
    )
    if best is None or match.score < best.score:
      best = match
  return best


def nearby_road_segments(
  db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH,
  lat: float = 0.0,
  lon: float = 0.0,
  radius_m: float = 180.0,
  limit: int = 80,
) -> list[OSMRoadSegment]:
  if not _db_source_exists(db_path):
    return []
  lat_min, lat_max, lon_min, lon_max = _bounding_box(lat, lon, radius_m)
  close_conn, conn = _connect_read_db(db_path)
  try:
    if not _table_exists(conn, "roads") or not _table_exists(conn, "roads_rtree"):
      return []
    rows = conn.execute("""
      SELECT roads.*
      FROM roads
      JOIN roads_rtree ON roads.id = roads_rtree.id
      WHERE roads_rtree.min_lat <= ?
        AND roads_rtree.max_lat >= ?
        AND roads_rtree.min_lon <= ?
        AND roads_rtree.max_lon >= ?
    """, (lat_max, lat_min, lon_max, lon_min)).fetchall()
  except sqlite3.Error:
    return []
  finally:
    if close_conn is not None:
      close_conn.close()

  segments = []
  for row in rows:
    distance_m = _distance_point_to_segment_m(lat, lon, row["lat1"], row["lon1"], row["lat2"], row["lon2"])
    if distance_m <= radius_m:
      segment = _row_to_segment(row)
      segments.append(OSMRoadSegment(**{**segment.__dict__, "distance_m": distance_m}))
  segments.sort(key=lambda segment: segment.distance_m)
  return segments[:max(0, limit)]


def forward_road_segments(
  db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH,
  lat: float = 0.0,
  lon: float = 0.0,
  heading_deg: float = 0.0,
  forward_start_m: float = -30.0,
  forward_end_m: float = 450.0,
  side_limit_m: float = 70.0,
  major_side_limit_m: float = 120.0,
  limit: int = 120,
) -> list[OSMRoadSegment]:
  if not _db_source_exists(db_path) or forward_end_m <= forward_start_m:
    return []
  max_side_m = max(side_limit_m, major_side_limit_m)
  lat_min, lat_max, lon_min, lon_max = _corridor_bounding_box(lat, lon, heading_deg, forward_start_m, forward_end_m, max_side_m)
  close_conn, conn = _connect_read_db(db_path)
  try:
    if not _table_exists(conn, "roads") or not _table_exists(conn, "roads_rtree"):
      return []
    rows = conn.execute("""
      SELECT roads.*
      FROM roads
      JOIN roads_rtree ON roads.id = roads_rtree.id
      WHERE roads_rtree.min_lat <= ?
        AND roads_rtree.max_lat >= ?
        AND roads_rtree.min_lon <= ?
        AND roads_rtree.max_lon >= ?
    """, (lat_max, lat_min, lon_max, lon_min)).fetchall()
  except sqlite3.Error:
    return []
  finally:
    if close_conn is not None:
      close_conn.close()

  selected: list[tuple[float, float, OSMRoadSegment]] = []
  for row in rows:
    x1, y1 = latlon_to_car_space_m(lat, lon, heading_deg, row["lat1"], row["lon1"])
    x2, y2 = latlon_to_car_space_m(lat, lon, heading_deg, row["lat2"], row["lon2"])
    highway = str(row["highway"] or "")
    row_side_limit_m = major_side_limit_m if highway in MAJOR_HIGHWAYS else side_limit_m
    if not _segment_intersects_rect(x1, y1, x2, y2, forward_start_m, forward_end_m, -row_side_limit_m, row_side_limit_m):
      continue
    distance_m = _point_to_segment_distance_xy(0.0, 0.0, x1, y1, x2, y2)
    sort_forward_m = max(0.0, min(x1, x2))
    selected.append((sort_forward_m, distance_m, _row_to_segment(row)))
  selected.sort(key=lambda item: (item[0], item[1]))
  return [segment for _, _, segment in selected[:max(0, limit)]]
