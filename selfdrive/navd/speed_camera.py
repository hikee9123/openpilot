#!/usr/bin/env python3
import csv
import json
import math
import os
import re
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, find_current_road, road_name_matches
except ModuleNotFoundError:
  from selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, find_current_road, road_name_matches


DB_VERSION = 6
PUBLIC_DATA_PK = "15028200"
PUBLIC_DATA_BASE_URL = "https://www.data.go.kr"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def _default_data_root() -> Path:
  if "SPEED_CAMERA_ROOT" in os.environ:
    return Path(os.environ["SPEED_CAMERA_ROOT"])
  return DEFAULT_DATA_DIR


DEFAULT_DB_PATH = _default_data_root() / "speed_cameras.sqlite3"
DEFAULT_CSV_PATH = _default_data_root() / "speed_cameras.csv"
DEFAULT_REGION_DIR = _default_data_root() / "region"

LOOKAHEAD_DISTANCE_M = 2500.0
LOOKAHEAD_ANGLE_DEG = 45.0
CAMERA_DIRECTION_ANGLE_DEG = 70.0
MANAGE_NO_DEDUP_DISTANCE_M = 50.0
EARTH_RADIUS_M = 6371000.0
DATA_GO_KR_TIMEOUT_SECONDS = 30
DATA_GO_KR_RETRY_COUNT = 3
DATA_GO_KR_USER_AGENT = "Mozilla/5.0 (openpilot speed camera updater)"


FIELD_ALIASES = {
  "id": (
    "무인교통단속카메라관리번호",
    "무인교통단속카메라 관리번호",
    "관리번호",
    "MNLSS_REGLT_CAMERA_MANAGE_NO",
    "manage_no",
    "camera_id",
    "id",
  ),
  "lat": ("위도", "LATITUDE", "lat", "latitude"),
  "lon": ("경도", "LONGITUDE", "lon", "lng", "longitude"),
  "camera_type": (
    "단속구분",
    "단속유형",
    "단속종류",
    "REGLT_SE",
    "regltSe",
    "camera_type",
    "type",
  ),
  "speed_limit": ("제한속도", "제한속도(km/h)", "LMTT_VE", "lmttVe", "speed_limit"),
  "region": ("시도명", "시도", "CTPRVN_NM", "SIDO_NM", "region", "sido"),
  "road_type": (
    "도로종류",
    "도로구분",
    "도로유형",
    "ROAD_KND",
    "roadKnd",
    "road_knd",
    "road_type",
  ),
  "road_name": ("도로노선명", "소재지도로명주소", "도로명", "ROAD_ROUTE_NM", "RDNMADR", "road_name"),
  "place": ("설치장소", "소재지지번주소", "ITLPC", "LNMADR", "place"),
  "direction": ("도로노선방향", "방향", "ROAD_ROUTE_DRC", "direction"),
  "section_type": ("단속구간위치구분", "REGLT_SCTN_LC_SE", "section_type"),
  "section_length_m": ("과속단속구간길이", "과속단속구간길이(m)", "OVRSPD_REGLT_SCTN_LT", "section_length_m"),
  "school_zone": ("보호구역구분", "PRTCAREA_TYPE", "school_zone"),
  "updated_at": ("데이터기준일자", "최종수정일", "REFERENCE_DATE", "updated_at"),
}

REGION_ALIASES = {
  "강원": "강원특별자치도",
  "강원도": "강원특별자치도",
  "강원특별자치도": "강원특별자치도",
  "경기": "경기도",
  "경기도": "경기도",
  "경남": "경상남도",
  "경상남도": "경상남도",
  "경북": "경상북도",
  "경상북도": "경상북도",
  "광주": "광주광역시",
  "광주광역시": "광주광역시",
  "대구": "대구광역시",
  "대구광역시": "대구광역시",
  "대전": "대전광역시",
  "대전광역시": "대전광역시",
  "부산": "부산광역시",
  "부산광역시": "부산광역시",
  "서울": "서울특별시",
  "서울시": "서울특별시",
  "서울특별시": "서울특별시",
  "세종": "세종특별자치시",
  "세종시": "세종특별자치시",
  "세종특별자치시": "세종특별자치시",
  "울산": "울산광역시",
  "울산광역시": "울산광역시",
  "인천": "인천광역시",
  "인천광역시": "인천광역시",
  "전남": "전라남도",
  "전라남도": "전라남도",
  "전북": "전북특별자치도",
  "전라북도": "전북특별자치도",
  "전북특별자치도": "전북특별자치도",
  "제주": "제주특별자치도",
  "제주도": "제주특별자치도",
  "제주특별자치도": "제주특별자치도",
  "충남": "충청남도",
  "충청남도": "충청남도",
  "충북": "충청북도",
  "충청북도": "충청북도",
}

CAMERA_CATEGORY_CODES = {
  "ETC": 0,
  "SPEED": 1,
  "SIGNAL": 2,
  "SPEED_SIGNAL": 3,
  "SECTION_SPEED": 4,
  "PARKING": 5,
  "BUS_LANE": 6,
  "TRAFFIC": 7,
  "SECURITY": 8,
  "UNKNOWN": 9,
  "PROTECTED_ZONE": 10,
}

ROAD_CLASS_CODES = {
  "UNKNOWN": 0,
  "EXPRESSWAY": 1,
  "NATIONAL_ROAD": 2,
  "NATIONAL_LOCAL_ROAD": 3,
  "LOCAL_ROAD": 4,
  "CITY_ROAD": 5,
  "COUNTY_ROAD": 6,
  "DISTRICT_ROAD": 7,
  "ETC": 8,
}

SOURCE_TYPE_PRIORITY = {
  "public": 1,
  "region": 2,
  "custom": 3,
}

SPEED_CAMERA_COLUMNS = (
  "id",
  "lat",
  "lon",
  "camera_type",
  "camera_type_raw",
  "camera_category",
  "camera_type_code",
  "is_speed_camera",
  "is_signal_camera",
  "is_section_camera",
  "is_etc_camera",
  "speed_limit",
  "region",
  "road_type_raw",
  "road_class",
  "road_class_code",
  "is_expressway",
  "is_national_road",
  "road_name",
  "place",
  "direction",
  "section_type",
  "section_length_m",
  "school_zone",
  "updated_at",
  "source_type",
  "source_file",
  "dedup_key",
  "osm_road_name",
  "osm_road_ref",
  "osm_road_match_dist_m",
  "osm_road_match_heading_deg",
)


