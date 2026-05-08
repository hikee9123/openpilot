#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.common.params import Params
except ImportError:
  class Params:
    def put(self, key: str, value: object) -> None:
      pass


try:
  from openpilot.selfdrive.navd.speed_camera import (
    DEFAULT_CSV_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_DOWNLOAD_TMP_DIR,
    DEFAULT_OSM_ROADS_DB_PATH,
    DEFAULT_REGION_DIR,
    PUBLIC_DATA_PK,
    CsvSource,
    create_database_from_csvs,
    database_data_date,
    database_osm_road_enrichment_stats,
    database_region_counts,
    download_public_speed_camera_csv,
  )
  from openpilot.selfdrive.navd.paths import ensure_navd_dirs
except ModuleNotFoundError:
  from selfdrive.navd.speed_camera import (
    DEFAULT_CSV_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_DOWNLOAD_TMP_DIR,
    DEFAULT_OSM_ROADS_DB_PATH,
    DEFAULT_REGION_DIR,
    PUBLIC_DATA_PK,
    CsvSource,
    create_database_from_csvs,
    database_data_date,
    database_osm_road_enrichment_stats,
    database_region_counts,
    download_public_speed_camera_csv,
  )
  from selfdrive.navd.paths import ensure_navd_dirs

SPEED_CAMERA_DATA_DATE_KEY = "SpeedCameraDataDate"
SPEED_CAMERA_PROGRESS_KEY = "SpeedCameraUpdateProgress"


def _put_progress(params: Params, progress: int) -> None:
  try:
    params.put(SPEED_CAMERA_PROGRESS_KEY, max(0, min(100, int(progress))))
  except Exception:
    pass


def _csv_sources(csv_path: Path, region_dir: Path, extra_csvs: list[Path] | None) -> list[CsvSource]:
  sources = [CsvSource(csv_path, "public")]

  if region_dir.exists() and region_dir.is_dir():
    sources.extend(CsvSource(path, "region") for path in sorted(region_dir.glob("*.csv")))

  for extra_csv in extra_csvs or []:
    if not extra_csv.exists():
      raise FileNotFoundError(f"extra CSV does not exist: {extra_csv}")
    sources.append(CsvSource(extra_csv, "custom"))

  return sources


def _source_counts(csv_sources: list[CsvSource]) -> dict[str, int]:
  counts = {"public": 0, "region": 0, "custom": 0}
  for csv_source in csv_sources:
    counts[csv_source.source_type] = counts.get(csv_source.source_type, 0) + 1
  return counts


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Download public speed camera CSV data and import it into the navid SQLite DB"
  )
  parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH, help=f"CSV path (default: {DEFAULT_CSV_PATH})")
  parser.add_argument(
    "--region-dir",
    type=Path,
    default=DEFAULT_REGION_DIR,
    help=f"Directory containing regional CSV files (default: {DEFAULT_REGION_DIR})",
  )
  parser.add_argument("--extra-csv", type=Path, action="append", help="Additional custom CSV path; can be repeated")
  parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
  parser.add_argument("--tmp-dir", type=Path, default=DEFAULT_DOWNLOAD_TMP_DIR, help=f"Temporary download directory (default: {DEFAULT_DOWNLOAD_TMP_DIR})")
  parser.add_argument(
    "--osm-roads-db",
    type=Path,
    default=None,
    help=f"Optional local OSM roads DB used to enrich camera road names (default: {DEFAULT_OSM_ROADS_DB_PATH})",
  )
  parser.add_argument("--osm-radius", type=float, default=60.0, help="OSM road-name enrichment radius in meters")
  parser.add_argument(
    "--public-data-pk",
    default=PUBLIC_DATA_PK,
    help=f"Public data portal PK (default: {PUBLIC_DATA_PK})",
  )
  parser.add_argument("--per-page", type=int, default=10000, help="Rows per portal request (default: 10000)")
  parser.add_argument("--max-pages", type=int, help="Limit downloaded pages for testing")
  parser.add_argument("--download-only", action="store_true", help="Download CSV without importing the DB")
  args = parser.parse_args()

  ensure_navd_dirs(
    db_dir=args.db.parent,
    source_dir=args.csv.parent,
    tmp_dir=args.tmp_dir,
    region_dir=args.region_dir,
  )

  params = Params()
  _put_progress(params, 0)

  def update_download_progress(written: int, total: int) -> None:
    progress = int((written / max(1, total)) * 90)
    _put_progress(params, progress)
    print(f"progress {progress}% ({written}/{total})", flush=True)

  downloaded = download_public_speed_camera_csv(
    args.csv,
    args.public_data_pk,
    args.per_page,
    args.max_pages,
    progress_callback=update_download_progress,
    tmp_dir=args.tmp_dir,
  )
  print(f"downloaded {downloaded} rows into {args.csv}")

  if args.download_only:
    _put_progress(params, 100)
    return

  _put_progress(params, 95)
  csv_sources = _csv_sources(args.csv, args.region_dir, args.extra_csv)
  osm_roads_db = args.osm_roads_db
  if osm_roads_db is None and DEFAULT_OSM_ROADS_DB_PATH.exists():
    osm_roads_db = DEFAULT_OSM_ROADS_DB_PATH
  imported = create_database_from_csvs(csv_sources, args.db, osm_roads_db_path=osm_roads_db, osm_lookup_radius_m=args.osm_radius)
  osm_stats = database_osm_road_enrichment_stats(args.db)
  data_date = database_data_date(args.db)
  region_counts = database_region_counts(args.db)
  source_counts = _source_counts(csv_sources)
  if data_date:
    params.put(SPEED_CAMERA_DATA_DATE_KEY, data_date)
  _put_progress(params, 100)
  print(f"imported {imported} speed cameras into {args.db}")
  print("sources:")
  print(f"  public: {source_counts.get('public', 0)}")
  print(f"  region: {source_counts.get('region', 0)}")
  print(f"  custom: {source_counts.get('custom', 0)}")
  if osm_roads_db is not None:
    print(f"osm roads {osm_roads_db}")
  print(f"osm road names primary matched {osm_stats.primary_match_count}")
  print(f"osm road names extended matched {osm_stats.extended_match_count} radius {osm_stats.extended_radius_m:.1f}m")
  print(f"osm road names matched {osm_stats.matched_count}")
  print(f"osm road names unmatched {osm_stats.unmatched_count}")
  if osm_stats.unmatched_by_category:
    print("osm road names unmatched by category:")
    for category, count in osm_stats.unmatched_by_category[:8]:
      print(f"  {category}: {count}")
  print(f"data date {data_date or 'unknown'}")
  print(f"regions {len(region_counts)}")


if __name__ == "__main__":
  main()
