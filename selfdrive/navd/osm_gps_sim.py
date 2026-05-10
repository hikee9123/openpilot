#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import time

import cereal.messaging as messaging
from cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog


SIM_RATE_HZ = 10.0
METERS_PER_DEG_LAT = 111111.0


def _env_float(name: str, default: float) -> float:
  value = os.getenv(name)
  if value is None:
    return default
  try:
    return float(value)
  except ValueError:
    cloudlog.warning("invalid %s=%r, using %.6f", name, value, default)
    return default


def _advance_position(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
  bearing_rad = math.radians(bearing_deg)
  north_m = math.cos(bearing_rad) * distance_m
  east_m = math.sin(bearing_rad) * distance_m
  next_lat = lat + north_m / METERS_PER_DEG_LAT
  lon_scale = METERS_PER_DEG_LAT * max(0.2, math.cos(math.radians(lat)))
  next_lon = lon + east_m / lon_scale
  return next_lat, next_lon


def _publish_gps(pm: messaging.PubMaster, lat: float, lon: float, altitude: float, bearing_deg: float, speed: float) -> None:
  bearing_rad = math.radians(bearing_deg)
  north_mps = math.cos(bearing_rad) * speed
  east_mps = math.sin(bearing_rad) * speed

  msg = messaging.new_message("gpsLocationExternal", valid=True)
  gps = msg.gpsLocationExternal
  gps.source = log.GpsLocationData.SensorSource.ublox
  gps.flags = 1
  gps.hasFix = True
  gps.latitude = lat
  gps.longitude = lon
  gps.altitude = altitude
  gps.speed = speed
  gps.bearingDeg = bearing_deg
  gps.horizontalAccuracy = 1.0
  gps.verticalAccuracy = 1.0
  gps.speedAccuracy = 0.1
  gps.bearingAccuracyDeg = 0.1
  gps.unixTimestampMillis = int(time.time() * 1000)
  gps.vNED = [north_mps, east_mps, 0.0]
  pm.send("gpsLocationExternal", msg)


def main() -> None:
  if os.getenv("USE_WEBCAM") is None:
    cloudlog.warning("osm_gps_simd is disabled because USE_WEBCAM is not set")
    return

  params = Params()
  pm = messaging.PubMaster(["gpsLocationExternal"])
  rk = Ratekeeper(SIM_RATE_HZ, print_delay_threshold=None)

  start_lat = _env_float("OSM_GPS_SIM_LAT", 37.501274)
  start_lon = _env_float("OSM_GPS_SIM_LON", 127.039585)
  altitude = _env_float("OSM_GPS_SIM_ALT", 50.0)
  bearing_deg = _env_float("OSM_GPS_SIM_BEARING", 90.0) % 360.0
  speed = max(0.0, _env_float("OSM_GPS_SIM_SPEED", 10.0))
  loop_distance_m = max(0.0, _env_float("OSM_GPS_SIM_LOOP_M", 800.0))

  lat = start_lat
  lon = start_lon
  traveled_m = 0.0
  last_t = time.monotonic()
  last_log_t = 0.0

  cloudlog.info("osm_gps_simd started lat=%.7f lon=%.7f bearing=%.1f speed=%.1f",
                start_lat, start_lon, bearing_deg, speed)

  while True:
    now = time.monotonic()
    dt = max(0.0, min(now - last_t, 1.0))
    last_t = now

    enabled = params.get_bool("OSMEnable") and params.get_bool("OsmGpsSimulation")
    if not enabled:
      if now - last_log_t > 30.0:
        cloudlog.info("osm_gps_simd waiting for OSMEnable and OsmGpsSimulation")
        last_log_t = now
      rk.keep_time()
      continue

    move_m = speed * dt
    if loop_distance_m > 0.0 and traveled_m + move_m > loop_distance_m:
      lat = start_lat
      lon = start_lon
      traveled_m = 0.0
    else:
      lat, lon = _advance_position(lat, lon, bearing_deg, move_m)
      traveled_m += move_m

    _publish_gps(pm, lat, lon, altitude, bearing_deg, speed)
    rk.keep_time()


if __name__ == "__main__":
  main()
