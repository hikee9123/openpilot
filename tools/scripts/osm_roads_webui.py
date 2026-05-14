#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR, DEFAULT_NAVD_TMP_DIR
except ModuleNotFoundError:
  osm_roads = import_module("selfdrive.navd.osm_roads")
  navd_paths = import_module("selfdrive.navd.paths")
  DEFAULT_OSM_ROADS_DB_PATH = osm_roads.DEFAULT_OSM_ROADS_DB_PATH
  DEFAULT_NAVD_SOURCE_DIR = navd_paths.DEFAULT_NAVD_SOURCE_DIR
  DEFAULT_NAVD_TMP_DIR = navd_paths.DEFAULT_NAVD_TMP_DIR


REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = REPO_ROOT / "tools" / "osm_roads_webui" / "index.html"
MAP_HTML_PATH = REPO_ROOT / "tools" / "osm_roads_webui" / "map.html"
WINDOWS_START_SCRIPT_PATH = REPO_ROOT / "tools" / "osm_roads_webui" / "start_server.cmd"
UBUNTU_START_SCRIPT_PATH = REPO_ROOT / "tools" / "osm_roads_webui" / "start_server.sh"
DEFAULT_PBF = DEFAULT_NAVD_SOURCE_DIR / "south-korea-latest.osm.pbf"
DEFAULT_SPEED_CAMERA_CSV = DEFAULT_NAVD_SOURCE_DIR / "speed_cameras.csv"
DEFAULT_TMP_DB = DEFAULT_NAVD_TMP_DIR / "osm_roads_build" / "osm_roads_kr.sqlite3.build"
TASK_ORDER = ("download", "generate_cameras", "build", "import_cameras", "validate", "upload_dry_run", "upload_push")
PROGRESS_PREFIX = "__osm_progress__ "
BUILD_PROFILES = ("full", "camera-balanced", "major")
BUILD_PROFILE_ALIASES = {
  "balanced": "camera-balanced",
  "camera": "camera-balanced",
  "camera_blanced": "camera-balanced",
  "camera-blanced": "camera-balanced",
  "camera_balanced": "camera-balanced",
  "camera-balanced": "camera-balanced",
}
TASK_LABELS = {
  "download": "PBF 다운로드",
  "generate_cameras": "단속카메라 생성",
  "build": "DB 생성",
  "import_cameras": "카메라 매칭",
  "validate": "DB 검증",
  "upload_dry_run": "GitHub 업로드 확인",
  "upload_push": "GitHub 업로드",
}


def _normalize_build_profile(value: str) -> str:
  profile = (value or "camera-balanced").strip().lower()
  profile = BUILD_PROFILE_ALIASES.get(profile, profile)
  if profile not in BUILD_PROFILES:
    return "camera-balanced"
  return profile


@dataclass
class TaskState:
  key: str
  label: str
  status: str = "idle"
  progress: int = 0
  message: str = "대기"
  stage: str = ""
  started_at: str = ""
  finished_at: str = ""
  updated_at: str = ""
  returncode: int | None = None
  command: list[str] = field(default_factory=list)
  details: dict[str, object] = field(default_factory=dict)
  log: deque[str] = field(default_factory=lambda: deque(maxlen=600))
  started_monotonic: float = 0.0

  def snapshot(self) -> dict[str, object]:
    return {
      "key": self.key,
      "label": self.label,
      "status": self.status,
      "progress": self.progress,
      "message": self.message,
      "stage": self.stage,
      "started_at": self.started_at,
      "finished_at": self.finished_at,
      "updated_at": self.updated_at,
      "returncode": self.returncode,
      "command": self.command,
      "details": self.details,
      "log": list(self.log),
    }


