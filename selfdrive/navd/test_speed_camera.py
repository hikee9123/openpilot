import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


try:
  import openpilot.selfdrive.navd.camera_road_context as camera_road_context
  import openpilot.selfdrive.navd.speed_camera as speed_camera
except ModuleNotFoundError:
  import selfdrive.navd.camera_road_context as camera_road_context
  spec = importlib.util.spec_from_file_location(
    "speed_camera", Path(__file__).resolve().parents[2] / "selfdrive" / "navd" / "speed_camera.py"
  )
  assert spec is not None and spec.loader is not None
  speed_camera = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = speed_camera
  spec.loader.exec_module(speed_camera)

CsvSource = speed_camera.CsvSource
camera_category_code = speed_camera.camera_category_code
camera_type_code = speed_camera.camera_type_code
create_database_from_csv = speed_camera.create_database_from_csv
create_database_from_csvs = speed_camera.create_database_from_csvs
database_category_counts = speed_camera.database_category_counts
database_data_date = speed_camera.database_data_date
database_region_counts = speed_camera.database_region_counts
database_region_stats = speed_camera.database_region_stats
direction_bearing_deg = speed_camera.direction_bearing_deg
direction_kind = speed_camera.direction_kind
normalize_code_for_db = speed_camera.normalize_code_for_db
normalize_direction_for_db = speed_camera.normalize_direction_for_db
download_public_speed_camera_csv = speed_camera.download_public_speed_camera_csv
export_speed_camera_leaflet_html = speed_camera.export_speed_camera_leaflet_html
find_lead_camera = speed_camera.find_lead_camera
find_lead_cameras = speed_camera.find_lead_cameras
normalize_camera_category = speed_camera.normalize_camera_category
normalize_road_class = speed_camera.normalize_road_class
relative_projection_m = speed_camera.relative_projection_m
route_hint_from_text = speed_camera.route_hint_from_text
same_corridor_likely = speed_camera.same_corridor_likely

try:
  from openpilot.selfdrive.navd.osm_roads import forward_road_segments, insert_road_segments
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import forward_road_segments, insert_road_segments


def _write_csv(path: Path, body: str) -> None:
  path.write_text(body, encoding="utf-8-sig")


def _build_test_osm_roads_db(db_path: Path) -> None:
  with sqlite3.connect(db_path) as conn:
    insert_road_segments(conn, [
      {
        "osm_id": 101,
        "name": "Current Road",
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
        "osm_id": 102,
        "name": "Other Road",
        "ref": "",
        "highway": "primary",
        "road_class": "NATIONAL_ROAD",
        "oneway": 0,
        "lat1": 37.0000,
        "lon1": 127.0010,
        "lat2": 37.0100,
        "lon2": 127.0010,
      },
    ])


def _build_single_osm_road_db(db_path: Path, *, oneway: int, lat1: float = 37.0, lat2: float = 37.0100) -> None:
  with sqlite3.connect(db_path) as conn:
    insert_road_segments(conn, [{
      "osm_id": 201,
      "name": "Current Road",
      "ref": "",
      "highway": "residential",
      "road_class": "CITY_ROAD",
      "oneway": oneway,
      "lat1": lat1,
      "lon1": 127.0000,
      "lat2": lat2,
      "lon2": 127.0000,
    }])


def _fetch_row(db_path: Path, camera_id_prefix: str) -> sqlite3.Row:
  with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM speed_cameras WHERE id LIKE ?", (f"{camera_id_prefix}-%",)).fetchone()
  assert row is not None
  return row