@dataclass(frozen=True)
class CsvSource:
  path: Path
  source_type: str


@dataclass(frozen=True)
class SpeedCamera:
  id: str
  lat: float
  lon: float
  camera_type: str
  speed_limit: int
  road_name: str
  place: str
  direction: str
  section_type: str
  section_length_m: int
  distance_m: float = 0.0
  bearing_deg: float = 0.0
  angle_diff_deg: float = 0.0
  relative_angle_deg: float = 0.0
  camera_category: str = "UNKNOWN"
  camera_type_code: int = 0
  region: str = ""
  road_type_raw: str = ""
  road_class: str = "UNKNOWN"
  road_class_code: int = 0
  is_expressway: bool = False
  is_national_road: bool = False
  source_type: str = ""
  source_file: str = ""
  osm_road_name: str = ""
  osm_road_ref: str = ""
  osm_road_match_dist_m: float = 0.0
  osm_road_match_heading_deg: float = 0.0
  local_road_match: bool = False


@dataclass(frozen=True)
class OsmRoadEnrichmentStats:
  total_count: int = 0
  matched_count: int = 0
  unmatched_count: int = 0
  unmatched_by_category: tuple[tuple[str, int], ...] = ()

  @property
  def match_percent(self) -> int:
    if self.total_count <= 0:
      return 0
    return int(round(self.matched_count * 100 / self.total_count))


def _first(row: dict[str, str], field: str) -> str:
  aliases = FIELD_ALIASES[field]
  for key in aliases:
    if key in row and row[key] is not None:
      return row[key].strip()

  lower_aliases = {key.lower() for key in aliases}
  for key, value in row.items():
    if key is not None and key.strip().lower() in lower_aliases and value is not None:
      return value.strip()
  return ""


def _parse_float(value: str) -> float | None:
  try:
    return float(value.replace(",", ""))
  except (AttributeError, ValueError):
    return None


def _parse_int(value: str) -> int:
  parsed = _parse_float(value)
  return int(parsed) if parsed is not None else 0


def _normalize_region(value: str) -> str:
  token = value.strip().split()[0] if value else ""
  return REGION_ALIASES.get(token, "")


def _extract_region(row: dict[str, str]) -> str:
  direct_region = _normalize_region(_first(row, "region"))
  if direct_region:
    return direct_region

  for field in ("road_name", "place"):
    region = _normalize_region(_first(row, field))
    if region:
      return region
  return "미분류"


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
  for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
    try:
      with csv_path.open("r", encoding=encoding, newline="") as f:
        return list(csv.DictReader(f))
    except UnicodeDecodeError:
      continue
  with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
    return list(csv.DictReader(f))


def normalize_camera_category(
  camera_type: str,
  section_type: str = "",
  context_text: str = "",
  speed_limit: int = 0,
) -> str:
  camera_type = (camera_type or "").strip()
  section_type = (section_type or "").strip()
  context_text = (context_text or "").strip()
  raw = f"{camera_type} {section_type}".strip()
  context_raw = f"{raw} {context_text}".strip()
  context_compact = context_raw.replace(" ", "")
  compact = raw.replace(" ", "").upper()

  if not raw:
    return "UNKNOWN"

  if camera_type in ("03", "3"):
    return "SECURITY"

  if camera_type in ("04", "4"):
    return "PROTECTED_ZONE"

  has_speed = (
    camera_type in ("01", "1") or
    compact in ("01+02", "1+2", "01/02", "1/02", "01/2") or
    "과속" in raw or
    "속도" in raw or
    "SPEED" in compact
  )

  has_signal = (
    camera_type in ("02", "2") or
    compact in ("01+02", "1+2", "01/02", "1/02", "01/2") or
    "신호" in raw or
    "SIGNAL" in compact
  )

  has_section = (
    (camera_type == "99" and section_type in ("01", "1", "02", "2")) or
    (camera_type == "99" and any(keyword in context_raw for keyword in ("구간", "시점", "종점"))) or
    (camera_type == "99" and "어린이보호구역" in context_compact) or
    (camera_type == "99" and speed_limit == 30 and "초등학교" in context_compact) or
    "구간" in raw or
    "SECTION" in compact
  )

  if has_section:
    return "SECTION_SPEED"

  if has_speed and has_signal:
    return "SPEED_SIGNAL"

  if has_speed:
    return "SPEED"

  if has_signal:
    return "SIGNAL"

  if "주정차" in raw or "불법주정차" in raw or "주차" in raw or "정차" in raw:
    return "PARKING"

  if "버스전용" in raw or "버스차로" in raw or "버스" in raw:
    return "BUS_LANE"

  if "통행" in raw or "진입" in raw or "교차로" in raw or "꼬리" in raw or "끼어들기" in raw:
    return "TRAFFIC"

  if "방범" in raw or "CCTV" in compact:
    return "SECURITY"

  if "기타" in raw or compact == "ETC":
    return "ETC"

  return "UNKNOWN"


def camera_category_code(camera_category: str) -> int:
  return CAMERA_CATEGORY_CODES.get(camera_category, 0)


def is_speed_category(camera_category: str) -> bool:
  return camera_category in ("SPEED", "SPEED_SIGNAL", "SECTION_SPEED")


def is_signal_category(camera_category: str) -> bool:
  return camera_category in ("SIGNAL", "SPEED_SIGNAL")


def is_section_category(camera_category: str) -> bool:
  return camera_category == "SECTION_SPEED"


def is_etc_category(camera_category: str) -> bool:
  return camera_category not in ("SPEED", "SIGNAL", "SPEED_SIGNAL", "SECTION_SPEED")


def _is_alertable_category(camera_category: str) -> bool:
  return (
    is_speed_category(camera_category) or
    is_signal_category(camera_category) or
    camera_category in ("SECURITY", "PROTECTED_ZONE")
  )


def same_corridor_likely(camera: "SpeedCamera") -> bool:
  angle = abs(camera.relative_angle_deg)
  if angle <= 15.0:
    return True
  if camera.is_expressway and angle <= 25.0:
    return True
  return False


