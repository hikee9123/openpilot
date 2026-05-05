from __future__ import annotations

import pyray as rl

from openpilot.common.constants import CV
from openpilot.selfdrive.ui.onroad.lead_tracking import LEAD_LANES, select_lane_leads
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


BASE_PANEL_WIDTH = 560
BASE_BOTTOM_MARGIN = 190
BASE_PADDING_X = 24
BASE_PADDING_Y = 18
BASE_TITLE_FONT_SIZE = 28
BASE_LINE_FONT_SIZE = 31
BASE_LINE_HEIGHT = 38
PANEL_BG = rl.Color(0, 0, 0, 115)
PANEL_BORDER = rl.Color(255, 255, 255, 80)
TITLE_COLOR = rl.Color(255, 255, 255, 210)
TEXT_COLOR = rl.Color(235, 235, 235, 225)
DIM_COLOR = rl.Color(160, 160, 160, 210)
WARN_COLOR = rl.Color(255, 188, 3, 225)
ALERT_COLOR = rl.Color(255, 90, 90, 225)


class CarTrackingRenderer(Widget):
  def __init__(self) -> None:
    super().__init__()
    self._title_font = gui_app.font(FontWeight.MEDIUM)
    self._text_font = gui_app.font(FontWeight.NORMAL)

  def _render(self, rect: rl.Rectangle) -> None:
    ui_custom = ui_state.sm["uICustom"].userInterface
    if not ui_custom.showCarTracking:
      return

    scale = min(1.0, max(0.66, rect.width / 1920.0, rect.height / 1080.0))
    title_font_size = max(18, round(BASE_TITLE_FONT_SIZE * scale))
    line_font_size = max(20, round(BASE_LINE_FONT_SIZE * scale))
    line_height = max(line_font_size + 6, round(BASE_LINE_HEIGHT * scale))
    padding_x = max(14, round(BASE_PADDING_X * scale))
    padding_y = max(12, round(BASE_PADDING_Y * scale))

    rows = self._tracking_rows()
    panel_w = min(rect.width * 0.62, max(360.0, BASE_PANEL_WIDTH * scale))
    panel_h = padding_y * 2 + title_font_size + 10 + line_height * len(rows)
    panel_x = rect.x + (rect.width - panel_w) / 2
    panel_y = rect.y + rect.height - panel_h - BASE_BOTTOM_MARGIN * scale
    panel_y = max(rect.y + 180 * scale, panel_y)

    panel_rect = rl.Rectangle(panel_x, panel_y, panel_w, panel_h)
    rl.draw_rectangle_rounded(panel_rect, 0.10, 10, PANEL_BG)
    rl.draw_rectangle_rounded_lines_ex(panel_rect, 0.10, 10, max(1.0, 2.0 * scale), PANEL_BORDER)

    title = "CAR TRACKING"
    title_x = panel_x + padding_x
    title_y = panel_y + padding_y
    rl.draw_text_ex(self._title_font, title, rl.Vector2(title_x, title_y), title_font_size, 0, TITLE_COLOR)

    max_text_width = panel_w - padding_x * 2
    row_y = title_y + title_font_size + 12 * scale
    for text, color in rows:
      rl.draw_text_ex(self._text_font, self._ellipsize(text, max_text_width, line_font_size),
                      rl.Vector2(title_x, row_y), line_font_size, 0, color)
      row_y += line_height

  def _tracking_rows(self) -> list[tuple[str, rl.Color]]:
    sm = ui_state.sm
    radar_state = sm["radarState"] if sm.valid["radarState"] else None
    live_tracks = sm["liveTracks"] if sm.valid["liveTracks"] else None
    leads = select_lane_leads(live_tracks, sm["modelV2"], radar_state)
    rows = [self._lead_row(lane, lead) for lane, lead in zip(LEAD_LANES, leads, strict=True)]

    custom = sm["carState"].carSCustom
    scc_distance = float(custom.leadDistance)
    gap = int(custom.gapSet)
    if scc_distance > 0:
      rows.append((f"SCC {scc_distance:.0f}m  GAP {gap}", self._distance_color(scc_distance)))
    else:
      rows.append((f"SCC none  GAP {gap}", DIM_COLOR))
    return rows

  def _lead_row(self, lane: str, lead) -> tuple[str, rl.Color]:
    if lead is None or not lead.status:
      return (f"{lane}: none", DIM_COLOR)

    speed_unit = "km/h" if ui_state.is_metric else "mph"
    speed = lead.vRel * (CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH)
    prob = max(0.0, min(100.0, float(getattr(lead, "modelProb", 0.0)) * 100.0))
    source = str(getattr(lead, "source", "RADAR" if bool(getattr(lead, "radar", False)) else "CAMERA"))
    track_id = int(getattr(lead, "radarTrackId", -1))
    source_text = f"{source}#{track_id}" if track_id >= 0 else source
    text = f"{lane}: {lead.dRel:.0f}m  {speed:+.1f}{speed_unit}  p{prob:.0f}%  {source_text}"
    return (text, self._lead_color(lead.dRel, lead.vRel))

  def _lead_color(self, distance: float, rel_speed: float) -> rl.Color:
    if distance < 8 or rel_speed < -5:
      return ALERT_COLOR
    if distance < 18 or rel_speed < -2:
      return WARN_COLOR
    return TEXT_COLOR

  def _distance_color(self, distance: float) -> rl.Color:
    if distance < 8:
      return ALERT_COLOR
    if distance < 18:
      return WARN_COLOR
    return TEXT_COLOR

  def _ellipsize(self, text: str, max_width: float, font_size: int) -> str:
    if measure_text_cached(self._text_font, text, font_size).x <= max_width:
      return text

    ellipsis = "..."
    while text and measure_text_cached(self._text_font, text + ellipsis, font_size).x > max_width:
      text = text[:-1]
    return text + ellipsis if text else ellipsis
