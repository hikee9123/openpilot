#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.common.params import Params
except ModuleNotFoundError:
  class Params:
    def put(self, key: str, value: object) -> None:
      pass


try:
  from openpilot.selfdrive.navd.speed_camera import (
    DEFAULT_CSV_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_REGION_DIR,
    PUBLIC_DATA_PK,
    CsvSource,
    create_database_from_csvs,
    database_data_date,
    database_region_counts,
    download_public_speed_camera_csv,
  )
except ModuleNotFoundError:
  from selfdrive.navd.speed_camera import (
    DEFAULT_CSV_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_REGION_DIR,
    PUBLIC_DATA_PK,
    CsvSource,
    create_database_from_csvs,
    database_data_date,
    database_region_counts,
    download_public_speed_camera_csv,
  )

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
  parser.add_argument(
    "--public-data-pk",
    default=PUBLIC_DATA_PK,
    help=f"Public data portal PK (default: {PUBLIC_DATA_PK})",
  )
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
  csv_sources = _csv_sources(args.csv, args.region_dir, args.extra_csv)
  imported = create_database_from_csvs(csv_sources, args.db)
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
  print(f"data date {data_date or 'unknown'}")
  print(f"regions {len(region_counts)}")


if __name__ == "__main__":
  main()
