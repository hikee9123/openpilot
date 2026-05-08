from __future__ import annotations

from dataclasses import dataclass

import pyray as rl
from cereal import log
from openpilot.common.constants import CV
from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.custom_overlay_layout import (
  BASE_ITEM_HEIGHT,
  BASE_MARGIN,
  overlay_cell_width,
  overlay_column_gap,
  overlay_padding,
  overlay_scale_for_rect,
)
from openpilot.selfdrive.ui.onroad.osm_road_overlay_renderer import minimap_rect
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


MAX_ITEMS = 6
BASE_TOP = 250
MINIMAP_CLEARANCE = 14
TPMS_FONT_SIZE = 38
TPMS_DM_BTN_SIZE = 192
TPMS_COL_GAP = 80
TPMS_DM_VERTICAL_GAP = 42

VALUE_FONT_SIZE = 50
LABEL_FONT_SIZE = 25
UNIT_FONT_SIZE = 22

WHITE = rl.Color(255, 255, 255, 220)
WHITE_DIM = rl.Color(255, 255, 255, 170)
TPMS_WHITE = rl.Color(255, 255, 255, 200)
TPMS_DIM = rl.Color(125, 125, 125, 200)
TPMS_LOW = rl.Color(255, 90, 90, 200)
GREEN = rl.Color(0, 255, 0, 220)
ORANGE = rl.Color(255, 188, 3, 220)
RED = rl.Color(255, 0, 0, 220)
BLUE = rl.Color(0, 180, 255, 220)
PANEL_BG = rl.Color(0, 0, 0, 110)
PANEL_BORDER = rl.Color(255, 255, 255, 85)
SEPARATOR = rl.Color(255, 255, 255, 30)
OSM_OVERLAY_MODE_MINIMAP = 1


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
    self._font_tpms = gui_app.font(FontWeight.BOLD)
    self._measures: list[KegmanMeasure] = []

  def _update_state(self) -> None:
    self._measures = self._collect_measures()

  def _render(self, rect: rl.Rectangle) -> None:
    measures = self._measures[:MAX_ITEMS]
    ui_custom = ui_state.sm["uICustom"].userInterface
    if ui_custom.tpms:
      self._draw_tpms_overlay(rect)

    if not measures:
      return

    minimap_rect = self._minimap_rect(rect)
    columns = 2 if len(measures) >= 5 else 1
    layout = self._layout(rect, len(measures), columns)
    panel_rect = layout["panel_rect"]

    if minimap_rect is not None and self._rects_overlap(panel_rect, minimap_rect):
      layout = self._layout(rect, len(measures), columns, minimap_rect)
      panel_rect = layout["panel_rect"]

    if minimap_rect is not None and self._rects_overlap(panel_rect, minimap_rect) and columns == 1 and len(measures) >= 3:
      columns = 2
      layout = self._layout(rect, len(measures), columns, minimap_rect)
      panel_rect = layout["panel_rect"]

    rows = int(layout["rows"])
    scale = float(layout["scale"])
    padding = float(layout["padding"])
    cell_width = float(layout["cell_width"])
    item_height = float(layout["item_height"])
    column_gap = float(layout["column_gap"])
    panel_height = panel_rect.height
    x = panel_rect.x
    y = panel_rect.y
    rl.draw_rectangle_rounded(panel_rect, 0.14, 10, PANEL_BG)
    rl.draw_rectangle_rounded_lines_ex(panel_rect, 0.14, 10, max(1.0, 3.0 * scale), PANEL_BORDER)

    for idx, measure in enumerate(measures):
      col = idx // rows if columns > 1 else 0
      row = idx % rows if columns > 1 else idx
      row_x = x + padding + col * (cell_width + column_gap) if columns > 1 else x
      row_y = y + padding + row * item_height
      row_rect = rl.Rectangle(row_x, row_y, cell_width, item_height)
      self._draw_measure(row_rect, measure, scale)
      col_items = max(0, min(rows, len(measures) - col * rows))
      if row + 1 < col_items:
        sep_y = row_y + item_height
        rl.draw_line(int(row_x + cell_width * 0.18), int(sep_y), int(row_x + cell_width * 0.82), int(sep_y), SEPARATOR)

    if columns > 1:
      sep_x = x + padding + cell_width + column_gap / 2
      rl.draw_line(int(sep_x), int(y + padding * 1.5), int(sep_x), int(y + panel_height - padding * 1.5), SEPARATOR)

  def _layout(
    self,
    rect: rl.Rectangle,
    item_count: int,
    columns: int,
    minimap_rect: rl.Rectangle | None = None,
  ) -> dict:
    columns = max(1, columns)
    rows = (item_count + columns - 1) // columns
    scale = self._scale_for_rect(rect, rows)
    margin = max(4.0, BASE_MARGIN * scale)
    cell_width = overlay_cell_width(rect, scale)
    item_height = max(30.0, BASE_ITEM_HEIGHT * scale)
    padding = overlay_padding(scale)
    column_gap = overlay_column_gap(scale) if columns > 1 else 0.0
    panel_width = padding * 2 + cell_width * columns + column_gap if columns > 1 else cell_width
    panel_height = padding * 2 + item_height * rows

    x = rect.x + rect.width - panel_width - margin
    y = rect.y + BASE_TOP * scale
    if rect.height < 500:
      y = rect.y + margin

    if minimap_rect is not None:
      max_bottom = minimap_rect.y - max(MINIMAP_CLEARANCE, margin)
      if y + panel_height > max_bottom:
        y = max(rect.y + margin, max_bottom - panel_height)

    if y + panel_height > rect.y + rect.height - margin:
      y = max(rect.y + margin, rect.y + rect.height - panel_height - margin)

    return {
      "panel_rect": rl.Rectangle(x, y, panel_width, panel_height),
      "rows": rows,
      "scale": scale,
      "padding": padding,
      "cell_width": cell_width,
      "item_height": item_height,
      "column_gap": column_gap,
    }

  def _scale_for_rect(self, rect: rl.Rectangle, item_count: int) -> float:
    return overlay_scale_for_rect(rect, item_count)

  def _minimap_rect(self, rect: rl.Rectangle) -> rl.Rectangle | None:
    mode = int(ui_state.custom_params.get("OsmRoadOverlayMode", 0))
    if mode != OSM_OVERLAY_MODE_MINIMAP:
      return None

    return minimap_rect(rect)

  @staticmethod
  def _rects_overlap(a: rl.Rectangle, b: rl.Rectangle) -> bool:
    return a.x < b.x + b.width and a.x + a.width > b.x and a.y < b.y + b.height and a.y + a.height > b.y

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
      ui_custom.kegmanGPS,
      ui_custom.kegmanGPULoad,
      ui_custom.kegmanAngle,
      ui_custom.kegmanDistance,
      ui_custom.kegmanSpeed,
      ui_custom.kegmanEngine,
      ui_custom.kegmanLag,
    ))

    measures: list[KegmanMeasure] = []
    if ui_custom.kegmanCPU or default_overlay:
      measures.append(self._cpu_measure())
    if ui_custom.kegmanGPULoad or default_overlay:
      measures.append(self._gpu_measure())

    if ui_custom.kegmanGPS or default_overlay:
      measures.append(self._gps_measure())

    if ui_custom.kegmanAngle or default_overlay:
      measures.append(self._steering_angle_measure())
    if ui_custom.kegmanDistance:
      measures.append(self._lead_distance_measure())
    if ui_custom.kegmanSpeed:
      measures.append(self._lead_speed_measure())
    if ui_custom.kegmanEngine:
      measures.append(self._engine_measure())

    if ui_custom.kegmanLag or default_overlay:
      measures.append(self._lag_measure())

    return measures

  def _draw_tpms_overlay(self, rect: rl.Rectangle) -> None:
    tpms = ui_state.sm["carState"].carSCustom.tpms
    scale = self._tpms_scale(rect)
    font_size = max(34, round(TPMS_FONT_SIZE * scale))
    col_gap = TPMS_COL_GAP * scale
    vertical_gap = TPMS_DM_VERTICAL_GAP * scale


    dm_radius = TPMS_DM_BTN_SIZE / 2
    dm_offset = UI_BORDER_SIZE + dm_radius - 10
    is_rhd = ui_state.sm["driverMonitoringState"].isRHD
    dm_x = rect.x + (rect.width - dm_offset if is_rhd else dm_offset)
    dm_y = rect.y + rect.height - dm_offset

    left_x = dm_x - col_gap
    right_x = dm_x + col_gap
    top_y = dm_y - dm_radius - vertical_gap
    bottom_y = min(dm_y + dm_radius + vertical_gap, rect.y + rect.height - UI_BORDER_SIZE - font_size)

    self._draw_tpms_text(left_x, top_y, self._tpms_text(tpms.fl), self._tpms_color(tpms.fl), font_size)
    self._draw_tpms_text(right_x, top_y, self._tpms_text(tpms.fr), self._tpms_color(tpms.fr), font_size)
    self._draw_tpms_text(left_x, bottom_y, self._tpms_text(tpms.rl), self._tpms_color(tpms.rl), font_size)
    self._draw_tpms_text(right_x, bottom_y, self._tpms_text(tpms.rr), self._tpms_color(tpms.rr), font_size)

  def _tpms_scale(self, rect: rl.Rectangle) -> float:
    return min(1.0, max(0.5, rect.width / 1860.0, rect.height / 1080.0))

  def _draw_tpms_text(self, x: float, y: float, text: str, color: rl.Color, font_size: int, align_right: bool = False) -> None:
    if align_right:
      text_size = measure_text_cached(self._font_tpms, text, font_size)
      x -= text_size.x
    rl.draw_text_ex(self._font_tpms, text, rl.Vector2(x, y), font_size, 0, color)

  def _tpms_text(self, pressure: float) -> str:
    if pressure < 5 or pressure > 200:
      return "-"
    return f"{pressure:.0f}"

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
      "C",
      f"CPU {cpu_usage:.1f}%",
      self._threshold_color(cpu_temp, 90, 60),
      self._threshold_color(cpu_usage, 92, 80),
      self._threshold_color(cpu_temp, 90, 60),
    )


  def _lag_measure(self) -> KegmanMeasure:
    cum_lag_ms = getattr(ui_state.sm["controlsState"].deprecated, "cumLagMs", 0.0)
    value_color = WHITE
    if cum_lag_ms < 10:
      value_color = GREEN
    elif cum_lag_ms > 100:
      value_color = RED
    return KegmanMeasure(f"{cum_lag_ms:.0f}", "ms", "Lag", value_color)

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

  def _gpu_measure(self) -> KegmanMeasure:
    device_state = ui_state.sm["deviceState"]
    gpu_temps = list(device_state.gpuTempC)
    gpu_temp = max(gpu_temps) if gpu_temps else 0.0
    gpu_usage = max(0, int(device_state.gpuUsagePercent))
    if gpu_temp > 120:
      gpu_temp = 0.0
    return KegmanMeasure(
      f"{gpu_temp:.1f}",
      "C",
      f"GPU {gpu_usage:.1f}%",
      self._threshold_color(gpu_temp, 90, 60),
      self._threshold_color(gpu_usage, 92, 80),
      self._threshold_color(gpu_temp, 90, 60),
    )

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

  def _tpms_color(self, pressure: float) -> rl.Color:
    if pressure < 5 or pressure > 60:
      return TPMS_DIM
    if pressure < 30:
      return TPMS_LOW
    return TPMS_WHITE

  def _steering_angle_color(self, angle: float) -> rl.Color:
    abs_angle = abs(angle)
    if abs_angle > 55:
      return RED
    if abs_angle > 30:
      return ORANGE
    return WHITE
