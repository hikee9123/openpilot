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
  # Captured from comma_10.30.188.86_20260513_172821 osm_prediction_trace.csv.
  (36.7973191, 127.1085011),
  (36.7974201, 127.1084447),
  (36.7975317, 127.1083781),
  (36.7976595, 127.1082919),
  (36.7978048, 127.1082041),
  (36.7979507, 127.1081173),
  (36.7980863, 127.1080369),
  (36.7982161, 127.1079692),
  (36.7983462, 127.1079177),
  (36.7984773, 127.1078793),
  (36.7986161, 127.1078701),
  (36.7987580, 127.1078913),
  (36.7989055, 127.1079278),
  (36.7990576, 127.1079876),
  (36.7992206, 127.1080704),
  (36.7993835, 127.1081511),
  (36.7995448, 127.1082256),
  (36.7996978, 127.1082968),
  (36.7998440, 127.1083667),
  (36.7999973, 127.1084458),
  (36.8001500, 127.1085169),
  (36.8003001, 127.1085540),
  (36.8004607, 127.1085807),
  (36.8006310, 127.1085953),
  (36.8007201, 127.1086030),
  (36.8008958, 127.1086259),
  (36.8010748, 127.1086477),
  (36.8012515, 127.1086775),
  (36.8014179, 127.1087081),
  (36.8015634, 127.1087420),
  (36.8016601, 127.1087644),
  (36.8017427, 127.1087757),
  (36.8017661, 127.1087806),
  (36.8017919, 127.1087997),
  (36.8018344, 127.1088641),
  (36.8018450, 127.1088959),
  (36.8018566, 127.1089956),
  (36.8018677, 127.1091623),
  (36.8018711, 127.1092649),
  (36.8018751, 127.1094918),
  (36.8018785, 127.1097397),
  (36.8018785, 127.1099982),
  (36.8018749, 127.1102575),
  (36.8018693, 127.1105185),
  (36.8018609, 127.1107711),
  (36.8018542, 127.1110230),
  (36.8018376, 127.1112629),
  (36.8018278, 127.1114885),
  (36.8018163, 127.1116804),
  (36.8017952, 127.1118193),
  (36.8017702, 127.1118672),
  (36.8017090, 127.1119144),
  (36.8016483, 127.1119329),
  (36.8015401, 127.1119298),
  (36.8013885, 127.1119152),
  (36.8012229, 127.1118845),
  (36.8010513, 127.1118185),
  (36.8008911, 127.1117040),
  (36.8007440, 127.1115684),
  (36.8006027, 127.1114006),
  (36.8004667, 127.1112147),
  (36.8003149, 127.1110113),
  (36.8001639, 127.1108058),
  (36.8000005, 127.1106027),
  (36.7998426, 127.1104047),
  (36.7997623, 127.1103126),
  (36.7995811, 127.1101616),
  (36.7993902, 127.1100390),
  (36.7991974, 127.1099198),
  (36.7990047, 127.1098019),
  (36.7988124, 127.1096829),
  (36.7986271, 127.1095664),
  (36.7984445, 127.1094243),
  (36.7982683, 127.1092674),
  (36.7981093, 127.1091246),
  (36.7979854, 127.1089923),
  (36.7979121, 127.1088902),
  (36.7978130, 127.1087448),
  (36.7977641, 127.1086691),
  (36.7976970, 127.1085678),
  (36.7976077, 127.1084549),
  (36.7974953, 127.1083876),
  (36.7973676, 127.1083811),
  (36.7972678, 127.1084281),
  (36.7971977, 127.1084592),
  (36.7971245, 127.1084683),
  (36.7970494, 127.1084720),
  (36.7969606, 127.1084794),
  (36.7968965, 127.1084987),
  (36.7968074, 127.1085413),
  (36.7967891, 127.1085321),
  (36.7967074, 127.1085073),
  (36.7966155, 127.1084789),
  (36.7965251, 127.1084510),
  (36.7964332, 127.1084226),
  (36.7963428, 127.1083946),
  (36.7962510, 127.1083662),
  (36.7961606, 127.1083383),
  (36.7960687, 127.1083099),
  (36.7959783, 127.1082819),
  (36.7958864, 127.1082535),
  (36.7957960, 127.1082256),
  (36.7957042, 127.1081972),
  (36.7956138, 127.1081692),
  (36.7955219, 127.1081408),
  (36.7954315, 127.1081129),
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
