import sqlite3
from pathlib import Path

try:
  from openpilot.selfdrive.navd.osm_roads import find_current_road, insert_road_segments, road_name_matches
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import find_current_road, insert_road_segments, road_name_matches


def _build_roads_db(db_path: Path) -> None:
  with sqlite3.connect(db_path) as conn:
    insert_road_segments(conn, [
      {
        "osm_id": 1,
        "name": "Test Expressway",
        "ref": "E1",
        "highway": "motorway",
        "road_class": "EXPRESSWAY",
        "oneway": 0,
        "lat1": 37.0000,
        "lon1": 127.0000,
        "lat2": 37.0100,
        "lon2": 127.0000,
      },
      {
        "osm_id": 2,
        "name": "Cross Road",
        "ref": "",
        "highway": "primary",
        "road_class": "NATIONAL_ROAD",
        "oneway": 0,
        "lat1": 37.0050,
        "lon1": 126.9900,
        "lat2": 37.0050,
        "lon2": 127.0100,
      },
    ])


def test_road_name_matches_uses_normalized_names() -> None:
  assert road_name_matches("Test Expressway", "test expressway")
  assert road_name_matches("E1", "E1")
  assert not road_name_matches("Test Expressway", "Other Road")


def test_find_current_road_prefers_heading_aligned_segment(tmp_path: Path) -> None:
  db_path = tmp_path / "osm_roads.sqlite3"
  _build_roads_db(db_path)

  match = find_current_road(db_path, 37.0050, 127.00002, 0.0, radius_m=80.0)

  assert match is not None
  assert match.name == "Test Expressway"
  assert match.distance_m < 5.0


def test_find_current_road_returns_none_when_db_missing(tmp_path: Path) -> None:
  assert find_current_road(tmp_path / "missing.sqlite3", 37.0, 127.0, 0.0) is None
