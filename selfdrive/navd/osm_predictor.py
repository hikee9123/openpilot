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
  OSMRoadTransition,
  angle_diff_deg,
  connect_readonly_db,
  database_segment_count,
  driving_bearing_for_oneway,
  find_current_road,
  forward_road_segments,
  latlon_to_car_space_m,
  nearby_road_segments,
  row_to_segment,
  road_successors,
)

MAX_GRAPH_HEADING_DIFF_DEG = 70.0
MAX_GRAPH_TURN_ANGLE_DEG = 75.0
PREFERRED_GRAPH_TURN_ANGLE_DEG = 135.0
PREFERRED_TRANSITION_SCORE_THRESHOLD = 0.65
PREFERRED_TRANSITION_COST_LIMIT = 90.0
TRANSITION_COST_SCORE_WEIGHT = 0.22
PREFERRED_TRANSITION_BONUS = 16.0
CONTINUITY_HINT_BONUS = 14.0
ROUTE_CONTINUITY_BONUS = 10.0
DESTINATION_CONTINUITY_BONUS = 8.0
RAMP_OVERSELECT_PENALTY = 10.0
RAMP_CONTINUITY_BONUS = 6.0
LAYER_MISMATCH_PENALTY = 18.0
LOW_CONFIDENCE_PENALTY = 20.0
MIN_GRAPH_SIDE_OFFSET_M = 80.0
MAX_GRAPH_SIDE_OFFSET_M = 260.0
MAX_GRAPH_SKIP_AHEAD_SEGMENTS = 5
MAX_GRAPH_ENDPOINT_ASSIST_M = 420.0
MAX_ENDPOINT_ASSIST_GAP_M = 100.0
MAX_ENDPOINT_ASSIST_RATIO_FOR_EXTENSION = 0.30
MAX_CONSECUTIVE_ENDPOINT_ASSIST = 2
MAX_STRONG_CONSECUTIVE_ENDPOINT_ASSIST = 4
STRONG_ENDPOINT_ASSIST_HEADING_DIFF_DEG = 25.0
STRONG_ENDPOINT_ASSIST_LAYER_DELTA = 1
ENDPOINT_ASSIST_BLOCKED_RAMP_TYPES = {"loop"}
BASE_GRAPH_SEGMENT_LIMIT = 40
EXTENDED_GRAPH_SEGMENT_LIMIT = 80
HIGH_SPEED_GRAPH_SEGMENT_LIMIT = 120
PREDICTION_QUALITY_WINDOW = 24
PREDICTION_QUALITY_MIN_SAMPLES = 8
PREDICTION_QUALITY_GOOD_RATIO = 0.75
PREDICTION_MATCH_WINDOW_S = 60.0
PREDICTION_MATCH_SAMPLE_WINDOW = 36
PREDICTION_MATCH_MIN_SAMPLES = 12
PREDICTION_MATCH_GOOD_RATIO = 0.85
PREDICTION_MATCH_MIN_SPEED_MPS = 5.0
CURVE_EXTENSION_MIN_TURN_DEG = 18.0
CURVE_EXTENSION_MIN_SIDE_M = 140.0
HIGH_SPEED_EXTENSION_MIN_MPS = 80.0 / 3.6
MED_SPEED_TARGET_MIN_MPS = 10.0
HIGH_SPEED_TARGET_MIN_MPS = 20.0
BASE_TARGET_PREDICTION_DISTANCE_M = 1000.0
MED_SPEED_TARGET_PREDICTION_DISTANCE_M = 1500.0
HIGH_SPEED_TARGET_PREDICTION_DISTANCE_M = 2000.0
SHORT_GRAPH_EXTENSION_SEGMENT_LIMIT = 80
SHORT_GRAPH_FORWARD_ASSIST_M = 700.0
DEBUG_SELECTED_LIMIT = 6
DEBUG_CANDIDATE_LIMIT = 3
LOW_SPEED_HEADING_IGNORE_MPS = 2.0
LOW_SPEED_LOOKUP_RADIUS_M = 95.0
LOW_SPEED_PREVIOUS_HOLD_MPS = 3.0
LOW_SPEED_PREVIOUS_HOLD_RADIUS_M = 110.0
RELAXED_LOOKUP_MIN_RADIUS_M = 85.0
RELAXED_LOOKUP_MAX_RADIUS_M = 120.0
RELAXED_LOOKUP_HEADING_DIFF_DEG = 85.0
TRUSTED_SUCCESSOR_BACKTRACK_M = -45.0
STRONG_SUCCESSOR_BACKTRACK_M = -85.0
TRUSTED_SUCCESSOR_SIDE_MULTIPLIER = 2.4
STRONG_SUCCESSOR_MIN_SIDE_LIMIT_M = 220.0
STRONG_SUCCESSOR_MAX_SIDE_LIMIT_M = 560.0
LINK_HIGHWAYS = {"motorway_link", "trunk_link", "primary_link", "secondary_link"}
MAJOR_FLOW_HIGHWAYS = {
  "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
  "secondary", "secondary_link", "tertiary", "tertiary_link",
}
LOCAL_FLOW_HIGHWAYS = {"service", "residential", "living_street", "track", "path", "footway", "cycleway", "pedestrian"}


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
  transition: OSMRoadTransition | None = None


@dataclass(frozen=True)
class _PendingPredictionMatch:
  created_at: float
  predicted_ids: set[int]


def _distance_m(a: GPSFix, b: GPSFix) -> float:
  dx, dy = latlon_to_car_space_m(a.lat, a.lon, a.bearing_deg, b.lat, b.lon)
  return math.hypot(dx, dy)


