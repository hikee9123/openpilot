#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH
  from openpilot.selfdrive.navd.osm_roads_db import (
    configure_build_connection,
    create_osm_roads_indexes,
    create_osm_roads_schema,
    install_pending_osm_roads_db,
    OSMRoadsDBReplaceError,
    pending_osm_roads_db_path,
    put_metadata,
    replace_osm_roads_db,
    road_row,
    roads_insert_sql,
    validate_osm_roads_db,
  )
  from openpilot.selfdrive.navd.osm_speed_cameras import DEFAULT_CAMERA_MATCH_RADIUS_M, import_speed_cameras_from_csv
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR, DEFAULT_NAVD_TMP_DIR, ensure_navd_dirs
except ModuleNotFoundError:
  osm_roads = import_module("selfdrive.navd.osm_roads")
  osm_roads_db = import_module("selfdrive.navd.osm_roads_db")
  osm_speed_cameras = import_module("selfdrive.navd.osm_speed_cameras")
  navd_paths = import_module("selfdrive.navd.paths")
  DEFAULT_OSM_ROADS_DB_PATH = osm_roads.DEFAULT_OSM_ROADS_DB_PATH
  configure_build_connection = osm_roads_db.configure_build_connection
  create_osm_roads_indexes = osm_roads_db.create_osm_roads_indexes
  create_osm_roads_schema = osm_roads_db.create_osm_roads_schema
  install_pending_osm_roads_db = osm_roads_db.install_pending_osm_roads_db
  OSMRoadsDBReplaceError = osm_roads_db.OSMRoadsDBReplaceError
  pending_osm_roads_db_path = osm_roads_db.pending_osm_roads_db_path
  put_metadata = osm_roads_db.put_metadata
  replace_osm_roads_db = osm_roads_db.replace_osm_roads_db
  road_row = osm_roads_db.road_row
  roads_insert_sql = osm_roads_db.roads_insert_sql
  validate_osm_roads_db = osm_roads_db.validate_osm_roads_db
  DEFAULT_CAMERA_MATCH_RADIUS_M = osm_speed_cameras.DEFAULT_CAMERA_MATCH_RADIUS_M
  import_speed_cameras_from_csv = osm_speed_cameras.import_speed_cameras_from_csv
  DEFAULT_NAVD_SOURCE_DIR = navd_paths.DEFAULT_NAVD_SOURCE_DIR
  DEFAULT_NAVD_TMP_DIR = navd_paths.DEFAULT_NAVD_TMP_DIR
  ensure_navd_dirs = navd_paths.ensure_navd_dirs


DEFAULT_PBF = DEFAULT_NAVD_SOURCE_DIR / "south-korea-latest.osm.pbf"
DEFAULT_TMP_DB = DEFAULT_NAVD_TMP_DIR / "osm_roads_build" / "osm_roads_kr.sqlite3.build"
ROAD_BATCH_SIZE = 50000
ADJACENCY_NODE_BATCH_SIZE = 20000
CROSS_LAYER_SHARED_NODE_BATCH_SIZE = 10000
EARTH_RADIUS_M = 6371000.0
PROGRESS_PREFIX = "__osm_progress__ "
CROSS_LAYER_SHARED_NODE_MAX_LAYER_DELTA = 1
CROSS_LAYER_SHARED_NODE_MAX_TURN_DEG = 35.0
CROSS_LAYER_SHARED_NODE_MAJOR_TURN_DEG = 25.0
CROSS_LAYER_SHARED_NODE_LINK_TURN_DEG = 45.0
CROSS_LAYER_SHARED_NODE_CONNECTIVITY_CONFIDENCE = 0.82

DRIVABLE_HIGHWAYS = {
  "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
  "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
  "residential", "living_street", "service", "road",
}
MAJOR_PROFILE_HIGHWAYS = {
  "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
  "secondary", "secondary_link", "tertiary", "tertiary_link",
}
CAMERA_BALANCED_EXCLUDED_HIGHWAYS = {"service", "living_street", "road"}
BUILD_PROFILE_HIGHWAYS = {
  "full": frozenset(DRIVABLE_HIGHWAYS),
  "camera-balanced": frozenset(DRIVABLE_HIGHWAYS - CAMERA_BALANCED_EXCLUDED_HIGHWAYS),
  "major": frozenset(MAJOR_PROFILE_HIGHWAYS),
}
BUILD_PROFILE_ALIASES = {
  "balanced": "camera-balanced",
  "camera": "camera-balanced",
  "camera_blanced": "camera-balanced",
  "camera-blanced": "camera-balanced",
  "camera_balanced": "camera-balanced",
  "camera-balanced": "camera-balanced",
}
LINK_HIGHWAYS = {"motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
BLOCKED_ACCESS = {"no", "private", "agricultural", "forestry"}
ROAD_PRIORITY = {
  "motorway": 100,
  "trunk": 90,
  "primary": 80,
  "secondary": 70,
  "tertiary": 60,
  "unclassified": 45,
  "residential": 40,
  "living_street": 30,
  "service": 20,
  "road": 20,
  "motorway_link": 75,
  "trunk_link": 70,
  "primary_link": 65,
  "secondary_link": 55,
  "tertiary_link": 45,
}


def _normalize_build_profile(value: str) -> str:
  profile = (value or "full").strip().lower()
  profile = BUILD_PROFILE_ALIASES.get(profile, profile)
  if profile not in BUILD_PROFILE_HIGHWAYS:
    choices = ", ".join(sorted(BUILD_PROFILE_HIGHWAYS))
    aliases = ", ".join(sorted(BUILD_PROFILE_ALIASES))
    raise ValueError(f"unknown build profile: {value!r}; choices: {choices}; aliases: {aliases}")
  return profile


class ProgressReporter:
  def __init__(self, enabled: bool = False, db_path: Path | None = None, min_interval_s: float = 10.0) -> None:
    self.enabled = enabled
    self.db_path = db_path
    self.min_interval_s = min_interval_s
    self.started_at = time.monotonic()
    self.last_emit_t = 0.0

  def emit(
    self,
    step: str,
    progress: int,
    message: str,
    *,
    force: bool = False,
    **details: object,
  ) -> None:
    now = time.monotonic()
    if not force and now - self.last_emit_t < self.min_interval_s:
      return
    self.last_emit_t = now
    payload: dict[str, object] = {
      "step": step,
      "progress": max(0, min(100, int(progress))),
      "message": message,
      "elapsed_s": int(now - self.started_at),
    }
    if self.db_path is not None:
      try:
        payload["db_size_bytes"] = self.db_path.stat().st_size
        payload["db_mtime"] = int(self.db_path.stat().st_mtime)
      except OSError:
        payload["db_size_bytes"] = 0
    payload.update(details)
    if self.enabled:
      print(PROGRESS_PREFIX + json.dumps(payload, sort_keys=True), flush=True)
    print(message, flush=True)

  def heartbeat(self, step: str, progress: int, message: str, **details: object):
    def _callback() -> int:
      self.emit(step, progress, message, **details)
      return 0

    return _callback


@dataclass(frozen=True)
class RouteMemberInfo:
  relation_id: int
  route: str
  ref: str
  network: str
  role: str
  route_level: int


@dataclass(frozen=True)
class RouteRelationInfo:
  relation_id: int
  route: str
  ref: str
  network: str
  name: str
  operator: str


@dataclass(frozen=True)
class TurnRestrictionInfo:
  relation_id: int
  from_osm_id: int
  via_osm_id: int
  to_osm_id: int
  restriction: str


def _load_osmium_module():
  try:
    import osmium
  except ImportError as e:
    raise RuntimeError("building the OSM roads DB requires the Python package 'osmium' (pyosmium). Install it outside this script first.") from e
  return osmium


def _tag(tags: Any, key: str, default: str = "") -> str:
  try:
    value = tags.get(key, default)
  except AttributeError:
    value = default
  return str(value or default)


def _int_tag(value: str, default: int = 0) -> int:
  try:
    return int(float(value))
  except (TypeError, ValueError):
    return default


def _lane_count(value: str) -> int:
  if not value:
    return 0
  first = value.replace(";", "|").split("|", maxsplit=1)[0]
  return _int_tag(first, 0)


def _route_level(network: str, ref: str) -> int:
  text = f"{network} {ref}".lower()
  if any(token in text for token in ("motorway", "expressway", "kr:ex")):
    return 100
  if "national" in text or "kr:national" in text:
    return 80
  if "regional" in text or "province" in text or "provincial" in text:
    return 60
  return 40 if ref else 0


def _member_is_way(member: Any) -> bool:
  return str(getattr(member, "type", "")).lower() in {"w", "way"}


def _member_is_node(member: Any) -> bool:
  return str(getattr(member, "type", "")).lower() in {"n", "node"}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  lat1_rad = math.radians(lat1)
  lat2_rad = math.radians(lat2)
  dlat = math.radians(lat2 - lat1)
  dlon = math.radians(lon2 - lon1)
  a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0) ** 2
  return 2.0 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  lat1_rad = math.radians(lat1)
  lat2_rad = math.radians(lat2)
  dlon_rad = math.radians(lon2 - lon1)
  y = math.sin(dlon_rad) * math.cos(lat2_rad)
  x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad)
  return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _reverse_bearing(bearing_deg: float) -> float:
  return (bearing_deg + 180.0) % 360.0


