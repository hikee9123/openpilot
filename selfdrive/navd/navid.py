#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import time
from collections import OrderedDict
from pathlib import Path

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.navd.osm_minimap import build_minimap_overlay
from openpilot.selfdrive.navd.osm_predictor import GPSFix, OSMRoadPredictor, RoadPrediction
from openpilot.selfdrive.navd.osm_roads import OSMRoadSegment
from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_LOG_DIR


HISTORY_SEGMENT_LIMIT = 40
OSM_TRACE_LOG_MAX_BYTES = 10 * 1024 * 1024
OSM_LOG_MIN_SPEED_MPS = 1.0
OSM_TRACE_LOG_PATH = DEFAULT_NAVD_LOG_DIR / "osm_prediction_trace.csv"
OSM_FAILURE_LOG_PATH = DEFAULT_NAVD_LOG_DIR / "osm_prediction_failures.csv"
OSM_TRACE_FIELDS = (
  "wall_time",
  "lat",
  "lon",
  "bearing_deg",
  "speed_mps",
  "mode",
  "current_road_id",
  "current_name",
  "current_distance_m",
  "current_heading_diff_deg",
  "predicted_road_ids",
  "assist_road_ids",
  "nearby_road_ids",
  "debug",
)


def _valid_number(value: float) -> bool:
  return math.isfinite(value) and abs(value) > 1e-7


def _select_gps(sm: messaging.SubMaster) -> GPSFix | None:
  for service in ("gpsLocationExternal", "gpsLocation"):
    if sm.recv_frame[service] < 0:
      continue
    gps = sm[service]
    lat = float(getattr(gps, "latitude", 0.0))
    lon = float(getattr(gps, "longitude", 0.0))
    if not _valid_number(lat) or not _valid_number(lon):
      continue
    bearing = float(getattr(gps, "bearingDeg", 0.0)) % 360.0
    speed = max(0.0, float(getattr(gps, "speed", 0.0)))
    return GPSFix(lat, lon, bearing, speed)
  return None


def _send_overlay(pm: messaging.PubMaster, available: bool, road_name: str = "", bearing: float = 0.0,
                  prediction_distance_m: float = 0.0, roads: list[dict] | None = None) -> None:
  msg = messaging.new_message("naviCustom")
  nav = msg.naviCustom.naviData
  nav.active = 1 if available else 0
  nav.currentRoadName = road_name
  overlay = nav.init("osmRoadOverlay")
  overlay.road = road_name
  overlay.bearing = bearing
  overlay.predictionDistanceM = prediction_distance_m
  road_items = overlay.init("roads", len(roads or []))
  for i, road in enumerate(roads or []):
    road_items[i].roadId = road["roadId"]
    road_items[i].name = road["name"]
    road_items[i].highway = road["highway"]
    road_items[i].x1 = road["x1"]
    road_items[i].y1 = road["y1"]
    road_items[i].x2 = road["x2"]
    road_items[i].y2 = road["y2"]
    road_items[i].current = road["current"]
    road_items[i].predicted = road["predicted"]
    road_items[i].history = road["history"]
    road_items[i].fallback = road["fallback"]
    road_items[i].assist = road["assist"]
  pm.send("naviCustom", msg)


def _current_segment(prediction) -> OSMRoadSegment | None:
  if prediction is None or prediction.current is None:
    return None
  current_id = prediction.current.road_id
  for segment in prediction.nearby:
    if segment.road_id == current_id:
      return segment
  return None


def _prediction_mode(prediction: RoadPrediction) -> str:
  if prediction.predicted_from_graph:
    return "graph_assist" if prediction.predicted_from_assist else "graph"
  return "fallback_assist" if prediction.predicted_from_assist else "fallback"


def _road_ids(roads: list[OSMRoadSegment], limit: int = 80) -> str:
  return " ".join(str(road.road_id) for road in roads[:limit])


def _prediction_log_allowed(prediction: RoadPrediction) -> bool:
  # GPS can report small non-zero speeds while the car is stationary.
  return prediction.gps.speed_mps >= OSM_LOG_MIN_SPEED_MPS


class CsvLogWriter:
  def __init__(self, path: Path) -> None:
    self.path = path
    self._file = None
    self._writer: csv.DictWriter | None = None
    self._last_error_t = 0.0

  def close(self) -> None:
    if self._file is not None:
      self._file.close()
      self._file = None
      self._writer = None

  def _rotate_if_needed(self) -> None:
    if not self.path.exists() or self.path.stat().st_size < OSM_TRACE_LOG_MAX_BYTES:
      return
    rotated_path = self.path.with_suffix(self.path.suffix + ".1")
    if rotated_path.exists():
      rotated_path.unlink()
    self.path.replace(rotated_path)

  def _open(self) -> bool:
    if self._file is not None and self._writer is not None:
      return True
    try:
      self.path.parent.mkdir(parents=True, exist_ok=True)
      self._rotate_if_needed()
      write_header = not self.path.exists() or self.path.stat().st_size == 0
      self._file = self.path.open("a", newline="", encoding="utf-8")
      self._writer = csv.DictWriter(self._file, fieldnames=OSM_TRACE_FIELDS)
      if write_header:
        self._writer.writeheader()
      return True
    except OSError as exc:
      now = time.monotonic()
      if now - self._last_error_t > 30.0:
        cloudlog.warning("navd csv log open failed path=%s error=%s", self.path, exc)
        self._last_error_t = now
      self.close()
      return False

  def write(self, row: dict) -> None:
    if not self._open() or self._writer is None or self._file is None:
      return

    try:
      self._writer.writerow(row)
      self._file.flush()
    except OSError as exc:
      now = time.monotonic()
      if now - self._last_error_t > 30.0:
        cloudlog.warning("navd csv log write failed path=%s error=%s", self.path, exc)
        self._last_error_t = now
      self.close()


