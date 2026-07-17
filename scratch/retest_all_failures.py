
import sys
import os
import csv
from pathlib import Path

# openpilot 경로 추가
root = Path("D:/openpilot/openpilot")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root.parent))

from selfdrive.navd.osm_predictor import OSMRoadPredictor, GPSFix

def retest_all_failures():
    db_path = Path("C:/Users/atom9/.comma/navd/db/osm_roads_kr.sqlite3")
    failure_log = Path("D:/openpilot/logs/navd/comma_10.30.188.86_20260511_191145/osm_prediction_failures.csv")
    
    if not db_path.exists() or not failure_log.exists():
        print("Required files not found.")
        return

    predictor = OSMRoadPredictor(db_path=db_path)
    
    total_failures = 0
    now_success = 0
    now_failed = 0
    
    print(f"Starting re-test for all failures in {failure_log.name}...")
    
    with open(failure_log, "r", encoding="utf-8") as f:
        # 헤더가 없는 CSV 형식으로 처리
        for line in f:
            line = line.strip()
            if not line: continue
            parts = line.split(",")
            if len(parts) < 5: continue
            
            try:
                # 2026-05-11 08:00:56, lat, lon, bearing, speed, ...
                lat = float(parts[1])
                lon = float(parts[2])
                bearing = float(parts[3])
                speed = float(parts[4])
                
                total_failures += 1
                gps = GPSFix(lat=lat, lon=lon, bearing_deg=bearing, speed_mps=speed)
                prediction = predictor.update(gps)
                
                if prediction and prediction.current:
                    now_success += 1
                else:
                    now_failed += 1
            except (ValueError, IndexError):
                continue
                
    print("\n--- Re-test Results ---")
    print(f"Total Failed Points Tested: {total_failures}")
    print(f"Now Successfully Matched: {now_success}")
    print(f"Still Failed: {now_failed}")
    
    # 최종 통계 계산
    original_trace = 7076
    original_total = 7207
    new_total_success = original_trace + now_success
    new_success_rate = (new_total_success / original_total) * 100
    
    print(f"\n--- Updated Global Statistics ---")
    print(f"New Total Success: {new_total_success} / {original_total}")
    print(f"Final Success Rate: {new_success_rate:.4f}%")

if __name__ == "__main__":
    retest_all_failures()
