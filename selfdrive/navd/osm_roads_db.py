#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


ROADS_COLUMNS = (
  "id", "osm_id", "name", "ref", "highway", "road_class", "oneway",
  "lat1", "lon1", "lat2", "lon2", "bearing_deg", "min_lat", "max_lat", "min_lon", "max_lon",
  "tunnel", "layer", "layer_int", "covered", "bridge", "junction",
  "destination", "destination_ref", "destination_forward", "destination_backward", "destination_ref_forward", "destination_ref_backward",
  "lanes", "lane_count", "turn_lanes", "turn_lanes_forward", "turn_lanes_backward", "destination_lanes", "maxspeed",
  "access", "motor_vehicle", "vehicle", "service", "route_ref", "int_ref", "placement", "change_lanes", "name_ko", "name_en",
  "motorway_link", "is_ramp", "road_priority", "route_level", "ramp_type", "bearing_in", "bearing_out", "curvature_avg", "curvature_max",
  "segment_length", "geometry_polyline", "parallel_group_id", "route_group_id", "parallel_overlap_score",
  "continuity_hint", "continuity_class", "split_angle", "merge_angle", "direction_confidence", "geometry_node_count", "geometry_density",
  "gps_shadow_zone", "gps_confidence_penalty", "tunnel_transition", "lane_delta", "future_heading_min", "future_heading_max",
  "road_width", "estimated_width", "ambiguity_score", "sensor_difficult_zone", "map_confidence", "future_corridor_polyline",
  "next_500m_topology", "next_1km_topology", "ic_complexity", "topology_density", "main_flow_bias", "ramp_bias", "exit_bias",
)

ROAD_COLUMN_DEFAULTS: dict[str, object] = {
  "id": None,
  "osm_id": 0,
  "name": "",
  "ref": "",
  "highway": "",
  "road_class": "",
  "oneway": 0,
  "lat1": 0.0,
  "lon1": 0.0,
  "lat2": 0.0,
  "lon2": 0.0,
  "bearing_deg": 0.0,
  "min_lat": 0.0,
  "max_lat": 0.0,
  "min_lon": 0.0,
  "max_lon": 0.0,
  "tunnel": "",
  "layer": "",
  "layer_int": 0,
  "covered": "",
  "bridge": "",
  "junction": "",
  "destination": "",
  "destination_ref": "",
  "destination_forward": "",
  "destination_backward": "",
  "destination_ref_forward": "",
  "destination_ref_backward": "",
  "lanes": "",
  "lane_count": 0,
  "turn_lanes": "",
  "turn_lanes_forward": "",
  "turn_lanes_backward": "",
  "destination_lanes": "",
  "maxspeed": "",
  "access": "",
  "motor_vehicle": "",
  "vehicle": "",
  "service": "",
  "route_ref": "",
  "int_ref": "",
  "placement": "",
  "change_lanes": "",
  "name_ko": "",
  "name_en": "",
  "motorway_link": 0,
  "is_ramp": 0,
  "road_priority": 0,
  "route_level": 0,
  "ramp_type": "",
  "bearing_in": 0.0,
  "bearing_out": 0.0,
  "curvature_avg": 0.0,
  "curvature_max": 0.0,
  "segment_length": 0.0,
  "geometry_polyline": "",
  "parallel_group_id": 0,
  "route_group_id": 0,
  "parallel_overlap_score": 0.0,
  "continuity_hint": 0.0,
  "continuity_class": "",
  "split_angle": 0.0,
  "merge_angle": 0.0,
  "direction_confidence": 1.0,
  "geometry_node_count": 0,
  "geometry_density": 0.0,
  "gps_shadow_zone": 0,
  "gps_confidence_penalty": 0.0,
  "tunnel_transition": 0,
  "lane_delta": 0,
  "future_heading_min": 0.0,
  "future_heading_max": 0.0,
  "road_width": 0.0,
  "estimated_width": 0.0,
  "ambiguity_score": 0.0,
  "sensor_difficult_zone": 0,
  "map_confidence": 1.0,
  "future_corridor_polyline": "",
  "next_500m_topology": "",
  "next_1km_topology": "",
  "ic_complexity": 0.0,
  "topology_density": 0.0,
  "main_flow_bias": 0.0,
  "ramp_bias": 0.0,
  "exit_bias": 0.0,
}


