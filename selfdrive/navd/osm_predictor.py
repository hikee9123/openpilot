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
  driving_bearing_for_oneway,
  find_current_road,
  forward_road_segments,
  latlon_to_car_space_m,
  nearby_road_segments,
  road_successors,
)

MAX_GRAPH_HEADING_DIFF_DEG = 70.0
MIN_GRAPH_SIDE_OFFSET_M = 80.0
MAX_GRAPH_SIDE_OFFSET_M = 260.0
MAX_GRAPH_SKIP_AHEAD_SEGMENTS = 5
MAX_GRAPH_ENDPOINT_ASSIST_M = 260.0


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
  predicted_from_graph: bool = False
  predicted_from_assist: bool = False
  assist_road_ids: set[int] = field(default_factory=set)
  debug_text: str = ""
  updated_at: float = 0.0


@dataclass(frozen=True)
class _SuccessorCandidate:
  score: float
  heading_diff_deg: float
  forward_m: float
  road: OSMRoadSegment
  driving_bearing_deg: float


def _distance_m(a: GPSFix, b: GPSFix) -> float:
  dx, dy = latlon_to_car_space_m(a.lat, a.lon, a.bearing_deg, b.lat, b.lon)
  return math.hypot(dx, dy)


def _same_display_name(a: str, b: str) -> bool:
  return bool(a) and bool(b) and a == b


def _same_road_identity(current_name: str, current_osm_id: int, road: OSMRoadSegment) -> bool:
  return _same_display_name(current_name, road.display_name) or (current_osm_id > 0 and road.osm_id == current_osm_id)


def _format_rejects(rejects: dict[str, int]) -> str:
  if not rejects:
    return "none"
  return ", ".join(f"{reason}={count}" for reason, count in sorted(rejects.items()))


