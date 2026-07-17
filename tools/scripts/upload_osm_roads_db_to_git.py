#!/usr/bin/env python3
from __future__ import annotations

import argparse
from importlib import import_module
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH
  from openpilot.selfdrive.navd.osm_roads_db import validate_osm_roads_db
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_TMP_DIR, ensure_navd_dirs
except ModuleNotFoundError:
  osm_roads = import_module("selfdrive.navd.osm_roads")
  osm_roads_db = import_module("selfdrive.navd.osm_roads_db")
  navd_paths = import_module("selfdrive.navd.paths")
  DEFAULT_OSM_ROADS_DB_PATH = osm_roads.DEFAULT_OSM_ROADS_DB_PATH
  validate_osm_roads_db = osm_roads_db.validate_osm_roads_db
  DEFAULT_NAVD_TMP_DIR = navd_paths.DEFAULT_NAVD_TMP_DIR
  ensure_navd_dirs = navd_paths.ensure_navd_dirs


DEFAULT_REPO_URL = "https://github.com/hikee9123/data_nev.git"
DEFAULT_REPO_DB_PATH = Path("db/osm_roads_kr.sqlite3")


def _run(command: list[str], cwd: Path | None = None) -> str:
  print(f"$ {' '.join(command)}" + (f" cwd={cwd}" if cwd else ""), flush=True)
  result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
  output = result.stdout.strip()
  if output:
    print(output, flush=True)
  if result.returncode != 0:
    raise RuntimeError(f"command failed with exit code {result.returncode}: {' '.join(command)}")
  return output


def _repo_dir(args: argparse.Namespace) -> Path:
  if args.repo:
    return args.repo.expanduser()
  clone_dir = args.tmp_dir.expanduser() / "repo"
  if clone_dir.exists():
    shutil.rmtree(clone_dir)
  clone_dir.parent.mkdir(parents=True, exist_ok=True)
  _run(["git", "clone", args.repo_url, str(clone_dir)])
  return clone_dir


def _ensure_git_lfs(repo_dir: Path, pattern: str) -> None:
  _run(["git", "lfs", "install", "--local"], cwd=repo_dir)
  tracked = _run(["git", "lfs", "track"], cwd=repo_dir)
  if pattern not in tracked:
    _run(["git", "lfs", "track", pattern], cwd=repo_dir)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Copy osm_roads_kr.sqlite3 into a Git LFS data repo and optionally push it")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"SQLite DB to upload (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--repo", type=Path, default=None, help="Existing local data repo. If omitted with --commit/--push, --repo-url is cloned into --tmp-dir.")
  parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help=f"Git data repo URL (default: {DEFAULT_REPO_URL})")
  parser.add_argument("--repo-db-path", type=Path, default=DEFAULT_REPO_DB_PATH, help=f"DB path inside the repo (default: {DEFAULT_REPO_DB_PATH})")
  parser.add_argument("--tmp-dir", type=Path, default=DEFAULT_NAVD_TMP_DIR / "osm_roads_upload", help="Temporary clone directory")
  parser.add_argument("--branch", default="", help="Optional branch to checkout/create before committing")
  parser.add_argument("--message", default="", help="Commit message. Defaults to a segment-count based message.")
  parser.add_argument("--lfs-pattern", default="db/*.sqlite3", help="Git LFS track pattern")
  parser.add_argument("--require-road-graph", action="store_true", help="Fail if the DB does not include the successor road graph")
  parser.add_argument("--commit", action="store_true", help="Copy the DB, git add, and commit")
  parser.add_argument("--push", action="store_true", help="Push after committing. Implies --commit.")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  db_path = args.db.expanduser()
  validation = validate_osm_roads_db(db_path, require_road_graph=args.require_road_graph)
  print(
    f"validated upload DB segments={validation.segment_count:,} graph={int(validation.has_road_graph)} "
    f"adjacency={validation.graph_adjacency_count:,}",
    flush=True,
  )

  if not args.commit and not args.push:
    print("dry run only. Re-run with --commit to modify the data repo, or --push to commit and push.", flush=True)
    return 0

  if args.repo_db_path.is_absolute() or ".." in args.repo_db_path.parts:
    raise RuntimeError("--repo-db-path must be a relative path inside the data repo")
  ensure_navd_dirs(tmp_dir=args.tmp_dir)
  repo_dir = _repo_dir(args)
  if not (repo_dir / ".git").exists():
    raise RuntimeError(f"not a git repo: {repo_dir}")

  if args.branch:
    branches = _run(["git", "branch", "--list", args.branch], cwd=repo_dir)
    if branches.strip():
      _run(["git", "checkout", args.branch], cwd=repo_dir)
    else:
      _run(["git", "checkout", "-b", args.branch], cwd=repo_dir)

  _ensure_git_lfs(repo_dir, args.lfs_pattern)
  repo_db = repo_dir / args.repo_db_path
  repo_db.parent.mkdir(parents=True, exist_ok=True)
  print(f"copying {db_path} -> {repo_db}", flush=True)
  shutil.copy2(db_path, repo_db)
  _run(["git", "add", str(args.repo_db_path).replace("\\", "/"), ".gitattributes"], cwd=repo_dir)
  status = _run(["git", "status", "--short"], cwd=repo_dir)
  if not status:
    print("no repo changes to commit", flush=True)
    return 0

  message = args.message or f"Update OSM roads KR DB ({validation.segment_count:,} segments)"
  _run(["git", "commit", "-m", message], cwd=repo_dir)
  if args.push:
    _run(["git", "push"], cwd=repo_dir)
  else:
    print("committed locally. Re-run with --push or push from the data repo when ready.", flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
