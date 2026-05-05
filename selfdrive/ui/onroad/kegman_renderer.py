from __future__ import annotations

from dataclasses import dataclass

import pyray as rl
from cereal import log
from openpilot.common.constants import CV
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


MAX_ITEMS = 7
BASE_PANEL_WIDTH = 180
BASE_ITEM_HEIGHT = 105
BASE_PANEL_PADDING = 10
BASE_MARGIN = 30
BASE_TOP = 250

VALUE_FONT_SIZE = 50
LABEL_FONT_SIZE = 25
UNIT_FONT_SIZE = 22

WHITE = rl.Color(255, 255, 255, 220)
WHITE_DIM = rl.Color(255, 255, 255, 170)
GREEN = rl.Color(0, 255, 0, 220)
ORANGE = rl.Color(255, 188, 3, 220)
RED = rl.Color(255, 0, 0, 220)
BLUE = rl.Color(0, 180, 255, 220)
PANEL_BG = rl.Color(0, 0, 0, 110)
PANEL_BORDER = rl.Color(255, 255, 255, 85)
SEPARATOR = rl.Color(255, 255, 255, 30)


@dataclass
class KegmanMeasure:
  value: str
  unit: str
  label: str
  value_color: rl.Color | None = None
  label_color: rl.Color | None = None
  unit_color: rl.Color | None = None

  def __post_init__(self) -> None:
    if self.value_color is None:
      self.value_color = WHITE
    if self.label_color is None:
      self.label_color = WHITE
    if self.unit_color is None:
      self.unit_color = WHITE_DIM


