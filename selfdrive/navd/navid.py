#!/usr/bin/env python3
from __future__ import annotations

import math
import time
from collections import OrderedDict

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.navd.osm_minimap import build_minimap_overlay
from openpilot.selfdrive.navd.osm_predictor import GPSFix, OSMRoadPredictor
from openpilot.selfdrive.navd.osm_roads import OSMRoadSegment


HISTORY_SEGMENT_LIMIT = 40


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


def _send_overlay(pm: messaging.PubMaster, available: bool, road_name: str = "", bearing: float = 0.0, roads: list[dict] | None = None) -> None:
  msg = messaging.new_message("naviCustom")
  nav = msg.naviCustom.naviData
  nav.active = 1 if available else 0
  nav.currentRoadName = road_name
  overlay = nav.init("osmRoadOverlay")
  overlay.road = road_name
  overlay.bearing = bearing
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
  pm.send("naviCustom", msg)


def _current_segment(prediction) -> OSMRoadSegment | None:
  if prediction is None or prediction.current is None:
    return None
  current_id = prediction.current.road_id
  for segment in prediction.nearby:
    if segment.road_id == current_id:
      return segment
  return None


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

  try:
    while True:
      sm.update(0)

      if not params.get_bool("OSMEnable"):
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
        if now - last_log_t > 30.0:
          cloudlog.info("navid waiting for valid GPS and OSM roads DB")
          last_log_t = now
        rk.keep_time()
        continue

      prediction = predictor.update(gps)
      now = time.monotonic()
      if prediction is not None and not prediction.predicted_from_graph and prediction.debug_text:
        if prediction.debug_text != last_prediction_debug or now - last_prediction_debug_t > 5.0:
          cloudlog.info("osm_predictor %s", prediction.debug_text)
          print(f"[osm_predictor] {prediction.debug_text}", flush=True)
          last_prediction_debug = prediction.debug_text
          last_prediction_debug_t = now
      current_segment = _current_segment(prediction)
      if current_segment is not None:
        history_segments.pop(current_segment.road_id, None)
        history_segments[current_segment.road_id] = current_segment
        while len(history_segments) > HISTORY_SEGMENT_LIMIT:
          history_segments.popitem(last=False)
      road_name, bearing, roads = build_minimap_overlay(prediction, list(history_segments.values()))
      overlay_key = (road_name, bearing, tuple(tuple(sorted(road.items())) for road in roads))
      if not last_available or overlay_key != last_overlay or now - last_send_t > 2.5:
        _send_overlay(pm, True, road_name, bearing, roads)
        last_available = True
        last_overlay = overlay_key
        last_send_t = now

      rk.keep_time()
  finally:
    predictor.close()


if __name__ == "__main__":
  main()
