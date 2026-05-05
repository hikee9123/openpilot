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
COMPILE_LOG_PATH = "/data/tmp/openpilot_custom_model_compile.log"
COMPILE_STATUS_CHECK_INTERVAL = 5.0
COMPILE_LOG_CACHE_INTERVAL = 2.0
COMPILE_PROCESS_GRACE_SECONDS = 60
COMPILE_STALE_SECONDS = 2 * 60 * 60
GIT_STATUS_KEY = "CustomGitUpdateStatus"
GIT_ERROR_KEY = "CustomGitUpdateError"
GIT_LOG_PATH = "/tmp/openpilot_git_update.log"
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
        self._toggle_json_item("ShowDebugMessage", tr_noop("Show debug message")),
        self._toggle_param_item("DisableUpdates", tr_noop("Disable OTA updates")),
        self._toggle_json_item("ShowCarTracking", tr_noop("Show car tracking")),
        self._toggle_json_item("tpms", tr_noop("Show TPMS")),
        self._toggle_json_item("ParamDebug", tr_noop("Debug overlay"), enabled=self._debug_enabled),
        SectionHeader(tr_noop("Kegman Show")),
        self._toggle_json_item("kegman", tr_noop("HUD overlay")),
        self._toggle_json_item("kegmanCPU", tr_noop("CPU temperature"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanLag", tr_noop("UI lag"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanBattery", tr_noop("Battery voltage"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanGPS", tr_noop("GPS accuracy"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanGPULoad", tr_noop("GPU load"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanAngle", tr_noop("Steering angle"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanEngine", tr_noop("Engine status"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanDistance", tr_noop("Relative distance"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanSpeed", tr_noop("Relative speed"), enabled=self._kegman_enabled),
      ],
      "Community": [
        SectionHeader(tr_noop("Cruise Settings")),
        self._number_item("ParamCruiseMode", tr_noop("Cruise mode"), 0, 15, 1),
        self._number_item("ParamCruiseGap", tr_noop("Cruise gap"), 0, 4, 1, enabled=lambda: int(self._values()["ParamCruiseMode"]) != 0),
        self._number_item("ParamCurveSpeedLimit", tr_noop("Curve speed adjust"), 30, 100, 5),
        self._number_item("ParamAutoEngage", tr_noop("Auto cruise engage speed"), 30, 100, 5),
        self._number_item("ParamAutoLaneChange", tr_noop("Auto lane change delay"), 0, 100, 10),
        self._number_item("ParamSteerRatio", tr_noop("Steering ratio"), -0.2, 0.2, 0.01),
        self._number_item("ParamStiffnessFactor", tr_noop("Lateral stiffness factor"), -0.1, 0.1, 0.01),
        self._number_item("ParamAngleOffsetDeg", tr_noop("Steering angle offset"), -2.0, 2.0, 0.1),
        SectionHeader(tr_noop("Screen & Power")),
        self._number_item("ParamBrightness", tr_noop("Screen brightness"), -20, 5, 1),
        self._number_item("ParamAutoScreenOff", tr_noop("Screen timeout"), 0, 120, 1),
        self._number_item("ParamPowerOff", tr_noop("Power off time"), 0, 60, 1),
        self._number_item("DUAL_CAMERA_VIEW", tr_noop("Dual camera view"), 0, 1, 1),
        SectionHeader(tr_noop("Logging")),
        self._logging_toggle_item(),
        self._selection_item("SelectedCar", tr_noop("Selected car"), self._car_options),
      ],
      "Git": [
        self._command_item(tr_noop("Fetch All and Prune"), tr_noop("SYNC"), ["bash", "-lc", "git fetch --all --prune && git remote prune origin"], confirm=False),
        self._update_from_remote_item(),
        text_item(lambda: tr("Git status"), self._git_update_status_text),
      ],
      "Model": [
        self._model_selection_item(),
        text_item(lambda: tr("Compile status"), self._compile_status_text),
        text_item(lambda: tr("Compile detail"), self._compile_log_tail_text),
      ],
      "Debug": [
        self._toggle_json_item("debug1", tr_noop("Debug 1")),
        self._toggle_json_item("debug2", tr_noop("Debug 2")),
        self._toggle_json_item("debug3", tr_noop("Debug 3")),
        self._toggle_json_item("debug4", tr_noop("Debug 4")),
        self._toggle_json_item("debug5", tr_noop("Debug 5")),
        self._toggle_json_item("debug6", tr_noop("Debug 6")),
      ],
      "Navigation": [
        self._toggle_param_item("UseExternalNaviRoutes", tr_noop("Use external navi routes")),
        self._cycle_param_int_item("ExternalNaviType", tr_noop("External navi type"), EXTERNAL_NAVI_OPTIONS),
        self._text_edit_item("MapboxToken", tr_noop("Mapbox token")),
      ],
    }
    self._scrollers = {name: Scroller(items, line_separator=True, spacing=0) for name, items in self._sections.items()}

  def _values(self):
    return read_custom_params(self._params)

  def _save_value(self, key: str, value: int | float | bool) -> None:
    write_custom_params({key: value}, self._params)
    ui_state.custom_publisher.update(force=True)

  def _debug_enabled(self) -> bool:
    return bool(self._values()["ShowDebugMessage"])

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
    return ListItem(title=lambda: tr(title), action_item=action)

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

  def _toggle_json_item(self, key: str, title: str, enabled: bool | Callable[[], bool] = True):
    return toggle_item(
      lambda: tr(title),
      initial_state=bool(self._values()[key]),
      callback=lambda state, k=key: self._save_value(k, bool(state)),
      enabled=enabled,
    )

  def _toggle_param_item(self, key: str, title: str):
    return toggle_item(
      lambda: tr(title),
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
      initial_state=logging_enabled(),
      callback=set_logging_enabled,
    )

  def _cycle_param_int_item(self, key: str, title: str, options: list[str]):
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
    return ListItem(title=lambda: tr(title), action_item=action)

  def _command_item(self, title: str, button_text: str, command: list[str], confirm: bool):
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

    return button_item(lambda: tr(title), lambda: tr(button_text), callback=callback)

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

    return button_item(lambda: tr("Update from Remote"), lambda: tr("UPDATE"), callback=callback)

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

  def _text_edit_item(self, key: str, title: str):
    item = button_item(lambda: tr(title), lambda: tr("EDIT"), callback=lambda k=key, t=title: self._show_keyboard(k, t))
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

  def _selection_item(self, key: str, title: str, options_fn: Callable[[], list[str]]):
    item = button_item(
      lambda: tr(title),
      lambda: tr("CHANGE"),
      callback=lambda k=key, t=title, fn=options_fn: self._show_selection(k, t, fn()),
    )
    item.action_item.set_value(lambda k=key: self._param_text(k))
    return item

  def _model_selection_item(self):
    item = button_item(
      lambda: tr("Active model"),
      self._model_button_text,
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
    self._params.put(COMPILE_PROGRESS_KEY, "100")

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
    now = time.monotonic()
    if now - self._last_compile_log_check < COMPILE_LOG_CACHE_INTERVAL:
      return self._compile_log_tail
    self._last_compile_log_check = now

    try:
      with open(COMPILE_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        lines = [line.strip() for line in log_file.readlines()[-80:]]
    except OSError:
      self._compile_log_tail = ""
      return self._compile_log_tail

    for line in reversed(lines):
      if line:
        self._compile_log_tail = line[-100:]
        return self._compile_log_tail

    self._compile_log_tail = ""
    return self._compile_log_tail

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
      self._params.put(COMPILE_PROGRESS_KEY, "0")
      return

    self._params.put(COMPILE_STATUS_KEY, STATUS_RUNNING)
    self._params.put(COMPILE_NAME_KEY, model_name)
    self._params.put(COMPILE_STARTED_AT_KEY, str(int(time.time())))
    self._params.put(COMPILE_FINISHED_AT_KEY, "")
    self._params.put(COMPILE_ERROR_KEY, "")
    self._params.put(COMPILE_PROGRESS_KEY, "0")

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
