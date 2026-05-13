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
  # Samsung Display Cheonan -> Samsung-daero -> Cheonan IC -> North Cheonan IC -> Heehong Valleyview Apt.
  # Generated from OpenStreetMap/OSRM route geometry on 2026-05-13.
  (36.8404530, 127.1194850),
  (36.8403970, 127.1194570),
  (36.8398620, 127.1192660),
  (36.8397330, 127.1192210),
  (36.8396660, 127.1192030),
  (36.8395930, 127.1192030),
  (36.8395140, 127.1192230),
  (36.8394350, 127.1192610),
  (36.8393860, 127.1193060),
  (36.8393410, 127.1193540),
  (36.8393040, 127.1194300),
  (36.8392600, 127.1195950),
  (36.8392450, 127.1197430),
  (36.8392390, 127.1198220),
  (36.8392290, 127.1201240),
  (36.8392250, 127.1203250),
  (36.8391670, 127.1230930),
  (36.8391560, 127.1238060),
  (36.8391550, 127.1239050),
  (36.8391540, 127.1239540),
  (36.8391530, 127.1240180),
  (36.8390970, 127.1279130),
  (36.8390870, 127.1286020),
  (36.8390820, 127.1289810),
  (36.8390580, 127.1306330),
  (36.8390510, 127.1311100),
  (36.8390200, 127.1330630),
  (36.8390130, 127.1335440),
  (36.8390100, 127.1340270),
  (36.8390170, 127.1344300),
  (36.8390440, 127.1348050),
  (36.8390450, 127.1357950),
  (36.8390480, 127.1360510),
  (36.8390390, 127.1369170),
  (36.8390110, 127.1378460),
  (36.8389850, 127.1387540),
  (36.8389400, 127.1411620),
  (36.8389270, 127.1422350),
  (36.8389110, 127.1422980),
  (36.8388490, 127.1452560),
  (36.8388400, 127.1461470),
  (36.8388320, 127.1476460),
  (36.8387980, 127.1492810),
  (36.8387910, 127.1493760),
  (36.8388160, 127.1497320),
  (36.8388780, 127.1511010),
  (36.8389080, 127.1516720),
  (36.8390160, 127.1531770),
  (36.8390500, 127.1535950),
  (36.8390780, 127.1541740),
  (36.8391450, 127.1552010),
  (36.8391620, 127.1557600),
  (36.8391420, 127.1564100),
  (36.8390850, 127.1567430),
  (36.8390670, 127.1568780),
  (36.8390290, 127.1571210),
  (36.8389490, 127.1575200),
  (36.8388170, 127.1579450),
  (36.8386280, 127.1584540),
  (36.8383950, 127.1589780),
  (36.8382600, 127.1592120),
  (36.8380190, 127.1596040),
  (36.8378430, 127.1598270),
  (36.8375800, 127.1601180),
  (36.8371900, 127.1604860),
  (36.8369950, 127.1606510),
  (36.8366710, 127.1608800),
  (36.8363480, 127.1610760),
  (36.8358800, 127.1612760),
  (36.8355840, 127.1613780),
  (36.8352520, 127.1614680),
  (36.8348810, 127.1615310),
  (36.8346220, 127.1615510),
  (36.8343080, 127.1615650),
  (36.8336360, 127.1615500),
  (36.8312920, 127.1615940),
  (36.8311420, 127.1615970),
  (36.8304000, 127.1616430),
  (36.8298870, 127.1616730),
  (36.8296880, 127.1616970),
  (36.8294820, 127.1617580),
  (36.8290520, 127.1619040),
  (36.8285620, 127.1622360),
  (36.8281230, 127.1626090),
  (36.8279970, 127.1627390),
  (36.8278960, 127.1628670),
  (36.8277890, 127.1630240),
  (36.8276500, 127.1632310),
  (36.8275430, 127.1634130),
  (36.8274700, 127.1635470),
  (36.8274130, 127.1636500),
  (36.8273530, 127.1638020),
  (36.8272260, 127.1641200),
  (36.8270830, 127.1645630),
  (36.8269690, 127.1649920),
  (36.8268210, 127.1655520),
  (36.8266960, 127.1660440),
  (36.8264900, 127.1668100),
  (36.8261350, 127.1681900),
  (36.8259240, 127.1689080),
  (36.8258560, 127.1691880),
  (36.8258280, 127.1693500),
  (36.8258120, 127.1695290),
  (36.8258080, 127.1696710),
  (36.8258190, 127.1698580),
  (36.8258370, 127.1699940),
  (36.8258850, 127.1701790),
  (36.8259530, 127.1703410),
  (36.8260140, 127.1704700),
  (36.8260960, 127.1705960),
  (36.8261760, 127.1707020),
  (36.8262450, 127.1707680),
  (36.8263460, 127.1708450),
  (36.8264490, 127.1708990),
  (36.8265680, 127.1709390),
  (36.8266960, 127.1709550),
  (36.8269070, 127.1709400),
  (36.8272130, 127.1708960),
  (36.8274680, 127.1708560),
  (36.8277000, 127.1708200),
  (36.8279570, 127.1707830),
  (36.8282100, 127.1707820),
  (36.8284630, 127.1708200),
  (36.8286820, 127.1708940),
  (36.8288540, 127.1709410),
  (36.8290280, 127.1710150),
  (36.8291810, 127.1711000),
  (36.8303860, 127.1718510),
  (36.8311640, 127.1724330),
  (36.8315350, 127.1727490),
  (36.8320090, 127.1731030),
  (36.8324340, 127.1734140),
  (36.8330060, 127.1738060),
  (36.8331150, 127.1738780),
  (36.8332240, 127.1739500),
  (36.8336360, 127.1741880),
  (36.8340400, 127.1743800),
  (36.8344900, 127.1745400),
  (36.8350100, 127.1746700),
  (36.8358900, 127.1748400),
  (36.8367730, 127.1749890),
  (36.8376600, 127.1751380),
  (36.8381130, 127.1752190),
  (36.8386070, 127.1753070),
  (36.8392390, 127.1754200),
  (36.8408190, 127.1757050),
  (36.8420700, 127.1759260),
  (36.8426160, 127.1760210),
  (36.8432500, 127.1761450),
  (36.8436330, 127.1762250),
  (36.8442000, 127.1764160),
  (36.8443210, 127.1764560),
  (36.8449870, 127.1767470),
  (36.8457130, 127.1771470),
  (36.8470420, 127.1779400),
  (36.8485490, 127.1787650),
  (36.8497680, 127.1794730),
  (36.8507320, 127.1800130),
  (36.8514270, 127.1804300),
  (36.8528070, 127.1812070),
  (36.8539390, 127.1818370),
  (36.8552200, 127.1825500),
  (36.8594000, 127.1849760),
  (36.8599620, 127.1852450),
  (36.8605370, 127.1854840),
  (36.8612250, 127.1857100),
  (36.8622760, 127.1859420),
  (36.8633300, 127.1861190),
  (36.8681980, 127.1869160),
  (36.8685060, 127.1869660),
  (36.8685390, 127.1869720),
  (36.8703060, 127.1872520),
  (36.8715710, 127.1874530),
  (36.8719470, 127.1875130),
  (36.8759670, 127.1881610),
  (36.8788200, 127.1886140),
  (36.8792730, 127.1886860),
  (36.8812070, 127.1890140),
  (36.8816930, 127.1890970),
  (36.8828070, 127.1892230),
  (36.8839140, 127.1893220),
  (36.8861960, 127.1893860),
  (36.8873530, 127.1893680),
  (36.8912730, 127.1893330),
  (36.8964910, 127.1892870),
  (36.8975890, 127.1894300),
  (36.8977300, 127.1894560),
  (36.8978020, 127.1894860),
  (36.8978640, 127.1895190),
  (36.8979460, 127.1895860),
  (36.8980010, 127.1896530),
  (36.8980550, 127.1897360),
  (36.8980920, 127.1898220),
  (36.8981120, 127.1899020),
  (36.8981220, 127.1899870),
  (36.8981230, 127.1900580),
  (36.8981220, 127.1901160),
  (36.8981150, 127.1901710),
  (36.8980970, 127.1902500),
  (36.8980680, 127.1903260),
  (36.8980260, 127.1904060),
  (36.8979800, 127.1904600),
  (36.8978980, 127.1905450),
  (36.8978400, 127.1905950),
  (36.8977680, 127.1906410),
  (36.8976850, 127.1906830),
  (36.8976000, 127.1907050),
  (36.8975390, 127.1907140),
  (36.8974580, 127.1907150),
  (36.8973850, 127.1907070),
  (36.8972910, 127.1906870),
  (36.8971910, 127.1906460),
  (36.8970890, 127.1905810),
  (36.8970390, 127.1905440),
  (36.8969980, 127.1905020),
  (36.8969470, 127.1904240),
  (36.8968900, 127.1903180),
  (36.8968560, 127.1902390),
  (36.8968280, 127.1901510),
  (36.8968010, 127.1900510),
  (36.8967910, 127.1899610),
  (36.8967720, 127.1896960),
  (36.8967720, 127.1895360),
  (36.8967590, 127.1883800),
  (36.8967550, 127.1879680),
  (36.8967580, 127.1876340),
  (36.8967800, 127.1873340),
  (36.8968170, 127.1870400),
  (36.8969470, 127.1864960),
  (36.8970060, 127.1862700),
  (36.8970580, 127.1860950),
  (36.8971240, 127.1858920),
  (36.8971880, 127.1857310),
  (36.8973170, 127.1854550),
  (36.8974190, 127.1852650),
  (36.8975590, 127.1850330),
  (36.8981690, 127.1841530),
  (36.8983930, 127.1838290),
  (36.8995100, 127.1821690),
  (36.9006220, 127.1805170),
  (36.9006840, 127.1804240),
  (36.9016280, 127.1790190),
  (36.9018940, 127.1786220),
  (36.9028680, 127.1771640),
  (36.9031810, 127.1766990),
  (36.9035700, 127.1761180),
  (36.9036230, 127.1760290),
  (36.9036780, 127.1759250),
  (36.9037220, 127.1758030),
  (36.9037640, 127.1756450),
  (36.9037860, 127.1755080),
  (36.9037870, 127.1753700),
  (36.9037530, 127.1751470),
  (36.9036950, 127.1749990),
  (36.9036130, 127.1748430),
  (36.9035430, 127.1747440),
  (36.9034880, 127.1746840),
  (36.9034120, 127.1746230),
  (36.9033020, 127.1745540),
  (36.9031870, 127.1745040),
  (36.9030850, 127.1744890),
  (36.9029990, 127.1744830),
  (36.9029080, 127.1745020),
  (36.9027890, 127.1745330),
  (36.9026470, 127.1745970),
  (36.9025170, 127.1746620),
  (36.9023520, 127.1747290),
  (36.9021290, 127.1748100),
  (36.9020120, 127.1748280),
  (36.9019090, 127.1748330),
  (36.9017610, 127.1748390),
  (36.9016740, 127.1748210),
  (36.9015860, 127.1747970),
  (36.9014700, 127.1747540),
  (36.9013520, 127.1746980),
  (36.9012060, 127.1745870),
  (36.9009460, 127.1743450),
  (36.9005090, 127.1739160),
  (36.9003790, 127.1737530),
  (36.9002170, 127.1735200),
  (36.9000660, 127.1732950),
  (36.8999510, 127.1730970),
  (36.8997910, 127.1728180),
  (36.8996120, 127.1724900),
  (36.8992280, 127.1715230),
  (36.8991110, 127.1711680),
  (36.8990120, 127.1708070),
  (36.8989640, 127.1706070),
  (36.8988720, 127.1701630),
  (36.8987640, 127.1695020),
  (36.8986900, 127.1690270),
  (36.8986220, 127.1681000),
  (36.8985470, 127.1670900),
  (36.8984680, 127.1660320),
  (36.8980750, 127.1658870),
  (36.8979940, 127.1658570),
  (36.8978310, 127.1657890),
  (36.8975380, 127.1656810),
  (36.8973130, 127.1655960),
  (36.8972050, 127.1655310),
  (36.8971120, 127.1654710),
  (36.8970600, 127.1654370),
  (36.8970190, 127.1654040),
  (36.8970090, 127.1653630),
  (36.8969880, 127.1653260),
  (36.8969580, 127.1653000),
  (36.8969230, 127.1652880),
  (36.8968860, 127.1652910),
  (36.8968530, 127.1653100),
  (36.8968260, 127.1653410),
  (36.8968100, 127.1653820),
  (36.8968050, 127.1654270),
  (36.8968130, 127.1654710),
  (36.8968220, 127.1654900),
  (36.8967330, 127.1657020),
  (36.8966580, 127.1659260),
  (36.8966020, 127.1660980),
  (36.8963230, 127.1661890),
  (36.8962800, 127.1662010),
  (36.8962910, 127.1664090),
  (36.8962670, 127.1664830),
  (36.8961880, 127.1665660),
  (36.8959460, 127.1668000),
  (36.8958360, 127.1667970),
  (36.8957720, 127.1668640),
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
