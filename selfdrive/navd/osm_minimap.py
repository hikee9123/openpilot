#!/usr/bin/env python3
from __future__ import annotations

from openpilot.selfdrive.navd.osm_predictor import RoadPrediction
from openpilot.selfdrive.navd.osm_roads import (
  OSMRoadSegment,
  OSMSpeedCamera,
  angle_diff_deg,
  driving_bearing_for_oneway,
  latlon_to_car_space_m,
  speed_cameras_for_road_ids,
)


MAX_CAMERA_OVERLAY_ITEMS = 32
CAMERA_LOOKUP_LIMIT = 96
CAMERA_FORWARD_BACK_TOLERANCE_M = 10.0
CAMERA_FORWARD_EXTRA_M = 120.0
CAMERA_MIN_FORWARD_WINDOW_M = 350.0
CAMERA_MAX_FORWARD_WINDOW_M = 2200.0
CAMERA_MAX_SIDE_M = 120.0
CAMERA_MAX_BEARING_DIFF_DEG = 105.0


def _segment_to_overlay(segment: OSMRoadSegment, prediction: RoadPrediction, current_id: int | None,
                        predicted_ids: set[int], history_ids: set[int], assist_ids: set[int]) -> dict:
  x1, y1 = latlon_to_car_space_m(prediction.gps.lat, prediction.gps.lon, prediction.gps.bearing_deg, segment.lat1, segment.lon1)
  x2, y2 = latlon_to_car_space_m(prediction.gps.lat, prediction.gps.lon, prediction.gps.bearing_deg, segment.lat2, segment.lon2)
  return {
    "roadId": segment.road_id,
    "name": segment.display_name,
    "highway": segment.highway,
    "x1": round(x1, 1),
    "y1": round(y1, 1),
    "x2": round(x2, 1),
    "y2": round(y2, 1),
    "current": segment.road_id == current_id,
    "predicted": segment.road_id in predicted_ids,
    "history": segment.road_id in history_ids,
    "fallback": segment.road_id in predicted_ids and not prediction.predicted_from_graph and segment.road_id not in assist_ids,
    "assist": segment.road_id in assist_ids,
  }


def _prediction_distance_m(prediction: RoadPrediction) -> float:
  return sum(max(0.0, segment.segment_length or segment.distance_m or 0.0) for segment in prediction.predicted)


def _route_road_ids(prediction: RoadPrediction) -> list[int]:
  road_ids: list[int] = []
  if prediction.current is not None:
    road_ids.append(prediction.current.road_id)
  road_ids.extend(segment.road_id for segment in prediction.predicted)
  return list(dict.fromkeys(road_id for road_id in road_ids if road_id > 0))


def _route_bearings(prediction: RoadPrediction) -> dict[int, float]:
  bearings: dict[int, float] = {}
  reference_bearing = prediction.gps.bearing_deg
  if prediction.current is not None:
    reference_bearing = prediction.current.driving_bearing_deg
    bearings[prediction.current.road_id] = reference_bearing

  for segment in prediction.predicted:
    driving_bearing = driving_bearing_for_oneway(segment.bearing_deg, segment.oneway, reference_bearing)
    bearings[segment.road_id] = driving_bearing
    reference_bearing = driving_bearing
  return bearings


def _camera_direction_matches(camera: OSMSpeedCamera, route_bearings: dict[int, float], fallback_bearing: float) -> bool:
  if camera.bearing_deg < 0.0:
    return True
  route_bearing = route_bearings.get(camera.road_id, fallback_bearing)
  return angle_diff_deg(camera.bearing_deg, route_bearing) <= CAMERA_MAX_BEARING_DIFF_DEG