class OSMRoadsTaskRunner:
  def __init__(self, args: argparse.Namespace) -> None:
    self.args = args
    self.lock = threading.RLock()
    self.tasks = {key: TaskState(key, TASK_LABELS[key]) for key in TASK_ORDER}
    self.active_task: str | None = None
    self.process: subprocess.Popen[str] | None = None
    self.sequence = 0
    self.started_monotonic = time.monotonic()

  def snapshot(self) -> dict[str, object]:
    with self.lock:
      return {
        "active_task": self.active_task,
        "sequence": self.sequence,
        "busy": self.active_task is not None,
        "defaults": {
          "speed_cameras": str(self.args.speed_cameras),
          "build_profile": self.args.build_profile,
        },
        "tasks": {key: self.tasks[key].snapshot() for key in TASK_ORDER},
      }

  def start(self, task_key: str, build_profile: str = "", speed_cameras: str = "") -> tuple[bool, str]:
    if task_key not in self.tasks:
      return False, f"unknown task: {task_key}"
    with self.lock:
      if self.active_task is not None:
        return False, f"{self.tasks[self.active_task].label} 실행 중"
      selected_build_profile = _normalize_build_profile(build_profile or self.args.build_profile)
      selected_speed_cameras = speed_cameras.strip() or str(self.args.speed_cameras or "")
      if task_key == "import_cameras" and not selected_speed_cameras:
        return False, "단속카메라 CSV 경로가 필요합니다"
      task = self.tasks[task_key]
      task.status = "running"
      task.progress = 1
      task.message = "시작"
      task.stage = ""
      task.started_at = _now_text()
      task.started_monotonic = time.monotonic()
      task.finished_at = ""
      task.updated_at = task.started_at
      task.returncode = None
      task.details = {}
      if task_key == "build":
        task.details["build_profile"] = selected_build_profile
      if task_key in ("generate_cameras", "build", "import_cameras") and selected_speed_cameras:
        task.details["speed_cameras"] = selected_speed_cameras
      task.command = self._command_for(task_key, selected_build_profile, selected_speed_cameras)
      task.log.clear()
      task.log.append("$ " + " ".join(task.command))
      self.active_task = task_key
      self.sequence += 1

    thread = threading.Thread(target=self._run_task, args=(task_key,), daemon=True)
    thread.start()
    if task_key == "build":
      monitor_thread = threading.Thread(target=self._monitor_build_task, daemon=True)
      monitor_thread.start()
    return True, "started"

  def stop(self) -> tuple[bool, str]:
    with self.lock:
      process = self.process
      task_key = self.active_task
    if process is None or task_key is None:
      return False, "no running task"
    with self.lock:
      task = self.tasks[task_key]
      task.status = "stopping"
      task.message = "중지 요청"
      task.updated_at = _now_text()
      task.log.append("stop requested")
      self.sequence += 1
    process.terminate()
    return True, "stopping"

  def _command_for(self, task_key: str, build_profile: str = "", speed_cameras: str = "") -> list[str]:
    db_path = str(Path(self.args.db).expanduser())
    pbf_path = str(Path(self.args.pbf).expanduser())
    require_graph = [] if self.args.no_require_road_graph else ["--require-road-graph"]
    if task_key == "download":
      command = [sys.executable, "tools/scripts/download_osm_roads_source.py", "--output", pbf_path]
      if self.args.skip_md5:
        command.append("--skip-md5")
      return command
    if task_key == "generate_cameras":
      command = [
        sys.executable,
        "tools/scripts/download_speed_cameras_source.py",
        "--output",
        str(Path(speed_cameras or self.args.speed_cameras).expanduser()),
        "--tmp-dir",
        str(Path(self.args.speed_camera_tmp_dir).expanduser()),
        "--public-data-pk",
        self.args.speed_camera_public_data_pk,
        "--per-page",
        str(self.args.speed_camera_per_page),
      ]
      if self.args.speed_camera_max_pages is not None:
        command.extend(["--max-pages", str(self.args.speed_camera_max_pages)])
      return command
    if task_key == "build":
      profile = _normalize_build_profile(build_profile or self.args.build_profile)
      command = [
        sys.executable,
        "tools/scripts/build_osm_roads_db.py",
        "--pbf",
        pbf_path,
        "--db",
        db_path,
        "--profile",
        profile,
        "--progress-json",
        *require_graph,
      ]
      if speed_cameras:
        command.extend([
          "--speed-cameras",
          str(Path(speed_cameras).expanduser()),
          "--speed-camera-match-radius-m",
          str(self.args.speed_camera_match_radius_m),
        ])
      return command
    if task_key == "import_cameras":
      return [
        sys.executable,
        "tools/scripts/import_osm_speed_cameras.py",
        "--db",
        db_path,
        "--csv",
        str(Path(speed_cameras).expanduser()),
        "--match-radius-m",
        str(self.args.speed_camera_match_radius_m),
        *require_graph,
      ]
    if task_key == "validate":
      return [sys.executable, "tools/scripts/build_osm_roads_db.py", "--db", db_path, "--validate-only", *require_graph]
    if task_key in ("upload_dry_run", "upload_push"):
      command = [sys.executable, "tools/scripts/upload_osm_roads_db_to_git.py", "--db", db_path, *require_graph]
      if self.args.upload_repo:
        command.extend(["--repo", str(Path(self.args.upload_repo).expanduser())])
      elif self.args.upload_repo_url:
        command.extend(["--repo-url", self.args.upload_repo_url])
      if self.args.upload_branch:
        command.extend(["--branch", self.args.upload_branch])
      if task_key == "upload_push":
        command.append("--push")
      return command
    raise RuntimeError(f"unknown task: {task_key}")

  def _run_task(self, task_key: str) -> None:
    with self.lock:
      task = self.tasks[task_key]
      command = list(task.command)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
      with subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
      ) as process:
        with self.lock:
          self.process = process
          self.sequence += 1
        assert process.stdout is not None
        for line in process.stdout:
          self._append_output(task_key, line.rstrip())
        returncode = process.wait()
    except Exception as e:
      with self.lock:
        task.status = "failed"
        task.progress = max(task.progress, 1)
        task.message = str(e)
        task.finished_at = _now_text()
        task.updated_at = task.finished_at
        task.log.append(f"error: {e}")
        task.returncode = -1
        self.active_task = None
        self.process = None
        self.sequence += 1
      return

    with self.lock:
      if task.status == "stopping":
        task.status = "stopped"
        task.message = "중지됨"
      elif returncode == 0:
        task.status = "success"
        task.progress = 100
        task.message = "완료"
      else:
        task.status = "failed"
        task.message = f"실패 exit={returncode}"
      task.returncode = returncode
      task.finished_at = _now_text()
      task.updated_at = task.finished_at
      self.active_task = None
      self.process = None
      self.sequence += 1

  def _append_output(self, task_key: str, line: str) -> None:
    if not line:
      return
    with self.lock:
      task = self.tasks[task_key]
      task.log.append(line)
      if line.startswith(PROGRESS_PREFIX):
        task.log.pop()
        try:
          payload = json.loads(line[len(PROGRESS_PREFIX):])
        except json.JSONDecodeError:
          task.log.append(line)
        else:
          details = dict(task.details)
          details.update(payload)
          task.progress = max(task.progress, int(payload.get("progress", task.progress)))
          task.message = str(payload.get("message", task.message))
          task.stage = str(payload.get("step", task.stage))
          task.updated_at = _now_text()
          task.details = details
          self.sequence += 1
          return
      progress, message = _progress_from_line(task_key, line, task.progress)
      task.progress = max(task.progress, progress)
      task.message = message or line[-180:]
      task.updated_at = _now_text()
      self.sequence += 1

  def _monitor_build_task(self) -> None:
    while True:
      time.sleep(5.0)
      with self.lock:
        if self.active_task != "build":
          return
        task = self.tasks["build"]
        details = dict(task.details)
        details["elapsed_s"] = int(time.monotonic() - task.started_monotonic) if task.started_monotonic > 0.0 else 0
        try:
          stat_result = DEFAULT_TMP_DB.stat()
          details["db_size_bytes"] = stat_result.st_size
          details["db_mtime"] = int(stat_result.st_mtime)
        except OSError:
          details.setdefault("db_size_bytes", 0)
        task.details = details
        task.updated_at = _now_text()
        self.sequence += 1


