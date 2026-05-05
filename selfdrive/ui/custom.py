import json
import math
import time
from collections.abc import Mapping

import cereal.messaging as messaging
from openpilot.common.params import Params


# #custom start: shared custom UI params and publisher
CUSTOM_PARAM_KEY = "CustomParam"
POWER_OFF_MIN_SPEED = 10.0
POWER_OFF_UPDATE_INTERVAL = 1.0

DEFAULT_CUSTOM_PARAMS: dict[str, int | float | bool] = {
  "ParamCruiseMode": 2,
  "ParamCruiseGap": 4,
  "ParamCurveSpeedLimit": 70,
  "ParamAutoEngage": 60,
  "ParamAutoLaneChange": 30,
  "ParamSteerRatio": 0.0,
  "ParamStiffnessFactor": 0.0,
  "ParamAngleOffsetDeg": 0.0,
  "SpeedCameraLookaheadDistance": 2000,
  "SpeedCameraLookaheadAngle": 35,
  "SpeedCameraDirectionAngle": 60,
  "SpeedCameraPassingDistance": 30,
  "SpeedCameraPassedIgnoreSeconds": 8,
  "SpeedCameraMinGpsSpeed": 3,
  "ParamAutoScreenOff": 8,
  "ParamScreenOffAfterFade": True,
  "ParamBrightness": -12,
  "ParamPowerOff": 15,
  "DUAL_CAMERA_VIEW": 0,
  "ShowDebugMessage": False,
  "ShowCarTracking": False,
  "tpms": True,
  "ParamDebug": False,
  "kegman": True,
  "kegmanCPU": True,
  "kegmanGPULoad": True,
  "kegmanBattery": True,
  "kegmanGPS": False,
  "kegmanAngle": False,
  "kegmanEngine": False,
  "kegmanDistance": False,
  "kegmanSpeed": False,
  "kegmanLag": False,
  "debug1": False,
  "debug2": False,
  "debug3": False,
  "debug4": False,
  "debug5": False,
  "debug6": False,
}


def read_custom_param_map(params: Params | None = None) -> dict:
  params = params or Params()
  raw = params.get(CUSTOM_PARAM_KEY)
  if not raw:
    return {}
  try:
    loaded = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    return dict(loaded) if isinstance(loaded, Mapping) else {}
  except Exception:
    return {}


def _coerce_like_default(key: str, value):
  default = DEFAULT_CUSTOM_PARAMS[key]
  if isinstance(default, bool):
    if isinstance(value, bool):
      return value
    if isinstance(value, (int, float)):
      return value != 0
    if isinstance(value, str):
      lowered = value.strip().lower()
      if lowered in ("1", "true", "yes", "on"):
        return True
      if lowered in ("0", "false", "no", "off", ""):
        return False
    return default
  if isinstance(default, int) and not isinstance(default, bool):
    try:
      return int(value)
    except (TypeError, ValueError):
      return default
  if isinstance(default, float):
    try:
      return float(value)
    except (TypeError, ValueError):
      return default
  return value


def read_custom_params(params: Params | None = None) -> dict[str, int | float | bool]:
  params = params or Params()
  values = DEFAULT_CUSTOM_PARAMS.copy()
  loaded = read_custom_param_map(params)
  for key in values:
    if key in loaded:
      values[key] = _coerce_like_default(key, loaded[key])
  if "kegmanGPS" not in loaded and "kegmanGPU" in loaded:
    values["kegmanGPS"] = _coerce_like_default("kegmanGPS", loaded["kegmanGPU"])
  if "ShowDebugMessage" not in loaded and "ParamDebug" in loaded:
    values["ShowDebugMessage"] = _coerce_like_default("ShowDebugMessage", loaded["ParamDebug"])
  values["ParamDebug"] = bool(values["ShowDebugMessage"])
  return values


def write_custom_params(values: Mapping[str, int | float | bool], params: Params | None = None) -> None:
  params = params or Params()
  merged = read_custom_param_map(params)
  for key, value in read_custom_params(params).items():
    merged[key] = value
  for key, value in values.items():
    if key in merged:
      merged[key] = _coerce_like_default(key, value)
  if "ShowDebugMessage" in values:
    merged["ParamDebug"] = bool(merged["ShowDebugMessage"])
  elif "ParamDebug" in values:
    merged["ShowDebugMessage"] = bool(merged["ParamDebug"])
  params.put(CUSTOM_PARAM_KEY, json.dumps(merged, separators=(",", ":"), sort_keys=True))


