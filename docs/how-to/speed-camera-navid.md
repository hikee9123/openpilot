# Speed Camera navid

`navid` publishes fixed speed camera information from a SQLite database to
`naviCustom`. The onroad HUD subscribes to `naviCustom` and shows camera category,
road class, speed limit, and remaining distance.

## 1. Input Data

The default public CSV remains:

```text
selfdrive/navd/data/speed_cameras.csv
```

Regional CSV files can be added under:

```text
selfdrive/navd/data/region/
```

Example:

```text
selfdrive/navd/data/
  speed_cameras.csv
  speed_cameras.sqlite3
  region/
    seoul_speed_cameras.csv
    gyeonggi_speed_cameras.csv
```

CSV files are read with `utf-8-sig`, `utf-8`, `cp949`, `euc-kr`, then a
replacement fallback.

## 2. Import

Single public CSV import still works:

```bash
.venv/bin/python tools/scripts/import_speed_cameras.py \
  --csv selfdrive/navd/data/speed_cameras.csv \
  --db selfdrive/navd/data/speed_cameras.sqlite3
```

To include regional CSVs:

```bash
.venv/bin/python tools/scripts/import_speed_cameras.py \
  --csv selfdrive/navd/data/speed_cameras.csv \
  --region-dir selfdrive/navd/data/region \
  --db selfdrive/navd/data/speed_cameras.sqlite3
```

Extra custom CSVs can be provided repeatedly:

```bash
.venv/bin/python tools/scripts/import_speed_cameras.py \
  --csv selfdrive/navd/data/speed_cameras.csv \
  --extra-csv /path/to/custom.csv
```

`update_speed_cameras.py` still downloads the national public data portal CSV, then
imports it together with optional `--region-dir` and `--extra-csv` sources.

## 3. Stored Classification

The DB stores both original and normalized values:

```text
camera_type_raw -> camera_category -> camera_type_code -> is_speed_camera
road_type_raw   -> road_class      -> road_class_code  -> is_expressway / is_national_road
```

Camera categories:

```text
SPEED
SIGNAL
SPEED_SIGNAL
SECTION_SPEED
PARKING
BUS_LANE
TRAFFIC
SECURITY
ETC
UNKNOWN
```

Default driving alerts use only:

```text
SPEED
SPEED_SIGNAL
SECTION_SPEED
```

Public data often uses numeric enforcement codes. `01+02` is normalized as
`SPEED_SIGNAL`. Rows with `단속구분=99` are kept as `UNKNOWN` unless their section
position code or location text indicates a section camera; `단속구간위치구분`
`1/01` or `2/02`, or location text containing `구간`, `시점`, `종점`, or
`어린이보호구역`, is normalized as `SECTION_SPEED`. `단속구분=99` rows with a
30 km/h limit and `초등학교` in the location text are also normalized as
`SECTION_SPEED`.

Signal-only, parking, bus-lane, and security cameras are stored in the DB but are
excluded from the default speed alert lookup.

Road classes:

```text
EXPRESSWAY
NATIONAL_ROAD
NATIONAL_LOCAL_ROAD
LOCAL_ROAD
CITY_ROAD
COUNTY_ROAD
DISTRICT_ROAD
ETC
UNKNOWN
```

## 4. Deduplication

Rows from all CSV sources are normalized, then merged by `dedup_key`.

Dedup key priority:

```text
관리번호 + compatible category + road class + GPS cluster within 50m
GPS + 제한속도 + category + road class
지역 + 설치장소 + 제한속도 + category + road class
fallback row id
```

Management numbers in the public data are not globally unique across every
region. Rows with the same management number are merged only when their GPS
coordinates are within 50m; farther rows are treated as separate cameras.
Known camera categories are not merged when they differ. `UNKNOWN` rows use a
practical mode: they can merge with a known category only when the speed limit
matches and the cluster has no conflicting known category. When an `UNKNOWN`
row is merged with a known category, the known category is preferred so speed
camera behavior is not lost just because a newer public row is less specific.
Road class is also part of dedup compatibility, so expressway cameras are not
merged with city, local, or national-road cameras even when their management
number and coordinates are nearly identical.

Merge priority:

```text
known camera category
newer updated_at
custom source
region source
public source
valid lat/lon
longer place text
```

## 5. Runtime Flow

```text
national public CSV + regional CSVs
        -> normalized columns
        -> camera category
        -> road class
        -> dedup merge
        -> speed_cameras.sqlite3
        -> find_lead_camera(is_speed_camera = 1)
        -> navid naviCustom category / roadClass
        -> HUD Speed / Expressway label
```

`naviCustom.naviData` includes:

```text
camType
camCategory
camCategoryCode
roadClass
roadClassCode
camLimitSpeed
camLimitSpeedLeftDist
currentRoadName
```

Watch output:

```bash
.venv/bin/python tools/scripts/watch_navi_custom.py
```

Example:

```text
active=1 camType=1 category=SPEED camCategoryCode=1 roadClass=EXPRESSWAY roadClassCode=1 limit=80 dist=450m roadLimit=80 road='...'
```

## 6. HUD Policy

HUD examples:

```text
Speed / Expressway
      80
     450m

Section / National
      80
     1.2km
```

Speed camera alert UI policy:

```text
No outer rectangular box
Large circular speed-limit donut as the primary element
SPEED / SPEED_SIGNAL / SECTION_SPEED: larger Red donut
Other categories: Blue donut
Camera category / road class: small supporting label
Remaining distance: centered below the donut
```

## 7. Lookup Check

Use a known latitude, longitude, and heading:

```bash
.venv/bin/python tools/scripts/import_speed_cameras.py \
  --csv /path/to/speed_cameras.csv \
  --check \
  --lat 37.0 \
  --lon 127.0 \
  --heading 0
```

Or check an existing DB:

```bash
.venv/bin/python tools/scripts/lookup_speed_camera.py \
  --lat 37.0 \
  --lon 127.0 \
  --heading 0
```

## 8. Tuning

The implementation uses GPS, heading, distance, and optional road direction fields.
These values can be tuned from `Custom > Navigation > Speed camera tuning`.

Default values:

```text
Camera search distance: 2000m
Camera search angle: 35deg
Camera direction angle: 60deg
Camera passing distance: 30m
Camera ignore time: 8s
Minimum GPS speed: 3km/h
```
