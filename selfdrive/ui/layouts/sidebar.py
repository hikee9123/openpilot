import pyray as rl
import time
from dataclasses import dataclass
from collections.abc import Callable
from cereal import log
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

SIDEBAR_WIDTH = 300
METRIC_HEIGHT = 126
METRIC_WIDTH = 240
METRIC_MARGIN = 30
FONT_SIZE = 35
BATTERY_ICON_W = 70
BATTERY_ICON_H = 34
BATTERY_CAP_W = 8
BATTERY_FONT_SIZE = 35
BATTERY_LABEL_FONT_SIZE = 30

SETTINGS_BTN = rl.Rectangle(50, 35, 200, 117)
HOME_BTN = rl.Rectangle(60, 860, 180, 180)

ThermalStatus = log.DeviceState.ThermalStatus
NetworkType = log.DeviceState.NetworkType


# Color scheme
class Colors:
  WHITE = rl.WHITE
  WHITE_DIM = rl.Color(255, 255, 255, 85)
  GRAY = rl.Color(84, 84, 84, 255)

  # Status colors
  GOOD = rl.WHITE
  WARNING = rl.Color(218, 202, 37, 255)
  DANGER = rl.Color(201, 34, 49, 255)

  # UI elements
  METRIC_BORDER = rl.Color(255, 255, 255, 85)
  BUTTON_NORMAL = rl.WHITE
  BUTTON_PRESSED = rl.Color(255, 255, 255, 166)
  AUTO_POWER_OFF_ARMED = rl.Color(255, 255, 0, 150)
  AUTO_POWER_OFF_COUNTDOWN = rl.Color(255, 225, 0, 255)
  AUTO_POWER_OFF_CRITICAL = rl.Color(255, 85, 0, 255)
  COUNTDOWN_BG = rl.Color(0, 0, 0, 180)


NETWORK_TYPES = {
  NetworkType.none: tr_noop("--"),
  NetworkType.wifi: tr_noop("Wi-Fi"),
  NetworkType.ethernet: tr_noop("ETH"),
  NetworkType.cell2G: tr_noop("2G"),
  NetworkType.cell3G: tr_noop("3G"),
  NetworkType.cell4G: tr_noop("LTE"),
  NetworkType.cell5G: tr_noop("5G"),
}


@dataclass(slots=True)
class MetricData:
  label: str
  value: str
  color: rl.Color

  def update(self, label: str, value: str, color: rl.Color):
    self.label = label
    self.value = value
    self.color = color


