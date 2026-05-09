#!/usr/bin/env python3
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  import osmium
except ModuleNotFoundError:
  osmium = None

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, build_road_graph, init_db, insert_road_segments
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, build_road_graph, init_db, insert_road_segments

import sqlite3


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


class RoadSegmentHandler(osmium.SimpleHandler if osmium is not None else object):
  def __init__(self, conn: sqlite3.Connection, batch_size: int) -> None:
    if osmium is not None:
      super().__init__()
    self.conn = conn
    self.batch_size = batch_size
    self.segments: list[dict[str, object]] = []
    self.segment_count = 0
    self.way_count = 0
    self.skipped_ways = 0

  def way(self, way) -> None:
    highway = _tag(way.tags, "highway")
    if highway not in SUPPORTED_HIGHWAYS:
      return

    name = _tag(way.tags, "name:ko") or _tag(way.tags, "name")
    ref = _tag(way.tags, "ref")
    if not name and not ref:
      return

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
    row_base = {
      "osm_id": int(way.id),
      "name": name,
      "ref": ref,
      "highway": highway,
      "road_class": HIGHWAY_CLASS.get(highway, "ETC"),
      "oneway": _oneway(way.tags),
    }
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:], strict=False):
      if lat1 == lat2 and lon1 == lon2:
        continue
      self.segments.append({
        **row_base,
        "lat1": lat1,
        "lon1": lon1,
        "lat2": lat2,
        "lon2": lon2,
      })
      if len(self.segments) >= self.batch_size:
        self.flush()

  def flush(self) -> None:
    if not self.segments:
      return
    self.segment_count += insert_road_segments(self.conn, self.segments, replace=False)
    self.segments.clear()
    print(f"segments {self.segment_count}", flush=True)


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
    handler = RoadSegmentHandler(conn, max(1000, args.batch_size))
    handler.apply_file(str(args.pbf), locations=True)
    handler.flush()
    if args.skip_road_graph:
      graph_stats = None
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_node_count", "0"))
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_edge_count", "0"))
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_adjacency_count", "0"))
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_skipped", "1"))
    else:
      graph_stats = build_road_graph(conn)
      conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("road_graph_skipped", "0"))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("segment_count", str(handler.segment_count)))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("source_pbf", str(args.pbf)))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", ("built_at", str(int(time.time()))))

  elapsed = time.monotonic() - started
  print(f"built {handler.segment_count} road segments from {handler.way_count} ways into {args.db}")
  if graph_stats is None:
    print("graph skipped")
  else:
    print(f"graph {graph_stats.node_count} nodes, {graph_stats.edge_count} edges, {graph_stats.adjacency_count} transitions")
  if handler.skipped_ways:
    print(f"skipped {handler.skipped_ways} ways with invalid geometry")
  print(f"elapsed {elapsed:.1f}s")


if __name__ == "__main__":
  main()
