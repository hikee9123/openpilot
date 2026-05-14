#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
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
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR
except ModuleNotFoundError:
  osm_roads = import_module("selfdrive.navd.osm_roads")
  navd_paths = import_module("selfdrive.navd.paths")
  DEFAULT_OSM_ROADS_DB_PATH = osm_roads.DEFAULT_OSM_ROADS_DB_PATH
  DEFAULT_NAVD_SOURCE_DIR = navd_paths.DEFAULT_NAVD_SOURCE_DIR


REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = REPO_ROOT / "tools" / "osm_roads_webui" / "index.html"
DEFAULT_PBF = DEFAULT_NAVD_SOURCE_DIR / "south-korea-latest.osm.pbf"
TASK_ORDER = ("download", "build", "validate", "upload_dry_run", "upload_push")
TASK_LABELS = {
  "download": "PBF 다운로드",
  "build": "DB 생성",
  "validate": "DB 검증",
  "upload_dry_run": "GitHub 업로드 확인",
  "upload_push": "GitHub 업로드",
}


@dataclass
class TaskState:
  key: str
  label: str
  status: str = "idle"
  progress: int = 0
  message: str = "대기"
  started_at: str = ""
  finished_at: str = ""
  returncode: int | None = None
  command: list[str] = field(default_factory=list)
  log: deque[str] = field(default_factory=lambda: deque(maxlen=600))

  def snapshot(self) -> dict[str, object]:
    return {
      "key": self.key,
      "label": self.label,
      "status": self.status,
      "progress": self.progress,
      "message": self.message,
      "started_at": self.started_at,
      "finished_at": self.finished_at,
      "returncode": self.returncode,
      "command": self.command,
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

  def snapshot(self) -> dict[str, object]:
    with self.lock:
      return {
        "active_task": self.active_task,
        "sequence": self.sequence,
        "busy": self.active_task is not None,
        "tasks": {key: self.tasks[key].snapshot() for key in TASK_ORDER},
      }

  def start(self, task_key: str) -> tuple[bool, str]:
    if task_key not in self.tasks:
      return False, f"unknown task: {task_key}"
    with self.lock:
      if self.active_task is not None:
        return False, f"{self.tasks[self.active_task].label} 실행 중"
      task = self.tasks[task_key]
      task.status = "running"
      task.progress = 1
      task.message = "시작"
      task.started_at = _now_text()
      task.finished_at = ""
      task.returncode = None
      task.command = self._command_for(task_key)
      task.log.clear()
      task.log.append("$ " + " ".join(task.command))
      self.active_task = task_key
      self.sequence += 1

    thread = threading.Thread(target=self._run_task, args=(task_key,), daemon=True)
    thread.start()
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
      task.log.append("stop requested")
      self.sequence += 1
    process.terminate()
    return True, "stopping"

  def _command_for(self, task_key: str) -> list[str]:
    db_path = str(Path(self.args.db).expanduser())
    pbf_path = str(Path(self.args.pbf).expanduser())
    require_graph = [] if self.args.no_require_road_graph else ["--require-road-graph"]
    if task_key == "download":
      command = [sys.executable, "tools/scripts/download_osm_roads_source.py", "--output", pbf_path]
      if self.args.skip_md5:
        command.append("--skip-md5")
      return command
    if task_key == "build":
      return [sys.executable, "tools/scripts/build_osm_roads_db.py", "--pbf", pbf_path, "--db", db_path, *require_graph]
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
      self.active_task = None
      self.process = None
      self.sequence += 1

  def _append_output(self, task_key: str, line: str) -> None:
    if not line:
      return
    with self.lock:
      task = self.tasks[task_key]
      task.log.append(line)
      progress, message = _progress_from_line(task_key, line, task.progress)
      task.progress = max(task.progress, progress)
      task.message = message or line[-180:]
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
  elif task_key == "build":
    stages = (
      ("collecting osm relations", 5),
      ("relations route=", 10),
      ("building road segments", 15),
      ("parsed ways=", min(52, current + 1)),
      ("built road segments", 55),
      ("indexing directed graph edges", 60),
      ("building road adjacency", 70),
      ("creating indexes", 85),
      ("validating built db", 92),
      ("validated built db", 96),
      ("installed built db", 100),
    )
    for token, progress in stages:
      if token in lower:
        return progress, line
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


class OSMRoadsWebHandler(BaseHTTPRequestHandler):
  runner: OSMRoadsTaskRunner

  def log_message(self, fmt: str, *args: object) -> None:
    print(f"[osm_roads_webui] {self.address_string()} {fmt % args}", flush=True)

  def do_GET(self) -> None:
    parsed = urlparse(self.path)
    if parsed.path in ("", "/", "/index.html"):
      self._serve_index()
    elif parsed.path == "/api/state":
      _json_response(self, HTTPStatus.OK, self.runner.snapshot())
    elif parsed.path == "/api/events":
      self._serve_events()
    else:
      self.send_error(HTTPStatus.NOT_FOUND, "not found")

  def do_POST(self) -> None:
    parsed = urlparse(self.path)
    if parsed.path.startswith("/api/tasks/"):
      task_key = parsed.path.rsplit("/", maxsplit=1)[-1]
      ok, message = self.runner.start(task_key)
      _json_response(self, HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok, "message": message})
    elif parsed.path == "/api/stop":
      ok, message = self.runner.stop()
      _json_response(self, HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok, "message": message})
    else:
      self.send_error(HTTPStatus.NOT_FOUND, "not found")

  def do_OPTIONS(self) -> None:
    self.send_response(HTTPStatus.NO_CONTENT)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.end_headers()

  def _serve_index(self) -> None:
    try:
      body = HTML_PATH.read_bytes()
    except OSError:
      self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"missing HTML: {HTML_PATH}")
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
