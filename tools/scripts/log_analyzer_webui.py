#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bz2
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = REPO_ROOT / "tools" / "log_analyzer_webui" / "index.html"
WINDOWS_START_SCRIPT_PATH = REPO_ROOT / "tools" / "log_analyzer_webui" / "start_server.cmd"
UBUNTU_START_SCRIPT_PATH = REPO_ROOT / "tools" / "log_analyzer_webui" / "start_server.sh"
DBC_ROOT = REPO_ROOT / "opendbc_repo" / "opendbc" / "dbc"

LOG_FILENAMES = {
  "rlog": ("rlog.zst", "rlog.bz2", "rlog"),
  "qlog": ("qlog.zst", "qlog.bz2", "qlog"),
  "qcamera": ("qcamera.ts",),
  "fcamera": ("fcamera.hevc",),
  "ecamera": ("ecamera.hevc",),
  "dcamera": ("dcamera.hevc",),
}

SERIES_SIGNALS = {
  "vEgo": ("carState", "vEgo"),
  "aEgo": ("carState", "aEgo"),
  "steeringAngleDeg": ("carState", "steeringAngleDeg"),
  "steeringTorque": ("carState", "steeringTorque"),
  "gasPressed": ("carState", "gasPressed"),
  "brakePressed": ("carState", "brakePressed"),
  "controlsActive": ("controlsState", "active"),
  "controlsEnabled": ("controlsState", "enabled"),
}

TEXT_MESSAGE_TYPES = {"logMessage", "errorLogMessage", "androidLog"}
TIMELINE_TYPES = {"controlsState", "selfdriveState", "carState", "deviceState"}
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
BO_RE = re.compile(r"^BO_ (\w+) (\w+) *: (\w+) (\w+)")
SG_RE = re.compile(r"^SG_ (\w+) : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.+\-eE]+),([0-9.+\-eE]+)\) \[[0-9.+\-eE]+\|[0-9.+\-eE]+\] \".*\" .*")
SGM_RE = re.compile(r"^SG_ (\w+) (\w+) *: (\d+)\|(\d+)@(\d)([+-]) \(([0-9.+\-eE]+),([0-9.+\-eE]+)\) \[[0-9.+\-eE]+\|[0-9.+\-eE]+\] \".*\" .*")


@dataclass
class SegmentInfo:
  route: str
  segment: int
  path: Path | None = None
  files: dict[str, Path] = field(default_factory=dict)
  locked: bool = False
  mtime: float = 0.0

  def add_file(self, key: str, path: Path) -> None:
    self.files[key] = path
    try:
      self.mtime = max(self.mtime, path.stat().st_mtime)
    except OSError:
      pass


@dataclass
class RouteInfo:
  name: str
  segments: dict[int, SegmentInfo] = field(default_factory=dict)
  size_bytes: int = 0
  mtime: float = 0.0

  def add_segment(self, segment: SegmentInfo) -> None:
    current = self.segments.get(segment.segment)
    if current is None:
      self.segments[segment.segment] = segment
    else:
      current.files.update(segment.files)
      current.locked = current.locked or segment.locked
      current.mtime = max(current.mtime, segment.mtime)
      if current.path is None:
        current.path = segment.path
    self.mtime = max(self.mtime, segment.mtime)


@dataclass
class DbcSignal:
  name: str
  start_bit: int
  msb: int
  lsb: int
  size: int
  is_signed: bool
  factor: float
  offset: float
  is_little_endian: bool


@dataclass
class DbcMessage:
  name: str
  address: int
  size: int
  signals: list[DbcSignal] = field(default_factory=list)


ROUTE_CACHE: dict[tuple[str, float], dict[str, object]] = {}
ROUTE_SCAN_CACHE: tuple[float, Path, dict[str, RouteInfo]] | None = None
CAPNP_EVENT_SCHEMA = None
DBC_CACHE: dict[str, dict[int, DbcMessage]] = {}


def prepare_openpilot_imports() -> None:
  # Some Windows checkouts have openpilot/common, openpilot/tools, ... as
  # text symlink placeholders. Extending the package path emulates the POSIX
  # symlink layout for Python imports without changing the checkout.
  try:
    import openpilot
    package_paths = getattr(openpilot, "__path__", None)
    if package_paths is not None and str(REPO_ROOT) not in package_paths:
      package_paths.append(str(REPO_ROOT))
  except ModuleNotFoundError:
    pass


prepare_openpilot_imports()


def default_log_root() -> Path:
  override = os.environ.get("LOG_ROOT")
  if override:
    return Path(override).expanduser()
  device_root = Path("/data/media/0/realdata")
  if device_root.exists():
    return device_root
  return Path.home() / ".comma" / "media" / "0" / "realdata"