class Sidebar(Widget):
  def __init__(self):
    super().__init__()
    self._net_type = NETWORK_TYPES.get(NetworkType.none)
    self._net_strength = 0

    self._temp_status = MetricData(tr_noop("TEMP"), tr_noop("GOOD"), Colors.GOOD)
    self._panda_status = MetricData(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)
    self._connect_status = MetricData(tr_noop("CONNECT"), tr_noop("OFFLINE"), Colors.WARNING)
    self._recording_audio = False
    self._show_battery_status = False
    self._battery_voltage = 0.0
    self._battery_fill = 0.0
    self._battery_color = Colors.WHITE

    self._home_img = gui_app.texture("images/button_home.png", HOME_BTN.width, HOME_BTN.height)
    self._flag_img = gui_app.texture("images/button_flag.png", HOME_BTN.width, HOME_BTN.height)
    self._settings_img = gui_app.texture("images/button_settings.png", SETTINGS_BTN.width, SETTINGS_BTN.height)
    self._mic_img = gui_app.texture("icons/microphone.png", 30, 30)
    self._mic_indicator_rect = rl.Rectangle(0, 0, 0, 0)
    self._font_regular = gui_app.font(FontWeight.NORMAL)
    self._font_bold = gui_app.font(FontWeight.SEMI_BOLD)

    # Callbacks
    self._on_settings_click: Callable | None = None
    self._on_flag_click: Callable | None = None
    self._open_settings_callback: Callable | None = None

  def set_callbacks(self, on_settings: Callable | None = None, on_flag: Callable | None = None,
                    open_settings: Callable | None = None):
    self._on_settings_click = on_settings
    self._on_flag_click = on_flag
    self._open_settings_callback = open_settings

  def _render(self, rect: rl.Rectangle):
    # Background
    rl.draw_rectangle_rec(rect, rl.BLACK)

    self._draw_buttons(rect)
    self._draw_network_indicator(rect)
    if self._show_battery_status:
      self._draw_battery_indicator(rect)
    self._draw_metrics(rect)

  def _update_state(self):
    sm = ui_state.sm
    if not sm.updated['deviceState']:
      return

    device_state = sm['deviceState']

    self._recording_audio = ui_state.recording_audio
    self._update_network_status(device_state)
    self._update_temperature_status(device_state)
    self._update_connection_status(device_state)
    self._update_panda_status()
    self._update_battery_status()

  def _update_network_status(self, device_state):
    self._net_type = NETWORK_TYPES.get(device_state.networkType.raw, tr_noop("Unknown"))
    strength = device_state.networkStrength
    self._net_strength = max(0, min(5, strength.raw + 1)) if strength.raw > 0 else 0

  def _update_temperature_status(self, device_state):
    thermal_status = device_state.thermalStatus

    if thermal_status == ThermalStatus.ok:
      self._temp_status.update(tr_noop("TEMP"), tr_noop("GOOD"), Colors.GOOD)
    else:
      self._temp_status.update(tr_noop("TEMP"), tr_noop("HIGH"), Colors.DANGER)

  def _update_connection_status(self, device_state):
    last_ping = device_state.lastAthenaPingTime
    if last_ping == 0:
      self._connect_status.update(tr_noop("CONNECT"), tr_noop("OFFLINE"), Colors.WARNING)
    elif time.monotonic_ns() - last_ping < 80_000_000_000:  # 80 seconds in nanoseconds
      self._connect_status.update(tr_noop("CONNECT"), tr_noop("ONLINE"), Colors.GOOD)
    else:
      self._connect_status.update(tr_noop("CONNECT"), tr_noop("ERROR"), Colors.DANGER)

  def _update_panda_status(self):
    if ui_state.panda_type == log.PandaState.PandaType.unknown:
      self._panda_status.update(tr_noop("NO"), tr_noop("PANDA"), Colors.DANGER)
    else:
      self._panda_status.update(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)

  def _update_battery_status(self):
    self._show_battery_status = bool(ui_state.sm["uICustom"].userInterface.kegmanBattery)
    self._battery_voltage = ui_state.sm["peripheralState"].voltage * 0.001
    self._battery_fill = max(0.0, min(1.0, (self._battery_voltage - 11.5) / (12.8 - 11.5)))

    if self._battery_voltage <= 0.0:
      self._battery_color = Colors.GRAY
    elif self._battery_voltage < 11.7:
      self._battery_color = Colors.DANGER
    elif self._battery_voltage < 12.0 or self._battery_voltage > 14.7:
      self._battery_color = Colors.WARNING
    else:
      self._battery_color = Colors.WHITE

  def _handle_mouse_release(self, mouse_pos: MousePos):
    home_clicked = rl.check_collision_point_rec(mouse_pos, HOME_BTN)
    if home_clicked:
      ui_state.auto_power_off.disarm()

    if rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN):
      if self._on_settings_click:
        self._on_settings_click()
    elif home_clicked and ui_state.started:
      if self._on_flag_click:
        self._on_flag_click()
    elif self._recording_audio and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect):
      if self._open_settings_callback:
        self._open_settings_callback()

  def _draw_buttons(self, rect: rl.Rectangle):
    mouse_pos = rl.get_mouse_position()
    mouse_down = self.is_pressed and rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)

    # Settings button
    settings_down = mouse_down and rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN)
    tint = Colors.BUTTON_PRESSED if settings_down else Colors.BUTTON_NORMAL
    rl.draw_texture_ex(self._settings_img, rl.Vector2(SETTINGS_BTN.x, SETTINGS_BTN.y), 0.0, 1.0, tint)

    # Home/Flag button
    flag_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, HOME_BTN)
    button_img = self._flag_img if ui_state.started else self._home_img

    tint = Colors.BUTTON_PRESSED if (ui_state.started and flag_pressed) else Colors.BUTTON_NORMAL
    rl.draw_texture_ex(button_img, rl.Vector2(HOME_BTN.x, HOME_BTN.y), 0.0, 1.0, tint)
    self._draw_auto_power_off_status()

    # Microphone button
    if self._recording_audio:
      self._mic_indicator_rect = rl.Rectangle(rect.x + rect.width - 130, rect.y + 245, 75, 40)

      mic_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect)
      bg_color = rl.Color(Colors.DANGER.r, Colors.DANGER.g, Colors.DANGER.b, int(255 * 0.65)) if mic_pressed else Colors.DANGER

      rl.draw_rectangle_rounded(self._mic_indicator_rect, 1, 10, bg_color)
      rl.draw_texture_ex(self._mic_img, rl.Vector2(self._mic_indicator_rect.x + (self._mic_indicator_rect.width - self._mic_img.width) / 2,
                         self._mic_indicator_rect.y + (self._mic_indicator_rect.height - self._mic_img.height) / 2), 0.0, 1.0, Colors.WHITE)

  def _draw_auto_power_off_status(self):
    if not ui_state.auto_power_off.armed:
      return

    center = rl.Vector2(HOME_BTN.x + HOME_BTN.width / 2, HOME_BTN.y + HOME_BTN.height / 2)
    radius = HOME_BTN.width / 2
    rl.draw_circle(int(center.x), int(center.y), int(radius), Colors.AUTO_POWER_OFF_ARMED)

    remaining = ui_state.auto_power_off.remaining_seconds
    progress = ui_state.auto_power_off.countdown_progress
    if remaining is None or progress is None:
      return

    countdown_color = Colors.AUTO_POWER_OFF_CRITICAL if remaining <= 5 else Colors.AUTO_POWER_OFF_COUNTDOWN
    rl.draw_ring(center, radius - 12, radius, -90.0, -90.0 + 360.0 * progress, 72, countdown_color)

    text = f"{remaining}s"
    font_size = 54 if remaining < 100 else 44
    text_size = measure_text_cached(self._font_bold, text, font_size)
    text_bg = rl.Rectangle(center.x - text_size.x / 2 - 14, center.y - text_size.y / 2 - 8,
                           text_size.x + 28, text_size.y + 16)
    rl.draw_rectangle_rounded(text_bg, 0.35, 10, Colors.COUNTDOWN_BG)
    rl.draw_text_ex(self._font_bold, text,
                    rl.Vector2(center.x - text_size.x / 2, center.y - text_size.y / 2),
                    font_size, 0, Colors.WHITE)

  def _draw_network_indicator(self, rect: rl.Rectangle):
    # Signal strength dots
    x_start = rect.x + 58
    y_pos = rect.y + 196
    dot_size = 27
    dot_spacing = 37

    for i in range(5):
      color = Colors.WHITE if i < self._net_strength else Colors.GRAY
      x = int(x_start + i * dot_spacing + dot_size // 2)
      y = int(y_pos + dot_size // 2)
      rl.draw_circle(x, y, dot_size // 2, color)

    # Network type text
    text_y = rect.y + 247
    text_pos = rl.Vector2(rect.x + 58, text_y)
    rl.draw_text_ex(self._font_regular, tr(self._net_type), text_pos, FONT_SIZE, 0, Colors.WHITE)

  def _draw_battery_indicator(self, rect: rl.Rectangle):
    icon_x = rect.x + 58
    icon_y = rect.y + 312
    cap_x = icon_x + BATTERY_ICON_W + 4
    cap_y = icon_y + (BATTERY_ICON_H - 14) / 2

    icon_rect = rl.Rectangle(icon_x, icon_y, BATTERY_ICON_W, BATTERY_ICON_H)
    rl.draw_rectangle_rounded_lines_ex(icon_rect, 0.18, 8, 3, self._battery_color)
    rl.draw_rectangle_rounded(rl.Rectangle(cap_x, cap_y, BATTERY_CAP_W, 14), 0.35, 6, self._battery_color)

    if self._battery_fill > 0.0:
      fill_w = max(4.0, (BATTERY_ICON_W - 12) * self._battery_fill)
      fill_rect = rl.Rectangle(icon_x + 6, icon_y + 6, fill_w, BATTERY_ICON_H - 12)
      rl.draw_rectangle_rounded(fill_rect, 0.18, 8, self._battery_color)

    value = f"{self._battery_voltage:.1f}V" if self._battery_voltage > 0.0 else "--.-V"
    value_pos = rl.Vector2(icon_x + BATTERY_ICON_W + BATTERY_CAP_W + 26, icon_y - 3)
    rl.draw_text_ex(self._font_bold, value, value_pos, BATTERY_FONT_SIZE, 0, self._battery_color)

    label_pos = rl.Vector2(icon_x, icon_y + 48)
    rl.draw_text_ex(self._font_regular, tr("Battery"), label_pos, BATTERY_LABEL_FONT_SIZE, 0, Colors.WHITE)

  def _draw_metrics(self, rect: rl.Rectangle):
    metrics = ([(self._temp_status, 410), (self._panda_status, 568), (self._connect_status, 726)]
               if self._show_battery_status else
               [(self._temp_status, 338), (self._panda_status, 496), (self._connect_status, 654)])

    for metric, y_offset in metrics:
      self._draw_metric(rect, metric, rect.y + y_offset)

  def _draw_metric(self, rect: rl.Rectangle, metric: MetricData, y: float):
    metric_rect = rl.Rectangle(rect.x + METRIC_MARGIN, y, METRIC_WIDTH, METRIC_HEIGHT)
    # Draw colored left edge (clipped rounded rectangle)
    edge_rect = rl.Rectangle(metric_rect.x + 4, metric_rect.y + 4, 100, 118)
    rl.begin_scissor_mode(int(metric_rect.x + 4), int(metric_rect.y), 18, int(metric_rect.height))
    rl.draw_rectangle_rounded(edge_rect, 0.3, 10, metric.color)
    rl.end_scissor_mode()

    # Draw border
    rl.draw_rectangle_rounded_lines_ex(metric_rect, 0.3, 10, 2, Colors.METRIC_BORDER)

    # Draw label and value
    labels = [tr(metric.label), tr(metric.value)]
    text_y = metric_rect.y + (metric_rect.height / 2 - len(labels) * FONT_SIZE * FONT_SCALE)
    for text in labels:
      text_size = measure_text_cached(self._font_bold, text, FONT_SIZE)
      text_y += text_size.y
      text_pos = rl.Vector2(
        metric_rect.x + 22 + (metric_rect.width - 22 - text_size.x) / 2,
        text_y
      )
      rl.draw_text_ex(self._font_bold, text, text_pos, FONT_SIZE, 0, Colors.WHITE)