def _oneway(tags: Any, highway: str) -> int:
  value = _tag(tags, "oneway").strip().lower()
  if value in {"yes", "true", "1"}:
    return 1
  if value in {"-1", "reverse"}:
    return -1
  if value in {"no", "false", "0"}:
    return 0
  if _tag(tags, "junction").strip().lower() in {"roundabout", "circular"}:
    return 1
  if highway == "motorway":
    return 1
  return 0


def _is_drivable_way(tags: Any, included_highways: frozenset[str]) -> bool:
  highway = _tag(tags, "highway")
  if highway not in included_highways:
    return False
  if _tag(tags, "area").lower() == "yes":
    return False
  for key in ("motor_vehicle", "vehicle", "access"):
    if _tag(tags, key).strip().lower() in BLOCKED_ACCESS:
      return False
  return True


def _ramp_type(tags: Any, highway: str) -> str:
  junction = _tag(tags, "junction").strip().lower()
  if junction in {"roundabout", "circular"}:
    return "loop"
  if highway in LINK_HIGHWAYS:
    if _tag(tags, "destination") or _tag(tags, "destination:ref"):
      return "connector"
    return "ramp"
  return ""


def _road_priority(highway: str, route_level: int) -> int:
  return max(ROAD_PRIORITY.get(highway, 0), route_level)


class OSMRelationCollector:
  def __init__(self, osmium: Any) -> None:
    self._osmium = osmium
    self.route_relations: list[RouteRelationInfo] = []
    self.route_members_by_way: dict[int, list[RouteMemberInfo]] = defaultdict(list)
    self.turn_restrictions: list[TurnRestrictionInfo] = []

  def relation(self, relation: Any) -> None:
    tags = relation.tags
    relation_type = _tag(tags, "type").lower()
    if relation_type == "route":
      route = _tag(tags, "route")
      ref = _tag(tags, "ref")
      network = _tag(tags, "network")
      name = _tag(tags, "name")
      operator = _tag(tags, "operator")
      if route or ref or network:
        self.route_relations.append(RouteRelationInfo(relation.id, route, ref, network, name, operator))
        level = _route_level(network, ref)
        for member in relation.members:
          if _member_is_way(member):
            self.route_members_by_way[int(member.ref)].append(RouteMemberInfo(relation.id, route, ref, network, str(member.role or ""), level))
    elif relation_type == "restriction":
      restriction = _tag(tags, "restriction")
      from_osm_id = 0
      via_osm_id = 0
      to_osm_id = 0
      for member in relation.members:
        role = str(member.role or "")
        if role == "from" and _member_is_way(member):
          from_osm_id = int(member.ref)
        elif role == "to" and _member_is_way(member):
          to_osm_id = int(member.ref)
        elif role == "via":
          via_osm_id = int(member.ref)
      if restriction and from_osm_id and to_osm_id:
        self.turn_restrictions.append(TurnRestrictionInfo(relation.id, from_osm_id, via_osm_id, to_osm_id, restriction))


