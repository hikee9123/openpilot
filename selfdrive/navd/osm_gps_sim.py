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
from openpilot.system.hardware import PC


SIM_RATE_HZ = 10.0
METERS_PER_DEG_LAT = 111111.0
DEFAULT_ROUTE = (
  (36.8137560, 127.1092039),  # Beonyeong-ro near Cheonan City Hall
  (36.8177683, 127.1104433),
  (36.8213725, 127.1115094),
  (36.8258617, 127.1130777),
  (36.8305737, 127.1148811),
  (36.8356796, 127.1171804),
  (36.8429826, 127.1210348),
  (36.8492216, 127.1241413),
  (36.8499556, 127.1246134),
  (36.8504835, 127.1250318),
  (36.8508935, 127.1254100),
  (36.8511455, 127.1256665),
  (36.8518529, 127.1264829),
  (36.8525741, 127.1275289),
  (36.8531707, 127.1286742),
  (36.8538596, 127.1302433),
  (36.8549520, 127.1327646),
  (36.8556316, 127.1343433),
  (36.8560260, 127.1352672),
  (36.8565308, 127.1364426),
  (36.8568520, 127.1372049),  # Toward Cheonan Police Station
)


def _env_float(name: str, default: float) -> float:
  value = os.getenv(name)
  if value is None:
    return default
  try:
    return float(value)
  except ValueError:
    cloudlog.warning("invalid %s=%r, using %.6f", name, value, default)
    return default


def _param_float(params: Params, name: str, default: float) -> float:
  value = params.get(name)
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


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  north_m = (lat2 - lat1) * METERS_PER_DEG_LAT
  east_m = (lon2 - lon1) * METERS_PER_DEG_LAT * max(0.2, math.cos(math.radians(lat1)))
  return math.hypot(north_m, east_m)


def _bearing_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  north_m = (lat2 - lat1) * METERS_PER_DEG_LAT
  east_m = (lon2 - lon1) * METERS_PER_DEG_LAT * max(0.2, math.cos(math.radians(lat1)))
  return math.degrees(math.atan2(east_m, north_m)) % 360.0


def _advance_route(route: tuple[tuple[float, float], ...], index: int, progress_m: float, distance_m: float) -> tuple[float, float, float, int, float]:
  if len(route) < 2:
    lat, lon = route[0]
    return lat, lon, 0.0, 0, 0.0

  remaining_m = distance_m
  while remaining_m > 0.0:
    lat1, lon1 = route[index]
    lat2, lon2 = route[index + 1]
    segment_m = max(0.1, _distance_m(lat1, lon1, lat2, lon2))
    available_m = segment_m - progress_m
    if remaining_m < available_m:
      progress_m += remaining_m
      break

    remaining_m -= available_m
    index += 1
    progress_m = 0.0
    if index >= len(route) - 1:
      index = 0

  lat1, lon1 = route[index]
  lat2, lon2 = route[index + 1]
  segment_m = max(0.1, _distance_m(lat1, lon1, lat2, lon2))
  ratio = max(0.0, min(1.0, progress_m / segment_m))
  lat = lat1 + (lat2 - lat1) * ratio
  lon = lon1 + (lon2 - lon1) * ratio
  bearing_deg = _bearing_between(lat1, lon1, lat2, lon2)
  return lat, lon, bearing_deg, index, progress_m


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
  if not PC:
    Params().put_bool("OsmGpsSimulation", False)
    cloudlog.warning("osm_gps_simd is disabled on device hardware")
    return

  if os.getenv("USE_WEBCAM") is None:
    cloudlog.warning("osm_gps_simd is disabled because USE_WEBCAM is not set")
    return

  params = Params()
  pm = messaging.PubMaster(["gpsLocationExternal"])
  rk = Ratekeeper(SIM_RATE_HZ, print_delay_threshold=None)

  use_default_route = os.getenv("OSM_GPS_SIM_LAT") is None and os.getenv("OSM_GPS_SIM_LON") is None
  start_lat = _env_float("OSM_GPS_SIM_LAT", DEFAULT_ROUTE[0][0])
  start_lon = _env_float("OSM_GPS_SIM_LON", DEFAULT_ROUTE[0][1])
  altitude = _env_float("OSM_GPS_SIM_ALT", 50.0)
  bearing_deg = _env_float("OSM_GPS_SIM_BEARING", _bearing_between(*DEFAULT_ROUTE[0], *DEFAULT_ROUTE[1])) % 360.0
  speed_kph = max(0.0, _env_float("OSM_GPS_SIM_SPEED", 60.0) if os.getenv("OSM_GPS_SIM_SPEED") is not None
                  else _param_float(params, "OsmGpsSimSpeedKph", 60.0))
  params.put("OsmGpsSimSpeedKph", int(round(speed_kph)))
  speed = speed_kph / 3.6
  loop_distance_m = max(0.0, _env_float("OSM_GPS_SIM_LOOP_M", 0.0 if use_default_route else 800.0))

  lat = start_lat
  lon = start_lon
  route_index = 0
  route_progress_m = 0.0
  traveled_m = 0.0
  last_t = time.monotonic()
  last_log_t = 0.0
  last_speed_kph = speed_kph

  cloudlog.info("osm_gps_simd started lat=%.7f lon=%.7f bearing=%.1f speed=%.1f km/h",
                start_lat, start_lon, bearing_deg, speed_kph)

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

    speed_kph = max(0.0, min(_param_float(params, "OsmGpsSimSpeedKph", speed_kph), 250.0))
    if abs(speed_kph - last_speed_kph) >= 0.5:
      cloudlog.info("osm_gps_simd speed changed to %.1f km/h", speed_kph)
      last_speed_kph = speed_kph
    speed = speed_kph / 3.6
    move_m = speed * dt
    if use_default_route:
      lat, lon, bearing_deg, route_index, route_progress_m = _advance_route(DEFAULT_ROUTE, route_index, route_progress_m, move_m)
    elif loop_distance_m > 0.0 and traveled_m + move_m > loop_distance_m:
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
