from dataclasses import dataclass

import pytest

try:
  from openpilot.selfdrive.navd.camera_road_context import (
    OSM_DIRECTION_ONEWAY_CONFIDENCE,
    apply_db_direction_context,
    apply_osm_road_context,
    osm_direction_priority,
  )
  from openpilot.selfdrive.navd.osm_roads import OSMRoadSegment
except ModuleNotFoundError:
  from selfdrive.navd.camera_road_context import (
    OSM_DIRECTION_ONEWAY_CONFIDENCE,
    apply_db_direction_context,
    apply_osm_road_context,
    osm_direction_priority,
  )
  from selfdrive.navd.osm_roads import OSMRoadSegment


@dataclass(frozen=True)
class CameraContextSample:
  osm_road_name: str = ""
  osm_road_ref: str = ""
  road_name: str = ""
  place: str = ""
  forward_m: float = 0.0
  side_m: float = 0.0
  local_road_match: bool = False
  osm_corridor_match: bool = False
  osm_corridor_distance_m: float = 0.0
  osm_predicted_bearing_deg: float = 0.0
  osm_direction_confidence: float = 0.0
  osm_direction_source: str = ""
  osm_direction_heading_diff_deg: float = 0.0


def _segment(*, oneway: int = 1) -> OSMRoadSegment:
  return OSMRoadSegment(
    road_id=1,
    osm_id=1,
    name="Context Road",
    ref="",
    highway="residential",
    road_class="CITY_ROAD",
    oneway=oneway,
    lat1=37.0000,
    lon1=127.0000,
    lat2=37.0100,
    lon2=127.0000,
    bearing_deg=0.0,
    distance_m=0.0,
  )


def test_apply_db_direction_context_sets_high_confidence_source() -> None:
  camera = apply_db_direction_context(CameraContextSample(), 90.0, 100.0)

  assert camera.osm_direction_source == "DB_DIRECTION"
  assert camera.osm_predicted_bearing_deg == pytest.approx(90.0)
  assert camera.osm_direction_confidence == pytest.approx(1.0)
  assert camera.osm_direction_heading_diff_deg == pytest.approx(10.0)


def test_apply_osm_road_context_matches_segment_and_predicts_oneway() -> None:
  camera = CameraContextSample(road_name="Context Road", forward_m=220.0, side_m=0.0)

  camera = apply_osm_road_context(
    camera,
    [_segment(oneway=1)],
    37.0,
    127.0,
    0.0,
    "Context Road",
    50.0,
  )

  assert camera.local_road_match
  assert camera.osm_corridor_match
  assert camera.osm_direction_source == "OSM_ONEWAY"
  assert camera.osm_predicted_bearing_deg == pytest.approx(0.0)
  assert camera.osm_direction_confidence >= OSM_DIRECTION_ONEWAY_CONFIDENCE


def test_osm_direction_priority_prefers_aligned_high_confidence_context() -> None:
  aligned = CameraContextSample(
    osm_direction_source="OSM_ONEWAY",
    osm_direction_confidence=0.9,
    osm_direction_heading_diff_deg=5.0,
  )
  opposite = CameraContextSample(
    osm_direction_source="OSM_ONEWAY",
    osm_direction_confidence=0.9,
    osm_direction_heading_diff_deg=120.0,
  )
  db_direction = CameraContextSample(
    osm_direction_source="DB_DIRECTION",
    osm_direction_confidence=1.0,
    osm_direction_heading_diff_deg=120.0,
  )

  assert osm_direction_priority(aligned, 50.0) == (0, 5.0)
  assert osm_direction_priority(db_direction, 50.0) == (1, 0.0)
  assert osm_direction_priority(opposite, 50.0) == (2, 120.0)
