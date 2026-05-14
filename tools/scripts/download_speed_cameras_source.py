#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR, DEFAULT_NAVD_TMP_DIR, ensure_navd_dirs
except ModuleNotFoundError:
  navd_paths = import_module("selfdrive.navd.paths")
  DEFAULT_NAVD_SOURCE_DIR = navd_paths.DEFAULT_NAVD_SOURCE_DIR
  DEFAULT_NAVD_TMP_DIR = navd_paths.DEFAULT_NAVD_TMP_DIR
  ensure_navd_dirs = navd_paths.ensure_navd_dirs


PUBLIC_DATA_PK = "15028200"
PUBLIC_DATA_BASE_URL = "https://www.data.go.kr"
DATA_GO_KR_TIMEOUT_SECONDS = 30
DATA_GO_KR_RETRY_COUNT = 3
DATA_GO_KR_USER_AGENT = "Mozilla/5.0 (openpilot speed camera source downloader)"
DEFAULT_OUTPUT = DEFAULT_NAVD_SOURCE_DIR / "speed_cameras.csv"


def _fetch_data_go_json(path: str, params: dict[str, object], timeout: int = DATA_GO_KR_TIMEOUT_SECONDS) -> object:
  url = f"{PUBLIC_DATA_BASE_URL}{path}?{urlencode(params, doseq=True)}"
  request = Request(url, headers={"User-Agent": DATA_GO_KR_USER_AGENT, "Accept": "application/json"})
  for attempt in range(DATA_GO_KR_RETRY_COUNT):
    try:
      with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
    except OSError:
      if attempt == DATA_GO_KR_RETRY_COUNT - 1:
        raise
      time.sleep(1.0 + attempt)
  raise RuntimeError("unreachable retry state")


def download_public_speed_camera_csv(
  csv_path: Path,
  public_data_pk: str = PUBLIC_DATA_PK,
  per_page: int = 10000,
  max_pages: int | None = None,
  progress_callback: Callable[[int, int], None] | None = None,
  tmp_dir: Path | None = None,
) -> int:
  header = _fetch_data_go_json("/download/columList.json", {"pk": public_data_pk, "ext": "CSV"})
  if not isinstance(header, dict):
    raise RuntimeError(f"unexpected column metadata response: {type(header).__name__}")

  column_list = header.get("columList")
  table = header.get("tableVO")
  if not isinstance(column_list, list) or not isinstance(table, dict):
    raise RuntimeError("public data response is missing columList/tableVO")

  columns = [
    (str(item["columCode"]), str(item.get("columNm") or item.get("columCode")))
    for item in column_list
    if isinstance(item, dict) and item.get("columCode")
  ]
  column_codes = [code for code, _ in columns]
  column_names = [name for _, name in columns]
  if not column_codes:
    raise RuntimeError("public data response has invalid column metadata")

  total_count = int(header.get("totalCount") or 0)
  svc_table_name = str(table.get("svcTableNm") or "")
  col_name_list = table.get("colNmList") or column_codes
  if not total_count or not svc_table_name:
    raise RuntimeError("public data response has invalid totalCount/svcTableNm")

  per_page = max(1, min(10000, int(per_page)))
  page_count = math.ceil(total_count / per_page)
  if max_pages is not None:
    page_count = min(page_count, max(0, int(max_pages)))

  csv_path.parent.mkdir(parents=True, exist_ok=True)
  effective_tmp_dir = tmp_dir or csv_path.parent
  effective_tmp_dir.mkdir(parents=True, exist_ok=True)
  tmp_path = effective_tmp_dir / f"{csv_path.name}.download"
  written = 0
  if progress_callback is not None:
    progress_callback(written, total_count)

  try:
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as f:
      writer = csv.writer(f)
      writer.writerow(column_names)

      for page in range(1, page_count + 1):
        rows = _fetch_data_go_json("/download/standard.json", {
          "publicDataPk": public_data_pk,
          "colNmList": col_name_list,
          "totalCount": total_count,
          "svcTableNm": svc_table_name,
          "perPage": per_page,
          "page": page,
        })
        if not isinstance(rows, list):
          raise RuntimeError(f"unexpected public data response on page {page}: {type(rows).__name__}")

        for row in rows:
          if not isinstance(row, dict):
            continue
          writer.writerow([row.get(code, "") for code in column_codes])
          written += 1
        if progress_callback is not None:
          progress_callback(written, total_count)
    os.replace(tmp_path, csv_path)
  except Exception:
    tmp_path.unlink(missing_ok=True)
    raise

  return written


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Download the public speed camera CSV used by the OSM roads DB")
  parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"Output CSV path (default: {DEFAULT_OUTPUT})")
  parser.add_argument("--tmp-dir", type=Path, default=DEFAULT_NAVD_TMP_DIR, help=f"Temporary download directory (default: {DEFAULT_NAVD_TMP_DIR})")
  parser.add_argument("--public-data-pk", default=PUBLIC_DATA_PK, help=f"Public data portal PK (default: {PUBLIC_DATA_PK})")
  parser.add_argument("--per-page", type=int, default=10000, help="Rows per public data request")
  parser.add_argument("--max-pages", type=int, help="Limit downloaded pages for testing")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  output = args.output.expanduser()
  tmp_dir = args.tmp_dir.expanduser()
  ensure_navd_dirs(source_dir=output.parent, tmp_dir=tmp_dir)

  def progress(written: int, total: int) -> None:
    percent = int((written / max(1, total)) * 100)
    print(f"progress {percent}% ({written:,}/{total:,})", flush=True)

  print(f"fetching public speed camera metadata pk={args.public_data_pk}", flush=True)
  downloaded = download_public_speed_camera_csv(
    output,
    public_data_pk=args.public_data_pk,
    per_page=args.per_page,
    max_pages=args.max_pages,
    progress_callback=progress,
    tmp_dir=tmp_dir,
  )
  print(f"downloaded {downloaded:,} speed camera rows into {output}", flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
