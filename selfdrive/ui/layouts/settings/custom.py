import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pyray as rl
from cereal import car, messaging

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.selfdrive.ui.custom import read_custom_param_map, read_custom_params, write_custom_params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import PC
from openpilot.system.ui.lib.application import FontWeight, MousePos, gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.list_view import ItemAction, ListItem, button_item, text_item, toggle_item
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller


# #custom start: Python port of qt/custom settings panel
MODEL_OPTIONS = [
  "11.POP_Model",
  "10.CD210_Model",
  "9.WMI_Model",
  "8.SC_Driving",
  "7.MacroStiff_Model",
  "6.Dark_Souls_2",
  "5.North_Nevada",
  "4.The_Cool_Peoples",
  "3.Firehose",
  "2.Steam_Powered",
  "1.Stock_Model",
]
DEFAULT_MODEL_NAME = "1.Stock_Model"
DEFAULT_MODEL_NAMES = {DEFAULT_MODEL_NAME, "1.default", "7.Current_Model", "7.Current_0.11_6a7d09ad"}

EXTERNAL_NAVI_OPTIONS = ["0", "1", "2"]
CAR_TRACKING_DESCRIPTION = tr_noop(
  "Shows a separate CAR TRACKING panel on the onroad screen.<br>"
  "EGO / LEFT / RIGHT: Fuses liveTracks radar points with modelV2 leadsV3 camera candidates, then selects the nearest lead in each lane.<br>"
  "If multiple candidates are in the same lane, one candidate is selected by source priority: FUSED, CAMERA, then RADAR. Ties use the nearest distance.<br>"
  "EGO uses modelV2 path/laneLines at the lead distance when available, so curved roads follow the model lane shape. If lane lines are weak, it falls back to the path center and radarState yRel side offset.<br>"
  "The lead triangle uses the same classification: yellow for EGO, blue for LEFT, green for RIGHT, and red for close or fast-closing leads.<br>"
  "Source shows RADAR#, CAMERA, or FUSED when radar and camera candidates match. If both are unavailable, it falls back to radarState leadOne/leadTwo.<br>"
  "SCC: Shows stock SCC lead distance and current gap from carState.carSCustom when supported vehicle CAN data is available.<br>"
  "If no lead data is available, the panel still appears and displays none so you can confirm the feature is enabled.<br>"
  "This is a visual/debug overlay only; it does not change longitudinal control, radar matching, or cruise behavior."
)
CRUISE_MODE_DESCRIPTION = tr_noop(
  "0: Disabled. Custom cruise button control is not used.<br>"
  "1-15: Enabled. Current code treats all non-zero values the same; higher numbers are reserved for future modes.<br>"
  "When enabled on supported Hyundai stock SCC paths, openpilot simulates RES/SET button presses to move the vehicle cruise set speed toward the planned speed. "
  "It is inactive when openpilot longitudinal control is enabled, when ACC is off, while braking, or while another cruise button is pressed. "
  "If Cruise gap matches the vehicle gap, the target follows longitudinalPlan speed; otherwise it holds the current custom set speed."
)
STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
COMPILE_STATUS_KEY = "CustomModelCompileStatus"
COMPILE_NAME_KEY = "CustomModelCompileName"
COMPILE_STARTED_AT_KEY = "CustomModelCompileStartedAt"
COMPILE_FINISHED_AT_KEY = "CustomModelCompileFinishedAt"
COMPILE_ERROR_KEY = "CustomModelCompileError"
COMPILE_PROGRESS_KEY = "CustomModelCompileProgress"
CUSTOM_TMP_ROOT = Path("/tmp") if PC else Path("/data/tmp")
COMPILE_LOG_PATH = str(CUSTOM_TMP_ROOT / "openpilot_custom_model_compile.log")
COMPILE_STATUS_CHECK_INTERVAL = 5.0
COMPILE_LOG_CACHE_INTERVAL = 2.0
COMPILE_PROCESS_GRACE_SECONDS = 60
COMPILE_STALE_SECONDS = 2 * 60 * 60
GIT_STATUS_KEY = "CustomGitUpdateStatus"
GIT_ERROR_KEY = "CustomGitUpdateError"
GIT_LOG_PATH = str(CUSTOM_TMP_ROOT / "openpilot_git_update.log")
SPEED_CAMERA_STATUS_KEY = "SpeedCameraUpdateStatus"
SPEED_CAMERA_ERROR_KEY = "SpeedCameraUpdateError"
SPEED_CAMERA_COUNT_KEY = "SpeedCameraUpdateCount"
SPEED_CAMERA_PROGRESS_KEY = "SpeedCameraUpdateProgress"
SPEED_CAMERA_UPDATED_AT_KEY = "SpeedCameraUpdatedAt"
SPEED_CAMERA_LOG_PATH = str(CUSTOM_TMP_ROOT / "openpilot_speed_camera_update.log")
REPO_ROOT = Path(BASEDIR)
MODELD_DIR = REPO_ROOT / "selfdrive/modeld"
TAB_HEIGHT = 110
TAB_GAP = 10
TAB_FONT_SIZE = 40
TAB_FONT_MIN_SIZE = 28
TAB_RADIUS = 0.35
TAB_SELECTED = rl.Color(245, 245, 245, 255)
TAB_NORMAL = rl.BLACK
TAB_PRESSED = rl.Color(35, 35, 35, 255)
TAB_BORDER = rl.Color(196, 196, 195, 255)
TAB_TEXT = rl.WHITE
TAB_TEXT_SELECTED = rl.BLACK
STEPPER_BUTTON_WIDTH = 120
STEPPER_VALUE_WIDTH = 170
STEPPER_HEIGHT = 100
STEPPER_GAP = 20
STEPPER_FONT_SIZE = 48
STEPPER_BUTTON_FONT_SIZE = 52
STEPPER_BUTTON_COLOR = rl.Color(57, 57, 57, 255)
STEPPER_BUTTON_PRESSED = rl.Color(74, 74, 74, 255)
STEPPER_VALUE_COLOR = rl.Color(170, 170, 170, 255)
SECTION_HEIGHT = 92
SECTION_FONT_SIZE = 42
SECTION_BG = rl.Color(58, 58, 58, 255)
COMPILE_LOG_HEIGHT = 500
COMPILE_LOG_TITLE_FONT_SIZE = 42
COMPILE_LOG_FONT_SIZE = 28
COMPILE_LOG_LINE_HEIGHT = 34
COMPILE_LOG_PADDING = 26
COMPILE_LOG_BG = rl.Color(23, 23, 23, 255)
COMPILE_LOG_BORDER = rl.Color(96, 96, 96, 255)
COMPILE_LOG_TEXT = rl.Color(190, 190, 190, 255)


