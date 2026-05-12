
import sys
import os
from pathlib import Path

# 모든 가능한 루트 추가
root = Path("D:/openpilot/openpilot")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root.parent))

try:
    from openpilot.selfdrive.navd.osm_predictor import OSMRoadPredictor, GPSFix
except ImportError:
    from selfdrive.navd.osm_predictor import OSMRoadPredictor, GPSFix

def test_points():
    db_path = Path("C:/Users/atom9/.comma/navd/db/osm_roads_kr.sqlite3")
    
    if not db_path.exists():
        print(f"ERROR: DB path {db_path} does not exist!")
        return
        
    print(f"Using New DB: {db_path}")
    predictor = OSMRoadPredictor(db_path=db_path)
    
    points = [
        ("송파구 방이동", 37.5146781, 127.1515906, 169.7, 14.07),
        ("송파구 방이동(2)", 37.5142862, 127.1516254, 181.5, 14.93),
        ("천안 서북구 저속", 36.7963896, 127.1088189, 149.8, 0.93)
    ]
    
    for desc, lat, lon, bearing, speed in points:
        gps = GPSFix(lat=lat, lon=lon, bearing_deg=bearing, speed_mps=speed)
        prediction = predictor.update(gps)
        
        print(f"\n--- Testing Point: {desc} ({lat}, {lon}) ---")
        if prediction and prediction.current:
            print(f"RESULT: SUCCESS - Matched to [{prediction.current.display_name}] (ID: {prediction.current.road_id})")
            print(f"Details: Distance={prediction.current.distance_m:.2f}m, HeadingDiff={prediction.current.heading_diff_deg:.2f}")
        else:
            print(f"RESULT: STILL FAILED")
            if prediction:
                print(f"Debug: {prediction.debug_text}")

if __name__ == "__main__":
    test_points()