def _now_text() -> str:
  return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _progress_from_line(task_key: str, line: str, current: int) -> tuple[int, str]:
  lower = line.lower()
  if task_key == "download":
    match = re.search(r"downloaded [\d,]+ / [\d,]+ bytes \(([\d.]+)%\)", line)
    if match:
      return min(99, 10 + int(float(match.group(1)) * 0.88)), line
    if "fetching md5" in lower:
      return 5, line
    if "remote md5" in lower:
      return 10, line
    if "source already up to date" in lower or "source already exists" in lower or "downloaded source" in lower:
      return 100, line
    if "downloading" in lower:
      return 15, line
  elif task_key == "generate_cameras":
    match = re.search(r"progress\s+(\d+)%", lower)
    if match:
      return min(99, max(current, int(match.group(1)))), line
    if "fetching public speed camera metadata" in lower:
      return max(current, 5), line
    if "downloaded" in lower and "speed camera rows" in lower:
      return 100, line
  elif task_key == "build":
    stages = (
      ("collecting osm relations", 5),
      ("relations route=", 10),
      ("building road segments", 15),
      ("parsed ways=", min(52, current + 1)),
      ("built road segments", 55),
      ("indexing directed graph edges", 60),
      ("building road adjacency", 70),
      ("matching speed cameras", 87),
      ("speed cameras imported", 87),
      ("creating indexes", 88),
      ("validating built db", 92),
      ("validated built db", 96),
      ("installed built db", 100),
    )
    for token, progress in stages:
      if token in lower:
        return progress, line
  elif task_key == "import_cameras":
    if "speed cameras imported" in lower:
      return 100, line
    return max(current, 50), line
  elif task_key == "validate":
    if "validated" in lower:
      return 100, line
    return max(current, 25), line
  elif task_key in ("upload_dry_run", "upload_push"):
    stages = (
      ("validated upload db", 10),
      ("dry run only", 100),
      ("$ git clone", 20),
      ("$ git lfs", 35),
      ("copying ", 45),
      ("$ git add", 55),
      ("$ git status", 60),
      ("$ git commit", 72),
      ("$ git push", 85),
      ("committed locally", 100),
    )
    for token, progress in stages:
      if token in lower:
        return progress, line
  return current, line


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]) -> None:
  body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
  handler.send_response(status)
  handler.send_header("Content-Type", "application/json; charset=utf-8")
  handler.send_header("Content-Length", str(len(body)))
  handler.send_header("Cache-Control", "no-store")
  handler.send_header("Access-Control-Allow-Origin", "*")
  handler.end_headers()
  handler.wfile.write(body)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
  return conn.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
    (name,),
  ).fetchone() is not None