class CustomPublisher:
  def __init__(self, params: Params | None = None):
    self.params = params or Params()
    self.pm = messaging.PubMaster(["uICustom"])
    self._cmd_idx = 0
    self._last_publish = 0.0

  def update(self, force: bool = False) -> None:
    now = time.monotonic()
    if not force and now - self._last_publish < 1.0:
      return
    self._last_publish = now
    self.publish()

  def publish(self) -> None:
    values = read_custom_params(self.params)
    self._cmd_idx += 1

    msg = messaging.new_message("uICustom")
    custom = msg.uICustom

    debug = custom.debug
    debug.cmdIdx = self._cmd_idx
    debug.idx1 = int(values["debug1"])
    debug.idx2 = int(values["debug2"])
    debug.idx3 = int(values["debug3"])
    debug.idx4 = int(values["debug4"])
    debug.idx5 = int(values["debug5"])
    debug.idx6 = int(values["debug6"])

    community = custom.community
    community.cmdIdx = self._cmd_idx
    community.cruiseMode = int(values["ParamCruiseMode"])
    community.cruiseGap = int(values["ParamCruiseGap"])
    community.curveSpeedLimit = int(values["ParamCurveSpeedLimit"])
    community.steerRatio = float(values["ParamSteerRatio"])
    community.stiffnessFactor = float(values["ParamStiffnessFactor"])
    community.angleOffsetDeg = float(values["ParamAngleOffsetDeg"])
    community.autoEngage = int(values["ParamAutoEngage"])
    community.autoLaneChange = int(values["ParamAutoLaneChange"])

    user_interface = custom.userInterface
    user_interface.cmdIdx = self._cmd_idx
    user_interface.showDebugMessage = int(values["ShowDebugMessage"])
    user_interface.showCarTracking = int(values["ShowCarTracking"])
    user_interface.tpms = int(values["tpms"])
    user_interface.debug = int(values["ShowDebugMessage"])
    user_interface.kegman = int(values["kegman"])
    user_interface.kegmanCPU = int(values["kegmanCPU"])
    user_interface.kegmanBattery = int(values["kegmanBattery"])
    user_interface.kegmanGPS = int(values["kegmanGPS"])
    user_interface.kegmanGPULoad = int(values["kegmanGPULoad"])
    user_interface.kegmanAngle = int(values["kegmanAngle"])
    user_interface.kegmanEngine = int(values["kegmanEngine"])
    user_interface.kegmanDistance = int(values["kegmanDistance"])
    user_interface.kegmanSpeed = int(values["kegmanSpeed"])
    user_interface.kegmanLag = int(values["kegmanLag"])
    user_interface.autoScreenOff = int(values["ParamAutoScreenOff"])
    user_interface.brightness = int(values["ParamBrightness"])

    self.pm.send("uICustom", msg)


class AutoPowerOffController:
  def __init__(self, params: Params | None = None):
    self.params = params or Params()
    self._armed = False
    self._ignition_off_since: float | None = None
    self._last_update = -POWER_OFF_UPDATE_INTERVAL
    self._power_off_delay = 0

  @property
  def armed(self) -> bool:
    return self._armed and self._power_off_delay > 0

  @property
  def remaining_seconds(self) -> int | None:
    if not self._armed or self._ignition_off_since is None or self._power_off_delay <= 0:
      return None
    remaining = self._power_off_delay - (time.monotonic() - self._ignition_off_since)
    return max(0, math.ceil(remaining))

  @property
  def countdown_progress(self) -> float | None:
    if not self._armed or self._ignition_off_since is None or self._power_off_delay <= 0:
      return None
    elapsed = time.monotonic() - self._ignition_off_since
    return max(0.0, min(1.0, elapsed / self._power_off_delay))

  def disarm(self) -> None:
    self._armed = False
    self._ignition_off_since = None
    self._power_off_delay = 0

  def update(self, started: bool, ignition: bool, v_ego: float, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if now - self._last_update < POWER_OFF_UPDATE_INTERVAL:
      return
    self._last_update = now
    self._power_off_delay = int(read_custom_params(self.params)["ParamPowerOff"])

    if self._power_off_delay <= 0:
      self.disarm()
      return

    if started:
      self._ignition_off_since = None
      if v_ego > POWER_OFF_MIN_SPEED:
        self._armed = True
      return

    if ignition:
      self._ignition_off_since = None
      return

    if not self._armed:
      self._ignition_off_since = None
      return

    if self._ignition_off_since is None:
      self._ignition_off_since = now
      return

    if now - self._ignition_off_since > self._power_off_delay:
      self._armed = False
      self._ignition_off_since = None
      self._power_off_delay = 0
      self.params.put_bool("DoShutdown", True)
# #custom end