def _same_display_name(a: str, b: str) -> bool:
  return bool(a) and bool(b) and a == b


def _same_road_identity(current_name: str, current_osm_id: int, road: OSMRoadSegment) -> bool:
  return _same_display_name(current_name, road.display_name) or (current_osm_id > 0 and road.osm_id == current_osm_id)


def _trusted_link_successor(road: OSMRoadSegment) -> bool:
  return road.highway in LINK_HIGHWAYS


def _transition_allowed_for_graph(transition: OSMRoadTransition) -> bool:
  if transition.turn_angle_deg <= MAX_GRAPH_TURN_ANGLE_DEG:
    return True
  return (
    transition.turn_angle_deg <= PREFERRED_GRAPH_TURN_ANGLE_DEG
    and transition.preferred_transition_score >= PREFERRED_TRANSITION_SCORE_THRESHOLD
    and transition.transition_cost <= PREFERRED_TRANSITION_COST_LIMIT
  )


def _transition_sort_cost(candidate: _SuccessorCandidate) -> float:
  if candidate.transition is None:
    return 0.0
  return max(0.0, candidate.transition.transition_cost)


def _clamp(value: float, low: float, high: float) -> float:
  return max(low, min(high, value))


def _same_nonempty(left: str, right: str) -> bool:
  return bool(left) and bool(right) and left == right


def _same_route_metadata(current_road: OSMRoadSegment | None, road: OSMRoadSegment) -> bool:
  if current_road is None:
    return False
  return (
    _same_nonempty(current_road.ref, road.ref)
    or _same_nonempty(current_road.route_ref, road.route_ref)
    or _same_nonempty(current_road.int_ref, road.int_ref)
  )


def _same_destination_metadata(current_road: OSMRoadSegment | None, road: OSMRoadSegment) -> bool:
  if current_road is None:
    return False
  return (
    _same_nonempty(current_road.destination_ref, road.destination_ref)
    or _same_nonempty(current_road.destination, road.destination)
  )


def _endpoint_assist_candidate_allowed(from_road: OSMRoadSegment, road: OSMRoadSegment) -> bool:
  if road.ramp_type in ENDPOINT_ASSIST_BLOCKED_RAMP_TYPES:
    return False
  if road.is_ramp and not from_road.is_ramp:
    return False
  same_identity = (
    _same_display_name(from_road.display_name, road.display_name)
    or (from_road.osm_id > 0 and from_road.osm_id == road.osm_id)
  )
  if not (same_identity or _same_route_metadata(from_road, road) or _same_destination_metadata(from_road, road)):
    return False
  return True


def _strong_endpoint_assist_candidate(from_road: OSMRoadSegment, road: OSMRoadSegment, heading_diff_deg: float) -> bool:
  if not _endpoint_assist_candidate_allowed(from_road, road):
    return False
  if heading_diff_deg > STRONG_ENDPOINT_ASSIST_HEADING_DIFF_DEG:
    return False
  if abs(from_road.layer_int - road.layer_int) > STRONG_ENDPOINT_ASSIST_LAYER_DELTA:
    return False
  same_identity = (
    _same_display_name(from_road.display_name, road.display_name)
    or (from_road.osm_id > 0 and from_road.osm_id == road.osm_id)
  )
  return same_identity or _same_route_metadata(from_road, road)


def _metadata_score_adjustment(current_road: OSMRoadSegment | None, road: OSMRoadSegment,
                               transition: OSMRoadTransition | None) -> float:
  adjustment = 0.0
  if transition is not None:
    adjustment += _clamp(transition.transition_cost, 0.0, 160.0) * TRANSITION_COST_SCORE_WEIGHT
    adjustment -= _clamp(transition.preferred_transition_score, 0.0, 1.0) * PREFERRED_TRANSITION_BONUS
    adjustment -= _clamp(max(transition.transition_probability, transition.flow_probability), 0.0, 1.0) * 6.0
    adjustment += (1.0 - _clamp(transition.connectivity_confidence, 0.0, 1.0)) * LOW_CONFIDENCE_PENALTY
    if transition.preferred_successor_id == road.road_id:
      adjustment -= 6.0

  route_continuity = _same_route_metadata(current_road, road)
  destination_continuity = _same_destination_metadata(current_road, road)
  if route_continuity:
    adjustment -= ROUTE_CONTINUITY_BONUS
  if destination_continuity:
    adjustment -= DESTINATION_CONTINUITY_BONUS

  adjustment -= _clamp(road.continuity_hint, 0.0, 1.0) * CONTINUITY_HINT_BONUS
  adjustment -= _clamp(road.main_flow_bias, 0.0, 1.0) * 6.0
  adjustment -= _clamp(road.road_priority / 100.0, 0.0, 1.0) * 4.0

  current_is_ramp = bool(current_road is not None and current_road.is_ramp)
  road_is_ramp = bool(road.is_ramp)
  if road_is_ramp:
    if current_is_ramp or route_continuity or destination_continuity or road.ramp_type in ("connector", "collector", "distributor", "loop"):
      adjustment -= RAMP_CONTINUITY_BONUS * _clamp(max(road.ramp_bias, road.continuity_hint), 0.0, 1.0)
    else:
      adjustment += RAMP_OVERSELECT_PENALTY
    if road.ramp_type == "loop" and transition is not None and transition.preferred_transition_score >= PREFERRED_TRANSITION_SCORE_THRESHOLD:
      adjustment -= 5.0
  elif current_is_ramp:
    adjustment -= 4.0

  if current_road is not None and current_road.layer_int != 0 and road.layer_int != 0:
    layer_delta = abs(current_road.layer_int - road.layer_int)
    if layer_delta > 0:
      adjustment += min(36.0, layer_delta * LAYER_MISMATCH_PENALTY)

  adjustment += (1.0 - _clamp(road.map_confidence, 0.0, 1.0)) * LOW_CONFIDENCE_PENALTY
  return adjustment


