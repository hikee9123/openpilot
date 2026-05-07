#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.selfdrive.navd.speed_camera import (
    DEFAULT_CSV_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_REGION_DIR,
    DEFAULT_OSM_ROADS_DB_PATH,
    CsvSource,
    create_database_from_csvs,
    find_lead_camera,
  )
except ModuleNotFoundError:
  from selfdrive.navd.speed_camera import (
    DEFAULT_CSV_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_REGION_DIR,
    DEFAULT_OSM_ROADS_DB_PATH,
    CsvSource,
    create_database_from_csvs,
    find_lead_camera,
  )


def _csv_sources(args: argparse.Namespace) -> list[CsvSource]:
  sources: list[CsvSource] = []
  if args.csv.exists():
    sources.append(CsvSource(args.csv, "public"))

  if args.region_dir.exists() and args.region_dir.is_dir():
    for csv_path in sorted(args.region_dir.glob("*.csv")):
      sources.append(CsvSource(csv_path, "region"))

  for csv_path in args.extra_csv or []:
    if not csv_path.exists():
      raise FileNotFoundError(f"extra CSV does not exist: {csv_path}")
    sources.append(CsvSource(csv_path, "custom"))

  return sources


def _source_counts(csv_sources: list[CsvSource]) -> dict[str, int]:
  counts = {"public": 0, "region": 0, "custom": 0}
  for csv_source in csv_sources:
    counts[csv_source.source_type] = counts.get(csv_source.source_type, 0) + 1
  return counts


def main() -> None:
  parser = argparse.ArgumentParser(description="Import speed camera CSV data into the navid SQLite DB")
  parser.add_argument(
    "--csv",
    type=Path,
    default=DEFAULT_CSV_PATH,
    help=f"Public CSV path (default: {DEFAULT_CSV_PATH})",
  )
  parser.add_argument(
    "--region-dir",
    type=Path,
    default=DEFAULT_REGION_DIR,
    help=f"Directory containing regional CSV files (default: {DEFAULT_REGION_DIR})",
  )
  parser.add_argument("--extra-csv", type=Path, action="append", help="Additional custom CSV path; can be repeated")
  parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
  parser.add_argument(
    "--osm-roads-db",
    type=Path,
    default=None,
    help=f"Optional local OSM roads DB used to enrich camera road names (default: {DEFAULT_OSM_ROADS_DB_PATH})",
  )
  parser.add_argument("--osm-radius", type=float, default=60.0, help="OSM road-name enrichment radius in meters")
  parser.add_argument("--check", action="store_true", help="Run a lookup after import")
  parser.add_argument("--lat", type=float, help="Latitude for --check")
  parser.add_argument("--lon", type=float, help="Longitude for --check")
  parser.add_argument("--heading", type=float, default=0.0, help="Heading degrees for --check")
  args = parser.parse_args()

  csv_sources = _csv_sources(args)
  if not csv_sources:
    parser.error("no CSV sources found")

  osm_roads_db = args.osm_roads_db
  if osm_roads_db is None and DEFAULT_OSM_ROADS_DB_PATH.exists():
    osm_roads_db = DEFAULT_OSM_ROADS_DB_PATH

  count = create_database_from_csvs(csv_sources, args.db, osm_roads_db_path=osm_roads_db, osm_lookup_radius_m=args.osm_radius)
  counts = _source_counts(csv_sources)
  print(f"imported {count} speed cameras into {args.db}")
  print("sources:")
  print(f"  public: {counts.get('public', 0)}")
  print(f"  region: {counts.get('region', 0)}")
  print(f"  custom: {counts.get('custom', 0)}")
  if osm_roads_db is not None:
    print(f"osm roads: {osm_roads_db}")

  if args.check:
    if args.lat is None or args.lon is None:
      parser.error("--check requires --lat and --lon")
    camera = find_lead_camera(args.db, args.lat, args.lon, args.heading)
    if camera is None:
      print("no lead camera found")
    else:
      print(
        f"lead camera id={camera.id} distance={camera.distance_m:.0f}m "
        f"limit={camera.speed_limit} category={camera.camera_category} "
        f"roadClass={camera.road_class} place={camera.place}"
      )


if __name__ == "__main__":
  main()
