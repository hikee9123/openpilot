from __future__ import annotations

import pyray as rl


BASE_PANEL_WIDTH = 180.0
BASE_ITEM_HEIGHT = 105.0
BASE_PANEL_PADDING = 10.0
BASE_COLUMN_GAP = 12.0
BASE_MARGIN = 30.0


def overlay_scale_for_rect(rect: rl.Rectangle, rows: int) -> float:
  base_height = BASE_PANEL_PADDING * 2 + BASE_ITEM_HEIGHT * rows
  height_fit = max(0.18, (rect.height - 2 * BASE_MARGIN) / base_height)
  return min(1.0, max(0.18, rect.width / 1860.0, rect.height / 1080.0), height_fit)


def overlay_cell_width(rect: rl.Rectangle, scale: float) -> float:
  return max(120.0 if rect.height < 500 else 0.0, BASE_PANEL_WIDTH * scale)


def overlay_padding(scale: float) -> float:
  return max(4.0, BASE_PANEL_PADDING * scale)


def overlay_column_gap(scale: float) -> float:
  return max(6.0, BASE_COLUMN_GAP * scale)


def overlay_two_column_width(rect: rl.Rectangle, rows: int = 3) -> float:
  scale = overlay_scale_for_rect(rect, rows)
  return overlay_padding(scale) * 2 + overlay_cell_width(rect, scale) * 2 + overlay_column_gap(scale)