class OSMRoadsBuilder:
  def __init__(
    self,
    conn: sqlite3.Connection,
    source_pbf: Path,
    relation_collector: OSMRelationCollector,
    build_graph: bool,
    included_highways: frozenset[str],
    progress: ProgressReporter,
  ) -> None:
    self.conn = conn
    self.source_pbf = source_pbf
    self.relation_collector = relation_collector
    self.build_graph = build_graph
    self.included_highways = included_highways
    self.progress = progress
    self.node_ids: dict[tuple[int, int], int] = {}
    self.next_node_id = 1
    self.next_road_id = 1
    self.roads: list[tuple[object, ...]] = []
    self.rtree_rows: list[tuple[int, float, float, float, float]] = []
    self.road_edges: list[tuple[int, int, int, str, str, int]] = []
    self.road_nodes: list[tuple[int, str, float, float, int]] = []
    self.directed_edges: list[tuple[int, int, int, int, int, float, int, str, str, str, str, str, int, int, int, int]] = []
    self.way_count = 0
    self.segment_count = 0

  def prepare_temp_tables(self) -> None:
    self.conn.execute("""
      CREATE TEMP TABLE directed_edges (
        road_id INTEGER NOT NULL,
        from_node_id INTEGER NOT NULL,
        to_node_id INTEGER NOT NULL,
        from_osm_node_id INTEGER NOT NULL,
        to_osm_node_id INTEGER NOT NULL,
        bearing_deg REAL NOT NULL,
        road_osm_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        ref TEXT NOT NULL,
        highway TEXT NOT NULL,
        route_ref TEXT NOT NULL,
        destination TEXT NOT NULL,
        layer_int INTEGER NOT NULL,
        is_ramp INTEGER NOT NULL,
        road_priority INTEGER NOT NULL,
        route_level INTEGER NOT NULL
      )
    """)

  def flush(self) -> None:
    if self.road_nodes:
      self.conn.executemany("INSERT INTO road_nodes(id, node_key, lat, lon, layer_int) VALUES (?, ?, ?, ?, ?)", self.road_nodes)
      self.road_nodes.clear()
    if self.roads:
      self.conn.executemany(roads_insert_sql(), self.roads)
      self.roads.clear()
    if self.rtree_rows:
      self.conn.executemany("INSERT INTO roads_rtree(id, min_lat, max_lat, min_lon, max_lon) VALUES (?, ?, ?, ?, ?)", self.rtree_rows)
      self.rtree_rows.clear()
    if self.road_edges:
      self.conn.executemany(
        "INSERT INTO road_edges(road_id, start_node_id, end_node_id, start_node_key, end_node_key, layer_int) VALUES (?, ?, ?, ?, ?, ?)",
        self.road_edges,
      )
      self.road_edges.clear()
    if self.directed_edges:
      self.conn.executemany(
        """
        INSERT INTO directed_edges(
          road_id, from_node_id, to_node_id, from_osm_node_id, to_osm_node_id, bearing_deg, road_osm_id,
          name, ref, highway, route_ref, destination, layer_int, is_ramp, road_priority, route_level
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        self.directed_edges,
      )
      self.directed_edges.clear()
    self.conn.commit()

  def _db_node_id(self, osm_node_id: int, lat: float, lon: float, layer_int: int) -> tuple[int, str]:
    key = (osm_node_id, layer_int)
    node_id = self.node_ids.get(key)
    node_key = f"{osm_node_id}:{layer_int}"
    if node_id is not None:
      return node_id, node_key
    node_id = self.next_node_id
    self.next_node_id += 1
    self.node_ids[key] = node_id
    self.road_nodes.append((node_id, node_key, lat, lon, layer_int))
    return node_id, node_key

  def _route_metadata(self, osm_id: int) -> tuple[str, str, int]:
    members = self.relation_collector.route_members_by_way.get(osm_id, [])
    refs = [member.ref for member in members if member.ref]
    route_ref = ";".join(dict.fromkeys(refs))
    int_ref = ";".join(dict.fromkeys(member.ref for member in members if member.ref and "int" in member.network.lower()))
    route_level = max((member.route_level for member in members), default=0)
    return route_ref, int_ref, route_level

  def _append_segment(self, way: Any, tags: Any, start: Any, end: Any) -> None:
    highway = _tag(tags, "highway")
    layer = _tag(tags, "layer")
    layer_int = _int_tag(layer, 0)
    start_lat = float(start.location.lat)
    start_lon = float(start.location.lon)
    end_lat = float(end.location.lat)
    end_lon = float(end.location.lon)
    length_m = _haversine_m(start_lat, start_lon, end_lat, end_lon)
    if length_m <= 0.05:
      return

    osm_id = int(way.id)
    road_id = self.next_road_id
    self.next_road_id += 1
    bearing = _bearing_deg(start_lat, start_lon, end_lat, end_lon)
    route_ref, int_ref, route_level = self._route_metadata(osm_id)
    ramp_type = _ramp_type(tags, highway)
    is_ramp = 1 if ramp_type or highway in LINK_HIGHWAYS else 0
    priority = _road_priority(highway, route_level)
    oneway = _oneway(tags, highway)
    start_node_id, start_node_key = self._db_node_id(int(start.ref), start_lat, start_lon, layer_int)
    end_node_id, end_node_key = self._db_node_id(int(end.ref), end_lat, end_lon, layer_int)
    start_osm_node_id = int(start.ref)
    end_osm_node_id = int(end.ref)
    min_lat = min(start_lat, end_lat)
    max_lat = max(start_lat, end_lat)
    min_lon = min(start_lon, end_lon)
    max_lon = max(start_lon, end_lon)
    geometry_polyline = f"{start_lat:.7f},{start_lon:.7f} {end_lat:.7f},{end_lon:.7f}"
    name = _tag(tags, "name") or _tag(tags, "name:ko") or _tag(tags, "name:en")
    ref = _tag(tags, "ref")
    road_values = {
      "id": road_id,
      "osm_id": osm_id,
      "name": name,
      "ref": ref,
      "highway": highway,
      "road_class": highway,
      "oneway": oneway,
      "lat1": start_lat,
      "lon1": start_lon,
      "lat2": end_lat,
      "lon2": end_lon,
      "bearing_deg": bearing,
      "min_lat": min_lat,
      "max_lat": max_lat,
      "min_lon": min_lon,
      "max_lon": max_lon,
      "tunnel": _tag(tags, "tunnel"),
      "layer": layer,
      "layer_int": layer_int,
      "covered": _tag(tags, "covered"),
      "bridge": _tag(tags, "bridge"),
      "junction": _tag(tags, "junction"),
      "destination": _tag(tags, "destination"),
      "destination_ref": _tag(tags, "destination:ref"),
      "destination_forward": _tag(tags, "destination:forward"),
      "destination_backward": _tag(tags, "destination:backward"),
      "destination_ref_forward": _tag(tags, "destination:ref:forward"),
      "destination_ref_backward": _tag(tags, "destination:ref:backward"),
      "lanes": _tag(tags, "lanes"),
      "lane_count": _lane_count(_tag(tags, "lanes")),
      "turn_lanes": _tag(tags, "turn:lanes"),
      "turn_lanes_forward": _tag(tags, "turn:lanes:forward"),
      "turn_lanes_backward": _tag(tags, "turn:lanes:backward"),
      "destination_lanes": _tag(tags, "destination:lanes"),
      "maxspeed": _tag(tags, "maxspeed"),
      "access": _tag(tags, "access"),
      "motor_vehicle": _tag(tags, "motor_vehicle"),
      "vehicle": _tag(tags, "vehicle"),
      "service": _tag(tags, "service"),
      "route_ref": route_ref,
      "int_ref": int_ref,
      "placement": _tag(tags, "placement"),
      "change_lanes": _tag(tags, "change:lanes"),
      "name_ko": _tag(tags, "name:ko"),
      "name_en": _tag(tags, "name:en"),
      "motorway_link": 1 if highway == "motorway_link" else 0,
      "is_ramp": is_ramp,
      "road_priority": priority,
      "route_level": route_level,
      "ramp_type": ramp_type,
      "bearing_in": bearing,
      "bearing_out": bearing,
      "segment_length": length_m,
      "geometry_polyline": geometry_polyline,
      "continuity_hint": 1.0 if name or ref or route_ref else 0.35,
      "continuity_class": "ramp" if is_ramp else "main" if priority >= 60 else "local",
      "direction_confidence": 1.0,
      "geometry_node_count": 2,
      "geometry_density": 2.0 / max(length_m, 1.0),
      "map_confidence": 1.0,
      "main_flow_bias": min(1.0, priority / 100.0),
      "ramp_bias": 1.0 if is_ramp else 0.0,
      "exit_bias": 1.0 if is_ramp and _tag(tags, "destination") else 0.0,
    }
    self.roads.append(road_row(road_values))
    self.rtree_rows.append((road_id, min_lat, max_lat, min_lon, max_lon))
    self.road_edges.append((road_id, start_node_id, end_node_id, start_node_key, end_node_key, layer_int))
    if self.build_graph:
      if oneway >= 0:
        self.directed_edges.append((
          road_id, start_node_id, end_node_id, start_osm_node_id, end_osm_node_id, bearing, osm_id,
          name, ref, highway, route_ref, _tag(tags, "destination"), layer_int, is_ramp, priority, route_level,
        ))
      if oneway <= 0:
        self.directed_edges.append((
          road_id, end_node_id, start_node_id, end_osm_node_id, start_osm_node_id, _reverse_bearing(bearing), osm_id,
          name, ref, highway, route_ref, _tag(tags, "destination"), layer_int, is_ramp, priority, route_level,
        ))
    self.segment_count += 1

  def way(self, way: Any) -> None:
    self.way_count += 1
    tags = way.tags
    if not _is_drivable_way(tags, self.included_highways):
      return
    nodes = []
    for node in way.nodes:
      try:
        if not node.location.valid():
          continue
        nodes.append(node)
      except Exception:
        continue
    if len(nodes) < 2:
      return
    for start, end in zip(nodes, nodes[1:], strict=False):
      self._append_segment(way, tags, start, end)
      if len(self.roads) >= ROAD_BATCH_SIZE:
        self.flush()
        self._log_progress()

  def _log_progress(self) -> None:
    message = f"parsed ways={self.way_count:,} segments={self.segment_count:,} nodes={len(self.node_ids):,}"
    self.progress.emit(
      "segments",
      min(54, 15 + self.segment_count // 250000),
      message,
      ways=self.way_count,
      segments=self.segment_count,
      nodes=len(self.node_ids),
    )


def _insert_relation_metadata(conn: sqlite3.Connection, collector: OSMRelationCollector) -> None:
  conn.executemany(
    "INSERT INTO route_relations(relation_id, route, ref, network, name, operator) VALUES (?, ?, ?, ?, ?, ?)",
    ((item.relation_id, item.route, item.ref, item.network, item.name, item.operator) for item in collector.route_relations),
  )
  conn.executemany(
    "INSERT INTO road_route_members(relation_id, osm_id, role, ref, network, route_level) VALUES (?, ?, ?, ?, ?, ?)",
    (
      (member.relation_id, way_id, member.role, member.ref, member.network, member.route_level)
      for way_id, members in collector.route_members_by_way.items()
      for member in members
    ),
  )
  conn.executemany(
    "INSERT INTO turn_restrictions(relation_id, from_osm_id, via_osm_id, to_osm_id, restriction) VALUES (?, ?, ?, ?, ?)",
    ((item.relation_id, item.from_osm_id, item.via_osm_id, item.to_osm_id, item.restriction) for item in collector.turn_restrictions),
  )


def _execute_script_with_progress(conn: sqlite3.Connection, progress: ProgressReporter, script: str, step: str, percent: int, message: str) -> None:
  conn.set_progress_handler(progress.heartbeat(step, percent, message), 100000)
  try:
    conn.executescript(script)
  finally:
    conn.set_progress_handler(None, 0)


def _build_cross_layer_shared_node_adjacency(conn: sqlite3.Connection, progress: ProgressReporter) -> int:
  progress.emit("layer_adjacency", 80, "building cross-layer shared-node adjacency", force=True)
  turn_angle_sql = """
    CASE
      WHEN ABS(to_edge.bearing_deg - from_edge.bearing_deg) > 180.0
      THEN 360.0 - ABS(to_edge.bearing_deg - from_edge.bearing_deg)
      ELSE ABS(to_edge.bearing_deg - from_edge.bearing_deg)
    END
  """
  same_identity_sql = """
    (from_edge.road_osm_id = to_edge.road_osm_id
     OR (from_edge.name != '' AND from_edge.name = to_edge.name))
  """
  route_continuity_sql = """
    ((from_edge.ref != '' AND from_edge.ref = to_edge.ref)
     OR (from_edge.route_ref != '' AND from_edge.route_ref = to_edge.route_ref))
  """
  link_continuity_sql = f"""
    (from_edge.highway IN ({",".join(repr(highway) for highway in sorted(LINK_HIGHWAYS))})
     OR to_edge.highway IN ({",".join(repr(highway) for highway in sorted(LINK_HIGHWAYS))}))
  """
  conn.set_progress_handler(progress.heartbeat("layer_adjacency", 80, "finding cross-layer shared-node candidates"), 100000)
  try:
    conn.execute("DROP TABLE IF EXISTS cross_layer_adjacency_candidates")
    conn.execute("DROP TABLE IF EXISTS cross_layer_osm_node_batches")
    conn.execute("DROP TABLE IF EXISTS cross_layer_osm_nodes")
    conn.execute(f"""
      CREATE TEMP TABLE cross_layer_osm_node_batches AS
      SELECT
        to_osm_node_id AS osm_node_id,
        CAST((ROW_NUMBER() OVER (ORDER BY to_osm_node_id) - 1) / {CROSS_LAYER_SHARED_NODE_BATCH_SIZE} AS INTEGER) AS batch_id
      FROM (SELECT DISTINCT to_osm_node_id FROM directed_edges)
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cross_layer_osm_node_batches_batch ON cross_layer_osm_node_batches(batch_id, osm_node_id)")
    conn.execute("DROP TABLE IF EXISTS cross_layer_exit_edges")
    conn.execute("DROP TABLE IF EXISTS cross_layer_entry_edges")
    conn.execute("""
      CREATE TEMP TABLE cross_layer_adjacency_candidates (
        from_road_id INTEGER NOT NULL,
        to_road_id INTEGER NOT NULL,
        from_osm_id INTEGER NOT NULL,
        to_osm_id INTEGER NOT NULL,
        via_osm_node_id INTEGER NOT NULL,
        from_priority INTEGER NOT NULL,
        to_priority INTEGER NOT NULL,
        from_is_ramp INTEGER NOT NULL,
        to_is_ramp INTEGER NOT NULL,
        layer_delta INTEGER NOT NULL,
        turn_angle_deg REAL NOT NULL,
        same_identity INTEGER NOT NULL,
        route_continuity INTEGER NOT NULL,
        link_continuity INTEGER NOT NULL
      )
    """)
    batch_count = int(conn.execute("SELECT COALESCE(MAX(batch_id) + 1, 0) FROM cross_layer_osm_node_batches").fetchone()[0])
    candidate_sql = f"""
      INSERT INTO cross_layer_adjacency_candidates(
        from_road_id, to_road_id, from_osm_id, to_osm_id, via_osm_node_id,
        from_priority, to_priority, from_is_ramp, to_is_ramp, layer_delta,
        turn_angle_deg, same_identity, route_continuity, link_continuity
      )
      WITH candidates AS (
        SELECT
          from_edge.road_id AS from_road_id,
          to_edge.road_id AS to_road_id,
          from_edge.road_osm_id AS from_osm_id,
          to_edge.road_osm_id AS to_osm_id,
          from_edge.to_osm_node_id AS via_osm_node_id,
          from_edge.road_priority AS from_priority,
          to_edge.road_priority AS to_priority,
          from_edge.is_ramp AS from_is_ramp,
          to_edge.is_ramp AS to_is_ramp,
          ABS(from_edge.layer_int - to_edge.layer_int) AS layer_delta,
          {turn_angle_sql} AS turn_angle_deg,
          CASE WHEN {same_identity_sql} THEN 1 ELSE 0 END AS same_identity,
          CASE WHEN {route_continuity_sql} THEN 1 ELSE 0 END AS route_continuity,
          CASE WHEN {link_continuity_sql} THEN 1 ELSE 0 END AS link_continuity
        FROM cross_layer_osm_node_batches AS node_batch
        JOIN directed_edges AS from_edge INDEXED BY idx_directed_edges_to_osm_layer
          ON from_edge.to_osm_node_id = node_batch.osm_node_id
        JOIN directed_edges AS to_edge INDEXED BY idx_directed_edges_from_osm_layer
          ON to_edge.from_osm_node_id = node_batch.osm_node_id
         AND to_edge.layer_int != from_edge.layer_int
         AND to_edge.layer_int BETWEEN from_edge.layer_int - {CROSS_LAYER_SHARED_NODE_MAX_LAYER_DELTA}
                                   AND from_edge.layer_int + {CROSS_LAYER_SHARED_NODE_MAX_LAYER_DELTA}
        WHERE node_batch.batch_id = ?
          AND from_edge.road_id != to_edge.road_id
      )
      SELECT
        from_road_id, to_road_id, from_osm_id, to_osm_id, via_osm_node_id,
        from_priority, to_priority, from_is_ramp, to_is_ramp, layer_delta,
        turn_angle_deg, same_identity, route_continuity, link_continuity
      FROM candidates
      WHERE turn_angle_deg <= {CROSS_LAYER_SHARED_NODE_MAX_TURN_DEG}
        AND (
          same_identity = 1
          OR route_continuity = 1
          OR (from_priority >= 60 AND to_priority >= 60 AND turn_angle_deg <= {CROSS_LAYER_SHARED_NODE_MAJOR_TURN_DEG})
          OR (link_continuity = 1 AND turn_angle_deg <= {CROSS_LAYER_SHARED_NODE_LINK_TURN_DEG})
        )
    """
    for batch in range(batch_count):
      conn.set_progress_handler(
        progress.heartbeat(
          "layer_adjacency",
          80,
          f"finding cross-layer shared-node candidates batch={batch + 1:,}/{batch_count:,}",
          batch=batch + 1,
          batch_count=batch_count,
        ),
        100000,
      )
      conn.execute(candidate_sql, (batch,))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cross_layer_adjacency_candidates_from_to ON cross_layer_adjacency_candidates(from_road_id, to_road_id)")
  finally:
    conn.set_progress_handler(None, 0)

  candidate_count = int(conn.execute("SELECT COUNT(*) FROM cross_layer_adjacency_candidates").fetchone()[0])
  before_changes = conn.total_changes
  conn.set_progress_handler(progress.heartbeat("layer_adjacency", 80, "inserting cross-layer shared-node adjacency"), 100000)
  try:
    conn.execute(f"""
      INSERT OR IGNORE INTO road_adjacency(
        from_road_id, to_road_id, turn_angle_deg, blocked_transition, transition_cost, transition_probability,
        preferred_transition_score, flow_probability, connectivity_confidence
      )
      SELECT
        from_road_id,
        to_road_id,
        turn_angle_deg,
        CASE
          WHEN EXISTS (
            SELECT 1
            FROM turn_restrictions
            WHERE restriction LIKE 'no_%'
              AND from_osm_id = cross_layer_adjacency_candidates.from_osm_id
              AND to_osm_id = cross_layer_adjacency_candidates.to_osm_id
              AND (via_osm_id = 0 OR via_osm_id = cross_layer_adjacency_candidates.via_osm_node_id)
          ) THEN 1
          ELSE 0
        END AS blocked_transition,
        MAX(
          0.0,
          turn_angle_deg
          + 8.0
          + CASE WHEN to_is_ramp = 1 AND from_is_ramp = 0 THEN 10.0 ELSE 0.0 END
          - CASE WHEN same_identity = 1 THEN 18.0 ELSE 0.0 END
          - CASE WHEN route_continuity = 1 THEN 10.0 ELSE 0.0 END
          - to_priority * 0.04
        ) AS transition_cost,
        CASE
          WHEN same_identity = 1 THEN 0.88
          WHEN route_continuity = 1 THEN 0.78
          WHEN turn_angle_deg <= 15.0 THEN 0.72
          ELSE 0.55
        END AS transition_probability,
        CASE
          WHEN same_identity = 1 THEN 0.88
          WHEN route_continuity = 1 THEN 0.80
          WHEN turn_angle_deg <= 15.0 THEN 0.72
          ELSE 0.58
        END AS preferred_transition_score,
        CASE
          WHEN turn_angle_deg <= 15.0 THEN 0.82
          WHEN turn_angle_deg <= 30.0 THEN 0.68
          ELSE 0.50
        END AS flow_probability,
        {CROSS_LAYER_SHARED_NODE_CONNECTIVITY_CONFIDENCE} AS connectivity_confidence
      FROM cross_layer_adjacency_candidates
    """)
  finally:
    conn.set_progress_handler(None, 0)
  inserted_count = max(0, conn.total_changes - before_changes)

  conn.execute("CREATE INDEX IF NOT EXISTS idx_road_topology_from_to ON road_topology(from_road_id, to_road_id)")
  conn.execute("""
    INSERT INTO road_topology(from_road_id, to_road_id, topology_type, topology_inferred, inferred_reason)
    SELECT DISTINCT candidates.from_road_id, candidates.to_road_id, 'layer_transition', 1, 'shared_osm_node_cross_layer'
    FROM cross_layer_adjacency_candidates AS candidates
    JOIN road_adjacency AS adjacency
      ON adjacency.from_road_id = candidates.from_road_id
     AND adjacency.to_road_id = candidates.to_road_id
    WHERE NOT EXISTS (
      SELECT 1
      FROM road_topology
      WHERE road_topology.from_road_id = candidates.from_road_id
        AND road_topology.to_road_id = candidates.to_road_id
    )
  """)
  conn.execute("DROP TABLE IF EXISTS cross_layer_adjacency_candidates")
  conn.execute("DROP TABLE IF EXISTS cross_layer_entry_edges")
  conn.execute("DROP TABLE IF EXISTS cross_layer_exit_edges")
  conn.execute("DROP TABLE IF EXISTS cross_layer_osm_node_batches")
  conn.execute("DROP TABLE IF EXISTS cross_layer_osm_nodes")
  conn.commit()
  progress.emit(
    "layer_adjacency",
    80,
    f"cross-layer shared-node adjacency candidates={candidate_count:,} inserted={inserted_count:,}",
    force=True,
    candidates=candidate_count,
    inserted_rows=inserted_count,
  )
  return inserted_count


def _build_graph(conn: sqlite3.Connection, progress: ProgressReporter) -> None:
  progress.emit("graph_index", 60, "indexing directed graph edges", force=True)
  _execute_script_with_progress(conn, progress, """
    CREATE INDEX IF NOT EXISTS idx_directed_edges_from ON directed_edges(from_node_id);
    CREATE INDEX IF NOT EXISTS idx_directed_edges_to ON directed_edges(to_node_id);
    CREATE INDEX IF NOT EXISTS idx_directed_edges_from_osm_node ON directed_edges(from_osm_node_id);
    CREATE INDEX IF NOT EXISTS idx_directed_edges_to_osm_node ON directed_edges(to_osm_node_id);
    CREATE INDEX IF NOT EXISTS idx_directed_edges_from_osm_layer ON directed_edges(from_osm_node_id, layer_int);
    CREATE INDEX IF NOT EXISTS idx_directed_edges_to_osm_layer ON directed_edges(to_osm_node_id, layer_int);
    CREATE INDEX IF NOT EXISTS idx_turn_restrictions_from_to ON turn_restrictions(from_osm_id, to_osm_id);

    DROP TABLE IF EXISTS node_degrees;
    CREATE TEMP TABLE node_degrees AS
      SELECT node_id, COUNT(*) AS degree
      FROM (
        SELECT start_node_id AS node_id FROM road_edges
        UNION ALL
        SELECT end_node_id AS node_id FROM road_edges
      )
      GROUP BY node_id;
    CREATE INDEX IF NOT EXISTS idx_node_degrees_node ON node_degrees(node_id);

    UPDATE road_nodes
    SET node_degree = COALESCE((SELECT degree FROM node_degrees WHERE node_degrees.node_id = road_nodes.id), 0);
  """, "graph_index", 61, "indexing directed graph edges")

  progress.emit("adjacency_prepare", 62, "preparing road adjacency batches", force=True)
  conn.set_progress_handler(progress.heartbeat("adjacency_prepare", 63, "preparing road adjacency batches"), 100000)
  try:
    conn.execute("DROP TABLE IF EXISTS adjacency_node_batches")
    conn.execute(f"""
      CREATE TEMP TABLE adjacency_node_batches AS
      SELECT
        from_node_id,
        CAST((ROW_NUMBER() OVER (ORDER BY from_node_id) - 1) / {ADJACENCY_NODE_BATCH_SIZE} AS INTEGER) AS batch_id
      FROM (SELECT DISTINCT from_node_id FROM directed_edges)
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_adjacency_node_batches_batch ON adjacency_node_batches(batch_id, from_node_id)")
  finally:
    conn.set_progress_handler(None, 0)
  total_from_nodes = int(conn.execute("SELECT COUNT(*) FROM adjacency_node_batches").fetchone()[0])
  batch_count = int(conn.execute("SELECT COALESCE(MAX(batch_id) + 1, 0) FROM adjacency_node_batches").fetchone()[0])
  progress.emit(
    "adjacency",
    64,
    f"building road adjacency batches={batch_count:,} from_nodes={total_from_nodes:,}",
    force=True,
    batch=0,
    batch_count=batch_count,
    from_nodes=total_from_nodes,
  )
  adjacency_sql = """
    INSERT OR IGNORE INTO road_adjacency(
      from_road_id, to_road_id, turn_angle_deg, blocked_transition, transition_cost, transition_probability,
      preferred_transition_score, flow_probability, connectivity_confidence
    )
    SELECT
      from_edge.road_id,
      to_edge.road_id,
      CASE
        WHEN ABS(to_edge.bearing_deg - from_edge.bearing_deg) > 180.0
        THEN 360.0 - ABS(to_edge.bearing_deg - from_edge.bearing_deg)
        ELSE ABS(to_edge.bearing_deg - from_edge.bearing_deg)
      END AS turn_angle_deg,
      CASE
        WHEN EXISTS (
          SELECT 1
          FROM turn_restrictions
          WHERE restriction LIKE 'no_%'
            AND from_osm_id = from_edge.road_osm_id
            AND to_osm_id = to_edge.road_osm_id
            AND (via_osm_id = 0 OR via_osm_id = from_edge.to_osm_node_id)
        ) THEN 1
        ELSE 0
      END AS blocked_transition,
      MAX(
        0.0,
        CASE
          WHEN ABS(to_edge.bearing_deg - from_edge.bearing_deg) > 180.0
          THEN 360.0 - ABS(to_edge.bearing_deg - from_edge.bearing_deg)
          ELSE ABS(to_edge.bearing_deg - from_edge.bearing_deg)
        END
        + CASE WHEN to_edge.is_ramp = 1 AND from_edge.is_ramp = 0 THEN 10.0 ELSE 0.0 END
        - CASE WHEN from_edge.road_osm_id = to_edge.road_osm_id THEN 18.0 ELSE 0.0 END
        - CASE WHEN from_edge.ref != '' AND from_edge.ref = to_edge.ref THEN 10.0 ELSE 0.0 END
        - CASE WHEN from_edge.route_ref != '' AND from_edge.route_ref = to_edge.route_ref THEN 8.0 ELSE 0.0 END
        - to_edge.road_priority * 0.04
      ) AS transition_cost,
      CASE
        WHEN from_edge.road_osm_id = to_edge.road_osm_id THEN 0.95
        WHEN from_edge.ref != '' AND from_edge.ref = to_edge.ref THEN 0.80
        WHEN from_edge.route_ref != '' AND from_edge.route_ref = to_edge.route_ref THEN 0.75
        WHEN ABS(to_edge.bearing_deg - from_edge.bearing_deg) <= 25.0 THEN 0.65
        ELSE 0.20
      END AS transition_probability,
      CASE
        WHEN from_edge.road_osm_id = to_edge.road_osm_id THEN 0.95
        WHEN from_edge.ref != '' AND from_edge.ref = to_edge.ref THEN 0.82
        WHEN from_edge.route_ref != '' AND from_edge.route_ref = to_edge.route_ref THEN 0.78
        WHEN ABS(to_edge.bearing_deg - from_edge.bearing_deg) <= 25.0 THEN 0.62
        ELSE 0.25
      END AS preferred_transition_score,
      CASE
        WHEN ABS(to_edge.bearing_deg - from_edge.bearing_deg) <= 15.0 THEN 0.90
        WHEN ABS(to_edge.bearing_deg - from_edge.bearing_deg) <= 45.0 THEN 0.70
        WHEN ABS(to_edge.bearing_deg - from_edge.bearing_deg) <= 90.0 THEN 0.40
        ELSE 0.10
      END AS flow_probability,
      1.0 AS connectivity_confidence
    FROM directed_edges AS from_edge
    JOIN directed_edges AS to_edge ON from_edge.to_node_id = to_edge.from_node_id
    WHERE from_edge.road_id != to_edge.road_id
      AND from_edge.layer_int = to_edge.layer_int
      AND from_edge.from_node_id IN (
        SELECT from_node_id FROM adjacency_node_batches WHERE batch_id = ?
      )
  """
  inserted_total = 0
  for batch in range(batch_count):
    percent = 64 + int(((batch + 1) / max(1, batch_count)) * 14)
    before_changes = conn.total_changes
    conn.set_progress_handler(
      progress.heartbeat(
        "adjacency",
        percent,
        f"building road adjacency batch={batch + 1:,}/{batch_count:,}",
        batch=batch + 1,
        batch_count=batch_count,
        inserted_rows=inserted_total,
      ),
      100000,
    )
    try:
      conn.execute(adjacency_sql, (batch,))
    finally:
      conn.set_progress_handler(None, 0)
    inserted_total += max(0, conn.total_changes - before_changes)
    if batch == 0 or batch + 1 == batch_count or (batch + 1) % 10 == 0:
      progress.emit(
        "adjacency",
        percent,
        f"road adjacency batch {batch + 1:,}/{batch_count:,} inserted={inserted_total:,}",
        force=True,
        batch=batch + 1,
        batch_count=batch_count,
        inserted_rows=inserted_total,
      )
    if (batch + 1) % 25 == 0:
      conn.commit()
  conn.commit()

  progress.emit("topology", 79, "building road topology", force=True)
  _execute_script_with_progress(conn, progress, """
    INSERT INTO road_topology(from_road_id, to_road_id, topology_type, topology_inferred, inferred_reason)
    SELECT from_road_id, to_road_id, 'shared_node', 0, ''
    FROM road_adjacency;
  """, "topology", 79, "building road topology")

  _build_cross_layer_shared_node_adjacency(conn, progress)

  progress.emit("successor_rank", 81, "ranking road successors", force=True)
  _execute_script_with_progress(conn, progress, """
    DROP TABLE IF EXISTS ranked_successors;
    CREATE TEMP TABLE ranked_successors AS
      SELECT
        from_road_id,
        to_road_id,
        ROW_NUMBER() OVER (
          PARTITION BY from_road_id
          ORDER BY preferred_transition_score DESC, transition_cost ASC, turn_angle_deg ASC, to_road_id ASC
        ) AS successor_rank
      FROM road_adjacency
      WHERE blocked_transition = 0;
    CREATE INDEX IF NOT EXISTS idx_ranked_successors_from_rank ON ranked_successors(from_road_id, successor_rank);
  """, "successor_rank", 82, "ranking road successors")

  progress.emit("successor_update", 83, "updating preferred road successors", force=True)
  _execute_script_with_progress(conn, progress, """
    UPDATE road_adjacency
    SET
      preferred_successor_id = COALESCE((
        SELECT to_road_id FROM ranked_successors
        WHERE ranked_successors.from_road_id = road_adjacency.from_road_id
          AND successor_rank = 1
      ), 0),
      secondary_successor_id = COALESCE((
        SELECT to_road_id FROM ranked_successors
        WHERE ranked_successors.from_road_id = road_adjacency.from_road_id
          AND successor_rank = 2
      ), 0);
  """, "successor_update", 84, "updating preferred road successors")

  progress.emit("continuity", 86, "building road continuity cache", force=True)
  _execute_script_with_progress(conn, progress, """
    INSERT OR REPLACE INTO road_continuity_cache(
      road_id, preferred_successor_id, secondary_successor_id, motorway_continuity, ramp_continuity,
      destination_continuity, route_continuity, continuity_class
    )
    SELECT
      roads.id,
      COALESCE((SELECT to_road_id FROM ranked_successors WHERE ranked_successors.from_road_id = roads.id AND successor_rank = 1), 0),
      COALESCE((SELECT to_road_id FROM ranked_successors WHERE ranked_successors.from_road_id = roads.id AND successor_rank = 2), 0),
      CASE WHEN roads.highway IN ('motorway', 'trunk', 'primary') THEN 1.0 ELSE 0.0 END,
      CASE WHEN roads.is_ramp = 1 THEN 1.0 ELSE 0.0 END,
      CASE WHEN roads.destination != '' OR roads.destination_ref != '' THEN 1.0 ELSE 0.0 END,
      CASE WHEN roads.route_ref != '' OR roads.int_ref != '' OR roads.ref != '' THEN 1.0 ELSE 0.0 END,
      roads.continuity_class
    FROM roads;
  """, "continuity", 86, "building road continuity cache")


def _finalize_metadata(
  conn: sqlite3.Connection,
  pbf_path: Path,
  skipped_graph: bool,
  build_profile: str,
  included_highways: frozenset[str],
) -> None:
  roads_count = int(conn.execute("SELECT COUNT(*) FROM roads").fetchone()[0])
  graph_node_count = int(conn.execute("SELECT COUNT(*) FROM road_nodes").fetchone()[0])
  graph_edge_count = int(conn.execute("SELECT COUNT(*) FROM road_edges").fetchone()[0])
  graph_adjacency_count = int(conn.execute("SELECT COUNT(*) FROM road_adjacency").fetchone()[0])
  speed_camera_count = int(conn.execute("SELECT COUNT(*) FROM speed_cameras").fetchone()[0])
  speed_camera_match_count = int(conn.execute("SELECT COUNT(*) FROM speed_camera_road_matches").fetchone()[0])
  route_camera_lookup_count = int(conn.execute("SELECT COUNT(*) FROM route_camera_lookup").fetchone()[0])
  put_metadata(conn, {
    "version": 1,
    "built_at": int(datetime.now().timestamp()),
    "source_pbf": str(pbf_path),
    "build_profile": build_profile,
    "included_highways": ",".join(sorted(included_highways)),
    "excluded_highways": ",".join(sorted(DRIVABLE_HIGHWAYS - set(included_highways))),
    "segment_count": roads_count,
    "road_graph_skipped": 1 if skipped_graph else 0,
    "road_graph_node_count": graph_node_count,
    "road_graph_edge_count": graph_edge_count,
    "road_graph_adjacency_count": graph_adjacency_count,
    "road_topology_count": int(conn.execute("SELECT COUNT(*) FROM road_topology").fetchone()[0]),
    "lane_graph_count": int(conn.execute("SELECT COUNT(*) FROM lane_graph").fetchone()[0]),
    "motorway_junction_count": int(conn.execute("SELECT COUNT(*) FROM motorway_junctions").fetchone()[0]),
    "osm_relation_count": int(conn.execute("SELECT COUNT(*) FROM route_relations").fetchone()[0]),
    "speed_camera_count": speed_camera_count,
    "speed_camera_match_count": speed_camera_match_count,
    "route_camera_lookup_count": route_camera_lookup_count,
  })


def build_db(
  pbf_path: Path,
  tmp_db: Path,
  final_db: Path,
  build_graph: bool,
  require_road_graph: bool,
  require_speed_cameras: bool,
  quick_check: bool,
  progress_json: bool,
  build_profile: str,
  speed_cameras_csv: Path | None,
  speed_camera_source: str,
  speed_camera_match_radius_m: float,
  speed_camera_max_matches: int,
  replace_retries: int,
  replace_retry_delay_s: float,
) -> None:
  build_profile = _normalize_build_profile(build_profile)
  included_highways = BUILD_PROFILE_HIGHWAYS[build_profile]
  progress = ProgressReporter(enabled=progress_json, db_path=tmp_db)
  osmium = _load_osmium_module()
  if not pbf_path.exists():
    raise RuntimeError(f"PBF source missing: {pbf_path}")
  tmp_db.parent.mkdir(parents=True, exist_ok=True)
  tmp_db.unlink(missing_ok=True)
  ensure_navd_dirs(db_dir=final_db.parent, source_dir=pbf_path.parent, tmp_dir=tmp_db.parent)

  progress.emit(
    "profile",
    1,
    f"build profile={build_profile} included_highways={','.join(sorted(included_highways))}",
    force=True,
    build_profile=build_profile,
    included_highways=sorted(included_highways),
    excluded_highways=sorted(DRIVABLE_HIGHWAYS - set(included_highways)),
  )
  progress.emit("relations", 3, f"collecting OSM relations from {pbf_path}", force=True)
  relation_collector = OSMRelationCollector(osmium)
  class OSMRelationHandler(osmium.SimpleHandler):
    def relation(self, relation: Any) -> None:
      relation_collector.relation(relation)

  relation_handler = OSMRelationHandler()
  relation_handler.apply_file(str(pbf_path), locations=False)
  progress.emit(
    "relations",
    10,
    f"relations route={len(relation_collector.route_relations):,} route_members={sum(len(v) for v in relation_collector.route_members_by_way.values()):,} "
    f"turn_restrictions={len(relation_collector.turn_restrictions):,}",
    force=True,
    route_relations=len(relation_collector.route_relations),
    route_members=sum(len(v) for v in relation_collector.route_members_by_way.values()),
    turn_restrictions=len(relation_collector.turn_restrictions),
  )

  with closing(sqlite3.connect(tmp_db)) as conn:
    configure_build_connection(conn)
    create_osm_roads_schema(conn)
    _insert_relation_metadata(conn, relation_collector)
    builder = OSMRoadsBuilder(conn, pbf_path, relation_collector, build_graph, included_highways, progress)
    builder.prepare_temp_tables()
    class OSMWayHandler(osmium.SimpleHandler):
      def way(self, way: Any) -> None:
        builder.way(way)

    way_handler = OSMWayHandler()
    progress.emit("segments", 15, "building road segments", force=True)
    way_handler.apply_file(str(pbf_path), locations=True)
    builder.flush()
    progress.emit("segments", 55, f"built road segments: {builder.segment_count:,}", force=True, segments=builder.segment_count)
    if builder.segment_count <= 0:
      raise RuntimeError("no road segments were built from the PBF")
    if build_graph:
      _build_graph(conn, progress)
    if speed_cameras_csv is not None:
      progress.emit("speed_cameras", 87, f"matching speed cameras from {speed_cameras_csv}", force=True)
      summary = import_speed_cameras_from_csv(
        conn,
        speed_cameras_csv,
        source=speed_camera_source,
        match_radius_m=speed_camera_match_radius_m,
        max_matches_per_camera=speed_camera_max_matches,
        clear_existing=True,
      )
      progress.emit(
        "speed_cameras",
        87,
        f"speed cameras imported={summary.imported_count:,} matched={summary.matched_camera_count:,} lookup={summary.lookup_count:,}",
        force=True,
        speed_camera_count=summary.imported_count,
        speed_camera_matched_count=summary.matched_camera_count,
        speed_camera_match_count=summary.match_count,
        route_camera_lookup_count=summary.lookup_count,
      )
    progress.emit("indexes", 88, "creating indexes", force=True)
    conn.set_progress_handler(progress.heartbeat("indexes", 89, "creating indexes"), 100000)
    try:
      create_osm_roads_indexes(conn)
    finally:
      conn.set_progress_handler(None, 0)
    progress.emit("metadata", 91, "writing metadata", force=True)
    _finalize_metadata(conn, pbf_path, skipped_graph=not build_graph, build_profile=build_profile, included_highways=included_highways)
    progress.emit("analyze", 92, "analyzing sqlite query planner statistics", force=True)
    conn.set_progress_handler(progress.heartbeat("analyze", 92, "analyzing sqlite query planner statistics"), 100000)
    try:
      conn.execute("ANALYZE")
    finally:
      conn.set_progress_handler(None, 0)
    conn.commit()

  progress.emit("validate", 94, f"validating built DB {tmp_db}", force=True)
  validation = validate_osm_roads_db(
    tmp_db,
    require_road_graph=require_road_graph,
    require_speed_cameras=require_speed_cameras,
    run_quick_check=quick_check,
  )
  progress.emit(
    "validate",
    96,
    f"validated built DB segments={validation.segment_count:,} nodes={validation.graph_node_count:,} "
    f"edges={validation.graph_edge_count:,} adjacency={validation.graph_adjacency_count:,} "
    f"speed_cameras={validation.speed_camera_count:,} camera_lookup={validation.route_camera_lookup_count:,}",
    force=True,
    segments=validation.segment_count,
    graph_nodes=validation.graph_node_count,
    graph_edges=validation.graph_edge_count,
    graph_adjacency=validation.graph_adjacency_count,
    speed_camera_count=validation.speed_camera_count,
    route_camera_lookup_count=validation.route_camera_lookup_count,
  )
  progress.emit("replace", 98, f"installing built DB {final_db}", force=True)
  final_validation = replace_osm_roads_db(
    tmp_db,
    final_db,
    require_road_graph=require_road_graph,
    require_speed_cameras=require_speed_cameras,
    retry_attempts=replace_retries,
    retry_delay_s=replace_retry_delay_s,
  )
  progress.db_path = final_db
  progress.emit(
    "replace",
    100,
    f"installed built DB {final_db} ({final_validation.segment_count:,} segments, {final_validation.speed_camera_count:,} speed cameras)",
    force=True,
    segments=final_validation.segment_count,
    speed_camera_count=final_validation.speed_camera_count,
  )


def _replace_error_lines(error: OSMRoadsDBReplaceError) -> list[str]:
  return [
    "OSM roads DB build/validation succeeded, but final replacement failed.",
    str(error),
    f"current DB: {error.final_db}",
    f"backup DB: {error.backup_path}",
    f"pending DB: {error.pending_db}",
    "Close processes that may be reading the current DB, then rerun with --replace-only.",
  ]


def replace_pending_db(
  pending_db: Path,
  final_db: Path,
  require_road_graph: bool,
  require_speed_cameras: bool,
  progress_json: bool,
  replace_retries: int,
  replace_retry_delay_s: float,
) -> None:
  progress = ProgressReporter(enabled=progress_json, db_path=pending_db)
  progress.emit("validate", 94, f"validating pending DB {pending_db}", force=True)
  validation = install_pending_osm_roads_db(
    pending_db,
    final_db,
    require_road_graph=require_road_graph,
    require_speed_cameras=require_speed_cameras,
    retry_attempts=replace_retries,
    retry_delay_s=replace_retry_delay_s,
  )
  progress.db_path = final_db
  progress.emit(
    "replace",
    100,
    f"installed pending DB {final_db} ({validation.segment_count:,} segments, {validation.speed_camera_count:,} speed cameras)",
    force=True,
    segments=validation.segment_count,
    graph_nodes=validation.graph_node_count,
    graph_edges=validation.graph_edge_count,
    graph_adjacency=validation.graph_adjacency_count,
    speed_camera_count=validation.speed_camera_count,
    route_camera_lookup_count=validation.route_camera_lookup_count,
  )


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Build osm_roads_kr.sqlite3 from an OSM PBF source")
  parser.add_argument("--pbf", type=Path, default=DEFAULT_PBF, help=f"Input OSM PBF (default: {DEFAULT_PBF})")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"Output SQLite DB (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--tmp-db", type=Path, default=DEFAULT_TMP_DB, help=f"Temporary build DB (default: {DEFAULT_TMP_DB})")
  parser.add_argument("--skip-road-graph", action="store_true", help="Build only roads/rtree and mark road graph as skipped")
  parser.add_argument("--require-road-graph", action="store_true", help="Fail validation if the successor road graph is missing")
  parser.add_argument("--quick-check", action="store_true", help="Run SQLite PRAGMA quick_check during validation")
  parser.add_argument("--progress-json", action="store_true", help="Print machine-readable progress events prefixed with __osm_progress__")
  parser.add_argument(
    "--profile",
    "--build-profile",
    default="full",
    help="Road inclusion profile: full, camera-balanced, or major. Aliases: balanced, camera, camera-blanced",
  )
  parser.add_argument("--speed-cameras", type=Path, default=None, help="Optional speed camera CSV to import and match into the built DB")
  parser.add_argument("--speed-camera-source", default="", help="Source label for --speed-cameras metadata")
  parser.add_argument("--speed-camera-match-radius-m", type=float, default=DEFAULT_CAMERA_MATCH_RADIUS_M, help="Road snapping radius for speed cameras")
  parser.add_argument("--speed-camera-max-matches", type=int, default=3, help="Store up to this many road matches per speed camera")
  parser.add_argument("--require-speed-cameras", action="store_true", help="Fail validation if matched speed camera lookup data is missing")
  parser.add_argument("--validate-only", action="store_true", help="Validate --db and exit without building")
  parser.add_argument("--replace-only", action="store_true", help="Validate and install the pending built DB without rebuilding")
  parser.add_argument("--pending-db", type=Path, default=None, help="Pending DB to install with --replace-only (default: <db>.tmp)")
  parser.add_argument("--replace-retries", type=int, default=15, help="Number of final DB replace attempts")
  parser.add_argument("--replace-retry-delay-s", type=float, default=1.0, help="Seconds to wait between final DB replace attempts")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  try:
    if args.validate_only:
      validation = validate_osm_roads_db(
        args.db.expanduser(),
        require_road_graph=args.require_road_graph,
        require_speed_cameras=args.require_speed_cameras,
        run_quick_check=args.quick_check,
      )
      print(
        f"validated {validation.db_path}: segments={validation.segment_count:,} graph={int(validation.has_road_graph)} "
        f"nodes={validation.graph_node_count:,} edges={validation.graph_edge_count:,} adjacency={validation.graph_adjacency_count:,} "
        f"speed_cameras={validation.speed_camera_count:,} camera_lookup={validation.route_camera_lookup_count:,}",
        flush=True,
      )
      return 0

    if args.replace_only:
      final_db = args.db.expanduser()
      pending_db = args.pending_db.expanduser() if args.pending_db is not None else pending_osm_roads_db_path(final_db)
      if not pending_db.exists():
        raise SystemExit(f"pending DB missing: {pending_db}")
      replace_pending_db(
        pending_db,
        final_db,
        args.require_road_graph,
        args.require_speed_cameras,
        args.progress_json,
        args.replace_retries,
        args.replace_retry_delay_s,
      )
      return 0

    build_graph = not args.skip_road_graph
    if args.require_road_graph and not build_graph:
      raise RuntimeError("--require-road-graph cannot be used with --skip-road-graph")
    try:
      build_profile = _normalize_build_profile(args.profile)
    except ValueError as e:
      raise SystemExit(str(e)) from e
    speed_cameras_csv = args.speed_cameras.expanduser() if args.speed_cameras is not None else None
    build_db(
      args.pbf.expanduser(),
      args.tmp_db.expanduser(),
      args.db.expanduser(),
      build_graph,
      args.require_road_graph,
      args.require_speed_cameras,
      args.quick_check,
      args.progress_json,
      build_profile,
      speed_cameras_csv,
      args.speed_camera_source,
      args.speed_camera_match_radius_m,
      args.speed_camera_max_matches,
      args.replace_retries,
      args.replace_retry_delay_s,
    )
  except OSMRoadsDBReplaceError as e:
    for line in _replace_error_lines(e):
      print(line, file=sys.stderr, flush=True)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
