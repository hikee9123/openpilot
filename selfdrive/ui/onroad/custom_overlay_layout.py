from __future__ import annotations

import pyray as rl


BASE_PANEL_WIDTH = 180.0
BASE_ITEM_HEIGHT = 105.0
BASE_PANEL_PADDING = 10.0
BASE_COLUMN_GAP = 12.0
BASE_MARGIN = 30.0
KEGMAN_BASE_TOP = 250.0
KEGMAN_MAX_ITEMS = 6


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


def kegman_overlay_item_count(ui_custom) -> int:
  if not getattr(ui_custom, "kegman", False):
    return 0

  default_overlay = not any((
    getattr(ui_custom, "kegmanCPU", False),
    getattr(ui_custom, "kegmanGPS", False),
    getattr(ui_custom, "kegmanGPULoad", False),
    getattr(ui_custom, "kegmanAngle", False),
    getattr(ui_custom, "kegmanDistance", False),
    getattr(ui_custom, "kegmanSpeed", False),
    getattr(ui_custom, "kegmanEngine", False),
    getattr(ui_custom, "kegmanLag", False),
  ))

  count = 0
  if getattr(ui_custom, "kegmanCPU", False) or default_overlay:
    count += 1
  if getattr(ui_custom, "kegmanGPULoad", False) or default_overlay:
    count += 1
  if getattr(ui_custom, "kegmanGPS", False) or default_overlay:
    count += 1
  if getattr(ui_custom, "kegmanAngle", False) or default_overlay:
    count += 1
  if getattr(ui_custom, "kegmanDistance", False):
    count += 1
  if getattr(ui_custom, "kegmanSpeed", False):
    count += 1
  if getattr(ui_custom, "kegmanEngine", False):
    count += 1
  if getattr(ui_custom, "kegmanLag", False) or default_overlay:
    count += 1
  return min(KEGMAN_MAX_ITEMS, count)


def kegman_overlay_columns(item_count: int) -> int:
  return 2 if item_count >= 5 else 1


def kegman_overlay_panel_layout(
  rect: rl.Rectangle,
  item_count: int,
  columns: int | None = None,
  obstacle_rect: rl.Rectangle | None = None,
  obstacle_clearance: float = 0.0,
) -> dict:
  columns = max(1, columns if columns is not None else kegman_overlay_columns(item_count))
  rows = (item_count + columns - 1) // columns
  scale = overlay_scale_for_rect(rect, rows)
  margin = max(4.0, BASE_MARGIN * scale)
  cell_width = overlay_cell_width(rect, scale)
  item_height = max(30.0, BASE_ITEM_HEIGHT * scale)
  padding = overlay_padding(scale)
  column_gap = overlay_column_gap(scale) if columns > 1 else 0.0
  panel_width = padding * 2 + cell_width * columns + column_gap if columns > 1 else cell_width
  panel_height = padding * 2 + item_height * rows

  x = rect.x + rect.width - panel_width - margin
  y = rect.y + KEGMAN_BASE_TOP * scale
  if rect.height < 500:
    y = rect.y + margin

  if obstacle_rect is not None:
    max_bottom = obstacle_rect.y - obstacle_clearance
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