@dataclass(frozen=True)
class OSMRoadsDBValidation:
  db_path: Path
  segment_count: int
  roads_count: int
  rtree_count: int
  graph_node_count: int
  graph_edge_count: int
  graph_adjacency_count: int
  graph_skipped: str
  has_road_graph: bool
  speed_camera_count: int = 0
  speed_camera_match_count: int = 0
  route_camera_lookup_count: int = 0


class OSMRoadsDBReplaceError(RuntimeError):
  def __init__(
    self,
    operation: str,
    source_path: Path,
    target_path: Path,
    pending_db: Path,
    final_db: Path,
    backup_path: Path,
    attempts: int,
    original_error: OSError,
  ) -> None:
    self.operation = operation
    self.source_path = source_path
    self.target_path = target_path
    self.pending_db = pending_db
    self.final_db = final_db
    self.backup_path = backup_path
    self.attempts = attempts
    self.original_error = original_error
    super().__init__(
      f"OSM roads DB replace failed while {operation} after {attempts} attempt(s): "
      f"{source_path} -> {target_path}: {original_error}. "
      f"Pending DB preserved at {pending_db}."
    )


def road_row(values: dict[str, object]) -> tuple[object, ...]:
  return tuple(values.get(column, ROAD_COLUMN_DEFAULTS[column]) for column in ROADS_COLUMNS)


def roads_insert_sql() -> str:
  columns = ", ".join(ROADS_COLUMNS)
  placeholders = ", ".join("?" for _ in ROADS_COLUMNS)
  return f"INSERT INTO roads ({columns}) VALUES ({placeholders})"


def configure_build_connection(conn: sqlite3.Connection) -> None:
  conn.execute("PRAGMA journal_mode = OFF")
  conn.execute("PRAGMA synchronous = OFF")
  conn.execute("PRAGMA temp_store = FILE")
  conn.execute("PRAGMA cache_size = -262144")


