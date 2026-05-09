import importlib.util
import sys
import types
from pathlib import Path


def _load_navid_module():
  repo_root = Path(__file__).resolve().parents[2]

  import selfdrive.navd.speed_camera as speed_camera

  cereal = sys.modules.setdefault("cereal", types.ModuleType("cereal"))
  messaging = types.ModuleType("cereal.messaging")
  messaging.PubMaster = object
  messaging.SubMaster = object
  messaging.new_message = lambda *args, **kwargs: None
  cereal.messaging = messaging
  sys.modules["cereal.messaging"] = messaging

  sys.modules.setdefault("openpilot", types.ModuleType("openpilot"))
  sys.modules.setdefault("openpilot.common", types.ModuleType("openpilot.common"))

  realtime = types.ModuleType("openpilot.common.realtime")
  realtime.Ratekeeper = object
  sys.modules["openpilot.common.realtime"] = realtime

  swaglog = types.ModuleType("openpilot.common.swaglog")
  swaglog.cloudlog = types.SimpleNamespace(exception=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
  sys.modules["openpilot.common.swaglog"] = swaglog

  sys.modules.setdefault("openpilot.selfdrive", types.ModuleType("openpilot.selfdrive"))
  sys.modules.setdefault("openpilot.selfdrive.navd", types.ModuleType("openpilot.selfdrive.navd"))
  sys.modules["openpilot.selfdrive.navd.speed_camera"] = speed_camera

  ui_custom = types.ModuleType("openpilot.selfdrive.ui.custom")
  ui_custom.read_custom_params = lambda: {}
  sys.modules.setdefault("openpilot.selfdrive.ui", types.ModuleType("openpilot.selfdrive.ui"))
  sys.modules["openpilot.selfdrive.ui.custom"] = ui_custom

  spec = importlib.util.spec_from_file_location("navid_test_module", repo_root / "selfdrive" / "navd" / "navid.py")
  assert spec is not None and spec.loader is not None
  navid = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = navid
  spec.loader.exec_module(navid)
  return navid


def test_format_camera_debug_text_includes_current_road_and_candidates() -> None:
  navid = _load_navid_module()
  camera = types.SimpleNamespace(
    camera_category="SPEED",
    camera_type_code=1,
    distance_m=180.0,
    relative_angle_deg=8.0,
    forward_m=178.0,
    side_m=25.0,
    local_road_match=True,
    is_expressway=True,
  )

  assert navid._format_camera_debug_text([camera], "Current Road").splitlines() == [
    "ROAD Current Road",
    "1 SPD 180m +8 f178 s+25 O R",
  ]


def test_format_debug_road_name_truncates_long_names() -> None:
  navid = _load_navid_module()
  road_line = navid._format_debug_road_name("1234567890123456789012345")

  assert road_line == "ROAD 1234567890123456789..."


def test_format_camera_classification_debug_text() -> None:
  navid = _load_navid_module()
  camera = types.SimpleNamespace(
    camera_type="02",
    section_type="",
    section_length_m=0,
    speed_limit=0,
    distance_m=42.4,
    forward_m=41.5,
    side_m=-8.8,
    bearing_deg=93.0,
    relative_angle_deg=-12.0,
    road_type_raw="시도",
    road_name="중앙사거리",
    place="중앙사거리 신호단속 원본 문구",
    id="ICHEON118",
    direction="3",
    direction_kind="BOTH",
    local_road_match=True,
    is_expressway=False,
  )

  assert navid._format_camera_classification_debug_text(camera, "SIGNAL", 2, "CITY_ROAD", "중앙사거리").splitlines() == [
    "CAM SIGNAL c=2 v=0 id=ICHEON118",
    "POS 42m f=41 s=-8 a=-12 bear=93",
    "RAW type=02 dir=3/BOTH sect=- len=0",
    "ROAD CITY_ROAD | 중앙사거리",
    "PLACE 중앙사거리 신호단속 원본 문구",
    "WHY osm=Y cur=중앙사거리 corr=Y flags=ZERO",
  ]


def test_forward_road_info_marks_ahead_corridor() -> None:
  navid = _load_navid_module()
  segment = types.SimpleNamespace(bearing_deg=0.0, highway="residential", name="Current Road", ref="")
  gps = types.SimpleNamespace(bearingDeg=0.0)

  info = navid._forward_road_info(segment, gps, 10.0, 3.0, 120.0, 5.0, "Current Road")

  assert info == {
    "f": True,
    "fm": 10.0,
    "sm": 3.0,
    "a": 0.0,
  }


def test_forward_road_info_rejects_cross_traffic() -> None:
  navid = _load_navid_module()
  segment = types.SimpleNamespace(bearing_deg=90.0, highway="residential", name="Current Road", ref="")
  gps = types.SimpleNamespace(bearingDeg=0.0)

  info = navid._forward_road_info(segment, gps, 20.0, -5.0, 20.0, 80.0, "Current Road")

  assert info["f"] is False


def test_osm_corridor_cache_refreshes_on_heading_change(tmp_path: Path) -> None:
  navid = _load_navid_module()
  cache = navid.OsmRoadCache(
    center_lat=37.0,
    center_lon=127.0,
    heading_deg=0.0,
    forward_start_m=-100.0,
    forward_end_m=1500.0,
    side_limit_m=70.0,
    major_side_limit_m=140.0,
    refresh_distance_m=900.0,
    loaded_at=1.0,
    db_mtime=0.0,
    cache_kind="corridor",
  )
  gps = types.SimpleNamespace(latitude=37.0, longitude=127.0, bearingDeg=30.0)

  assert navid._osm_corridor_cache_needs_refresh(
    cache, tmp_path / "missing.sqlite3", gps, -100.0, 1500.0, 70.0, 140.0, 900.0, 3.0
  )


def test_stable_osm_overlay_keeps_last_good_text_briefly() -> None:
  navid = _load_navid_module()

  overlay, last_good, last_good_t = navid._stable_osm_overlay_text('{"mapRoads":[1]}', "", 0.0, 10.0)
  assert overlay == '{"mapRoads":[1]}'
  assert last_good == '{"mapRoads":[1]}'
  assert last_good_t == 10.0

  overlay, last_good, last_good_t = navid._stable_osm_overlay_text("", last_good, last_good_t, 12.0)
  assert overlay == '{"mapRoads":[1]}'
  assert last_good == '{"mapRoads":[1]}'
  assert last_good_t == 10.0

  overlay, last_good, last_good_t = navid._stable_osm_overlay_text("", last_good, last_good_t, 14.0)
  assert overlay == ""
  assert last_good == ""
  assert last_good_t == 0.0


def test_osm_corridor_cache_keeps_existing_segments_on_sparse_refresh(tmp_path: Path, monkeypatch) -> None:
  navid = _load_navid_module()
  db_path = tmp_path / "osm.sqlite3"
  db_path.write_text("")
  old_segments = [object(), object(), object(), object()]
  new_segments = [object()]
  cache = navid.OsmRoadCache(
    center_lat=37.0,
    center_lon=127.0,
    heading_deg=0.0,
    forward_start_m=-100.0,
    forward_end_m=1500.0,
    side_limit_m=70.0,
    major_side_limit_m=140.0,
    refresh_distance_m=900.0,
    loaded_at=1.0,
    db_mtime=123.0,
    cache_kind="corridor",
    segments=old_segments,
  )
  gps = types.SimpleNamespace(latitude=37.0, longitude=127.0, bearingDeg=30.0)

  monkeypatch.setattr(navid, "_osm_db_mtime", lambda path: 123.0)
  monkeypatch.setattr(navid, "forward_road_segments", lambda *args, **kwargs: new_segments)

  navid._ensure_osm_corridor_cache(cache, db_path, gps, 500.0, 3.0)

  assert cache.segments == old_segments
  assert cache.loaded_at == 3.0


def test_minimap_roads_include_full_visible_view(monkeypatch) -> None:
  navid = _load_navid_module()
  cache = types.SimpleNamespace(segments=["visible_top", "outside_side"])
  payloads = {
    "visible_top": {"x1": 360.0, "y1": 0.0, "x2": 390.0, "y2": 5.0, "d": 360.0, "n": "visible", "h": "residential", "c": False},
    "outside_side": {"x1": 80.0, "y1": 520.0, "x2": 120.0, "y2": 540.0, "d": 80.0, "n": "outside", "h": "residential", "c": False},
  }

  monkeypatch.setattr(navid, "_road_payload", lambda segment, gps, current_road_name, include_distance=False: payloads[segment])

  roads = navid._minimap_roads(cache, types.SimpleNamespace(), "", 300.0)

  assert [road["n"] for road in roads] == ["visible"]


def test_osm_corridor_cache_covers_minimap_visible_width(tmp_path: Path, monkeypatch) -> None:
  navid = _load_navid_module()
  db_path = tmp_path / "osm.sqlite3"
  db_path.write_text("")
  cache = navid.OsmRoadCache()
  gps = types.SimpleNamespace(latitude=37.0, longitude=127.0, bearingDeg=0.0)
  captured = {}

  def fake_forward_road_segments(db_path, lat, lon, heading_deg, forward_start_m, forward_end_m,
                                 side_limit_m, major_side_limit_m, limit):
    captured.update({
      "forward_start_m": forward_start_m,
      "forward_end_m": forward_end_m,
      "side_limit_m": side_limit_m,
      "major_side_limit_m": major_side_limit_m,
      "limit": limit,
    })
    return [object()]

  monkeypatch.setattr(navid, "_osm_db_mtime", lambda path: 123.0)
  monkeypatch.setattr(navid, "forward_road_segments", fake_forward_road_segments)

  navid._ensure_osm_corridor_cache(cache, db_path, gps, 300.0, 3.0)

  assert captured["forward_start_m"] <= -120.0
  assert captured["forward_end_m"] >= 1300.0
  assert captured["side_limit_m"] >= 480.0
  assert captured["major_side_limit_m"] >= 480.0
  assert cache.side_limit_m == captured["side_limit_m"]
