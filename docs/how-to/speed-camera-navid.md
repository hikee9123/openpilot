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
관리번호
GPS + 제한속도
지역 + 설치장소 + 제한속도
fallback row id
```

Merge priority:

```text
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