def create_osm_roads_schema(conn: sqlite3.Connection) -> None:
  conn.executescript("""
    CREATE TABLE metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );

    CREATE TABLE roads (
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
      tunnel TEXT NOT NULL DEFAULT '',
      layer TEXT NOT NULL DEFAULT '',
      layer_int INTEGER NOT NULL DEFAULT 0,
      covered TEXT NOT NULL DEFAULT '',
      bridge TEXT NOT NULL DEFAULT '',
      junction TEXT NOT NULL DEFAULT '',
      destination TEXT NOT NULL DEFAULT '',
      destination_ref TEXT NOT NULL DEFAULT '',
      destination_forward TEXT NOT NULL DEFAULT '',
      destination_backward TEXT NOT NULL DEFAULT '',
      destination_ref_forward TEXT NOT NULL DEFAULT '',
      destination_ref_backward TEXT NOT NULL DEFAULT '',
      lanes TEXT NOT NULL DEFAULT '',
      lane_count INTEGER NOT NULL DEFAULT 0,
      turn_lanes TEXT NOT NULL DEFAULT '',
      turn_lanes_forward TEXT NOT NULL DEFAULT '',
      turn_lanes_backward TEXT NOT NULL DEFAULT '',
      destination_lanes TEXT NOT NULL DEFAULT '',
      maxspeed TEXT NOT NULL DEFAULT '',
      access TEXT NOT NULL DEFAULT '',
      motor_vehicle TEXT NOT NULL DEFAULT '',
      vehicle TEXT NOT NULL DEFAULT '',
      service TEXT NOT NULL DEFAULT '',
      route_ref TEXT NOT NULL DEFAULT '',
      int_ref TEXT NOT NULL DEFAULT '',
      placement TEXT NOT NULL DEFAULT '',
      change_lanes TEXT NOT NULL DEFAULT '',
      name_ko TEXT NOT NULL DEFAULT '',
      name_en TEXT NOT NULL DEFAULT '',
      motorway_link INTEGER NOT NULL DEFAULT 0,
      is_ramp INTEGER NOT NULL DEFAULT 0,
      road_priority INTEGER NOT NULL DEFAULT 0,
      route_level INTEGER NOT NULL DEFAULT 0,
      ramp_type TEXT NOT NULL DEFAULT '',
      bearing_in REAL NOT NULL DEFAULT 0.0,
      bearing_out REAL NOT NULL DEFAULT 0.0,
      curvature_avg REAL NOT NULL DEFAULT 0.0,
      curvature_max REAL NOT NULL DEFAULT 0.0,
      segment_length REAL NOT NULL DEFAULT 0.0,
      geometry_polyline TEXT NOT NULL DEFAULT '',
      parallel_group_id INTEGER NOT NULL DEFAULT 0,
      route_group_id INTEGER NOT NULL DEFAULT 0,
      parallel_overlap_score REAL NOT NULL DEFAULT 0.0,
      continuity_hint REAL NOT NULL DEFAULT 0.0,
      continuity_class TEXT NOT NULL DEFAULT '',
      split_angle REAL NOT NULL DEFAULT 0.0,
      merge_angle REAL NOT NULL DEFAULT 0.0,
      direction_confidence REAL NOT NULL DEFAULT 1.0,
      geometry_node_count INTEGER NOT NULL DEFAULT 0,
      geometry_density REAL NOT NULL DEFAULT 0.0,
      gps_shadow_zone INTEGER NOT NULL DEFAULT 0,
      gps_confidence_penalty REAL NOT NULL DEFAULT 0.0,
      tunnel_transition INTEGER NOT NULL DEFAULT 0,
      lane_delta INTEGER NOT NULL DEFAULT 0,
      future_heading_min REAL NOT NULL DEFAULT 0.0,
      future_heading_max REAL NOT NULL DEFAULT 0.0,
      road_width REAL NOT NULL DEFAULT 0.0,
      estimated_width REAL NOT NULL DEFAULT 0.0,
      ambiguity_score REAL NOT NULL DEFAULT 0.0,
      sensor_difficult_zone INTEGER NOT NULL DEFAULT 0,
      map_confidence REAL NOT NULL DEFAULT 1.0,
      future_corridor_polyline TEXT NOT NULL DEFAULT '',
      next_500m_topology TEXT NOT NULL DEFAULT '',
      next_1km_topology TEXT NOT NULL DEFAULT '',
      ic_complexity REAL NOT NULL DEFAULT 0.0,
      topology_density REAL NOT NULL DEFAULT 0.0,
      main_flow_bias REAL NOT NULL DEFAULT 0.0,
      ramp_bias REAL NOT NULL DEFAULT 0.0,
      exit_bias REAL NOT NULL DEFAULT 0.0
    );

    CREATE VIRTUAL TABLE roads_rtree USING rtree(id, min_lat, max_lat, min_lon, max_lon);

    CREATE TABLE road_nodes (
      id INTEGER PRIMARY KEY,
      node_key TEXT NOT NULL UNIQUE,
      lat REAL NOT NULL,
      lon REAL NOT NULL,
      layer_int INTEGER NOT NULL DEFAULT 0,
      node_degree INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE road_edges (
      road_id INTEGER PRIMARY KEY,
      start_node_id INTEGER NOT NULL,
      end_node_id INTEGER NOT NULL,
      start_node_key TEXT NOT NULL DEFAULT '',
      end_node_key TEXT NOT NULL DEFAULT '',
      layer_int INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE road_adjacency (
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
      PRIMARY KEY (from_road_id, to_road_id)
    );

    CREATE TABLE road_topology (
      id INTEGER PRIMARY KEY,
      from_road_id INTEGER,
      to_road_id INTEGER,
      topology_type TEXT NOT NULL DEFAULT '',
      topology_inferred INTEGER NOT NULL DEFAULT 0,
      inferred_reason TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE turn_restrictions (
      id INTEGER PRIMARY KEY,
      relation_id INTEGER,
      from_osm_id INTEGER,
      via_osm_id INTEGER,
      to_osm_id INTEGER,
      from_node_id INTEGER,
      via_node_id INTEGER,
      to_node_id INTEGER,
      restriction TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE lane_connectivity (
      id INTEGER PRIMARY KEY,
      relation_id INTEGER,
      from_osm_id INTEGER,
      to_osm_id INTEGER,
      from_node_id INTEGER,
      to_node_id INTEGER,
      lanes TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE lane_graph (
      id INTEGER PRIMARY KEY,
      from_road_id INTEGER,
      to_road_id INTEGER,
      from_lane INTEGER,
      to_lane INTEGER,
      allowed INTEGER NOT NULL DEFAULT 1,
      preferred INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE route_relations (
      id INTEGER PRIMARY KEY,
      relation_id INTEGER NOT NULL UNIQUE,
      route TEXT NOT NULL DEFAULT '',
      ref TEXT NOT NULL DEFAULT '',
      network TEXT NOT NULL DEFAULT '',
      name TEXT NOT NULL DEFAULT '',
      operator TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE road_route_members (
      id INTEGER PRIMARY KEY,
      relation_id INTEGER,
      osm_id INTEGER,
      role TEXT NOT NULL DEFAULT '',
      ref TEXT NOT NULL DEFAULT '',
      network TEXT NOT NULL DEFAULT '',
      route_level INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE motorway_junctions (
      id INTEGER PRIMARY KEY,
      osm_id INTEGER,
      ref TEXT NOT NULL DEFAULT '',
      name TEXT NOT NULL DEFAULT '',
      exit_to TEXT NOT NULL DEFAULT '',
      lat REAL,
      lon REAL,
      elevation REAL NOT NULL DEFAULT 0.0
    );

    CREATE TABLE road_continuity_cache (
      id INTEGER PRIMARY KEY,
      road_id INTEGER NOT NULL,
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
      next_1km_topology TEXT NOT NULL DEFAULT '',
      UNIQUE (road_id)
    );
  """)
  create_speed_camera_schema(conn)


