import sqlite3
from pathlib import Path

try:
  from openpilot.selfdrive.navd.osm_roads import (
    OSMRoadSegment,
    build_road_graph,
    find_current_road,
    forward_road_segments,
    insert_road_segments,
    road_name_matches,
    road_successors,
    segment_allowed_bearings,
  )
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import (
    OSMRoadSegment,
    build_road_graph,
    find_current_road,
    forward_road_segments,
    insert_road_segments,
    road_name_matches,
    road_successors,
    segment_allowed_bearings,
  )


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
  assert match.oneway == 0
  assert match.distance_m < 5.0


def test_osm_road_queries_accept_reused_connection(tmp_path: Path) -> None:
  db_path = tmp_path / "osm_roads.sqlite3"
  _build_roads_db(db_path)

  with sqlite3.connect(db_path) as conn:
    match = find_current_road(conn, 37.0050, 127.00002, 0.0, radius_m=80.0)
    segments = forward_road_segments(conn, 37.0, 127.0, 0.0, -100.0, 1500.0, 70.0, 140.0, 10)

  assert match is not None
  assert match.name == "Test Expressway"
  assert [segment.name for segment in segments] == ["Test Expressway", "Cross Road"]


def test_find_current_road_returns_none_when_db_missing(tmp_path: Path) -> None:
  assert find_current_road(tmp_path / "missing.sqlite3", 37.0, 127.0, 0.0) is None


def test_forward_road_segments_filters_to_corridor(tmp_path: Path) -> None:
  db_path = tmp_path / "osm_roads.sqlite3"
  with sqlite3.connect(db_path) as conn:
    insert_road_segments(conn, [
      {
        "osm_id": 10,
        "name": "Forward Road",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 37.0010,
        "lon1": 127.0000,
        "lat2": 37.0100,
        "lon2": 127.0000,
      },
      {
        "osm_id": 11,
        "name": "Rear Road",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 36.9950,
        "lon1": 127.0000,
        "lat2": 36.9985,
        "lon2": 127.0000,
      },
      {
        "osm_id": 12,
        "name": "Far Side Road",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 37.0010,
        "lon1": 127.0020,
        "lat2": 37.0100,
        "lon2": 127.0020,
      },
    ])

  segments = forward_road_segments(db_path, 37.0, 127.0, 0.0, -100.0, 1500.0, 70.0, 140.0, 10)

  assert [segment.name for segment in segments] == ["Forward Road"]
  assert segments[0].oneway == 0


def test_forward_road_segments_uses_wider_major_side_limit(tmp_path: Path) -> None:
  db_path = tmp_path / "osm_roads.sqlite3"
  with sqlite3.connect(db_path) as conn:
    insert_road_segments(conn, [
      {
        "osm_id": 20,
        "name": "Local Side Road",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 37.0010,
        "lon1": 127.0012,
        "lat2": 37.0100,
        "lon2": 127.0012,
      },
      {
        "osm_id": 21,
        "name": "Major Side Road",
        "ref": "",
        "highway": "primary",
        "road_class": "NATIONAL_ROAD",
        "oneway": 0,
        "lat1": 37.0010,
        "lon1": 127.0012,
        "lat2": 37.0100,
        "lon2": 127.0012,
      },
    ])

  segments = forward_road_segments(db_path, 37.0, 127.0, 0.0, -100.0, 1500.0, 70.0, 140.0, 10)

  assert [segment.name for segment in segments] == ["Major Side Road"]


def test_segment_allowed_bearings_respects_oneway() -> None:
  base_segment = OSMRoadSegment(
    road_id=1,
    osm_id=1,
    name="Bearing Road",
    ref="",
    highway="residential",
    road_class="CITY_ROAD",
    oneway=1,
    lat1=37.0,
    lon1=127.0,
    lat2=37.001,
    lon2=127.0,
    bearing_deg=10.0,
    distance_m=0.0,
  )

  assert segment_allowed_bearings(base_segment) == (10.0,)
  assert segment_allowed_bearings(base_segment.__class__(**{**base_segment.__dict__, "oneway": -1})) == (190.0,)
  assert segment_allowed_bearings(base_segment.__class__(**{**base_segment.__dict__, "oneway": 0})) == (10.0, 190.0)


def test_road_graph_successors_orders_by_turn_angle(tmp_path: Path) -> None:
  db_path = tmp_path / "osm_roads.sqlite3"
  with sqlite3.connect(db_path) as conn:
    insert_road_segments(conn, [
      {
        "osm_id": 30,
        "name": "Approach Road",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 37.0000,
        "lon1": 127.0000,
        "lat2": 37.0010,
        "lon2": 127.0000,
      },
      {
        "osm_id": 31,
        "name": "Straight Road",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 37.0010,
        "lon1": 127.0000,
        "lat2": 37.0020,
        "lon2": 127.0000,
      },
      {
        "osm_id": 32,
        "name": "Right Road",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 37.0010,
        "lon1": 127.0000,
        "lat2": 37.0010,
        "lon2": 127.0010,
      },
    ])
    approach_id = conn.execute("SELECT id FROM roads WHERE name = ?", ("Approach Road",)).fetchone()[0]

  successors = road_successors(db_path, approach_id)

  assert [transition.road.name for transition in successors] == ["Straight Road", "Right Road"]
  assert successors[0].turn_angle_deg < 1.0
  assert 89.0 < successors[1].turn_angle_deg < 91.0


def test_road_graph_respects_oneway_direction(tmp_path: Path) -> None:
  db_path = tmp_path / "osm_roads.sqlite3"
  with sqlite3.connect(db_path) as conn:
    insert_road_segments(conn, [
      {
        "osm_id": 40,
        "name": "One Way A",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 1,
        "lat1": 37.0000,
        "lon1": 127.0000,
        "lat2": 37.0010,
        "lon2": 127.0000,
      },
      {
        "osm_id": 41,
        "name": "One Way B",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 1,
        "lat1": 37.0010,
        "lon1": 127.0000,
        "lat2": 37.0020,
        "lon2": 127.0000,
      },
    ])
    road_a_id = conn.execute("SELECT id FROM roads WHERE name = ?", ("One Way A",)).fetchone()[0]
    road_b_id = conn.execute("SELECT id FROM roads WHERE name = ?", ("One Way B",)).fetchone()[0]

  assert [transition.road.name for transition in road_successors(db_path, road_a_id)] == ["One Way B"]
  assert road_successors(db_path, road_b_id) == []


def test_build_road_graph_reports_metadata(tmp_path: Path) -> None:
  db_path = tmp_path / "osm_roads.sqlite3"
  with sqlite3.connect(db_path) as conn:
    insert_road_segments(conn, [
      {
        "osm_id": 50,
        "name": "Graph Road A",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 37.0000,
        "lon1": 127.0000,
        "lat2": 37.0010,
        "lon2": 127.0000,
      },
      {
        "osm_id": 51,
        "name": "Graph Road B",
        "ref": "",
        "highway": "residential",
        "road_class": "CITY_ROAD",
        "oneway": 0,
        "lat1": 37.0010,
        "lon1": 127.0000,
        "lat2": 37.0020,
        "lon2": 127.0000,
      },
    ])
    stats = build_road_graph(conn)
    metadata = dict(conn.execute("SELECT key, value FROM metadata WHERE key LIKE 'road_graph_%'"))

  assert stats.node_count == 3
  assert stats.edge_count == 2
  assert stats.adjacency_count == 2
  assert metadata["road_graph_node_count"] == "3"
  assert metadata["road_graph_edge_count"] == "2"
  assert metadata["road_graph_adjacency_count"] == "2"
