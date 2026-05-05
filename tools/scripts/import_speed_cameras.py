#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openpilot.selfdrive.navd.speed_camera import (
  DEFAULT_CSV_PATH,
  DEFAULT_DB_PATH,
  create_database_from_csv,
  find_lead_camera,
)


def main() -> None:
  parser = argparse.ArgumentParser(description="Import public speed camera CSV data into the navid SQLite DB")
  parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH, help=f"CSV path (default: {DEFAULT_CSV_PATH})")
  parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
  parser.add_argument("--check", action="store_true", help="Run a lookup after import")
  parser.add_argument("--lat", type=float, help="Latitude for --check")
  parser.add_argument("--lon", type=float, help="Longitude for --check")
  parser.add_argument("--heading", type=float, default=0.0, help="Heading degrees for --check")
  args = parser.parse_args()

  count = create_database_from_csv(args.csv, args.db)
  print(f"imported {count} speed cameras into {args.db}")

  if args.check:
    if args.lat is None or args.lon is None:
      parser.error("--check requires --lat and --lon")
    camera = find_lead_camera(args.db, args.lat, args.lon, args.heading)
    if camera is None:
      print("no lead camera found")
    else:
      print(
        f"lead camera id={camera.id} distance={camera.distance_m:.0f}m "
        f"limit={camera.speed_limit} type={camera.camera_type} place={camera.place}"
      )


if __name__ == "__main__":
  main()