def _alert_priority(camera: "SpeedCamera") -> tuple[int, int, int, float, float]:
  return (
    0 if is_speed_category(camera.camera_category) else 1,
    0 if camera.local_road_match else 1,
    0 if same_corridor_likely(camera) else 1,
    camera.distance_m,
    abs(camera.relative_angle_deg),
  )


def camera_type_code(camera_type: str, section_type: str = "") -> int:
  category = normalize_camera_category(camera_type, section_type)
  return camera_category_code(category)


def normalize_road_class(road_type: str, road_name: str = "", place: str = "") -> str:
  raw = f"{road_type or ''} {road_name or ''} {place or ''}".strip()
  compact = raw.replace(" ", "").upper()

  if not raw:
    return "UNKNOWN"

  if "고속국도" in raw or "고속도로" in raw or "고속" in raw:
    return "EXPRESSWAY"

  if "일반국도" in raw or "국도" in raw:
    return "NATIONAL_ROAD"

  if "국가지원지방도" in raw or "국지도" in raw:
    return "NATIONAL_LOCAL_ROAD"

  if "지방도" in raw:
    return "LOCAL_ROAD"

  if "특별시도" in raw or "특별광역시도" in raw or "시도" in raw:
    return "CITY_ROAD"

  if "군도" in raw:
    return "COUNTY_ROAD"

  if "구도" in raw:
    return "DISTRICT_ROAD"

  if "기타" in raw or compact == "ETC":
    return "ETC"

  return "UNKNOWN"


def road_class_code(road_class: str) -> int:
  return ROAD_CLASS_CODES.get(road_class, 0)


def is_expressway_class(road_class: str) -> bool:
  return road_class == "EXPRESSWAY"


def is_national_road_class(road_class: str) -> bool:
  return road_class == "NATIONAL_ROAD"


def build_dedup_key(
  row: dict[str, str],
  lat: float,
  lon: float,
  speed_limit: int,
  camera_category: str,
  road_class: str,
  region: str,
  place: str,
  fallback_id: str,
) -> str:
  manage_no = _first(row, "id")
  if manage_no:
    return f"NO|{manage_no}"

  if lat is not None and lon is not None:
    return f"GPS|{lat:.6f}|{lon:.6f}|{speed_limit}|{camera_category}|{road_class}"

  if region and place:
    return f"LOC|{region}|{place}|{speed_limit}|{camera_category}|{road_class}"

  return f"ROW|{fallback_id}"