def run_logged(command: list[str], cwd: Path, log_path: str) -> subprocess.CompletedProcess:
  Path(log_path).parent.mkdir(parents=True, exist_ok=True)
  with open(log_path, "a", encoding="utf-8") as log_file:
    log_file.write(f"\n$ {' '.join(command)}\n")
    log_file.flush()
    return subprocess.run(command, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT, text=True, check=False)


def clear_log(log_path: str) -> None:
  path = Path(log_path)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text("", encoding="utf-8")


def valid_branch_name(branch: str) -> bool:
  if not branch or branch.startswith("-"):
    return False
  return subprocess.run(["git", "check-ref-format", "--branch", branch],
                        cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def origin_branch_exists(branch: str) -> bool:
  return subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
                        cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


class StepperAction(ItemAction):
  def __init__(self, value_text: Callable[[], str], minus_callback: Callable[[], None], plus_callback: Callable[[], None]):
    super().__init__(width=STEPPER_BUTTON_WIDTH * 2 + STEPPER_VALUE_WIDTH + STEPPER_GAP * 2)
    self._value_text = value_text
    self._minus_callback = minus_callback
    self._plus_callback = plus_callback
    self._font = gui_app.font(FontWeight.NORMAL)
    self._button_font = gui_app.font(FontWeight.MEDIUM)
    self._minus_rect = rl.Rectangle(0, 0, 0, 0)
    self._plus_rect = rl.Rectangle(0, 0, 0, 0)

  def _render(self, rect: rl.Rectangle) -> bool:
    y = rect.y + (rect.height - STEPPER_HEIGHT) / 2
    self._minus_rect = rl.Rectangle(rect.x, y, STEPPER_BUTTON_WIDTH, STEPPER_HEIGHT)
    value_rect = rl.Rectangle(
      self._minus_rect.x + self._minus_rect.width + STEPPER_GAP,
      y,
      STEPPER_VALUE_WIDTH,
      STEPPER_HEIGHT,
    )
    self._plus_rect = rl.Rectangle(value_rect.x + value_rect.width + STEPPER_GAP, y, STEPPER_BUTTON_WIDTH, STEPPER_HEIGHT)

    self._draw_button(self._minus_rect, "-")
    self._draw_value(value_rect)
    self._draw_button(self._plus_rect, "+")
    return False

  def _draw_button(self, rect: rl.Rectangle, label: str) -> None:
    pressed = self.is_pressed and rl.check_collision_point_rec(rl.get_mouse_position(), rect)
    color = STEPPER_BUTTON_PRESSED if pressed else STEPPER_BUTTON_COLOR
    if not self.enabled:
      color = rl.Color(color.r, color.g, color.b, 100)
    rl.draw_rectangle_rounded(rect, 1.0, 20, color)
    text_size = measure_text_cached(self._button_font, label, STEPPER_BUTTON_FONT_SIZE)
    text_pos = rl.Vector2(rect.x + (rect.width - text_size.x) / 2, rect.y + (rect.height - text_size.y) / 2)
    text_color = TAB_TEXT if self.enabled else rl.Color(TAB_TEXT.r, TAB_TEXT.g, TAB_TEXT.b, 100)
    rl.draw_text_ex(self._button_font, label, text_pos, STEPPER_BUTTON_FONT_SIZE, 0, text_color)

  def _draw_value(self, rect: rl.Rectangle) -> None:
    label = self._value_text()
    text_size = measure_text_cached(self._font, label, STEPPER_FONT_SIZE)
    text_pos = rl.Vector2(rect.x + (rect.width - text_size.x) / 2, rect.y + (rect.height - text_size.y) / 2)
    text_color = STEPPER_VALUE_COLOR if self.enabled else rl.Color(STEPPER_VALUE_COLOR.r, STEPPER_VALUE_COLOR.g, STEPPER_VALUE_COLOR.b, 100)
    rl.draw_text_ex(self._font, label, text_pos, STEPPER_FONT_SIZE, 0, text_color)

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    if not self.enabled:
      return
    if rl.check_collision_point_rec(mouse_pos, self._minus_rect):
      self._minus_callback()
    elif rl.check_collision_point_rec(mouse_pos, self._plus_rect):
      self._plus_callback()


class SectionHeader(Widget):
  def __init__(self, title: str):
    super().__init__()
    self._title = title
    self._font = gui_app.font(FontWeight.MEDIUM)
    self.set_rect(rl.Rectangle(0, 0, 0, SECTION_HEIGHT))

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.15, 12, SECTION_BG)
    label = tr(self._title)
    text_size = measure_text_cached(self._font, label, SECTION_FONT_SIZE)
    text_pos = rl.Vector2(rect.x + 32, rect.y + (rect.height - text_size.y) / 2)
    rl.draw_text_ex(self._font, label, text_pos, SECTION_FONT_SIZE, 0, TAB_TEXT)


