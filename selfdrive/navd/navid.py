#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import re
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
OSM_LOG_REPEAT_SKIP_AFTER = 2
HISTORY_HOLD_MIN_LEN_RATIO = 0.70
HISTORY_HOLD_MIN_LEN_M = 1000.0
OSM_SHORT_FAILURE_RATIO_THRESHOLD = 0.85
OSM_TRACE_LOG_PATH = DEFAULT_NAVD_LOG_DIR / "osm_prediction_trace.csv"
OSM_FAILURE_LOG_PATH = DEFAULT_NAVD_LOG_DIR / "osm_prediction_failures.csv"
OSM_CAMERA_DISPLAY_DISTANCE_PARAM = "OsmCameraDisplayDistanceM"
OSM_CAMERA_DISPLAY_DISTANCE_DEFAULT_M = 1000.0
OSM_CAMERA_DISPLAY_DISTANCE_MIN_M = 350.0
OSM_CAMERA_DISPLAY_DISTANCE_MAX_M = 3000.0
OSM_TRACE_FIELDS = (
  "wall_time",
  "lat",
  "lon",
  "bearing_deg",
  "speed_mps",
  "mode",
  "failure_reason",
  "target_len_m",
  "short_ratio",
  "short_severity",
  "stop_reason",
  "confidence_reason",
  "endpoint_assist_ratio",
  "short_extend_count",
  "fallback_fill_count",
  "corridor_fill_count",
  "camera_display_distance_m",
  "current_road_id",
  "current_name",
  "current_distance_m",
  "current_heading_diff_deg",
  "predicted_len_m",
  "predicted_road_ids",
  "assist_road_ids",
  "nearby_road_ids",
  "normal_camera_id",
  "normal_camera_type",
  "normal_camera_signal",
  "normal_camera_speed_kph",
  "normal_camera_forward_m",
  "nearest_camera_id",
  "nearest_camera_type",
  "nearest_camera_signal",
  "nearest_camera_display_class",
  "nearest_camera_reject_reason",
  "nearest_camera_forward_m",
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
                  prediction_distance_m: float = 0.0, roads: list[dict] | None = None,
                  cameras: list[dict] | None = None) -> None:
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
  camera_items = overlay.init("cameras", len(cameras or []))
  for i, camera in enumerate(cameras or []):
    camera_items[i].cameraId = camera["cameraId"]
    camera_items[i].roadId = camera["roadId"]
    camera_items[i].cameraType = camera["cameraType"]
    camera_items[i].speedLimitKph = camera["speedLimitKph"]
    camera_items[i].x = camera["x"]
    camera_items[i].y = camera["y"]
    camera_items[i].matchDistanceM = camera["matchDistanceM"]
    camera_items[i].matchConfidence = camera["matchConfidence"]
    camera_items[i].primaryMatch = camera["primaryMatch"]
    camera_items[i].bearingDeg = camera["bearingDeg"]
    camera_items[i].displayClass = camera.get("displayClass", "suspicious")
    camera_items[i].directionVerdict = camera.get("directionVerdict", "unknown")
    camera_items[i].rejectReason = camera.get("rejectReason", "")
    camera_items[i].signalCamera = bool(camera.get("signalCamera", False))
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


def _prediction_distance_m(prediction: RoadPrediction) -> float:
  return sum(max(0.0, road.segment_length) for road in prediction.predicted)


def _target_prediction_distance_m(speed_mps: float) -> float:
  if speed_mps >= 20.0:
    return 2000.0
  if speed_mps >= 10.0:
    return 1500.0
  return 1000.0


def _short_ratio(predicted_len_m: float, target_len_m: float) -> float:
  if target_len_m <= 0.0:
    return 1.0
  return min(1.0, max(0.0, predicted_len_m / target_len_m))


def _short_severity(predicted_len_m: float, target_len_m: float) -> str:
  ratio = _short_ratio(predicted_len_m, target_len_m)
  if ratio >= 1.0:
    return ""
  if ratio < 0.50:
    return "critical"
  if ratio < 0.70:
    return "severe"
  if ratio < 0.90:
    return "moderate"
  return "minor"


