#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
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


def _put_progress(params: Params, progress: int) -> None:
  try:
    params.put(OSM_ROADS_PROGRESS_KEY, max(0, min(100, int(progress))))
  except Exception:
    pass


def _put_segment_count(params: Params, count: int) -> None:
  try:
    params.put(OSM_ROADS_COUNT_KEY, max(0, int(count)))
  except Exception:
    pass


def _run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
  where = f" cwd={cwd}" if cwd is not None else ""
  print(f"$ {' '.join(command)}{where}", flush=True)
  with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
    assert process.stdout is not None
    for line in process.stdout:
      print(line.rstrip(), flush=True)
    returncode = process.wait()
  if returncode != 0:
    raise RuntimeError(f"command failed with exit code {returncode}: {' '.join(command)}")


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
  _put_progress(params, 0)
  _put_segment_count(params, 0)
  ensure_navd_dirs(db_dir=args.db.parent, tmp_dir=args.tmp_dir)
  clone_dir = args.tmp_dir / "repo"
  _rmtree_if_exists(clone_dir)

  env = os.environ.copy()
  env["GIT_LFS_SKIP_SMUDGE"] = "1"
  try:
    print(f"git repo {args.repo}", flush=True)
    print(f"git ref {args.ref}", flush=True)
    print(f"repo DB path {args.repo_db_path}", flush=True)
    _put_progress(params, 5)
    _run(["git", "clone", "--depth", "1", "--branch", args.ref, args.repo, str(clone_dir)], env=env)

    _put_progress(params, 15)
    _run(["git", "lfs", "install", "--local"], cwd=clone_dir)
    _run(["git", "lfs", "pull", "-I", str(args.repo_db_path).replace("\\", "/")], cwd=clone_dir)

    downloaded_db = clone_dir / args.repo_db_path
    size_bytes = downloaded_db.stat().st_size
    print(f"downloaded git DB {downloaded_db} ({size_bytes} bytes)", flush=True)
    _put_progress(params, 80)

    count = _replace_db(downloaded_db, args.db, args.require_road_graph)
    _put_segment_count(params, count)
    _put_progress(params, 100)
    print(f"installed git OSM roads DB {args.db}", flush=True)
    print(f"osm road segments {count}", flush=True)
    return 0
  finally:
    if not args.keep_clone:
      _rmtree_if_exists(clone_dir, required=False)


if __name__ == "__main__":
  raise SystemExit(main())
