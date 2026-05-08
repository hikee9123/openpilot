#!/usr/bin/env python3
import argparse
import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import time
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
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR, DEFAULT_NAVD_TMP_DIR
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, database_segment_count
  from selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR, DEFAULT_NAVD_TMP_DIR


DEFAULT_OSM_PBF_URL = "https://download.geofabrik.de/asia/south-korea-latest.osm.pbf"
DEFAULT_OSM_PBF_PATH = DEFAULT_NAVD_SOURCE_DIR / "south-korea-latest.osm.pbf"
OSM_ROADS_PROGRESS_KEY = "OsmRoadsUpdateProgress"
OSM_ROADS_COUNT_KEY = "OsmRoadsSegmentCount"
OSM_USER_AGENT = "Mozilla/5.0 (openpilot OSM roads updater)"
STALE_BUILD_SECONDS = 24 * 60 * 60


def _put_progress(params: Params, progress: int) -> None:
  try:
    params.put(OSM_ROADS_PROGRESS_KEY, max(0, min(100, int(progress))))
  except Exception:
    pass


def _osmium_available() -> bool:
  return importlib.util.find_spec("osmium") is not None


def _uv_binary() -> str | None:
  uv = shutil.which("uv")
  if uv is not None:
    return uv

  local_uv = Path.home() / ".local/bin/uv"
  if local_uv.exists():
    return str(local_uv)
  return None


def _install_osmium(params: Params) -> bool:
  print("osmium not installed; installing osmium", flush=True)
  _put_progress(params, 5)

  commands: list[tuple[str, list[str]]] = []
  uv = _uv_binary()
  if uv is not None:
    commands.append(("uv", [uv, "pip", "install", "--python", sys.executable, "osmium"]))
  commands.append(("pip", [sys.executable, "-m", "pip", "install", "osmium"]))

  for label, command in commands:
    print(f"trying {label} install", flush=True)
    result = subprocess.run(command, text=True, check=False)
    if result.returncode == 0:
      print(f"osmium install completed via {label}", flush=True)
      _put_progress(params, 10)
      return True
    print(f"osmium install via {label} failed: exit code {result.returncode}", flush=True)

  print("osmium install failed; install manually with: uv pip install --python "
        f"{sys.executable} osmium", flush=True)
  return False


def _ensure_osmium(params: Params, auto_install: bool) -> bool:
  print("checking osmium", flush=True)
  if _osmium_available():
    print("osmium already installed", flush=True)
    return True
  if not auto_install:
    print("osmium is not installed; rerun without --no-auto-install-osmium or install with: pip install osmium", flush=True)
    return False
  return _install_osmium(params)


def _download(url: str, output_path: Path, params: Params, tmp_dir: Path) -> None:
  output_path.parent.mkdir(parents=True, exist_ok=True)
  tmp_dir.mkdir(parents=True, exist_ok=True)
  tmp_path = tmp_dir / f"{output_path.name}.tmp"
  try:
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
  except Exception:
    _unlink_if_exists(tmp_path)
    raise


def _unlink_if_exists(path: Path) -> None:
  try:
    path.unlink()
  except FileNotFoundError:
    pass
  except OSError as e:
    print(f"failed to remove {path}: {e}", flush=True)


def _cleanup_stale_build_files(db_path: Path, tmp_dir: Path) -> None:
  now = time.time()
  paths = (
    tmp_dir / f"{db_path.name}.building",
    tmp_dir / f"{db_path.name}.tmp",
    db_path.with_suffix(db_path.suffix + ".building"),
    db_path.with_suffix(db_path.suffix + ".tmp"),
  )
  for path in paths:
    try:
      age = now - os.path.getmtime(path)
    except OSError:
      continue
    if age > STALE_BUILD_SECONDS:
      print(f"removing stale build file {path}", flush=True)
      _unlink_if_exists(path)


def _validate_osm_db(db_path: Path) -> int:
  if not db_path.exists():
    raise RuntimeError(f"temporary DB missing: {db_path}")
  count = database_segment_count(db_path)
  if count <= 0:
    raise RuntimeError(f"temporary DB has no road segments: {db_path}")
  try:
    with sqlite3.connect(db_path) as conn:
      for table in ("roads", "roads_rtree", "metadata"):
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE name = ? LIMIT 1", (table,)).fetchone()
        if row is None:
          raise RuntimeError(f"temporary DB missing table: {table}")
      conn.execute("SELECT COUNT(*) FROM roads").fetchone()
      conn.execute("SELECT COUNT(*) FROM roads_rtree").fetchone()
  except sqlite3.Error as e:
    raise RuntimeError(f"temporary DB validation failed: {e}") from e
  return count


def _replace_db_atomically(build_path: Path, final_path: Path) -> None:
  final_path.parent.mkdir(parents=True, exist_ok=True)
  backup_path = final_path.with_suffix(final_path.suffix + ".bak")
  if final_path.exists():
    print(f"backing up existing DB to {backup_path}", flush=True)
    os.replace(final_path, backup_path)
  try:
    print(f"replacing {final_path}", flush=True)
    os.replace(build_path, final_path)
  except Exception:
    if backup_path.exists() and not final_path.exists():
      print("restore existing DB from backup", flush=True)
      os.replace(backup_path, final_path)
    raise


def main() -> None:
  parser = argparse.ArgumentParser(description="Download South Korea OSM PBF and build the local OSM roads DB")
  parser.add_argument("--url", default=DEFAULT_OSM_PBF_URL, help=f"OSM PBF URL (default: {DEFAULT_OSM_PBF_URL})")
  parser.add_argument("--pbf", type=Path, default=DEFAULT_OSM_PBF_PATH, help=f"OSM PBF path (default: {DEFAULT_OSM_PBF_PATH})")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"Output SQLite DB (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--tmp-dir", type=Path, default=DEFAULT_NAVD_TMP_DIR, help=f"Temporary build directory (default: {DEFAULT_NAVD_TMP_DIR})")
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
    _download(args.url, args.pbf, params, args.tmp_dir)
  elif not args.pbf.exists():
    parser.error(f"--skip-download requested but PBF does not exist: {args.pbf}")

  _put_progress(params, 75)
  args.tmp_dir.mkdir(parents=True, exist_ok=True)
  _cleanup_stale_build_files(args.db, args.tmp_dir)
  build_db = args.tmp_dir / f"{args.db.name}.building"
  _unlink_if_exists(build_db)
  print(f"building temporary OSM roads DB {build_db}", flush=True)
  result = subprocess.run(
    [sys.executable, "tools/scripts/build_osm_roads.py", str(args.pbf), "--db", str(build_db)],
    cwd=Path(__file__).resolve().parents[2],
    text=True,
    check=False,
  )
  if result.returncode != 0:
    print(f"build failed; keeping existing DB {args.db}", flush=True)
    _unlink_if_exists(build_db)
    return result.returncode

  try:
    print("validating temporary OSM roads DB", flush=True)
    count = _validate_osm_db(build_db)
    print(f"validated temporary DB: {count} segments", flush=True)
    _replace_db_atomically(build_db, args.db)
  except Exception as e:
    print(f"validation or replace failed: {e}", flush=True)
    print(f"keeping existing DB {args.db}", flush=True)
    _unlink_if_exists(build_db)
    return 1

  try:
    params.put(OSM_ROADS_COUNT_KEY, count)
  except Exception:
    pass
  _put_progress(params, 80)
  print(f"osm road segments {count}", flush=True)

  if not args.keep_pbf:
    try:
      args.pbf.unlink()
    except OSError:
      pass
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
