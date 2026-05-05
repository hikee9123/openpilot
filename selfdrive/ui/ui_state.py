import pyray as rl
import numpy as np
import os
import time
import threading
from collections.abc import Callable
from enum import Enum
from cereal import messaging, car, log
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.custom import AutoPowerOffController, CustomPublisher, read_custom_params
from openpilot.selfdrive.ui.lib.prime_state import PrimeState
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.hardware import HARDWARE, PC

BACKLIGHT_OFFROAD = 65 if HARDWARE.get_device_type() == "mici" else 50
PARAM_UPDATE_TIME = 5.0
CUSTOM_PARAM_UPDATE_TIME = 1.0
CAMERA_SIM = PC and os.getenv("CAM_SIM", "").lower() in ("road", "webcam")
DISPLAY_FADE_IN_SECONDS = 1.0
DISPLAY_FADE_OUT_SECONDS = 60.0
DISPLAY_DIM_MIN_SECONDS = 1.0
DISPLAY_DIM_MAX_SECONDS = 2.0
DISPLAY_DIM_START = 0.30
DISPLAY_DIM_END = 0.10
DISPLAY_DIM_MIN_BRIGHTNESS = 5.0


class UIStatus(Enum):
  DISENGAGED = "disengaged"
  ENGAGED = "engaged"
  OVERRIDE = "override"


class UIState:
  _instance: 'UIState | None' = None

  def __new__(cls):
    if cls._instance is None:
      cls._instance = super().__new__(cls)
      cls._instance._initialize()
    return cls._instance

  def _initialize(self):
    self.params = Params()
    self.sm = messaging.SubMaster(
      [
        "modelV2",
        "controlsState",
        "onroadEvents",
        "liveCalibration",
        "radarState",
        "deviceState",
        "pandaStates",
        "peripheralState",
        "carParams",
        "driverMonitoringState",
        "carState",
        "driverStateV2",
        "roadCameraState",
        "wideRoadCameraState",
        "managerState",
        "selfdriveState",
        "longitudinalPlan",
        "gpsLocation",
        "gpsLocationExternal",
        "carOutput",
        "carControl",
        "liveParameters",
        "testJoystick",
        "rawAudioData",
        "uICustom",
      ]
    )

    self.prime_state = PrimeState()
    # #custom start: publish custom UI tuning state
    self.custom_params = read_custom_params(self.params)
    self._custom_param_update_time: float = -CUSTOM_PARAM_UPDATE_TIME
    self.custom_publisher = CustomPublisher(self.params)
    self.auto_power_off = AutoPowerOffController(self.params)
    # #custom end

    # UI Status tracking
    self.status: UIStatus = UIStatus.DISENGAGED
    self.started_frame: int = 0
    self.started_time: float = 0.0
    self._engaged_prev: bool = False
    self._started_prev: bool = False

    # Core state variables
    self.is_metric: bool = self.params.get_bool("IsMetric")
    self.is_release = self.params.get_bool("IsReleaseBranch")
    self.always_on_dm: bool = self.params.get_bool("AlwaysOnDM")
    self.started: bool = False
    self.ignition: bool = False
    self.recording_audio: bool = False
    self.panda_type: log.PandaState.PandaType = log.PandaState.PandaType.unknown
    self.personality: log.LongitudinalPersonality = log.LongitudinalPersonality.standard
    self.has_longitudinal_control: bool = False
    self.is_body: bool | None = None
    self.CP: car.CarParams | None = None
    self.light_sensor: float = -1.0
    self._param_update_time: float = -PARAM_UPDATE_TIME

    # Callbacks
    self._offroad_transition_callbacks: list[Callable[[], None]] = []
    self._engaged_transition_callbacks: list[Callable[[], None]] = []
    self._on_body_changed_callbacks: list[Callable[[], None]] = []

  def add_offroad_transition_callback(self, callback: Callable[[], None]):
    self._offroad_transition_callbacks.append(callback)

  def add_engaged_transition_callback(self, callback: Callable[[], None]):
    self._engaged_transition_callbacks.append(callback)

  def add_on_body_changed_callbacks(self, callback: Callable[[], None]):
    self._on_body_changed_callbacks.append(callback)

  @property
  def engaged(self) -> bool:
    return self.started and self.sm["selfdriveState"].enabled

  def is_onroad(self) -> bool:
    return self.started

  def is_offroad(self) -> bool:
    return not self.started

  def update(self) -> None:
    self.prime_state.start()  # start thread after manager forks ui
    self.sm.update(0)
    self._update_state()
    self._update_status()
    if time.monotonic() - self._param_update_time >= PARAM_UPDATE_TIME:
      self.update_params()
    # #custom start: publish custom UI tuning state
    if time.monotonic() - self._custom_param_update_time >= CUSTOM_PARAM_UPDATE_TIME:
      self.custom_params = read_custom_params(self.params)
      self._custom_param_update_time = time.monotonic()
    self.custom_publisher.update()
    self.auto_power_off.update(self.started, self.ignition, self.sm["carState"].vEgo)
    # #custom end
    device.update()

  def _update_state(self) -> None:
    # Handle panda states updates
    if self.sm.updated["pandaStates"]:
      panda_states = self.sm["pandaStates"]

      if len(panda_states) > 0:
        # Get panda type from first panda
        self.panda_type = panda_states[0].pandaType
        # Check ignition status across all pandas
        if self.panda_type != log.PandaState.PandaType.unknown:
          self.ignition = any(state.ignitionLine or state.ignitionCan for state in panda_states)
    elif self.sm.frame - self.sm.recv_frame["pandaStates"] > 5 * rl.get_fps():
      self.panda_type = log.PandaState.PandaType.unknown

    # Handle wide road camera state updates
    if self.sm.updated["wideRoadCameraState"]:
      cam_state = self.sm["wideRoadCameraState"]
      self.light_sensor = max(100.0 - cam_state.exposureValPercent, 0.0)
    elif not self.sm.alive["wideRoadCameraState"] or not self.sm.valid["wideRoadCameraState"]:
      self.light_sensor = -1

    # Update started state
    if CAMERA_SIM:
      self.ignition = True
      self.started = True
    else:
      self.started = self.sm["deviceState"].started and self.ignition

    # Update recording audio state
    self.recording_audio = self.params.get_bool("RecordAudio") and self.started

    self.is_metric = self.params.get_bool("IsMetric")
    self.always_on_dm = self.params.get_bool("AlwaysOnDM")

  def _update_status(self) -> None:
    if self.started and self.sm.updated["selfdriveState"]:
      ss = self.sm["selfdriveState"]
      state = ss.state

      if state in (log.SelfdriveState.OpenpilotState.preEnabled, log.SelfdriveState.OpenpilotState.overriding):
        self.status = UIStatus.OVERRIDE
      else:
        self.status = UIStatus.ENGAGED if ss.enabled else UIStatus.DISENGAGED

    # Check for engagement state changes
    if self.engaged != self._engaged_prev:
      for callback in self._engaged_transition_callbacks:
        callback()
      self._engaged_prev = self.engaged

    # Handle onroad/offroad transition
    if self.started != self._started_prev or self.sm.frame == 1:
      if self.started:
        self.status = UIStatus.DISENGAGED
        self.started_frame = self.sm.frame
        self.started_time = time.monotonic()

      for callback in self._offroad_transition_callbacks:
        callback()

      self._started_prev = self.started

  def update_params(self) -> None:
    # For slower operations
    # Update longitudinal control state
    CP_bytes = self.params.get("CarParamsPersistent")
    if CP_bytes is not None:
      self.CP = messaging.log_from_bytes(CP_bytes, car.CarParams)
      if self.CP.alphaLongitudinalAvailable:
        self.has_longitudinal_control = self.params.get_bool("AlphaLongitudinalEnabled")
      else:
        self.has_longitudinal_control = self.CP.openpilotLongitudinalControl

      if self.is_body != self.CP.notCar:
        self.is_body = self.CP.notCar
        for callback in self._on_body_changed_callbacks:
          callback()

    self._param_update_time = time.monotonic()


