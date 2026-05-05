#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openpilot.selfdrive.navd.speed_camera import (
  DEFAULT_CSV_PATH,
  DEFAULT_DB_PATH,
  PUBLIC_DATA_PK,
  create_database_from_csv,
  download_public_speed_camera_csv,
)


def main() -> None:
  parser = argparse.ArgumentParser(description="Download public speed camera CSV data and import it into the navid SQLite DB")
  parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH, help=f"CSV path (default: {DEFAULT_CSV_PATH})")
  parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
  parser.add_argument("--public-data-pk", default=PUBLIC_DATA_PK, help=f"Public data portal PK (default: {PUBLIC_DATA_PK})")
  parser.add_argument("--per-page", type=int, default=10000, help="Rows per portal request (default: 10000)")
  parser.add_argument("--max-pages", type=int, help="Limit downloaded pages for testing")
  parser.add_argument("--download-only", action="store_true", help="Download CSV without importing the DB")
  args = parser.parse_args()

  downloaded = download_public_speed_camera_csv(args.csv, args.public_data_pk, args.per_page, args.max_pages)
  print(f"downloaded {downloaded} rows into {args.csv}")

  if args.download_only:
    return

  imported = create_database_from_csv(args.csv, args.db)
  print(f"imported {imported} speed cameras into {args.db}")


if __name__ == "__main__":
  main()