def _candidate_debug(candidate: _SuccessorCandidate) -> str:
  road = candidate.road
  transition = candidate.transition
  if transition is None:
    transition_text = "cost=- pref=- conf=- turn=-"
  else:
    transition_text = (
      f"cost={transition.transition_cost:.1f} pref={transition.preferred_transition_score:.2f} "
      f"conf={transition.connectivity_confidence:.2f} turn={transition.turn_angle_deg:.1f}"
    )
  ramp = road.ramp_type or ("ramp" if road.is_ramp else "-")
  continuity = road.continuity_class or "-"
  return (
    f"{road.road_id}:score={candidate.score:.1f} {transition_text} "
    f"ramp={ramp} cont={continuity} layer={road.layer_int}"
  )


def _candidate_list_debug(candidates: list[_SuccessorCandidate], limit: int = DEBUG_CANDIDATE_LIMIT) -> str:
  if not candidates:
    return "-"
  return "|".join(_candidate_debug(candidate) for candidate in candidates[:max(0, limit)])


def _point_to_segment_distance_m(gps: GPSFix, road: OSMRoadSegment) -> float:
  x1, y1 = latlon_to_car_space_m(gps.lat, gps.lon, 0.0, road.lat1, road.lon1)
  x2, y2 = latlon_to_car_space_m(gps.lat, gps.lon, 0.0, road.lat2, road.lon2)
  dx = x2 - x1
  dy = y2 - y1
  length_sq = dx * dx + dy * dy
  if length_sq <= 0.0:
    return math.hypot(x1, y1)
  t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length_sq))
  return math.hypot(x1 + t * dx, y1 + t * dy)


def _format_rejects(rejects: dict[str, int]) -> str:
  if not rejects:
    return "none"
  return ", ".join(f"{reason}={count}" for reason, count in sorted(rejects.items()))


def _graph_prediction_limit(high_quality: bool, extension_quality_ok: bool, speed_mps: float) -> int:
  if not high_quality or not extension_quality_ok:
    return BASE_GRAPH_SEGMENT_LIMIT
  if speed_mps >= HIGH_SPEED_EXTENSION_MIN_MPS:
    return HIGH_SPEED_GRAPH_SEGMENT_LIMIT
  return EXTENDED_GRAPH_SEGMENT_LIMIT


def _prediction_distance_m(roads: list[OSMRoadSegment]) -> float:
  return sum(max(0.0, road.segment_length) for road in roads)


def _target_prediction_distance_m(speed_mps: float) -> float:
  if speed_mps >= HIGH_SPEED_TARGET_MIN_MPS:
    return HIGH_SPEED_TARGET_PREDICTION_DISTANCE_M
  if speed_mps >= MED_SPEED_TARGET_MIN_MPS:
    return MED_SPEED_TARGET_PREDICTION_DISTANCE_M
  return BASE_TARGET_PREDICTION_DISTANCE_M