def _count_or_metadata(conn: sqlite3.Connection, metadata: dict[str, str], table: str, metadata_key: str) -> int:
  value = metadata.get(metadata_key)
  if value is not None:
    try:
      return int(value)
    except ValueError:
      pass
  if not _table_exists(conn, table):
    return 0
  return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _rows(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> dict[str, object]:
  cursor = conn.execute(query, params)
  columns = [item[0] for item in cursor.description or []]
  return {
    "columns": columns,
    "rows": [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()],
  }


def _platform_name() -> str:
  system = platform.system().lower()
  if system == "windows":
    return "windows"
  if system == "linux":
    return "ubuntu"
  return system or "unknown"


def _start_script_path() -> Path:
  return WINDOWS_START_SCRIPT_PATH if _platform_name() == "windows" else UBUNTU_START_SCRIPT_PATH


def _start_scripts_payload() -> dict[str, str]:
  return {
    "windows": str(WINDOWS_START_SCRIPT_PATH),
    "ubuntu": str(UBUNTU_START_SCRIPT_PATH),
  }


def server_health(args: argparse.Namespace, started_monotonic: float) -> dict[str, object]:
  db_path = Path(args.db).expanduser()
  default_db_path = Path(DEFAULT_OSM_ROADS_DB_PATH).expanduser()
  uses_default_path = os.path.normcase(os.path.abspath(str(db_path))) == os.path.normcase(os.path.abspath(str(default_db_path)))
  required_tables = ("roads", "roads_rtree", "speed_cameras", "route_camera_lookup")
  checked_at = time.time()
  check_start = time.perf_counter()
  db: dict[str, object] = {
    "configured_path": str(db_path),
    "default_path": str(default_db_path),
    "uses_default_path": uses_default_path,
    "exists": False,
    "readable": False,
    "schema_ok": False,
    "smoke_ok": False,
    "size_bytes": 0,
    "modified_at": 0,
    "tables": {table: False for table in required_tables},
    "error": "",
  }

  try:
    stat_result = db_path.stat()
    db["exists"] = True
    db["size_bytes"] = stat_result.st_size
    db["modified_at"] = int(stat_result.st_mtime)
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
      db["readable"] = True
      tables = {table: _table_exists(conn, table) for table in required_tables}
      db["tables"] = tables
      db["schema_ok"] = all(tables.values())
      if tables["roads"]:
        conn.execute("SELECT 1 FROM roads LIMIT 1").fetchone()
        db["smoke_ok"] = True
      else:
        db["error"] = "roads table missing"
  except OSError as e:
    db["error"] = str(e)
  except sqlite3.Error as e:
    db["error"] = str(e)

  db["check_ms"] = round((time.perf_counter() - check_start) * 1000, 1)
  ok = bool(db["exists"] and db["readable"] and db["schema_ok"] and db["smoke_ok"])
  current_platform = _platform_name()
  start_script_path = _start_script_path()
  return {
    "ok": ok,
    "checked_at": int(checked_at),
    "server": {
      "ok": True,
      "host": args.host,
      "port": args.port,
      "uptime_s": round(time.monotonic() - started_monotonic, 1),
    },
    "platform": current_platform,
    "start_script_path": str(start_script_path),
    "start_scripts": _start_scripts_payload(),
    "db": db,
  }


def open_start_script_folder() -> dict[str, object]:
  start_script_path = _start_script_path()
  current_platform = _platform_name()
  if not start_script_path.exists():
    return {"ok": False, "message": f"시작 스크립트가 없습니다: {start_script_path}", "path": str(start_script_path)}
  try:
    if current_platform == "windows":
      subprocess.Popen(["explorer.exe", f"/select,{start_script_path}"])
    elif current_platform == "ubuntu":
      opener = shutil.which("xdg-open")
      if opener is None:
        return {"ok": False, "message": "xdg-open을 찾을 수 없습니다", "path": str(start_script_path)}
      subprocess.Popen([opener, str(start_script_path.parent)])
    else:
      return {"ok": False, "message": f"지원하지 않는 OS입니다: {current_platform}", "path": str(start_script_path)}
  except OSError as e:
    return {"ok": False, "message": f"파일 탐색기 실행 실패: {e}", "path": str(start_script_path)}
  return {"ok": True, "message": "opened", "platform": current_platform, "path": str(start_script_path)}


def db_summary(db_path: Path) -> dict[str, object]:
  db_path = db_path.expanduser()
  if not db_path.exists():
    return {"ok": False, "message": f"DB 파일이 없습니다: {db_path}", "db_path": str(db_path)}

  stat_result = db_path.stat()
  with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
    metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall()) if _table_exists(conn, "metadata") else {}
    counts = {
      "roads": _count_or_metadata(conn, metadata, "roads", "segment_count"),
      "road_nodes": _count_or_metadata(conn, metadata, "road_nodes", "road_graph_node_count"),
      "road_edges": _count_or_metadata(conn, metadata, "road_edges", "road_graph_edge_count"),
      "road_adjacency": _count_or_metadata(conn, metadata, "road_adjacency", "road_graph_adjacency_count"),
      "speed_cameras": _count_or_metadata(conn, metadata, "speed_cameras", "speed_camera_count"),
      "speed_camera_road_matches": _count_or_metadata(conn, metadata, "speed_camera_road_matches", "speed_camera_match_count"),
      "route_camera_lookup": _count_or_metadata(conn, metadata, "route_camera_lookup", "route_camera_lookup_count"),
    }
    samples = {
      "roads": _rows(conn, """
        SELECT id, name, ref, highway, road_priority, segment_length, lat1, lon1, lat2, lon2
        FROM roads
        ORDER BY road_priority DESC, id
        LIMIT 30
      """) if _table_exists(conn, "roads") else {"columns": [], "rows": []},
      "cameras": _rows(conn, """
        SELECT id, camera_type, speed_limit_kph, lat, lon, road_name, address, source_updated_at
        FROM speed_cameras
        ORDER BY id
        LIMIT 30
      """) if _table_exists(conn, "speed_cameras") else {"columns": [], "rows": []},
      "matches": _rows(conn, """
        SELECT
          lookup.road_id,
          roads.name AS road_name,
          roads.ref AS road_ref,
          roads.highway,
          lookup.camera_id,
          cameras.camera_type,
          lookup.speed_limit_kph,
          ROUND(lookup.match_distance_m, 1) AS match_distance_m,
          ROUND(lookup.match_confidence, 3) AS match_confidence,
          cameras.address
        FROM route_camera_lookup AS lookup
        JOIN roads ON roads.id = lookup.road_id
        JOIN speed_cameras AS cameras ON cameras.id = lookup.camera_id
        ORDER BY lookup.match_confidence DESC, lookup.match_distance_m ASC
        LIMIT 30
      """) if all(_table_exists(conn, table) for table in ("route_camera_lookup", "roads", "speed_cameras")) else {"columns": [], "rows": []},
    }

  important_metadata_keys = (
    "build_profile", "built_at", "source_pbf", "included_highways", "excluded_highways",
    "speed_camera_source", "speed_camera_csv", "speed_camera_matched_count", "speed_camera_match_radius_m",
  )
  return {
    "ok": True,
    "db_path": str(db_path),
    "size_bytes": stat_result.st_size,
    "modified_at": int(stat_result.st_mtime),
    "metadata": {key: metadata[key] for key in important_metadata_keys if key in metadata},
    "counts": counts,
    "samples": samples,
  }