def now_text() -> str:
  return time.strftime("%Y-%m-%d %H:%M:%S")


def file_size(path: Path | None) -> int:
  if path is None:
    return 0
  try:
    return path.stat().st_size
  except OSError:
    return 0


def route_time(route: str) -> str:
  match = re.search(r"(\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2})", route)
  if not match:
    return ""
  return match.group(1).replace("--", " ")


def segment_key(route: str, segment: int) -> str:
  return f"{route}--{segment}"


def file_kind(filename: str) -> str | None:
  for key, names in LOG_FILENAMES.items():
    if filename in names:
      return key
  return None


def split_segment_name(name: str) -> tuple[str, int] | None:
  match = re.match(r"^(?P<route>.+)--(?P<segment>[0-9]+)$", name)
  if not match:
    return None
  return match.group("route"), int(match.group("segment"))


def add_segment_file(routes: dict[str, RouteInfo], route: str, segment: int, kind: str, path: Path, segment_path: Path | None) -> None:
  info = routes.setdefault(route, RouteInfo(name=route))
  seg = info.segments.get(segment)
  if seg is None:
    seg = SegmentInfo(route=route, segment=segment, path=segment_path)
  seg.add_file(kind, path)
  if segment_path is not None:
    seg.locked = seg.locked or (segment_path / "rlog.lock").exists()
  info.add_segment(seg)
  info.size_bytes += file_size(path)


def scan_routes_uncached(log_root: Path) -> dict[str, RouteInfo]:
  routes: dict[str, RouteInfo] = {}
  if not log_root.exists():
    return routes

  try:
    children = list(log_root.iterdir())
  except OSError:
    return routes

  for entry in children:
    if entry.is_dir():
      split = split_segment_name(entry.name)
      if split is not None:
        route, segment = split
        try:
          files = list(entry.iterdir())
        except OSError:
          continue
        for path in files:
          if not path.is_file():
            continue
          kind = file_kind(path.name)
          if kind is not None:
            add_segment_file(routes, route, segment, kind, path, entry)
        continue

      # Support a nested layout: <route>/<segment>/<files>.
      route = entry.name
      try:
        segment_dirs = list(entry.iterdir())
      except OSError:
        continue
      for segment_dir in segment_dirs:
        if not segment_dir.is_dir() or not segment_dir.name.isdigit():
          continue
        segment = int(segment_dir.name)
        try:
          files = list(segment_dir.iterdir())
        except OSError:
          continue
        for path in files:
          if not path.is_file():
            continue
          kind = file_kind(path.name)
          if kind is not None:
            add_segment_file(routes, route, segment, kind, path, segment_dir)
    elif entry.is_file():
      # Support explorer-style flat files:
      # <route>--<segment>--qlog.zst
      match = re.match(r"^(?P<seg>.+--[0-9]+)--(?P<file>[A-Za-z0-9_.]+)$", entry.name)
      if not match:
        continue
      kind = file_kind(match.group("file"))
      split = split_segment_name(match.group("seg"))
      if kind is None or split is None:
        continue
      route, segment = split
      add_segment_file(routes, route, segment, kind, entry, None)

  return routes


def scan_routes(log_root: Path) -> dict[str, RouteInfo]:
  global ROUTE_SCAN_CACHE
  now = time.monotonic()
  if ROUTE_SCAN_CACHE is not None:
    cached_at, cached_root, cached_routes = ROUTE_SCAN_CACHE
    if cached_root == log_root and now - cached_at < 3.0:
      return cached_routes
  routes = scan_routes_uncached(log_root)
  ROUTE_SCAN_CACHE = (now, log_root, routes)
  return routes


def route_to_json(route: RouteInfo) -> dict[str, object]:
  segments = sorted(route.segments.values(), key=lambda s: s.segment)
  file_counts = {key: 0 for key in LOG_FILENAMES}
  locked = False
  for seg in segments:
    locked = locked or seg.locked
    for key in seg.files:
      file_counts[key] = file_counts.get(key, 0) + 1
  return {
    "name": route.name,
    "time": route_time(route.name),
    "segments": len(segments),
    "first_segment": segments[0].segment if segments else None,
    "last_segment": segments[-1].segment if segments else None,
    "size_bytes": route.size_bytes,
    "mtime": route.mtime,
    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(route.mtime)) if route.mtime else "",
    "locked": locked,
    "file_counts": file_counts,
  }