def _camera_to_overlay(
  camera: OSMSpeedCamera,
  prediction: RoadPrediction,
  route_bearings: dict[int, float],
  max_forward_m: float,
) -> dict | None:
  if camera.display_class == "rejected":
    return None
  forward_m, right_m = latlon_to_car_space_m(prediction.gps.lat, prediction.gps.lon, prediction.gps.bearing_deg, camera.lat, camera.lon)
  if forward_m < -CAMERA_FORWARD_BACK_TOLERANCE_M or forward_m > max_forward_m:
    return None
  if abs(right_m) > CAMERA_MAX_SIDE_M:
    return None
  if not _camera_direction_matches(camera, route_bearings, prediction.gps.bearing_deg):
    return None
  return {
    "cameraId": camera.camera_id,
    "roadId": camera.road_id,
    "cameraType": camera.camera_type,
    "speedLimitKph": max(0, camera.speed_limit_kph),
    "x": round(forward_m, 1),
    "y": round(right_m, 1),
    "matchDistanceM": round(camera.match_distance_m, 1),
    "matchConfidence": round(camera.match_confidence, 3),
    "primaryMatch": bool(camera.primary_match),
    "bearingDeg": round(camera.bearing_deg, 1),
    "displayClass": camera.display_class or "suspicious",
    "directionVerdict": camera.direction_verdict or "unknown",
    "rejectReason": camera.reject_reason,
  }


def _speed_camera_overlay(prediction: RoadPrediction, prediction_distance_m: float) -> list[dict]:
  road_ids = _route_road_ids(prediction)
  if not road_ids:
    return []
  max_forward_m = min(
    CAMERA_MAX_FORWARD_WINDOW_M,
    max(CAMERA_MIN_FORWARD_WINDOW_M, prediction_distance_m + CAMERA_FORWARD_EXTRA_M),
  )
  route_bearings = _route_bearings(prediction)
  cameras = speed_cameras_for_road_ids(road_ids=road_ids[:CAMERA_LOOKUP_LIMIT], limit=MAX_CAMERA_OVERLAY_ITEMS * 3)
  overlays: list[dict] = []
  seen_camera_ids: set[int] = set()
  for camera in cameras:
    if camera.camera_id in seen_camera_ids:
      continue
    overlay = _camera_to_overlay(camera, prediction, route_bearings, max_forward_m)
    if overlay is None:
      continue
    seen_camera_ids.add(camera.camera_id)
    overlays.append(overlay)
  overlays.sort(key=lambda item: (item["x"], -int(item["primaryMatch"]), -float(item["matchConfidence"]), item["cameraId"]))
  return overlays[:MAX_CAMERA_OVERLAY_ITEMS]


def build_minimap_overlay(prediction: RoadPrediction | None, history_segments: list[OSMRoadSegment] | None = None, max_segments: int = 220) -> tuple[str, float, float, list[dict], list[dict]]:
  if prediction is None:
    return "", 0.0, 0.0, [], []

  current_id = prediction.current.road_id if prediction.current is not None else None
  predicted_ids = {segment.road_id for segment in prediction.predicted}
  assist_ids = prediction.assist_road_ids
  history_segments = history_segments or []
  history_ids = {segment.road_id for segment in history_segments}
  merged: dict[int, OSMRoadSegment] = {}
  for segment in prediction.nearby:
    if segment.road_id == current_id:
      merged.setdefault(segment.road_id, segment)
      break
  for segment in history_segments:
    merged.setdefault(segment.road_id, segment)
  for segment in prediction.predicted:
    merged.setdefault(segment.road_id, segment)
  for segment in prediction.nearby:
    merged.setdefault(segment.road_id, segment)

  if not merged:
    prediction_distance_m = _prediction_distance_m(prediction)
    return (
      prediction.current.display_name if prediction.current is not None else "",
      round(prediction.gps.bearing_deg, 1),
      prediction_distance_m,
      [],
      _speed_camera_overlay(prediction, prediction_distance_m),
    )

  roads = [
    _segment_to_overlay(segment, prediction, current_id, predicted_ids, history_ids, assist_ids)
    for segment in list(merged.values())[:max_segments]
  ]
  prediction_distance_m = _prediction_distance_m(prediction)
  return (
    prediction.current.display_name if prediction.current is not None else "",
    round(prediction.gps.bearing_deg, 1),
    prediction_distance_m,
    roads,
    _speed_camera_overlay(prediction, prediction_distance_m),
  )
