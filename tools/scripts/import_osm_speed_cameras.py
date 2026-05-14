#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH
  from openpilot.selfdrive.navd.osm_roads_db import validate_osm_roads_db
  from openpilot.selfdrive.navd.osm_speed_cameras import DEFAULT_CAMERA_MATCH_RADIUS_M, import_speed_cameras_from_csv
except ModuleNotFoundError:
  osm_roads = import_module("selfdrive.navd.osm_roads")
  osm_roads_db = import_module("selfdrive.navd.osm_roads_db")
  osm_speed_cameras = import_module("selfdrive.navd.osm_speed_cameras")
  DEFAULT_OSM_ROADS_DB_PATH = osm_roads.DEFAULT_OSM_ROADS_DB_PATH
  validate_osm_roads_db = osm_roads_db.validate_osm_roads_db
  DEFAULT_CAMERA_MATCH_RADIUS_M = osm_speed_cameras.DEFAULT_CAMERA_MATCH_RADIUS_M
  import_speed_cameras_from_csv = osm_speed_cameras.import_speed_cameras_from_csv


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Import speed cameras into osm_roads_kr.sqlite3 and match them to road IDs")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--csv", type=Path, required=True, help="Speed camera CSV path")
  parser.add_argument("--source", default="", help="Source label stored in metadata and speed_cameras.source")
  parser.add_argument("--match-radius-m", type=float, default=DEFAULT_CAMERA_MATCH_RADIUS_M, help="Road snapping radius in meters")
  parser.add_argument("--max-matches-per-camera", type=int, default=3, help="Store up to this many road matches per camera")
  parser.add_argument("--append", action="store_true", help="Append to existing speed camera tables instead of clearing them first")
  parser.add_argument("--require-road-graph", action="store_true", help="Validate that the DB has a road graph before importing")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  db_path = args.db.expanduser()
  validate_osm_roads_db(db_path, require_road_graph=args.require_road_graph)
  with closing(sqlite3.connect(db_path)) as conn:
    summary = import_speed_cameras_from_csv(
      conn,
      args.csv.expanduser(),
      source=args.source,
      match_radius_m=args.match_radius_m,
      max_matches_per_camera=args.max_matches_per_camera,
      clear_existing=not args.append,
    )
  print(
    f"speed cameras imported rows={summary.total_rows:,} cameras={summary.imported_count:,} skipped={summary.skipped_count:,} "
    f"matched_cameras={summary.matched_camera_count:,} matches={summary.match_count:,} lookup={summary.lookup_count:,}",
    flush=True,
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