def test_import_and_find_lead_camera(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,속도위반,80,전방도로\n"
    "A2,36.999,127.0,속도위반,60,후방도로\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  front_camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  rear_camera = find_lead_camera(db_path, 37.0, 127.0, 180.0)

  assert front_camera is not None
  assert front_camera.id.startswith("A1-")
  assert front_camera.speed_limit == 80

  assert rear_camera is not None
  assert rear_camera.id.startswith("A2-")


def test_export_speed_camera_leaflet_html(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  html_path = tmp_path / "speed_cameras.html"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로노선방향,설치장소\n"
    "A1,37.001,127.0,속도위반,80,1,전방도로\n",
  )
  create_database_from_csv(csv_path, db_path)

  assert export_speed_camera_leaflet_html(db_path, html_path, data_mode="inline") == 1
  html = html_path.read_text(encoding="utf-8")

  assert "leaflet@1.9.4" in html
  assert "tile.openstreetmap.org" in html
  assert "L.circleMarker" in html
  assert "speed-limit-label" in html
  assert "bindTooltip(speedLabel" in html
  assert "category-chip" in html
  assert "categoryDot(label)" in html
  assert "#d73027" in html
  assert "popup-grid" in html
  assert "--popup-min-width: 620px" in html
  assert "--popup-width: 760px" in html
  assert "--popup-viewport-width: 42vw" in html
  assert "--popup-opacity: 0.70" in html
  assert "width: clamp(var(--popup-min-width), var(--popup-viewport-width), var(--popup-width))" in html
  assert "background: rgba(255, 255, 255, var(--popup-opacity))" in html
  assert "backdrop-filter: blur(2px)" in html
  assert "grid-template-columns: minmax(0, 1.08fr) minmax(0, 0.92fr)" in html
  assert "function popupOptions()" in html
  assert 'cssLengthPx("--popup-width", 760)' in html
  assert 'cssLengthPx("--popup-min-width", 620)' in html
  assert "marker.bindPopup(makePopup(camera), popupOptions())" in html
  assert "max-height: 520px" in html
  assert "overflow-wrap: anywhere" in html
  assert "Speed camera debug" in html
  assert "dataset-source" in html
  assert "dataset-load-status" in html
  assert "camera-type-filter" in html
  assert "direction-filter" in html
  assert "quality-filter" in html
  assert "전체 단속 구분" in html
  assert "전체 도로방향" in html
  assert "전체 데이터 상태" in html
  assert "좌표 오기 의심 수" in html
  assert "function cameraEnforcementType(camera)" in html
  assert "function cameraDirectionType(camera)" in html
  assert "function cameraQualityCategory(camera)" in html
  assert "function defaultQualityFilter()" in html
  assert 'activeDatasetKey === "db" ? "NORMAL" : ""' in html
  assert "directionKindLabel(camera.directionKind)" in html
  assert "qualityLabel(cameraQualityCategory(camera))" in html
  assert '"방향 추정데이터": camera.directionKind ? directionKindLabel(camera.directionKind) : ""' in html
  assert '"데이터 상태": qualityLabel(cameraQualityCategory(camera))' in html
  assert '"qualityCategory":"NORMAL"' in html
  assert '"quality_reason":"NORMAL"' not in html
  assert '"cameraType":"속도위반"' in html
  assert '"direction":"1"' in html
  assert '"directionKind":"UP"' in html
  assert "데이터 로딩 중" in html
  assert "데이터 로드 완료" in html
  assert "setActiveDataset" in html
  assert "setActiveDataset(activeDatasetKey, true)" in html
  assert "setActiveDataset(event.target.value, false)" in html
  assert "Array.isArray(dataset.cameras) || dataset.url || dataset.scriptUrl" in html
  assert "activeDataset.count ?? cameras.length" in html
  assert '"activeDataset":"db"' in html
  assert '"inputSource":"DB"' in html
  assert '"sourceFile":"speed_cameras.sqlite3"' in html
  assert '"datasets":{"db"' in html
  assert '"categoryCounts":[{"category":"SPEED","count":1}]' in html
  assert '"id":"A1-' in html
  assert '"lat":37.001' in html
  assert '"category":"SPEED"' in html


def test_export_speed_camera_leaflet_html_can_show_raw_csv_rows(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  html_path = tmp_path / "speed_cameras.html"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,속도위반,80,전방도로\n"
    "A1,37.001,127.0,속도위반,80,중복 전방도로\n",
  )
  assert create_database_from_csv(csv_path, db_path) == 1

  assert export_speed_camera_leaflet_html(
    db_path,
    html_path,
    csv_sources=[CsvSource(csv_path, "public")],
    active_source="csv",
    data_mode="inline",
  ) == 2
  html = html_path.read_text(encoding="utf-8")

  assert '"count":2' in html
  assert '"activeDataset":"csv"' in html
  assert '"inputSource":"CSV"' in html
  assert '"sourceFile":"speed_cameras.csv"' in html
  assert '"datasets":{"db"' in html
  assert '"csv":{"inputSource":"CSV"' in html
  assert "무인교통단속카메라관리번호" in html
  assert "중복 전방도로" in html
  assert '"categoryCounts":[{"category":"SPEED","count":1}]' in html
  assert '"dedup_key"' in html
  assert "speed_cameras.csv" in html


def test_export_speed_camera_leaflet_html_can_start_from_db_dataset(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  html_path = tmp_path / "speed_cameras.html"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,속도위반,80,전방도로\n"
    "A1,37.001,127.0,속도위반,80,중복 전방도로\n",
  )
  assert create_database_from_csv(csv_path, db_path) == 1

  assert export_speed_camera_leaflet_html(
    db_path,
    html_path,
    csv_sources=[CsvSource(csv_path, "public")],
    active_source="db",
    data_mode="inline",
  ) == 1
  html = html_path.read_text(encoding="utf-8")

  assert '"activeDataset":"db"' in html
  assert '"count":1' in html
  assert '"csv":{"inputSource":"CSV","sourceFile":"speed_cameras.csv","count":2' in html


def test_export_speed_camera_leaflet_html_can_write_external_datasets(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  html_path = tmp_path / "speed_cameras.html"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,속도위반,80,전방도로\n"
    "A1,37.001,127.0,속도위반,80,중복 전방도로\n",
  )
  assert create_database_from_csv(csv_path, db_path) == 1

  assert export_speed_camera_leaflet_html(
    db_path,
    html_path,
    csv_sources=[CsvSource(csv_path, "public")],
    active_source="csv",
  ) == 2
  data_dir = tmp_path / "speed_cameras_data"
  csv_json_path = data_dir / "csv.json"
  db_json_path = data_dir / "db.json"
  csv_js_path = data_dir / "csv.js"
  db_js_path = data_dir / "db.js"
  html = html_path.read_text(encoding="utf-8")
  csv_json = csv_json_path.read_text(encoding="utf-8")
  db_json = db_json_path.read_text(encoding="utf-8")
  csv_js = csv_js_path.read_text(encoding="utf-8")
  db_js = db_js_path.read_text(encoding="utf-8")

  assert csv_json_path.exists()
  assert db_json_path.exists()
  assert csv_js_path.exists()
  assert db_js_path.exists()
  assert '"dataMode":"external"' in html
  assert "Array.isArray(dataset.cameras) || dataset.url || dataset.scriptUrl" in html
  assert "activeDataset.count ?? cameras.length" in html
  assert "loadDatasetScript" in html
  assert '"url":"speed_cameras_data/db.json"' in html
  assert '"url":"speed_cameras_data/csv.json"' in html
  assert '"scriptUrl":"speed_cameras_data/db.js"' in html
  assert '"scriptUrl":"speed_cameras_data/csv.js"' in html
  assert '"cameras":[' not in html
  assert "중복 전방도로" not in html
  assert '"inputSource":"CSV"' in csv_json
  assert '"count":2' in csv_json
  assert "중복 전방도로" in csv_json
  assert "window.__NAVD_CAMERA_DATASETS__" in csv_js
  assert "중복 전방도로" in csv_js
  assert '"inputSource":"DB"' in db_json
  assert '"count":1' in db_json
  assert "window.__NAVD_CAMERA_DATASETS__" in db_js


def test_export_speed_camera_leaflet_html_can_write_external_datasets_to_custom_dir(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  html_path = tmp_path / "viewer" / "speed_cameras.html"
  data_dir = tmp_path / "assets" / "camera_data"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,속도위반,80,전방도로\n",
  )
  assert create_database_from_csv(csv_path, db_path) == 1

  assert export_speed_camera_leaflet_html(
    db_path,
    html_path,
    csv_sources=[CsvSource(csv_path, "public")],
    data_dir=data_dir,
  ) == 1
  html = html_path.read_text(encoding="utf-8")

  assert (data_dir / "csv.json").exists()
  assert (data_dir / "db.json").exists()
  assert '"url":"../assets/camera_data/csv.json"' in html
  assert '"scriptUrl":"../assets/camera_data/csv.js"' in html


@pytest.mark.parametrize(
  ("camera_type", "expected"),
  [
    ("01", "SPEED"),
    ("1", "SPEED"),
    ("속도위반", "SPEED"),
    ("과속단속", "SPEED"),
    ("02", "SIGNAL"),
    ("2", "SIGNAL"),
    ("신호위반", "SIGNAL"),
    ("신호+속도위반", "SPEED_SIGNAL"),
    ("과속+신호", "SPEED_SIGNAL"),
    ("01+02", "SPEED_SIGNAL"),
    ("구간단속", "SECTION_SPEED"),
    ("03", "SECURITY"),
    ("3", "SECURITY"),
    ("04", "PROTECTED_ZONE"),
    ("4", "PROTECTED_ZONE"),
    ("99", "UNKNOWN"),
    ("주정차", "PARKING"),
    ("버스전용차로", "BUS_LANE"),
    ("방범CCTV", "SECURITY"),
    ("", "UNKNOWN"),
    ("기타", "ETC"),
  ],
)
def test_normalize_camera_category(camera_type: str, expected: str) -> None:
  assert normalize_camera_category(camera_type) == expected


def test_normalize_camera_category_uses_section_type() -> None:
  assert normalize_camera_category("", section_type="구간") == "SECTION_SPEED"
  assert normalize_camera_category("99", section_type="1") == "SECTION_SPEED"
  assert normalize_camera_category("99", section_type="2") == "SECTION_SPEED"
  assert normalize_camera_category("99", context_text="구간 종점 1차로") == "SECTION_SPEED"
  assert normalize_camera_category("99", context_text="초교 건너편 어린이보호구역") == "SECTION_SPEED"
  assert normalize_camera_category("99", context_text="학돌초등학교 사거리", speed_limit=30) == "SECTION_SPEED"
  assert normalize_camera_category("99", context_text="학돌초등학교 사거리", speed_limit=50) == "UNKNOWN"


def test_normalize_signal_type_with_speed_limit_as_speed_signal() -> None:
  assert normalize_camera_category("2", speed_limit=50) == "SPEED_SIGNAL"
  assert normalize_camera_category("02", speed_limit=30) == "SPEED_SIGNAL"
  assert normalize_camera_category("2", speed_limit=0) == "SIGNAL"
  assert normalize_camera_category("02") == "SIGNAL"


@pytest.mark.parametrize(
  ("category", "expected"),
  [
    ("SPEED", 1),
    ("SIGNAL", 2),
    ("SPEED_SIGNAL", 3),
    ("SECTION_SPEED", 4),
    ("PARKING", 5),
    ("BUS_LANE", 6),
    ("TRAFFIC", 7),
    ("SECURITY", 8),
    ("UNKNOWN", 9),
    ("PROTECTED_ZONE", 10),
    ("ETC", 0),
  ],
)
def test_camera_category_code(category: str, expected: int) -> None:
  assert camera_category_code(category) == expected


@pytest.mark.parametrize(
  ("road_type", "expected"),
  [
    ("고속국도", "EXPRESSWAY"),
    ("고속도로", "EXPRESSWAY"),
    ("일반국도", "NATIONAL_ROAD"),
    ("국도", "NATIONAL_ROAD"),
    ("국가지원지방도", "NATIONAL_LOCAL_ROAD"),
    ("지방도", "LOCAL_ROAD"),
    ("특별시도", "CITY_ROAD"),
    ("시도", "CITY_ROAD"),
    ("군도", "COUNTY_ROAD"),
    ("구도", "DISTRICT_ROAD"),
    ("", "UNKNOWN"),
    ("기타", "ETC"),
  ],
)
def test_normalize_road_class(road_type: str, expected: str) -> None:
  assert normalize_road_class(road_type) == expected


@pytest.mark.parametrize(
  ("road_type", "road_name", "place", "expected"),
  [
    ("시도", "고속버스터미널 앞", "", "CITY_ROAD"),
    ("기타", "고속철대로", "", "ETC"),
    ("지방도", "과천봉담도시고속화대로", "과천-봉담도시고속화도로", "LOCAL_ROAD"),
    ("일반국도", "분당-수서간도시고속화도로", "", "NATIONAL_ROAD"),
    ("고속국도", "경부고속도로", "", "EXPRESSWAY"),
    ("", "경부고속도로", "", "EXPRESSWAY"),
    ("", "고속철대로", "천안아산역 동편도로 주변", "UNKNOWN"),
    ("", "갑천도시고속도로", "", "UNKNOWN"),
  ],
)
def test_normalize_road_class_prefers_source_road_type(
  road_type: str, road_name: str, place: str, expected: str,
) -> None:
  assert normalize_road_class(road_type, road_name, place) == expected


def test_import_stores_camera_category_and_road_class_columns(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로종류,설치장소\n"
    "A1,37.001,127.0,속도위반,80,고속국도,전방도로\n"
    "A2,37.002,127.0,신호위반,0,일반국도,교차로\n"
    "A3,37.003,127.0,신호+속도위반,60,지방도,복합단속\n"
    "A4,37.004,127.0,주정차,0,시도,주차구역\n"
    "A5,37.005,127.0,2,50,시도,신호속도 교차로\n"
    "A6,37.006,127.0,02,0,시도,신호 교차로\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 6

  a1 = _fetch_row(db_path, "A1")
  assert a1["camera_category"] == "SPEED"
  assert a1["camera_type_code"] == 1
  assert a1["is_speed_camera"] == 1
  assert a1["quality_category"] == "NORMAL"
  assert a1["quality_reason"] == ""
  assert a1["road_class"] == "EXPRESSWAY"
  assert a1["road_class_code"] == 1
  assert a1["is_expressway"] == 1

  a2 = _fetch_row(db_path, "A2")
  assert a2["camera_category"] == "SIGNAL"
  assert a2["camera_type_code"] == 2
  assert a2["is_signal_camera"] == 1
  assert a2["is_speed_camera"] == 0
  assert a2["road_class"] == "NATIONAL_ROAD"
  assert a2["road_class_code"] == 2
  assert a2["is_national_road"] == 1

  a3 = _fetch_row(db_path, "A3")
  assert a3["camera_category"] == "SPEED_SIGNAL"
  assert a3["camera_type_code"] == 3
  assert a3["is_speed_camera"] == 1
  assert a3["is_signal_camera"] == 1
  assert a3["road_class"] == "LOCAL_ROAD"

  a5 = _fetch_row(db_path, "A5")
  assert a5["camera_category"] == "SPEED_SIGNAL"
  assert a5["camera_type_code"] == 3
  assert a5["is_speed_camera"] == 1
  assert a5["is_signal_camera"] == 1

  a6 = _fetch_row(db_path, "A6")
  assert a6["camera_category"] == "SIGNAL"
  assert a6["camera_type_code"] == 2
  assert a6["is_speed_camera"] == 0
  assert a6["is_signal_camera"] == 1
  assert a6["speed_limit"] == 0

  a4 = _fetch_row(db_path, "A4")
  assert a4["camera_category"] == "PARKING"
  assert a4["camera_type_code"] == 5
  assert a4["is_etc_camera"] == 1
  assert a4["road_class"] == "CITY_ROAD"

  with sqlite3.connect(db_path) as conn:
    version = conn.execute("SELECT value FROM metadata WHERE key = 'version'").fetchone()[0]
    suspect_count = conn.execute("SELECT value FROM metadata WHERE key = 'coordinate_suspect_count'").fetchone()[0]
  assert version == str(speed_camera.DB_VERSION)
  assert suspect_count == "0"


def test_coordinate_suspect_rows_are_categorized_not_removed(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로노선명,설치장소\n"
    "J4262,37.4447525,125.1673663,2,30,금광로,금빛그랑메종 508동 앞\n"
    "A1,37.001,127.0,속도위반,80,정상로,정상 카메라\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  suspect = _fetch_row(db_path, "J4262")
  normal = _fetch_row(db_path, "A1")
  assert suspect["camera_category"] == "SPEED_SIGNAL"
  assert suspect["quality_category"] == "COORDINATE_SUSPECT"
  assert suspect["quality_reason"] == "known_longitude_typo"
  assert normal["quality_category"] == "NORMAL"

  with sqlite3.connect(db_path) as conn:
    suspect_count = conn.execute("SELECT value FROM metadata WHERE key = 'coordinate_suspect_count'").fetchone()[0]
  assert suspect_count == "1"

  assert find_lead_camera(db_path, 37.4447525, 125.1673663, 90.0, max_distance_m=500.0) is None


def test_find_lead_camera_prioritizes_speed_camera_over_nearest_signal(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,신호위반,0,신호교차로\n"
    "A2,37.002,127.0,속도위반,80,과속단속\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2
  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.id.startswith("A2-")
  assert camera.camera_category == "SPEED"
  assert camera.camera_type_code == 1

  cameras = find_lead_cameras(db_path, 37.0, 127.0, 0.0, limit=2)
  assert [camera.camera_category for camera in cameras] == ["SPEED", "SIGNAL"]


def test_find_lead_camera_prefers_same_corridor_within_speed_candidates(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.0005,127.0005,속도위반,80,측방도로\n"
    "A2,37.0010,127.0000,속도위반,80,직진도로\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2
  cameras = find_lead_cameras(db_path, 37.0, 127.0, 0.0, max_angle_deg=60.0, limit=2)
  assert len(cameras) == 2
  assert cameras[0].id.startswith("A2-")
  assert same_corridor_likely(cameras[0])
  assert not same_corridor_likely(cameras[1])


def test_speed_camera_without_limit_keeps_speed_category(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,속도위반,0,제한속도누락\n"
    "A2,37.002,127.0,주정차,0,주차단속\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2
  row = _fetch_row(db_path, "A1")
  assert row["camera_category"] == "SPEED"
  assert row["is_speed_camera"] == 1

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.camera_category == "SPEED"
  assert camera.speed_limit == 0


def test_type_three_and_four_are_non_speed_categories(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,3,0,보안구역\n"
    "A2,37.002,127.0,4,0,어린이보호구역\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2
  security = _fetch_row(db_path, "A1")
  assert security["camera_category"] == "SECURITY"
  assert security["camera_type_code"] == 8
  assert security["is_speed_camera"] == 0
  assert security["is_etc_camera"] == 1

  protected = _fetch_row(db_path, "A2")
  assert protected["camera_category"] == "PROTECTED_ZONE"
  assert protected["camera_type_code"] == 10
  assert protected["is_speed_camera"] == 0
  assert protected["is_etc_camera"] == 1
  assert protected["speed_limit"] == 30

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.camera_category == "SECURITY"


def test_speed_signal_category_is_returned(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,신호+속도위반,60,복합단속\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.camera_category == "SPEED_SIGNAL"
  assert camera.camera_type_code == 3


def test_section_speed_category_is_returned(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,단속구간위치구분,제한속도,설치장소\n"
    "A1,37.001,127.0,기타,구간단속,80,구간단속\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  row = _fetch_row(db_path, "A1")
  assert row["camera_category"] == "SECTION_SPEED"
  assert row["camera_type_code"] == 4
  assert row["is_speed_camera"] == 1

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.camera_category == "SECTION_SPEED"
  assert camera.camera_type_code == 4


def test_combined_speed_signal_code_is_returned(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,01+02,50,복합단속\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  row = _fetch_row(db_path, "A1")
  assert row["camera_category"] == "SPEED_SIGNAL"
  assert row["is_speed_camera"] == 1
  assert row["is_signal_camera"] == 1


def test_section_speed_from_unknown_code_and_context(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,단속구간위치구분,제한속도,설치장소\n"
    "A1,37.001,127.0,99,1,80,구간 시점 1차로\n"
    "A2,37.002,127.0,99,,80,구간 종점 1차로\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2
  with sqlite3.connect(db_path) as conn:
    rows = conn.execute("SELECT camera_category, is_speed_camera FROM speed_cameras ORDER BY id").fetchall()
  assert rows == [("SECTION_SPEED", 1), ("SECTION_SPEED", 1)]


def test_create_database_from_csvs_merges_duplicate_rows(tmp_path: Path) -> None:
  public_csv = tmp_path / "public.csv"
  region_csv = tmp_path / "region.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  header = "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소,데이터기준일자\n"
  _write_csv(public_csv, header + "A1,37.001,127.0,속도위반,80,공공,2026-01-01\n")
  _write_csv(region_csv, header + "A1,37.001,127.0,속도위반,80,지역 상세 위치,2026-01-01\n")

  assert create_database_from_csvs([CsvSource(public_csv, "public"), CsvSource(region_csv, "region")], db_path) == 1

  row = _fetch_row(db_path, "A1")
  assert row["source_type"] == "region"
  assert row["source_file"] == "region.csv"
  assert row["place"] == "지역 상세 위치"


def test_create_database_from_csvs_custom_overrides_region(tmp_path: Path) -> None:
  region_csv = tmp_path / "region.csv"
  custom_csv = tmp_path / "custom.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  header = "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소,데이터기준일자\n"
  _write_csv(region_csv, header + "A1,37.001,127.0,속도위반,80,지역 상세 위치,2026-01-01\n")
  _write_csv(custom_csv, header + "A1,37.001,127.0,속도위반,80,커스텀 위치,2026-01-01\n")

  assert create_database_from_csvs([CsvSource(region_csv, "region"), CsvSource(custom_csv, "custom")], db_path) == 1

  row = _fetch_row(db_path, "A1")
  assert row["source_type"] == "custom"
  assert row["source_file"] == "custom.csv"
  assert row["place"] == "커스텀 위치"


def test_same_manage_no_nearby_gps_rows_are_merged(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소,데이터기준일자\n"
    "A1,37.000000,127.000000,속도위반,80,짧은 위치,2026-01-01\n"
    "A1,37.000100,127.000000,속도위반,80,더 자세한 같은 위치,2026-01-01\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 1

  row = _fetch_row(db_path, "A1")
  assert row["place"] == "더 자세한 같은 위치"


def test_same_manage_no_far_gps_rows_are_kept_separate(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소,데이터기준일자\n"
    "A1,37.000000,127.000000,속도위반,80,첫 번째 위치,2026-01-01\n"
    "A1,37.002000,127.000000,속도위반,80,두 번째 위치,2026-01-01\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  with sqlite3.connect(db_path) as conn:
    rows = conn.execute("SELECT dedup_key FROM speed_cameras WHERE id LIKE 'A1-%' ORDER BY id").fetchall()
  assert len(rows) == 2
  assert rows[0][0] != rows[1][0]


def test_same_manage_no_rows_over_50m_are_kept_separate(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소,데이터기준일자\n"
    "A1,37.000000,127.000000,속도위반,80,첫 번째 위치,2026-01-01\n"
    "A1,37.000600,127.000000,속도위반,80,두 번째 위치,2026-01-01\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2


def test_same_manage_no_different_known_categories_are_kept_separate(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소,데이터기준일자\n"
    "A1,37.000000,127.000000,속도위반,50,과속 위치,2026-01-01\n"
    "A1,37.000100,127.000000,신호위반,50,신호 위치,2026-01-02\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  with sqlite3.connect(db_path) as conn:
    categories = [row[0] for row in conn.execute("SELECT camera_category FROM speed_cameras ORDER BY camera_category")]
  assert categories == ["SIGNAL", "SPEED"]


def test_same_manage_no_different_road_classes_are_kept_separate(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로종류,설치장소,데이터기준일자\n"
    "A1,37.0000000,127.0000000,속도위반,80,고속국도,고속도로 위치,2026-01-01\n"
    "A1,37.0001000,127.0000000,속도위반,80,시도,일반도로 위치,2026-01-02\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  with sqlite3.connect(db_path) as conn:
    road_classes = [row[0] for row in conn.execute("SELECT road_class FROM speed_cameras ORDER BY road_class")]
  assert road_classes == ["CITY_ROAD", "EXPRESSWAY"]


def test_unknown_category_merges_with_known_same_speed_and_keeps_known_category(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소,데이터기준일자\n"
    "A1,37.000000,127.000000,속도위반,50,과속 위치,2025-01-01\n"
    "A1,37.000100,127.000000,,50,최신 미분류 위치,2026-01-01\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 1

  row = _fetch_row(db_path, "A1")
  assert row["camera_category"] == "SPEED"
  assert row["place"] == "과속 위치"


def test_unknown_category_different_speed_is_kept_separate_from_known(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소,데이터기준일자\n"
    "A1,37.000000,127.000000,속도위반,50,과속 위치,2025-01-01\n"
    "A1,37.000100,127.000000,,60,미분류 위치,2026-01-01\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2


def test_speed_camera_dataclass_contains_ui_fields(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로종류,설치장소\n"
    "A1,37.001,127.0,속도위반,80,고속국도,전방도로\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.camera_category == "SPEED"
  assert camera.camera_type_code == 1
  assert camera.road_class == "EXPRESSWAY"
  assert camera.road_class_code == 1
  assert camera.is_expressway is True
  assert camera.is_national_road is False
  assert camera.osm_road_name == ""
  assert camera.osm_road_ref == ""


def test_create_database_enriches_camera_osm_road_name(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  _build_test_osm_roads_db(osm_db_path)
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.004,127.0,01,80,Public DB Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csvs([CsvSource(csv_path, "public")], db_path, osm_roads_db_path=osm_db_path) == 1

  row = _fetch_row(db_path, "A1")
  assert row["osm_road_name"] == "Current Road"
  assert row["osm_road_ref"] == "E1"
  assert row["osm_road_match_dist_m"] < 5.0

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, current_road_name="Current Road")
  assert camera is not None
  assert camera.local_road_match
  assert camera.osm_road_name == "Current Road"


def test_osm_enriched_road_name_prioritizes_camera_with_mismatched_public_name(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  _build_test_osm_roads_db(osm_db_path)
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.002,127.001,01,80,Current Road\n"
    "A2,37.004,127.0,01,80,Public DB Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csvs([CsvSource(csv_path, "public")], db_path, osm_roads_db_path=osm_db_path) == 2

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, current_road_name="Current Road")
  assert camera is not None
  assert camera.id.startswith("A2-")
  assert camera.road_name == "Public DB Road"
  assert camera.osm_road_name == "Current Road"
  assert camera.local_road_match


def test_init_db_backfills_old_database_speed_flags(tmp_path: Path) -> None:
  db_path = tmp_path / "old_speed_cameras.sqlite3"
  with sqlite3.connect(db_path) as conn:
    conn.executescript("""
      CREATE TABLE metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
      INSERT INTO metadata(key, value) VALUES('version', '2');

      CREATE TABLE speed_cameras (
        id TEXT PRIMARY KEY,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        camera_type TEXT NOT NULL,
        speed_limit INTEGER NOT NULL,
        region TEXT NOT NULL,
        road_name TEXT NOT NULL,
        place TEXT NOT NULL,
        direction TEXT NOT NULL,
        section_type TEXT NOT NULL,
        section_length_m INTEGER NOT NULL,
        school_zone TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
      INSERT INTO speed_cameras VALUES (
        'OLD', 37.001, 127.0, '01', 80, '', '고속도로', '전방도로', '', '', 0, '', '2026-01-01'
      );
      INSERT INTO speed_cameras VALUES (
        'OLD_PROTECTED', 37.002, 127.0, '04', 0, '', '칠중1길', '마지초등학교 정문 앞', '', '', 0, '', '2026-01-01'
      );
    """)
    speed_camera.init_db(conn)
    protected = conn.execute("SELECT speed_limit, camera_category FROM speed_cameras WHERE id = 'OLD_PROTECTED'").fetchone()

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.id == "OLD"
  assert camera.camera_category == "SPEED"
  assert camera.camera_type_code == 1
  assert camera.road_class == "EXPRESSWAY"
  assert camera.is_expressway is True
  assert protected == (30, "PROTECTED_ZONE")


def test_init_db_removes_legacy_camera_type_raw_column(tmp_path: Path) -> None:
  db_path = tmp_path / "legacy_raw_speed_cameras.sqlite3"
  with sqlite3.connect(db_path) as conn:
    conn.executescript("""
      CREATE TABLE metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
      INSERT INTO metadata(key, value) VALUES('version', '10');

      CREATE TABLE speed_cameras (
        id TEXT PRIMARY KEY,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        camera_type TEXT NOT NULL,
        camera_type_raw TEXT NOT NULL,
        speed_limit INTEGER NOT NULL,
        region TEXT NOT NULL,
        road_name TEXT NOT NULL,
        place TEXT NOT NULL,
        direction TEXT NOT NULL,
        section_type TEXT NOT NULL,
        section_length_m INTEGER NOT NULL,
        school_zone TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
      INSERT INTO speed_cameras VALUES (
        'LEGACY_RAW', 37.001, 127.0, '01', '01', 80, '', '고속도로', '전방도로', '03', '01', 0, '02', '2026-01-01'
      );
    """)

    speed_camera.init_db(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(speed_cameras)")}
    row = conn.execute("""
      SELECT camera_type, direction, section_type, school_zone, camera_category
      FROM speed_cameras
      WHERE id = 'LEGACY_RAW'
    """).fetchone()

  assert "camera_type_raw" not in columns
  assert row == ("1", "3", "1", "2", "SPEED")


def test_camera_type_code_backward_compatibility() -> None:
  assert camera_type_code("속도위반") == 1
  assert camera_type_code("신호위반") == 2
  assert camera_type_code("신호+속도위반") == 3
  assert camera_type_code("구간단속") == 4
  assert camera_type_code("01") == 1
  assert camera_type_code("02") == 2
  assert camera_type_code("02", speed_limit=30) == 3
  assert camera_type_code("1") == 1
  assert camera_type_code("2") == 2
  assert camera_type_code("2", speed_limit=50) == 3
  assert camera_type_code("3") == 8
  assert camera_type_code("03") == 8
  assert camera_type_code("4") == 10
  assert camera_type_code("04") == 10


def test_camera_direction_filter(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로노선방향\n"
    "A1,37.001,127.0,속도위반,80,남\n"
    "A2,37.002,127.0,속도위반,60,북\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.id.startswith("A2-")

  permissive_camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, camera_direction_angle_deg=181.0)
  assert permissive_camera is not None
  assert permissive_camera.id.startswith("A1-")


def test_numeric_road_direction_codes_are_not_absolute_bearings(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로노선방향,설치장소\n"
    "A1,37.001,127.0,속도위반,80,01,상행 후보\n"
    "A2,37.002,127.0,속도위반,60,02,하행 후보\n"
    "A3,37.003,127.0,속도위반,50,03,양방향 후보\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 3

  with sqlite3.connect(db_path) as conn:
    directions = [row[0] for row in conn.execute("SELECT direction FROM speed_cameras ORDER BY id")]
  assert directions == ["1", "2", "3"]

  cameras = find_lead_cameras(db_path, 37.0, 127.0, 0.0, limit=3)
  assert [camera.direction_kind for camera in cameras] == ["UP", "DOWN", "BOTH"]


def test_db_code_columns_normalize_leading_zero_codes(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로노선방향,단속구간위치구분,보호구역구분,설치장소\n"
    "B1,37.001,127.0,01+02,60,03,01,02,복합 코드 후보\n"
    "B2,37.002,127.0,04,0,01,,01,초등학교 보호구역 후보\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  with sqlite3.connect(db_path) as conn:
    rows = conn.execute("""
      SELECT camera_type, direction, section_type, school_zone
      FROM speed_cameras
      ORDER BY id
    """).fetchall()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(speed_cameras)")}
  assert rows == [
    ("1+2", "3", "1", "2"),
    ("4", "1", "", "1"),
  ]
  assert "camera_type_raw" not in columns


def test_lateral_offset_filter_removes_side_road_camera(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로노선방향,설치장소\n"
    "A1,37.0045,127.0028,속도위반,80,3,옆도로 후보\n"
    "A2,37.0050,127.0000,속도위반,60,3,진행축 후보\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  cameras = find_lead_cameras(db_path, 37.0, 127.0, 0.0, limit=3)
  assert len(cameras) == 1
  assert cameras[0].id.startswith("A2-")
  assert cameras[0].forward_m > 0.0
  assert abs(cameras[0].side_m) < 1.0


def test_direction_bearing_deg() -> None:
  assert direction_bearing_deg("북") == 0.0
  assert direction_bearing_deg("동") == 90.0
  assert direction_bearing_deg("남") == 180.0
  assert direction_bearing_deg("서") == 270.0
  assert direction_bearing_deg("1") is None
  assert direction_bearing_deg("02") is None
  assert direction_bearing_deg("양방향") is None


def test_direction_kind_and_route_hint_helpers() -> None:
  assert direction_kind("1") == "UP"
  assert direction_kind("01") == "UP"
  assert direction_kind("2") == "DOWN"
  assert direction_kind("02") == "DOWN"
  assert direction_kind("3") == "BOTH"
  assert direction_kind("03") == "BOTH"
  assert direction_kind("북") == ""
  assert route_hint_from_text("중원초교사거리 어린이보호구역(부천체육관→부천시청역)") == "부천체육관->부천시청역"
  assert route_hint_from_text("포도마을사거리(부천시청역->순천향대학교부천병원)") == "부천시청역->순천향대학교부천병원"


def test_normalize_direction_for_db() -> None:
  assert normalize_code_for_db("01+02") == "1+2"
  assert normalize_code_for_db("01/02") == "1/2"
  assert normalize_direction_for_db("01") == "1"
  assert normalize_direction_for_db("1") == "1"
  assert normalize_direction_for_db("02") == "2"
  assert normalize_direction_for_db("2") == "2"
  assert normalize_direction_for_db("03") == "3"
  assert normalize_direction_for_db("3") == "3"
  assert normalize_direction_for_db("북") == "북"


def test_relative_projection_m() -> None:
  forward_m, side_m = relative_projection_m(100.0, 0.0)
  assert forward_m == pytest.approx(100.0)
  assert side_m == pytest.approx(0.0)
  forward_m, side_m = relative_projection_m(100.0, 90.0)
  assert forward_m == pytest.approx(0.0, abs=1e-6)
  assert side_m == pytest.approx(100.0)


def test_public_data_portal_column_codes(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM,ITLPC,REFERENCE_DATE\n"
    "J0071,35.765665,128.13621,01,40,일천로,일천삼거리,2026-01-29\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 1

  camera = find_lead_camera(db_path, 35.764665, 128.13621, 0.0)
  assert camera is not None
  assert camera.id.startswith("J0071-")
  assert camera.speed_limit == 40
  assert camera.camera_type == "1"
  with sqlite3.connect(db_path) as conn:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(speed_cameras)")}
  assert "camera_type_raw" not in columns
  assert database_data_date(db_path) == "2026-01-29"


def test_find_lead_camera_prioritizes_local_road_match_within_speed_category(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.001,127.0,01,80,Other Road\n"
    "A2,37.002,127.0,01,80,Current Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, current_road_name="Current Road")
  assert camera is not None
  assert camera.id.startswith("A2-")
  assert camera.local_road_match


def test_find_lead_camera_prioritizes_forward_road_match_within_speed_category(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.001,127.002,01,80,Current Road\n"
    "A2,37.002,127.000,01,80,Other Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  cameras = find_lead_cameras(db_path, 37.0, 127.0, 0.0, max_angle_deg=75.0, current_road_name="Current Road", limit=2)
  assert len(cameras) == 2
  assert cameras[0].id.startswith("A2-")
  assert cameras[0].forward_road_match
  assert not cameras[1].forward_road_match
  assert cameras[1].local_road_match


def test_find_lead_camera_keeps_speed_category_ahead_of_local_road_signal(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.001,127.0,02,0,Current Road\n"
    "A2,37.002,127.0,01,80,Other Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, current_road_name="Current Road")
  assert camera is not None
  assert camera.id.startswith("A2-")
  assert not camera.local_road_match


def test_osm_context_does_not_extend_camera_lookahead_distance(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  _build_test_osm_roads_db(osm_db_path)
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.020,127.000,01,80,Current Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  osm_segments = forward_road_segments(osm_db_path, 37.0, 127.0, 0.0, -100.0, 3000.0, 70.0, 140.0, 100)

  assert find_lead_camera(db_path, 37.0, 127.0, 0.0, max_distance_m=500.0, osm_road_segments=osm_segments) is None


def test_osm_context_prioritizes_camera_on_cached_forward_road(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  _build_test_osm_roads_db(osm_db_path)
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.002,127.000,01,80,Current Road\n"
    "A2,37.001,127.000,01,80,Side Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 2
  osm_segments = forward_road_segments(osm_db_path, 37.0, 127.0, 0.0, -100.0, 3000.0, 70.0, 140.0, 100)

  cameras = find_lead_cameras(db_path, 37.0, 127.0, 0.0, limit=2, osm_road_segments=osm_segments)

  assert cameras[0].id.startswith("A1-")
  assert cameras[0].local_road_match
  assert cameras[0].osm_corridor_match


def test_osm_context_beats_local_forward_match_within_speed_category(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  with sqlite3.connect(osm_db_path) as conn:
    insert_road_segments(conn, [{
      "osm_id": 301,
      "name": "Predicted Road",
      "ref": "",
      "highway": "primary",
      "road_class": "NATIONAL_ROAD",
      "oneway": 1,
      "lat1": 37.0000,
      "lon1": 127.0015,
      "lat2": 37.0100,
      "lon2": 127.0015,
    }])
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.001,126.9995,01,80,Current Road\n"
    "A2,37.002,127.0015,01,80,Predicted Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 2
  osm_segments = forward_road_segments(osm_db_path, 37.0, 127.0, 0.0, -100.0, 3000.0, 70.0, 140.0, 100)

  cameras = find_lead_cameras(
    db_path,
    37.0,
    127.0,
    0.0,
    current_road_name="Current Road",
    osm_road_segments=osm_segments,
    limit=2,
  )

  assert len(cameras) == 2
  assert cameras[0].id.startswith("A2-")
  assert cameras[0].osm_corridor_match
  assert cameras[0].osm_direction_source == "OSM_ONEWAY"
  assert cameras[1].id.startswith("A1-")
  assert cameras[1].forward_road_match


def test_osm_direction_prediction_uses_oneway_bearing(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  _build_single_osm_road_db(osm_db_path, oneway=1)
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.002,127.000,01,80,Current Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  osm_segments = forward_road_segments(osm_db_path, 37.0, 127.0, 0.0, -100.0, 3000.0, 70.0, 140.0, 100)

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, osm_road_segments=osm_segments)

  assert camera is not None
  assert camera.osm_direction_source == "OSM_ONEWAY"
  assert camera.osm_predicted_bearing_deg == pytest.approx(0.0)
  assert camera.osm_direction_confidence >= camera_road_context.OSM_DIRECTION_ONEWAY_CONFIDENCE


def test_osm_direction_prediction_uses_reverse_oneway_bearing(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  _build_single_osm_road_db(osm_db_path, oneway=-1)
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,37.002,127.000,01,80,Current Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  osm_segments = forward_road_segments(osm_db_path, 37.0, 127.0, 0.0, -100.0, 3000.0, 70.0, 140.0, 100)

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, osm_road_segments=osm_segments)

  assert camera is not None
  assert camera.osm_direction_source == "OSM_ONEWAY"
  assert camera.osm_predicted_bearing_deg == pytest.approx(180.0)
  assert camera.osm_direction_heading_diff_deg == pytest.approx(180.0)


def test_osm_bidirectional_prediction_chooses_heading_with_lower_confidence(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  _build_single_osm_road_db(osm_db_path, oneway=0, lat1=36.9900, lat2=37.0000)
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM\n"
    "A1,36.998,127.000,01,80,Current Road\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  osm_segments = forward_road_segments(osm_db_path, 37.0, 127.0, 180.0, -100.0, 3000.0, 70.0, 140.0, 100)

  camera = find_lead_camera(db_path, 37.0, 127.0, 180.0, osm_road_segments=osm_segments)

  assert camera is not None
  assert camera.osm_direction_source == "OSM_BIDIRECTIONAL_HEADING"
  assert camera.osm_predicted_bearing_deg == pytest.approx(180.0)
  assert camera.osm_direction_confidence < camera_road_context.OSM_DIRECTION_ONEWAY_CONFIDENCE


def test_db_direction_prediction_takes_precedence_over_osm(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  osm_db_path = tmp_path / "osm_roads.sqlite3"
  _build_single_osm_road_db(osm_db_path, oneway=-1)
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM,ROAD_ROUTE_DRC\n"
    "A1,37.002,127.000,01,80,Current Road,북\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 1
  osm_segments = forward_road_segments(osm_db_path, 37.0, 127.0, 0.0, -100.0, 3000.0, 70.0, 140.0, 100)

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, osm_road_segments=osm_segments)

  assert camera is not None
  assert camera.osm_direction_source == "DB_DIRECTION"
  assert camera.osm_predicted_bearing_deg == pytest.approx(0.0)
  assert camera.osm_direction_confidence == pytest.approx(1.0)


def test_region_counts_from_address(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  _write_csv(
    csv_path,
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,소재지도로명주소,소재지지번주소,데이터기준일자\n"
    "A1,37.001,127.0,속도위반,80,서울특별시 강남구 테헤란로,,2026-01-01\n"
    "A2,36.999,127.0,속도위반,60,서울시 서초구 반포대로,,2026-02-01\n"
    "A3,35.001,128.0,신호위반,50,,경상남도 창원시 성산구,2026-03-01\n"
    "A4,35.002,128.0,속도위반,50,,주소없음,2026-04-01\n",
  )

  assert create_database_from_csv(csv_path, db_path) == 4
  assert database_region_counts(db_path) == [
    ("서울특별시", 2),
    ("미분류", 1),
  ]
  assert database_region_stats(db_path) == [
    ("서울특별시", 2, 2, "2026-02-01"),
    ("미분류", 1, 1, "2026-04-01"),
    ("경상남도", 1, 0, "2026-03-01"),
  ]
  assert database_category_counts(db_path) == [
    ("SPEED", 3),
    ("SIGNAL", 1),
  ]


def test_database_summary_helpers_handle_unopenable_path(tmp_path: Path) -> None:
  db_path = tmp_path / "not_a_database.sqlite3"
  db_path.mkdir()

  assert database_data_date(db_path) == ""
  assert database_category_counts(db_path) == []
  assert database_region_counts(db_path) == []
  assert database_region_stats(db_path) == []


def test_download_public_speed_camera_csv(tmp_path: Path, monkeypatch) -> None:
  def fake_fetch(path: str, params: dict, timeout: int = speed_camera.DATA_GO_KR_TIMEOUT_SECONDS):
    if path.endswith("columList.json"):
      return {
        "totalCount": 2,
        "fileName": "전국무인교통단속카메라표준데이터",
        "columList": [
          {"columCode": "MNLSS_REGLT_CAMERA_MANAGE_NO", "columNm": "무인교통단속카메라관리번호"},
          {"columCode": "LATITUDE", "columNm": "위도"},
          {"columCode": "LONGITUDE", "columNm": "경도"},
          {"columCode": "REGLT_SE", "columNm": "단속구분"},
          {"columCode": "LMTT_VE", "columNm": "제한속도"},
          {"columCode": "ITLPC", "columNm": "설치장소"},
        ],
        "tableVO": {
          "colNmList": ["MNLSS_REGLT_CAMERA_MANAGE_NO", "LATITUDE", "LONGITUDE", "REGLT_SE", "LMTT_VE", "ITLPC"],
          "svcTableNm": "tn_pubr_public_unmanned_traffic_camera_svc",
        },
      }
    assert path.endswith("standard.json")
    assert params["page"] == 1
    return [
      {
        "MNLSS_REGLT_CAMERA_MANAGE_NO": "J0071",
        "LATITUDE": "35.765665",
        "LONGITUDE": "128.13621",
        "REGLT_SE": "01",
        "LMTT_VE": "40",
        "ITLPC": "일천삼거리",
      },
      {
        "MNLSS_REGLT_CAMERA_MANAGE_NO": "J0070",
        "LATITUDE": "35.7655683",
        "LONGITUDE": "128.1360521",
        "REGLT_SE": "01",
        "LMTT_VE": "60",
        "ITLPC": "일천삼거리",
      },
    ]

  monkeypatch.setattr(speed_camera, "_fetch_data_go_json", fake_fetch)

  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  progress = []

  assert download_public_speed_camera_csv(
    csv_path,
    per_page=10000,
    progress_callback=lambda written, total: progress.append((written, total)),
  ) == 2
  assert create_database_from_csv(csv_path, db_path) == 2
  assert progress == [(0, 2), (2, 2)]