class CompileLogPanel(Widget):
  def __init__(self, title: str, lines_callback: Callable[[], list[str]]):
    super().__init__()
    self._title = title
    self._lines_callback = lines_callback
    self._font_regular = gui_app.font(FontWeight.NORMAL)
    self._font_bold = gui_app.font(FontWeight.MEDIUM)
    self.set_rect(rl.Rectangle(0, 0, 0, COMPILE_LOG_HEIGHT))

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, rect: rl.Rectangle):
    title = tr(self._title)
    title_size = measure_text_cached(self._font_bold, title, COMPILE_LOG_TITLE_FONT_SIZE)
    title_y = rect.y + COMPILE_LOG_PADDING
    rl.draw_text_ex(self._font_bold, title, rl.Vector2(rect.x + COMPILE_LOG_PADDING, title_y),
                    COMPILE_LOG_TITLE_FONT_SIZE, 0, rl.WHITE)

    log_rect = rl.Rectangle(
      rect.x + COMPILE_LOG_PADDING,
      title_y + title_size.y + 18,
      rect.width - COMPILE_LOG_PADDING * 2,
      rect.height - title_size.y - COMPILE_LOG_PADDING * 2 - 18,
    )
    rl.draw_rectangle_rounded(log_rect, 0.04, 8, COMPILE_LOG_BG)
    rl.draw_rectangle_rounded_lines_ex(log_rect, 0.04, 8, 2, COMPILE_LOG_BORDER)

    lines = self._fit_lines(self._lines_callback(), log_rect.width - COMPILE_LOG_PADDING * 2)
    max_lines = max(1, int((log_rect.height - COMPILE_LOG_PADDING * 2) // COMPILE_LOG_LINE_HEIGHT))
    visible_lines = lines[-max_lines:]

    rl.begin_scissor_mode(int(log_rect.x), int(log_rect.y), int(log_rect.width), int(log_rect.height))
    y = log_rect.y + COMPILE_LOG_PADDING
    for line in visible_lines:
      rl.draw_text_ex(self._font_regular, line, rl.Vector2(log_rect.x + COMPILE_LOG_PADDING, y),
                      COMPILE_LOG_FONT_SIZE, 0, COMPILE_LOG_TEXT)
      y += COMPILE_LOG_LINE_HEIGHT
    rl.end_scissor_mode()

  def _fit_lines(self, lines: list[str], max_width: float) -> list[str]:
    fitted: list[str] = []
    for line in lines:
      fitted.append(self._truncate_line(line, max_width))
    return fitted or [tr("No compile log yet")]

  def _truncate_line(self, line: str, max_width: float) -> str:
    text = line.expandtabs(2).strip()
    if measure_text_cached(self._font_regular, text, COMPILE_LOG_FONT_SIZE).x <= max_width:
      return text

    ellipsis = "..."
    while text and measure_text_cached(self._font_regular, text + ellipsis, COMPILE_LOG_FONT_SIZE).x > max_width:
      text = text[:-1]
    return (text.rstrip() + ellipsis) if text else ellipsis


class CustomSettingsLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._dialog: MultiOptionDialog | None = None
    self._last_compile_status_check = -COMPILE_STATUS_CHECK_INTERVAL
    self._last_compile_log_check = -COMPILE_LOG_CACHE_INTERVAL
    self._compile_log_tail = ""
    self._current_tab = "UI"
    self._tab_rects: dict[str, rl.Rectangle] = {}
    self._tab_font = gui_app.font(FontWeight.MEDIUM)
    self._sections = {
      "UI": [
        SectionHeader(tr_noop("Toggle def")),
        self._toggle_json_item("ShowDebugMessage", tr_noop("Debug overlay"),
                               tr_noop("Shows the three-line trace debug panel on the onroad screen.")),
        self._toggle_param_item("DisableUpdates", tr_noop("Disable OTA updates"),
                                tr_noop("Prevents the updater from downloading and applying openpilot updates.")),
        self._toggle_json_item("ShowCarTracking", tr_noop("Show car tracking"),
                               CAR_TRACKING_DESCRIPTION),
        self._toggle_json_item("tpms", tr_noop("Show TPMS"),
                               tr_noop("Shows tire pressure values around the driver monitoring icon when TPMS data is available.")),
        self._toggle_json_item("kegmanBattery", tr_noop("Battery voltage"),
                               tr_noop("Shows battery voltage in the sidebar status area.")),
        SectionHeader(tr_noop("Kegman Show")),
        self._toggle_json_item("kegman", tr_noop("HUD overlay"),
                               tr_noop("Shows the custom Kegman information panel on the onroad screen.")),
        self._toggle_json_item("kegmanCPU", tr_noop("CPU temperature"),
                               tr_noop("Adds CPU temperature to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanLag", tr_noop("UI lag"),
                               tr_noop("Adds UI render lag to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanGPS", tr_noop("GPS accuracy"),
                               tr_noop("Adds GPS accuracy information to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanGPULoad", tr_noop("GPU load"),
                               tr_noop("Adds GPU load to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanAngle", tr_noop("Steering angle"),
                               tr_noop("Adds current steering angle to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanEngine", tr_noop("Engine status"),
                               tr_noop("Adds engine or EV status to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanDistance", tr_noop("Relative distance"),
                               tr_noop("Adds lead vehicle distance to the Kegman onroad panel when lead data is available."),
                               enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanSpeed", tr_noop("Relative speed"),
                               tr_noop("Adds lead vehicle relative speed to the Kegman onroad panel when lead data is available."),
                               enabled=self._kegman_enabled),
      ],
      "Community": [
        SectionHeader(tr_noop("Cruise Settings")),
        self._number_item("ParamCruiseMode", tr_noop("Cruise mode"), 0, 15, 1,
                          CRUISE_MODE_DESCRIPTION),
        self._number_item("ParamCruiseGap", tr_noop("Cruise gap"), 0, 4, 1,
                          tr_noop("Sets the custom cruise following gap when a non-zero cruise mode is selected."),
                          enabled=lambda: int(self._values()["ParamCruiseMode"]) != 0),
        self._number_item("ParamCurveSpeedLimit", tr_noop("Curve speed adjust"), 30, 100, 5,
                          tr_noop("Sets the curve speed adjustment percentage used by supported vehicle code.")),
        self._number_item("ParamAutoEngage", tr_noop("Auto cruise engage speed"), 30, 100, 5,
                          tr_noop("Sets the speed threshold used for automatic cruise engagement on supported vehicles.")),
        self._number_item("ParamAutoLaneChange", tr_noop("Auto lane change delay"), 0, 100, 10,
                          tr_noop("Sets the custom auto lane change delay used by supported vehicles.")),
        self._number_item("ParamSteerRatio", tr_noop("Steering ratio"), -0.2, 0.2, 0.01,
                          tr_noop("Applies a small steering ratio adjustment for supported custom lateral tuning.")),
        self._number_item("ParamStiffnessFactor", tr_noop("Lateral stiffness factor"), -0.1, 0.1, 0.01,
                          tr_noop("Applies a small lateral stiffness adjustment for supported custom tuning.")),
        self._number_item("ParamAngleOffsetDeg", tr_noop("Steering angle offset"), -2.0, 2.0, 0.1,
                          tr_noop("Applies a steering angle offset in degrees for supported custom tuning.")),
        SectionHeader(tr_noop("Screen & Power")),
        self._number_item("ParamBrightness", tr_noop("Screen brightness"), -20, 5, 1,
                          tr_noop("Adjusts automatic screen brightness. Negative values dim the screen; positive values brighten it.")),
        self._number_item("ParamAutoScreenOff", tr_noop("Screen timeout"), 0, 120, 1,
                          tr_noop("Sets the idle timeout in 10 second steps before the screen fades while ignition is off.")),
        self._toggle_json_item("ParamScreenOffAfterFade", tr_noop("Screen off after fade"),
                               tr_noop("Turns the display off after fade-out. If disabled, the display stays at minimum brightness.")),
        self._number_item("ParamPowerOff", tr_noop("Power off time"), 0, 60, 1,
                          tr_noop("Sets the delayed power-off timer in minutes after ignition turns off.")),
        self._number_item("DUAL_CAMERA_VIEW", tr_noop("Dual camera view"), 0, 1, 1,
                          tr_noop("Shows road and wide camera views side by side when both streams are available.")),
        SectionHeader(tr_noop("Logging")),
        self._logging_toggle_item(),
        self._selection_item("SelectedCar", tr_noop("Selected car"), self._car_options,
                             tr_noop("Overrides the selected vehicle fingerprint when a supported car option is available.")),
      ],
      "Git": [
        self._command_item(tr_noop("Fetch All and Prune"), tr_noop("SYNC"), ["bash", "-lc", "git fetch --all --prune && git remote prune origin"],
                           confirm=False, description=tr_noop("Fetches remote branch updates and removes stale remote-tracking branches.")),
        self._update_from_remote_item(),
        text_item(lambda: tr("Git status"), self._git_update_status_text,
                  description=lambda: tr("Shows the latest custom Git operation status.")),
      ],
      "Model": [
        self._model_selection_item(),
        text_item(lambda: tr("Compile status"), self._compile_status_text,
                  description=lambda: tr("Shows the current custom model compile state, progress, and last error.")),
        CompileLogPanel(tr_noop("Compile detail"), self._compile_log_lines),
      ],
      "Debug": [
        self._toggle_json_item("debug1", tr_noop("Debug 1"), tr_noop("Enables custom debug flag 1 for supported vehicle or UI code.")),
        self._toggle_json_item("debug2", tr_noop("Debug 2"), tr_noop("Enables custom debug flag 2 for supported vehicle or UI code.")),
        self._toggle_json_item("debug3", tr_noop("Debug 3"), tr_noop("Enables custom debug flag 3 for supported vehicle or UI code.")),
        self._toggle_json_item("debug4", tr_noop("Debug 4"), tr_noop("Enables custom debug flag 4 for supported vehicle or UI code.")),
        self._toggle_json_item("debug5", tr_noop("Debug 5"), tr_noop("Enables custom debug flag 5 for supported vehicle or UI code.")),
        self._toggle_json_item("debug6", tr_noop("Debug 6"), tr_noop("Enables custom debug flag 6 for supported vehicle or UI code.")),
      ],
      "Navigation": [
        self._speed_camera_update_item(),
        text_item(lambda: tr("Speed camera status"), self._speed_camera_status_text,
                  description=lambda: tr("Shows the last public speed camera CSV download and DB import result.")),
        text_item(lambda: tr("Speed camera progress"), self._speed_camera_progress_text,
                  description=lambda: tr("Shows download and import progress for the speed camera DB update.")),
        SectionHeader(tr_noop("Speed camera tuning")),
        self._number_item("SpeedCameraLookaheadDistance", tr_noop("Camera search distance"), 500, 3000, 100,
                          tr_noop("Sets how far ahead, in meters, the speed camera lookup searches.")),
        self._number_item("SpeedCameraLookaheadAngle", tr_noop("Camera search angle"), 15, 60, 5,
                          tr_noop("Sets the allowed angle from the current driving heading to a candidate camera.")),
        self._number_item("SpeedCameraDirectionAngle", tr_noop("Camera direction angle"), 30, 90, 5,
                          tr_noop("Sets the allowed difference between the public DB road direction and current driving heading.")),
        self._number_item("SpeedCameraPassingDistance", tr_noop("Camera passing distance"), 10, 80, 5,
                          tr_noop("Sets the distance, in meters, used to mark a camera as passed.")),
        self._number_item("SpeedCameraPassedIgnoreSeconds", tr_noop("Camera ignore time"), 3, 30, 1,
                          tr_noop("Sets how long, in seconds, a passed camera is hidden from repeated alerts.")),
        self._toggle_param_item("UseExternalNaviRoutes", tr_noop("Use external navi routes"),
                                tr_noop("Allows navigation to use routes from an external navigation provider.")),
        self._cycle_param_int_item("ExternalNaviType", tr_noop("External navi type"), EXTERNAL_NAVI_OPTIONS,
                                   tr_noop("Selects the external navigation provider type.")),
        self._text_edit_item("MapboxToken", tr_noop("Mapbox token"),
                             tr_noop("Sets the Mapbox access token used by map and navigation features.")),
      ],
    }
    self._scrollers = {name: Scroller(items, line_separator=True, spacing=0) for name, items in self._sections.items()}

  def _values(self):
    return read_custom_params(self._params)

  def _save_value(self, key: str, value: int | float | bool) -> None:
    write_custom_params({key: value}, self._params)
    ui_state.custom_publisher.update(force=True)

  def _kegman_enabled(self) -> bool:
    values = self._values()
    return bool(values["kegman"])

  @staticmethod
  def _decimals(step: int | float) -> int:
    step_text = f"{step:.10f}".rstrip("0").rstrip(".")
    return len(step_text.partition(".")[2])

  def _number_item(
    self,
    key: str,
    title: str,
    min_value: int | float,
    max_value: int | float,
    step_size: int | float,
    description: str | None = None,
    enabled: bool | Callable[[], bool] = True,
  ):
    decimals = self._decimals(step_size)

    def current_numeric() -> int | float:
      value = self._values()[key]
      return float(value) if decimals else int(value)

    def current_value() -> str:
      value = current_numeric()
      return f"{float(value):.{decimals}f}" if decimals else str(int(value))

    def step(delta: int) -> None:
      next_value = current_numeric() + delta * step_size
      next_value = max(min_value, min(max_value, next_value))
      if decimals:
        next_value = round(float(next_value), decimals)
      else:
        next_value = int(next_value)
      self._save_value(key, next_value)

    action = StepperAction(current_value, lambda: step(-1), lambda: step(1))
    action.set_enabled(enabled)
    return ListItem(title=lambda: tr(title), description=(lambda: tr(description)) if description else None, action_item=action)

  def _cycle_item(self, key: str, title: str, options: list[str], convert: Callable[[str], int | float]):
    def current_value() -> str:
      value = self._values()[key]
      if isinstance(value, float):
        return f"{value:.2f}"
      return str(value)

    def step(delta: int) -> None:
      current = current_value()
      try:
        idx = options.index(current)
      except ValueError:
        idx = 0
      next_idx = max(0, min(len(options) - 1, idx + delta))
      self._save_value(key, convert(options[next_idx]))

    action = StepperAction(current_value, lambda: step(-1), lambda: step(1))
    return ListItem(title=lambda: tr(title), action_item=action)

  def _cycle_int_item(self, key: str, title: str, options: list[str]):
    return self._cycle_item(key, title, options, int)

  def _cycle_float_item(self, key: str, title: str, options: list[str]):
    return self._cycle_item(key, title, options, float)

  def _toggle_json_item(self, key: str, title: str, description: str | None = None, enabled: bool | Callable[[], bool] = True):
    return toggle_item(
      lambda: tr(title),
      description=(lambda: tr(description)) if description else None,
      initial_state=bool(self._values()[key]),
      callback=lambda state, k=key: self._save_value(k, bool(state)),
      enabled=enabled,
    )

  def _toggle_param_item(self, key: str, title: str, description: str | None = None):
    return toggle_item(
      lambda: tr(title),
      description=(lambda: tr(description)) if description else None,
      initial_state=self._params.get_bool(key),
      callback=lambda state, k=key: self._params.put_bool(k, bool(state)),
    )

  def _logging_toggle_item(self):
    def logging_enabled() -> bool:
      enable_logging = self._params.get("EnableLogging")
      enabled = True if enable_logging is None else self._params.get_bool("EnableLogging")
      return enabled and not self._params.get_bool("DisableLogging")

    def set_logging_enabled(state: bool) -> None:
      self._params.put_bool("EnableLogging", bool(state))
      self._params.put_bool("DisableLogging", not bool(state))

    return toggle_item(
      lambda: tr(tr_noop("Enable logging")),
      description=lambda: tr("Enables route logging and upload-related logger processes when logging is allowed."),
      initial_state=logging_enabled(),
      callback=set_logging_enabled,
    )

  def _cycle_param_int_item(self, key: str, title: str, options: list[str], description: str | None = None):
    def current_value() -> str:
      raw = self._param_text(key)
      return raw if raw in options else options[0]

    def step(delta: int) -> None:
      try:
        idx = options.index(current_value())
      except ValueError:
        idx = 0
      next_idx = max(0, min(len(options) - 1, idx + delta))
      self._params.put(key, options[next_idx])

    action = StepperAction(current_value, lambda: step(-1), lambda: step(1))
    return ListItem(title=lambda: tr(title), description=(lambda: tr(description)) if description else None, action_item=action)

  def _command_item(self, title: str, button_text: str, command: list[str], confirm: bool, description: str | None = None):
    def run() -> None:
      def worker() -> None:
        self._set_git_status(STATUS_RUNNING)
        clear_log(GIT_LOG_PATH)
        result = run_logged(command, REPO_ROOT, GIT_LOG_PATH)
        status = STATUS_SUCCESS if result.returncode == 0 else STATUS_FAILED
        error = "" if result.returncode == 0 else f"exit code {result.returncode}"
        self._set_git_status(status, error)

      threading.Thread(target=worker, daemon=True).start()

    def callback() -> None:
      if not confirm:
        run()
        return

      dialog = ConfirmDialog(tr("Are you sure?"), tr(button_text), callback=lambda result: run() if result == DialogResult.CONFIRM else None)
      gui_app.push_widget(dialog)

    return button_item(lambda: tr(title), lambda: tr(button_text),
                       description=(lambda: tr(description)) if description else None, callback=callback)

  def _update_from_remote_item(self):
    def callback() -> None:
      branch = self._param_text("GitBranch") or "test1-custom-port"

      def run() -> None:
        def worker() -> None:
          self._set_git_status(STATUS_RUNNING)
          clear_log(GIT_LOG_PATH)

          if not valid_branch_name(branch):
            self._set_git_status(STATUS_FAILED, f"invalid branch: {branch}")
            return

          fetch_result = run_logged(["git", "fetch", "origin"], REPO_ROOT, GIT_LOG_PATH)
          if fetch_result.returncode != 0:
            self._set_git_status(STATUS_FAILED, f"fetch failed: {fetch_result.returncode}")
            return

          if not origin_branch_exists(branch):
            self._set_git_status(STATUS_FAILED, f"missing origin/{branch}")
            return

          reset_result = run_logged(["git", "reset", "--hard", f"origin/{branch}"], REPO_ROOT, GIT_LOG_PATH)
          if reset_result.returncode != 0:
            self._set_git_status(STATUS_FAILED, f"reset failed: {reset_result.returncode}")
            return

          sync_result = run_logged(["git", "submodule", "sync", "--recursive"], REPO_ROOT, GIT_LOG_PATH)
          if sync_result.returncode != 0:
            self._set_git_status(STATUS_FAILED, f"submodule sync failed: {sync_result.returncode}")
            return

          submodule_result = run_logged(["git", "submodule", "update", "--init", "--recursive"], REPO_ROOT, GIT_LOG_PATH)
          if submodule_result.returncode != 0:
            self._set_git_status(STATUS_FAILED, f"submodule update failed: {submodule_result.returncode}")
            return

          self._set_git_status(STATUS_SUCCESS, "")

        threading.Thread(target=worker, daemon=True).start()

      content = tr("Update from remote? This will reset local files to origin branch.")
      dialog = ConfirmDialog(content, tr("Update"), callback=lambda result: run() if result == DialogResult.CONFIRM else None)
      gui_app.push_widget(dialog)

    return button_item(lambda: tr("Update from Remote"), lambda: tr("UPDATE"),
                       description=lambda: tr("Fetches the configured origin branch and resets this checkout to match it."),
                       callback=callback)

  def _speed_camera_update_item(self):
    return button_item(
      lambda: tr("Speed camera DB"),
      self._speed_camera_button_text,
      description=lambda: tr("Downloads the national public unmanned traffic enforcement camera CSV and imports it into the local navigation DB."),
      callback=self._handle_speed_camera_update,
      enabled=lambda: self._speed_camera_update_status() != STATUS_RUNNING,
    )

  def _handle_speed_camera_update(self) -> None:
    def run() -> None:
      def worker() -> None:
        self._params.put(SPEED_CAMERA_STATUS_KEY, STATUS_RUNNING)
        self._params.put(SPEED_CAMERA_ERROR_KEY, "")
        self._params.put(SPEED_CAMERA_PROGRESS_KEY, 0)
        clear_log(SPEED_CAMERA_LOG_PATH)

        result = run_logged([sys.executable, "tools/scripts/update_speed_cameras.py"], REPO_ROOT, SPEED_CAMERA_LOG_PATH)
        if result.returncode != 0:
          self._set_speed_camera_failed(f"exit code {result.returncode}")
          return

        count = self._speed_camera_db_count_from_log()
        self._params.put(SPEED_CAMERA_COUNT_KEY, max(0, count))
        self._params.put(SPEED_CAMERA_PROGRESS_KEY, 100)
        self._params.put(SPEED_CAMERA_UPDATED_AT_KEY, time.strftime("%Y-%m-%d %H:%M"))
        self._params.put(SPEED_CAMERA_STATUS_KEY, STATUS_SUCCESS)
        self._params.put(SPEED_CAMERA_ERROR_KEY, "")

      threading.Thread(target=worker, daemon=True).start()

    content = tr("Download public speed camera CSV and replace the local DB?")
    dialog = ConfirmDialog(content, tr("UPDATE"), callback=lambda result: run() if result == DialogResult.CONFIRM else None)
    gui_app.push_widget(dialog)

  def _speed_camera_update_status(self) -> str:
    return self._param_text(SPEED_CAMERA_STATUS_KEY) or STATUS_IDLE

  def _speed_camera_button_text(self) -> str:
    status = self._speed_camera_update_status()
    if status == STATUS_RUNNING:
      return tr("WAIT")
    if status == STATUS_FAILED:
      return tr("RETRY")
    return tr("UPDATE")

  def _speed_camera_db_count_from_log(self) -> int:
    try:
      with open(SPEED_CAMERA_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        for line in reversed(log_file.readlines()):
          if line.startswith("imported "):
            return int(line.split()[1])
    except (OSError, ValueError, IndexError):
      pass
    return 0

  def _set_speed_camera_failed(self, error: str) -> None:
    try:
      with open(SPEED_CAMERA_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        tail = log_file.read()[-500:].strip()
    except OSError:
      tail = ""
    self._params.put(SPEED_CAMERA_STATUS_KEY, STATUS_FAILED)
    self._params.put(SPEED_CAMERA_ERROR_KEY, tail or error)

  def _speed_camera_progress_text(self) -> str:
    progress = self._param_text(SPEED_CAMERA_PROGRESS_KEY)
    if not progress:
      return "--"
    return f"{progress}%"

  def _speed_camera_status_text(self) -> str:
    status = self._speed_camera_update_status()
    if status == STATUS_RUNNING:
      return tr("Downloading")
    if status == STATUS_SUCCESS:
      count = self._param_text(SPEED_CAMERA_COUNT_KEY) or "0"
      updated_at = self._param_text(SPEED_CAMERA_UPDATED_AT_KEY)
      suffix = f" {updated_at}" if updated_at else ""
      return f"{tr('Ready')} {count}{suffix}"
    if status == STATUS_FAILED:
      error = self._param_text(SPEED_CAMERA_ERROR_KEY)
      if len(error) > 80:
        error = error[-80:]
      return f"{tr('Failed')}: {error}".strip(": ")
    return tr("Idle")

  def _set_git_status(self, status: str, error: str = "") -> None:
    self._params.put(GIT_STATUS_KEY, status)
    self._params.put(GIT_ERROR_KEY, error[-500:])

  def _git_update_status_text(self) -> str:
    status = self._param_text(GIT_STATUS_KEY) or STATUS_IDLE
    if status == STATUS_RUNNING:
      return tr("Running")
    if status == STATUS_SUCCESS:
      return tr("Ready")
    if status == STATUS_FAILED:
      error = self._param_text(GIT_ERROR_KEY)
      if len(error) > 80:
        error = error[-80:]
      return f"{tr('Failed')}: {error}".strip(": ")
    return tr("Idle")

  def _text_edit_item(self, key: str, title: str, description: str | None = None):
    item = button_item(lambda: tr(title), lambda: tr("EDIT"),
                       description=(lambda: tr(description)) if description else None,
                       callback=lambda k=key, t=title: self._show_keyboard(k, t))
    item.action_item.set_value(lambda k=key: self._param_text(k))
    return item

  def _show_keyboard(self, key: str, title: str) -> None:
    keyboard = Keyboard(max_text_size=512, callback=lambda result, k=key: self._handle_keyboard_result(k, keyboard, result))
    keyboard.set_title(tr(title), "")
    keyboard.set_text(self._param_text(key))
    gui_app.push_widget(keyboard)

  def _handle_keyboard_result(self, key: str, keyboard: Keyboard, result: DialogResult) -> None:
    if result == DialogResult.CONFIRM:
      self._params.put(key, keyboard.text)

  def _param_text(self, key: str) -> str:
    raw = self._params.get(key)
    if raw is None:
      return ""
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

  def _selection_item(self, key: str, title: str, options_fn: Callable[[], list[str]], description: str | None = None):
    item = button_item(
      lambda: tr(title),
      lambda: tr("CHANGE"),
      description=(lambda: tr(description)) if description else None,
      callback=lambda k=key, t=title, fn=options_fn: self._show_selection(k, t, fn()),
    )
    item.action_item.set_value(lambda k=key: self._param_text(k))
    return item

  def _model_selection_item(self):
    item = button_item(
      lambda: tr("Active model"),
      self._model_button_text,
      description=lambda: tr("Selects and compiles the active driving model. Retry appears after a failed compile."),
      callback=self._handle_model_button,
      enabled=lambda: self._compile_status() != STATUS_RUNNING,
    )
    item.action_item.set_value(self._active_model_text)
    return item

  def _active_model_text(self) -> str:
    model_name = self._param_text("ActiveModelName")
    return DEFAULT_MODEL_NAME if not model_name or model_name in DEFAULT_MODEL_NAMES else model_name

  def _set_compile_failed(self, model_name: str, error: str) -> None:
    self._params.put(COMPILE_STATUS_KEY, STATUS_FAILED)
    self._params.put(COMPILE_NAME_KEY, model_name)
    self._params.put(COMPILE_FINISHED_AT_KEY, str(int(time.time())))
    self._params.put(COMPILE_ERROR_KEY, error[-500:])

  def _set_compile_success(self, model_name: str) -> None:
    self._params.put(COMPILE_STATUS_KEY, STATUS_SUCCESS)
    self._params.put(COMPILE_NAME_KEY, model_name)
    self._params.put(COMPILE_FINISHED_AT_KEY, str(int(time.time())))
    self._params.put(COMPILE_ERROR_KEY, "")
    self._params.put(COMPILE_PROGRESS_KEY, 100)

  def _compile_progress(self) -> int:
    raw = self._param_text(COMPILE_PROGRESS_KEY)
    try:
      return max(0, min(100, int(raw)))
    except ValueError:
      return 0

  def _compile_process_running(self, model_name: str) -> bool | None:
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
      return None

    process_names = ("model_make.py", "compile_modeld.py", "compile3.py")
    for path in proc_dir.iterdir():
      if not path.name.isdigit():
        continue
      try:
        cmdline = (path / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
      except OSError:
        continue
      if any(process_name in cmdline for process_name in process_names):
        if not model_name or model_name in cmdline or "compile_modeld.py" in cmdline or "compile3.py" in cmdline:
          return True
    return False

  def _refresh_compile_status(self) -> None:
    status = self._param_text(COMPILE_STATUS_KEY)
    if status != STATUS_RUNNING:
      return

    now = time.monotonic()
    if now - self._last_compile_status_check < COMPILE_STATUS_CHECK_INTERVAL:
      return
    self._last_compile_status_check = now

    model_name = self._param_text(COMPILE_NAME_KEY)
    started_at = self._param_text(COMPILE_STARTED_AT_KEY)
    try:
      elapsed = int(time.time()) - int(started_at)
    except ValueError:
      self._set_compile_failed(model_name, "compile status was running without a valid start time")
      return

    if elapsed >= COMPILE_STALE_SECONDS:
      self._set_compile_failed(model_name, f"compile timed out after {elapsed}s")
      return

    process_running = self._compile_process_running(model_name)
    if process_running is False and elapsed >= COMPILE_PROCESS_GRACE_SECONDS:
      self._set_compile_failed(model_name, "compile process stopped before finishing")

  def _compile_status(self) -> str:
    self._refresh_compile_status()
    return self._param_text(COMPILE_STATUS_KEY) or STATUS_IDLE

  def _compile_status_text(self) -> str:
    status = self._compile_status()
    model_name = self._param_text(COMPILE_NAME_KEY)
    if status == STATUS_RUNNING:
      started_at = self._param_text(COMPILE_STARTED_AT_KEY)
      elapsed = ""
      if started_at:
        try:
          elapsed = f" ({max(0, int(time.time()) - int(started_at))}s)"
        except ValueError:
          elapsed = ""
      return f"{tr('Compiling...')} {self._compile_progress()}% {model_name}{elapsed}".strip()
    if status == STATUS_SUCCESS:
      return f"{tr('Ready')} {model_name}".strip()
    if status == STATUS_FAILED:
      error = self._param_text(COMPILE_ERROR_KEY)
      error = error.splitlines()[-1] if error else ""
      if len(error) > 80:
        error = error[-80:]
      return f"{tr('Failed')} {model_name}: {error}".strip(": ")
    return tr("Idle")

  def _compile_log_tail_text(self) -> str:
    lines = self._compile_log_lines()
    return lines[-1][-100:] if lines else ""

  def _compile_log_lines(self) -> list[str]:
    now = time.monotonic()
    if now - self._last_compile_log_check < COMPILE_LOG_CACHE_INTERVAL:
      return self._compile_log_tail.splitlines()
    self._last_compile_log_check = now

    try:
      with open(COMPILE_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        lines = [line.rstrip() for line in log_file.readlines()[-120:]]
    except OSError:
      error = self._param_text(COMPILE_ERROR_KEY)
      self._compile_log_tail = error or ""
      return self._compile_log_tail.splitlines()

    visible_lines = [line for line in lines if line.strip()]
    self._compile_log_tail = "\n".join(visible_lines[-80:])
    return self._compile_log_tail.splitlines()

  def _model_button_text(self) -> str:
    status = self._compile_status()
    if status == STATUS_RUNNING:
      return tr("WAIT")
    if status == STATUS_FAILED:
      return tr("RETRY")
    return tr("CHANGE")

  def _handle_model_button(self) -> None:
    if self._compile_status() == STATUS_FAILED:
      model_name = self._param_text(COMPILE_NAME_KEY) or self._param_text("ActiveModelName")
      if model_name and model_name not in DEFAULT_MODEL_NAMES:
        self._compile_selected_model(model_name)
        return
    self._show_selection("ActiveModelName", tr_noop("Active model"), MODEL_OPTIONS)

  def _show_selection(self, key: str, title: str, options: list[str]) -> None:
    current = self._param_text(key)
    if key == "ActiveModelName" and current in DEFAULT_MODEL_NAMES:
      current = DEFAULT_MODEL_NAME

    def handle_selection(result: DialogResult) -> None:
      if result == DialogResult.CONFIRM and self._dialog is not None:
        self._params.put(key, self._dialog.selection)
        if key == "ActiveModelName":
          ui_state.custom_publisher.update(force=True)
          self._compile_selected_model(self._dialog.selection)
      self._dialog = None

    self._dialog = MultiOptionDialog(tr(title), options, current, callback=handle_selection)
    gui_app.push_widget(self._dialog)

  def _compile_selected_model(self, model_name: str) -> None:
    if not model_name or model_name in DEFAULT_MODEL_NAMES:
      self._params.put(COMPILE_STATUS_KEY, STATUS_IDLE)
      self._params.put("ActiveModelName", DEFAULT_MODEL_NAME)
      self._params.put(COMPILE_NAME_KEY, "")
      self._params.put(COMPILE_ERROR_KEY, "")
      self._params.put(COMPILE_PROGRESS_KEY, 0)
      return

    self._params.put(COMPILE_STATUS_KEY, STATUS_RUNNING)
    self._params.put(COMPILE_NAME_KEY, model_name)
    self._params.put(COMPILE_STARTED_AT_KEY, str(int(time.time())))
    self._params.put(COMPILE_FINISHED_AT_KEY, "")
    self._params.put(COMPILE_ERROR_KEY, "")
    self._params.put(COMPILE_PROGRESS_KEY, 0)

    def worker() -> None:
      result: subprocess.CompletedProcess | None = None
      error = ""
      try:
        Path(COMPILE_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(COMPILE_LOG_PATH, "w") as log_file:
          result = subprocess.run([sys.executable, "model_make.py", "--model", model_name], cwd=MODELD_DIR,
                                  stdout=log_file, stderr=subprocess.STDOUT, text=True, check=False)
      except Exception as e:
        error = f"{type(e).__name__}: {e}"
        try:
          with open(COMPILE_LOG_PATH, "a") as log_file:
            log_file.write(f"\n{error}\n")
        except OSError:
          pass

      status = self._param_text(COMPILE_STATUS_KEY)
      running_model = self._param_text(COMPILE_NAME_KEY)
      if status != STATUS_RUNNING or running_model != model_name:
        return

      if result is not None and result.returncode == 0:
        self._set_compile_success(model_name)
      else:
        try:
          with open(COMPILE_LOG_PATH) as log_file:
            error = error or log_file.read()[-500:]
        except OSError:
          error = error or f"exit code {result.returncode if result is not None else 'unknown'}"
        self._set_compile_failed(model_name, error)

    threading.Thread(target=worker, daemon=True).start()

  def _car_options(self) -> list[str]:
    options: list[str] = []

    def add_options(car_names) -> None:
      for car_name in car_names:
        option = str(car_name)
        if option and option not in options:
          options.append(option)

    try:
      add_options(ui_state.sm["carState"].carSCustom.supportedCars)
    except Exception:
      pass

    if options:
      custom_params = read_custom_param_map(self._params)
      custom_params["SupportCars"] = options
      self._params.put("CustomParam", json.dumps(custom_params, separators=(",", ":"), sort_keys=True))

    support_cars = read_custom_param_map(self._params).get("SupportCars", [])
    if isinstance(support_cars, list):
      add_options(support_cars)

    cp_bytes = self._params.get("CarParamsPersistent")
    if cp_bytes is not None:
      try:
        cp = messaging.log_from_bytes(cp_bytes, car.CarParams)
        if cp.carFingerprint:
          add_options([cp.carFingerprint])
      except Exception:
        pass

    return options or ["MOCK"]

  def show_event(self):
    super().show_event()
    self._scrollers[self._current_tab].show_event()

  def hide_event(self):
    super().hide_event()
    self._scrollers[self._current_tab].hide_event()

  def _render(self, rect: rl.Rectangle):
    self._draw_tabs(rect)
    scroller_rect = rl.Rectangle(rect.x, rect.y + TAB_HEIGHT + TAB_GAP, rect.width, rect.height - TAB_HEIGHT - TAB_GAP)
    self._scrollers[self._current_tab].render(scroller_rect)

  def _draw_tabs(self, rect: rl.Rectangle):
    self._tab_rects.clear()
    tab_names = list(self._sections.keys())
    tab_w = (rect.width - TAB_GAP * (len(tab_names) - 1)) / len(tab_names)
    mouse_pos = rl.get_mouse_position()

    for idx, name in enumerate(tab_names):
      tab_rect = rl.Rectangle(rect.x + idx * (tab_w + TAB_GAP), rect.y, tab_w, TAB_HEIGHT)
      self._tab_rects[name] = tab_rect
      selected = name == self._current_tab
      pressed = self.is_pressed and rl.check_collision_point_rec(mouse_pos, tab_rect)
      color = TAB_SELECTED if selected else (TAB_PRESSED if pressed else TAB_NORMAL)
      text_color = TAB_TEXT_SELECTED if selected else TAB_TEXT

      rl.draw_rectangle_rounded(tab_rect, TAB_RADIUS, 12, color)
      rl.draw_rectangle_rounded_lines_ex(tab_rect, TAB_RADIUS, 12, 2, TAB_BORDER)
      label = tr(name)
      font_size = TAB_FONT_SIZE
      text_size = measure_text_cached(self._tab_font, label, font_size)
      while text_size.x > tab_rect.width - 20 and font_size > TAB_FONT_MIN_SIZE:
        font_size -= 2
        text_size = measure_text_cached(self._tab_font, label, font_size)
      text_pos = rl.Vector2(tab_rect.x + (tab_rect.width - text_size.x) / 2,
                            tab_rect.y + (tab_rect.height - text_size.y) / 2)
      rl.draw_text_ex(self._tab_font, label, text_pos, font_size, 0, text_color)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    for name, tab_rect in self._tab_rects.items():
      if rl.check_collision_point_rec(mouse_pos, tab_rect):
        if name != self._current_tab:
          self._scrollers[self._current_tab].hide_event()
          self._current_tab = name
          self._scrollers[self._current_tab].show_event()
        return
# #custom end