def _parse_float(value: str, default: float) -> float:
  try:
    return float(value)
  except (TypeError, ValueError):
    return default


def _parse_int(value: str, default: int, low: int, high: int) -> int:
  try:
    parsed = int(value)
  except (TypeError, ValueError):
    parsed = default
  return max(low, min(high, parsed))


def db_map(db_path: Path, query: dict[str, list[str]]) -> dict[str, object]:
  db_path = db_path.expanduser()
  if not db_path.exists():
    return {"ok": False, "message": f"DB 파일이 없습니다: {db_path}", "db_path": str(db_path)}

  bbox_text = query.get("bbox", [""])[0]
  try:
    min_lon, min_lat, max_lon, max_lat = (float(part) for part in bbox_text.split(",", maxsplit=3))
  except ValueError:
    return {"ok": False, "message": "bbox=minLon,minLat,maxLon,maxLat 형식이 필요합니다", "db_path": str(db_path)}

  min_lat, max_lat = sorted((max(-90.0, min(90.0, min_lat)), max(-90.0, min(90.0, max_lat))))
  min_lon, max_lon = sorted((max(-180.0, min(180.0, min_lon)), max(-180.0, min(180.0, max_lon))))
  camera_limit = _parse_int(query.get("camera_limit", ["800"])[0], 800, 1, 3000)
  road_limit = _parse_int(query.get("road_limit", ["1200"])[0], 1200, 1, 5000)

  with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
    if not all(_table_exists(conn, table) for table in ("speed_cameras", "route_camera_lookup", "roads")):
      return {"ok": False, "message": "지도에 필요한 speed_cameras/route_camera_lookup/roads 테이블이 없습니다", "db_path": str(db_path)}

    camera_rows = _rows(conn, """
      SELECT
        cameras.id,
        cameras.lat,
        cameras.lon,
        cameras.camera_type,
        cameras.speed_limit_kph,
        cameras.road_name,
        cameras.address,
        best.road_id,
        best.road_name AS matched_road_name,
        best.road_ref AS matched_road_ref,
        best.highway,
        ROUND(best.match_distance_m, 1) AS match_distance_m,
        ROUND(best.match_confidence, 3) AS match_confidence
      FROM speed_cameras AS cameras
      LEFT JOIN (
        SELECT
          lookup.camera_id,
          lookup.road_id,
          roads.name AS road_name,
          roads.ref AS road_ref,
          roads.highway,
          lookup.match_distance_m,
          lookup.match_confidence
        FROM route_camera_lookup AS lookup
        JOIN roads ON roads.id = lookup.road_id
        WHERE lookup.primary_match = 1
      ) AS best ON best.camera_id = cameras.id
      WHERE cameras.lat BETWEEN ? AND ?
        AND cameras.lon BETWEEN ? AND ?
      ORDER BY cameras.id
      LIMIT ?
    """, (min_lat, max_lat, min_lon, max_lon, camera_limit))

    road_cursor = conn.execute("""
      SELECT
        lookup.road_id,
        lookup.camera_id,
        roads.name,
        roads.ref,
        roads.highway,
        roads.lat1,
        roads.lon1,
        roads.lat2,
        roads.lon2,
        ROUND(lookup.match_distance_m, 1) AS match_distance_m,
        ROUND(lookup.match_confidence, 3) AS match_confidence
      FROM route_camera_lookup AS lookup
      JOIN speed_cameras AS cameras ON cameras.id = lookup.camera_id
      JOIN roads ON roads.id = lookup.road_id
      WHERE lookup.primary_match = 1
        AND cameras.lat BETWEEN ? AND ?
        AND cameras.lon BETWEEN ? AND ?
        AND roads.min_lat <= ?
        AND roads.max_lat >= ?
        AND roads.min_lon <= ?
        AND roads.max_lon >= ?
      ORDER BY lookup.match_confidence DESC, lookup.match_distance_m ASC
      LIMIT ?
    """, (min_lat, max_lat, min_lon, max_lon, max_lat, min_lat, max_lon, min_lon, road_limit))
    road_columns = [item[0] for item in road_cursor.description or []]
    road_rows = [dict(zip(road_columns, row, strict=False)) for row in road_cursor.fetchall()]

  return {
    "ok": True,
    "db_path": str(db_path),
    "bbox": {
      "min_lat": min_lat,
      "max_lat": max_lat,
      "min_lon": min_lon,
      "max_lon": max_lon,
    },
    "limits": {
      "camera_limit": camera_limit,
      "road_limit": road_limit,
    },
    "cameras": camera_rows["rows"],
    "roads": road_rows,
  }