def create_speed_camera_schema(conn: sqlite3.Connection) -> None:
  conn.executescript("""
    CREATE TABLE IF NOT EXISTS speed_cameras (
      id INTEGER PRIMARY KEY,
      external_id TEXT NOT NULL DEFAULT '',
      camera_type TEXT NOT NULL DEFAULT '',
      lat REAL NOT NULL,
      lon REAL NOT NULL,
      speed_limit_kph INTEGER NOT NULL DEFAULT 0,
      bearing_deg REAL NOT NULL DEFAULT -1.0,
      direction TEXT NOT NULL DEFAULT '',
      road_name TEXT NOT NULL DEFAULT '',
      address TEXT NOT NULL DEFAULT '',
      source TEXT NOT NULL DEFAULT '',
      source_updated_at TEXT NOT NULL DEFAULT '',
      raw_json TEXT NOT NULL DEFAULT '',
      map_confidence REAL NOT NULL DEFAULT 1.0,
      UNIQUE (source, external_id)
    );

    CREATE TABLE IF NOT EXISTS speed_camera_road_matches (
      id INTEGER PRIMARY KEY,
      camera_id INTEGER NOT NULL,
      road_id INTEGER NOT NULL,
      distance_m REAL NOT NULL,
      heading_diff_deg REAL NOT NULL DEFAULT -1.0,
      match_score REAL NOT NULL DEFAULT 0.0,
      match_confidence REAL NOT NULL DEFAULT 0.0,
      same_road_name INTEGER NOT NULL DEFAULT 0,
      primary_match INTEGER NOT NULL DEFAULT 0,
      matched_by TEXT NOT NULL DEFAULT 'nearest_road',
      UNIQUE (camera_id, road_id)
    );

    CREATE TABLE IF NOT EXISTS route_camera_lookup (
      road_id INTEGER NOT NULL,
      camera_id INTEGER NOT NULL,
      match_id INTEGER NOT NULL,
      match_distance_m REAL NOT NULL,
      match_confidence REAL NOT NULL,
      primary_match INTEGER NOT NULL DEFAULT 0,
      speed_limit_kph INTEGER NOT NULL DEFAULT 0,
      camera_type TEXT NOT NULL DEFAULT '',
      camera_bearing_deg REAL NOT NULL DEFAULT -1.0,
      display_class TEXT NOT NULL DEFAULT 'suspicious',
      direction_verdict TEXT NOT NULL DEFAULT 'unknown',
      reject_reason TEXT NOT NULL DEFAULT '',
      opposite_road_id INTEGER NOT NULL DEFAULT 0,
      opposite_match_distance_m REAL NOT NULL DEFAULT 0.0,
      opposite_match_confidence REAL NOT NULL DEFAULT 0.0,
      PRIMARY KEY (road_id, camera_id)
    );
  """)
  _ensure_columns(conn, "route_camera_lookup", {
    "display_class": "TEXT NOT NULL DEFAULT 'suspicious'",
    "direction_verdict": "TEXT NOT NULL DEFAULT 'unknown'",
    "reject_reason": "TEXT NOT NULL DEFAULT ''",
    "opposite_road_id": "INTEGER NOT NULL DEFAULT 0",
    "opposite_match_distance_m": "REAL NOT NULL DEFAULT 0.0",
    "opposite_match_confidence": "REAL NOT NULL DEFAULT 0.0",
  })


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
  existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
  for name, definition in columns.items():
    if name not in existing:
      conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def create_osm_roads_indexes(conn: sqlite3.Connection) -> None:
  conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_roads_osm_id ON roads(osm_id);
    CREATE INDEX IF NOT EXISTS idx_roads_highway ON roads(highway);
    CREATE INDEX IF NOT EXISTS idx_roads_name ON roads(name);
    CREATE INDEX IF NOT EXISTS idx_roads_ref ON roads(ref);
    CREATE INDEX IF NOT EXISTS idx_roads_layer_int ON roads(layer_int);
    CREATE INDEX IF NOT EXISTS idx_roads_parallel_group ON roads(parallel_group_id);
    CREATE INDEX IF NOT EXISTS idx_roads_route_group ON roads(route_group_id);
    CREATE INDEX IF NOT EXISTS idx_road_edges_start_node ON road_edges(start_node_id);
    CREATE INDEX IF NOT EXISTS idx_road_edges_end_node ON road_edges(end_node_id);
    CREATE INDEX IF NOT EXISTS idx_road_adjacency_to ON road_adjacency(to_road_id);
    CREATE INDEX IF NOT EXISTS idx_road_topology_from ON road_topology(from_road_id);
    CREATE INDEX IF NOT EXISTS idx_road_topology_from_to ON road_topology(from_road_id, to_road_id);
    CREATE INDEX IF NOT EXISTS idx_turn_restrictions_from_to ON turn_restrictions(from_osm_id, to_osm_id);
    CREATE INDEX IF NOT EXISTS idx_lane_connectivity_from_to ON lane_connectivity(from_osm_id, to_osm_id);
    CREATE INDEX IF NOT EXISTS idx_lane_graph_from ON lane_graph(from_road_id);
    CREATE INDEX IF NOT EXISTS idx_route_members_osm_id ON road_route_members(osm_id);
    CREATE INDEX IF NOT EXISTS idx_motorway_junctions_osm_id ON motorway_junctions(osm_id);
  """)
  create_speed_camera_indexes(conn)


def create_speed_camera_indexes(conn: sqlite3.Connection) -> None:
  create_speed_camera_schema(conn)
  conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_speed_cameras_lat_lon ON speed_cameras(lat, lon);
    CREATE INDEX IF NOT EXISTS idx_speed_cameras_source_external ON speed_cameras(source, external_id);
    CREATE INDEX IF NOT EXISTS idx_speed_camera_matches_camera ON speed_camera_road_matches(camera_id);
    CREATE INDEX IF NOT EXISTS idx_speed_camera_matches_road ON speed_camera_road_matches(road_id);
    CREATE INDEX IF NOT EXISTS idx_speed_camera_matches_primary ON speed_camera_road_matches(primary_match, match_confidence);
    CREATE INDEX IF NOT EXISTS idx_route_camera_lookup_road ON route_camera_lookup(road_id);
    CREATE INDEX IF NOT EXISTS idx_route_camera_lookup_camera ON route_camera_lookup(camera_id);
    CREATE INDEX IF NOT EXISTS idx_route_camera_lookup_display ON route_camera_lookup(display_class, direction_verdict);
  """)


