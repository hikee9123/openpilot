#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openpilot.common.params import Params
from openpilot.selfdrive.navd.speed_camera import (
  DEFAULT_CSV_PATH,
  DEFAULT_DB_PATH,
  PUBLIC_DATA_PK,
  create_database_from_csv,
  download_public_speed_camera_csv,
)

SPEED_CAMERA_PROGRESS_KEY = "SpeedCameraUpdateProgress"


def _put_progress(params: Params, progress: int) -> None:
  try:
    params.put(SPEED_CAMERA_PROGRESS_KEY, max(0, min(100, int(progress))))
  except Exception:
    pass


def main() -> None:
  parser = argparse.ArgumentParser(description="Download public speed camera CSV data and import it into the navid SQLite DB")
  parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH, help=f"CSV path (default: {DEFAULT_CSV_PATH})")
  parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
  parser.add_argument("--public-data-pk", default=PUBLIC_DATA_PK, help=f"Public data portal PK (default: {PUBLIC_DATA_PK})")
  parser.add_argument("--per-page", type=int, default=10000, help="Rows per portal request (default: 10000)")
  parser.add_argument("--max-pages", type=int, help="Limit downloaded pages for testing")
  parser.add_argument("--download-only", action="store_true", help="Download CSV without importing the DB")
  args = parser.parse_args()

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
  )
  print(f"downloaded {downloaded} rows into {args.csv}")

  if args.download_only:
    _put_progress(params, 100)
    return

  _put_progress(params, 95)
  imported = create_database_from_csv(args.csv, args.db)
  _put_progress(params, 100)
  print(f"imported {imported} speed cameras into {args.db}")


if __name__ == "__main__":
  main()