class OSMRoadPredictor:
  def __init__(
    self,
    db_path: Path = DEFAULT_OSM_ROADS_DB_PATH,
    lookup_radius_m: float = DEFAULT_LOOKUP_RADIUS_M,
    map_radius_m: float = 220.0,
    forward_distance_m: float = 1000.0,
    min_update_interval_s: float = 1.0,
    min_move_m: float = 8.0,
    min_heading_change_deg: float = 8.0,
    ready_cache_interval_s: float = 5.0,
  ) -> None:
    self.db_path = Path(db_path)
    self.lookup_radius_m = lookup_radius_m
    self.map_radius_m = map_radius_m
    self.forward_distance_m = forward_distance_m
    self.min_update_interval_s = min_update_interval_s
    self.min_move_m = min_move_m
    self.min_heading_change_deg = min_heading_change_deg
    self.ready_cache_interval_s = ready_cache_interval_s
    self._conn: sqlite3.Connection | None = None
    self._db_mtime = 0.0
    self._ready_cache_valid = False
    self._ready_cache_value = False
    self._ready_cache_t = 0.0
    self._ready_cache_mtime: float | None = None
    self._last_gps: GPSFix | None = None
    self._last_prediction: RoadPrediction | None = None
    self._last_update_t = 0.0
    self._successor_cache: dict[int, list[OSMRoadSegment]] = {}

  def close(self) -> None:
    if self._conn is not None:
      self._conn.close()
      self._conn = None

  def _db_file_mtime(self) -> float | None:
    try:
      return self.db_path.stat().st_mtime
    except OSError:
      return None

  def ready(self) -> bool:
    now = time.monotonic()
    if self._ready_cache_valid and now - self._ready_cache_t < self.ready_cache_interval_s:
      return self._ready_cache_value

    mtime = self._db_file_mtime()
    ready = mtime is not None and database_segment_count(self.db_path) > 0
    self._ready_cache_valid = True
    self._ready_cache_value = ready
    self._ready_cache_t = now
    self._ready_cache_mtime = mtime
    return ready

  def _db_changed(self) -> bool:
    mtime = self._ready_cache_mtime
    if mtime is None:
      return False
    return self._conn is None or mtime != self._db_mtime

  def _connection(self) -> sqlite3.Connection | None:
    if not self.ready():
      self.close()
      return None
    if self._db_changed():
      self.close()
      self._conn = connect_readonly_db(self.db_path)
      self._db_mtime = self._ready_cache_mtime or self.db_path.stat().st_mtime
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

    previous_current = self._last_prediction.current if self._last_prediction is not None else None
    previous_name = previous_current.display_name if previous_current is not None else ""
    previous_road_id = previous_current.road_id if previous_current is not None else None
    previous_osm_id = previous_current.osm_id if previous_current is not None else None
    current = find_current_road(conn, gps.lat, gps.lon, gps.bearing_deg, self.lookup_radius_m,
                                previous_name, previous_road_id, previous_osm_id)
    nearby = nearby_road_segments(conn, gps.lat, gps.lon, self.map_radius_m, limit=80)
    predicted, predicted_from_graph, predicted_from_assist, assist_road_ids, debug_text = self._predict_forward(conn, gps, current)

    result = RoadPrediction(gps=gps, current=current, nearby=nearby, predicted=predicted,
                            predicted_from_graph=predicted_from_graph, predicted_from_assist=predicted_from_assist,
                            assist_road_ids=assist_road_ids, debug_text=debug_text, updated_at=now)
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

  def _road_segment(self, conn: sqlite3.Connection, road_id: int) -> OSMRoadSegment | None:
    try:
      row = conn.execute("""
        SELECT id, osm_id, name, ref, highway, road_class, oneway,
               lat1, lon1, lat2, lon2, bearing_deg, 0.0 AS distance_m
        FROM roads
        WHERE id = ?
      """, (road_id,)).fetchone()
    except sqlite3.Error:
      return None
    if row is None:
      return None
    return OSMRoadSegment(
      road_id=int(row["id"]),
      osm_id=int(row["osm_id"]),
      name=str(row["name"] or ""),
      ref=str(row["ref"] or ""),
      highway=str(row["highway"] or ""),
      road_class=str(row["road_class"] or ""),
      oneway=int(row["oneway"]),
      lat1=float(row["lat1"]),
      lon1=float(row["lon1"]),
      lat2=float(row["lat2"]),
      lon2=float(row["lon2"]),
      bearing_deg=float(row["bearing_deg"]),
      distance_m=float(row["distance_m"]),
    )

  def _score_successor(self, gps: GPSFix, reference_bearing_deg: float, current_name: str, road: OSMRoadSegment) -> tuple[_SuccessorCandidate | None, str]:
    x1, y1 = latlon_to_car_space_m(gps.lat, gps.lon, gps.bearing_deg, road.lat1, road.lon1)
    x2, y2 = latlon_to_car_space_m(gps.lat, gps.lon, gps.bearing_deg, road.lat2, road.lon2)
    if max(x1, x2) < 5.0:
      return None, "behind"

    forward_points = [x for x in (x1, x2) if x >= 0.0]
    forward_m = min(forward_points) if forward_points else max(x1, x2)
    side_offset_m = min(abs(y1), abs(y2))
    side_limit_m = min(MAX_GRAPH_SIDE_OFFSET_M, max(MIN_GRAPH_SIDE_OFFSET_M, forward_m * 0.45))
    if side_offset_m > side_limit_m:
      return None, "side_offset"

    road_bearing = driving_bearing_for_oneway(road.bearing_deg, road.oneway, reference_bearing_deg)
    heading_diff = angle_diff_deg(reference_bearing_deg, road_bearing)
    if heading_diff > MAX_GRAPH_HEADING_DIFF_DEG:
      return None, "heading_diff"

    same_name_bonus = -12.0 if _same_display_name(current_name, road.display_name) else 0.0
    score = heading_diff * 3.0 + side_offset_m * 0.35 + forward_m * 0.02 + same_name_bonus
    return _SuccessorCandidate(score, heading_diff, forward_m, road, road_bearing), ""

  def _skip_ahead_successor(self, conn: sqlite3.Connection, gps: GPSFix, reference_bearing_deg: float,
                            current_name: str, current_osm_id: int, start_road: OSMRoadSegment,
                            visited: set[int]) -> tuple[_SuccessorCandidate | None, int]:
    if not _same_road_identity(current_name, current_osm_id, start_road):
      return None, 0

    frontier = [start_road]
    seen = set(visited)
    seen.add(start_road.road_id)
    skipped = 0
    while frontier and skipped < MAX_GRAPH_SKIP_AHEAD_SEGMENTS:
      road = frontier.pop(0)
      skipped += 1
      for next_road in self._successors(conn, road.road_id):
        if next_road.road_id in seen:
          continue
        seen.add(next_road.road_id)
        if not _same_road_identity(current_name, current_osm_id, next_road):
          continue
        candidate, reject_reason = self._score_successor(gps, reference_bearing_deg, current_name, next_road)
        if candidate is not None:
          return candidate, skipped
        if reject_reason == "behind":
          frontier.append(next_road)
    return None, skipped

  def _endpoint_assist_successor(self, conn: sqlite3.Connection, gps: GPSFix, reference_bearing_deg: float,
                                 current_name: str, road_id: int, visited: set[int]) -> _SuccessorCandidate | None:
    road = self._road_segment(conn, road_id)
    if road is None:
      return None

    forward_to_lat2 = angle_diff_deg(road.bearing_deg, reference_bearing_deg) <= 90.0
    end_lat = road.lat2 if forward_to_lat2 else road.lat1
    end_lon = road.lon2 if forward_to_lat2 else road.lon1
    candidates = forward_road_segments(conn, end_lat, end_lon, reference_bearing_deg,
                                       forward_start_m=-20.0, forward_end_m=MAX_GRAPH_ENDPOINT_ASSIST_M,
                                       side_limit_m=90.0, major_side_limit_m=130.0, limit=80)
    scored: list[tuple[float, _SuccessorCandidate]] = []
    for candidate_road in candidates:
      if candidate_road.road_id in visited or candidate_road.road_id == road_id:
        continue
      candidate, reject_reason = self._score_successor(gps, reference_bearing_deg, current_name, candidate_road)
      if candidate is None:
        continue
      x1, y1 = latlon_to_car_space_m(end_lat, end_lon, reference_bearing_deg, candidate_road.lat1, candidate_road.lon1)
      x2, y2 = latlon_to_car_space_m(end_lat, end_lon, reference_bearing_deg, candidate_road.lat2, candidate_road.lon2)
      endpoint_gap_m = min(math.hypot(x1, y1), math.hypot(x2, y2))
      scored.append((candidate.score + endpoint_gap_m * 0.4, candidate))
    if not scored:
      return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]

  def _predict_forward(self, conn: sqlite3.Connection, gps: GPSFix, current: OSMRoadMatch | None) -> tuple[list[OSMRoadSegment], bool, bool, set[int], str]:
    if current is None:
      predicted = forward_road_segments(conn, gps.lat, gps.lon, gps.bearing_deg, forward_start_m=5.0, forward_end_m=self.forward_distance_m, limit=60)
      return predicted, False, False, set(), f"current=none fallback_count={len(predicted)}"

    predicted: list[OSMRoadSegment] = []
    assist_road_ids: set[int] = set()
    visited = {current.road_id}
    road_id = current.road_id
    bearing = current.driving_bearing_deg
    total_successors = 0
    total_accepted = 0
    total_skip_ahead = 0
    skip_ahead_hits = 0
    endpoint_assist_hits = 0
    rejects: dict[str, int] = {}
    reject_samples: list[str] = []
    stop_reason = ""

    for _ in range(40):
      candidates: list[_SuccessorCandidate] = []
      successors = self._successors(conn, road_id)
      total_successors += len(successors)
      if not successors:
        assist_candidate = self._endpoint_assist_successor(conn, gps, bearing, current.display_name, road_id, visited)
        if assist_candidate is not None:
          candidates.append(assist_candidate)
          assist_road_ids.add(assist_candidate.road.road_id)
          endpoint_assist_hits += 1
          if len(reject_samples) < 3:
            reject_samples.append(f"{road_id}->{assist_candidate.road.road_id}:endpoint_assist")
      for road in successors:
        if road.road_id in visited:
          rejects["visited"] = rejects.get("visited", 0) + 1
          continue
        candidate, reject_reason = self._score_successor(gps, bearing, current.display_name, road)
        if candidate is not None:
          candidates.append(candidate)
        elif reject_reason == "behind":
          skip_candidate, skipped = self._skip_ahead_successor(conn, gps, bearing, current.display_name,
                                                               current.osm_id, road, visited)
          total_skip_ahead += skipped
          if skip_candidate is not None:
            candidates.append(skip_candidate)
            skip_ahead_hits += 1
            if len(reject_samples) < 3:
              reject_samples.append(f"{road.road_id}->{skip_candidate.road.road_id}:skip_ahead")
          else:
            rejects[reject_reason] = rejects.get(reject_reason, 0) + 1
            if len(reject_samples) < 3:
              reject_samples.append(f"{road.road_id}:{road.display_name or '-'}:{reject_reason}")
        elif reject_reason:
          rejects[reject_reason] = rejects.get(reject_reason, 0) + 1
          if len(reject_samples) < 3:
            reject_samples.append(f"{road.road_id}:{road.display_name or '-'}:{reject_reason}")
      if not candidates:
        stop_reason = "no_candidates"
        break
      candidates.sort(key=lambda item: (item.score, item.heading_diff_deg, item.forward_m))
      best_candidate = candidates[0]
      best = best_candidate.road
      total_accepted += len(candidates)
      predicted.append(best)
      visited.add(best.road_id)
      road_id = best.road_id
      bearing = best_candidate.driving_bearing_deg

    if not predicted:
      predicted = forward_road_segments(conn, gps.lat, gps.lon, gps.bearing_deg, forward_start_m=5.0, forward_end_m=self.forward_distance_m, limit=60)
      graph_gap_assist = total_successors == 0
      if graph_gap_assist:
        assist_road_ids = {segment.road_id for segment in predicted}
      debug_text = (
        f"current={current.display_name or '-'} road_id={current.road_id} "
        f"successors={total_successors} accepted={total_accepted} skip_ahead={total_skip_ahead}/{skip_ahead_hits} "
        f"endpoint_assist={endpoint_assist_hits} stop={stop_reason or '-'} "
        f"rejects={_format_rejects(rejects)} samples={';'.join(reject_samples) or '-'} "
        f"fallback_count={len(predicted)}"
      )
      return predicted[:80], False, graph_gap_assist, assist_road_ids, debug_text

    debug_text = (
      f"current={current.display_name or '-'} road_id={current.road_id} "
      f"graph_count={len(predicted)} successors={total_successors} accepted={total_accepted} "
      f"skip_ahead={total_skip_ahead}/{skip_ahead_hits} endpoint_assist={endpoint_assist_hits}"
    )
    return predicted[:80], True, endpoint_assist_hits > 0, assist_road_ids, debug_text