class OsmPredictionLogWriter:
  def __init__(self, trace_path: Path, failure_path: Path) -> None:
    self.enabled = False
    self.trace_log = CsvLogWriter(trace_path)
    self.failure_log = CsvLogWriter(failure_path)

  def set_enabled(self, enabled: bool) -> None:
    if self.enabled == enabled:
      return
    self.enabled = enabled
    if not enabled:
      self.close()

  def close(self) -> None:
    self.trace_log.close()
    self.failure_log.close()

  def log(self, prediction: RoadPrediction) -> None:
    if not self.enabled or not _prediction_log_allowed(prediction):
      return

    current = prediction.current
    row = {
      "wall_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
      "lat": f"{prediction.gps.lat:.7f}",
      "lon": f"{prediction.gps.lon:.7f}",
      "bearing_deg": f"{prediction.gps.bearing_deg:.1f}",
      "speed_mps": f"{prediction.gps.speed_mps:.2f}",
      "mode": _prediction_mode(prediction),
      "current_road_id": "" if current is None else current.road_id,
      "current_name": "" if current is None else current.display_name,
      "current_distance_m": "" if current is None else f"{current.distance_m:.1f}",
      "current_heading_diff_deg": "" if current is None else f"{current.heading_diff_deg:.1f}",
      "predicted_road_ids": _road_ids(prediction.predicted),
      "assist_road_ids": " ".join(str(road_id) for road_id in sorted(prediction.assist_road_ids)),
      "nearby_road_ids": _road_ids(prediction.nearby, limit=40),
      "debug": prediction.debug_text,
    }
    self.trace_log.write(row)
    if not prediction.predicted_from_graph:
      self.failure_log.write(row)


def main() -> None:
  params = Params()
  pm = messaging.PubMaster(["naviCustom"])
  sm = messaging.SubMaster(["gpsLocationExternal", "gpsLocation"])
  rk = Ratekeeper(1.0, print_delay_threshold=None)
  predictor = OSMRoadPredictor()
  last_overlay: tuple[str, float, tuple[tuple, ...]] | None = None
  last_available = False
  last_send_t = 0.0
  last_log_t = 0.0
  last_prediction_debug = ""
  last_prediction_debug_t = 0.0
  history_segments: OrderedDict[int, OSMRoadSegment] = OrderedDict()
  log_writer = OsmPredictionLogWriter(OSM_TRACE_LOG_PATH, OSM_FAILURE_LOG_PATH)

  try:
    while True:
      sm.update(0)

      osm_enabled = params.get_bool("OSMEnable")
      nav_logging_enabled = params.get_bool("NavdLogging")
      osm_logging_enabled = osm_enabled and nav_logging_enabled and params.get_bool("OsmPredictionLogging")
      log_writer.set_enabled(osm_logging_enabled)

      if not osm_enabled:
        if last_available:
          _send_overlay(pm, False)
          last_available = False
          last_overlay = None
          history_segments.clear()
        rk.keep_time()
        continue

      gps = _select_gps(sm)
      if gps is None or not predictor.ready():
        if last_available:
          _send_overlay(pm, False)
          last_available = False
          last_overlay = None
          history_segments.clear()
        now = time.monotonic()
        if nav_logging_enabled and now - last_log_t > 30.0:
          cloudlog.info("navid waiting for valid GPS and OSM roads DB")
          last_log_t = now
        rk.keep_time()
        continue

      prediction = predictor.update(gps)
      now = time.monotonic()
      if prediction is not None:
        log_writer.log(prediction)
        if osm_logging_enabled and _prediction_log_allowed(prediction) and prediction.debug_text:
          prediction_debug = f"{_prediction_mode(prediction)} {prediction.debug_text}"
          log_interval_s = 30.0 if prediction.predicted_from_graph else 5.0
          if prediction_debug != last_prediction_debug or now - last_prediction_debug_t > log_interval_s:
            cloudlog.info("osm_predictor %s", prediction_debug)
            print(f"[osm_predictor] {prediction_debug}", flush=True)
            last_prediction_debug = prediction_debug
            last_prediction_debug_t = now
      current_segment = _current_segment(prediction)
      if current_segment is not None:
        history_segments.pop(current_segment.road_id, None)
        history_segments[current_segment.road_id] = current_segment
        while len(history_segments) > HISTORY_SEGMENT_LIMIT:
          history_segments.popitem(last=False)
      road_name, bearing, prediction_distance_m, roads = build_minimap_overlay(prediction, list(history_segments.values()))
      overlay_key = (road_name, bearing, round(prediction_distance_m, 1), tuple(tuple(sorted(road.items())) for road in roads))
      if not last_available or overlay_key != last_overlay or now - last_send_t > 2.5:
        _send_overlay(pm, True, road_name, bearing, prediction_distance_m, roads)
        last_available = True
        last_overlay = overlay_key
        last_send_t = now

      rk.keep_time()
  finally:
    log_writer.close()
    predictor.close()


if __name__ == "__main__":
  main()
