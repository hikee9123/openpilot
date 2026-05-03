import subprocess
import threading
from collections.abc import Callable

import pyray as rl
from cereal import car, messaging

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
  "1.default",
  "2.Steam_Powered",
  "3.Firehose",
  "4.The_Cool_Peoples",
  "5.North_Nevada",
  "6.Dark_Souls_2",
]

EXTERNAL_NAVI_OPTIONS = ["0", "1", "2"]
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
    self._current_tab = "UI"
    self._tab_rects: dict[str, rl.Rectangle] = {}
    self._tab_font = gui_app.font(FontWeight.MEDIUM)
    self._sections = {
      "UI": [
        SectionHeader(tr_noop("Toggle def")),
        self._toggle_json_item("ShowDebugMessage", tr_noop("Show debug message")),
        self._toggle_param_item("DisableUpdates", tr_noop("Disable OTA updates")),
        self._toggle_json_item("ShowCarTracking", tr_noop("Show car tracking")),
        self._toggle_json_item("tpms", tr_noop("Show TPMS"), enabled=self._debug_enabled),
        self._toggle_json_item("ParamDebug", tr_noop("Debug overlay"), enabled=self._debug_enabled),
        SectionHeader(tr_noop("Kegman Show")),
        self._toggle_json_item("kegman", tr_noop("HUD overlay"), enabled=self._debug_enabled),
        self._toggle_json_item("kegmanCPU", tr_noop("CPU temperature"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanLag", tr_noop("UI lag"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanBattery", tr_noop("Battery voltage"), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanGPU", tr_noop("GPS accuracy"), enabled=self._kegman_enabled),
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
        self._toggle_param_item("EnableLogging", tr_noop("Enable logging")),
        self._selection_item("SelectedCar", tr_noop("Selected car"), self._car_options),
      ],
      "Git": [
        self._command_item(tr_noop("Fetch All and Prune"), tr_noop("SYNC"), ["bash", "-lc", "git fetch --all --prune && git remote prune origin"], confirm=False),
        self._update_from_remote_item(),
        self._command_item(tr_noop("Revert Commit"), tr_noop("ROLLBACK"), ["git", "reset", "--hard", "ec448a9"], confirm=True),
      ],
      "Model": [
        self._selection_item("ActiveModelName", tr_noop("Active model"), lambda: MODEL_OPTIONS),
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
    return bool(values["ShowDebugMessage"] and values["kegman"])

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
      threading.Thread(target=lambda: subprocess.run(command, cwd="/home/bhcho/openpilot", check=False), daemon=True).start()

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
          subprocess.run(["git", "fetch", "origin"], cwd="/home/bhcho/openpilot", check=False)
          subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], cwd="/home/bhcho/openpilot", check=False)

        threading.Thread(target=worker, daemon=True).start()

      content = tr("Update from remote? This will reset local files to origin branch.")
      dialog = ConfirmDialog(content, tr("Update"), callback=lambda result: run() if result == DialogResult.CONFIRM else None)
      gui_app.push_widget(dialog)

    return button_item(lambda: tr("Update from Remote"), lambda: tr("UPDATE"), callback=callback)

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

  def _show_selection(self, key: str, title: str, options: list[str]) -> None:
    current = self._param_text(key)

    def handle_selection(result: DialogResult) -> None:
      if result == DialogResult.CONFIRM and self._dialog is not None:
        self._params.put(key, self._dialog.selection)
        if key == "ActiveModelName":
          ui_state.custom_publisher.update(force=True)
      self._dialog = None

    self._dialog = MultiOptionDialog(tr(title), options, current, callback=handle_selection)
    gui_app.push_widget(self._dialog)

  def _car_options(self) -> list[str]:
    options: list[str] = []
    support_cars = read_custom_param_map(self._params).get("SupportCars", [])
    if isinstance(support_cars, list):
      options.extend(str(car_name) for car_name in support_cars if car_name)

    cp_bytes = self._params.get("CarParamsPersistent")
    if cp_bytes is not None:
      try:
        cp = messaging.log_from_bytes(cp_bytes, car.CarParams)
        if cp.carFingerprint:
          options.append(cp.carFingerprint)
      except Exception:
        pass

    selected = self._param_text("SelectedCar")
    if selected and selected not in options:
      options.insert(0, selected)

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
