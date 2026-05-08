from __future__ import annotations

import json

import pyray as rl
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets import Widget


ROAD_DEFAULT = rl.Color(255, 255, 255, 86)
ROAD_MAJOR = rl.Color(135, 190, 220, 135)
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
    panel_w = min(360.0, rect.width * 0.30)
    panel_h = min(260.0, rect.height * 0.30)
    panel = rl.Rectangle(rect.x + rect.width - panel_w - 34, rect.y + rect.height - panel_h - 34, panel_w, panel_h)
    rl.draw_rectangle_rounded(panel, 0.08, 8, PANEL_BG)
    rl.draw_rectangle_rounded_lines_ex(panel, 0.08, 8, 2.0, PANEL_BORDER)

    radius = max(100.0, float(data.get("mapRadius", 140.0)))
    scale = min((panel_w * 0.46) / radius, (panel_h * 0.70) / radius)
    origin = rl.Vector2(panel.x + panel_w * 0.5, panel.y + panel_h * 0.78)
    rl.draw_line(int(panel.x + 18), int(origin.y), int(panel.x + panel_w - 18), int(origin.y), PANEL_GRID)
    rl.draw_line(int(origin.x), int(panel.y + 18), int(origin.x), int(panel.y + panel_h - 18), PANEL_GRID)

    for road in data.get("mapRoads", []):
      p1 = self._project_to_map(origin, scale, float(road.get("x1", 0.0)), float(road.get("y1", 0.0)))
      p2 = self._project_to_map(origin, scale, float(road.get("x2", 0.0)), float(road.get("y2", 0.0)))
      if not self._point_in_panel(panel, p1) and not self._point_in_panel(panel, p2):
        continue
      rl.draw_line_ex(p1, p2, 4.0 if road.get("c") else 2.0, self._road_color(road))

    self._draw_ego(origin)
    for camera in data.get("cameras", []):
      point = self._project_to_map(origin, scale, float(camera.get("x", 0.0)), float(camera.get("y", 0.0)))
      if not self._point_in_panel(panel, point):
        continue
      rl.draw_circle(int(point.x), int(point.y), 9, rl.Color(0, 0, 0, 150))
      rl.draw_circle(int(point.x), int(point.y), 6, CAMERA_COLOR)
      rl.draw_text_ex(self._font_medium, str(camera.get("s", ""))[:3], rl.Vector2(point.x + 8, point.y - 12), 22, 0, CAMERA_TEXT)

    road_name = str(data.get("road", "")).strip()
    title = road_name if road_name else "OSM roads"
    rl.draw_text_ex(self._font_medium, title[:22], rl.Vector2(panel.x + 16, panel.y + 12), 24, 0, TEXT_COLOR)

  @staticmethod
  def _road_color(road: dict) -> rl.Color:
    if road.get("c"):
      return ROAD_CURRENT
    if str(road.get("h", "")) in ("motorway", "trunk", "primary"):
      return ROAD_MAJOR
    return ROAD_DEFAULT

  @staticmethod
  def _project_to_map(origin: rl.Vector2, scale: float, forward_m: float, right_m: float) -> rl.Vector2:
    return rl.Vector2(origin.x + right_m * scale, origin.y - forward_m * scale)

  @staticmethod
  def _point_in_panel(panel: rl.Rectangle, point: rl.Vector2) -> bool:
    return panel.x <= point.x <= panel.x + panel.width and panel.y <= point.y <= panel.y + panel.height

  @staticmethod
  def _draw_ego(origin: rl.Vector2) -> None:
    points = [
      rl.Vector2(origin.x, origin.y - 15),
      rl.Vector2(origin.x - 10, origin.y + 12),
      rl.Vector2(origin.x + 10, origin.y + 12),
    ]
    rl.draw_triangle(points[0], points[1], points[2], EGO_COLOR)