def put_metadata(conn: sqlite3.Connection, values: dict[str, object]) -> None:
  conn.executemany(
    "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
    ((str(key), str(value)) for key, value in values.items()),
  )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
  return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1", (table,)).fetchone() is not None


def _metadata_value(conn: sqlite3.Connection, key: str) -> str:
  if not _table_exists(conn, "metadata"):
    return ""
  row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
  return str(row[0]) if row and row[0] is not None else ""


def _metadata_int(conn: sqlite3.Connection, key: str) -> int:
  try:
    return int(_metadata_value(conn, key))
  except ValueError:
    return 0


def validate_osm_roads_db(
  db_path: Path,
  require_road_graph: bool = False,
  require_speed_cameras: bool = False,
  run_quick_check: bool = False,
  run_rtree_check: bool = False,
) -> OSMRoadsDBValidation:
  db_path = Path(db_path)
  if not db_path.exists():
    raise RuntimeError(f"OSM roads DB missing: {db_path}")

  try:
    with closing(sqlite3.connect(db_path, cached_statements=0)) as conn:
      for table in ("roads", "roads_rtree", "metadata"):
        if not _table_exists(conn, table):
          raise RuntimeError(f"OSM roads DB missing table: {table}")

      roads_count = int(conn.execute("SELECT COUNT(*) FROM roads").fetchone()[0])
      rtree_count = int(conn.execute("SELECT COUNT(*) FROM roads_rtree").fetchone()[0])
      segment_count = _metadata_int(conn, "segment_count") or roads_count
      if roads_count <= 0 or rtree_count <= 0:
        raise RuntimeError(f"OSM roads DB has no road segments: roads={roads_count}, rtree={rtree_count}")
      if roads_count != rtree_count:
        raise RuntimeError(f"OSM roads DB row count mismatch: roads={roads_count}, rtree={rtree_count}")

      graph_node_count = _metadata_int(conn, "road_graph_node_count")
      graph_edge_count = _metadata_int(conn, "road_graph_edge_count")
      graph_adjacency_count = _metadata_int(conn, "road_graph_adjacency_count")
      graph_skipped = _metadata_value(conn, "road_graph_skipped")
      has_graph_tables = all(_table_exists(conn, table) for table in ("road_nodes", "road_edges", "road_adjacency"))
      if has_graph_tables:
        graph_node_count = graph_node_count or int(conn.execute("SELECT COUNT(*) FROM road_nodes").fetchone()[0])
        graph_edge_count = graph_edge_count or int(conn.execute("SELECT COUNT(*) FROM road_edges").fetchone()[0])
        graph_adjacency_count = graph_adjacency_count or int(conn.execute("SELECT COUNT(*) FROM road_adjacency").fetchone()[0])

      has_road_graph = has_graph_tables and graph_node_count > 0 and graph_edge_count > 0 and graph_adjacency_count > 0 and graph_skipped != "1"
      if require_road_graph and not has_road_graph:
        raise RuntimeError("OSM roads DB does not contain the forward successor road graph")

      speed_camera_count = 0
      speed_camera_match_count = 0
      route_camera_lookup_count = 0
      has_speed_camera_tables = all(_table_exists(conn, table) for table in ("speed_cameras", "speed_camera_road_matches", "route_camera_lookup"))
      if has_speed_camera_tables:
        speed_camera_count = int(conn.execute("SELECT COUNT(*) FROM speed_cameras").fetchone()[0])
        speed_camera_match_count = int(conn.execute("SELECT COUNT(*) FROM speed_camera_road_matches").fetchone()[0])
        route_camera_lookup_count = int(conn.execute("SELECT COUNT(*) FROM route_camera_lookup").fetchone()[0])
      if require_speed_cameras and (not has_speed_camera_tables or speed_camera_count <= 0 or route_camera_lookup_count <= 0):
        raise RuntimeError("OSM roads DB does not contain matched speed camera lookup data")

      if run_quick_check:
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check.lower() != "ok":
          raise RuntimeError(f"OSM roads DB quick_check failed: {quick_check}")

      if run_rtree_check:
        try:
          rtree_check = str(conn.execute("SELECT rtreecheck('roads_rtree')").fetchone()[0])
          if rtree_check.lower() != "ok":
            raise RuntimeError(f"OSM roads DB rtreecheck failed: {rtree_check}")
        except sqlite3.Error as e:
          if "no such function" not in str(e).lower():
            raise
  except sqlite3.Error as e:
    raise RuntimeError(f"OSM roads DB validation failed: {e}") from e

  return OSMRoadsDBValidation(
    db_path=db_path,
    segment_count=max(segment_count, roads_count),
    roads_count=roads_count,
    rtree_count=rtree_count,
    graph_node_count=graph_node_count,
    graph_edge_count=graph_edge_count,
    graph_adjacency_count=graph_adjacency_count,
    graph_skipped=graph_skipped,
    has_road_graph=has_road_graph,
    speed_camera_count=speed_camera_count,
    speed_camera_match_count=speed_camera_match_count,
    route_camera_lookup_count=route_camera_lookup_count,
  )


