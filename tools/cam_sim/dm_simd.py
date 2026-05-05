#!/usr/bin/env python3
from cereal import log, messaging
from openpilot.common.realtime import Ratekeeper


def main():
  pm = messaging.PubMaster(["driverStateV2", "driverMonitoringState"])
  rk = Ratekeeper(20, None)
  frame_id = 0

  while True:
    driver_state = messaging.new_message("driverStateV2", valid=True)
    ds = driver_state.driverStateV2
    ds.frameId = frame_id
    ds.wheelOnRightProb = 0.0
    for driver_data in (ds.leftDriverData, ds.rightDriverData):
      driver_data.faceOrientation = [0.0, 0.0, 0.0]
      driver_data.faceOrientationStd = [0.01, 0.01, 0.01]
      driver_data.facePosition = [0.0, 0.0]
      driver_data.facePositionStd = [0.01, 0.01]
      driver_data.faceProb = 1.0
      driver_data.eyesVisibleProb = 1.0
      driver_data.eyesClosedProb = 0.0
      driver_data.phoneProb = 0.0
    pm.send("driverStateV2", driver_state)

    dm_state = messaging.new_message("driverMonitoringState", valid=True)
    dm = dm_state.driverMonitoringState
    dm.alertLevel = log.DriverMonitoringState.AlertLevel.none
    dm.activePolicy = log.DriverMonitoringState.MonitoringPolicy.vision
    dm.isRHD = False
    dm.visionPolicyState.awarenessPercent = 100.0
    dm.visionPolicyState.faceDetected = True
    dm.visionPolicyState.isDistracted = False
    dm.visionPolicyState.pose.pitch = 0.0
    dm.visionPolicyState.pose.yaw = 0.0
    dm.visionPolicyState.pose.uncertainty = 0.01
    pm.send("driverMonitoringState", dm_state)

    frame_id += 1
    rk.keep_time()


if __name__ == "__main__":
  main()