def segments_to_json(route: RouteInfo) -> list[dict[str, object]]:
  result = []
  for seg in sorted(route.segments.values(), key=lambda s: s.segment):
    files = {}
    for key, path in sorted(seg.files.items()):
      files[key] = {
        "path": str(path),
        "size_bytes": file_size(path),
      }
    result.append({
      "segment": seg.segment,
      "name": segment_key(route.name, seg.segment),
      "path": str(seg.path) if seg.path is not None else "",
      "locked": seg.locked,
      "mtime": seg.mtime,
      "files": files,
    })
  return result


def selected_segments(route: RouteInfo, segment_query: str) -> list[SegmentInfo]:
  segments = sorted(route.segments.values(), key=lambda s: s.segment)
  query = segment_query.strip().lower()
  if query in ("", "all", "*"):
    return segments
  wanted = set()
  for item in query.split(","):
    item = item.strip()
    if not item:
      continue
    if ":" in item:
      start, end = item.split(":", 1)
      start_i = int(start) if start else segments[0].segment
      end_i = int(end) if end else segments[-1].segment + 1
      wanted.update(range(start_i, end_i))
    else:
      wanted.add(int(item))
  return [seg for seg in segments if seg.segment in wanted]


def log_paths_for(route: RouteInfo, mode: str, segment_query: str) -> list[str]:
  paths = []
  for seg in selected_segments(route, segment_query):
    if mode == "rlog":
      path = seg.files.get("rlog")
    elif mode == "auto":
      path = seg.files.get("rlog") or seg.files.get("qlog")
    else:
      path = seg.files.get("qlog")
    if path is not None:
      paths.append(str(path))
  return paths


def route_fingerprint(route: RouteInfo) -> str:
  values = []
  for seg in sorted(route.segments.values(), key=lambda s: s.segment):
    for key in ("rlog", "qlog"):
      path = seg.files.get(key)
      if path is None:
        continue
      try:
        stat = path.stat()
        values.append(f"{seg.segment}:{key}:{stat.st_size}:{int(stat.st_mtime)}")
      except OSError:
        values.append(f"{seg.segment}:{key}:missing")
  return "|".join(values)


def available_dbc_names() -> list[str]:
  if not DBC_ROOT.exists():
    return []
  return sorted(path.stem for path in DBC_ROOT.glob("*.dbc"))


def default_dbc_name() -> str:
  names = available_dbc_names()
  for preferred in ("hyundai_kia_generic", "hyundai_2015_mcan", "hyundai_canfd_generated", "toyota_new_mc_pt_generated"):
    if preferred in names:
      return preferred
  return names[0] if names else ""


def safe_dbc_name(name: str) -> str:
  clean = Path(name).stem
  if clean in available_dbc_names():
    return clean
  return ""


def load_dbc_messages(name: str) -> dict[int, DbcMessage]:
  name = safe_dbc_name(name)
  if not name:
    return {}
  cached = DBC_CACHE.get(name)
  if cached is not None:
    return cached

  path = DBC_ROOT / f"{name}.dbc"
  be_bits = [j + i * 8 for i in range(64) for j in range(7, -1, -1)]
  messages: dict[int, DbcMessage] = {}
  current_addr: int | None = None
  with path.open(encoding="utf-8", errors="replace") as f:
    for line in f:
      line = line.strip()
      if line.startswith("BO_ "):
        match = BO_RE.match(line)
        if not match:
          current_addr = None
          continue
        current_addr = int(match.group(1), 0)
        messages[current_addr] = DbcMessage(
          name=match.group(2),
          address=current_addr,
          size=int(match.group(3), 0),
        )
      elif line.startswith("SG_ ") and current_addr is not None and current_addr in messages:
        match = SG_RE.search(line)
        offset = 0
        if not match:
          match = SGM_RE.search(line)
          offset = 1
        if not match:
          continue
        start_bit = int(match.group(2 + offset))
        size = int(match.group(3 + offset))
        is_little_endian = match.group(4 + offset) == "1"
        if is_little_endian:
          lsb = start_bit
          msb = start_bit + size - 1
        else:
          try:
            idx = be_bits.index(start_bit)
          except ValueError:
            continue
          lsb = be_bits[idx + size - 1]
          msb = start_bit
        messages[current_addr].signals.append(DbcSignal(
          name=match.group(1),
          start_bit=start_bit,
          msb=msb,
          lsb=lsb,
          size=size,
          is_signed=match.group(5 + offset) == "-",
          factor=float(match.group(6 + offset)),
          offset=float(match.group(7 + offset)),
          is_little_endian=is_little_endian,
        ))

  DBC_CACHE[name] = messages
  return messages