def _prediction_failure_reason(prediction: RoadPrediction) -> str:
  predicted_len_m = _prediction_distance_m(prediction)
  target_len_m = _target_prediction_distance_m(prediction.gps.speed_mps)
  short = predicted_len_m < target_len_m
  history_hold = "history_hold=1" in prediction.debug_text
  if prediction.current is None:
    return "current_none_short" if short else "current_none_len_ok"
  if history_hold:
    history_min_len_m = max(HISTORY_HOLD_MIN_LEN_M, target_len_m * HISTORY_HOLD_MIN_LEN_RATIO)
    return "" if predicted_len_m >= history_min_len_m else "history_hold_short"
  if short and _short_ratio(predicted_len_m, target_len_m) >= OSM_SHORT_FAILURE_RATIO_THRESHOLD:
    return ""
  if prediction.predicted_from_graph and not short:
    return ""
  if "confidence=assist_uncertain" in prediction.debug_text:
    return "assist_uncertain_short" if short else ""
  if "confidence=fallback_fill" in prediction.debug_text:
    return "fallback_fill_short" if short else ""
  if "confidence=corridor_fill" in prediction.debug_text:
    return "corridor_fill_short" if short else ""
  if "confidence=short_prediction" in prediction.debug_text or short:
    return "graph_short"
  if "stop=no_candidates" in prediction.debug_text:
    return "graph_no_candidates_short" if short else ""
  return "fallback_short" if short else ""


def _prediction_log_allowed(prediction: RoadPrediction) -> bool:
  # GPS can report small non-zero speeds while the car is stationary.
  return prediction.gps.speed_mps >= OSM_LOG_MIN_SPEED_MPS


def _camera_display_distance_m(params: Params) -> float:
  value = OSM_CAMERA_DISPLAY_DISTANCE_DEFAULT_M
  try:
    param_value = params.get(OSM_CAMERA_DISPLAY_DISTANCE_PARAM, return_default=True)
    if param_value not in (None, ""):
      value = float(param_value)
  except Exception:
    value = OSM_CAMERA_DISPLAY_DISTANCE_DEFAULT_M
  return min(OSM_CAMERA_DISPLAY_DISTANCE_MAX_M, max(OSM_CAMERA_DISPLAY_DISTANCE_MIN_M, value))


def _debug_value(debug_text: str, key: str) -> str:
  match = re.search(rf"(?:^| ){re.escape(key)}=([^ ]+)", debug_text)
  return "" if match is None else match.group(1)


