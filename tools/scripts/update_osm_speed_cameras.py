#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from contextlib import closing
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.common.params import Params
except Exception:
  class Params:
    def put(self, key: str, value: object) -> None:
      pass

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH
  from openpilot.selfdrive.navd.osm_roads_db import validate_osm_roads_db
  from openpilot.selfdrive.navd.osm_speed_cameras import DEFAULT_CAMERA_MATCH_RADIUS_M, import_speed_cameras_from_csv
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR, DEFAULT_NAVD_TMP_DIR, ensure_navd_dirs
  from openpilot.tools.scripts.download_speed_cameras_source import PUBLIC_DATA_PK, download_public_speed_camera_csv
except ModuleNotFoundError:
  osm_roads = import_module("selfdrive.navd.osm_roads")
  osm_roads_db = import_module("selfdrive.navd.osm_roads_db")
  osm_speed_cameras = import_module("selfdrive.navd.osm_speed_cameras")
  navd_paths = import_module("selfdrive.navd.paths")
  download_speed_cameras_source = import_module("tools.scripts.download_speed_cameras_source")
  DEFAULT_OSM_ROADS_DB_PATH = osm_roads.DEFAULT_OSM_ROADS_DB_PATH
  validate_osm_roads_db = osm_roads_db.validate_osm_roads_db
  DEFAULT_CAMERA_MATCH_RADIUS_M = osm_speed_cameras.DEFAULT_CAMERA_MATCH_RADIUS_M
  import_speed_cameras_from_csv = osm_speed_cameras.import_speed_cameras_from_csv
  DEFAULT_NAVD_SOURCE_DIR = navd_paths.DEFAULT_NAVD_SOURCE_DIR
  DEFAULT_NAVD_TMP_DIR = navd_paths.DEFAULT_NAVD_TMP_DIR
  ensure_navd_dirs = navd_paths.ensure_navd_dirs
  PUBLIC_DATA_PK = download_speed_cameras_source.PUBLIC_DATA_PK
  download_public_speed_camera_csv = download_speed_cameras_source.download_public_speed_camera_csv


DEFAULT_SPEED_CAMERA_CSV = DEFAULT_NAVD_SOURCE_DIR / "speed_cameras.csv"
STATUS_KEY = "OsmSpeedCamerasUpdateStatus"
ERROR_KEY = "OsmSpeedCamerasUpdateError"
PROGRESS_KEY = "OsmSpeedCamerasUpdateProgress"
UPDATED_AT_KEY = "OsmSpeedCamerasUpdatedAt"
CSV_KEY = "OsmSpeedCamerasCsvPath"
DOWNLOAD_ROWS_KEY = "OsmSpeedCamerasDownloadRows"
DOWNLOAD_TOTAL_KEY = "OsmSpeedCamerasDownloadTotalRows"
IMPORTED_KEY = "OsmSpeedCamerasImportedCount"
MATCHED_KEY = "OsmSpeedCamerasMatchedCount"
LOOKUP_KEY = "OsmSpeedCamerasLookupCount"


def _put_param(params: Params, key: str, value: object) -> None:
  try:
    params.put(key, value)
  except Exception:
    pass


def _put_progress(params: Params, progress: int) -> None:
  _put_param(params, PROGRESS_KEY, max(0, min(100, int(progress))))


def _now_text() -> str:
  return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Download public speed camera data and rematch it into osm_roads_kr.sqlite3")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--csv", type=Path, default=DEFAULT_SPEED_CAMERA_CSV, help=f"Speed camera CSV path (default: {DEFAULT_SPEED_CAMERA_CSV})")
  parser.add_argument("--tmp-dir", type=Path, default=DEFAULT_NAVD_TMP_DIR, help=f"Temporary download directory (default: {DEFAULT_NAVD_TMP_DIR})")
  parser.add_argument("--public-data-pk", default=PUBLIC_DATA_PK, help=f"Public data portal PK (default: {PUBLIC_DATA_PK})")
  parser.add_argument("--per-page", type=int, default=10000, help="Rows per public data request")
  parser.add_argument("--max-pages", type=int, help="Limit downloaded pages for testing")
  parser.add_argument("--match-radius-m", type=float, default=DEFAULT_CAMERA_MATCH_RADIUS_M, help="Road snapping radius in meters")
  parser.add_argument("--max-matches-per-camera", type=int, default=3, help="Store up to this many road matches per speed camera")
  parser.add_argument("--require-road-graph", action="store_true", help="Validate that the DB has a road graph before matching")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  db_path = args.db.expanduser()
  csv_path = args.csv.expanduser()
  tmp_dir = args.tmp_dir.expanduser()
  params = Params()

  _put_param(params, STATUS_KEY, "running")
  _put_param(params, ERROR_KEY, "")
  _put_param(params, CSV_KEY, str(csv_path))
  _put_param(params, DOWNLOAD_ROWS_KEY, 0)
  _put_param(params, DOWNLOAD_TOTAL_KEY, 0)
  _put_param(params, IMPORTED_KEY, 0)
  _put_param(params, MATCHED_KEY, 0)
  _put_param(params, LOOKUP_KEY, 0)
  _put_progress(params, 1)

  try:
    ensure_navd_dirs(db_dir=db_path.parent, source_dir=csv_path.parent, tmp_dir=tmp_dir)
    print(f"validating OSM roads DB {db_path}", flush=True)
    validate_osm_roads_db(db_path, require_road_graph=args.require_road_graph)
    _put_progress(params, 5)

    print(f"downloading speed camera CSV to {csv_path}", flush=True)
    def progress(written: int, total: int) -> None:
      _put_param(params, DOWNLOAD_ROWS_KEY, max(0, int(written)))
      _put_param(params, DOWNLOAD_TOTAL_KEY, max(0, int(total)))
      _put_progress(params, 5 + int((written / max(1, total)) * 50))
      print(f"download progress {written:,}/{total:,}", flush=True)

    downloaded = download_public_speed_camera_csv(
      csv_path,
      public_data_pk=args.public_data_pk,
      per_page=args.per_page,
      max_pages=args.max_pages,
      progress_callback=progress,
      tmp_dir=tmp_dir,
    )
    _put_param(params, DOWNLOAD_ROWS_KEY, int(downloaded))
    _put_progress(params, 60)

    print(f"matching speed cameras into {db_path}", flush=True)
    with closing(sqlite3.connect(db_path)) as conn:
      summary = import_speed_cameras_from_csv(
        conn,
        csv_path,
        match_radius_m=args.match_radius_m,
        max_matches_per_camera=args.max_matches_per_camera,
        clear_existing=True,
      )

    _put_param(params, IMPORTED_KEY, int(summary.imported_count))
    _put_param(params, MATCHED_KEY, int(summary.matched_camera_count))
    _put_param(params, LOOKUP_KEY, int(summary.lookup_count))
    _put_progress(params, 100)
    _put_param(params, UPDATED_AT_KEY, _now_text())
    _put_param(params, STATUS_KEY, "success")
    _put_param(params, ERROR_KEY, "")
    print(
      f"speed cameras updated rows={summary.total_rows:,} cameras={summary.imported_count:,} "
      f"skipped={summary.skipped_count:,} matched_cameras={summary.matched_camera_count:,} "
      f"matches={summary.match_count:,} lookup={summary.lookup_count:,}",
      flush=True,
    )
    return 0
  except Exception as e:
    _put_param(params, STATUS_KEY, "failed")
    _put_param(params, ERROR_KEY, str(e))
    print(f"speed camera update failed: {e}", flush=True)
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
