#!/usr/bin/env python3
import math
from dataclasses import dataclass
from dataclasses import replace

try:
  from openpilot.selfdrive.navd.osm_roads import (
    MAJOR_HIGHWAYS,
    angle_diff_deg,
    latlon_to_car_space_m,
    road_name_matches,
    segment_allowed_bearings,
  )
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import (
    MAJOR_HIGHWAYS,
    angle_diff_deg,
    latlon_to_car_space_m,
    road_name_matches,
    segment_allowed_bearings,
  )


OSM_CAMERA_CONTEXT_DEFAULT_DISTANCE_M = 70.0
OSM_CAMERA_CONTEXT_MAJOR_DISTANCE_M = 140.0
OSM_DIRECTION_ONEWAY_CONFIDENCE = 0.85
OSM_DIRECTION_BIDIRECTIONAL_CONFIDENCE = 0.45
OSM_DIRECTION_NAME_MATCH_BONUS = 0.1
OSM_DIRECTION_HEADING_MATCH_BONUS = 0.05
OSM_DIRECTION_MAX_CONFIDENCE = 0.95


@dataclass(frozen=True)
class OSMRoadContextSegment:
  segment: object
  x1: float
  y1: float
  x2: float
  y2: float
  heading_diff_deg: float


def build_osm_road_context(osm_road_segments, origin_lat: float, origin_lon: float, heading_deg: float) -> list[OSMRoadContextSegment]:
  context_segments = []
  for segment in osm_road_segments or []:
    x1, y1 = latlon_to_car_space_m(origin_lat, origin_lon, heading_deg, segment.lat1, segment.lon1)
    x2, y2 = latlon_to_car_space_m(origin_lat, origin_lon, heading_deg, segment.lat2, segment.lon2)
    segment_bearing = float(getattr(segment, "bearing_deg", 0.0))
    heading_diff = min(
      angle_diff_deg(segment_bearing, heading_deg),
      angle_diff_deg((segment_bearing + 180.0) % 360.0, heading_deg),
    )
    context_segments.append(OSMRoadContextSegment(segment, x1, y1, x2, y2, heading_diff))
  return context_segments


def osm_direction_priority(camera, max_heading_diff_deg: float) -> tuple[int, float]:
  if camera.osm_direction_source == "DB_DIRECTION":
    return 1, 0.0
  if camera.osm_direction_confidence <= 0.0:
    return 1, 180.0
  if camera.osm_direction_confidence < OSM_DIRECTION_BIDIRECTIONAL_CONFIDENCE:
    return 1, camera.osm_direction_heading_diff_deg
  if camera.osm_direction_heading_diff_deg <= max_heading_diff_deg:
    return 0, camera.osm_direction_heading_diff_deg
  return 2, camera.osm_direction_heading_diff_deg


def apply_db_direction_context(camera, db_bearing: float | None, heading_deg: float):
  if db_bearing is None:
    return camera
  return replace(
    camera,
    osm_predicted_bearing_deg=db_bearing,
    osm_direction_confidence=1.0,
    osm_direction_source="DB_DIRECTION",
    osm_direction_heading_diff_deg=angle_diff_deg(db_bearing, heading_deg),
  )