def _unlink_if_exists(path: Path) -> None:
  try:
    path.unlink()
  except FileNotFoundError:
    pass


def _move_or_copy(source: Path, target: Path) -> None:
  try:
    os.replace(source, target)
  except OSError:
    shutil.copy2(source, target)
    source.unlink()


def pending_osm_roads_db_path(final_db: Path) -> Path:
  final_db = Path(final_db)
  return final_db.with_suffix(final_db.suffix + ".tmp")


def _same_path(left: Path, right: Path) -> bool:
  return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def _replace_with_retries(
  source: Path,
  target: Path,
  operation: str,
  pending_db: Path,
  final_db: Path,
  backup_path: Path,
  retry_attempts: int,
  retry_delay_s: float,
) -> None:
  attempts = max(1, int(retry_attempts))
  delay_s = max(0.0, float(retry_delay_s))
  last_error: OSError | None = None
  for attempt in range(1, attempts + 1):
    try:
      os.replace(source, target)
      return
    except OSError as e:
      last_error = e
      if attempt < attempts and delay_s > 0.0:
        time.sleep(delay_s)

  assert last_error is not None
  raise OSMRoadsDBReplaceError(operation, source, target, pending_db, final_db, backup_path, attempts, last_error) from last_error


def install_pending_osm_roads_db(
  pending_db: Path,
  final_db: Path,
  require_road_graph: bool = False,
  require_speed_cameras: bool = False,
  retry_attempts: int = 15,
  retry_delay_s: float = 1.0,
) -> OSMRoadsDBValidation:
  pending_db = Path(pending_db)
  final_db = Path(final_db)
  backup_path = final_db.with_suffix(final_db.suffix + ".bak")
  final_db.parent.mkdir(parents=True, exist_ok=True)

  validation = validate_osm_roads_db(
    pending_db,
    require_road_graph=require_road_graph,
    require_speed_cameras=require_speed_cameras,
  )

  backed_up = False
  if final_db.exists():
    _replace_with_retries(
      final_db,
      backup_path,
      "moving current DB to backup",
      pending_db,
      final_db,
      backup_path,
      retry_attempts,
      retry_delay_s,
    )
    backed_up = True

  try:
    _replace_with_retries(
      pending_db,
      final_db,
      "installing pending DB",
      pending_db,
      final_db,
      backup_path,
      retry_attempts,
      retry_delay_s,
    )
  except Exception:
    if backed_up and backup_path.exists() and not final_db.exists():
      os.replace(backup_path, final_db)
    raise
  return validation


def replace_osm_roads_db(
  source_db: Path,
  final_db: Path,
  require_road_graph: bool = False,
  require_speed_cameras: bool = False,
  retry_attempts: int = 15,
  retry_delay_s: float = 1.0,
) -> OSMRoadsDBValidation:
  source_db = Path(source_db)
  final_db = Path(final_db)
  final_db.parent.mkdir(parents=True, exist_ok=True)
  install_tmp = pending_osm_roads_db_path(final_db)
  if not _same_path(source_db, install_tmp):
    _unlink_if_exists(install_tmp)
    _move_or_copy(source_db, install_tmp)

  try:
    return install_pending_osm_roads_db(
      install_tmp,
      final_db,
      require_road_graph=require_road_graph,
      require_speed_cameras=require_speed_cameras,
      retry_attempts=retry_attempts,
      retry_delay_s=retry_delay_s,
    )
  except OSMRoadsDBReplaceError:
    raise
  except Exception:
    _unlink_if_exists(install_tmp)
    raise
