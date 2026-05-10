#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import select
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.common.params import Params
except Exception:
  class Params:
    def put(self, key: str, value: object) -> None:
      pass

from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, database_segment_count
from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_TMP_DIR, ensure_navd_dirs


DEFAULT_REPO_URL = "https://github.com/hikee9123/data_nev.git"
DEFAULT_REPO_REF = "main"
DEFAULT_REPO_DB_PATH = Path("db/osm_roads_kr.sqlite3")
OSM_ROADS_PROGRESS_KEY = "OsmRoadsUpdateProgress"
OSM_ROADS_COUNT_KEY = "OsmRoadsSegmentCount"
OSM_ROADS_STATUS_KEY = "OsmRoadsUpdateStatus"
OSM_ROADS_ERROR_KEY = "OsmRoadsUpdateError"
OSM_ROADS_UPDATED_AT_KEY = "OsmRoadsUpdatedAt"
OSM_ROADS_DOWNLOAD_BYTES_KEY = "OsmRoadsDownloadBytes"
OSM_ROADS_DOWNLOAD_TOTAL_BYTES_KEY = "OsmRoadsDownloadTotalBytes"


def _put_param(params: Params, key: str, value: object) -> None:
  try:
    params.put(key, value)
  except Exception:
    pass


def _put_progress(params: Params, progress: int) -> None:
  _put_param(params, OSM_ROADS_PROGRESS_KEY, max(0, min(100, int(progress))))


def _put_segment_count(params: Params, count: int) -> None:
  _put_param(params, OSM_ROADS_COUNT_KEY, max(0, int(count)))


def _put_download_size(params: Params, downloaded_bytes: int, total_bytes: int = 0) -> None:
  _put_param(params, OSM_ROADS_DOWNLOAD_BYTES_KEY, str(max(0, int(downloaded_bytes))))
  _put_param(params, OSM_ROADS_DOWNLOAD_TOTAL_BYTES_KEY, str(max(0, int(total_bytes))))


def _format_bytes(size_bytes: int) -> str:
  value = float(max(0, int(size_bytes)))
  for unit in ("B", "KB", "MB", "GB"):
    if value < 1024.0 or unit == "GB":
      return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
    value /= 1024.0
  return f"{value:.1f} GB"


def _path_state(label: str, path: Path) -> str:
  try:
    stat_result = path.stat()
  except FileNotFoundError:
    return f"{label} missing path={path}"
  except OSError as e:
    return f"{label} stat failed path={path}: {e}"

  kind = "dir" if path.is_dir() else "file"
  modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat_result.st_mtime))
  return f"{label} {kind} path={path} size={_format_bytes(stat_result.st_size)} mtime={modified}"


def _run_diagnostic(command: list[str], cwd: Path | None = None) -> None:
  where = f" cwd={cwd}" if cwd is not None else ""
  print(f"$ diag {' '.join(command)}{where}", flush=True)
  try:
    result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
  except Exception as e:
    print(f"diagnostic command failed: {e}", flush=True)
    return

  output = (result.stdout or "").strip()
  if output:
    for line in output.splitlines()[-80:]:
      print(line, flush=True)
  print(f"diagnostic exit code {result.returncode}", flush=True)


def _log_install_diagnostics(args: argparse.Namespace, clone_dir: Path) -> None:
  print("OSM roads install diagnostics", flush=True)
  print(f"cwd {Path.cwd()}", flush=True)
  print(f"python {sys.executable} {sys.version.split()[0]}", flush=True)
  print(f"target DB {args.db}", flush=True)
  print(f"tmp dir {args.tmp_dir}", flush=True)
  print(f"clone dir {clone_dir}", flush=True)
  print(f"repo {args.repo}", flush=True)
  print(f"ref {args.ref}", flush=True)
  print(f"repo DB path {args.repo_db_path}", flush=True)
  print(_path_state("target DB", args.db), flush=True)
  print(_path_state("tmp dir", args.tmp_dir), flush=True)
  print(_path_state("existing clone", clone_dir), flush=True)
  _run_diagnostic(["git", "--version"])
  _run_diagnostic(["git", "lfs", "version"])
  _run_diagnostic(["df", "-h", str(args.db.parent), str(args.tmp_dir)])


def _log_lfs_pointer(pointer_path: Path) -> None:
  print(_path_state("repo DB pointer", pointer_path), flush=True)
  try:
    data = pointer_path.read_bytes()[:1024]
    for line in data.decode("utf-8").splitlines()[:8]:
      value = line.strip()
      if value:
        print(f"lfs pointer {value}", flush=True)
  except (OSError, UnicodeDecodeError) as e:
    print(f"failed to read LFS pointer {pointer_path}: {e}", flush=True)