def _point_to_segment_distance_m(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
  dx = x2 - x1
  dy = y2 - y1
  length_sq = dx * dx + dy * dy
  if length_sq <= 0.0:
    return math.hypot(px - x1, py - y1)
  t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
  return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _osm_context_side_limit_m(segment) -> float:
  highway = str(getattr(segment, "highway", "") or "")
  if highway in MAJOR_HIGHWAYS:
    return OSM_CAMERA_CONTEXT_MAJOR_DISTANCE_M
  return OSM_CAMERA_CONTEXT_DEFAULT_DISTANCE_M


def _bearing_closest_to_heading(bearings: tuple[float, ...], heading_deg: float) -> tuple[float, float]:
  if not bearings:
    return 0.0, 180.0
  bearing = min(bearings, key=lambda candidate: angle_diff_deg(candidate, heading_deg))
  return bearing, angle_diff_deg(bearing, heading_deg)


def _osm_direction_prediction(segment, heading_deg: float, name_match: bool, max_heading_diff_deg: float) -> tuple[float, float, str, float]:
  allowed_bearings = segment_allowed_bearings(segment)
  predicted_bearing, heading_diff = _bearing_closest_to_heading(allowed_bearings, heading_deg)
  oneway = int(getattr(segment, "oneway", 0) or 0)
  confidence = OSM_DIRECTION_ONEWAY_CONFIDENCE if oneway != 0 else OSM_DIRECTION_BIDIRECTIONAL_CONFIDENCE
  if name_match:
    confidence += OSM_DIRECTION_NAME_MATCH_BONUS
  if heading_diff <= max_heading_diff_deg:
    confidence += OSM_DIRECTION_HEADING_MATCH_BONUS
  source = "OSM_ONEWAY" if oneway != 0 else "OSM_BIDIRECTIONAL_HEADING"
  return predicted_bearing, min(confidence, OSM_DIRECTION_MAX_CONFIDENCE), source, heading_diff


def apply_osm_road_context(
  camera,
  osm_road_context,
  origin_lat: float,
  origin_lon: float,
  heading_deg: float,
  current_road_name: str,
  max_heading_diff_deg: float,
):
  if not osm_road_context:
    return camera

  best_distance: float | None = None
  best_local_match = False
  best_corridor_match = False
  best_prediction: tuple[float, float, str, float] | None = None
  camera_road_names = (
    camera.osm_road_name,
    camera.osm_road_ref,
    camera.road_name,
    camera.place,
  )
  for road_context in osm_road_context:
    if isinstance(road_context, OSMRoadContextSegment):
      segment = road_context.segment
      x1, y1, x2, y2 = road_context.x1, road_context.y1, road_context.x2, road_context.y2
      heading_diff = road_context.heading_diff_deg
    else:
      segment = road_context
      x1, y1 = latlon_to_car_space_m(origin_lat, origin_lon, heading_deg, segment.lat1, segment.lon1)
      x2, y2 = latlon_to_car_space_m(origin_lat, origin_lon, heading_deg, segment.lat2, segment.lon2)
      segment_bearing = float(getattr(segment, "bearing_deg", 0.0))
      heading_diff = min(
        angle_diff_deg(segment_bearing, heading_deg),
        angle_diff_deg((segment_bearing + 180.0) % 360.0, heading_deg),
      )

    distance_m = _point_to_segment_distance_m(camera.forward_m, camera.side_m, x1, y1, x2, y2)
    if distance_m > _osm_context_side_limit_m(segment):
      continue

    current_match = road_name_matches(current_road_name, segment.name, segment.ref)
    camera_match = road_name_matches(segment.display_name, *camera_road_names) or any(
      road_name_matches(name, segment.name, segment.ref) for name in camera_road_names if name
    )
    name_match = current_match or camera_match
    if not (name_match or heading_diff <= max_heading_diff_deg):
      continue

    if best_distance is None or distance_m < best_distance:
      best_distance = distance_m
      best_local_match = name_match
      best_corridor_match = True
      best_prediction = _osm_direction_prediction(segment, heading_deg, name_match, max_heading_diff_deg)

  if best_distance is None:
    return camera

  updates = {
    "local_road_match": camera.local_road_match or best_local_match,
    "osm_corridor_match": best_corridor_match,
    "osm_corridor_distance_m": best_distance,
  }
  if best_prediction is not None and camera.osm_direction_source != "DB_DIRECTION":
    bearing, confidence, source, heading_diff = best_prediction
    updates.update({
      "osm_predicted_bearing_deg": bearing,
      "osm_direction_confidence": confidence,
      "osm_direction_source": source,
      "osm_direction_heading_diff_deg": heading_diff,
    })
  return replace(camera, **updates)