def _short_extension_candidate_allowed(from_road: OSMRoadSegment, road: OSMRoadSegment, speed_mps: float) -> bool:
  if road.ramp_type in ENDPOINT_ASSIST_BLOCKED_RAMP_TYPES:
    return False
  if _endpoint_assist_candidate_allowed(from_road, road):
    return True
  if speed_mps >= MED_SPEED_TARGET_MIN_MPS and from_road.highway in MAJOR_FLOW_HIGHWAYS and road.highway in LOCAL_FLOW_HIGHWAYS:
    return False
  if from_road.highway in LINK_HIGHWAYS and road.highway in LINK_HIGHWAYS:
    return True
  if from_road.highway in MAJOR_FLOW_HIGHWAYS and road.highway in MAJOR_FLOW_HIGHWAYS and not road.is_ramp:
    return True
  return speed_mps < MED_SPEED_TARGET_MIN_MPS and from_road.highway == road.highway and not road.is_ramp


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
    self._successor_cache: dict[int, list[OSMRoadTransition]] = {}
    self._prediction_quality_samples: list[bool] = []
    self._prediction_match_samples: list[bool] = []
    self._pending_prediction_matches: list[_PendingPredictionMatch] = []

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

  def _prediction_quality(self) -> float:
    if not self._prediction_quality_samples:
      return 0.0
    return sum(1 for sample in self._prediction_quality_samples if sample) / len(self._prediction_quality_samples)

  def _good_prediction_quality(self) -> bool:
    return (
      len(self._prediction_quality_samples) >= PREDICTION_QUALITY_MIN_SAMPLES
      and self._prediction_quality() >= PREDICTION_QUALITY_GOOD_RATIO
    )

  def _prediction_match_quality(self) -> float:
    if not self._prediction_match_samples:
      return 0.0
    return sum(1 for sample in self._prediction_match_samples if sample) / len(self._prediction_match_samples)

  def _prediction_match_ready(self) -> bool:
    return len(self._prediction_match_samples) >= PREDICTION_MATCH_MIN_SAMPLES

  def _good_prediction_match_quality(self) -> bool:
    return self._prediction_match_ready() and self._prediction_match_quality() >= PREDICTION_MATCH_GOOD_RATIO

  def _record_prediction_match_sample(self, hit: bool) -> None:
    self._prediction_match_samples.append(hit)
    if len(self._prediction_match_samples) > PREDICTION_MATCH_SAMPLE_WINDOW:
      self._prediction_match_samples = self._prediction_match_samples[-PREDICTION_MATCH_SAMPLE_WINDOW:]

  def _update_prediction_match_quality(self, current: OSMRoadMatch | None, now: float) -> None:
    if not self._pending_prediction_matches:
      return

    current_road_id = current.road_id if current is not None else None
    pending: list[_PendingPredictionMatch] = []
    for sample in self._pending_prediction_matches:
      if current_road_id is not None and current_road_id in sample.predicted_ids:
        self._record_prediction_match_sample(True)
      elif now - sample.created_at >= PREDICTION_MATCH_WINDOW_S:
        self._record_prediction_match_sample(False)
      else:
        pending.append(sample)
    self._pending_prediction_matches = pending

  def _add_pending_prediction_match(self, prediction: RoadPrediction) -> None:
    if (
      prediction.current is None
      or not prediction.predicted_from_graph
      or prediction.gps.speed_mps < PREDICTION_MATCH_MIN_SPEED_MPS
    ):
      return

    predicted_ids = {road.road_id for road in prediction.predicted}
    if not predicted_ids:
      return
    self._pending_prediction_matches.append(_PendingPredictionMatch(prediction.updated_at, predicted_ids))

  def _record_prediction_quality(self, prediction: RoadPrediction) -> None:
    graph_success = prediction.current is not None and prediction.predicted_from_graph and bool(prediction.predicted)
    self._prediction_quality_samples.append(graph_success)
    if len(self._prediction_quality_samples) > PREDICTION_QUALITY_WINDOW:
      self._prediction_quality_samples = self._prediction_quality_samples[-PREDICTION_QUALITY_WINDOW:]

  def _find_current_road(
    self,
    conn: sqlite3.Connection,
    gps: GPSFix,
    previous_name: str,
    previous_road_id: int | None,
    previous_osm_id: int | None,
  ) -> OSMRoadMatch | None:
    current = find_current_road(conn, gps.lat, gps.lon, gps.bearing_deg, self.lookup_radius_m,
                                previous_name, previous_road_id, previous_osm_id)
    if current is not None:
      return current

    if previous_road_id is not None and gps.speed_mps <= LOW_SPEED_PREVIOUS_HOLD_MPS:
      current = self._previous_current_hold_match(conn, gps, previous_road_id)
      if current is not None:
        return current

    if gps.speed_mps <= LOW_SPEED_HEADING_IGNORE_MPS:
      low_speed_radius = max(LOW_SPEED_LOOKUP_RADIUS_M, self.lookup_radius_m * 1.8)
      current = find_current_road(conn, gps.lat, gps.lon, None, low_speed_radius,
                                  previous_name, previous_road_id, previous_osm_id)
      if current is not None:
        return current

    relaxed_radius = min(RELAXED_LOOKUP_MAX_RADIUS_M, max(RELAXED_LOOKUP_MIN_RADIUS_M, self.lookup_radius_m * 1.8))
    if relaxed_radius <= self.lookup_radius_m:
      return None
    return find_current_road(conn, gps.lat, gps.lon, gps.bearing_deg, relaxed_radius,
                             previous_name, previous_road_id, previous_osm_id,
                             max_heading_diff_deg=RELAXED_LOOKUP_HEADING_DIFF_DEG)

  def _previous_current_hold_match(self, conn: sqlite3.Connection, gps: GPSFix, road_id: int) -> OSMRoadMatch | None:
    road = self._road_segment(conn, road_id)
    if road is None:
      return None
    distance_m = _point_to_segment_distance_m(gps, road)
    if distance_m > LOW_SPEED_PREVIOUS_HOLD_RADIUS_M:
      return None

    driving_bearing = driving_bearing_for_oneway(road.bearing_deg, road.oneway, gps.bearing_deg)
    heading_diff = angle_diff_deg(driving_bearing, gps.bearing_deg)
    return OSMRoadMatch(
      road_id=road.road_id,
      osm_id=road.osm_id,
      name=road.name,
      ref=road.ref,
      highway=road.highway,
      road_class=road.road_class,
      oneway=road.oneway,
      distance_m=distance_m,
      heading_diff_deg=heading_diff,
      bearing_deg=road.bearing_deg,
      driving_bearing_deg=driving_bearing,
      score=distance_m - 20.0,
    )

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
    current = self._find_current_road(conn, gps, previous_name, previous_road_id, previous_osm_id)
    self._update_prediction_match_quality(current, now)
    nearby = nearby_road_segments(conn, gps.lat, gps.lon, self.map_radius_m, limit=80)
    predicted, predicted_from_graph, predicted_from_assist, assist_road_ids, debug_text = self._predict_forward(conn, gps, current)

    result = RoadPrediction(gps=gps, current=current, nearby=nearby, predicted=predicted,
                            predicted_from_graph=predicted_from_graph, predicted_from_assist=predicted_from_assist,
                            assist_road_ids=assist_road_ids, debug_text=debug_text, updated_at=now)
    self._record_prediction_quality(result)
    self._add_pending_prediction_match(result)
    self._last_gps = gps
    self._last_prediction = result
    self._last_update_t = now
    return result

  def _successors(self, conn: sqlite3.Connection, road_id: int) -> list[OSMRoadTransition]:
    cached = self._successor_cache.get(road_id)
    if cached is not None:
      return cached
    successors = [transition for transition in road_successors(conn, road_id, limit=12) if _transition_allowed_for_graph(transition)]
    self._successor_cache[road_id] = successors
    return successors

  def _road_segment(self, conn: sqlite3.Connection, road_id: int) -> OSMRoadSegment | None:
    try:
      row = conn.execute("""
        SELECT roads.*, 0.0 AS distance_m
        FROM roads
        WHERE id = ?
      """, (road_id,)).fetchone()
    except sqlite3.Error:
      return None
    if row is None:
      return None
    return row_to_segment(row)

  def _score_successor(self, gps: GPSFix, reference_bearing_deg: float, current_name: str,
                       current_osm_id: int, road: OSMRoadSegment,
                       trusted_successor: bool = False,
                       transition: OSMRoadTransition | None = None,
                       current_road: OSMRoadSegment | None = None) -> tuple[_SuccessorCandidate | None, str]:
    x1, y1 = latlon_to_car_space_m(gps.lat, gps.lon, gps.bearing_deg, road.lat1, road.lon1)
    x2, y2 = latlon_to_car_space_m(gps.lat, gps.lon, gps.bearing_deg, road.lat2, road.lon2)
    same_identity = _same_road_identity(current_name, current_osm_id, road)
    trust_geometry = trusted_successor and (same_identity or _trusted_link_successor(road))
    behind_limit_m = STRONG_SUCCESSOR_BACKTRACK_M if trusted_successor and same_identity else TRUSTED_SUCCESSOR_BACKTRACK_M if trust_geometry else 5.0
    if max(x1, x2) < behind_limit_m:
      return None, "behind"

    forward_points = [x for x in (x1, x2) if x >= 0.0]
    forward_m = min(forward_points) if forward_points else max(x1, x2)
    score_forward_m = max(0.0, forward_m)
    side_offset_m = min(abs(y1), abs(y2))
    side_limit_m = min(MAX_GRAPH_SIDE_OFFSET_M, max(MIN_GRAPH_SIDE_OFFSET_M, score_forward_m * 0.45))
    if trust_geometry:
      side_limit_m *= TRUSTED_SUCCESSOR_SIDE_MULTIPLIER
      if same_identity:
        side_limit_m = max(side_limit_m, STRONG_SUCCESSOR_MIN_SIDE_LIMIT_M)
        side_limit_m = min(side_limit_m, STRONG_SUCCESSOR_MAX_SIDE_LIMIT_M)
    if side_offset_m > side_limit_m:
      return None, "side_offset"

    road_bearing = driving_bearing_for_oneway(road.bearing_deg, road.oneway, reference_bearing_deg)
    heading_diff = angle_diff_deg(reference_bearing_deg, road_bearing)
    if heading_diff > MAX_GRAPH_HEADING_DIFF_DEG:
      return None, "heading_diff"

    same_name_bonus = -12.0 if _same_display_name(current_name, road.display_name) else 0.0
    same_osm_bonus = -8.0 if current_osm_id > 0 and road.osm_id == current_osm_id else 0.0
    trusted_bonus = -6.0 if trust_geometry else 0.0
    score = heading_diff * 3.0 + side_offset_m * 0.35 + score_forward_m * 0.02 + same_name_bonus + same_osm_bonus + trusted_bonus
    score += _metadata_score_adjustment(current_road, road, transition)
    return _SuccessorCandidate(score, heading_diff, forward_m, road, road_bearing, transition), ""

  def _skip_ahead_successor(self, conn: sqlite3.Connection, gps: GPSFix, reference_bearing_deg: float,
                            current_name: str, current_osm_id: int, start_road: OSMRoadSegment,
                            visited: set[int],
                            current_road: OSMRoadSegment | None = None) -> tuple[_SuccessorCandidate | None, int]:
    if not _same_road_identity(current_name, current_osm_id, start_road):
      return None, 0

    frontier = [start_road]
    seen = set(visited)
    seen.add(start_road.road_id)
    skipped = 0
    while frontier and skipped < MAX_GRAPH_SKIP_AHEAD_SEGMENTS:
      road = frontier.pop(0)
      skipped += 1
      for next_transition in self._successors(conn, road.road_id):
        next_road = next_transition.road
        if next_road.road_id in seen:
          continue
        seen.add(next_road.road_id)
        if not _same_road_identity(current_name, current_osm_id, next_road):
          continue
        candidate, reject_reason = self._score_successor(gps, reference_bearing_deg, current_name,
                                                          current_osm_id, next_road,
                                                          trusted_successor=True,
                                                          transition=next_transition,
                                                          current_road=current_road)
        if candidate is not None:
          return candidate, skipped
        if reject_reason == "behind":
          frontier.append(next_road)
    return None, skipped

  def _score_endpoint_candidate(self, end_lat: float, end_lon: float, reference_bearing_deg: float,
                                current_name: str, current_osm_id: int,
                                road: OSMRoadSegment,
                                current_road: OSMRoadSegment | None = None) -> _SuccessorCandidate | None:
    if road.ramp_type in ENDPOINT_ASSIST_BLOCKED_RAMP_TYPES:
      return None

    x1, y1 = latlon_to_car_space_m(end_lat, end_lon, reference_bearing_deg, road.lat1, road.lon1)
    x2, y2 = latlon_to_car_space_m(end_lat, end_lon, reference_bearing_deg, road.lat2, road.lon2)
    endpoint_gap_m = min(math.hypot(x1, y1), math.hypot(x2, y2))
    if endpoint_gap_m > MAX_ENDPOINT_ASSIST_GAP_M:
      return None

    road_bearing = driving_bearing_for_oneway(road.bearing_deg, road.oneway, reference_bearing_deg)
    heading_diff = angle_diff_deg(reference_bearing_deg, road_bearing)
    if heading_diff > MAX_GRAPH_HEADING_DIFF_DEG:
      return None

    side_offset_m = min(abs(y1), abs(y2))
    same_identity = _same_road_identity(current_name, current_osm_id, road)
    same_name_bonus = -12.0 if _same_display_name(current_name, road.display_name) else 0.0
    same_osm_bonus = -8.0 if current_osm_id > 0 and road.osm_id == current_osm_id else 0.0
    trusted_bonus = -6.0 if same_identity or _trusted_link_successor(road) else 0.0
    forward_m = max(0.0, min(max(x1, x2), MAX_GRAPH_ENDPOINT_ASSIST_M))
    score = heading_diff * 3.0 + endpoint_gap_m * 0.7 + side_offset_m * 0.2 + forward_m * 0.02
    score += same_name_bonus + same_osm_bonus + trusted_bonus
    score += _metadata_score_adjustment(current_road, road, None)
    return _SuccessorCandidate(score, heading_diff, forward_m, road, road_bearing)

  def _endpoint_assist_successor(self, conn: sqlite3.Connection, gps: GPSFix, reference_bearing_deg: float,
                                 current_name: str, current_osm_id: int, road_id: int,
                                 visited: set[int],
                                 current_road: OSMRoadSegment | None = None) -> _SuccessorCandidate | None:
    road = self._road_segment(conn, road_id)
    if road is None:
      return None

    forward_to_lat2 = angle_diff_deg(road.bearing_deg, reference_bearing_deg) <= 90.0
    end_lat = road.lat2 if forward_to_lat2 else road.lat1
    end_lon = road.lon2 if forward_to_lat2 else road.lon1
    endpoint_side_limit_m = 130.0 if road.highway in LINK_HIGHWAYS else 110.0
    endpoint_major_side_limit_m = 220.0 if road.highway in LINK_HIGHWAYS else 180.0
    candidates = forward_road_segments(conn, end_lat, end_lon, reference_bearing_deg,
                                       forward_start_m=-20.0, forward_end_m=MAX_GRAPH_ENDPOINT_ASSIST_M,
                                       side_limit_m=endpoint_side_limit_m,
                                       major_side_limit_m=endpoint_major_side_limit_m, limit=120)
    scored: list[tuple[float, _SuccessorCandidate]] = []
    for candidate_road in candidates:
      if candidate_road.road_id in visited or candidate_road.road_id == road_id:
        continue
      if not _endpoint_assist_candidate_allowed(road, candidate_road):
        continue
      candidate, reject_reason = self._score_successor(gps, reference_bearing_deg, current_name,
                                                        current_osm_id, candidate_road,
                                                        current_road=current_road)
      if candidate is None and reject_reason in ("behind", "side_offset"):
        candidate = self._score_endpoint_candidate(end_lat, end_lon, reference_bearing_deg,
                                                   current_name, current_osm_id, candidate_road,
                                                   current_road=current_road)
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

  def _forward_assist_successor(self, conn: sqlite3.Connection, gps: GPSFix, reference_bearing_deg: float,
                                current_name: str, current_osm_id: int, from_road: OSMRoadSegment,
                                visited: set[int], current_road: OSMRoadSegment | None,
                                remaining_distance_m: float) -> _SuccessorCandidate | None:
    forward_to_lat2 = angle_diff_deg(from_road.bearing_deg, reference_bearing_deg) <= 90.0
    end_lat = from_road.lat2 if forward_to_lat2 else from_road.lat1
    end_lon = from_road.lon2 if forward_to_lat2 else from_road.lon1
    forward_end_m = min(SHORT_GRAPH_FORWARD_ASSIST_M, max(220.0, remaining_distance_m + 120.0))
    candidates = forward_road_segments(conn, end_lat, end_lon, reference_bearing_deg,
                                       forward_start_m=-15.0, forward_end_m=forward_end_m,
                                       side_limit_m=90.0, major_side_limit_m=180.0, limit=120)
    scored: list[tuple[float, _SuccessorCandidate]] = []
    for candidate_road in candidates:
      if candidate_road.road_id in visited or candidate_road.road_id == from_road.road_id:
        continue
      if not _short_extension_candidate_allowed(from_road, candidate_road, gps.speed_mps):
        continue
      candidate = self._score_endpoint_candidate(end_lat, end_lon, reference_bearing_deg,
                                                 current_name, current_osm_id, candidate_road,
                                                 current_road=current_road)
      if candidate is None:
        continue
      scored.append((candidate.score + max(0.0, candidate.forward_m) * 0.02, candidate))
    if not scored:
      return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]

  def _extend_short_prediction(self, conn: sqlite3.Connection, gps: GPSFix, current: OSMRoadMatch,
                               predicted: list[OSMRoadSegment], visited: set[int],
                               reference_bearing_deg: float, current_road: OSMRoadSegment | None,
                               target_distance_m: float, predicted_distance_m: float) -> tuple[list[OSMRoadSegment], int, int]:
    if not predicted:
      return [], 0, 0

    added: list[OSMRoadSegment] = []
    extension_visited = set(visited)
    from_road = predicted[-1]
    bearing = reference_bearing_deg
    context_road = current_road or from_road
    endpoint_hits = 0
    forward_hits = 0

    while (
      predicted_distance_m < target_distance_m
      and len(predicted) + len(added) < SHORT_GRAPH_EXTENSION_SEGMENT_LIMIT
    ):
      remaining_distance_m = target_distance_m - predicted_distance_m
      candidate = self._endpoint_assist_successor(conn, gps, bearing, current.display_name,
                                                  current.osm_id, from_road.road_id, extension_visited,
                                                  current_road=context_road)
      if candidate is not None and _short_extension_candidate_allowed(from_road, candidate.road, gps.speed_mps):
        endpoint_hits += 1
      else:
        candidate = self._forward_assist_successor(conn, gps, bearing, current.display_name,
                                                   current.osm_id, from_road, extension_visited,
                                                   context_road, remaining_distance_m)
        if candidate is not None:
          forward_hits += 1

      if candidate is None:
        break

      road = candidate.road
      added.append(road)
      extension_visited.add(road.road_id)
      predicted_distance_m += max(0.0, road.segment_length)
      from_road = road
      bearing = candidate.driving_bearing_deg
      context_road = road

    return added, endpoint_hits, forward_hits

  def _predict_forward(self, conn: sqlite3.Connection, gps: GPSFix, current: OSMRoadMatch | None) -> tuple[list[OSMRoadSegment], bool, bool, set[int], str]:
    if current is None:
      predicted = forward_road_segments(conn, gps.lat, gps.lon, gps.bearing_deg, forward_start_m=5.0, forward_end_m=self.forward_distance_m, limit=60)
      predicted_distance_m = _prediction_distance_m(predicted)
      target_distance_m = _target_prediction_distance_m(gps.speed_mps)
      return predicted, False, False, set(), (
        f"current=none quality={self._prediction_quality():.2f} "
        f"match={self._prediction_match_quality():.2f}/{len(self._prediction_match_samples)} "
        f"fallback_count={len(predicted)} predicted_len={predicted_distance_m:.1f} target_len={target_distance_m:.0f}"
      )

    predicted: list[OSMRoadSegment] = []
    assist_road_ids: set[int] = set()
    visited = {current.road_id}
    road_id = current.road_id
    bearing = current.driving_bearing_deg
    current_road = self._road_segment(conn, current.road_id)
    score_context_road = current_road
    total_successors = 0
    total_accepted = 0
    total_skip_ahead = 0
    skip_ahead_hits = 0
    endpoint_assist_hits = 0
    consecutive_endpoint_assist = 0
    consecutive_strong_endpoint_assist = 0
    rejects: dict[str, int] = {}
    reject_samples: list[str] = []
    selected_samples: list[str] = []
    candidate_samples: list[str] = []
    stop_reason = ""
    quality = self._prediction_quality()
    match_quality = self._prediction_match_quality()
    match_ready = self._prediction_match_ready()
    match_good = self._good_prediction_match_quality()
    high_quality = self._good_prediction_quality()
    extension_quality_ok = high_quality and (not match_ready or match_good)
    graph_segment_limit = _graph_prediction_limit(high_quality, extension_quality_ok, gps.speed_mps)
    high_speed_extension_allowed = extension_quality_ok and gps.speed_mps >= HIGH_SPEED_EXTENSION_MIN_MPS
    curve_turn_total_deg = 0.0
    max_route_side_m = 0.0
    short_extension_count = 0
    short_extension_endpoint_hits = 0
    short_extension_forward_hits = 0

    for _ in range(graph_segment_limit):
      candidates: list[_SuccessorCandidate] = []
      successors = self._successors(conn, road_id)
      endpoint_assist_attempted = False
      total_successors += len(successors)
      if not successors:
        endpoint_assist_attempted = True
        assist_candidate = self._endpoint_assist_successor(conn, gps, bearing, current.display_name,
                                                           current.osm_id, road_id, visited,
                                                           current_road=score_context_road)
        if assist_candidate is not None:
          candidates.append(assist_candidate)
          assist_road_ids.add(assist_candidate.road.road_id)
          endpoint_assist_hits += 1
          if len(reject_samples) < 3:
            reject_samples.append(f"{road_id}->{assist_candidate.road.road_id}:endpoint_assist")
      for transition in successors:
        road = transition.road
        if road.road_id in visited:
          rejects["visited"] = rejects.get("visited", 0) + 1
          continue
        candidate, reject_reason = self._score_successor(gps, bearing, current.display_name,
                                                          current.osm_id, road,
                                                          trusted_successor=True,
                                                          transition=transition,
                                                          current_road=score_context_road)
        if candidate is not None:
          candidates.append(candidate)
        elif reject_reason == "behind":
          skip_candidate, skipped = self._skip_ahead_successor(conn, gps, bearing, current.display_name,
                                                               current.osm_id, road, visited,
                                                               current_road=score_context_road)
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
      candidates.sort(key=lambda item: (item.score, _transition_sort_cost(item), item.heading_diff_deg, item.forward_m))
      if len(candidate_samples) < DEBUG_CANDIDATE_LIMIT:
        candidate_samples.append(_candidate_list_debug(candidates))
      best_candidate = candidates[0]
      best = best_candidate.road
      previous_context_road = score_context_road
      total_accepted += len(candidates)
      predicted.append(best)
      if best.road_id in assist_road_ids:
        consecutive_endpoint_assist += 1
        if previous_context_road is not None and _strong_endpoint_assist_candidate(previous_context_road, best, best_candidate.heading_diff_deg):
          consecutive_strong_endpoint_assist += 1
        else:
          consecutive_strong_endpoint_assist = 0
      else:
        consecutive_endpoint_assist = 0
        consecutive_strong_endpoint_assist = 0
      if len(selected_samples) < DEBUG_SELECTED_LIMIT:
        selected_samples.append(_candidate_debug(best_candidate))
      visited.add(best.road_id)
      previous_bearing = bearing
      road_id = best.road_id
      bearing = best_candidate.driving_bearing_deg
      score_context_road = best
      curve_turn_total_deg += angle_diff_deg(previous_bearing, bearing)
      _, best_y1 = latlon_to_car_space_m(gps.lat, gps.lon, gps.bearing_deg, best.lat1, best.lon1)
      _, best_y2 = latlon_to_car_space_m(gps.lat, gps.lon, gps.bearing_deg, best.lat2, best.lon2)
      max_route_side_m = max(max_route_side_m, abs(best_y1), abs(best_y2))
      assist_ratio = endpoint_assist_hits / max(1, len(predicted))
      assist_extension_ok = assist_ratio <= MAX_ENDPOINT_ASSIST_RATIO_FOR_EXTENSION
      curve_extension_allowed = (
        extension_quality_ok
        and assist_extension_ok
        and (
          curve_turn_total_deg >= CURVE_EXTENSION_MIN_TURN_DEG
          or max_route_side_m >= CURVE_EXTENSION_MIN_SIDE_M
        )
      )
      high_speed_extension_active = high_speed_extension_allowed and assist_extension_ok
      assist_chain_limit = (
        MAX_STRONG_CONSECUTIVE_ENDPOINT_ASSIST
        if consecutive_endpoint_assist == consecutive_strong_endpoint_assist
        else MAX_CONSECUTIVE_ENDPOINT_ASSIST
      )
      if consecutive_endpoint_assist >= assist_chain_limit:
        stop_reason = "assist_chain"
        break
      if len(predicted) >= BASE_GRAPH_SEGMENT_LIMIT and not (curve_extension_allowed or high_speed_extension_active):
        stop_reason = "assist_uncertain" if not assist_extension_ok else "base_range"
        break

    if not predicted:
      predicted = forward_road_segments(conn, gps.lat, gps.lon, gps.bearing_deg, forward_start_m=5.0, forward_end_m=self.forward_distance_m, limit=60)
      predicted_distance_m = _prediction_distance_m(predicted)
      target_distance_m = _target_prediction_distance_m(gps.speed_mps)
      graph_gap_assist = total_successors == 0
      if graph_gap_assist:
        assist_road_ids = {segment.road_id for segment in predicted}
      debug_text = (
        f"current={current.display_name or '-'} road_id={current.road_id} "
        f"successors={total_successors} accepted={total_accepted} skip_ahead={total_skip_ahead}/{skip_ahead_hits} "
        f"endpoint_assist={endpoint_assist_hits} assist_ratio={endpoint_assist_hits / max(1, len(predicted)):.2f} stop={stop_reason or '-'} "
        f"rejects={_format_rejects(rejects)} samples={';'.join(reject_samples) or '-'} "
        f"candidates={';'.join(candidate_samples) or '-'} selected={';'.join(selected_samples) or '-'} "
        f"current_meta={current_road.continuity_class if current_road is not None else '-'} "
        f"quality={quality:.2f} match={match_quality:.2f}/{len(self._prediction_match_samples)} "
        f"fallback_count={len(predicted)} predicted_len={predicted_distance_m:.1f} target_len={target_distance_m:.0f}"
      )
      return predicted[:80], False, graph_gap_assist, assist_road_ids, debug_text

    target_distance_m = _target_prediction_distance_m(gps.speed_mps)
    predicted_distance_m = _prediction_distance_m(predicted)
    if predicted_distance_m < target_distance_m and stop_reason == "no_candidates":
      extension, short_extension_endpoint_hits, short_extension_forward_hits = self._extend_short_prediction(
        conn, gps, current, predicted, visited, bearing, score_context_road,
        target_distance_m, predicted_distance_m,
      )
      if extension:
        predicted.extend(extension)
        short_extension_count = len(extension)
        assist_road_ids.update(road.road_id for road in extension)
        endpoint_assist_hits += short_extension_endpoint_hits
        predicted_distance_m = _prediction_distance_m(predicted)

    if len(predicted) <= BASE_GRAPH_SEGMENT_LIMIT:
      range_mode = "base"
    elif high_speed_extension_allowed:
      range_mode = "speed_extended"
    else:
      range_mode = "curve_extended"
    debug_text = (
      f"current={current.display_name or '-'} road_id={current.road_id} "
      f"graph_count={len(predicted)} successors={total_successors} accepted={total_accepted} "
      f"skip_ahead={total_skip_ahead}/{skip_ahead_hits} endpoint_assist={endpoint_assist_hits} assist_ratio={endpoint_assist_hits / max(1, len(predicted)):.2f} "
      f"quality={quality:.2f} match={match_quality:.2f}/{len(self._prediction_match_samples)} range={range_mode} stop={stop_reason or '-'} "
      f"predicted_len={predicted_distance_m:.1f} target_len={target_distance_m:.0f} short={int(predicted_distance_m < target_distance_m)} "
      f"short_extend={short_extension_count}/{short_extension_endpoint_hits}/{short_extension_forward_hits} "
      f"selected={';'.join(selected_samples) or '-'} candidates={';'.join(candidate_samples) or '-'} "
      f"current_meta={current_road.continuity_class if current_road is not None else '-'} "
      f"curve_turn={curve_turn_total_deg:.1f} side={max_route_side_m:.1f} speed={gps.speed_mps * 3.6:.1f}"
    )
    return predicted[:max(graph_segment_limit, SHORT_GRAPH_EXTENSION_SEGMENT_LIMIT if short_extension_count else graph_segment_limit)], True, endpoint_assist_hits > 0 or short_extension_count > 0, assist_road_ids, debug_text
