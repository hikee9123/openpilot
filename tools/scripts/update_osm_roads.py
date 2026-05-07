#!/usr/bin/env python3
import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.common.params import Params
except ModuleNotFoundError:
  class Params:
    def put(self, key: str, value: object) -> None:
      pass

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, database_segment_count
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, database_segment_count


DEFAULT_OSM_PBF_URL = "https://download.geofabrik.de/asia/south-korea-latest.osm.pbf"
DEFAULT_OSM_PBF_PATH = DEFAULT_OSM_ROADS_DB_PATH.with_name("south-korea-latest.osm.pbf")
OSM_ROADS_PROGRESS_KEY = "OsmRoadsUpdateProgress"
OSM_ROADS_COUNT_KEY = "OsmRoadsSegmentCount"
OSM_USER_AGENT = "Mozilla/5.0 (openpilot OSM roads updater)"


def _put_progress(params: Params, progress: int) -> None:
  try:
    params.put(OSM_ROADS_PROGRESS_KEY, max(0, min(100, int(progress))))
  except Exception:
    pass


def _osmium_available() -> bool:
  return importlib.util.find_spec("osmium") is not None


def _install_osmium(params: Params) -> bool:
  print("osmium not installed; installing osmium", flush=True)
  _put_progress(params, 5)
  result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "osmium"],
    text=True,
    check=False,
  )
  if result.returncode != 0:
    print(f"osmium install failed: exit code {result.returncode}", flush=True)
    return False

  print("osmium install completed", flush=True)
  _put_progress(params, 10)
  return True


def _ensure_osmium(params: Params, auto_install: bool) -> bool:
  print("checking osmium", flush=True)
  if _osmium_available():
    print("osmium already installed", flush=True)
    return True
  if not auto_install:
    print("osmium is not installed; rerun without --no-auto-install-osmium or install with: pip install osmium", flush=True)
    return False
  return _install_osmium(params)


def _download(url: str, output_path: Path, params: Params) -> None:
  output_path.parent.mkdir(parents=True, exist_ok=True)
  tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
  request = Request(url, headers={"User-Agent": OSM_USER_AGENT})
  with urlopen(request, timeout=60) as response, tmp_path.open("wb") as out:
    total = int(response.headers.get("Content-Length") or 0)
    written = 0
    while True:
      chunk = response.read(1024 * 1024)
      if not chunk:
        break
      out.write(chunk)
      written += len(chunk)
      if total > 0:
        progress = int((written / total) * 70)
        _put_progress(params, progress)
        print(f"download {progress}% ({written}/{total})", flush=True)
      else:
        print(f"downloaded {written}", flush=True)
  os.replace(tmp_path, output_path)


def main() -> None:
  parser = argparse.ArgumentParser(description="Download South Korea OSM PBF and build the local OSM roads DB")
  parser.add_argument("--url", default=DEFAULT_OSM_PBF_URL, help=f"OSM PBF URL (default: {DEFAULT_OSM_PBF_URL})")
  parser.add_argument("--pbf", type=Path, default=DEFAULT_OSM_PBF_PATH, help=f"OSM PBF path (default: {DEFAULT_OSM_PBF_PATH})")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"Output SQLite DB (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--skip-download", action="store_true", help="Use the existing PBF file instead of downloading it")
  parser.add_argument("--keep-pbf", action="store_true", help="Keep the downloaded PBF after building the DB")
  parser.add_argument("--no-auto-install-osmium", action="store_true", help="Fail instead of trying to install osmium when it is missing")
  args = parser.parse_args()

  params = Params()
  _put_progress(params, 0)

  if not _ensure_osmium(params, not args.no_auto_install_osmium):
    return 1

  if not args.skip_download:
    print(f"downloading {args.url} -> {args.pbf}", flush=True)
    _download(args.url, args.pbf, params)
  elif not args.pbf.exists():
    parser.error(f"--skip-download requested but PBF does not exist: {args.pbf}")

  _put_progress(params, 75)
  print(f"building OSM roads DB {args.db}", flush=True)
  result = subprocess.run(
    [sys.executable, "tools/scripts/build_osm_roads.py", str(args.pbf), "--db", str(args.db)],
    cwd=Path(__file__).resolve().parents[2],
    text=True,
    check=False,
  )
  if result.returncode != 0:
    return result.returncode

  count = database_segment_count(args.db)
  try:
    params.put(OSM_ROADS_COUNT_KEY, count)
  except Exception:
    pass
  _put_progress(params, 100)
  print(f"osm road segments {count}", flush=True)

  if not args.keep_pbf:
    try:
      args.pbf.unlink()
    except OSError:
      pass
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