def init_db(conn: sqlite3.Connection, backfill: bool = True) -> None:
  conn.executescript("""
    CREATE TABLE IF NOT EXISTS metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS speed_cameras (
      id TEXT PRIMARY KEY,
      lat REAL NOT NULL,
      lon REAL NOT NULL,
      camera_type TEXT NOT NULL,
      camera_type_raw TEXT NOT NULL,
      camera_category TEXT NOT NULL,
      camera_type_code INTEGER NOT NULL,
      is_speed_camera INTEGER NOT NULL,
      is_signal_camera INTEGER NOT NULL,
      is_section_camera INTEGER NOT NULL,
      is_etc_camera INTEGER NOT NULL,
      speed_limit INTEGER NOT NULL,
      region TEXT NOT NULL,
      road_type_raw TEXT NOT NULL,
      road_class TEXT NOT NULL,
      road_class_code INTEGER NOT NULL,
      is_expressway INTEGER NOT NULL,
      is_national_road INTEGER NOT NULL,
      road_name TEXT NOT NULL,
      place TEXT NOT NULL,
      direction TEXT NOT NULL,
      section_type TEXT NOT NULL,
      section_length_m INTEGER NOT NULL,
      school_zone TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      source_type TEXT NOT NULL,
      source_file TEXT NOT NULL,
      dedup_key TEXT NOT NULL,
      osm_road_name TEXT NOT NULL,
      osm_road_ref TEXT NOT NULL,
      osm_road_match_dist_m REAL NOT NULL,
      osm_road_match_heading_deg REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS speed_camera_region_counts (
      region TEXT PRIMARY KEY,
      count INTEGER NOT NULL
    );
  """)

  column_defaults = {
    "region": "TEXT NOT NULL DEFAULT ''",
    "camera_type_raw": "TEXT NOT NULL DEFAULT ''",
    "camera_category": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
    "camera_type_code": "INTEGER NOT NULL DEFAULT 0",
    "is_speed_camera": "INTEGER NOT NULL DEFAULT 0",
    "is_signal_camera": "INTEGER NOT NULL DEFAULT 0",
    "is_section_camera": "INTEGER NOT NULL DEFAULT 0",
    "is_etc_camera": "INTEGER NOT NULL DEFAULT 0",
    "road_type_raw": "TEXT NOT NULL DEFAULT ''",
    "road_class": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
    "road_class_code": "INTEGER NOT NULL DEFAULT 0",
    "is_expressway": "INTEGER NOT NULL DEFAULT 0",
    "is_national_road": "INTEGER NOT NULL DEFAULT 0",
    "source_type": "TEXT NOT NULL DEFAULT 'public'",
    "source_file": "TEXT NOT NULL DEFAULT ''",
    "dedup_key": "TEXT NOT NULL DEFAULT ''",
    "osm_road_name": "TEXT NOT NULL DEFAULT ''",
    "osm_road_ref": "TEXT NOT NULL DEFAULT ''",
    "osm_road_match_dist_m": "REAL NOT NULL DEFAULT 0.0",
    "osm_road_match_heading_deg": "REAL NOT NULL DEFAULT 0.0",
  }
  columns = {row[1] for row in conn.execute("PRAGMA table_info(speed_cameras)")}
  for column, definition in column_defaults.items():
    if column not in columns:
      conn.execute(f"ALTER TABLE speed_cameras ADD COLUMN {column} {definition}")

  conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_speed_cameras_lat_lon
    ON speed_cameras(lat, lon);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_category
    ON speed_cameras(camera_category);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_type_code
    ON speed_cameras(camera_type_code);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_is_speed
    ON speed_cameras(is_speed_camera);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_is_signal
    ON speed_cameras(is_signal_camera);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_road_class
    ON speed_cameras(road_class);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_is_expressway
    ON speed_cameras(is_expressway);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_is_national_road
    ON speed_cameras(is_national_road);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_source
    ON speed_cameras(source_type);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_dedup
    ON speed_cameras(dedup_key);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_osm_road_name
    ON speed_cameras(osm_road_name);
  """)
  if backfill:
    _backfill_derived_columns(conn)
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("version", str(DB_VERSION)))
  conn.commit()


def _backfill_derived_columns(conn: sqlite3.Connection) -> None:
  rows = conn.execute("""
    SELECT
      id, lat, lon, camera_type, camera_type_raw, camera_category, camera_type_code,
      speed_limit, region, road_type_raw, road_class, road_name, place, section_type,
      source_type, source_file, dedup_key
    FROM speed_cameras
  """).fetchall()

  for row in rows:
    (
      camera_id,
      lat,
      lon,
      camera_type,
      camera_type_raw,
      camera_category,
      _stored_type_code,
      speed_limit,
      _region,
      road_type_raw,
      road_class,
      road_name,
      place,
      section_type,
      source_type,
      source_file,
      dedup_key,
    ) = row

    raw_camera_type = camera_type_raw or camera_type or ""
    category = normalize_camera_category(
      raw_camera_type, section_type or "", f"{road_name or ''} {place or ''}", int(speed_limit or 0)
    )
    type_code = camera_category_code(category)

    raw_road_type = road_type_raw or ""
    normalized_road_class = road_class or normalize_road_class(raw_road_type, road_name or "", place or "")
    if normalized_road_class == "UNKNOWN":
      normalized_road_class = normalize_road_class(raw_road_type, road_name or "", place or "")
    road_code = road_class_code(normalized_road_class)

    normalized_source_type = _source_type(source_type or "public")
    normalized_dedup_key = dedup_key or f"GPS|{float(lat):.6f}|{float(lon):.6f}|{int(speed_limit or 0)}"

    conn.execute("""
      UPDATE speed_cameras
      SET
        camera_type_raw = ?,
        camera_category = ?,
        camera_type_code = ?,
        is_speed_camera = ?,
        is_signal_camera = ?,
        is_section_camera = ?,
        is_etc_camera = ?,
        road_type_raw = ?,
        road_class = ?,
        road_class_code = ?,
        is_expressway = ?,
        is_national_road = ?,
        source_type = ?,
        source_file = ?,
        dedup_key = ?
      WHERE id = ?
    """, (
      raw_camera_type,
      category,
      type_code,
      int(is_speed_category(category)),
      int(is_signal_category(category)),
      int(is_section_category(category)),
      int(is_etc_category(category)),
      raw_road_type,
      normalized_road_class,
      road_code,
      int(is_expressway_class(normalized_road_class)),
      int(is_national_road_class(normalized_road_class)),
      normalized_source_type,
      source_file or "",
      normalized_dedup_key,
      camera_id,
    ))


def _date_priority(value: str) -> int:
  parts = [int(part) for part in re.findall(r"\d+", value or "")]
  if len(parts) >= 3:
    return parts[0] * 10000 + parts[1] * 100 + parts[2]
  if len(parts) == 1 and parts[0] > 9999999:
    return parts[0]
  return 0


def _source_type(source_type: str) -> str:
  normalized = (source_type or "custom").strip().lower()
  if normalized in SOURCE_TYPE_PRIORITY:
    return normalized
  return "custom"


def _merge_priority(record: dict[str, object]) -> tuple[int, int, int, int, int]:
  return (
    int(str(record["camera_category"]) != "UNKNOWN"),
    _date_priority(str(record["updated_at"])),
    SOURCE_TYPE_PRIORITY.get(str(record["source_type"]), 0),
    int(record["lat"] is not None and record["lon"] is not None),
    len(str(record["place"])),
  )


def _dedup_categories_are_compatible(
  record: dict[str, object],
  cluster: dict[str, object],
) -> bool:
  category = str(record["camera_category"])
  speed_limit = int(record["speed_limit"])
  cluster_categories = set(str(category) for category in cluster["categories"])
  cluster_speed_limits = set(int(speed_limit) for speed_limit in cluster["speed_limits"])
  non_unknown_categories = {cluster_category for cluster_category in cluster_categories if cluster_category != "UNKNOWN"}

  if category != "UNKNOWN":
    if non_unknown_categories and non_unknown_categories != {category}:
      return False
    if "UNKNOWN" not in cluster_categories:
      return True

  if category == "UNKNOWN" and len(non_unknown_categories) > 1:
    return False

  return cluster_speed_limits == {speed_limit}


def _dedup_road_class_is_compatible(
  record: dict[str, object],
  cluster: dict[str, object],
) -> bool:
  road_class = str(record["road_class"])
  cluster_road_classes = set(str(road_class) for road_class in cluster["road_classes"])
  return cluster_road_classes == {road_class}


def _manage_no_dedup_key(
  record: dict[str, object],
  manage_no_clusters: dict[str, list[dict[str, object]]],
) -> str | None:
  manage_no = str(record.get("_manage_no", ""))
  if not manage_no:
    return None

  lat = float(record["lat"])
  lon = float(record["lon"])
  clusters = manage_no_clusters.setdefault(manage_no, [])
  for cluster in clusters:
    distance = haversine_distance_m(lat, lon, float(cluster["lat"]), float(cluster["lon"]))
    if (
      distance <= MANAGE_NO_DEDUP_DISTANCE_M and
      _dedup_categories_are_compatible(record, cluster) and
      _dedup_road_class_is_compatible(record, cluster)
    ):
      cluster["categories"].add(str(record["camera_category"]))
      cluster["speed_limits"].add(int(record["speed_limit"]))
      cluster["road_classes"].add(str(record["road_class"]))
      return str(cluster["key"])

  key = (
    f"NO|{manage_no}|{str(record['camera_category'])}|"
    f"{int(record['speed_limit'])}|{str(record['road_class'])}|{lat:.6f}|{lon:.6f}"
  )
  clusters.append({
    "key": key,
    "lat": lat,
    "lon": lon,
    "categories": {str(record["camera_category"])},
    "speed_limits": {int(record["speed_limit"])},
    "road_classes": {str(record["road_class"])},
  })
  return key


def _standardize_csv_row(row: dict[str, str], csv_source: CsvSource, idx: int) -> dict[str, object] | None:
  lat = _parse_float(_first(row, "lat"))
  lon = _parse_float(_first(row, "lon"))
  if lat is None or lon is None:
    return None

  source_type = _source_type(csv_source.source_type)
  source_file = csv_source.path.name
  manage_no = _first(row, "id")
  raw_camera_id = manage_no or f"{source_type}-{csv_source.path.stem}-{idx}"
  camera_id = f"{raw_camera_id}-{lat:.7f}-{lon:.7f}"

  raw_road_type = _first(row, "road_type")
  road_name = _first(row, "road_name")
  place = _first(row, "place")
  speed_limit = _parse_int(_first(row, "speed_limit"))
  raw_camera_type = _first(row, "camera_type")
  section_type = _first(row, "section_type")
  category = normalize_camera_category(raw_camera_type, section_type, f"{road_name} {place}", speed_limit)
  type_code = camera_category_code(category)

  road_class = normalize_road_class(raw_road_type, road_name, place)
  road_code = road_class_code(road_class)
  region = _extract_region(row)
  fallback_id = f"{source_type}-{source_file}-{idx}"
  dedup_key = build_dedup_key(row, lat, lon, speed_limit, category, road_class, region, place, fallback_id)

  return {
    "id": camera_id,
    "lat": lat,
    "lon": lon,
    "camera_type": raw_camera_type,
    "camera_type_raw": raw_camera_type,
    "camera_category": category,
    "camera_type_code": type_code,
    "is_speed_camera": int(is_speed_category(category)),
    "is_signal_camera": int(is_signal_category(category)),
    "is_section_camera": int(is_section_category(category)),
    "is_etc_camera": int(is_etc_category(category)),
    "speed_limit": speed_limit,
    "region": region,
    "road_type_raw": raw_road_type,
    "road_class": road_class,
    "road_class_code": road_code,
    "is_expressway": int(is_expressway_class(road_class)),
    "is_national_road": int(is_national_road_class(road_class)),
    "road_name": road_name,
    "place": place,
    "direction": _first(row, "direction"),
    "section_type": section_type,
    "section_length_m": _parse_int(_first(row, "section_length_m")),
    "school_zone": _first(row, "school_zone"),
    "updated_at": _first(row, "updated_at"),
    "source_type": source_type,
    "source_file": source_file,
    "dedup_key": dedup_key,
    "osm_road_name": "",
    "osm_road_ref": "",
    "osm_road_match_dist_m": 0.0,
    "osm_road_match_heading_deg": 0.0,
    "_manage_no": manage_no,
  }


def create_database_from_csv(csv_path: Path = DEFAULT_CSV_PATH, db_path: Path = DEFAULT_DB_PATH) -> int:
  return create_database_from_csvs([CsvSource(csv_path, "public")], db_path)


def create_database_from_csvs(
  csv_sources: list[CsvSource],
  db_path: Path = DEFAULT_DB_PATH,
  osm_roads_db_path: Path | None = None,
  osm_lookup_radius_m: float = 60.0,
) -> int:
  merged: dict[str, dict[str, object]] = {}
  manage_no_clusters: dict[str, list[dict[str, object]]] = {}
  for csv_source in csv_sources:
    rows = _read_csv_rows(csv_source.path)
    for idx, row in enumerate(rows):
      record = _standardize_csv_row(row, csv_source, idx)
      if record is None:
        continue

      dedup_key = _manage_no_dedup_key(record, manage_no_clusters) or str(record["dedup_key"])
      record["dedup_key"] = dedup_key
      current = merged.get(dedup_key)
      if current is None or _merge_priority(record) > _merge_priority(current):
        merged[dedup_key] = record

  records = sorted(merged.values(), key=lambda record: str(record["id"]))
  db_path.parent.mkdir(parents=True, exist_ok=True)

  with closing(sqlite3.connect(db_path)) as conn:
    init_db(conn, backfill=False)
    conn.execute("DELETE FROM speed_cameras")

    placeholders = ", ".join("?" for _ in SPEED_CAMERA_COLUMNS)
    columns = ", ".join(SPEED_CAMERA_COLUMNS)
    conn.executemany(
      f"INSERT OR REPLACE INTO speed_cameras({columns}) VALUES ({placeholders})",
      [tuple(record[column] for column in SPEED_CAMERA_COLUMNS) for record in records],
    )

    conn.execute("DELETE FROM speed_camera_region_counts")
    conn.execute("""
      INSERT INTO speed_camera_region_counts(region, count)
      SELECT region, COUNT(*)
      FROM speed_cameras
      WHERE is_speed_camera = 1
      GROUP BY region
      ORDER BY region
    """)

    source_updated_at = ""
    if records:
      source_updated_at = str(max(records, key=lambda record: _date_priority(str(record["updated_at"])))["updated_at"])
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("source_updated_at", source_updated_at))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_enriched_count", "0"))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_db_path", ""))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("version", str(DB_VERSION)))
    conn.commit()
    if osm_roads_db_path is not None:
      enrich_speed_camera_osm_roads(conn, osm_roads_db_path, osm_lookup_radius_m)
    return conn.execute("SELECT COUNT(*) FROM speed_cameras").fetchone()[0]


def enrich_speed_camera_osm_roads(
  conn: sqlite3.Connection,
  osm_roads_db_path: Path = DEFAULT_OSM_ROADS_DB_PATH,
  lookup_radius_m: float = 60.0,
) -> int:
  if not osm_roads_db_path.exists():
    return 0

  init_db(conn, backfill=False)
  conn.row_factory = sqlite3.Row
  rows = conn.execute("""
    SELECT id, lat, lon, direction, road_name, place
    FROM speed_cameras
  """).fetchall()

  updates = []
  for row in rows:
    camera_direction = direction_bearing_deg(str(_row_get(row, "direction", "")))
    previous_name = f"{_row_get(row, 'road_name', '')} {_row_get(row, 'place', '')}"
    match = find_current_road(
      osm_roads_db_path,
      float(row["lat"]),
      float(row["lon"]),
      camera_direction,
      lookup_radius_m,
      previous_name=previous_name,
    )
    if match is None:
      continue
    updates.append((
      match.display_name,
      match.ref,
      float(match.distance_m),
      float(match.heading_diff_deg),
      row["id"],
    ))

  if not updates:
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_enriched_count", "0"))
    conn.commit()
    return 0

  conn.executemany("""
    UPDATE speed_cameras
    SET osm_road_name = ?,
        osm_road_ref = ?,
        osm_road_match_dist_m = ?,
        osm_road_match_heading_deg = ?
    WHERE id = ?
  """, updates)
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_enriched_count", str(len(updates))))
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_db_path", str(osm_roads_db_path)))
  conn.commit()
  return len(updates)


def database_data_date(db_path: Path = DEFAULT_DB_PATH) -> str:
  try:
    if not db_path.exists():
      return ""
  except OSError:
    return ""

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return ""

  with closing(conn):
    try:
      row = conn.execute("SELECT value FROM metadata WHERE key = ?", ("source_updated_at",)).fetchone()
      if row and row[0]:
        return str(row[0])
    except sqlite3.Error:
      pass

    try:
      row = conn.execute("SELECT MAX(updated_at) FROM speed_cameras").fetchone()
      return str(row[0] or "")
    except sqlite3.Error:
      return ""


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
  try:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
  except sqlite3.Error:
    return set()


def database_osm_road_enriched_count(db_path: Path = DEFAULT_DB_PATH) -> int:
  return database_osm_road_enrichment_stats(db_path).matched_count


def database_osm_road_enrichment_stats(db_path: Path = DEFAULT_DB_PATH) -> OsmRoadEnrichmentStats:
  try:
    if not db_path.exists():
      return OsmRoadEnrichmentStats()
  except OSError:
    return OsmRoadEnrichmentStats()

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return OsmRoadEnrichmentStats()

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if not {"osm_road_name", "osm_road_ref"}.issubset(columns):
      return OsmRoadEnrichmentStats()
    try:
      row = conn.execute("""
        SELECT
          COUNT(*) AS total_count,
          SUM(CASE WHEN COALESCE(osm_road_name, '') != '' OR COALESCE(osm_road_ref, '') != '' THEN 1 ELSE 0 END) AS matched_count
        FROM speed_cameras
      """).fetchone()
      total_count = int(row[0] if row else 0)
      matched_count = int(row[1] if row and row[1] is not None else 0)
    except (sqlite3.Error, TypeError, ValueError):
      return OsmRoadEnrichmentStats()

    unmatched_count = max(0, total_count - matched_count)
    unmatched_by_category: tuple[tuple[str, int], ...] = ()
    if unmatched_count > 0 and "camera_category" in columns:
      try:
        rows = conn.execute("""
          SELECT camera_category, COUNT(*)
          FROM speed_cameras
          WHERE COALESCE(osm_road_name, '') = '' AND COALESCE(osm_road_ref, '') = ''
          GROUP BY camera_category
          ORDER BY COUNT(*) DESC, camera_category
        """).fetchall()
        unmatched_by_category = tuple((str(category or "UNKNOWN"), int(count)) for category, count in rows)
      except (sqlite3.Error, TypeError, ValueError):
        unmatched_by_category = ()

    return OsmRoadEnrichmentStats(total_count, matched_count, unmatched_count, unmatched_by_category)


def database_region_counts(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int]]:
  try:
    if not db_path.exists():
      return []
  except OSError:
    return []

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return []

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if "is_speed_camera" in columns:
      try:
        rows = conn.execute("""
          SELECT region, COUNT(*)
          FROM speed_cameras
          WHERE is_speed_camera = 1
          GROUP BY region
          ORDER BY COUNT(*) DESC, region
        """).fetchall()
        if rows:
          return [(str(region or "미분류"), int(count)) for region, count in rows]
      except sqlite3.Error:
        pass

    try:
      rows = conn.execute("""
        SELECT region, count
        FROM speed_camera_region_counts
        ORDER BY count DESC, region
      """).fetchall()
      if rows:
        return [(str(region), int(count)) for region, count in rows]
    except sqlite3.Error:
      pass

    try:
      rows = conn.execute("""
        SELECT region, COUNT(*)
        FROM speed_cameras
        GROUP BY region
        ORDER BY COUNT(*) DESC, region
      """).fetchall()
      return [(str(region or "미분류"), int(count)) for region, count in rows]
    except sqlite3.Error:
      return []


def database_region_stats(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int, int, str]]:
  try:
    if not db_path.exists():
      return []
  except OSError:
    return []

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return []

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if {"region", "is_speed_camera", "updated_at"}.issubset(columns):
      try:
        rows = conn.execute("""
          SELECT
            region,
            COUNT(*) AS total_count,
            SUM(CASE WHEN is_speed_camera = 1 THEN 1 ELSE 0 END) AS alert_count,
            MAX(updated_at) AS latest_updated_at
          FROM speed_cameras
          GROUP BY region
          ORDER BY alert_count DESC, total_count DESC, region
        """).fetchall()
        return [
          (str(region or "미분류"), int(total_count), int(alert_count or 0), str(latest_updated_at or ""))
          for region, total_count, alert_count, latest_updated_at in rows
        ]
      except sqlite3.Error:
        pass

    return [
      (region, count, count, "")
      for region, count in database_region_counts(db_path)
    ]


def database_category_counts(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int]]:
  try:
    if not db_path.exists():
      return []
  except OSError:
    return []

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return []

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if "camera_category" not in columns:
      return []

    try:
      rows = conn.execute("""
        SELECT camera_category, COUNT(*)
        FROM speed_cameras
        GROUP BY camera_category
        ORDER BY
          CASE camera_category
            WHEN 'SPEED' THEN 1
            WHEN 'SECTION_SPEED' THEN 2
            WHEN 'SIGNAL' THEN 3
            WHEN 'SECURITY' THEN 4
            WHEN 'PROTECTED_ZONE' THEN 5
            WHEN 'UNKNOWN' THEN 6
            ELSE 7
          END,
          camera_category
      """).fetchall()
      return [(str(category or "UNKNOWN"), int(count)) for category, count in rows]
    except sqlite3.Error:
      return []


def database_road_class_counts(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int]]:
  try:
    if not db_path.exists():
      return []
  except OSError:
    return []

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return []

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if "road_class" not in columns:
      return []

    if "is_speed_camera" in columns:
      try:
        rows = conn.execute("""
          SELECT road_class, COUNT(*)
          FROM speed_cameras
          WHERE is_speed_camera = 1
          GROUP BY road_class
          ORDER BY COUNT(*) DESC, road_class
        """).fetchall()
        if rows:
          return [(str(road_class or "UNKNOWN"), int(count)) for road_class, count in rows]
      except sqlite3.Error:
        pass

    try:
      rows = conn.execute("""
        SELECT road_class, COUNT(*)
        FROM speed_cameras
        GROUP BY road_class
        ORDER BY COUNT(*) DESC, road_class
      """).fetchall()
      return [(str(road_class or "UNKNOWN"), int(count)) for road_class, count in rows]
    except sqlite3.Error:
      return []


def _fetch_data_go_json(path: str, params: dict, timeout: int = DATA_GO_KR_TIMEOUT_SECONDS):
  url = f"{PUBLIC_DATA_BASE_URL}{path}?{urlencode(params, doseq=True)}"
  request = Request(url, headers={"User-Agent": DATA_GO_KR_USER_AGENT, "Accept": "application/json"})
  for attempt in range(DATA_GO_KR_RETRY_COUNT):
    try:
      with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
    except OSError:
      if attempt == DATA_GO_KR_RETRY_COUNT - 1:
        raise
      time.sleep(1.0 + attempt)


def download_public_speed_camera_csv(
  csv_path: Path = DEFAULT_CSV_PATH,
  public_data_pk: str = PUBLIC_DATA_PK,
  per_page: int = 10000,
  max_pages: int | None = None,
  progress_callback: Callable[[int, int], None] | None = None,
) -> int:
  header = _fetch_data_go_json("/download/columList.json", {"pk": public_data_pk, "ext": "CSV"})
  column_list = header["columList"]
  column_codes = [item["columCode"] for item in column_list]
  column_names = [item["columNm"] for item in column_list]
  total_count = int(header["totalCount"])
  svc_table_name = header["tableVO"]["svcTableNm"]
  col_name_list = header["tableVO"].get("colNmList") or column_codes

  per_page = max(1, min(10000, int(per_page)))
  page_count = math.ceil(total_count / per_page)
  if max_pages is not None:
    page_count = min(page_count, max(0, int(max_pages)))

  csv_path.parent.mkdir(parents=True, exist_ok=True)
  written = 0
  if progress_callback is not None:
    progress_callback(written, total_count)

  with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(column_names)

    for page in range(1, page_count + 1):
      rows = _fetch_data_go_json("/download/standard.json", {
        "publicDataPk": public_data_pk,
        "colNmList": col_name_list,
        "totalCount": total_count,
        "svcTableNm": svc_table_name,
        "perPage": per_page,
        "page": page,
      })
      if not isinstance(rows, list):
        raise ValueError(f"unexpected public data response on page {page}: {type(rows).__name__}")

      for row in rows:
        writer.writerow([row.get(code, "") for code in column_codes])
        written += 1
      if progress_callback is not None:
        progress_callback(written, total_count)

  return written


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  phi1 = math.radians(lat1)
  phi2 = math.radians(lat2)
  d_phi = math.radians(lat2 - lat1)
  d_lambda = math.radians(lon2 - lon1)

  a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
  return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  phi1 = math.radians(lat1)
  phi2 = math.radians(lat2)
  d_lambda = math.radians(lon2 - lon1)

  y = math.sin(d_lambda) * math.cos(phi2)
  x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
  return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def relative_angle_deg(bearing: float, heading: float) -> float:
  return (bearing - heading + 180.0) % 360.0 - 180.0


def update_camera_position(camera: SpeedCamera, lat: float, lon: float, heading_deg: float) -> SpeedCamera:
  distance = haversine_distance_m(lat, lon, camera.lat, camera.lon)
  bearing = bearing_deg(lat, lon, camera.lat, camera.lon)
  relative_angle = relative_angle_deg(bearing, heading_deg)
  return replace(
    camera,
    distance_m=distance,
    bearing_deg=bearing,
    angle_diff_deg=abs(relative_angle),
    relative_angle_deg=relative_angle,
  )


def direction_bearing_deg(direction: str) -> float | None:
  normalized = direction.strip().upper()
  if not normalized:
    return None

  exact_directions = {
    "N": 0.0,
    "NB": 0.0,
    "E": 90.0,
    "EB": 90.0,
    "S": 180.0,
    "SB": 180.0,
    "W": 270.0,
    "WB": 270.0,
  }
  if normalized in exact_directions:
    return exact_directions[normalized]

  directions = [
    (("북", "NORTH"), 0.0),
    (("동", "EAST"), 90.0),
    (("남", "SOUTH"), 180.0),
    (("서", "WEST"), 270.0),
  ]
  matches = [bearing for names, bearing in directions if any(name in normalized for name in names)]
  if len(matches) == 1:
    return matches[0]
  return None


def _bounding_box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
  lat_delta = math.degrees(radius_m / EARTH_RADIUS_M)
  lon_radius = max(math.cos(math.radians(lat)), 0.01)
  lon_delta = math.degrees(radius_m / (EARTH_RADIUS_M * lon_radius))
  return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def _row_get(row: sqlite3.Row, column: str, default):
  if column in row.keys():
    value = row[column]
    if value is not None:
      return value
  return default


def _row_to_camera(row: sqlite3.Row, distance_m: float, bearing: float, angle_diff: float, relative_angle: float) -> SpeedCamera:
  camera_type = str(_row_get(row, "camera_type", ""))
  section_type = str(_row_get(row, "section_type", ""))
  road_name = str(_row_get(row, "road_name", ""))
  place = str(_row_get(row, "place", ""))

  category = str(_row_get(row, "camera_category", ""))
  if not category or category == "UNKNOWN":
    category = normalize_camera_category(camera_type, section_type)

  type_code = int(_row_get(row, "camera_type_code", 0))
  if type_code == 0:
    type_code = camera_type_code(camera_type, section_type)

  road_type_raw = str(_row_get(row, "road_type_raw", ""))
  road_class = str(_row_get(row, "road_class", ""))
  if not road_class or road_class == "UNKNOWN":
    road_class = normalize_road_class(road_type_raw, road_name, place)

  road_code = int(_row_get(row, "road_class_code", 0))
  if road_code == 0:
    road_code = road_class_code(road_class)

  is_expressway = bool(int(_row_get(row, "is_expressway", int(is_expressway_class(road_class)))))
  is_national_road = bool(int(_row_get(row, "is_national_road", int(is_national_road_class(road_class)))))

  return SpeedCamera(
    id=str(row["id"]),
    lat=float(row["lat"]),
    lon=float(row["lon"]),
    camera_type=camera_type,
    speed_limit=int(row["speed_limit"]),
    road_name=road_name,
    place=place,
    direction=str(_row_get(row, "direction", "")),
    section_type=section_type,
    section_length_m=int(_row_get(row, "section_length_m", 0)),
    distance_m=distance_m,
    bearing_deg=bearing,
    angle_diff_deg=angle_diff,
    relative_angle_deg=relative_angle,
    camera_category=category,
    camera_type_code=type_code,
    region=str(_row_get(row, "region", "")),
    road_type_raw=road_type_raw,
    road_class=road_class,
    road_class_code=road_code,
    is_expressway=is_expressway,
    is_national_road=is_national_road,
    source_type=str(_row_get(row, "source_type", "")),
    source_file=str(_row_get(row, "source_file", "")),
    osm_road_name=str(_row_get(row, "osm_road_name", "")),
    osm_road_ref=str(_row_get(row, "osm_road_ref", "")),
    osm_road_match_dist_m=float(_row_get(row, "osm_road_match_dist_m", 0.0)),
    osm_road_match_heading_deg=float(_row_get(row, "osm_road_match_heading_deg", 0.0)),
  )


def _database_version(conn: sqlite3.Connection) -> int:
  try:
    row = conn.execute("SELECT value FROM metadata WHERE key = ?", ("version",)).fetchone()
    return int(row[0]) if row and row[0] else 0
  except (sqlite3.Error, TypeError, ValueError):
    return 0


def _candidate_rows(
  conn: sqlite3.Connection,
  lat_min: float,
  lat_max: float,
  lon_min: float,
  lon_max: float,
) -> list[sqlite3.Row]:
  columns = _table_columns(conn, "speed_cameras")
  version = _database_version(conn)
  if {"is_speed_camera", "is_signal_camera", "camera_category"}.issubset(columns):
    rows = conn.execute("""
      SELECT * FROM speed_cameras
      WHERE lat BETWEEN ? AND ?
        AND lon BETWEEN ? AND ?
        AND (
          is_speed_camera = 1 OR
          is_signal_camera = 1 OR
          camera_category IN ('SECURITY', 'PROTECTED_ZONE')
        )
    """, (lat_min, lat_max, lon_min, lon_max)).fetchall()
    if rows or version >= DB_VERSION:
      return rows

  if "is_speed_camera" in columns:
    rows = conn.execute("""
      SELECT * FROM speed_cameras
      WHERE lat BETWEEN ? AND ?
        AND lon BETWEEN ? AND ?
        AND is_speed_camera = 1
    """, (lat_min, lat_max, lon_min, lon_max)).fetchall()
    if rows or version >= DB_VERSION:
      return rows

  return conn.execute("""
    SELECT * FROM speed_cameras
    WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
  """, (lat_min, lat_max, lon_min, lon_max)).fetchall()


def find_lead_cameras(
  db_path: Path,
  lat: float,
  lon: float,
  heading_deg: float,
  max_distance_m: float = LOOKAHEAD_DISTANCE_M,
  max_angle_deg: float = LOOKAHEAD_ANGLE_DEG,
  camera_direction_angle_deg: float = CAMERA_DIRECTION_ANGLE_DEG,
  ignored_ids: set[str] | None = None,
  limit: int = 3,
  current_road_name: str = "",
) -> list[SpeedCamera]:
  if not db_path.exists():
    return []

  ignored_ids = ignored_ids or set()
  lat_min, lat_max, lon_min, lon_max = _bounding_box(lat, lon, max_distance_m)

  with closing(sqlite3.connect(db_path)) as conn:
    conn.row_factory = sqlite3.Row
    rows = _candidate_rows(conn, lat_min, lat_max, lon_min, lon_max)

  candidates: list[SpeedCamera] = []
  for row in rows:
    if row["id"] in ignored_ids:
      continue

    distance = haversine_distance_m(lat, lon, row["lat"], row["lon"])
    if distance > max_distance_m:
      continue

    cam_bearing = bearing_deg(lat, lon, row["lat"], row["lon"])
    relative_angle = relative_angle_deg(cam_bearing, heading_deg)
    diff = abs(relative_angle)
    if diff > max_angle_deg:
      continue

    camera_direction = direction_bearing_deg(row["direction"])
    if camera_direction is not None and angle_diff_deg(camera_direction, heading_deg) > camera_direction_angle_deg:
      continue

    camera = _row_to_camera(row, distance, cam_bearing, diff, relative_angle)
    if current_road_name:
      camera_road_names = (
        (camera.osm_road_name, camera.osm_road_ref)
        if (camera.osm_road_name or camera.osm_road_ref)
        else (camera.road_name, camera.place)
      )
      camera = replace(
        camera,
        local_road_match=road_name_matches(current_road_name, *camera_road_names),
      )
    if _is_alertable_category(camera.camera_category):
      candidates.append(camera)

  return sorted(candidates, key=_alert_priority)[:max(0, limit)]


def find_lead_camera(
  db_path: Path,
  lat: float,
  lon: float,
  heading_deg: float,
  max_distance_m: float = LOOKAHEAD_DISTANCE_M,
  max_angle_deg: float = LOOKAHEAD_ANGLE_DEG,
  camera_direction_angle_deg: float = CAMERA_DIRECTION_ANGLE_DEG,
  ignored_ids: set[str] | None = None,
  current_road_name: str = "",
) -> SpeedCamera | None:
  cameras = find_lead_cameras(
    db_path,
    lat,
    lon,
    heading_deg,
    max_distance_m,
    max_angle_deg,
    camera_direction_angle_deg,
    ignored_ids,
    limit=1,
    current_road_name=current_road_name,
  )
  return cameras[0] if cameras else None
