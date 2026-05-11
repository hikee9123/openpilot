#!/usr/bin/env python3
import json
import math
import os
import re
import sqlite3
import time
import zlib
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
OSM_STRUCTURE_TAGS = ("tunnel", "layer", "covered", "bridge")

ROAD_EXTRA_COLUMNS: tuple[tuple[str, str, object], ...] = (
  ("tunnel", "TEXT NOT NULL DEFAULT ''", ""),
  ("layer", "TEXT NOT NULL DEFAULT ''", ""),
  ("layer_int", "INTEGER NOT NULL DEFAULT 0", 0),
  ("covered", "TEXT NOT NULL DEFAULT ''", ""),
  ("bridge", "TEXT NOT NULL DEFAULT ''", ""),
  ("junction", "TEXT NOT NULL DEFAULT ''", ""),
  ("destination", "TEXT NOT NULL DEFAULT ''", ""),
  ("destination_ref", "TEXT NOT NULL DEFAULT ''", ""),
  ("destination_forward", "TEXT NOT NULL DEFAULT ''", ""),
  ("destination_backward", "TEXT NOT NULL DEFAULT ''", ""),
  ("destination_ref_forward", "TEXT NOT NULL DEFAULT ''", ""),
  ("destination_ref_backward", "TEXT NOT NULL DEFAULT ''", ""),
  ("lanes", "TEXT NOT NULL DEFAULT ''", ""),
  ("lane_count", "INTEGER NOT NULL DEFAULT 0", 0),
  ("turn_lanes", "TEXT NOT NULL DEFAULT ''", ""),
  ("turn_lanes_forward", "TEXT NOT NULL DEFAULT ''", ""),
  ("turn_lanes_backward", "TEXT NOT NULL DEFAULT ''", ""),
  ("destination_lanes", "TEXT NOT NULL DEFAULT ''", ""),
  ("maxspeed", "TEXT NOT NULL DEFAULT ''", ""),
  ("access", "TEXT NOT NULL DEFAULT ''", ""),
  ("motor_vehicle", "TEXT NOT NULL DEFAULT ''", ""),
  ("vehicle", "TEXT NOT NULL DEFAULT ''", ""),
  ("service", "TEXT NOT NULL DEFAULT ''", ""),
  ("route_ref", "TEXT NOT NULL DEFAULT ''", ""),
  ("int_ref", "TEXT NOT NULL DEFAULT ''", ""),
  ("placement", "TEXT NOT NULL DEFAULT ''", ""),
  ("change_lanes", "TEXT NOT NULL DEFAULT ''", ""),
  ("name_ko", "TEXT NOT NULL DEFAULT ''", ""),
  ("name_en", "TEXT NOT NULL DEFAULT ''", ""),
  ("motorway_link", "INTEGER NOT NULL DEFAULT 0", 0),
  ("is_ramp", "INTEGER NOT NULL DEFAULT 0", 0),
  ("road_priority", "INTEGER NOT NULL DEFAULT 0", 0),
  ("route_level", "INTEGER NOT NULL DEFAULT 0", 0),
  ("ramp_type", "TEXT NOT NULL DEFAULT ''", ""),
  ("bearing_in", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("bearing_out", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("curvature_avg", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("curvature_max", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("segment_length", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("geometry_polyline", "TEXT NOT NULL DEFAULT ''", ""),
  ("parallel_group_id", "INTEGER NOT NULL DEFAULT 0", 0),
  ("route_group_id", "INTEGER NOT NULL DEFAULT 0", 0),
  ("parallel_overlap_score", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("continuity_hint", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("continuity_class", "TEXT NOT NULL DEFAULT ''", ""),
  ("split_angle", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("merge_angle", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("direction_confidence", "REAL NOT NULL DEFAULT 1.0", 1.0),
  ("geometry_node_count", "INTEGER NOT NULL DEFAULT 0", 0),
  ("geometry_density", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("gps_shadow_zone", "INTEGER NOT NULL DEFAULT 0", 0),
  ("gps_confidence_penalty", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("tunnel_transition", "INTEGER NOT NULL DEFAULT 0", 0),
  ("lane_delta", "INTEGER NOT NULL DEFAULT 0", 0),
  ("future_heading_min", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("future_heading_max", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("road_width", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("estimated_width", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("ambiguity_score", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("sensor_difficult_zone", "INTEGER NOT NULL DEFAULT 0", 0),
  ("map_confidence", "REAL NOT NULL DEFAULT 1.0", 1.0),
  ("future_corridor_polyline", "TEXT NOT NULL DEFAULT ''", ""),
  ("next_500m_topology", "TEXT NOT NULL DEFAULT ''", ""),
  ("next_1km_topology", "TEXT NOT NULL DEFAULT ''", ""),
  ("ic_complexity", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("topology_density", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("main_flow_bias", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("ramp_bias", "REAL NOT NULL DEFAULT 0.0", 0.0),
  ("exit_bias", "REAL NOT NULL DEFAULT 0.0", 0.0),
)
ROAD_EXTRA_COLUMN_DEFS = {name: definition for name, definition, _default in ROAD_EXTRA_COLUMNS}
ROAD_EXTRA_DEFAULTS = {name: default for name, _definition, default in ROAD_EXTRA_COLUMNS}
ROAD_INT_COLUMNS = {name for name, definition, _default in ROAD_EXTRA_COLUMNS if definition.startswith("INTEGER")}
ROAD_REAL_COLUMNS = {name for name, definition, _default in ROAD_EXTRA_COLUMNS if definition.startswith("REAL")}
ROAD_INSERT_COLUMNS = (
  "osm_id", "name", "ref", "highway", "road_class", "oneway",
  "lat1", "lon1", "lat2", "lon2", "bearing_deg",
  "min_lat", "max_lat", "min_lon", "max_lon",
  *tuple(name for name, _definition, _default in ROAD_EXTRA_COLUMNS),
)

ROAD_NODES_EXTRA_COLUMNS = {
  "layer_int": "INTEGER NOT NULL DEFAULT 0",
  "node_degree": "INTEGER NOT NULL DEFAULT 0",
}
ROAD_EDGES_EXTRA_COLUMNS = {
  "start_node_key": "TEXT NOT NULL DEFAULT ''",
  "end_node_key": "TEXT NOT NULL DEFAULT ''",
  "layer_int": "INTEGER NOT NULL DEFAULT 0",
}
ROAD_ADJACENCY_EXTRA_COLUMNS = {
  "blocked_transition": "INTEGER NOT NULL DEFAULT 0",
  "transition_cost": "REAL NOT NULL DEFAULT 0.0",
  "transition_probability": "REAL NOT NULL DEFAULT 0.0",
  "historical_flow_weight": "REAL NOT NULL DEFAULT 0.0",
  "preferred_transition_score": "REAL NOT NULL DEFAULT 0.0",
  "flow_probability": "REAL NOT NULL DEFAULT 0.0",
  "connectivity_confidence": "REAL NOT NULL DEFAULT 1.0",
  "preferred_successor_id": "INTEGER NOT NULL DEFAULT 0",
  "secondary_successor_id": "INTEGER NOT NULL DEFAULT 0",
}

RAMP_HIGHWAYS = {"motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
ROAD_PRIORITY = {
  "motorway": 100,
  "motorway_link": 95,
  "trunk": 90,
  "trunk_link": 85,
  "primary": 80,
  "primary_link": 75,
  "secondary": 70,
  "secondary_link": 65,
  "tertiary": 60,
  "tertiary_link": 55,
  "unclassified": 40,
  "residential": 30,
  "living_street": 20,
  "service": 10,
}

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
  tunnel: str = ""
  layer: str = ""
  covered: str = ""
  bridge: str = ""
  destination: str = ""
  destination_ref: str = ""
  access: str = ""
  motor_vehicle: str = ""
  vehicle: str = ""
  service: str = ""
  layer_int: int = 0
  is_ramp: int = 0
  road_priority: int = 0
  route_level: int = 0
  ramp_type: str = ""
  segment_length: float = 0.0
  gps_confidence_penalty: float = 0.0
  sensor_difficult_zone: int = 0
  map_confidence: float = 1.0

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
  tunnel: str = ""
  layer: str = ""
  covered: str = ""
  bridge: str = ""
  destination: str = ""
  destination_ref: str = ""
  access: str = ""
  motor_vehicle: str = ""
  vehicle: str = ""
  service: str = ""
  layer_int: int = 0
  is_ramp: int = 0
  road_priority: int = 0
  route_level: int = 0
  ramp_type: str = ""
  segment_length: float = 0.0
  geometry_polyline: str = ""
  gps_confidence_penalty: float = 0.0
  sensor_difficult_zone: int = 0
  map_confidence: float = 1.0

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


def road_segment_length_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  mean_lat = (lat1 + lat2) * 0.5
  return math.hypot((lat2 - lat1) * METERS_PER_DEG_LAT, (lon2 - lon1) * _lon_scale(mean_lat))


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


def _parse_int(value: object, default: int = 0) -> int:
  if value is None:
    return default
  try:
    return int(float(str(value).strip()))
  except (TypeError, ValueError):
    return default


def _parse_float(value: object, default: float = 0.0) -> float:
  if value is None:
    return default
  text = str(value).strip().lower().replace(",", ".")
  if not text:
    return default
  match = re.search(r"-?\d+(?:\.\d+)?", text)
  if match is None:
    return default
  try:
    return float(match.group(0))
  except ValueError:
    return default


def lane_count_from_tag(value: object) -> int:
  text = str(value or "")
  counts = [_parse_int(match.group(0), 0) for match in re.finditer(r"\d+", text)]
  return max(counts, default=0)


def road_priority_for_highway(highway: str) -> int:
  return ROAD_PRIORITY.get(str(highway or ""), 0)


def route_level_for_tags(highway: str, ref: str = "", route_ref: str = "", int_ref: str = "") -> int:
  highway = str(highway or "")
  refs = " ".join(value for value in (ref, route_ref, int_ref) if value).upper()
  if highway in ("motorway", "motorway_link") or re.search(r"\bE\d+", refs):
    return 5
  if highway in ("trunk", "trunk_link") or re.search(r"\b(?:AH|NH|N)\d+", refs):
    return 4
  if highway in ("primary", "primary_link"):
    return 3
  if highway in ("secondary", "secondary_link", "tertiary", "tertiary_link"):
    return 2
  if highway in ("residential", "living_street"):
    return 1
  return 0


def infer_layer_int(layer: object, tunnel: object = "", bridge: object = "", covered: object = "") -> int:
  parsed = _parse_int(layer, 0)
  if parsed != 0 or str(layer or "").strip() in ("0", "+0", "-0"):
    return parsed

  tunnel_text = str(tunnel or "").strip().lower()
  covered_text = str(covered or "").strip().lower()
  bridge_text = str(bridge or "").strip().lower()
  if bridge_text and bridge_text not in ("no", "false", "0"):
    return 1
  if tunnel_text and tunnel_text not in ("no", "false", "0"):
    return -1
  if covered_text and covered_text not in ("no", "false", "0"):
    return -1
  return 0


def estimate_road_width_m(width: object, lane_count: int) -> tuple[float, float]:
  road_width = _parse_float(width, 0.0)
  estimated_width = road_width if road_width > 0.0 else max(0.0, float(lane_count) * 3.5)
  return road_width, estimated_width


def stable_group_id(*values: object) -> int:
  key = "|".join(str(value or "").strip().upper() for value in values if str(value or "").strip())
  if not key:
    return 0
  return zlib.crc32(key.encode("utf-8")) & 0x7fffffff


def encode_polyline(points: Iterable[tuple[float, float]]) -> str:
  result: list[str] = []
  last_lat = 0
  last_lon = 0

  def encode_value(value: int) -> None:
    value = ~(value << 1) if value < 0 else value << 1
    while value >= 0x20:
      result.append(chr((0x20 | (value & 0x1f)) + 63))
      value >>= 5
    result.append(chr(value + 63))

  for lat, lon in points:
    lat_i = int(round(float(lat) * 1e5))
    lon_i = int(round(float(lon) * 1e5))
    encode_value(lat_i - last_lat)
    encode_value(lon_i - last_lon)
    last_lat = lat_i
    last_lon = lon_i
  return "".join(result)


def polyline_geometry_metrics(points: list[tuple[float, float]]) -> dict[str, float | int | str]:
  if len(points) < 2:
    return {
      "bearing_in": 0.0,
      "bearing_out": 0.0,
      "curvature_avg": 0.0,
      "curvature_max": 0.0,
      "geometry_node_count": len(points),
      "geometry_density": 0.0,
      "future_heading_min": 0.0,
      "future_heading_max": 0.0,
      "geometry_polyline": encode_polyline(points),
      "geometry_length": 0.0,
    }

  bearings: list[float] = []
  lengths: list[float] = []
  for (lat1, lon1), (lat2, lon2) in zip(points, points[1:], strict=False):
    if lat1 == lat2 and lon1 == lon2:
      continue
    bearings.append(road_bearing_deg(lat1, lon1, lat2, lon2))
    lengths.append(road_segment_length_m(lat1, lon1, lat2, lon2))

  if not bearings:
    return {
      "bearing_in": 0.0,
      "bearing_out": 0.0,
      "curvature_avg": 0.0,
      "curvature_max": 0.0,
      "geometry_node_count": len(points),
      "geometry_density": 0.0,
      "future_heading_min": 0.0,
      "future_heading_max": 0.0,
      "geometry_polyline": encode_polyline(points),
      "geometry_length": 0.0,
    }

  turns = [angle_diff_deg(prev_bearing, next_bearing) for prev_bearing, next_bearing in zip(bearings, bearings[1:], strict=False)]
  total_length = sum(lengths)
  curvature_avg = sum(turns) / max(total_length, 1.0)
  curvature_max = max((turn / max(length, 1.0) for turn, length in zip(turns, lengths[1:], strict=False)), default=0.0)
  unwrapped = [bearings[0]]
  for bearing in bearings[1:]:
    prev = unwrapped[-1]
    delta = (bearing - prev + 180.0) % 360.0 - 180.0
    unwrapped.append(prev + delta)
  return {
    "bearing_in": bearings[0],
    "bearing_out": bearings[-1],
    "curvature_avg": curvature_avg,
    "curvature_max": curvature_max,
    "geometry_node_count": len(points),
    "geometry_density": len(points) / max(total_length / 1000.0, 0.001),
    "future_heading_min": min(unwrapped) % 360.0,
    "future_heading_max": max(unwrapped) % 360.0,
    "geometry_polyline": encode_polyline(points),
    "geometry_length": total_length,
  }


def infer_ramp_type(highway: str, destination: str = "", destination_ref: str = "", junction: str = "",
                    curvature_avg: float = 0.0, curvature_max: float = 0.0, name: str = "") -> str:
  if highway not in RAMP_HIGHWAYS:
    return ""
  text = " ".join((destination, destination_ref, junction, name)).strip().lower()
  if any(keyword in text for keyword in ("collector", "collector-distributor", "c-d")):
    return "collector"
  if "distributor" in text:
    return "distributor"
  if curvature_avg > 0.45 or curvature_max > 1.4:
    return "loop"
  if destination or destination_ref:
    return "exit"
  return "connector"


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


def _road_node_key(lat: float, lon: float, layer_int: int = 0) -> str:
  return f"{int(layer_int)}:{lat:.7f},{lon:.7f}"


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
    tunnel=_row_text(row, "tunnel"),
    layer=_row_text(row, "layer"),
    covered=_row_text(row, "covered"),
    bridge=_row_text(row, "bridge"),
    destination=_row_text(row, "destination"),
    destination_ref=_row_text(row, "destination_ref"),
    access=_row_text(row, "access"),
    motor_vehicle=_row_text(row, "motor_vehicle"),
    vehicle=_row_text(row, "vehicle"),
    service=_row_text(row, "service"),
    layer_int=_row_int(row, "layer_int"),
    is_ramp=_row_int(row, "is_ramp"),
    road_priority=_row_int(row, "road_priority"),
    route_level=_row_int(row, "route_level"),
    ramp_type=_row_text(row, "ramp_type"),
    segment_length=_row_float(row, "segment_length"),
    geometry_polyline=_row_text(row, "geometry_polyline"),
    gps_confidence_penalty=_row_float(row, "gps_confidence_penalty"),
    sensor_difficult_zone=_row_int(row, "sensor_difficult_zone"),
    map_confidence=_row_float(row, "map_confidence", 1.0),
  )


def _row_text(row, key: str) -> str:
  if key not in row.keys():
    return ""
  return str(row[key] or "")


def _row_int(row, key: str, default: int = 0) -> int:
  if key not in row.keys():
    return default
  return _parse_int(row[key], default)


def _row_float(row, key: str, default: float = 0.0) -> float:
  if key not in row.keys():
    return default
  return _parse_float(row[key], default)


def _ensure_columns(conn: sqlite3.Connection, table: str, column_defs: dict[str, str]) -> None:
  if not _table_exists(conn, table):
    return
  columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
  for column, definition in column_defs.items():
    if column not in columns:
      conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_road_tag_columns(conn: sqlite3.Connection) -> None:
  _ensure_columns(conn, "roads", ROAD_EXTRA_COLUMN_DEFS)


def init_db(conn: sqlite3.Connection) -> None:
  road_extra_sql = ",\n      ".join(f"{name} {definition}" for name, definition, _default in ROAD_EXTRA_COLUMNS)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
  """)
  conn.execute(f"""
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
      max_lon REAL NOT NULL,
      {road_extra_sql}
    )
  """)
  _ensure_road_tag_columns(conn)
  conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS roads_rtree
    USING rtree(id, min_lat, max_lat, min_lon, max_lon)
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_nodes (
      id INTEGER PRIMARY KEY,
      node_key TEXT NOT NULL UNIQUE,
      lat REAL NOT NULL,
      lon REAL NOT NULL,
      layer_int INTEGER NOT NULL DEFAULT 0,
      node_degree INTEGER NOT NULL DEFAULT 0
    )
  """)
  _ensure_columns(conn, "road_nodes", ROAD_NODES_EXTRA_COLUMNS)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_edges (
      road_id INTEGER PRIMARY KEY,
      start_node_id INTEGER NOT NULL,
      end_node_id INTEGER NOT NULL,
      start_node_key TEXT NOT NULL DEFAULT '',
      end_node_key TEXT NOT NULL DEFAULT '',
      layer_int INTEGER NOT NULL DEFAULT 0
    )
  """)
  _ensure_columns(conn, "road_edges", ROAD_EDGES_EXTRA_COLUMNS)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_adjacency (
      from_road_id INTEGER NOT NULL,
      to_road_id INTEGER NOT NULL,
      turn_angle_deg REAL NOT NULL,
      blocked_transition INTEGER NOT NULL DEFAULT 0,
      transition_cost REAL NOT NULL DEFAULT 0.0,
      transition_probability REAL NOT NULL DEFAULT 0.0,
      historical_flow_weight REAL NOT NULL DEFAULT 0.0,
      preferred_transition_score REAL NOT NULL DEFAULT 0.0,
      flow_probability REAL NOT NULL DEFAULT 0.0,
      connectivity_confidence REAL NOT NULL DEFAULT 1.0,
      preferred_successor_id INTEGER NOT NULL DEFAULT 0,
      secondary_successor_id INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(from_road_id, to_road_id)
    )
  """)
  _ensure_columns(conn, "road_adjacency", ROAD_ADJACENCY_EXTRA_COLUMNS)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS turn_restrictions (
      id INTEGER PRIMARY KEY,
      relation_id INTEGER,
      from_osm_id INTEGER,
      via_osm_id INTEGER,
      to_osm_id INTEGER,
      from_node_id INTEGER,
      via_node_id INTEGER,
      to_node_id INTEGER,
      restriction TEXT NOT NULL DEFAULT ''
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS lane_connectivity (
      id INTEGER PRIMARY KEY,
      relation_id INTEGER,
      from_osm_id INTEGER,
      to_osm_id INTEGER,
      from_node_id INTEGER,
      to_node_id INTEGER,
      lanes TEXT NOT NULL DEFAULT ''
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS lane_graph (
      id INTEGER PRIMARY KEY,
      from_road_id INTEGER,
      to_road_id INTEGER,
      from_lane INTEGER,
      to_lane INTEGER,
      allowed INTEGER NOT NULL DEFAULT 1,
      preferred INTEGER NOT NULL DEFAULT 0
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS motorway_junctions (
      id INTEGER PRIMARY KEY,
      osm_id INTEGER,
      ref TEXT NOT NULL DEFAULT '',
      name TEXT NOT NULL DEFAULT '',
      exit_to TEXT NOT NULL DEFAULT '',
      lat REAL,
      lon REAL,
      elevation REAL NOT NULL DEFAULT 0.0
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_topology (
      id INTEGER PRIMARY KEY,
      from_road_id INTEGER,
      to_road_id INTEGER,
      topology_type TEXT NOT NULL DEFAULT '',
      topology_inferred INTEGER NOT NULL DEFAULT 0,
      inferred_reason TEXT NOT NULL DEFAULT ''
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS route_relations (
      id INTEGER PRIMARY KEY,
      relation_id INTEGER NOT NULL UNIQUE,
      route TEXT NOT NULL DEFAULT '',
      ref TEXT NOT NULL DEFAULT '',
      network TEXT NOT NULL DEFAULT '',
      name TEXT NOT NULL DEFAULT '',
      operator TEXT NOT NULL DEFAULT ''
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_route_members (
      id INTEGER PRIMARY KEY,
      relation_id INTEGER,
      osm_id INTEGER,
      role TEXT NOT NULL DEFAULT '',
      ref TEXT NOT NULL DEFAULT '',
      network TEXT NOT NULL DEFAULT '',
      route_level INTEGER NOT NULL DEFAULT 0
    )
  """)
  conn.execute("""
    CREATE TABLE IF NOT EXISTS road_continuity_cache (
      id INTEGER PRIMARY KEY,
      road_id INTEGER NOT NULL UNIQUE,
      preferred_successor_id INTEGER NOT NULL DEFAULT 0,
      secondary_successor_id INTEGER NOT NULL DEFAULT 0,
      motorway_continuity REAL NOT NULL DEFAULT 0.0,
      ramp_continuity REAL NOT NULL DEFAULT 0.0,
      destination_continuity REAL NOT NULL DEFAULT 0.0,
      route_continuity REAL NOT NULL DEFAULT 0.0,
      parallel_road_continuity REAL NOT NULL DEFAULT 0.0,
      collector_distributor_continuity REAL NOT NULL DEFAULT 0.0,
      continuity_class TEXT NOT NULL DEFAULT '',
      future_corridor_polyline TEXT NOT NULL DEFAULT '',
      next_500m_topology TEXT NOT NULL DEFAULT '',
      next_1km_topology TEXT NOT NULL DEFAULT ''
    )
  """)
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_name ON roads(name)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_ref ON roads(ref)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_osm_id ON roads(osm_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_highway ON roads(highway)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_layer_int ON roads(layer_int)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_route_group ON roads(route_group_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_roads_parallel_group ON roads(parallel_group_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_road_edges_start_node ON road_edges(start_node_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_road_edges_end_node ON road_edges(end_node_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_road_adjacency_to ON road_adjacency(to_road_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_turn_restrictions_from_to ON turn_restrictions(from_osm_id, to_osm_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_lane_connectivity_from_to ON lane_connectivity(from_osm_id, to_osm_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_lane_graph_from ON lane_graph(from_road_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_motorway_junctions_osm_id ON motorway_junctions(osm_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_road_topology_from ON road_topology(from_road_id)")
  conn.execute("CREATE INDEX IF NOT EXISTS idx_route_members_osm_id ON road_route_members(osm_id)")
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


def _bool_tag(value: object) -> bool:
  return str(value or "").strip().lower() not in ("", "no", "false", "0")


def _coerce_road_value(column: str, value: object) -> object:
  if column in ROAD_INT_COLUMNS:
    return _parse_int(value, int(ROAD_EXTRA_DEFAULTS.get(column, 0)))
  if column in ROAD_REAL_COLUMNS:
    return _parse_float(value, float(ROAD_EXTRA_DEFAULTS.get(column, 0.0)))
  return str(value or "")


def _road_access_penalty(row_values: dict[str, object]) -> float:
  penalty = 0.0
  if str(row_values.get("service", "")).lower() in ("parking_aisle", "driveway"):
    penalty += 0.25
  if str(row_values.get("access", "")).lower() == "private":
    penalty += 0.25
  if str(row_values.get("motor_vehicle", "")).lower() == "no":
    penalty += 0.35
  if str(row_values.get("vehicle", "")).lower() == "no":
    penalty += 0.35
  return penalty


def _base_continuity_class(row_values: dict[str, object]) -> str:
  ramp_type = str(row_values.get("ramp_type", "") or "")
  if ramp_type:
    return ramp_type
  highway = str(row_values.get("highway", "") or "")
  if highway in RAMP_HIGHWAYS:
    return "connector"
  if _parse_int(row_values.get("layer_int"), 0) < 0 or _bool_tag(row_values.get("tunnel")):
    return "tunnel"
  if _parse_int(row_values.get("layer_int"), 0) > 0 or _bool_tag(row_values.get("bridge")):
    return "elevated"
  return "main"


def _build_road_insert_values(row: dict[str, object]) -> tuple[object, ...]:
  lat1 = float(row["lat1"])
  lon1 = float(row["lon1"])
  lat2 = float(row["lat2"])
  lon2 = float(row["lon2"])
  bearing_deg = _parse_float(row.get("bearing_deg"), road_bearing_deg(lat1, lon1, lat2, lon2))
  segment_length = _parse_float(row.get("segment_length"), road_segment_length_m(lat1, lon1, lat2, lon2))
  highway = str(row.get("highway", "") or "")
  ref = str(row.get("ref", "") or "")
  route_ref = str(row.get("route_ref", "") or "")
  int_ref = str(row.get("int_ref", "") or "")

  row_values: dict[str, object] = {
    "osm_id": int(row["osm_id"]),
    "name": str(row.get("name", "") or ""),
    "ref": ref,
    "highway": highway,
    "road_class": str(row.get("road_class", "") or ""),
    "oneway": int(row.get("oneway", 0) or 0),
    "lat1": lat1,
    "lon1": lon1,
    "lat2": lat2,
    "lon2": lon2,
    "bearing_deg": bearing_deg,
    "min_lat": min(lat1, lat2),
    "max_lat": max(lat1, lat2),
    "min_lon": min(lon1, lon2),
    "max_lon": max(lon1, lon2),
  }

  for column, _definition, default in ROAD_EXTRA_COLUMNS:
    row_values[column] = row.get(column, default)

  row_values["lane_count"] = row.get("lane_count") or lane_count_from_tag(row_values.get("lanes", ""))
  row_values["layer_int"] = row.get("layer_int") if row.get("layer_int") is not None else infer_layer_int(
    row_values.get("layer"), row_values.get("tunnel"), row_values.get("bridge"), row_values.get("covered")
  )
  row_values["motorway_link"] = int(highway == "motorway_link")
  row_values["is_ramp"] = int(highway in RAMP_HIGHWAYS)
  row_values["road_priority"] = row.get("road_priority") or road_priority_for_highway(highway)
  row_values["route_level"] = row.get("route_level") or route_level_for_tags(highway, ref, route_ref, int_ref)
  row_values["bearing_in"] = row.get("bearing_in") if row.get("bearing_in") is not None else bearing_deg
  row_values["bearing_out"] = row.get("bearing_out") if row.get("bearing_out") is not None else bearing_deg
  row_values["segment_length"] = segment_length
  row_values["geometry_node_count"] = row.get("geometry_node_count") or 2
  row_values["geometry_density"] = row.get("geometry_density") or (1000.0 / max(segment_length, 1.0))
  row_values["future_heading_min"] = row.get("future_heading_min") if row.get("future_heading_min") is not None else bearing_deg
  row_values["future_heading_max"] = row.get("future_heading_max") if row.get("future_heading_max") is not None else bearing_deg

  road_width, estimated_width = estimate_road_width_m(row.get("road_width", row.get("width", 0.0)), int(row_values["lane_count"]))
  row_values["road_width"] = road_width
  row_values["estimated_width"] = row.get("estimated_width") or estimated_width

  if not row_values.get("ramp_type"):
    row_values["ramp_type"] = infer_ramp_type(
      highway,
      str(row_values.get("destination", "")),
      str(row_values.get("destination_ref", "")),
      str(row_values.get("junction", "")),
      _parse_float(row_values.get("curvature_avg")),
      _parse_float(row_values.get("curvature_max")),
      str(row_values.get("name", "")),
    )
  if not row_values.get("route_group_id"):
    row_values["route_group_id"] = stable_group_id(ref, route_ref, int_ref, row_values.get("name"), highway)
  if not row_values.get("parallel_group_id"):
    row_values["parallel_group_id"] = stable_group_id(ref, row_values.get("name"), highway, row_values.get("layer_int"))

  row_values["main_flow_bias"] = row.get("main_flow_bias") if row.get("main_flow_bias") is not None else (1.0 if highway not in RAMP_HIGHWAYS else 0.0)
  row_values["ramp_bias"] = row.get("ramp_bias") if row.get("ramp_bias") is not None else (1.0 if highway in RAMP_HIGHWAYS else 0.0)
  row_values["exit_bias"] = row.get("exit_bias") if row.get("exit_bias") is not None else (1.0 if str(row_values.get("ramp_type")) == "exit" else 0.0)
  row_values["continuity_class"] = row.get("continuity_class") or _base_continuity_class(row_values)

  structure_penalty = 0.0
  if _parse_int(row_values.get("layer_int"), 0) != 0:
    structure_penalty += 0.25
  if _bool_tag(row_values.get("tunnel")) or _bool_tag(row_values.get("covered")):
    structure_penalty += 0.35
  if _bool_tag(row_values.get("bridge")):
    structure_penalty += 0.2
  if highway in RAMP_HIGHWAYS:
    structure_penalty += 0.2
  if segment_length < 25.0:
    structure_penalty += 0.15
  access_penalty = _road_access_penalty(row_values)
  if not row_values.get("ambiguity_score"):
    row_values["ambiguity_score"] = min(1.0, structure_penalty + access_penalty)
  if not row_values.get("gps_shadow_zone"):
    row_values["gps_shadow_zone"] = int(_bool_tag(row_values.get("tunnel")) or _bool_tag(row_values.get("covered")) or abs(_parse_int(row_values.get("layer_int"), 0)) >= 2)
  if not row_values.get("gps_confidence_penalty"):
    row_values["gps_confidence_penalty"] = min(0.8, structure_penalty + access_penalty)
  if not row_values.get("sensor_difficult_zone"):
    row_values["sensor_difficult_zone"] = int(float(row_values["gps_confidence_penalty"]) >= 0.35)
  if not row_values.get("map_confidence") or float(row_values.get("map_confidence", 1.0)) == 1.0:
    row_values["map_confidence"] = max(0.1, 1.0 - float(row_values["gps_confidence_penalty"]))

  return tuple(
    _coerce_road_value(column, row_values[column]) if column in ROAD_EXTRA_DEFAULTS else row_values[column]
    for column in ROAD_INSERT_COLUMNS
  )


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
    batch.append(_build_road_insert_values(row))
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
  columns = ", ".join(ROAD_INSERT_COLUMNS)
  placeholders = ", ".join("?" for _column in ROAD_INSERT_COLUMNS)
  cursor = conn.executemany(f"INSERT INTO roads({columns}) VALUES ({placeholders})", batch)
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


def apply_osm_relation_hints(conn: sqlite3.Connection) -> None:
  init_db(conn)
  rows = conn.execute("""
    SELECT osm_id, ref, network, route_level
    FROM road_route_members
    WHERE osm_id IS NOT NULL AND osm_id != 0
    ORDER BY route_level DESC, id ASC
  """).fetchall()
  updates = [
    (str(row[1] or ""), str(row[1] or "") if str(row[2] or "").lower().startswith(("e-road", "international")) else "",
     int(row[3] or 0), int(row[3] or 0), int(row[0] or 0))
    for row in rows
  ]
  conn.executemany("""
    UPDATE roads
    SET route_ref = CASE WHEN route_ref = '' THEN ? ELSE route_ref END,
        int_ref = CASE WHEN int_ref = '' THEN ? ELSE int_ref END,
        route_level = CASE WHEN route_level < ? THEN ? ELSE route_level END
    WHERE osm_id = ?
  """, updates)


def _restriction_sets(conn: sqlite3.Connection) -> tuple[set[tuple[int, int]], dict[int, set[int]]]:
  blocked: set[tuple[int, int]] = set()
  only_allowed: dict[int, set[int]] = {}
  for row in conn.execute("SELECT from_osm_id, to_osm_id, restriction FROM turn_restrictions"):
    from_osm_id = int(row[0] or 0)
    to_osm_id = int(row[1] or 0)
    restriction = str(row[2] or "")
    if from_osm_id == 0 or to_osm_id == 0:
      continue
    if restriction.startswith("no_"):
      blocked.add((from_osm_id, to_osm_id))
    elif restriction.startswith("only_"):
      only_allowed.setdefault(from_osm_id, set()).add(to_osm_id)
  return blocked, only_allowed


def _transition_blocked(from_row, to_row, blocked_pairs: set[tuple[int, int]], only_allowed: dict[int, set[int]]) -> bool:
  from_osm_id = int(from_row["osm_id"] or 0)
  to_osm_id = int(to_row["osm_id"] or 0)
  if (from_osm_id, to_osm_id) in blocked_pairs:
    return True
  allowed_targets = only_allowed.get(from_osm_id)
  return allowed_targets is not None and to_osm_id not in allowed_targets


def _same_route_or_destination(from_row, to_row) -> bool:
  for key in ("osm_id", "ref", "route_ref", "int_ref", "destination", "destination_ref"):
    left = str(from_row[key] or "") if key != "osm_id" else str(int(from_row[key] or 0))
    right = str(to_row[key] or "") if key != "osm_id" else str(int(to_row[key] or 0))
    if left and left == right:
      return True
  return road_name_matches(str(from_row["name"] or ""), str(to_row["name"] or ""), str(to_row["ref"] or ""))


def _transition_cost(from_row, to_row, turn_angle: float, blocked: bool, explicit_connectivity: bool) -> tuple[float, float]:
  if blocked:
    return 1_000_000.0, 0.0
  cost = max(0.0, turn_angle)
  if int(from_row["osm_id"] or 0) == int(to_row["osm_id"] or 0):
    cost = max(0.0, cost - 35.0)
  elif _same_route_or_destination(from_row, to_row):
    cost = max(0.0, cost - 15.0)
  if int(to_row["is_ramp"] or 0):
    cost += 12.0
  if int(from_row["is_ramp"] or 0) and not int(to_row["is_ramp"] or 0):
    cost = max(0.0, cost - 8.0)
  if str(to_row["service"] or "").lower() in ("parking_aisle", "driveway"):
    cost += 80.0
  if str(to_row["access"] or "").lower() == "private" or str(to_row["motor_vehicle"] or "").lower() == "no" or str(to_row["vehicle"] or "").lower() == "no":
    cost += 100.0
  confidence = 1.0 if explicit_connectivity else 0.75
  if abs(int(from_row["layer_int"] or 0) - int(to_row["layer_int"] or 0)) > 0:
    confidence = min(confidence, 0.35)
  return cost, confidence


def _classify_topology(from_row, to_row, outgoing_count: int, incoming_count: int, turn_angle: float) -> tuple[str, str]:
  from_ramp = int(from_row["is_ramp"] or 0) != 0
  to_ramp = int(to_row["is_ramp"] or 0) != 0
  if not from_ramp and to_ramp:
    return "exit", "ramp_geometry_continuity"
  if from_ramp and not to_ramp:
    return "entrance", "ramp_geometry_continuity"
  if from_ramp and to_ramp:
    return "connector", "ramp_geometry_continuity"
  if outgoing_count > 1:
    return ("fork" if turn_angle > 20.0 else "split"), "geometry_split"
  if incoming_count > 1:
    return "merge", "geometry_merge"
  if _same_route_or_destination(from_row, to_row):
    return "connector", "same_ref_continuity"
  return "connector", "geometry_connectivity"


def _lane_connections(lanes: str, from_count: int, to_count: int) -> list[tuple[int, int]]:
  pairs: list[tuple[int, int]] = []
  for token in re.split(r"[|;]", str(lanes or "")):
    if ":" not in token:
      continue
    left, right = token.split(":", 1)
    from_lanes = [_parse_int(value, 0) for value in re.findall(r"\d+", left)]
    to_lanes = [_parse_int(value, 0) for value in re.findall(r"\d+", right)]
    for from_lane in from_lanes:
      for to_lane in to_lanes:
        if from_lane > 0 and to_lane > 0:
          pairs.append((from_lane, to_lane))
  if pairs:
    return sorted(set(pairs))
  max_lane = min(max(1, from_count), max(1, to_count))
  return [(lane, lane) for lane in range(1, max_lane + 1)]


def _topology_json(items: list[tuple[int, str, float]], limit: int) -> str:
  return json.dumps([
    {"to": to_road_id, "type": topology_type, "p": round(probability, 4)}
    for to_road_id, topology_type, probability in items[:limit]
  ], separators=(",", ":"))


def build_road_graph(conn: sqlite3.Connection) -> RoadGraphStats:
  init_db(conn)
  conn.execute("DELETE FROM road_adjacency")
  conn.execute("DELETE FROM road_edges")
  conn.execute("DELETE FROM road_nodes")
  conn.execute("DELETE FROM road_topology")
  conn.execute("DELETE FROM lane_graph")
  conn.execute("DELETE FROM road_continuity_cache")

  old_row_factory = conn.row_factory
  conn.row_factory = sqlite3.Row
  try:
    road_rows = conn.execute("""
      SELECT id, osm_id, name, ref, highway, road_class, oneway,
             lat1, lon1, lat2, lon2, bearing_deg,
             tunnel, layer, layer_int, covered, bridge, junction,
             destination, destination_ref, service, access, motor_vehicle, vehicle,
             motorway_link, is_ramp, road_priority, route_level, ramp_type,
             lane_count, route_ref, int_ref, geometry_polyline, segment_length,
             curvature_avg, curvature_max, parallel_group_id, route_group_id,
             ambiguity_score, sensor_difficult_zone,
             map_confidence, main_flow_bias, ramp_bias, exit_bias,
             0.0 AS distance_m
      FROM roads
      ORDER BY id
    """).fetchall()
    row_by_id = {int(row["id"]): row for row in road_rows}

    node_coords: dict[str, tuple[float, float, int]] = {}
    node_roads: dict[str, set[int]] = {}
    for row in road_rows:
      road_id = int(row["id"])
      layer_int = int(row["layer_int"] or 0)
      start_key = _road_node_key(float(row["lat1"]), float(row["lon1"]), layer_int)
      end_key = _road_node_key(float(row["lat2"]), float(row["lon2"]), layer_int)
      node_coords.setdefault(start_key, (float(row["lat1"]), float(row["lon1"]), layer_int))
      node_coords.setdefault(end_key, (float(row["lat2"]), float(row["lon2"]), layer_int))
      node_roads.setdefault(start_key, set()).add(road_id)
      node_roads.setdefault(end_key, set()).add(road_id)

    conn.executemany(
      "INSERT INTO road_nodes(node_key, lat, lon, layer_int, node_degree) VALUES (?, ?, ?, ?, ?)",
      (
        (node_key, lat, lon, layer_int, len(node_roads.get(node_key, set())))
        for node_key, (lat, lon, layer_int) in node_coords.items()
      ),
    )
    node_ids = {
      str(row["node_key"]): int(row["id"])
      for row in conn.execute("SELECT id, node_key FROM road_nodes")
    }

    edge_rows: list[tuple[int, int, int, str, str, int]] = []
    edge_by_road: dict[int, tuple[int, int]] = {}
    traversals: list[tuple[int, int, int, float]] = []
    for row in road_rows:
      road_id = int(row["id"])
      layer_int = int(row["layer_int"] or 0)
      start_key = _road_node_key(float(row["lat1"]), float(row["lon1"]), layer_int)
      end_key = _road_node_key(float(row["lat2"]), float(row["lon2"]), layer_int)
      start_node_id = node_ids[start_key]
      end_node_id = node_ids[end_key]
      edge_rows.append((road_id, start_node_id, end_node_id, start_key, end_key, layer_int))
      edge_by_road[road_id] = (start_node_id, end_node_id)
      traversals.extend(_road_traversals(road_id, start_node_id, end_node_id, float(row["bearing_deg"]), int(row["oneway"])))

    conn.executemany(
      "INSERT INTO road_edges(road_id, start_node_id, end_node_id, start_node_key, end_node_key, layer_int) VALUES (?, ?, ?, ?, ?, ?)",
      edge_rows,
    )

    outgoing_by_node: dict[int, list[tuple[int, int, int, float]]] = {}
    for traversal in traversals:
      outgoing_by_node.setdefault(traversal[1], []).append(traversal)

    adjacency: dict[tuple[int, int], float] = {}
    adjacency_via_node: dict[tuple[int, int], int] = {}
    for from_road_id, _from_node_id, to_node_id, from_bearing_deg in traversals:
      for to_road_id, _next_from_node_id, _next_to_node_id, to_bearing_deg in outgoing_by_node.get(to_node_id, []):
        if from_road_id == to_road_id:
          continue
        key = (from_road_id, to_road_id)
        turn_angle = _turn_angle_deg(from_bearing_deg, to_bearing_deg)
        if key not in adjacency or turn_angle < adjacency[key]:
          adjacency[key] = turn_angle
          adjacency_via_node[key] = to_node_id

    blocked_pairs, only_allowed = _restriction_sets(conn)
    explicit_connectivity_pairs = {
      (int(row[0] or 0), int(row[1] or 0))
      for row in conn.execute("SELECT from_osm_id, to_osm_id FROM lane_connectivity")
      if int(row[0] or 0) != 0 and int(row[1] or 0) != 0
    }

    adjacency_items: dict[tuple[int, int], dict[str, object]] = {}
    for (from_road_id, to_road_id), turn_angle in adjacency.items():
      from_row = row_by_id[from_road_id]
      to_row = row_by_id[to_road_id]
      blocked = _transition_blocked(from_row, to_row, blocked_pairs, only_allowed)
      explicit_connectivity = (int(from_row["osm_id"] or 0), int(to_row["osm_id"] or 0)) in explicit_connectivity_pairs
      transition_cost, connectivity_confidence = _transition_cost(from_row, to_row, turn_angle, blocked, explicit_connectivity)
      adjacency_items[(from_road_id, to_road_id)] = {
        "from_road_id": from_road_id,
        "to_road_id": to_road_id,
        "turn_angle": turn_angle,
        "blocked": blocked,
        "transition_cost": transition_cost,
        "connectivity_confidence": connectivity_confidence,
        "via_node_id": adjacency_via_node.get((from_road_id, to_road_id), 0),
      }

    outgoing_by_road: dict[int, list[dict[str, object]]] = {}
    incoming_by_road: dict[int, list[dict[str, object]]] = {}
    for item in adjacency_items.values():
      outgoing_by_road.setdefault(int(item["from_road_id"]), []).append(item)
      incoming_by_road.setdefault(int(item["to_road_id"]), []).append(item)

    nonblocked_out_count = {
      road_id: sum(1 for item in items if not bool(item["blocked"]))
      for road_id, items in outgoing_by_road.items()
    }
    nonblocked_in_count = {
      road_id: sum(1 for item in items if not bool(item["blocked"]))
      for road_id, items in incoming_by_road.items()
    }

    preferred_by_from: dict[int, tuple[int, int]] = {}
    probability_by_key: dict[tuple[int, int], float] = {}
    preferred_score_by_key: dict[tuple[int, int], float] = {}
    for from_road_id, items in outgoing_by_road.items():
      candidates = [item for item in items if not bool(item["blocked"])]
      candidates.sort(key=lambda item: (float(item["transition_cost"]), float(item["turn_angle"]), int(item["to_road_id"])))
      preferred_id = int(candidates[0]["to_road_id"]) if candidates else 0
      secondary_id = int(candidates[1]["to_road_id"]) if len(candidates) > 1 else 0
      preferred_by_from[from_road_id] = (preferred_id, secondary_id)
      weights = {
        int(item["to_road_id"]): 1.0 / (1.0 + max(0.0, float(item["transition_cost"])))
        for item in candidates
      }
      total_weight = sum(weights.values())
      for item in items:
        key = (from_road_id, int(item["to_road_id"]))
        probability = 0.0 if bool(item["blocked"]) or total_weight <= 0.0 else weights.get(int(item["to_road_id"]), 0.0) / total_weight
        probability_by_key[key] = probability
        preferred_score_by_key[key] = 0.0 if bool(item["blocked"]) else max(0.0, 1.0 - min(float(item["transition_cost"]), 200.0) / 200.0)

    topology_by_key: dict[tuple[int, int], tuple[str, str]] = {}
    adjacency_rows: list[tuple[object, ...]] = []
    topology_rows: list[tuple[object, ...]] = []
    for key, item in adjacency_items.items():
      from_road_id, to_road_id = key
      preferred_id, secondary_id = preferred_by_from.get(from_road_id, (0, 0))
      probability = probability_by_key.get(key, 0.0)
      topology_type, inferred_reason = _classify_topology(
        row_by_id[from_road_id],
        row_by_id[to_road_id],
        nonblocked_out_count.get(from_road_id, 0),
        nonblocked_in_count.get(to_road_id, 0),
        float(item["turn_angle"]),
      )
      topology_by_key[key] = (topology_type, inferred_reason)
      adjacency_rows.append((
        from_road_id,
        to_road_id,
        float(item["turn_angle"]),
        int(bool(item["blocked"])),
        float(item["transition_cost"]),
        probability,
        0.0,
        preferred_score_by_key.get(key, 0.0),
        probability,
        float(item["connectivity_confidence"]),
        preferred_id,
        secondary_id,
      ))
      topology_rows.append((from_road_id, to_road_id, topology_type, 1, inferred_reason))

    conn.executemany("""
      INSERT INTO road_adjacency(
        from_road_id, to_road_id, turn_angle_deg, blocked_transition,
        transition_cost, transition_probability, historical_flow_weight,
        preferred_transition_score, flow_probability, connectivity_confidence,
        preferred_successor_id, secondary_successor_id
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, adjacency_rows)
    conn.executemany("""
      INSERT INTO road_topology(
        from_road_id, to_road_id, topology_type, topology_inferred, inferred_reason
      ) VALUES (?, ?, ?, ?, ?)
    """, topology_rows)

    adjacency_keys_by_osm_pair: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for key in adjacency_items:
      from_row = row_by_id[key[0]]
      to_row = row_by_id[key[1]]
      adjacency_keys_by_osm_pair.setdefault((int(from_row["osm_id"] or 0), int(to_row["osm_id"] or 0)), []).append(key)

    lane_graph_rows: list[tuple[int, int, int, int, int, int]] = []
    lane_graph_seen: set[tuple[int, int, int, int]] = set()
    for key, item in adjacency_items.items():
      if bool(item["blocked"]):
        continue
      from_road_id, to_road_id = key
      preferred_id = preferred_by_from.get(from_road_id, (0, 0))[0]
      lane_graph_seen.add((from_road_id, to_road_id, 0, 0))
      lane_graph_rows.append((from_road_id, to_road_id, 0, 0, 1, int(to_road_id == preferred_id)))

    for relation_id, from_osm_id, to_osm_id, lanes in conn.execute("SELECT relation_id, from_osm_id, to_osm_id, lanes FROM lane_connectivity"):
      _ = relation_id
      for from_road_id, to_road_id in adjacency_keys_by_osm_pair.get((int(from_osm_id or 0), int(to_osm_id or 0)), []):
        from_count = int(row_by_id[from_road_id]["lane_count"] or 0)
        to_count = int(row_by_id[to_road_id]["lane_count"] or 0)
        preferred_id = preferred_by_from.get(from_road_id, (0, 0))[0]
        for from_lane, to_lane in _lane_connections(str(lanes or ""), from_count, to_count):
          lane_key = (from_road_id, to_road_id, from_lane, to_lane)
          if lane_key in lane_graph_seen:
            continue
          lane_graph_seen.add(lane_key)
          lane_graph_rows.append((from_road_id, to_road_id, from_lane, to_lane, 1, int(to_road_id == preferred_id and from_lane == to_lane)))
    conn.executemany("""
      INSERT INTO lane_graph(from_road_id, to_road_id, from_lane, to_lane, allowed, preferred)
      VALUES (?, ?, ?, ?, ?, ?)
    """, lane_graph_rows)

    road_updates: list[tuple[object, ...]] = []
    cache_rows: list[tuple[object, ...]] = []
    for row in road_rows:
      road_id = int(row["id"])
      outgoing = sorted(
        (item for item in outgoing_by_road.get(road_id, []) if not bool(item["blocked"])),
        key=lambda item: (float(item["transition_cost"]), float(item["turn_angle"]), int(item["to_road_id"])),
      )
      incoming = [item for item in incoming_by_road.get(road_id, []) if not bool(item["blocked"])]
      preferred_id, secondary_id = preferred_by_from.get(road_id, (0, 0))
      topology_items = [
        (int(item["to_road_id"]), topology_by_key.get((road_id, int(item["to_road_id"])), ("connector", ""))[0],
         probability_by_key.get((road_id, int(item["to_road_id"])), 0.0))
        for item in outgoing
      ]
      topology_json = _topology_json(topology_items, 12)
      split_angle = max((float(item["turn_angle"]) for item in outgoing), default=0.0) if len(outgoing) > 1 else 0.0
      merge_angle = max((float(item["turn_angle"]) for item in incoming), default=0.0) if len(incoming) > 1 else 0.0
      topology_density = float(len(outgoing) + len(incoming))
      structure_complexity = (
        topology_density +
        (1.5 if int(row["is_ramp"] or 0) else 0.0) +
        (1.0 if int(row["layer_int"] or 0) != 0 else 0.0) +
        (1.0 if _bool_tag(row["tunnel"]) or _bool_tag(row["covered"]) else 0.0) +
        (0.5 if _bool_tag(row["bridge"]) else 0.0)
      )
      ambiguity_score = min(1.0, max(float(row["ambiguity_score"] or 0.0), structure_complexity / 12.0))
      sensor_difficult_zone = int(bool(row["sensor_difficult_zone"]) or structure_complexity >= 4.0)
      map_confidence = max(0.1, min(float(row["map_confidence"] or 1.0), 1.0 - ambiguity_score * 0.5))
      continuity_hint = preferred_score_by_key.get((road_id, preferred_id), 0.0) if preferred_id else 0.0
      effective_ramp_type = str(row["ramp_type"] or "")
      if int(row["is_ramp"] or 0) and effective_ramp_type in ("", "connector"):
        if any(not int(row_by_id[int(item["to_road_id"])]["is_ramp"] or 0) for item in outgoing):
          effective_ramp_type = "entrance"
        elif any(not int(row_by_id[int(item["from_road_id"])]["is_ramp"] or 0) for item in incoming):
          effective_ramp_type = "exit"
      class_values = {key: row[key] for key in row.keys() if key in ROAD_EXTRA_DEFAULTS or key in ("highway",)}
      class_values["ramp_type"] = effective_ramp_type
      continuity_class = _base_continuity_class(class_values)
      if preferred_id:
        preferred_row = row_by_id[preferred_id]
        if _same_route_or_destination(row, preferred_row):
          continuity_class = "route"
      future_polyline = str(row["geometry_polyline"] or "")
      main_flow_bias = float(row["main_flow_bias"] or 0.0)
      ramp_bias = float(row["ramp_bias"] or 0.0)
      exit_bias = float(row["exit_bias"] or 0.0)
      if preferred_id and not int(row["is_ramp"] or 0):
        main_flow_bias = max(main_flow_bias, continuity_hint)
      if int(row["is_ramp"] or 0):
        ramp_bias = max(ramp_bias, continuity_hint)
      if effective_ramp_type == "exit":
        exit_bias = max(exit_bias, continuity_hint)

      road_updates.append((
        effective_ramp_type,
        continuity_hint,
        continuity_class,
        split_angle,
        merge_angle,
        structure_complexity,
        topology_density,
        ambiguity_score,
        sensor_difficult_zone,
        map_confidence,
        future_polyline,
        topology_json,
        topology_json,
        main_flow_bias,
        ramp_bias,
        exit_bias,
        road_id,
      ))
      preferred_row = row_by_id.get(preferred_id)
      same_route = 1.0 if preferred_row is not None and _same_route_or_destination(row, preferred_row) else 0.0
      cache_rows.append((
        road_id,
        preferred_id,
        secondary_id,
        same_route if str(row["highway"] or "") in ("motorway", "trunk", "primary") else 0.0,
        continuity_hint if int(row["is_ramp"] or 0) else 0.0,
        same_route if str(row["destination"] or "") or str(row["destination_ref"] or "") else 0.0,
        same_route,
        same_route if int(row["parallel_group_id"] or 0) else 0.0,
        continuity_hint if effective_ramp_type in ("collector", "distributor") else 0.0,
        continuity_class,
        future_polyline,
        topology_json,
        topology_json,
      ))

    conn.executemany("""
      UPDATE roads
      SET ramp_type = ?, continuity_hint = ?, continuity_class = ?, split_angle = ?, merge_angle = ?,
          ic_complexity = ?, topology_density = ?, ambiguity_score = ?,
          sensor_difficult_zone = ?, map_confidence = ?, future_corridor_polyline = ?,
          next_500m_topology = ?, next_1km_topology = ?,
          main_flow_bias = ?, ramp_bias = ?, exit_bias = ?
      WHERE id = ?
    """, road_updates)
    conn.executemany("""
      INSERT OR REPLACE INTO road_continuity_cache(
        road_id, preferred_successor_id, secondary_successor_id,
        motorway_continuity, ramp_continuity, destination_continuity, route_continuity,
        parallel_road_continuity, collector_distributor_continuity, continuity_class,
        future_corridor_polyline, next_500m_topology, next_1km_topology
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, cache_rows)

    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_node_count", str(len(node_ids))))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_edge_count", str(len(edge_rows))))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_adjacency_count", str(len(adjacency_rows))))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_topology_count", str(len(topology_rows))))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("lane_graph_count", str(len(lane_graph_rows))))

    return RoadGraphStats(len(node_ids), len(edge_rows), len(adjacency_rows))
  finally:
    conn.row_factory = old_row_factory


def road_successors(db_path: DbSource = DEFAULT_OSM_ROADS_DB_PATH, road_id: int = 0, limit: int = 32) -> list[OSMRoadTransition]:
  if not _db_source_exists(db_path):
    return []

  close_conn, conn = _connect_read_db(db_path)
  try:
    if not _table_exists(conn, "roads") or not _table_exists(conn, "road_adjacency"):
      return []
    adjacency_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(road_adjacency)")}
    blocked_filter = "AND road_adjacency.blocked_transition = 0" if "blocked_transition" in adjacency_columns else ""
    order_clause = "road_adjacency.transition_cost ASC, road_adjacency.turn_angle_deg ASC" if "transition_cost" in adjacency_columns else "road_adjacency.turn_angle_deg ASC"
    rows = conn.execute("""
      SELECT roads.*,
             0.0 AS distance_m,
             road_adjacency.turn_angle_deg
      FROM road_adjacency
      JOIN roads ON roads.id = road_adjacency.to_road_id
      WHERE road_adjacency.from_road_id = ?
        {blocked_filter}
      ORDER BY {order_clause}, roads.id ASC
      LIMIT ?
    """.format(blocked_filter=blocked_filter, order_clause=order_clause), (road_id, max(0, limit))).fetchall()
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
    access_penalty = 0.0
    if _row_text(row, "service").lower() in ("parking_aisle", "driveway"):
      access_penalty += 25.0
    if _row_text(row, "access").lower() == "private" or _row_text(row, "motor_vehicle").lower() == "no" or _row_text(row, "vehicle").lower() == "no":
      access_penalty += 35.0
    ramp_penalty = 8.0 if _row_int(row, "is_ramp") and not road_name_matches(previous_name, name, ref, _row_text(row, "destination"), _row_text(row, "destination_ref")) else 0.0
    confidence_penalty = _row_float(row, "gps_confidence_penalty") * 15.0 + (1.0 - _row_float(row, "map_confidence", 1.0)) * 12.0
    priority_bonus = -min(100, max(0, _row_int(row, "road_priority"))) * 0.03
    score = distance_m + heading_diff * 0.8 + name_bonus + highway_bonus + access_penalty + ramp_penalty + confidence_penalty + priority_bonus
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
      tunnel=_row_text(row, "tunnel"),
      layer=_row_text(row, "layer"),
      covered=_row_text(row, "covered"),
      bridge=_row_text(row, "bridge"),
      destination=_row_text(row, "destination"),
      destination_ref=_row_text(row, "destination_ref"),
      access=_row_text(row, "access"),
      motor_vehicle=_row_text(row, "motor_vehicle"),
      vehicle=_row_text(row, "vehicle"),
      service=_row_text(row, "service"),
      layer_int=_row_int(row, "layer_int"),
      is_ramp=_row_int(row, "is_ramp"),
      road_priority=_row_int(row, "road_priority"),
      route_level=_row_int(row, "route_level"),
      ramp_type=_row_text(row, "ramp_type"),
      segment_length=_row_float(row, "segment_length"),
      gps_confidence_penalty=_row_float(row, "gps_confidence_penalty"),
      sensor_difficult_zone=_row_int(row, "sensor_difficult_zone"),
      map_confidence=_row_float(row, "map_confidence", 1.0),
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
      tunnel=_row_text(row, "tunnel"),
      layer=_row_text(row, "layer"),
      covered=_row_text(row, "covered"),
      bridge=_row_text(row, "bridge"),
      destination=_row_text(row, "destination"),
      destination_ref=_row_text(row, "destination_ref"),
      access=_row_text(row, "access"),
      motor_vehicle=_row_text(row, "motor_vehicle"),
      vehicle=_row_text(row, "vehicle"),
      service=_row_text(row, "service"),
      layer_int=_row_int(row, "layer_int"),
      is_ramp=_row_int(row, "is_ramp"),
      road_priority=_row_int(row, "road_priority"),
      route_level=_row_int(row, "route_level"),
      ramp_type=_row_text(row, "ramp_type"),
      segment_length=_row_float(row, "segment_length"),
      geometry_polyline=_row_text(row, "geometry_polyline"),
      gps_confidence_penalty=_row_float(row, "gps_confidence_penalty"),
      sensor_difficult_zone=_row_int(row, "sensor_difficult_zone"),
      map_confidence=_row_float(row, "map_confidence", 1.0),
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
      tunnel=_row_text(row, "tunnel"),
      layer=_row_text(row, "layer"),
      covered=_row_text(row, "covered"),
      bridge=_row_text(row, "bridge"),
      destination=_row_text(row, "destination"),
      destination_ref=_row_text(row, "destination_ref"),
      access=_row_text(row, "access"),
      motor_vehicle=_row_text(row, "motor_vehicle"),
      vehicle=_row_text(row, "vehicle"),
      service=_row_text(row, "service"),
      layer_int=_row_int(row, "layer_int"),
      is_ramp=_row_int(row, "is_ramp"),
      road_priority=_row_int(row, "road_priority"),
      route_level=_row_int(row, "route_level"),
      ramp_type=_row_text(row, "ramp_type"),
      segment_length=_row_float(row, "segment_length"),
      geometry_polyline=_row_text(row, "geometry_polyline"),
      gps_confidence_penalty=_row_float(row, "gps_confidence_penalty"),
      sensor_difficult_zone=_row_int(row, "sensor_difficult_zone"),
      map_confidence=_row_float(row, "map_confidence", 1.0),
    )))

  segments_with_sort_key.sort(key=lambda item: (item[0], item[1]))
  return [segment for _, _, segment in segments_with_sort_key[:max(0, limit)]]