def _bbox_from_query(db_path: Path, query: dict[str, list[str]]) -> tuple[float, float, float, float] | dict[str, object]:
  bbox_text = query.get("bbox", [""])[0]
  try:
    min_lon, min_lat, max_lon, max_lat = (float(part) for part in bbox_text.split(",", maxsplit=3))
  except ValueError:
    return {"ok": False, "message": "bbox=minLon,minLat,maxLon,maxLat 형식이 필요합니다", "db_path": str(db_path)}

  min_lat, max_lat = sorted((max(-90.0, min(90.0, min_lat)), max(-90.0, min(90.0, max_lat))))
  min_lon, max_lon = sorted((max(-180.0, min(180.0, min_lon)), max(-180.0, min(180.0, max_lon))))
  return min_lon, min_lat, max_lon, max_lat


def db_roads(db_path: Path, query: dict[str, list[str]]) -> dict[str, object]:
  db_path = db_path.expanduser()
  if not db_path.exists():
    return {"ok": False, "message": f"DB 파일이 없습니다: {db_path}", "db_path": str(db_path)}

  bbox = _bbox_from_query(db_path, query)
  if isinstance(bbox, dict):
    return bbox
  min_lon, min_lat, max_lon, max_lat = bbox
  road_limit = _parse_int(query.get("road_limit", ["12000"])[0], 12000, 1, 50000)
  min_priority = _parse_float(query.get("min_priority", ["0"])[0], 0.0)

  with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
    if not all(_table_exists(conn, table) for table in ("roads", "roads_rtree")):
      return {"ok": False, "message": "전체 도로망에 필요한 roads/roads_rtree 테이블이 없습니다", "db_path": str(db_path)}

    cursor = conn.execute("""
      SELECT
        roads.id,
        roads.name,
        roads.ref,
        roads.highway,
        roads.road_priority,
        ROUND(roads.segment_length, 1) AS segment_length,
        roads.lat1,
        roads.lon1,
        roads.lat2,
        roads.lon2
      FROM roads
      JOIN roads_rtree ON roads_rtree.id = roads.id
      WHERE roads_rtree.min_lat <= ?
        AND roads_rtree.max_lat >= ?
        AND roads_rtree.min_lon <= ?
        AND roads_rtree.max_lon >= ?
        AND roads.road_priority >= ?
      ORDER BY roads.road_priority DESC, roads.id
      LIMIT ?
    """, (max_lat, min_lat, max_lon, min_lon, min_priority, road_limit))
    columns = [item[0] for item in cursor.description or []]
    rows = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

  return {
    "ok": True,
    "db_path": str(db_path),
    "bbox": {
      "min_lat": min_lat,
      "max_lat": max_lat,
      "min_lon": min_lon,
      "max_lon": max_lon,
    },
    "limits": {
      "road_limit": road_limit,
      "min_priority": min_priority,
    },
    "roads": rows,
  }