def _log_failure_diagnostics(args: argparse.Namespace, clone_dir: Path) -> None:
  print("OSM roads install failure diagnostics", flush=True)
  print(_path_state("target DB", args.db), flush=True)
  print(_path_state("backup DB", args.db.with_suffix(args.db.suffix + ".bak")), flush=True)
  print(_path_state("install tmp DB", args.db.with_suffix(args.db.suffix + ".git.tmp")), flush=True)
  print(_path_state("clone dir", clone_dir), flush=True)
  print(_path_state("repo DB", clone_dir / args.repo_db_path), flush=True)

  incomplete_dir = clone_dir / ".git" / "lfs" / "incomplete"
  print(_path_state("LFS incomplete dir", incomplete_dir), flush=True)
  try:
    for path in sorted(incomplete_dir.iterdir()):
      if path.is_file():
        print(_path_state("LFS incomplete", path), flush=True)
  except OSError as e:
    print(f"failed to list LFS incomplete dir {incomplete_dir}: {e}", flush=True)

  if clone_dir.exists():
    _run_diagnostic(["git", "status", "--short"], cwd=clone_dir)
    _run_diagnostic(["git", "lfs", "logs", "last"], cwd=clone_dir)


def _lfs_pointer_size(pointer_path: Path) -> int:
  try:
    with pointer_path.open("r", encoding="utf-8") as f:
      for line in f:
        if line.startswith("size "):
          return max(0, int(line.split()[1]))
  except (OSError, UnicodeDecodeError, ValueError, IndexError):
    pass
  return 0


def _largest_lfs_incomplete_size(repo_dir: Path) -> int:
  incomplete_dir = repo_dir / ".git" / "lfs" / "incomplete"
  try:
    return max((path.stat().st_size for path in incomplete_dir.iterdir() if path.is_file()), default=0)
  except OSError:
    return 0


