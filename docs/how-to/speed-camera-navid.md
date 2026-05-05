# Speed Camera navid

`navid` publishes fixed speed camera information from a public CSV database to
`naviCustom`. The onroad HUD subscribes to `naviCustom` and shows the camera
speed limit and remaining distance.

## 1. Download the CSV

Download `전국무인교통단속카메라표준데이터` from the public data portal:

https://www.data.go.kr/data/15028200/standard.do

The dataset is for fixed unmanned traffic enforcement cameras. It does not cover
mobile or temporary enforcement.

## 2. Import the database

Copy the CSV to the device or PC, then import it:

```bash
.venv/bin/python tools/scripts/import_speed_cameras.py --csv /path/to/speed_cameras.csv
```

Default output path:

```text
/persist/speed_cameras.sqlite3
```

On PC, if `/persist` does not exist, the fallback is:

```text
~/.comma/persist/speed_cameras.sqlite3
```

You can also download the official public data portal CSV and import it in one step:

```bash
.venv/bin/python tools/scripts/update_speed_cameras.py
```

On device, the same flow is available from `Custom > Navigation > Speed camera DB`.
The button downloads the national public dataset, writes `speed_cameras.csv`, and
replaces the local SQLite DB used by `navid`.

You can override paths:

```bash
.venv/bin/python tools/scripts/import_speed_cameras.py \
  --csv /path/to/speed_cameras.csv \
  --db /persist/speed_cameras.sqlite3
```

## 3. Check a known location

Use the current latitude, longitude, and heading:

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

## 4. Run onroad

`navid` is registered as an onroad process. When the car is onroad and GPS is
valid, it reads:

```text
gpsLocationExternal
gpsLocation
```

Then it publishes:

```text
naviCustom.naviData.active
naviCustom.naviData.camType
naviCustom.naviData.camLimitSpeed
naviCustom.naviData.camLimitSpeedLeftDist
naviCustom.naviData.currentRoadName
```

## 5. Watch the output

Run this while onroad or while replaying/mocking GPS:

```bash
.venv/bin/python tools/scripts/watch_navi_custom.py
```

Expected active output:

```text
active=1 camType=1 limit=80 dist=450m roadLimit=80 road='...'
```

## 6. Tune false positives

The first implementation uses GPS, heading, distance, and optional road direction
fields from the CSV.

Tune these constants in `selfdrive/navd/speed_camera.py`:

```text
LOOKAHEAD_DISTANCE_M
LOOKAHEAD_ANGLE_DEG
CAMERA_DIRECTION_ANGLE_DEG
```

Suggested starting points:

```text
LOOKAHEAD_DISTANCE_M = 1500 to 2500
LOOKAHEAD_ANGLE_DEG = 30 to 45
CAMERA_DIRECTION_ANGLE_DEG = 45 to 70
```

If adjacent-road detections are common, lower `LOOKAHEAD_ANGLE_DEG` first.
