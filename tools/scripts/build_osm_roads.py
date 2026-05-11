#!/usr/bin/env python3
import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  import osmium
except ModuleNotFoundError:
  osmium = None

try:
  from openpilot.selfdrive.navd.osm_roads import (
    DEFAULT_OSM_ROADS_DB_PATH,
    RAMP_HIGHWAYS,
    apply_osm_relation_hints,
    build_road_graph,
    estimate_road_width_m,
    infer_layer_int,
    infer_ramp_type,
    init_db,
    insert_road_segments,
    lane_count_from_tag,
    polyline_geometry_metrics,
    road_priority_for_highway,
    road_segment_length_m,
    route_level_for_tags,
    stable_group_id,
  )
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import (
    DEFAULT_OSM_ROADS_DB_PATH,
    RAMP_HIGHWAYS,
    apply_osm_relation_hints,
    build_road_graph,
    estimate_road_width_m,
    infer_layer_int,
    infer_ramp_type,
    init_db,
    insert_road_segments,
    lane_count_from_tag,
    polyline_geometry_metrics,
    road_priority_for_highway,
    road_segment_length_m,
    route_level_for_tags,
    stable_group_id,
  )


HIGHWAY_CLASS = {
  "motorway": "EXPRESSWAY",
  "motorway_link": "EXPRESSWAY",
  "trunk": "NATIONAL_ROAD",
  "trunk_link": "NATIONAL_ROAD",
  "primary": "NATIONAL_ROAD",
  "primary_link": "NATIONAL_ROAD",
  "secondary": "LOCAL_ROAD",
  "secondary_link": "LOCAL_ROAD",
  "tertiary": "LOCAL_ROAD",
  "tertiary_link": "LOCAL_ROAD",
  "unclassified": "CITY_ROAD",
  "residential": "CITY_ROAD",
  "living_street": "CITY_ROAD",
  "service": "ETC",
}

SUPPORTED_HIGHWAYS = set(HIGHWAY_CLASS)


def _format_memory_kb(kb: int) -> str:
  if kb >= 1024 * 1024:
    return f"{kb / (1024 * 1024):.1f} GB"
  if kb >= 1024:
    return f"{kb / 1024:.0f} MB"
  return f"{kb} KB"


def _memory_status_text() -> str:
  try:
    values: dict[str, int] = {}
    with open("/proc/self/status", encoding="utf-8") as status_file:
      for line in status_file:
        if line.startswith(("VmRSS:", "VmHWM:")):
          parts = line.split()
          if len(parts) >= 2:
            values[parts[0].rstrip(":")] = int(parts[1])
    rss = values.get("VmRSS")
    if rss is None:
      return ""
    peak = values.get("VmHWM", rss)
    return f"memory rss {_format_memory_kb(rss)} peak {_format_memory_kb(peak)}"
  except (OSError, ValueError):
    return ""


def _print_with_memory(prefix: str) -> None:
  memory_text = _memory_status_text()
  if memory_text:
    print(f"{prefix} {memory_text}", flush=True)
  else:
    print(prefix, flush=True)


def _print_phase_with_memory(progress: int, label: str, meaning: str) -> None:
  _print_with_memory(f"phase {progress}% {label} - {meaning}")


def _tag(tags, key: str) -> str:
  value = tags.get(key)
  return str(value) if value is not None else ""


def _oneway(tags) -> int:
  value = _tag(tags, "oneway").strip().lower()
  if value in ("yes", "true", "1"):
    return 1
  if value == "-1":
    return -1
  return 0


def _float_tag(tags, key: str) -> float:
  text = _tag(tags, key).strip().lower().replace(",", ".")
  if not text:
    return 0.0
  number = ""
  for char in text:
    if char.isdigit() or char in ".-":
      number += char
    elif number:
      break
  try:
    return float(number) if number else 0.0
  except ValueError:
    return 0.0