class OSMRoadsWebHandler(BaseHTTPRequestHandler):
  runner: OSMRoadsTaskRunner

  def log_message(self, fmt: str, *args: object) -> None:
    print(f"[osm_roads_webui] {self.address_string()} {fmt % args}", flush=True)

  def do_GET(self) -> None:
    parsed = urlparse(self.path)
    if parsed.path in ("", "/", "/index.html"):
      self._serve_file(HTML_PATH)
    elif parsed.path in ("/map", "/map.html"):
      self._serve_file(MAP_HTML_PATH)
    elif parsed.path == "/api/health":
      payload = server_health(self.runner.args, self.runner.started_monotonic)
      _json_response(self, HTTPStatus.OK, payload)
    elif parsed.path == "/api/state":
      _json_response(self, HTTPStatus.OK, self.runner.snapshot())
    elif parsed.path == "/api/db/summary":
      payload = db_summary(Path(self.runner.args.db))
      _json_response(self, HTTPStatus.OK if payload.get("ok") else HTTPStatus.NOT_FOUND, payload)
    elif parsed.path == "/api/db/map":
      payload = db_map(Path(self.runner.args.db), parse_qs(parsed.query))
      _json_response(self, HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_REQUEST, payload)
    elif parsed.path == "/api/db/roads":
      payload = db_roads(Path(self.runner.args.db), parse_qs(parsed.query))
      _json_response(self, HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_REQUEST, payload)
    elif parsed.path == "/api/events":
      self._serve_events()
    else:
      self.send_error(HTTPStatus.NOT_FOUND, "not found")

  def do_POST(self) -> None:
    parsed = urlparse(self.path)
    if parsed.path.startswith("/api/tasks/"):
      task_key = parsed.path.rsplit("/", maxsplit=1)[-1]
      query = parse_qs(parsed.query)
      build_profile = query.get("profile", [""])[0]
      speed_cameras = query.get("speed_cameras", [""])[0]
      ok, message = self.runner.start(task_key, build_profile=build_profile, speed_cameras=speed_cameras)
      _json_response(self, HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok, "message": message})
    elif parsed.path == "/api/stop":
      ok, message = self.runner.stop()
      _json_response(self, HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok, "message": message})
    elif parsed.path == "/api/open/start-script-folder":
      payload = open_start_script_folder()
      _json_response(self, HTTPStatus.OK if payload.get("ok") else HTTPStatus.INTERNAL_SERVER_ERROR, payload)
    else:
      self.send_error(HTTPStatus.NOT_FOUND, "not found")

  def do_OPTIONS(self) -> None:
    self.send_response(HTTPStatus.NO_CONTENT)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.end_headers()

  def _serve_file(self, path: Path) -> None:
    try:
      body = path.read_bytes()
    except OSError:
      self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"missing HTML: {path}")
      return
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()
    self.wfile.write(body)

  def _serve_events(self) -> None:
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()
    last_sequence = -1
    while True:
      snapshot = self.runner.snapshot()
      sequence = int(snapshot["sequence"])
      if sequence != last_sequence:
        data = json.dumps(snapshot, ensure_ascii=False)
        try:
          self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
          self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
          return
        last_sequence = sequence
      time.sleep(0.5)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Run a local web UI for OSM roads DB download/build/upload tasks")
  parser.add_argument("--host", default="127.0.0.1", help="Bind host")
  parser.add_argument("--port", type=int, default=8765, help="Bind port")
  parser.add_argument("--pbf", type=Path, default=DEFAULT_PBF, help=f"PBF source path (default: {DEFAULT_PBF})")
  parser.add_argument("--db", type=Path, default=DEFAULT_OSM_ROADS_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_OSM_ROADS_DB_PATH})")
  parser.add_argument("--skip-md5", action="store_true", help="Pass --skip-md5 to the download task")
  parser.add_argument("--build-profile", default="camera-balanced", help="Default DB build profile for the web UI")
  parser.add_argument("--speed-cameras", type=Path, default=DEFAULT_SPEED_CAMERA_CSV, help=f"Default speed camera CSV path for generate/build/import tasks (default: {DEFAULT_SPEED_CAMERA_CSV})")
  parser.add_argument("--speed-camera-tmp-dir", type=Path, default=DEFAULT_NAVD_TMP_DIR, help=f"Temporary directory for speed camera downloads (default: {DEFAULT_NAVD_TMP_DIR})")
  parser.add_argument("--speed-camera-public-data-pk", default="15028200", help="Public data portal PK for speed camera CSV generation")
  parser.add_argument("--speed-camera-per-page", type=int, default=10000, help="Rows per speed camera public data request")
  parser.add_argument("--speed-camera-max-pages", type=int, default=None, help="Limit speed camera public data pages for testing")
  parser.add_argument("--speed-camera-match-radius-m", type=float, default=65.0, help="Road snapping radius for speed cameras")
  parser.add_argument("--no-require-road-graph", action="store_true", help="Do not pass --require-road-graph to build/validate/upload tasks")
  parser.add_argument("--upload-repo", type=Path, default=None, help="Existing local Git LFS data repo for upload tasks")
  parser.add_argument("--upload-repo-url", default="", help="Git data repo URL used when --upload-repo is omitted")
  parser.add_argument("--upload-branch", default="", help="Optional branch for upload tasks")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  OSMRoadsWebHandler.runner = OSMRoadsTaskRunner(args)
  server = ThreadingHTTPServer((args.host, args.port), OSMRoadsWebHandler)
  print(f"OSM roads web UI: http://{args.host}:{args.port}/", flush=True)
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    print("stopping OSM roads web UI", flush=True)
  finally:
    server.server_close()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
