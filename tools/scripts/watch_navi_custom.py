#!/usr/bin/env python3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if sys.version_info < (3, 12):
  print(
    "watch_navi_custom.py must run with openpilot's Python 3.12 environment.\n"
    "Run: .venv/bin/python tools/scripts/watch_navi_custom.py",
    file=sys.stderr,
  )
  sys.exit(2)

import cereal.messaging as messaging


def main() -> None:
  sm = messaging.SubMaster(["naviCustom"])
  last_print = 0.0

  while True:
    sm.update(1000)
    nav = sm["naviCustom"].naviData

    now = time.monotonic()
    if now - last_print < 0.5:
      continue
    last_print = now

    print(
      f"active={nav.active} camType={nav.camType} "
      f"category={getattr(nav, 'camCategory', '')} "
      f"camCategoryCode={getattr(nav, 'camCategoryCode', 0)} "
      f"roadClass={getattr(nav, 'roadClass', '')} "
      f"roadClassCode={getattr(nav, 'roadClassCode', 0)} "
      f"limit={nav.camLimitSpeed} dist={nav.camLimitSpeedLeftDist}m "
      f"roadLimit={nav.roadLimitSpeed} road='{nav.currentRoadName}'"
    )


if __name__ == "__main__":
  main()