def _member_type(member) -> str:
  value = getattr(member, "type", "")
  if isinstance(value, bytes):
    return value.decode("ascii", errors="ignore")
  text = str(value)
  if text.endswith(".w") or text == "w" or "way" in text.lower():
    return "w"
  if text.endswith(".n") or text == "n" or "node" in text.lower():
    return "n"
  return text[:1].lower()


def _member_ref(member) -> int:
  try:
    return int(member.ref)
  except (TypeError, ValueError):
    return 0


def _member_role(member) -> str:
  return str(getattr(member, "role", "") or "")


def _way_member_ref(relation, role: str) -> int:
  for member in relation.members:
    if _member_role(member) == role and _member_type(member) == "w":
      return _member_ref(member)
  return 0


def _node_member_ref(relation, role: str) -> int:
  for member in relation.members:
    if _member_role(member) == role and _member_type(member) == "n":
      return _member_ref(member)
  return 0


def _route_relation_level(tags) -> int:
  route = _tag(tags, "route")
  ref = _tag(tags, "ref")
  network = _tag(tags, "network")
  if route in ("road", "motorway"):
    return route_level_for_tags("motorway" if route == "motorway" else "", ref, ref, "")
  if network.lower().startswith(("e-road", "asian_highway", "international")):
    return 5
  if network.lower().startswith(("kr:national", "national")):
    return 4
  return 2 if route else 0


def _should_store_way(highway: str, tags) -> bool:
  if highway not in SUPPORTED_HIGHWAYS:
    return False

  named_or_routed = any(_tag(tags, key) for key in (
    "name",
    "name:ko",
    "ref",
    "route_ref",
    "int_ref",
    "destination",
    "destination:ref",
    "junction",
  ))
  if named_or_routed:
    return True

  if highway in RAMP_HIGHWAYS:
    return True

  structured_major = highway in ("motorway", "trunk", "primary", "secondary") and any(_tag(tags, key) for key in (
    "tunnel",
    "covered",
    "bridge",
    "layer",
    "lanes",
    "maxspeed",
  ))
  if structured_major:
    return True

  service = _tag(tags, "service").strip().lower()
  if highway == "service" and service in ("parking_aisle", "driveway"):
    return False

  return False


