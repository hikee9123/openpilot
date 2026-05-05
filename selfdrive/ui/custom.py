import json
import time
from collections.abc import Mapping

import cereal.messaging as messaging
from openpilot.common.params import Params


# #custom start: shared custom UI params and publisher
CUSTOM_PARAM_KEY = "CustomParam"

DEFAULT_CUSTOM_PARAMS: dict[str, int | float | bool] = {
  "ParamCruiseMode": 2,
  "ParamCruiseGap": 4,
  "ParamCurveSpeedLimit": 70,
  "ParamAutoEngage": 60,
  "ParamAutoLaneChange": 30,
  "ParamSteerRatio": 0.0,
  "ParamStiffnessFactor": 0.0,
  "ParamAngleOffsetDeg": 0.0,
  "ShowDebugMessage": False,
  "ShowCarTracking": False,
  "tpms": False,
  "ParamDebug": False,
  "kegman": False,
  "kegmanCPU": False,
  "kegmanBattery": False,
  "kegmanGPU": False,
  "kegmanAngle": False,
  "kegmanEngine": False,
  "kegmanDistance": False,
  "kegmanSpeed": False,
  "kegmanLag": False,
  "ParamAutoScreenOff": 8,
  "ParamBrightness": -12,
  "ParamPowerOff": 15,
  "DUAL_CAMERA_VIEW": 0,
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
  return values


def write_custom_params(values: Mapping[str, int | float | bool], params: Params | None = None) -> None:
  params = params or Params()
  merged = read_custom_param_map(params)
  for key, value in read_custom_params(params).items():
    merged[key] = value
  for key, value in values.items():
    if key in merged:
      merged[key] = _coerce_like_default(key, value)
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

    user_interface = custom.userInterface
    user_interface.cmdIdx = self._cmd_idx
    user_interface.showDebugMessage = int(values["ShowDebugMessage"])
    user_interface.showCarTracking = int(values["ShowCarTracking"])
    user_interface.tpms = int(values["tpms"])
    user_interface.debug = int(values["ParamDebug"])
    user_interface.kegman = int(values["kegman"])
    user_interface.kegmanCPU = int(values["kegmanCPU"])
    user_interface.kegmanBattery = int(values["kegmanBattery"])
    user_interface.kegmanGPU = int(values["kegmanGPU"])
    user_interface.kegmanAngle = int(values["kegmanAngle"])
    user_interface.kegmanEngine = int(values["kegmanEngine"])
    user_interface.kegmanDistance = int(values["kegmanDistance"])
    user_interface.kegmanSpeed = int(values["kegmanSpeed"])
    user_interface.kegmanLag = int(values["kegmanLag"])
    user_interface.autoScreenOff = int(values["ParamAutoScreenOff"])
    user_interface.brightness = int(values["ParamBrightness"])

    self.pm.send("uICustom", msg)
# #custom end
