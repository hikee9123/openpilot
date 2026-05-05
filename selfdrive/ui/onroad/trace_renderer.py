from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


BASE_SIDE_MARGIN = 250
BASE_BOTTOM_MARGIN = 34
BASE_FONT_SIZE = 40
BASE_LINE_HEIGHT = 45
BASE_PADDING_X = 28
BASE_PADDING_Y = 10
PANEL_BG = rl.Color(0, 0, 0, 100)
TEXT_COLOR = rl.Color(255, 255, 255, 255)


class TraceRenderer(Widget):
  def __init__(self) -> None:
    super().__init__()
    self._font = gui_app.font(FontWeight.NORMAL)

  def _render(self, rect: rl.Rectangle) -> None:
    ui_custom = ui_state.sm["uICustom"].userInterface
    if not ui_custom.showDebugMessage:
      return

    car_custom = ui_state.sm["carState"].carSCustom
    lines = [
      str(car_custom.alertTextMsg1),
      str(car_custom.alertTextMsg2),
      str(car_custom.alertTextMsg3),
    ]

    scale = min(1.0, max(0.65, rect.width / 1920.0, rect.height / 1080.0))
    font_size = max(24, round(BASE_FONT_SIZE * scale))
    line_height = max(font_size + 5, round(BASE_LINE_HEIGHT * scale))
    padding_x = max(16, round(BASE_PADDING_X * scale))
    padding_y = max(8, round(BASE_PADDING_Y * scale))
    side_margin = min(BASE_SIDE_MARGIN * scale, rect.width * 0.18)
    panel_w = max(240.0, rect.width - side_margin * 2)
    panel_h = line_height * 3 + padding_y * 2
    panel_x = rect.x + (rect.width - panel_w) / 2
    panel_y = rect.y + rect.height - panel_h - BASE_BOTTOM_MARGIN * scale

    panel_rect = rl.Rectangle(panel_x, panel_y, panel_w, panel_h)
    rl.draw_rectangle_rounded(panel_rect, 0.20, 10, PANEL_BG)

    max_text_width = panel_w - padding_x * 2
    text_x = panel_x + padding_x
    for idx, line in enumerate(lines):
      text_y = panel_y + padding_y + idx * line_height
      rl.draw_text_ex(self._font, self._ellipsize(line, max_text_width, font_size),
                      rl.Vector2(text_x, text_y), font_size, 0, TEXT_COLOR)

  def _ellipsize(self, text: str, max_width: float, font_size: int) -> str:
    if measure_text_cached(self._font, text, font_size).x <= max_width:
      return text

    ellipsis = "..."
    while text and measure_text_cached(self._font, text + ellipsis, font_size).x > max_width:
      text = text[:-1]
    return text + ellipsis if text else ellipsis