def _debug_count(debug_text: str, key: str) -> str:
  value = _debug_value(debug_text, key)
  return value.split("/", 1)[0] if value else ""


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

  def _rotate_if_header_changed(self) -> None:
    if not self.path.exists() or self.path.stat().st_size == 0:
      return
    try:
      with self.path.open("r", encoding="utf-8", newline="") as f:
        header = f.readline().strip()
    except OSError:
      return
    if header == ",".join(OSM_TRACE_FIELDS):
      return
    rotated_path = self.path.with_suffix(self.path.suffix + f".schema.{int(time.time())}")
    self.path.replace(rotated_path)

  def _open(self) -> bool:
    if self._file is not None and self._writer is not None:
      return True
    try:
      self.path.parent.mkdir(parents=True, exist_ok=True)
      self._rotate_if_needed()
      self._rotate_if_header_changed()
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
    self._last_row_key: tuple | None = None
    self._repeat_count = 0

  def set_enabled(self, enabled: bool) -> None:
    if self.enabled == enabled:
      return
    self.enabled = enabled
    if not enabled:
      self.close()

  def close(self) -> None:
    self.trace_log.close()
    self.failure_log.close()
    self._last_row_key = None
    self._repeat_count = 0

  def _repeated_row(self, row: dict) -> bool:
    row_key = (
      row["lat"],
      row["lon"],
      row["bearing_deg"],
      row["speed_mps"],
      row["mode"],
      row["failure_reason"],
      row["current_road_id"],
      row["predicted_road_ids"],
    )
    if row_key == self._last_row_key:
      self._repeat_count += 1
    else:
      self._last_row_key = row_key
      self._repeat_count = 1
    return self._repeat_count > OSM_LOG_REPEAT_SKIP_AFTER

  def _camera_log_fields(self, cameras: list[dict] | None) -> dict[str, str]:
    sorted_cameras = sorted(cameras or [], key=lambda item: (float(item.get("x", 0.0)), int(item.get("cameraId", 0))))
    normal_camera = next((camera for camera in sorted_cameras if camera.get("displayClass") == "normal"), None)
    nearest_camera = sorted_cameras[0] if sorted_cameras else None
    return {
      "normal_camera_id": "" if normal_camera is None else str(normal_camera.get("cameraId", "")),
      "normal_camera_type": "" if normal_camera is None else str(normal_camera.get("cameraType", "")),
      "normal_camera_signal": "" if normal_camera is None else str(int(bool(normal_camera.get("signalCamera", False)))),
      "normal_camera_speed_kph": "" if normal_camera is None else str(normal_camera.get("speedLimitKph", "")),
      "normal_camera_forward_m": "" if normal_camera is None else f"{float(normal_camera.get('x', 0.0)):.1f}",
      "nearest_camera_id": "" if nearest_camera is None else str(nearest_camera.get("cameraId", "")),
      "nearest_camera_type": "" if nearest_camera is None else str(nearest_camera.get("cameraType", "")),
      "nearest_camera_signal": "" if nearest_camera is None else str(int(bool(nearest_camera.get("signalCamera", False)))),
      "nearest_camera_display_class": "" if nearest_camera is None else str(nearest_camera.get("displayClass", "")),
      "nearest_camera_reject_reason": "" if nearest_camera is None else str(nearest_camera.get("rejectReason", "")),
      "nearest_camera_forward_m": "" if nearest_camera is None else f"{float(nearest_camera.get('x', 0.0)):.1f}",
    }

  def _prediction_debug_fields(self, prediction: RoadPrediction) -> dict[str, str]:
    predicted_len_m = _prediction_distance_m(prediction)
    target_len_m = _target_prediction_distance_m(prediction.gps.speed_mps)
    return {
      "target_len_m": f"{target_len_m:.0f}",
      "short_ratio": f"{_short_ratio(predicted_len_m, target_len_m):.3f}",
      "short_severity": _short_severity(predicted_len_m, target_len_m),
      "stop_reason": _debug_value(prediction.debug_text, "stop"),
      "confidence_reason": _debug_value(prediction.debug_text, "confidence"),
      "endpoint_assist_ratio": _debug_value(prediction.debug_text, "assist_ratio"),
      "short_extend_count": _debug_count(prediction.debug_text, "short_extend"),
      "fallback_fill_count": _debug_value(prediction.debug_text, "fallback_fill"),
      "corridor_fill_count": _debug_value(prediction.debug_text, "corridor_fill"),
    }

  def log(self, prediction: RoadPrediction, cameras: list[dict] | None = None,
          camera_display_distance_m: float = OSM_CAMERA_DISPLAY_DISTANCE_DEFAULT_M) -> None:
    if not self.enabled or not _prediction_log_allowed(prediction):
      return

    current = prediction.current
    failure_reason = _prediction_failure_reason(prediction)
    row = {
      "wall_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
      "lat": f"{prediction.gps.lat:.7f}",
      "lon": f"{prediction.gps.lon:.7f}",
      "bearing_deg": f"{prediction.gps.bearing_deg:.1f}",
      "speed_mps": f"{prediction.gps.speed_mps:.2f}",
      "mode": _prediction_mode(prediction),
      "failure_reason": failure_reason,
      **self._prediction_debug_fields(prediction),
      "camera_display_distance_m": f"{camera_display_distance_m:.0f}",
      "current_road_id": "" if current is None else current.road_id,
      "current_name": "" if current is None else current.display_name,
      "current_distance_m": "" if current is None else f"{current.distance_m:.1f}",
      "current_heading_diff_deg": "" if current is None else f"{current.heading_diff_deg:.1f}",
      "predicted_len_m": f"{_prediction_distance_m(prediction):.1f}",
      "predicted_road_ids": _road_ids(prediction.predicted),
      "assist_road_ids": " ".join(str(road_id) for road_id in sorted(prediction.assist_road_ids)),
      "nearby_road_ids": _road_ids(prediction.nearby, limit=40),
      **self._camera_log_fields(cameras),
      "debug": prediction.debug_text,
    }
    if self._repeated_row(row):
      return

    self.trace_log.write(row)
    if failure_reason:
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
      camera_display_distance_m = _camera_display_distance_m(params)
      road_name, bearing, prediction_distance_m, roads, cameras = build_minimap_overlay(
        prediction,
        list(history_segments.values()),
        camera_max_forward_m=camera_display_distance_m,
      )
      if prediction is not None:
        log_writer.log(prediction, cameras, camera_display_distance_m)
      overlay_key = (
        road_name,
        bearing,
        round(prediction_distance_m, 1),
        tuple(tuple(sorted(road.items())) for road in roads),
        tuple(tuple(sorted(camera.items())) for camera in cameras),
      )
      if not last_available or overlay_key != last_overlay or now - last_send_t > 2.5:
        _send_overlay(pm, True, road_name, bearing, prediction_distance_m, roads, cameras)
        last_available = True
        last_overlay = overlay_key
        last_send_t = now

      rk.keep_time()
  finally:
    log_writer.close()
    predictor.close()


if __name__ == "__main__":
  main()
