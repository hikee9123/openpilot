from __future__ import annotations

import json
import math
import time

import pyray as rl
from openpilot.selfdrive.ui.onroad.custom_overlay_layout import (
  kegman_overlay_columns,
  kegman_overlay_item_count,
  kegman_overlay_panel_layout,
  overlay_two_column_width,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


MINIMAP_MARGIN = 30.0
MINIMAP_MAX_HEIGHT = 300.0
MINIMAP_HEIGHT_FRACTION = 0.34
MINIMAP_MIN_HEIGHT = 180.0
MINIMAP_KEGMAN_GAP = 3.0
MINIMAP_RADIUS_ANIMATION_TAU_SECONDS = 0.22
MINIMAP_RADIUS_ANIMATION_EPSILON_M = 0.5
ROAD_DEFAULT = rl.Color(255, 255, 255, 86)
ROAD_MAJOR = rl.Color(135, 190, 220, 135)
ROAD_FORWARD = rl.Color(92, 230, 150, 170)
ROAD_PREDICTED = rl.Color(98, 255, 152, 225)
ROAD_CURRENT = rl.Color(47, 214, 114, 210)
CAMERA_COLOR = rl.Color(255, 198, 77, 235)
CAMERA_TEXT = rl.Color(255, 235, 180, 235)
EGO_COLOR = rl.Color(72, 156, 255, 240)
PANEL_BG = rl.Color(0, 0, 0, 136)
PANEL_BORDER = rl.Color(255, 255, 255, 58)
PANEL_GRID = rl.Color(255, 255, 255, 28)
TEXT_COLOR = rl.Color(230, 230, 230, 215)
OSM_OVERLAY_MODE_OFF = 0
OSM_OVERLAY_MODE_MINIMAP = 1


class OsmRoadOverlayRenderer(Widget):
  def __init__(self):
    super().__init__()
    self._last_text = ""
    self._data: dict = {}
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._animated_radius_m = 0.0
    self._last_animation_t = 0.0

  def _render(self, rect: rl.Rectangle) -> None:
    mode = int(ui_state.custom_params.get("OsmRoadOverlayMode", OSM_OVERLAY_MODE_OFF))
    if mode != OSM_OVERLAY_MODE_MINIMAP:
      return
    if ui_state.sm.recv_frame["naviCustom"] <= ui_state.started_frame:
      return

    nav = ui_state.sm["naviCustom"].naviData
    overlay_text = str(getattr(nav, "osmRoadOverlayText", ""))
    if not overlay_text:
      return

    data = self._parse_overlay(overlay_text)
    map_roads = data.get("mapRoads", [])
    cameras = data.get("cameras", [])
    if not map_roads and not cameras:
      return

    self._draw_minimap(rect, data)

  def _parse_overlay(self, overlay_text: str) -> dict:
    if overlay_text == self._last_text:
      return self._data
    self._last_text = overlay_text
    try:
      loaded = json.loads(overlay_text)
      self._data = loaded if isinstance(loaded, dict) else {}
    except (TypeError, ValueError):
      self._data = {}
    return self._data

  def _draw_minimap(self, rect: rl.Rectangle, data: dict) -> None:
    panel = minimap_rect(rect)
    panel_w = panel.width
    panel_h = panel.height
    rl.draw_rectangle_rounded(panel, 0.08, 8, PANEL_BG)
    rl.draw_rectangle_rounded_lines_ex(panel, 0.08, 8, 2.0, PANEL_BORDER)

    radius = self._animated_radius(max(100.0, float(data.get("mapRadius", 140.0))))
    scale = min((panel_w * 0.46) / radius, (panel_h * 0.70) / radius)
    origin = rl.Vector2(panel.x + panel_w * 0.5, panel.y + panel_h * 0.78)
    rl.draw_line(int(panel.x + 18), int(origin.y), int(panel.x + panel_w - 18), int(origin.y), PANEL_GRID)
    rl.draw_line(int(origin.x), int(panel.y + 18), int(origin.x), int(panel.y + panel_h - 18), PANEL_GRID)

    for road in data.get("mapRoads", []):
      p1 = self._project_to_map(origin, scale, float(road.get("x1", 0.0)), float(road.get("y1", 0.0)))
      p2 = self._project_to_map(origin, scale, float(road.get("x2", 0.0)), float(road.get("y2", 0.0)))
      clipped = self._clip_line_to_panel(panel, p1, p2)
      if clipped is None:
        continue
      rl.draw_line_ex(clipped[0], clipped[1], self._road_thickness(road), self._road_color(road))

    self._draw_ego(origin)
    for camera in data.get("cameras", []):
      point = self._project_to_map(origin, scale, float(camera.get("x", 0.0)), float(camera.get("y", 0.0)))
      if not self._point_in_panel(panel, point):
        continue
      rl.draw_circle(int(point.x), int(point.y), 9, rl.Color(0, 0, 0, 150))
      rl.draw_circle(int(point.x), int(point.y), 6, CAMERA_COLOR)
      rl.draw_text_ex(self._font_medium, str(camera.get("s", ""))[:3], rl.Vector2(point.x + 8, point.y - 11), 20, 0, CAMERA_TEXT)

    road_name = str(data.get("road", "")).strip()
    title = self._elide_text(road_name if road_name else "OSM roads", panel_w - 32.0, 24)
    rl.draw_text_ex(self._font_medium, title, rl.Vector2(panel.x + 16, panel.y + 12), 24, 0, TEXT_COLOR)

  @staticmethod
  def _road_color(road: dict) -> rl.Color:
    if road.get("c"):
      return ROAD_CURRENT
    if "pr" in road:
      return ROAD_PREDICTED
    if road.get("f"):
      return ROAD_FORWARD
    if str(road.get("h", "")) in ("motorway", "trunk", "primary"):
      return ROAD_MAJOR
    return ROAD_DEFAULT

  @staticmethod
  def _road_thickness(road: dict) -> float:
    if road.get("c"):
      return 5.0
    if "pr" in road:
      return 4.5 if int(road.get("pr", 0)) == 0 else 3.8
    if road.get("f"):
      return 4.0
    if str(road.get("h", "")) in ("motorway", "trunk", "primary"):
      return 3.0
    return 2.5

  def _elide_text(self, text: str, max_width: float, font_size: int) -> str:
    if measure_text_cached(self._font_medium, text, font_size).x <= max_width:
      return text
    ellipsis = "..."
    while text and measure_text_cached(self._font_medium, text + ellipsis, font_size).x > max_width:
      text = text[:-1]
    return (text.rstrip() + ellipsis) if text else ellipsis

  @staticmethod
  def _project_to_map(origin: rl.Vector2, scale: float, forward_m: float, right_m: float) -> rl.Vector2:
    return rl.Vector2(origin.x + right_m * scale, origin.y - forward_m * scale)

  @staticmethod
  def _point_in_panel(panel: rl.Rectangle, point: rl.Vector2) -> bool:
    return panel.x <= point.x <= panel.x + panel.width and panel.y <= point.y <= panel.y + panel.height

  @staticmethod
  def _clip_line_to_panel(panel: rl.Rectangle, p1: rl.Vector2, p2: rl.Vector2) -> tuple[rl.Vector2, rl.Vector2] | None:
    min_x = panel.x
    max_x = panel.x + panel.width
    min_y = panel.y
    max_y = panel.y + panel.height
    if min_x <= p1.x <= max_x and min_y <= p1.y <= max_y and min_x <= p2.x <= max_x and min_y <= p2.y <= max_y:
      return p1, p2

    dx = p2.x - p1.x
    dy = p2.y - p1.y
    u1 = 0.0
    u2 = 1.0
    for p, q in ((-dx, p1.x - min_x), (dx, max_x - p1.x), (-dy, p1.y - min_y), (dy, max_y - p1.y)):
      if p == 0.0:
        if q < 0.0:
          return None
        continue
      t = q / p
      if p < 0.0:
        if t > u2:
          return None
        u1 = max(u1, t)
      else:
        if t < u1:
          return None
        u2 = min(u2, t)

    return (
      rl.Vector2(p1.x + u1 * dx, p1.y + u1 * dy),
      rl.Vector2(p1.x + u2 * dx, p1.y + u2 * dy),
    )

  @staticmethod
  def _draw_ego(origin: rl.Vector2) -> None:
    points = [
      rl.Vector2(origin.x, origin.y - 15),
      rl.Vector2(origin.x - 10, origin.y + 12),
      rl.Vector2(origin.x + 10, origin.y + 12),
    ]
    rl.draw_triangle(points[0], points[1], points[2], EGO_COLOR)

  def _animated_radius(self, target_radius_m: float) -> float:
    now = time.monotonic()
    if self._animated_radius_m <= 0.0 or self._last_animation_t <= 0.0:
      self._animated_radius_m = target_radius_m
      self._last_animation_t = now
      return self._animated_radius_m

    dt = max(0.0, min(0.1, now - self._last_animation_t))
    self._last_animation_t = now
    alpha = 1.0 - math.exp(-dt / MINIMAP_RADIUS_ANIMATION_TAU_SECONDS)
    self._animated_radius_m += (target_radius_m - self._animated_radius_m) * alpha
    if abs(target_radius_m - self._animated_radius_m) <= MINIMAP_RADIUS_ANIMATION_EPSILON_M:
      self._animated_radius_m = target_radius_m
    return self._animated_radius_m


def minimap_rect(rect: rl.Rectangle) -> rl.Rectangle:
  panel_w = overlay_two_column_width(rect)
  panel_bottom = rect.y + rect.height - MINIMAP_MARGIN
  kegman_bottom = _kegman_panel_bottom(rect)
  if kegman_bottom is not None:
    panel_y = kegman_bottom + MINIMAP_KEGMAN_GAP
    panel_h = panel_bottom - panel_y
    if panel_h >= MINIMAP_MIN_HEIGHT:
      return rl.Rectangle(
        rect.x + rect.width - panel_w - MINIMAP_MARGIN,
        panel_y,
        panel_w,
        panel_h,
      )

  panel_h = min(MINIMAP_MAX_HEIGHT, rect.height * MINIMAP_HEIGHT_FRACTION)
  return rl.Rectangle(
    rect.x + rect.width - panel_w - MINIMAP_MARGIN,
    panel_bottom - panel_h,
    panel_w,
    panel_h,
  )


def _kegman_panel_bottom(rect: rl.Rectangle) -> float | None:
  try:
    ui_custom = ui_state.sm["uICustom"].userInterface
  except Exception:
    return None

  item_count = kegman_overlay_item_count(ui_custom)
  if item_count <= 0:
    return None

  columns = kegman_overlay_columns(item_count)
  panel = kegman_overlay_panel_layout(rect, item_count, columns)["panel_rect"]
  return panel.y + panel.height
