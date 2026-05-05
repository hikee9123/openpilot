#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openpilot.selfdrive.navd.speed_camera import DEFAULT_DB_PATH, find_lead_camera


def main() -> None:
  parser = argparse.ArgumentParser(description="Find the lead speed camera for a GPS position and heading")
  parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
  parser.add_argument("--lat", type=float, required=True)
  parser.add_argument("--lon", type=float, required=True)
  parser.add_argument("--heading", type=float, required=True)
  parser.add_argument("--distance", type=float, default=2500.0)
  parser.add_argument("--angle", type=float, default=45.0)
  args = parser.parse_args()

  camera = find_lead_camera(args.db, args.lat, args.lon, args.heading, args.distance, args.angle)
  if camera is None:
    print("no lead camera found")
    return

  print(f"id: {camera.id}")
  print(f"distance_m: {camera.distance_m:.1f}")
  print(f"bearing_deg: {camera.bearing_deg:.1f}")
  print(f"angle_diff_deg: {camera.angle_diff_deg:.1f}")
  print(f"speed_limit: {camera.speed_limit}")
  print(f"camera_type: {camera.camera_type}")
  print(f"road_name: {camera.road_name}")
  print(f"place: {camera.place}")


if __name__ == "__main__":
  main()
