#!/usr/bin/env python3
import math
import os
import re
import sqlite3
import time
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

try:
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_DB_DIR, REPO_NAVD_DATA_DIR
except ModuleNotFoundError:
  from selfdrive.navd.paths import DEFAULT_NAVD_DB_DIR, REPO_NAVD_DATA_DIR

DEFAULT_DATA_DIR = REPO_NAVD_DATA_DIR
DEFAULT_OSM_ROADS_DB_PATH = Path(os.getenv("OSM_ROADS_DB", str(DEFAULT_NAVD_DB_DIR / "osm_roads_kr.sqlite3")))

METERS_PER_DEG_LAT = 111320.0
DEFAULT_LOOKUP_RADIUS_M = 50.0
MAX_HEADING_DIFF_DEG = 60.0
MAJOR_HIGHWAYS = {
  "motorway",
  "motorway_link",
  "trunk",
  "trunk_link",
  "primary",
  "primary_link",
  "secondary",
  "secondary_link",
}
DbSource = Path | sqlite3.Connection

ROAD_NAME_SUFFIXES = (
  "EXPRESSWAY",
  "HIGHWAY",
  "ROAD",
  "RO",
  "GIL",
  "DAERO",
  "STREET",
)


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


@dataclass(frozen=True)
class RoadGraphStats:
  node_count: int
  edge_count: int
  adjacency_count: int


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


def road_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  phi1 = math.radians(lat1)
  phi2 = math.radians(lat2)
  dlon = math.radians(lon2 - lon1)
  y = math.sin(dlon) * math.cos(phi2)
  x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
  return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def bidirectional_heading_diff_deg(segment_bearing_deg: float, heading_deg: float) -> float:
  return min(angle_diff_deg(segment_bearing_deg, heading_deg), angle_diff_deg((segment_bearing_deg + 180.0) % 360.0, heading_deg))


def segment_allowed_bearings(segment) -> tuple[float, ...]:
  bearing = float(getattr(segment, "bearing_deg", 0.0)) % 360.0
  oneway = int(getattr(segment, "oneway", 0) or 0)
  if oneway > 0:
    return (bearing,)
  if oneway < 0:
    return ((bearing + 180.0) % 360.0,)
  return (bearing, (bearing + 180.0) % 360.0)


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
  closest_x = x1 + t * dx
  closest_y = y1 + t * dy
  return math.hypot(closest_x, closest_y)


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
  lats = [point[0] for point in points]
  lons = [point[1] for point in points]
  return min(lats), max(lats), min(lons), max(lons)


