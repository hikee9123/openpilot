#!/usr/bin/env python3
from __future__ import annotations

from openpilot.selfdrive.navd.osm_predictor import RoadPrediction
from openpilot.selfdrive.navd.osm_roads import OSMRoadSegment, latlon_to_car_space_m


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


def build_minimap_overlay(prediction: RoadPrediction | None, history_segments: list[OSMRoadSegment] | None = None, max_segments: int = 220) -> tuple[str, float, float, list[dict]]:
  if prediction is None:
    return "", 0.0, 0.0, []

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
    return prediction.current.display_name if prediction.current is not None else "", round(prediction.gps.bearing_deg, 1), _prediction_distance_m(prediction), []

  roads = [
    _segment_to_overlay(segment, prediction, current_id, predicted_ids, history_ids, assist_ids)
    for segment in list(merged.values())[:max_segments]
  ]
  return prediction.current.display_name if prediction.current is not None else "", round(prediction.gps.bearing_deg, 1), _prediction_distance_m(prediction), roads