class KegmanRenderer(Widget):
  def __init__(self) -> None:
    super().__init__()
    self.set_enabled(False)
    self._font_value = gui_app.font(FontWeight.BOLD)
    self._font_label = gui_app.font(FontWeight.MEDIUM)
    self._font_unit = gui_app.font(FontWeight.NORMAL)
    self._measures: list[KegmanMeasure] = []

  def _update_state(self) -> None:
    self._measures = self._collect_measures()

  def _render(self, rect: rl.Rectangle) -> None:
    measures = self._measures[:MAX_ITEMS]
    if not measures:
      return

    scale = self._scale_for_rect(rect, len(measures))
    margin = max(4.0, BASE_MARGIN * scale)
    panel_width = max(120.0 if rect.height < 500 else 0.0, BASE_PANEL_WIDTH * scale)
    item_height = max(30.0, BASE_ITEM_HEIGHT * scale)
    padding = max(4.0, BASE_PANEL_PADDING * scale)
    panel_height = padding * 2 + item_height * len(measures)

    x = rect.x + rect.width - panel_width - margin
    y = rect.y + BASE_TOP * scale
    if rect.height < 500:
      y = rect.y + margin
    if y + panel_height > rect.y + rect.height - margin:
      y = max(rect.y + margin, rect.y + rect.height - panel_height - margin)

    panel_rect = rl.Rectangle(x, y, panel_width, panel_height)
    rl.draw_rectangle_rounded(panel_rect, 0.14, 10, PANEL_BG)
    rl.draw_rectangle_rounded_lines_ex(panel_rect, 0.14, 10, max(1.0, 3.0 * scale), PANEL_BORDER)

    for idx, measure in enumerate(measures):
      row_y = y + padding + idx * item_height
      row_rect = rl.Rectangle(x, row_y, panel_width, item_height)
      self._draw_measure(row_rect, measure, scale)
      if idx + 1 < len(measures):
        sep_y = row_y + item_height
        rl.draw_line(int(x + panel_width * 0.18), int(sep_y), int(x + panel_width * 0.82), int(sep_y), SEPARATOR)

  def _scale_for_rect(self, rect: rl.Rectangle, item_count: int) -> float:
    base_height = BASE_PANEL_PADDING * 2 + BASE_ITEM_HEIGHT * item_count
    height_fit = max(0.18, (rect.height - 2 * BASE_MARGIN) / base_height)
    return min(1.0, max(0.18, rect.width / 1860.0, rect.height / 1080.0), height_fit)

  def _draw_measure(self, rect: rl.Rectangle, measure: KegmanMeasure, scale: float) -> None:
    value_font = max(14, round(VALUE_FONT_SIZE * scale))
    label_font = max(8, round(LABEL_FONT_SIZE * scale))
    unit_font = max(8, round(UNIT_FONT_SIZE * scale))

    value_y = rect.y + rect.height * 0.16
    label_y = rect.y + rect.height * 0.62

    unit_size = measure_text_cached(self._font_unit, measure.unit, unit_font) if measure.unit else rl.Vector2(0, 0)
    value_max_width = rect.width - unit_size.x - max(14.0, 22.0 * scale)
    value_font = self._fit_font(self._font_value, measure.value, value_font, value_max_width)
    value_size = measure_text_cached(self._font_value, measure.value, value_font)

    value_x = rect.x + (rect.width - value_size.x) / 2
    if measure.unit:
      value_x -= unit_size.x / 4
    rl.draw_text_ex(self._font_value, measure.value, rl.Vector2(value_x, value_y), value_font, 0, measure.value_color)

    if measure.unit:
      unit_x = min(
        rect.x + rect.width - unit_size.x - max(7.0, 10.0 * scale),
        value_x + value_size.x + max(4.0, 6.0 * scale),
      )
      unit_y = value_y + max(0.0, value_size.y - unit_size.y) * 0.58
      rl.draw_text_ex(self._font_unit, measure.unit, rl.Vector2(unit_x, unit_y), unit_font, 0, measure.unit_color)

    label_font = self._fit_font(self._font_label, measure.label, label_font, rect.width - 12 * scale)
    label_size = measure_text_cached(self._font_label, measure.label, label_font)
    label_x = rect.x + (rect.width - label_size.x) / 2
    rl.draw_text_ex(self._font_label, measure.label, rl.Vector2(label_x, label_y), label_font, 0, measure.label_color)

  def _fit_font(self, font: rl.Font, text: str, font_size: int, max_width: float) -> int:
    while font_size > 8 and measure_text_cached(font, text, font_size).x > max_width:
      font_size -= 1
    return font_size

  def _collect_measures(self) -> list[KegmanMeasure]:
    sm = ui_state.sm
    ui_custom = sm["uICustom"].userInterface
    if not ui_custom.kegman:
      return []

    default_overlay = not any((
      ui_custom.kegmanCPU,
      ui_custom.kegmanLag,
      ui_custom.kegmanBattery,
      ui_custom.kegmanGPU,
      ui_custom.kegmanAngle,
      ui_custom.kegmanDistance,
      ui_custom.kegmanSpeed,
      ui_custom.kegmanEngine,
    ))

    measures: list[KegmanMeasure] = []
    if ui_custom.kegmanCPU or default_overlay:
      measures.append(self._cpu_measure())
    if ui_custom.kegmanLag or default_overlay:
      measures.append(self._lag_measure())
    if ui_custom.kegmanBattery or default_overlay:
      measures.append(self._battery_measure())
    if ui_custom.kegmanGPU or default_overlay:
      measures.append(self._gps_measure())
    if ui_custom.kegmanAngle or default_overlay:
      measures.append(self._steering_angle_measure())
    if ui_custom.kegmanDistance:
      measures.append(self._lead_distance_measure())
    if ui_custom.kegmanSpeed:
      measures.append(self._lead_speed_measure())
    if ui_custom.kegmanEngine:
      measures.append(self._engine_measure())
    return measures

  def _cpu_measure(self) -> KegmanMeasure:
    device_state = ui_state.sm["deviceState"]
    cpu_temps = list(device_state.cpuTempC)
    cpu_usages = [usage for usage in device_state.cpuUsagePercent if usage >= 0]
    cpu_temp = max(cpu_temps) if cpu_temps else 0.0
    cpu_usage = max(cpu_usages) if cpu_usages else 0
    if cpu_temp > 100:
      cpu_temp = 0.0
    return KegmanMeasure(
      f"{cpu_temp:.1f}",
      str(cpu_usage),
      "CPU TEMP",
      self._threshold_color(cpu_temp, 92, 80),
      self._threshold_color(cpu_usage, 90, 60),
    )

  def _lag_measure(self) -> KegmanMeasure:
    cum_lag_ms = getattr(ui_state.sm["controlsState"].deprecated, "cumLagMs", 0.0)
    value_color = WHITE
    if cum_lag_ms < 10:
      value_color = GREEN
    elif cum_lag_ms > 100:
      value_color = RED
    return KegmanMeasure(f"{cum_lag_ms:.0f}", "ms", "Lag", value_color)

  def _battery_measure(self) -> KegmanMeasure:
    voltage = ui_state.sm["peripheralState"].voltage * 0.001
    value_color = WHITE
    if voltage > 14.7 or voltage < 12.0:
      value_color = ORANGE
    if voltage < 11.7:
      value_color = RED
    return KegmanMeasure(f"{voltage:.1f}", "volt", "battery", value_color)

  def _gps_measure(self) -> KegmanMeasure:
    gps_msg = self._gps_message()
    accuracy = (
      getattr(gps_msg, "verticalAccuracy", 0.0)
      if self._using_tres_gps() else getattr(gps_msg, "horizontalAccuracy", 0.0)
    )
    altitude = getattr(gps_msg, "altitude", 0.0)
    if accuracy == 0 or accuracy > 99:
      value = "-"
    elif accuracy > 9.99:
      value = f"{accuracy:.1f}"
    else:
      value = f"{accuracy:.2f}"
    return KegmanMeasure(value, f"{altitude:.1f}", "GPS PREC", self._threshold_color(accuracy, 5, 2))

  def _steering_angle_measure(self) -> KegmanMeasure:
    angle = ui_state.sm["carState"].steeringAngleDeg
    return KegmanMeasure(f"{angle:.1f}", "deg", "REAL STEER", self._steering_angle_color(angle))

  def _lead_distance_measure(self) -> KegmanMeasure:
    lead = ui_state.sm["radarState"].leadOne
    unit = "m"
    value = "-"
    value_color = WHITE
    if lead.status:
      value = str(int(lead.dRel))
      if lead.dRel < 15:
        value_color = ORANGE
      if lead.dRel < 5:
        value_color = RED

    leads = ui_state.sm["modelV2"].leadsV3
    if len(leads) > 0 and leads[0].prob > 0.1 and len(leads[0].x) > 0:
      unit = str(int(leads[0].x[0]))
    return KegmanMeasure(value, unit, "REL DIST", value_color)

  def _lead_speed_measure(self) -> KegmanMeasure:
    lead = ui_state.sm["radarState"].leadOne
    unit = "km/h" if ui_state.is_metric else "mph"
    value = "-"
    value_color = WHITE
    if lead.status:
      speed = lead.vRel * (CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH)
      value = str(int(speed + 0.5))
      if lead.vRel < 0:
        value_color = ORANGE
      if lead.vRel < -5:
        value_color = RED
    return KegmanMeasure(value, unit, "REL SPEED", value_color)

  def _engine_measure(self) -> KegmanMeasure:
    car_state = ui_state.sm["carState"]
    rpm = car_state.engineRpmDEPRECATED
    gear_step = car_state.carSCustom.electGearStep

    if rpm <= 0:
      return KegmanMeasure("EV", self._gear_text(gear_step), "ENGINE", GREEN, unit_color=BLUE)

    value_color = WHITE
    if rpm > 3000:
      value_color = RED
    elif rpm > 2000:
      value_color = ORANGE
    return KegmanMeasure(f"{rpm:.0f}", self._gear_text(gear_step), "ENGINE", value_color, unit_color=BLUE)

  def _gps_message(self):
    sm = ui_state.sm
    if self._using_tres_gps() and sm.seen["gpsLocation"]:
      return sm["gpsLocation"]
    return sm["gpsLocationExternal"]

  def _using_tres_gps(self) -> bool:
    tres_type = getattr(log.PandaState.PandaType, "tres", None)
    return tres_type is not None and ui_state.panda_type == tres_type

  def _gear_text(self, gear_step: int) -> str:
    if gear_step <= 0:
      return "P"
    return f"G{gear_step}"

  def _threshold_color(self, value: float, red_threshold: float, yellow_threshold: float) -> rl.Color:
    if value > red_threshold:
      return RED
    if value > yellow_threshold:
      return ORANGE
    return WHITE

  def _steering_angle_color(self, angle: float) -> rl.Color:
    abs_angle = abs(angle)
    if abs_angle > 55:
      return RED
    if abs_angle > 30:
      return ORANGE
    return WHITE