def _point_to_segment_distance_xy(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
  dx = x2 - x1
  dy = y2 - y1
  length_sq = dx * dx + dy * dy
  if length_sq <= 0.0:
    return math.hypot(px - x1, py - y1)
  t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
  return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


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
  u1 = 0.0
  u2 = 1.0
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
  row = conn.execute("SELECT 1 FROM sqlite_master WHERE name = ? LIMIT 1", (name,)).fetchone()
  return row is not None


def _db_source_exists(db_source: DbSource) -> bool:
  return isinstance(db_source, sqlite3.Connection) or Path(db_source).exists()


def _connect_read_db(db_source: DbSource):
  if isinstance(db_source, sqlite3.Connection):
    db_source.row_factory = sqlite3.Row
    return None, db_source
  conn = sqlite3.connect(db_source)
  conn.row_factory = sqlite3.Row
  return conn, conn


def _road_node_key(lat: float, lon: float) -> str:
  return f"{lat:.7f},{lon:.7f}"


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


def init_db(conn: sqlite3.Connection) -> None:
  conn.execute("""
    CREATE TABLE IF NOT EXISTS metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS roads (
      id INTEGER PRIMARY KEY,
      osm_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      ref TEXT NOT NULL,
      highway TEXT NOT NULL,
      road_class TEXT NOT NULL,
      oneway INTEGER NOT NULL,
      lat1 REAL NOT NULL,
      lon1 REAL NOT NULL,
      lat2 REAL NOT NULL,
      lon2 REAL NOT NULL,
      bearing_deg REAL NOT NULL,
      min_lat REAL NOT NULL,
      max_lat REAL NOT NULL,
      min_lon REAL NOT NULL,
      max_lon REAL NOT NULL
    )
  """)
  conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS roads_rtree
    USING rtree(id, min_lat, max_lat, min_lon, max_lon)
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_nodes (
      id INTEGER PRIMARY KEY,
      node_key TEXT NOT NULL UNIQUE,
      lat REAL NOT NULL,
      lon REAL NOT NULL
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_edges (
      road_id INTEGER PRIMARY KEY,
      start_node_id INTEGER NOT NULL,
      end_node_id INTEGER NOT NULL
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_adjacency (
      from_road_id INTEGER NOT NULL,
      to_road_id INTEGER NOT NULL,
      turn_angle_deg REAL NOT NULL,
      PRIMARY KEY(from_road_id, to_road_id)
    )
  """)
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_name ON roads(name)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_ref ON roads(ref)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_highway ON roads(highway)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_road_edges_start_node ON road_edges(start_node_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_road_edges_end_node ON road_edges(end_node_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_road_adjacency_to ON road_adjacency(to_road_id)")
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("version", "1"))


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


def insert_road_segments(
  conn: sqlite3.Connection,
  rows: Iterable[dict[str, object]],
  batch_size: int = 20000,
  replace: bool = True,
) -> int:
  init_db(conn)
  if replace:
    conn.execute("DELETE FROM roads")
    conn.execute("DELETE FROM roads_rtree")

  count = 0
  batch: list[tuple[object, ...]] = []
  for row in rows:
    lat1 = float(row["lat1"])
    lon1 = float(row["lon1"])
    lat2 = float(row["lat2"])
    lon2 = float(row["lon2"])
    min_lat = min(lat1, lat2)
    max_lat = max(lat1, lat2)
    min_lon = min(lon1, lon2)
    max_lon = max(lon1, lon2)
    batch.append((
      int(row["osm_id"]),
      str(row.get("name", "") or ""),
      str(row.get("ref", "") or ""),
      str(row.get("highway", "") or ""),
      str(row.get("road_class", "") or ""),
      int(row.get("oneway", 0) or 0),
      lat1,
      lon1,
      lat2,
      lon2,
      road_bearing_deg(lat1, lon1, lat2, lon2),
      min_lat,
      max_lat,
      min_lon,
      max_lon,
    ))
    if len(batch) >= batch_size:
      count += _flush_segments(conn, batch)
      batch.clear()

  count += _flush_segments(conn, batch)
  if replace:
    build_road_graph(conn)
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("segment_count", str(count)))
  return count


def _flush_segments(conn: sqlite3.Connection, batch: list[tuple[object, ...]]) -> int:
  if not batch:
    return 0
  cursor = conn.executemany("""
    INSERT INTO roads(
      osm_id, name, ref, highway, road_class, oneway,
      lat1, lon1, lat2, lon2, bearing_deg,
      min_lat, max_lat, min_lon, max_lon
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  """, batch)
  first_id = cursor.lastrowid - len(batch) + 1 if cursor.lastrowid else None
  if first_id is None:
    ids = [row[0] for row in conn.execute("SELECT id FROM roads ORDER BY id DESC LIMIT ?", (len(batch),))]
    ids.reverse()
  else:
    ids = range(first_id, first_id + len(batch))
  conn.executemany(
    "INSERT INTO roads_rtree(id, min_lat, max_lat, min_lon, max_lon) VALUES (?, ?, ?, ?, ?)",
    ((road_id, row[11], row[12], row[13], row[14]) for road_id, row in zip(ids, batch, strict=False)),
  )
  return len(batch)


def _directed_bearing(bearing_deg: float, reverse: bool) -> float:
  return (bearing_deg + 180.0) % 360.0 if reverse else bearing_deg % 360.0


def _turn_angle_deg(from_bearing_deg: float, to_bearing_deg: float) -> float:
  return abs((to_bearing_deg - from_bearing_deg + 180.0) % 360.0 - 180.0)


def _road_traversals(road_id: int, start_node_id: int, end_node_id: int, bearing_deg: float, oneway: int) -> list[tuple[int, int, int, float]]:
  if oneway > 0:
    return [(road_id, start_node_id, end_node_id, _directed_bearing(bearing_deg, False))]
  if oneway < 0:
    return [(road_id, end_node_id, start_node_id, _directed_bearing(bearing_deg, True))]
  return [
    (road_id, start_node_id, end_node_id, _directed_bearing(bearing_deg, False)),
    (road_id, end_node_id, start_node_id, _directed_bearing(bearing_deg, True)),
  ]


def build_road_graph(conn: sqlite3.Connection) -> RoadGraphStats:
  init_db(conn)
  conn.execute("DELETE FROM road_adjacency")
  conn.execute("DELETE FROM road_edges")
  conn.execute("DELETE FROM road_nodes")

  old_row_factory = conn.row_factory
  conn.row_factory = sqlite3.Row
  try:
    road_rows = conn.execute("""
      SELECT id, osm_id, name, ref, highway, road_class, oneway,
             lat1, lon1, lat2, lon2, bearing_deg,
             0.0 AS distance_m
      FROM roads
      ORDER BY id
    """).fetchall()

    node_coords: dict[str, tuple[float, float]] = {}
    for row in road_rows:
      node_coords.setdefault(_road_node_key(float(row["lat1"]), float(row["lon1"])), (float(row["lat1"]), float(row["lon1"])))
      node_coords.setdefault(_road_node_key(float(row["lat2"]), float(row["lon2"])), (float(row["lat2"]), float(row["lon2"])))

    conn.executemany(
      "INSERT INTO road_nodes(node_key, lat, lon) VALUES (?, ?, ?)",
      ((node_key, lat, lon) for node_key, (lat, lon) in node_coords.items()),
    )
    node_ids = {
      str(row["node_key"]): int(row["id"])
      for row in conn.execute("SELECT id, node_key FROM road_nodes")
    }

    edge_rows: list[tuple[int, int, int]] = []
    traversals: list[tuple[int, int, int, float]] = []
    for row in road_rows:
      road_id = int(row["id"])
      start_node_id = node_ids[_road_node_key(float(row["lat1"]), float(row["lon1"]))]
      end_node_id = node_ids[_road_node_key(float(row["lat2"]), float(row["lon2"]))]
      edge_rows.append((road_id, start_node_id, end_node_id))
      traversals.extend(_road_traversals(road_id, start_node_id, end_node_id, float(row["bearing_deg"]), int(row["oneway"])))

    conn.executemany(
      "INSERT INTO road_edges(road_id, start_node_id, end_node_id) VALUES (?, ?, ?)",
      edge_rows,
    )

    outgoing_by_node: dict[int, list[tuple[int, int, int, float]]] = {}
    for traversal in traversals:
      outgoing_by_node.setdefault(traversal[1], []).append(traversal)

    adjacency: dict[tuple[int, int], float] = {}
    for from_road_id, _from_node_id, to_node_id, from_bearing_deg in traversals:
      for to_road_id, _next_from_node_id, _next_to_node_id, to_bearing_deg in outgoing_by_node.get(to_node_id, []):
        if from_road_id == to_road_id:
          continue
        key = (from_road_id, to_road_id)
        turn_angle = _turn_angle_deg(from_bearing_deg, to_bearing_deg)
        if key not in adjacency or turn_angle < adjacency[key]:
          adjacency[key] = turn_angle

    conn.executemany(
      "INSERT INTO road_adjacency(from_road_id, to_road_id, turn_angle_deg) VALUES (?, ?, ?)",
      ((from_road_id, to_road_id, turn_angle) for (from_road_id, to_road_id), turn_angle in adjacency.items()),
    )
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_node_count", str(len(node_ids))))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_edge_count", str(len(edge_rows))))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_adjacency_count", str(len(adjacency))))

    return RoadGraphStats(len(node_ids), len(edge_rows), len(adjacency))
  finally:
    conn.row_factory = old_row_factory


def road_successors(db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH, road_id: int = 0, limit: int = 32) -> list[OSMRoadTransition]:
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

  return [
    OSMRoadTransition(_row_to_segment(row), float(row["turn_angle_deg"]))
    for row in rows
  ]


def find_current_road(
  db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH,
  lat: float = 0.0,
  lon: float = 0.0,
  heading_deg: float | None = 0.0,
  radius_m: float = DEFAULT_LOOKUP_RADIUS_M,
  previous_name: str = "",
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

    heading_diff = 0.0
    if heading_deg is not None:
      heading_diff = bidirectional_heading_diff_deg(row["bearing_deg"], heading_deg)
      if heading_diff > MAX_HEADING_DIFF_DEG:
        continue

    name = str(row["name"] or "")
    ref = str(row["ref"] or "")
    name_bonus = -8.0 if road_name_matches(previous_name, name, ref) else 0.0
    highway_bonus = -4.0 if str(row["highway"] or "") in ("motorway", "trunk", "primary") else 0.0
    score = distance_m + heading_diff * 0.8 + name_bonus + highway_bonus
    match = OSMRoadMatch(
      road_id=int(row["id"]),
      osm_id=int(row["osm_id"]),
      name=name,
      ref=ref,
      highway=str(row["highway"] or ""),
      road_class=str(row["road_class"] or ""),
      oneway=int(row["oneway"]),
      distance_m=distance_m,
      heading_diff_deg=heading_diff,
      bearing_deg=float(row["bearing_deg"]),
      score=score,
    )
    if best is None or match.score < best.score:
      best = match

  return best


def nearby_road_segments(
  db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH,
  lat: float = 0.0,
  lon: float = 0.0,
  radius_m: float = 140.0,
  limit: int = 90,
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

  segments: list[OSMRoadSegment] = []
  for row in rows:
    distance_m = _distance_point_to_segment_m(lat, lon, row["lat1"], row["lon1"], row["lat2"], row["lon2"])
    if distance_m > radius_m:
      continue
    segments.append(OSMRoadSegment(
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
      distance_m=distance_m,
    ))

  segments.sort(key=lambda segment: segment.distance_m)
  return segments[:max(0, limit)]


def forward_road_segments(
  db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH,
  lat: float = 0.0,
  lon: float = 0.0,
  heading_deg: float = 0.0,
  forward_start_m: float = -30.0,
  forward_end_m: float = 1500.0,
  side_limit_m: float = 70.0,
  major_side_limit_m: float = 140.0,
  limit: int = 1000,
) -> list[OSMRoadSegment]:
  if not _db_source_exists(db_path) or forward_end_m <= forward_start_m:
    return []

  max_side_m = max(side_limit_m, major_side_limit_m)
  lat_min, lat_max, lon_min, lon_max = _corridor_bounding_box(
    lat, lon, heading_deg, forward_start_m, forward_end_m, max_side_m
  )
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

  segments_with_sort_key: list[tuple[float, float, OSMRoadSegment]] = []
  for row in rows:
    x1, y1 = latlon_to_car_space_m(lat, lon, heading_deg, row["lat1"], row["lon1"])
    x2, y2 = latlon_to_car_space_m(lat, lon, heading_deg, row["lat2"], row["lon2"])
    highway = str(row["highway"] or "")
    row_side_limit_m = major_side_limit_m if highway in MAJOR_HIGHWAYS else side_limit_m
    if not _segment_intersects_rect(x1, y1, x2, y2, forward_start_m, forward_end_m, -row_side_limit_m, row_side_limit_m):
      continue

    distance_m = _point_to_segment_distance_xy(0.0, 0.0, x1, y1, x2, y2)
    sort_forward_m = max(0.0, min(x1, x2))
    segments_with_sort_key.append((sort_forward_m, distance_m, OSMRoadSegment(
      road_id=int(row["id"]),
      osm_id=int(row["osm_id"]),
      name=str(row["name"] or ""),
      ref=str(row["ref"] or ""),
      highway=highway,
      road_class=str(row["road_class"] or ""),
      oneway=int(row["oneway"]),
      lat1=float(row["lat1"]),
      lon1=float(row["lon1"]),
      lat2=float(row["lat2"]),
      lon2=float(row["lon2"]),
      bearing_deg=float(row["bearing_deg"]),
      distance_m=distance_m,
    )))

  segments_with_sort_key.sort(key=lambda item: (item[0], item[1]))
  return [segment for _, _, segment in segments_with_sort_key[:max(0, limit)]]