class Device:
  def __init__(self):
    self._ignition = False
    self._interaction_time: float = -1
    self._override_interactive_timeout: int | None = None
    self._interactive_timeout_callbacks: list[Callable] = []
    self._prev_timed_out = False
    self._awake: bool = True
    self._cmd_awake: bool = True

    self._offroad_brightness: int = BACKLIGHT_OFFROAD
    self._last_brightness: int = 0
    self._brightness_filter = FirstOrderFilter(BACKLIGHT_OFFROAD, 10.00, 1 / gui_app.target_fps)
    self._brightness_thread: threading.Thread | None = None
    self._fade_active = False
    self._fade_start = 0.0
    self._fade_duration = 0.0
    self._fade_from = 0.0
    self._fade_to = 0.0

  @property
  def awake(self) -> bool:
    return self._awake

  def set_override_interactive_timeout(self, timeout: int | None) -> None:
    # Override the interactive timeout duration temporarily
    self._override_interactive_timeout = timeout
    self._reset_interactive_timeout()

  @property
  def interactive_timeout(self) -> int | None:
    if self._override_interactive_timeout is not None:
      return self._override_interactive_timeout

    timeout_steps = int(ui_state.custom_params["ParamAutoScreenOff"])
    if timeout_steps <= 0:
      return None
    return timeout_steps * 10

  def _reset_interactive_timeout(self) -> None:
    timeout = self.interactive_timeout
    self._interaction_time = float("inf") if timeout is None else time.monotonic() + timeout

  def add_interactive_timeout_callback(self, callback: Callable):
    self._interactive_timeout_callbacks.append(callback)

  def update(self):
    # do initial reset
    if self._interaction_time <= 0:
      self._reset_interactive_timeout()

    self._update_wakefulness()
    self._update_brightness()

  def set_offroad_brightness(self, brightness: int | None):
    if brightness is None:
      brightness = BACKLIGHT_OFFROAD
    self._offroad_brightness = min(max(brightness, 0), 100)

  def _update_brightness(self):
    clipped_brightness = self._offroad_brightness

    if ui_state.started and ui_state.light_sensor >= 0:
      clipped_brightness = ui_state.light_sensor

      # CIE 1931 - https://www.photonstophotos.net/GeneralTopics/Exposure/Psychometric_Lightness_and_Gamma.htm
      if clipped_brightness <= 8:
        clipped_brightness = clipped_brightness / 903.3
      else:
        clipped_brightness = ((clipped_brightness + 16.0) / 116.0) ** 3.0

      clipped_brightness = float(np.interp(clipped_brightness, [0, 1], [30, 100]))

    brightness_offset = int(ui_state.custom_params["ParamBrightness"])
    if brightness_offset != 0:
      brightness_scale = min(max(1.0 + brightness_offset * 0.05, 0.2), 2.0)
      clipped_brightness = min(max(clipped_brightness * brightness_scale, 1.0), 100.0)

    clipped_brightness = self._apply_idle_dim(clipped_brightness)
    filtered_brightness = round(self._brightness_filter.update(clipped_brightness))
    brightness = self._fade_brightness(filtered_brightness)

    if brightness != self._last_brightness:
      if self._brightness_thread is None or not self._brightness_thread.is_alive():
        self._brightness_thread = threading.Thread(target=HARDWARE.set_screen_brightness, args=(brightness,))
        self._brightness_thread.start()
        self._last_brightness = brightness

  def _apply_idle_dim(self, brightness: float) -> float:
    timeout = self.interactive_timeout
    if timeout is None or timeout <= 0 or ui_state.ignition or PC:
      return brightness

    remaining = self._interaction_time - time.monotonic()
    dim_window = min(DISPLAY_DIM_MAX_SECONDS, max(DISPLAY_DIM_MIN_SECONDS, timeout / 5.0))
    if remaining > dim_window:
      return brightness

    progress = min(max((dim_window - remaining) / dim_window, 0.0), 1.0)
    dim_scale = DISPLAY_DIM_START + (DISPLAY_DIM_END - DISPLAY_DIM_START) * progress
    return min(brightness, max(DISPLAY_DIM_MIN_BRIGHTNESS, brightness * dim_scale))

  def _fade_brightness(self, target: int) -> int:
    if not self._cmd_awake and not self._fade_active:
      return self._sleep_brightness_target()

    if not self._fade_active:
      return target

    if self._cmd_awake:
      self._fade_to = float(target)

    elapsed = time.monotonic() - self._fade_start
    progress = min(max(elapsed / max(self._fade_duration, 1e-3), 0.0), 1.0)
    eased = progress * progress * (3.0 - 2.0 * progress)
    brightness = round(self._fade_from + (self._fade_to - self._fade_from) * eased)

    if progress >= 1.0:
      self._fade_active = False
      brightness = round(self._fade_to)
      if not self._cmd_awake and self._screen_off_after_fade():
        self._set_display_awake(False)

    return min(max(brightness, 0), 100)

  def _start_brightness_fade(self, on: bool) -> None:
    self._fade_active = True
    self._fade_start = time.monotonic()
    self._fade_duration = DISPLAY_FADE_IN_SECONDS if on else DISPLAY_FADE_OUT_SECONDS
    self._fade_from = float(self._last_brightness)
    self._fade_to = self._fade_from if on else self._sleep_brightness_target()

    if on:
      self._set_display_awake(True)

  def _screen_off_after_fade(self) -> bool:
    return bool(ui_state.custom_params["ParamScreenOffAfterFade"])

  def _sleep_brightness_target(self) -> int:
    return 0 if self._screen_off_after_fade() else round(DISPLAY_DIM_MIN_BRIGHTNESS)

  def _update_wakefulness(self):
    # Handle interactive timeout
    ignition_just_turned_off = not ui_state.ignition and self._ignition
    self._ignition = ui_state.ignition

    if ignition_just_turned_off or self._has_wake_input():
      self._reset_interactive_timeout()

    interaction_timeout = time.monotonic() > self._interaction_time
    if interaction_timeout and not self._prev_timed_out:
      for callback in self._interactive_timeout_callbacks:
        callback()
    self._prev_timed_out = interaction_timeout

    self._set_awake(ui_state.ignition or not interaction_timeout or PC)

  def _set_awake(self, on: bool):
    if on != self._cmd_awake:
      self._cmd_awake = on
      self._start_brightness_fade(on)

  def _has_wake_input(self) -> bool:
    if any(ev.left_down for ev in gui_app.mouse_events):
      return True
    return any(button.type == car.CarState.ButtonEvent.Type.cancel for button in ui_state.sm["carState"].buttonEvents)

  def _set_display_awake(self, on: bool):
    if on != self._awake:
      self._awake = on
      cloudlog.debug(f"setting display power {int(on)}")
      HARDWARE.set_display_power(on)
      gui_app.set_should_render(on)


# Global instance
ui_state = UIState()
device = Device()
