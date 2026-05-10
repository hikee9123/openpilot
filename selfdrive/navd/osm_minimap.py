#!/usr/bin/env python3
from __future__ import annotations

import json

from openpilot.selfdrive.navd.osm_predictor import RoadPrediction
from openpilot.selfdrive.navd.osm_roads import OSMRoadSegment, latlon_to_car_space_m


def _segment_to_payload(segment: OSMRoadSegment, prediction: RoadPrediction, current_id: int | None, predicted_ids: set[int]) -> dict:
  x1, y1 = latlon_to_car_space_m(prediction.gps.lat, prediction.gps.lon, prediction.gps.bearing_deg, segment.lat1, segment.lon1)
  x2, y2 = latlon_to_car_space_m(prediction.gps.lat, prediction.gps.lon, prediction.gps.bearing_deg, segment.lat2, segment.lon2)
  return {
    "id": segment.road_id,
    "name": segment.display_name,
    "highway": segment.highway,
    "x1": round(x1, 1),
    "y1": round(y1, 1),
    "x2": round(x2, 1),
    "y2": round(y2, 1),
    "current": segment.road_id == current_id,
    "predicted": segment.road_id in predicted_ids,
  }


def build_minimap_payload(prediction: RoadPrediction | None, max_segments: int = 90) -> str:
  if prediction is None:
    return ""

  current_id = prediction.current.road_id if prediction.current is not None else None
  predicted_ids = {segment.road_id for segment in prediction.predicted}
  merged: dict[int, OSMRoadSegment] = {}
  for segment in prediction.nearby:
    merged.setdefault(segment.road_id, segment)
  for segment in prediction.predicted:
    merged[segment.road_id] = segment

  if not merged:
    return ""

  roads = [
    _segment_to_payload(segment, prediction, current_id, predicted_ids)
    for segment in list(merged.values())[:max_segments]
  ]
  payload = {
    "road": prediction.current.display_name if prediction.current is not None else "",
    "bearing": round(prediction.gps.bearing_deg, 1),
    "mapRoads": roads,
  }
  return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
