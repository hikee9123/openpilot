#!/usr/bin/env python3
from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from openpilot.selfdrive.navd.osm_roads import (
  DEFAULT_LOOKUP_RADIUS_M,
  DEFAULT_OSM_ROADS_DB_PATH,
  OSMRoadMatch,
  OSMRoadSegment,
  angle_diff_deg,
  connect_readonly_db,
  database_segment_count,
  find_current_road,
  forward_road_segments,
  latlon_to_car_space_m,
  nearby_road_segments,
  road_successors,
)


@dataclass(frozen=True)
class GPSFix:
  lat: float
  lon: float
  bearing_deg: float
  speed_mps: float = 0.0


@dataclass
class RoadPrediction:
  gps: GPSFix
  current: OSMRoadMatch | None = None
  nearby: list[OSMRoadSegment] = field(default_factory=list)
  predicted: list[OSMRoadSegment] = field(default_factory=list)
  updated_at: float = 0.0


def _distance_m(a: GPSFix, b: GPSFix) -> float:
  dx, dy = latlon_to_car_space_m(a.lat, a.lon, a.bearing_deg, b.lat, b.lon)
  return math.hypot(dx, dy)


class OSMRoadPredictor:
  def __init__(
    self,
    db_path: Path = DEFAULT_OSM_ROADS_DB_PATH,
    lookup_radius_m: float = DEFAULT_LOOKUP_RADIUS_M,
    map_radius_m: float = 220.0,
    forward_distance_m: float = 450.0,
    min_update_interval_s: float = 1.0,
    min_move_m: float = 8.0,
    min_heading_change_deg: float = 8.0,
  ) -> None:
    self.db_path = Path(db_path)
    self.lookup_radius_m = lookup_radius_m
    self.map_radius_m = map_radius_m
    self.forward_distance_m = forward_distance_m
    self.min_update_interval_s = min_update_interval_s
    self.min_move_m = min_move_m
    self.min_heading_change_deg = min_heading_change_deg
    self._conn: sqlite3.Connection | None = None
    self._db_mtime = 0.0
    self._last_gps: GPSFix | None = None
    self._last_prediction: RoadPrediction | None = None
    self._last_update_t = 0.0
    self._successor_cache: dict[int, list[OSMRoadSegment]] = {}

  def close(self) -> None:
    if self._conn is not None:
      self._conn.close()
      self._conn = None

  def ready(self) -> bool:
    return self.db_path.exists() and database_segment_count(self.db_path) > 0

  def _db_changed(self) -> bool:
    try:
      mtime = self.db_path.stat().st_mtime
    except OSError:
      return False
    return self._conn is None or mtime != self._db_mtime

  def _connection(self) -> sqlite3.Connection | None:
    if not self.ready():
      self.close()
      return None
    if self._db_changed():
      self.close()
      self._conn = connect_readonly_db(self.db_path)
      self._db_mtime = self.db_path.stat().st_mtime
      self._successor_cache.clear()
    return self._conn

  def _should_update(self, gps: GPSFix, now: float) -> bool:
    if self._last_prediction is None or self._last_gps is None:
      return True
    if now - self._last_update_t < self.min_update_interval_s:
      return False
    if _distance_m(self._last_gps, gps) >= self.min_move_m:
      return True
    return angle_diff_deg(self._last_gps.bearing_deg, gps.bearing_deg) >= self.min_heading_change_deg

  def update(self, gps: GPSFix, now: float | None = None) -> RoadPrediction | None:
    now = time.monotonic() if now is None else now
    if not self._should_update(gps, now):
      return self._last_prediction

    conn = self._connection()
    if conn is None:
      self._last_prediction = None
      return None

    previous_name = self._last_prediction.current.display_name if self._last_prediction and self._last_prediction.current else ""
    current = find_current_road(conn, gps.lat, gps.lon, gps.bearing_deg, self.lookup_radius_m, previous_name)
    nearby = nearby_road_segments(conn, gps.lat, gps.lon, self.map_radius_m, limit=80)
    predicted = self._predict_forward(conn, gps, current)

    result = RoadPrediction(gps=gps, current=current, nearby=nearby, predicted=predicted, updated_at=now)
    self._last_gps = gps
    self._last_prediction = result
    self._last_update_t = now
    return result

  def _successors(self, conn: sqlite3.Connection, road_id: int) -> list[OSMRoadSegment]:
    cached = self._successor_cache.get(road_id)
    if cached is not None:
      return cached
    successors = [transition.road for transition in road_successors(conn, road_id, limit=8) if transition.turn_angle_deg <= 75.0]
    self._successor_cache[road_id] = successors
    return successors

  def _predict_forward(self, conn: sqlite3.Connection, gps: GPSFix, current: OSMRoadMatch | None) -> list[OSMRoadSegment]:
    if current is None:
      return forward_road_segments(conn, gps.lat, gps.lon, gps.bearing_deg, forward_end_m=self.forward_distance_m, limit=60)

    predicted: list[OSMRoadSegment] = []
    visited = {current.road_id}
    road_id = current.road_id
    bearing = current.bearing_deg

    for _ in range(14):
      candidates = [road for road in self._successors(conn, road_id) if road.road_id not in visited]
      if not candidates:
        break
      candidates.sort(key=lambda road: (angle_diff_deg(bearing, road.bearing_deg), 0 if road.display_name == current.display_name else 1))
      best = candidates[0]
      if angle_diff_deg(bearing, best.bearing_deg) > 95.0:
        break
      predicted.append(best)
      visited.add(best.road_id)
      road_id = best.road_id
      bearing = best.bearing_deg

    if not predicted:
      predicted = forward_road_segments(conn, gps.lat, gps.lon, gps.bearing_deg, forward_end_m=self.forward_distance_m, limit=60)
    return predicted[:40]
