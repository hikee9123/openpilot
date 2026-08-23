#!/usr/bin/env python3
import time

import cereal.messaging as messaging

from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process
from openpilot.selfdrive.monitoring.blink_auto_tuner import BlinkAutoTuner


SAVE_INTERVAL_SECONDS = 60.0
MINIMUM_SPEED = 2.8


def current_settings(params, blink_debug):
  return {
    "closeThresholdPct": int(blink_debug.closeThresholdPercent),
    "openThresholdPct": int(blink_debug.openThresholdPercent),
    "minDurationMs": int(blink_debug.minDurationMillis),
    "maxBlinkDurationMs": int(blink_debug.maxBlinkDurationMillis),
    "sleepCandidateDurationMs": int(blink_debug.sleepCandidateDurationMillis),
    "minValidPct": int(params.get("DmBlinkMinValidPct", return_default=True)),
  }


def main():
  config_realtime_process([0, 1, 2, 3], 1)
  params = Params()
  tuner = BlinkAutoTuner.from_dict(params.get("DmBlinkAutoTuneState") or {})
  sm = messaging.SubMaster(["driverMonitoringState", "selfdriveState", "carState"], poll="driverMonitoringState")
  last_save_time = time.monotonic()
  latest_settings = None

  try:
    while True:
      sm.update()
      if not sm.updated["driverMonitoringState"]:
        continue

      dm_state = sm["driverMonitoringState"]
      blink_debug = dm_state.visionPolicyState.blinkDebugState
      latest_settings = current_settings(params, blink_debug)
      collecting = sm["selfdriveState"].enabled and sm["carState"].vEgo >= MINIMUM_SPEED
      if collecting:
        tuner.observe(
          valid=blink_debug.valid,
          effective_blink_prob=blink_debug.effectiveBlinkProb,
          eye_closed=blink_debug.eyeClosed,
          current_closure_ms=blink_debug.currentClosureMillis,
          valid_ratio_percent=blink_debug.validPercent10s,
        )
      else:
        tuner.pause()

      if time.monotonic() - last_save_time >= SAVE_INTERVAL_SECONDS:
        params.put_nonblocking("DmBlinkAutoTuneState", tuner.to_dict(latest_settings))
        last_save_time = time.monotonic()
  finally:
    if latest_settings is not None:
      params.put("DmBlinkAutoTuneState", tuner.to_dict(latest_settings))


if __name__ == "__main__":
  main()
