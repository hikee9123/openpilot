#!/usr/bin/env python3
from __future__ import annotations

import math
import time

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.navd.osm_minimap import build_minimap_payload
from openpilot.selfdrive.navd.osm_predictor import GPSFix, OSMRoadPredictor


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


def _send_payload(pm: messaging.PubMaster, payload: str, road_name: str = "") -> None:
  msg = messaging.new_message("naviCustom")
  nav = msg.naviCustom.naviData
  nav.active = 1 if payload else 0
  nav.currentRoadName = road_name
  nav.osmRoadOverlayText = payload
  pm.send("naviCustom", msg)


def main() -> None:
  params = Params()
  pm = messaging.PubMaster(["naviCustom"])
  sm = messaging.SubMaster(["gpsLocationExternal", "gpsLocation"])
  rk = Ratekeeper(1.0, print_delay_threshold=None)
  predictor = OSMRoadPredictor()
  last_payload = ""
  last_send_t = 0.0
  last_log_t = 0.0

  try:
    while True:
      sm.update(0)

      if not params.get_bool("OSMEnable"):
        if last_payload:
          _send_payload(pm, "")
          last_payload = ""
        rk.keep_time()
        continue

      gps = _select_gps(sm)
      if gps is None or not predictor.ready():
        if last_payload:
          _send_payload(pm, "")
          last_payload = ""
        now = time.monotonic()
        if now - last_log_t > 30.0:
          cloudlog.info("navid waiting for valid GPS and OSM roads DB")
          last_log_t = now
        rk.keep_time()
        continue

      prediction = predictor.update(gps)
      payload = build_minimap_payload(prediction)
      road_name = prediction.current.display_name if prediction is not None and prediction.current is not None else ""
      now = time.monotonic()
      if payload != last_payload or now - last_send_t > 2.5:
        _send_payload(pm, payload, road_name)
        last_payload = payload
        last_send_t = now

      rk.keep_time()
  finally:
    predictor.close()


if __name__ == "__main__":
  main()