class RoadSegmentHandler(osmium.SimpleHandler if osmium is not None else object):
  def __init__(self, conn: sqlite3.Connection, batch_size: int) -> None:
    if osmium is not None:
      super().__init__()
    self.conn = conn
    self.batch_size = batch_size
    self.segments: list[dict[str, object]] = []
    self.motorway_junctions: list[tuple[object, ...]] = []
    self.turn_restrictions: list[tuple[object, ...]] = []
    self.lane_connectivity: list[tuple[object, ...]] = []
    self.route_relations: list[tuple[object, ...]] = []
    self.route_members: list[tuple[object, ...]] = []
    self.segment_count = 0
    self.way_count = 0
    self.relation_count = 0
    self.motorway_junction_count = 0
    self.skipped_ways = 0

  def way(self, way) -> None:
    highway = _tag(way.tags, "highway")
    if not _should_store_way(highway, way.tags):
      return

    name = _tag(way.tags, "name:ko") or _tag(way.tags, "name")
    ref = _tag(way.tags, "ref")

    points: list[tuple[float, float]] = []
    try:
      for node in way.nodes:
        if node.location.valid():
          points.append((float(node.location.lat), float(node.location.lon)))
    except Exception:
      self.skipped_ways += 1
      return

    if len(points) < 2:
      return

    self.way_count += 1
    metrics = polyline_geometry_metrics(points)
    lane_count = lane_count_from_tag(_tag(way.tags, "lanes"))
    layer_int = infer_layer_int(_tag(way.tags, "layer"), _tag(way.tags, "tunnel"), _tag(way.tags, "bridge"), _tag(way.tags, "covered"))
    route_ref = _tag(way.tags, "route_ref")
    int_ref = _tag(way.tags, "int_ref")
    road_width, estimated_width = estimate_road_width_m(_tag(way.tags, "width"), lane_count)
    destination = _tag(way.tags, "destination")
    destination_ref = _tag(way.tags, "destination:ref")
    ramp_type = infer_ramp_type(
      highway,
      destination,
      destination_ref,
      _tag(way.tags, "junction"),
      float(metrics["curvature_avg"]),
      float(metrics["curvature_max"]),
      name,
    )
    row_base = {
      "osm_id": int(way.id),
      "name": name,
      "ref": ref,
      "highway": highway,
      "road_class": HIGHWAY_CLASS.get(highway, "ETC"),
      "oneway": _oneway(way.tags),
      "tunnel": _tag(way.tags, "tunnel"),
      "layer": _tag(way.tags, "layer"),
      "layer_int": layer_int,
      "covered": _tag(way.tags, "covered"),
      "bridge": _tag(way.tags, "bridge"),
      "junction": _tag(way.tags, "junction"),
      "destination": destination,
      "destination_ref": destination_ref,
      "destination_forward": _tag(way.tags, "destination:forward"),
      "destination_backward": _tag(way.tags, "destination:backward"),
      "destination_ref_forward": _tag(way.tags, "destination:ref:forward"),
      "destination_ref_backward": _tag(way.tags, "destination:ref:backward"),
      "lanes": _tag(way.tags, "lanes"),
      "lane_count": lane_count,
      "turn_lanes": _tag(way.tags, "turn:lanes"),
      "turn_lanes_forward": _tag(way.tags, "turn:lanes:forward"),
      "turn_lanes_backward": _tag(way.tags, "turn:lanes:backward"),
      "destination_lanes": _tag(way.tags, "destination:lanes"),
      "maxspeed": _tag(way.tags, "maxspeed"),
      "access": _tag(way.tags, "access"),
      "motor_vehicle": _tag(way.tags, "motor_vehicle"),
      "vehicle": _tag(way.tags, "vehicle"),
      "service": _tag(way.tags, "service"),
      "route_ref": route_ref,
      "int_ref": int_ref,
      "placement": _tag(way.tags, "placement"),
      "change_lanes": _tag(way.tags, "change:lanes"),
      "name_ko": _tag(way.tags, "name:ko"),
      "name_en": _tag(way.tags, "name:en"),
      "motorway_link": int(highway == "motorway_link"),
      "is_ramp": int(highway in RAMP_HIGHWAYS),
      "road_priority": road_priority_for_highway(highway),
      "route_level": route_level_for_tags(highway, ref, route_ref, int_ref),
      "ramp_type": ramp_type,
      "bearing_in": metrics["bearing_in"],
      "bearing_out": metrics["bearing_out"],
      "curvature_avg": metrics["curvature_avg"],
      "curvature_max": metrics["curvature_max"],
      "geometry_polyline": metrics["geometry_polyline"],
      "geometry_node_count": metrics["geometry_node_count"],
      "geometry_density": metrics["geometry_density"],
      "future_heading_min": metrics["future_heading_min"],
      "future_heading_max": metrics["future_heading_max"],
      "road_width": road_width,
      "estimated_width": estimated_width,
      "route_group_id": stable_group_id(ref, route_ref, int_ref, name, highway),
      "parallel_group_id": stable_group_id(ref, name, highway, layer_int),
      "future_corridor_polyline": metrics["geometry_polyline"],
    }
    segment_pairs = list(zip(points, points[1:], strict=False))
    for index, ((lat1, lon1), (lat2, lon2)) in enumerate(segment_pairs):
      if lat1 == lat2 and lon1 == lon2:
        continue
      segment_length = road_segment_length_m(lat1, lon1, lat2, lon2)
      self.segments.append({
        **row_base,
        "lat1": lat1,
        "lon1": lon1,
        "lat2": lat2,
        "lon2": lon2,
        "segment_length": segment_length,
        "tunnel_transition": int(bool(row_base["tunnel"]) and (index == 0 or index == len(segment_pairs) - 1)),
      })
      if len(self.segments) >= self.batch_size:
        self.flush()

  def node(self, node) -> None:
    if _tag(node.tags, "highway") != "motorway_junction":
      return
    try:
      if not node.location.valid():
        return
      lat = float(node.location.lat)
      lon = float(node.location.lon)
    except Exception:
      return
    self.motorway_junctions.append((
      int(node.id),
      _tag(node.tags, "ref"),
      _tag(node.tags, "name"),
      _tag(node.tags, "exit_to"),
      lat,
      lon,
      _float_tag(node.tags, "ele"),
    ))
    if len(self.motorway_junctions) >= self.batch_size:
      self.flush()

  def relation(self, relation) -> None:
    relation_type = _tag(relation.tags, "type")
    if relation_type not in ("restriction", "connectivity", "route"):
      return
    self.relation_count += 1
    relation_id = int(relation.id)

    if relation_type == "restriction":
      restriction = _tag(relation.tags, "restriction")
      if restriction not in (
        "no_left_turn",
        "no_right_turn",
        "no_u_turn",
        "only_right_turn",
        "only_left_turn",
        "only_straight_on",
      ):
        return
      self.turn_restrictions.append((
        relation_id,
        _way_member_ref(relation, "from"),
        _way_member_ref(relation, "via"),
        _way_member_ref(relation, "to"),
        _node_member_ref(relation, "from"),
        _node_member_ref(relation, "via"),
        _node_member_ref(relation, "to"),
        restriction,
      ))
    elif relation_type == "connectivity":
      self.lane_connectivity.append((
        relation_id,
        _way_member_ref(relation, "from"),
        _way_member_ref(relation, "to"),
        _node_member_ref(relation, "from"),
        _node_member_ref(relation, "to"),
        _tag(relation.tags, "connectivity") or _tag(relation.tags, "connectivity:lanes") or _tag(relation.tags, "lanes"),
      ))
    elif relation_type == "route":
      route = _tag(relation.tags, "route")
      ref = _tag(relation.tags, "ref")
      network = _tag(relation.tags, "network")
      route_level = _route_relation_level(relation.tags)
      self.route_relations.append((
        relation_id,
        route,
        ref,
        network,
        _tag(relation.tags, "name"),
        _tag(relation.tags, "operator"),
      ))
      for member in relation.members:
        if _member_type(member) != "w":
          continue
        self.route_members.append((
          relation_id,
          _member_ref(member),
          _member_role(member),
          ref,
          network,
          route_level,
        ))

    if (
      len(self.turn_restrictions) >= self.batch_size or
      len(self.lane_connectivity) >= self.batch_size or
      len(self.route_relations) >= self.batch_size or
      len(self.route_members) >= self.batch_size
    ):
      self.flush()

  def _flush_segments(self) -> None:
    if not self.segments:
      return
    self.segment_count += insert_road_segments(self.conn, self.segments, replace=False)
    self.segments.clear()
    _print_with_memory(f"segments {self.segment_count}")

  def _flush_motorway_junctions(self) -> None:
    if not self.motorway_junctions:
      return
    self.conn.executemany("""
      INSERT INTO motorway_junctions(osm_id, ref, name, exit_to, lat, lon, elevation)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    """, self.motorway_junctions)
    self.motorway_junction_count += len(self.motorway_junctions)
    self.motorway_junctions.clear()

  def _flush_turn_restrictions(self) -> None:
    if not self.turn_restrictions:
      return
    self.conn.executemany("""
      INSERT INTO turn_restrictions(
        relation_id, from_osm_id, via_osm_id, to_osm_id,
        from_node_id, via_node_id, to_node_id, restriction
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, self.turn_restrictions)
    self.turn_restrictions.clear()

  def _flush_lane_connectivity(self) -> None:
    if not self.lane_connectivity:
      return
    self.conn.executemany("""
      INSERT INTO lane_connectivity(relation_id, from_osm_id, to_osm_id, from_node_id, to_node_id, lanes)
      VALUES (?, ?, ?, ?, ?, ?)
    """, self.lane_connectivity)
    self.lane_connectivity.clear()

  def _flush_routes(self) -> None:
    if self.route_relations:
      self.conn.executemany("""
        INSERT OR IGNORE INTO route_relations(relation_id, route, ref, network, name, operator)
        VALUES (?, ?, ?, ?, ?, ?)
      """, self.route_relations)
      self.route_relations.clear()
    if self.route_members:
      self.conn.executemany("""
        INSERT INTO road_route_members(relation_id, osm_id, role, ref, network, route_level)
        VALUES (?, ?, ?, ?, ?, ?)
      """, self.route_members)
      self.route_members.clear()

  def flush(self) -> None:
    self._flush_segments()
    self._flush_motorway_junctions()
    self._flush_turn_restrictions()
    self._flush_lane_connectivity()
    self._flush_routes()


def main() -> None:
  parser = argparse.ArgumentParser(description="Build an offline OSM road-name SQLite DB for navd")
  parser.add_argument("pbf", type=Path, help="Input OSM PBF file, for example south-korea-latest.osm.pbf")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"Output SQLite DB (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--batch-size", type=int, default=20000, help="SQLite insert batch size")
  parser.add_argument(
    "--skip-road-graph",
    action="store_true",
    help="Skip the memory-heavy road successor graph build; current-road lookup still works",
  )
  args = parser.parse_args()

  if osmium is None:
    parser.error("pyosmium is required. Install it in the build environment with: pip install osmium")
  if not args.pbf.exists():
    parser.error(f"PBF does not exist: {args.pbf}")

  args.db.parent.mkdir(parents=True, exist_ok=True)
  started = time.monotonic()
  with sqlite3.connect(args.db) as conn:
    init_db(conn)
    conn.execute("DELETE FROM roads")
    conn.execute("DELETE FROM roads_rtree")
    conn.execute("DELETE FROM road_adjacency")
    conn.execute("DELETE FROM road_edges")
    conn.execute("DELETE FROM road_nodes")
    conn.execute("DELETE FROM turn_restrictions")
    conn.execute("DELETE FROM lane_connectivity")
    conn.execute("DELETE FROM lane_graph")
    conn.execute("DELETE FROM motorway_junctions")
    conn.execute("DELETE FROM road_topology")
    conn.execute("DELETE FROM route_relations")
    conn.execute("DELETE FROM road_route_members")
    conn.execute("DELETE FROM road_continuity_cache")
    handler = RoadSegmentHandler(conn, max(1000, args.batch_size))
    handler.apply_file(str(args.pbf), locations=True)
    handler.flush()
    _print_phase_with_memory(89, "Saving road segments", "PBF road segments are being written to SQLite")
    apply_osm_relation_hints(conn)
    if args.skip_road_graph:
      graph_stats = None
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_node_count", "0"))
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_edge_count", "0"))
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_adjacency_count", "0"))
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_skipped", "1"))
    else:
      _print_phase_with_memory(90, "Building road index", "Road graph and index tables are being generated")
      graph_stats = build_road_graph(conn)
      _print_phase_with_memory(92, "Writing metadata", "Segment count, built_at, and graph metadata are being stored")
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_skipped", "0"))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("segment_count", str(handler.segment_count)))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("osm_relation_count", str(handler.relation_count)))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("motorway_junction_count", str(handler.motorway_junction_count)))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("source_pbf", str(args.pbf)))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("built_at", str(int(time.time()))))
    _print_phase_with_memory(94, "Optimizing database", "SQLite commit and final database checks are running")

  elapsed = time.monotonic() - started
  print(f"built {handler.segment_count} road segments from {handler.way_count} ways into {args.db}")
  if graph_stats is None:
    print("graph skipped")
  else:
    print(f"graph {graph_stats.node_count} nodes, {graph_stats.edge_count} edges, {graph_stats.adjacency_count} transitions")
  if handler.skipped_ways:
    print(f"skipped {handler.skipped_ways} ways with invalid geometry")
  print(f"relations {handler.relation_count}, motorway junctions {handler.motorway_junction_count}")
  print(f"elapsed {elapsed:.1f}s")


if __name__ == "__main__":
  main()