def _run(
  command: list[str],
  cwd: Path | None = None,
  env: dict[str, str] | None = None,
  params: Params | None = None,
  progress_start: int | None = None,
  progress_end: int | None = None,
  download_total_bytes: int = 0,
) -> None:
  where = f" cwd={cwd}" if cwd is not None else ""
  print(f"$ {' '.join(command)}{where}", flush=True)
  last_lines: list[str] = []
  with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
    assert process.stdout is not None
    started_at = time.monotonic()
    last_heartbeat = started_at
    while True:
      ready, _, _ = select.select([process.stdout], [], [], 1.0)
      if ready:
        line = process.stdout.readline()
        if line:
          stripped = line.rstrip()
          print(stripped, flush=True)
          if stripped:
            last_lines.append(stripped)
            last_lines = last_lines[-16:]
        elif process.poll() is not None:
          break
      elif process.poll() is not None:
        break

      now = time.monotonic()
      if now - last_heartbeat >= 15.0 and process.poll() is None:
        elapsed = int(now - started_at)
        downloaded_bytes = _largest_lfs_incomplete_size(cwd) if cwd is not None and download_total_bytes > 0 else 0
        download_text = ""
        if downloaded_bytes > 0:
          _put_download_size(params, downloaded_bytes, download_total_bytes) if params is not None else None
          download_text = f" downloaded {_format_bytes(downloaded_bytes)} / {_format_bytes(download_total_bytes)}"
        print(f"... still running {' '.join(command)} ({elapsed}s){download_text}", flush=True)
        if params is not None and progress_start is not None and progress_end is not None and progress_end > progress_start:
          if downloaded_bytes > 0 and download_total_bytes > 0:
            fraction = min(1.0, downloaded_bytes / download_total_bytes)
            progress = min(progress_end - 1, progress_start + int((progress_end - progress_start) * fraction))
          else:
            progress = min(progress_end - 1, progress_start + elapsed // 20)
          _put_progress(params, progress)
        last_heartbeat = now
    returncode = process.wait()
  if returncode != 0:
    detail = next((line for line in reversed(last_lines) if "batch response" in line.lower()), "")
    if not detail:
      detail = next(
        (line for line in reversed(last_lines)
         if any(token in line.lower() for token in ("error", "failed", "fatal"))),
        "",
      )
    suffix = f": {detail}" if detail else ""
    raise RuntimeError(f"command failed with exit code {returncode}: {' '.join(command)}{suffix}")


def _unlink_if_exists(path: Path) -> None:
  try:
    path.unlink()
  except FileNotFoundError:
    pass


def _rmtree_onerror(function, path: str, _exc_info) -> None:
  os.chmod(path, stat.S_IWRITE)
  function(path)


def _rmtree_if_exists(path: Path, required: bool = True) -> None:
  if not path.exists():
    return
  try:
    shutil.rmtree(path, onerror=_rmtree_onerror)
  except OSError as e:
    if required:
      raise
    print(f"failed to remove temporary clone {path}: {e}", flush=True)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
  row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1", (table,)).fetchone()
  return row is not None


def _metadata_value(conn: sqlite3.Connection, key: str) -> str:
  row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
  return str(row[0]) if row and row[0] is not None else ""


def _metadata_int(conn: sqlite3.Connection, key: str) -> int:
  try:
    return int(_metadata_value(conn, key))
  except ValueError:
    return 0


def _validate_osm_db(db_path: Path, require_road_graph: bool) -> int:
  if not db_path.exists():
    raise RuntimeError(f"downloaded DB missing: {db_path}")

  try:
    with closing(sqlite3.connect(db_path)) as conn:
      for table in ("roads", "roads_rtree", "metadata"):
        if not _table_exists(conn, table):
          raise RuntimeError(f"downloaded DB missing table: {table}")

      segment_count = database_segment_count(db_path)
      roads_count = int(conn.execute("SELECT COUNT(*) FROM roads").fetchone()[0])
      rtree_count = int(conn.execute("SELECT COUNT(*) FROM roads_rtree").fetchone()[0])
      if segment_count <= 0:
        segment_count = roads_count
      if roads_count <= 0 or rtree_count <= 0:
        raise RuntimeError(f"downloaded DB has no road segments: roads={roads_count}, rtree={rtree_count}")
      if roads_count != rtree_count:
        raise RuntimeError(f"downloaded DB row count mismatch: roads={roads_count}, rtree={rtree_count}")

      graph_nodes = _metadata_int(conn, "road_graph_node_count")
      graph_edges = _metadata_int(conn, "road_graph_edge_count")
      graph_adjacency = _metadata_int(conn, "road_graph_adjacency_count")
      graph_skipped = _metadata_value(conn, "road_graph_skipped")
      has_graph_tables = all(_table_exists(conn, table) for table in ("road_nodes", "road_edges", "road_adjacency"))
      print(
        f"road graph skipped={graph_skipped or 'unknown'} "
        f"nodes={graph_nodes:,} edges={graph_edges:,} adjacency={graph_adjacency:,}",
        flush=True,
      )
      if require_road_graph and (graph_skipped == "1" or not has_graph_tables or graph_nodes <= 0 or graph_edges <= 0 or graph_adjacency <= 0):
        raise RuntimeError("downloaded DB does not contain the forward successor road graph")
  except sqlite3.Error as e:
    raise RuntimeError(f"downloaded DB validation failed: {e}") from e

  return max(segment_count, roads_count)


def _move_or_copy(source: Path, target: Path) -> None:
  try:
    os.replace(source, target)
  except OSError:
    shutil.copy2(source, target)
    source.unlink()


def _replace_db(downloaded_db: Path, final_db: Path, require_road_graph: bool) -> int:
  final_db.parent.mkdir(parents=True, exist_ok=True)
  install_tmp = final_db.with_suffix(final_db.suffix + ".git.tmp")
  backup_path = final_db.with_suffix(final_db.suffix + ".bak")
  _unlink_if_exists(install_tmp)

  print(f"moving downloaded DB to {install_tmp}", flush=True)
  _move_or_copy(downloaded_db, install_tmp)

  try:
    print("validating downloaded OSM roads DB", flush=True)
    count = _validate_osm_db(install_tmp, require_road_graph)
    print(f"validated downloaded DB: {count:,} segments", flush=True)
  except Exception:
    _unlink_if_exists(install_tmp)
    raise

  if final_db.exists():
    print(f"backing up existing DB to {backup_path}", flush=True)
    os.replace(final_db, backup_path)
  try:
    print(f"replacing {final_db}", flush=True)
    os.replace(install_tmp, final_db)
  except Exception:
    if backup_path.exists() and not final_db.exists():
      print("restoring existing DB from backup", flush=True)
      os.replace(backup_path, final_db)
    _unlink_if_exists(install_tmp)
    raise
  return count


def main() -> int:
  parser = argparse.ArgumentParser(description="Install the prebuilt OSM roads DB from a Git LFS repository")
  parser.add_argument("--repo", default=DEFAULT_REPO_URL, help=f"Git repository URL (default: {DEFAULT_REPO_URL})")
  parser.add_argument("--ref", default=DEFAULT_REPO_REF, help=f"Git ref or branch to fetch (default: {DEFAULT_REPO_REF})")
  parser.add_argument("--repo-db-path", type=Path, default=DEFAULT_REPO_DB_PATH, help=f"DB path inside repo (default: {DEFAULT_REPO_DB_PATH})")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"Output SQLite DB (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--tmp-dir", type=Path, default=DEFAULT_NAVD_TMP_DIR / "osm_roads_git_db", help="Temporary clone directory")
  parser.add_argument("--require-road-graph", action="store_true", help="Fail if the downloaded DB does not include the successor road graph")
  parser.add_argument("--keep-clone", action="store_true", help="Keep the temporary clone after installing")
  args = parser.parse_args()

  if args.repo_db_path.is_absolute() or ".." in args.repo_db_path.parts:
    parser.error("--repo-db-path must be a relative path inside the Git repository")
  if shutil.which("git") is None:
    raise RuntimeError("git is not installed")

  params = Params()
  _put_param(params, OSM_ROADS_STATUS_KEY, "running")
  _put_param(params, OSM_ROADS_ERROR_KEY, "")
  _put_progress(params, 0)
  _put_segment_count(params, 0)
  _put_download_size(params, 0, 0)
  ensure_navd_dirs(db_dir=args.db.parent, tmp_dir=args.tmp_dir)
  clone_dir = args.tmp_dir / "repo"
  _log_install_diagnostics(args, clone_dir)
  _rmtree_if_exists(clone_dir)

  env = os.environ.copy()
  env["GIT_LFS_SKIP_SMUDGE"] = "1"
  try:
    print(f"git repo {args.repo}", flush=True)
    print(f"git ref {args.ref}", flush=True)
    print(f"repo DB path {args.repo_db_path}", flush=True)
    _put_progress(params, 5)
    _run(["git", "clone", "--depth", "1", "--branch", args.ref, args.repo, str(clone_dir)], env=env, params=params, progress_start=5, progress_end=15)
    _log_lfs_pointer(clone_dir / args.repo_db_path)

    _put_progress(params, 15)
    _run(["git", "lfs", "install", "--local"], cwd=clone_dir)
    total_bytes = _lfs_pointer_size(clone_dir / args.repo_db_path)
    if total_bytes > 0:
      _put_download_size(params, 0, total_bytes)
      print(f"OSM roads DB download size {_format_bytes(total_bytes)} ({total_bytes:,} bytes)", flush=True)
    _run(
      ["git", "lfs", "pull", "-I", str(args.repo_db_path).replace("\\", "/")],
      cwd=clone_dir,
      params=params,
      progress_start=15,
      progress_end=80,
      download_total_bytes=total_bytes,
    )

    downloaded_db = clone_dir / args.repo_db_path
    size_bytes = downloaded_db.stat().st_size
    _put_download_size(params, size_bytes, total_bytes if total_bytes > 0 else size_bytes)
    print(f"downloaded git DB {downloaded_db} ({size_bytes} bytes)", flush=True)
    _put_progress(params, 80)

    count = _replace_db(downloaded_db, args.db, args.require_road_graph)
    _put_segment_count(params, count)
    _put_progress(params, 100)
    _put_param(params, OSM_ROADS_STATUS_KEY, "success")
    _put_param(params, OSM_ROADS_ERROR_KEY, "")
    _put_param(params, OSM_ROADS_UPDATED_AT_KEY, time.strftime("%Y-%m-%d %H:%M"))
    print(f"installed git OSM roads DB {args.db}", flush=True)
    print(f"osm road segments {count}", flush=True)
    return 0
  except Exception:
    try:
      _log_failure_diagnostics(args, clone_dir)
    except Exception as e:
      print(f"failed to write OSM roads failure diagnostics: {e}", flush=True)
    raise
  finally:
    if not args.keep_clone:
      _rmtree_if_exists(clone_dir, required=False)


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except Exception as e:
    params = Params()
    _put_param(params, OSM_ROADS_STATUS_KEY, "failed")
    _put_param(params, OSM_ROADS_ERROR_KEY, str(e)[-500:])
    print(f"OSM roads DB install failed: {e}", flush=True)
    raise SystemExit(1)