def get_raw_signal_value(dat: bytes, sig: DbcSignal) -> int:
  ret = 0
  i = sig.msb // 8
  bits = sig.size
  while 0 <= i < len(dat) and bits > 0:
    lsb = sig.lsb if (sig.lsb // 8) == i else i * 8
    msb = sig.msb if (sig.msb // 8) == i else (i + 1) * 8 - 1
    size = msb - lsb + 1
    d = (dat[i] >> (lsb - (i * 8))) & ((1 << size) - 1)
    ret |= d << (bits - size)
    bits -= size
    i = i - 1 if sig.is_little_endian else i + 1
  return ret


def decode_dbc_message(dbc_name: str, address: int, data_hex: str) -> dict[str, object]:
  messages = load_dbc_messages(dbc_name)
  msg = messages.get(address)
  if msg is None:
    return {}
  data = bytes.fromhex(data_hex)
  signals = []
  for sig in msg.signals:
    raw = get_raw_signal_value(data, sig)
    if sig.is_signed and sig.size > 0:
      raw -= ((raw >> (sig.size - 1)) & 1) * (1 << sig.size)
    value = raw * sig.factor + sig.offset
    signals.append({
      "name": sig.name,
      "raw": raw,
      "value": value,
      "start_bit": sig.start_bit,
      "size": sig.size,
      "factor": sig.factor,
      "offset": sig.offset,
    })
  return {
    "dbc": dbc_name,
    "message_name": msg.name,
    "address": address,
    "address_hex": hex(address),
    "size": msg.size,
    "signals": signals,
  }


class CachedEventReader:
  __slots__ = ("_evt", "_enum")

  def __init__(self, evt, enum: str | None = None) -> None:
    self._evt = evt
    self._enum = enum

  def which(self) -> str:
    if self._enum is None:
      self._enum = self._evt.which()
    return self._enum

  def __getattr__(self, name: str):
    return getattr(self._evt, name)

  def __str__(self) -> str:
    return str(self._evt)


def resolve_text_symlink(path: Path) -> Path:
  try:
    text = path.read_text(encoding="utf-8").strip()
  except UnicodeDecodeError:
    return path
  except OSError:
    return path
  if "\n" in text or len(text) > 260:
    return path
  candidate = (path.parent / text).resolve()
  if candidate.exists() and candidate.suffix == path.suffix:
    return candidate
  return path


def materialized_capnp_dir() -> Path:
  target = Path(tempfile.gettempdir()) / "openpilot_log_analyzer_capnp"
  include_target = target / "include"
  include_target.mkdir(parents=True, exist_ok=True)

  for name in ("log.capnp", "legacy.capnp", "custom.capnp", "car.capnp"):
    source = resolve_text_symlink(REPO_ROOT / "cereal" / name)
    shutil.copyfile(source, target / name)
  shutil.copyfile(resolve_text_symlink(REPO_ROOT / "cereal" / "include" / "c++.capnp"), include_target / "c++.capnp")
  return target


def capnp_event_schema():
  global CAPNP_EVENT_SCHEMA
  if CAPNP_EVENT_SCHEMA is not None:
    return CAPNP_EVENT_SCHEMA
  try:
    import capnp
  except ModuleNotFoundError as e:
    if e.name == "capnp":
      raise RuntimeError("Missing Python package pycapnp. Install it with: python -m pip install pycapnp zstandard") from e
    raise
  schema_dir = materialized_capnp_dir()
  capnp.remove_import_hook()
  CAPNP_EVENT_SCHEMA = capnp.load(str(schema_dir / "log.capnp")).Event
  return CAPNP_EVENT_SCHEMA


def decompress_log_data(path: str, data: bytes) -> bytes:
  ext = Path(path).suffix
  if ext == ".bz2" or data.startswith(b"BZh9"):
    return bz2.decompress(data)
  if ext == ".zst" or data.startswith(b"\x28\xB5\x2F\xFD"):
    try:
      import zstandard as zstd
    except ModuleNotFoundError as e:
      if e.name == "zstandard":
        raise RuntimeError("Missing Python package zstandard. Install it with: python -m pip install zstandard") from e
      raise
    dctx = zstd.ZstdDecompressor()
    with dctx.stream_reader(data) as reader:
      return reader.read()
  return data


def iter_log_messages(paths: list[str], sort_by_time: bool = False):
  schema = capnp_event_schema()
  for path in paths:
    data = Path(path).read_bytes()
    data = decompress_log_data(path, data)
    try:
      ents = schema.read_multiple_bytes(data)
      msgs = [CachedEventReader(e) for e in ents]
    except Exception as e:
      raise RuntimeError(f"failed to read {path}: {e}") from e
    if sort_by_time:
      msgs.sort(key=lambda x: safe_attr(x, "logMonoTime") or 0)
    yield from msgs


def import_logreader():
  try:
    capnp_event_schema()
  except ModuleNotFoundError as e:
    if e.name == "zstandard":
      raise RuntimeError("Missing Python package zstandard. Install it with: python -m pip install zstandard") from e
    raise
  return iter_log_messages


def safe_which(msg) -> str:
  try:
    return msg.which()
  except Exception:
    return "unknown"


def safe_attr(obj, name: str):
  try:
    return getattr(obj, name)
  except Exception:
    return None


def jsonable(value):
  if isinstance(value, (bool, int, float, str)) or value is None:
    return value
  if isinstance(value, bytes):
    return value.hex()
  if isinstance(value, (list, tuple)):
    return [jsonable(v) for v in value[:16]]
  return str(value)


def as_float(value) -> float | None:
  if isinstance(value, bool):
    return 1.0 if value else 0.0
  if isinstance(value, (int, float)):
    return float(value)
  return None


def event_time_ms(log_mono_time: int | float | None, start_time: int | None) -> float:
  if log_mono_time is None or start_time is None:
    return 0.0
  return max(0.0, (float(log_mono_time) - float(start_time)) / 1e6)


def get_signal_value(msg, signal: str):
  spec = SERIES_SIGNALS.get(signal)
  if spec is None:
    return None
  msg_type, attr = spec
  if safe_which(msg) != msg_type:
    return None
  value = safe_attr(safe_attr(msg, msg_type), attr)
  return as_float(value)


def extract_timeline_event(msg, msg_type: str, start_time: int | None) -> dict[str, object] | None:
  payload = safe_attr(msg, msg_type)
  if payload is None:
    return None
  t_ms = event_time_ms(safe_attr(msg, "logMonoTime"), start_time)

  if msg_type == "controlsState":
    alert1 = str(safe_attr(payload, "alertText1") or "")
    alert2 = str(safe_attr(payload, "alertText2") or "")
    active = safe_attr(payload, "active")
    enabled = safe_attr(payload, "enabled")
    state = safe_attr(payload, "state")
    if not alert1 and not alert2 and active is None and enabled is None:
      return None
    return {
      "time_ms": t_ms,
      "type": msg_type,
      "title": "controls",
      "detail": f"active={jsonable(active)} enabled={jsonable(enabled)} state={jsonable(state)} {alert1} {alert2}".strip(),
    }

  if msg_type == "selfdriveState":
    enabled = safe_attr(payload, "enabled")
    active = safe_attr(payload, "active")
    alert1 = str(safe_attr(payload, "alertText1") or "")
    alert2 = str(safe_attr(payload, "alertText2") or "")
    return {
      "time_ms": t_ms,
      "type": msg_type,
      "title": "selfdrive",
      "detail": f"active={jsonable(active)} enabled={jsonable(enabled)} {alert1} {alert2}".strip(),
    }

  if msg_type == "deviceState":
    thermal = safe_attr(payload, "thermalStatus")
    free_space = safe_attr(payload, "freeSpacePercent")
    if thermal is None and free_space is None:
      return None
    return {
      "time_ms": t_ms,
      "type": msg_type,
      "title": "device",
      "detail": f"thermal={jsonable(thermal)} free={jsonable(free_space)}",
    }

  if msg_type == "carState":
    cruise = safe_attr(payload, "cruiseState")
    speed = safe_attr(payload, "vEgo")
    enabled = safe_attr(cruise, "enabled") if cruise is not None else None
    available = safe_attr(cruise, "available") if cruise is not None else None
    if enabled is None and available is None:
      return None
    return {
      "time_ms": t_ms,
      "type": msg_type,
      "title": "cruise",
      "detail": f"vEgo={jsonable(speed)} cruiseEnabled={jsonable(enabled)} available={jsonable(available)}",
    }

  return None


def analyze_summary(route: RouteInfo, mode: str, segment_query: str) -> dict[str, object]:
  cache_key = (f"summary:{route.name}:{mode}:{segment_query}", hash(route_fingerprint(route)))
  cached = ROUTE_CACHE.get(cache_key)
  if cached is not None:
    return cached

  paths = log_paths_for(route, mode, segment_query)
  counts: dict[str, int] = {}
  timeline: list[dict[str, object]] = []
  first_time: int | None = None
  last_time: int | None = None
  message_count = 0
  errors: list[str] = []

  try:
    for msg in iter_log_messages(paths):
      message_count += 1
      msg_time = safe_attr(msg, "logMonoTime")
      if isinstance(msg_time, int):
        first_time = msg_time if first_time is None else min(first_time, msg_time)
        last_time = msg_time if last_time is None else max(last_time, msg_time)
      msg_type = safe_which(msg)
      counts[msg_type] = counts.get(msg_type, 0) + 1
      if msg_type in TIMELINE_TYPES and len(timeline) < 250:
        event = extract_timeline_event(msg, msg_type, first_time)
        if event is not None:
          timeline.append(event)
  except Exception as e:
    errors.append(repr(e))

  duration_s = 0.0
  if first_time is not None and last_time is not None:
    duration_s = max(0.0, (last_time - first_time) / 1e9)

  data = {
    "route": route_to_json(route),
    "segments": segments_to_json(route),
    "mode": mode,
    "selected_segments": segment_query or "all",
    "log_paths": paths,
    "message_count": message_count,
    "duration_s": duration_s,
    "counts": sorted(({"type": key, "count": value} for key, value in counts.items()), key=lambda x: x["count"], reverse=True),
    "timeline": timeline,
    "errors": errors,
  }
  ROUTE_CACHE[cache_key] = data
  return data


def analyze_series(route: RouteInfo, mode: str, segment_query: str, signal_query: str, max_points: int) -> dict[str, object]:
  signals = [s.strip() for s in signal_query.split(",") if s.strip()]
  signals = [s for s in signals if s in SERIES_SIGNALS]
  if not signals:
    signals = ["vEgo", "steeringAngleDeg", "aEgo", "controlsActive"]

  paths = log_paths_for(route, mode, segment_query)
  raw_points: list[dict[str, object]] = []
  first_time: int | None = None
  errors: list[str] = []

  try:
    for msg in iter_log_messages(paths):
      msg_time = safe_attr(msg, "logMonoTime")
      if isinstance(msg_time, int):
        first_time = msg_time if first_time is None else min(first_time, msg_time)
      values = {}
      for signal in signals:
        value = get_signal_value(msg, signal)
        if value is not None:
          values[signal] = value
      if values:
        raw_points.append({
          "time_ms": event_time_ms(msg_time, first_time),
          "values": values,
        })
  except Exception as e:
    errors.append(repr(e))

  if len(raw_points) > max_points:
    step = max(1, len(raw_points) // max_points)
    raw_points = raw_points[::step][:max_points]

  return {
    "signals": signals,
    "points": raw_points,
    "errors": errors,
  }


def analyze_text_logs(route: RouteInfo, mode: str, segment_query: str, limit: int) -> dict[str, object]:
  paths = log_paths_for(route, mode, segment_query)
  rows = []
  first_time: int | None = None
  errors: list[str] = []

  try:
    for msg in iter_log_messages(paths):
      msg_time = safe_attr(msg, "logMonoTime")
      if isinstance(msg_time, int):
        first_time = msg_time if first_time is None else min(first_time, msg_time)
      msg_type = safe_which(msg)
      if msg_type not in TEXT_MESSAGE_TYPES:
        continue
      payload = safe_attr(msg, msg_type)
      rows.append({
        "time_ms": event_time_ms(msg_time, first_time),
        "type": msg_type,
        "text": str(payload)[:3000],
      })
      if len(rows) >= limit:
        break
  except Exception as e:
    errors.append(repr(e))

  return {"rows": rows, "errors": errors}


def analyze_messages(route: RouteInfo, mode: str, segment_query: str, msg_type: str, limit: int) -> dict[str, object]:
  paths = log_paths_for(route, mode, segment_query)
  rows = []
  first_time: int | None = None
  errors: list[str] = []

  try:
    for msg in iter_log_messages(paths):
      msg_time = safe_attr(msg, "logMonoTime")
      if isinstance(msg_time, int):
        first_time = msg_time if first_time is None else min(first_time, msg_time)
      if safe_which(msg) != msg_type:
        continue
      payload = safe_attr(msg, msg_type)
      rows.append({
        "time_ms": event_time_ms(msg_time, first_time),
        "type": msg_type,
        "text": str(payload)[:5000],
      })
      if len(rows) >= limit:
        break
  except Exception as e:
    errors.append(repr(e))

  return {"rows": rows, "errors": errors}


def analyze_can(route: RouteInfo, mode: str, segment_query: str, frame_type: str, limit: int,
                address_filter: int | None = None, dbc_name: str = "") -> dict[str, object]:
  paths = log_paths_for(route, mode, segment_query)
  counts: dict[tuple[int, int], dict[str, object]] = {}
  samples = []
  first_time: int | None = None
  errors: list[str] = []
  msg_type = "sendcan" if frame_type == "sendcan" else "can"
  dbc_messages = load_dbc_messages(dbc_name) if dbc_name else {}

  try:
    for msg in iter_log_messages(paths):
      if safe_which(msg) != msg_type:
        continue
      msg_time = safe_attr(msg, "logMonoTime")
      if isinstance(msg_time, int):
        first_time = msg_time if first_time is None else min(first_time, msg_time)
      frames = safe_attr(msg, msg_type) or []
      for frame in frames:
        address = int(safe_attr(frame, "address") or 0)
        if address_filter is not None and address != address_filter:
          continue
        src = int(safe_attr(frame, "src") or 0)
        key = (address, src)
        dbc_msg = dbc_messages.get(address)
        row = counts.setdefault(key, {
          "address": address,
          "address_hex": hex(address),
          "message_name": dbc_msg.name if dbc_msg is not None else "",
          "signal_count": len(dbc_msg.signals) if dbc_msg is not None else 0,
          "signal_names": [sig.name for sig in dbc_msg.signals] if dbc_msg is not None else [],
          "src": src,
          "count": 0,
          "last_data": "",
          "first_time_ms": None,
          "last_time_ms": None,
          "dlc": 0,
        })
        row["count"] = int(row["count"]) + 1
        t_ms = event_time_ms(msg_time, first_time)
        if row["first_time_ms"] is None:
          row["first_time_ms"] = t_ms
        row["last_time_ms"] = t_ms
        try:
          frame_data = bytes(safe_attr(frame, "dat") or b"")
          row["last_data"] = frame_data.hex()
          row["dlc"] = len(frame_data)
        except Exception:
          row["last_data"] = str(safe_attr(frame, "dat"))[:80]
          row["dlc"] = 0
        if len(samples) < limit:
          decoded = decode_dbc_message(dbc_name, address, row["last_data"]) if dbc_name else {}
          samples.append({
            "time_ms": t_ms,
            "address": address,
            "address_hex": hex(address),
            "message_name": dbc_msg.name if dbc_msg is not None else "",
            "src": src,
            "data": row["last_data"],
            "dlc": row["dlc"],
            "signals": decoded.get("signals", []),
          })
  except Exception as e:
    errors.append(repr(e))

  summary = sorted(counts.values(), key=lambda x: int(x["count"]), reverse=True)
  for row in summary:
    first_ms = row.get("first_time_ms")
    last_ms = row.get("last_time_ms")
    duration_s = 0.0
    if isinstance(first_ms, (int, float)) and isinstance(last_ms, (int, float)):
      duration_s = max(0.001, (float(last_ms) - float(first_ms)) / 1000.0)
    row["frequency_hz"] = round(int(row["count"]) / duration_s, 2) if duration_s > 0 else 0.0

  return {
    "summary": summary[:limit],
    "samples": samples,
    "address_filter": hex(address_filter) if address_filter is not None else "",
    "dbc": dbc_name,
    "errors": errors,
  }


def clamp_int(value: str, default: int, minimum: int, maximum: int) -> int:
  try:
    parsed = int(value)
  except (TypeError, ValueError):
    return default
  return max(minimum, min(maximum, parsed))


def query_first(query: dict[str, list[str]], key: str, default: str = "") -> str:
  values = query.get(key)
  if not values:
    return default
  return values[0]


def server_health(args: argparse.Namespace, started_monotonic: float) -> dict[str, object]:
  log_root = Path(args.log_root).expanduser()
  return {
    "status": "ok",
    "server_time": now_text(),
    "uptime_s": round(time.monotonic() - started_monotonic, 1),
    "platform": platform.system().lower(),
    "repo_root": str(REPO_ROOT),
    "log_root": str(log_root),
    "log_root_exists": log_root.exists(),
    "start_script_path": str(WINDOWS_START_SCRIPT_PATH if platform.system().lower().startswith("win") else UBUNTU_START_SCRIPT_PATH),
    "windows_start_script_path": str(WINDOWS_START_SCRIPT_PATH),
    "ubuntu_start_script_path": str(UBUNTU_START_SCRIPT_PATH),
  }


class LogAnalyzerHandler(BaseHTTPRequestHandler):
  server_version = "LogAnalyzerWebUI/1.0"

  def log_message(self, fmt: str, *args) -> None:
    if getattr(self.server, "quiet", False):
      return
    super().log_message(fmt, *args)

  @property
  def args(self) -> argparse.Namespace:
    return self.server.args

  def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    try:
      self.wfile.write(data)
    except CLIENT_DISCONNECT_ERRORS:
      pass

  def send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK, content_type: str = "text/plain; charset=utf-8") -> None:
    data = text.encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    try:
      self.wfile.write(data)
    except CLIENT_DISCONNECT_ERRORS:
      pass

  def send_html(self) -> None:
    try:
      data = HTML_PATH.read_bytes()
    except OSError:
      self.send_text(f"Missing {HTML_PATH}", HTTPStatus.NOT_FOUND)
      return
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    try:
      self.wfile.write(data)
    except CLIENT_DISCONNECT_ERRORS:
      pass

  def get_routes(self) -> dict[str, RouteInfo]:
    return scan_routes(Path(self.args.log_root).expanduser())

  def find_route(self, route_name: str) -> RouteInfo | None:
    routes = self.get_routes()
    return routes.get(unquote(route_name))

  def do_GET(self) -> None:
    parsed = urlparse(self.path)
    query = parse_qs(parsed.query)
    try:
      if parsed.path in ("", "/"):
        self.send_html()
      elif parsed.path == "/api/health":
        self.send_json(server_health(self.args, self.server.started_monotonic))
      elif parsed.path == "/api/routes":
        routes = sorted((route_to_json(route) for route in self.get_routes().values()), key=lambda x: float(x["mtime"]), reverse=True)
        self.send_json({"log_root": str(Path(self.args.log_root).expanduser()), "routes": routes})
      elif parsed.path == "/api/dbc/list":
        dbcs = available_dbc_names()
        self.send_json({"dbcs": dbcs, "default": default_dbc_name()})
      elif parsed.path == "/api/summary":
        route = self.require_route(query)
        mode = query_first(query, "mode", "qlog")
        segment_query = query_first(query, "segments", "all")
        self.send_json(analyze_summary(route, mode, segment_query))
      elif parsed.path == "/api/series":
        route = self.require_route(query)
        mode = query_first(query, "mode", "qlog")
        segment_query = query_first(query, "segments", "all")
        signal_query = query_first(query, "signals", "")
        max_points = clamp_int(query_first(query, "max_points", "800"), 800, 100, 5000)
        self.send_json(analyze_series(route, mode, segment_query, signal_query, max_points))
      elif parsed.path == "/api/text":
        route = self.require_route(query)
        mode = query_first(query, "mode", "qlog")
        segment_query = query_first(query, "segments", "all")
        limit = clamp_int(query_first(query, "limit", "200"), 200, 1, 1000)
        self.send_json(analyze_text_logs(route, mode, segment_query, limit))
      elif parsed.path == "/api/messages":
        route = self.require_route(query)
        mode = query_first(query, "mode", "qlog")
        segment_query = query_first(query, "segments", "all")
        msg_type = query_first(query, "type", "controlsState")
        limit = clamp_int(query_first(query, "limit", "80"), 80, 1, 300)
        self.send_json(analyze_messages(route, mode, segment_query, msg_type, limit))
      elif parsed.path == "/api/can":
        route = self.require_route(query)
        mode = query_first(query, "mode", "rlog")
        segment_query = query_first(query, "segments", "all")
        frame_type = query_first(query, "frame_type", "can")
        limit = clamp_int(query_first(query, "limit", "200"), 200, 1, 2000)
        addr = query_first(query, "addr", "").strip()
        address_filter = int(addr, 0) if addr else None
        dbc_name = safe_dbc_name(query_first(query, "dbc", ""))
        self.send_json(analyze_can(route, mode, segment_query, frame_type, limit, address_filter, dbc_name))
      else:
        self.send_text("Not found", HTTPStatus.NOT_FOUND)
    except ValueError as e:
      self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
    except Exception as e:
      self.send_json({"error": repr(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

  def require_route(self, query: dict[str, list[str]]) -> RouteInfo:
    route_name = query_first(query, "route", "")
    if not route_name:
      raise ValueError("missing route")
    route = self.find_route(route_name)
    if route is None:
      raise ValueError(f"route not found: {route_name}")
    return route


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Run a local web UI for openpilot drive log analysis")
  parser.add_argument("--host", default="127.0.0.1")
  parser.add_argument("--port", type=int, default=8091)
  parser.add_argument("--log-root", default=str(default_log_root()))
  parser.add_argument("--quiet", action="store_true")
  return parser.parse_args()


def main() -> None:
  args = parse_args()
  server = ThreadingHTTPServer((args.host, args.port), LogAnalyzerHandler)
  server.args = args
  server.quiet = args.quiet
  server.started_monotonic = time.monotonic()
  print(f"Serving log analyzer web UI at http://{args.host}:{args.port}/")
  print(f"Repo: {REPO_ROOT}")
  print(f"Log root: {Path(args.log_root).expanduser()}")
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    pass
  finally:
    server.server_close()


if __name__ == "__main__":
  main()
