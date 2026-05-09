import math
import time
from dataclasses import dataclass

import pyray as rl
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.selfdrive.ui.custom import read_custom_params, speed_camera_debug_preview_active
from openpilot.selfdrive.ui.mici.onroad.torque_bar import TorqueBar
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.common.filter_simple import FirstOrderFilter
from cereal import log

EventName = log.OnroadEvent.EventName

# Constants
SET_SPEED_NA = 255
KM_TO_MILE = 0.621371
CRUISE_DISABLED_CHAR = '–'
SPEED_CAMERA_DEBUG_PREVIEW_POLL_INTERVAL = 0.5
SPEED_CAMERA_DEBUG_PREVIEW_LIMIT = 50
SPEED_CAMERA_DEBUG_PREVIEW_DISTANCE_M = 350
SPEED_CAMERA_DEBUG_PREVIEW_TYPE = 3
SPEED_CAMERA_DEBUG_PREVIEW_CATEGORY = "SPEED_SIGNAL"
SPEED_CAMERA_DEBUG_PREVIEW_ROAD_CLASS = "EXPRESSWAY"
SPEED_CAMERA_DEBUG_PREVIEW_ROAD_CLASS_CODE = 1
SPEED_CAMERA_DEBUG_PREVIEW_RELATIVE_ANGLE_DEG = 30.0
SPEED_CAMERA_DEBUG_PREVIEW_CANDIDATES = "road: preview road\n1 SPEED+SIGNAL 350m local\n2 SPEED 620m\n3 SIGNAL 910m"
SPEED_CAMERA_DEBUG_PREVIEW_TEXT = "\n".join((
  "CAM SPEED_SIGNAL c=3 v=50 id=preview",
  "POS 350m f=303 s=+175 a=+30 bear=0",
  "RAW type=preview dir=3/BOTH sect=0 len=0",
  "ROAD EXPRESSWAY | preview road",
  "PLACE preview road (source->target)",
  "WHY osm=Y cur=고속국도 corr=Y flags=-",
))

SET_SPEED_PERSISTENCE = 2.5  # seconds


@dataclass(frozen=True)
class FontSizes:
  current_speed: int = 176
  speed_unit: int = 66
  max_speed: int = 36
  set_speed: int = 112


@dataclass(frozen=True)
class Colors:
  WHITE = rl.WHITE
  WHITE_TRANSLUCENT = rl.Color(255, 255, 255, 200)
  BLACK_TRANSLUCENT = rl.Color(0, 0, 0, 150)
  SPEED_CAMERA = rl.Color(255, 198, 77, 230)
  SPEED_SIGN_RED = rl.Color(210, 32, 42, 255)
  SPEED_SIGN_RING_RED = rl.Color(210, 32, 42, 255)
  SPEED_SIGN_RING_BLUE = rl.Color(52, 120, 246, 255)
  SPEED_SIGN_INNER = rl.WHITE
  SPEED_SIGN_SEARCH_AREA = rl.Color(255, 198, 77, 45)
  SPEED_SIGN_TEXT = rl.Color(18, 18, 18, 255)
  SIGNAL_BADGE_BODY = rl.Color(16, 18, 22, 230)
  SIGNAL_BADGE_BORDER = rl.Color(52, 120, 246, 255)
  SIGNAL_RED = rl.Color(235, 56, 64, 255)
  SIGNAL_YELLOW = rl.Color(245, 190, 64, 255)
  SIGNAL_GREEN = rl.Color(55, 210, 125, 255)


FONT_SIZES = FontSizes()
COLORS = Colors()


class TurnIntent(Widget):
  FADE_IN_ANGLE = 30  # degrees

  def __init__(self):
    super().__init__()
    self._pre = False
    self._turn_intent_direction: int = 0

    self._turn_intent_alpha_filter = FirstOrderFilter(0, 0.05, 1 / gui_app.target_fps)
    self._turn_intent_rotation_filter = FirstOrderFilter(0, 0.1, 1 / gui_app.target_fps)

    self._txt_turn_intent_left: rl.Texture = gui_app.texture('icons_mici/turn_intent_left.png', 50, 20)
    self._txt_turn_intent_right: rl.Texture = gui_app.texture('icons_mici/turn_intent_left.png', 50, 20, flip_x=True)

  def _render(self, _):
    if self._turn_intent_alpha_filter.x > 1e-2:
      turn_intent_texture = (
        self._txt_turn_intent_right if self._turn_intent_direction == 1 else self._txt_turn_intent_left
      )
      src_rect = rl.Rectangle(0, 0, turn_intent_texture.width, turn_intent_texture.height)
      dest_rect = rl.Rectangle(self._rect.x + self._rect.width / 2, self._rect.y + self._rect.height / 2,
                               turn_intent_texture.width, turn_intent_texture.height)

      origin = (turn_intent_texture.width / 2, self._rect.height / 2)
      color = rl.Color(255, 255, 255, int(255 * self._turn_intent_alpha_filter.x))
      rl.draw_texture_pro(turn_intent_texture, src_rect, dest_rect, origin, self._turn_intent_rotation_filter.x, color)

  def _update_state(self) -> None:
    sm = ui_state.sm

    left = any(e.name == EventName.preLaneChangeLeft for e in sm['onroadEvents'])
    right = any(e.name == EventName.preLaneChangeRight for e in sm['onroadEvents'])
    if left or right:
      # pre lane change
      if not self._pre:
        self._turn_intent_rotation_filter.x = self.FADE_IN_ANGLE if left else -self.FADE_IN_ANGLE

      self._pre = True
      self._turn_intent_direction = -1 if left else 1
      self._turn_intent_alpha_filter.update(1)
      self._turn_intent_rotation_filter.update(0)
    elif any(e.name == EventName.laneChange for e in sm['onroadEvents']):
      # fade out and rotate away
      self._pre = False
      self._turn_intent_alpha_filter.update(0)

      if self._turn_intent_direction == 0:
        # unknown. missed pre frame?
        self._turn_intent_rotation_filter.update(0)
      else:
        self._turn_intent_rotation_filter.update(self._turn_intent_direction * self.FADE_IN_ANGLE)
    else:
      # didn't complete lane change, just hide
      self._pre = False
      self._turn_intent_direction = 0
      self._turn_intent_alpha_filter.update(0)
      self._turn_intent_rotation_filter.update(0)


class HudRenderer(Widget):
  def __init__(self):
    super().__init__()
    """Initialize the HUD renderer."""
    self.is_cruise_set: bool = False
    self.is_cruise_available: bool = True
    self.set_speed: float = SET_SPEED_NA
    self._set_speed_changed_time: float = 0
    self.speed: float = 0.0
    self.v_ego_cluster_seen: bool = False
    self._engaged: bool = False
    self.camera_alert_active: bool = False
    self.camera_limit_speed: int = 0
    self.camera_distance_m: int = 0
    self.camera_category: str = ""
    self.camera_category_code: int = 0
    self.camera_type: int = 0
    self.road_class: str = ""
    self.road_class_code: int = 0
    self.camera_bearing_deg: float = 0.0
    self.camera_relative_angle_deg: float = 0.0
    self.camera_candidates_text: str = ""
    self.camera_debug_text: str = ""
    self.show_speed_camera_candidates: bool = False
    self.show_speed_camera_debug_text: bool = False
    self._camera_pointer_angle_filter = FirstOrderFilter(0.0, 0.25, 1 / gui_app.target_fps, initialized=False)
    self.camera_search_angle_deg: float = 35.0
    self._camera_search_angle_last_check: float = 0.0
    self._params = Params()

    self._can_draw_top_icons = True
    self._show_wheel_critical = False

    self._font_bold: rl.Font = gui_app.font(FontWeight.BOLD)
    self._font_medium: rl.Font = gui_app.font(FontWeight.MEDIUM)
    self._font_semi_bold: rl.Font = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_display: rl.Font = gui_app.font(FontWeight.DISPLAY)

    self._turn_intent = TurnIntent()
    self._torque_bar = TorqueBar()

    self._txt_wheel: rl.Texture = gui_app.texture('icons_mici/wheel.png', 50, 50)
    self._txt_wheel_critical: rl.Texture = gui_app.texture('icons_mici/wheel_critical.png', 50, 50)
    self._txt_exclamation_point: rl.Texture = gui_app.texture('icons_mici/exclamation_point.png', 9, 44)

    self._wheel_alpha_filter = FirstOrderFilter(0, 0.05, 1 / gui_app.target_fps)
    self._wheel_y_filter = FirstOrderFilter(0, 0.1, 1 / gui_app.target_fps)

    self._set_speed_alpha_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)

  def set_wheel_critical_icon(self, critical: bool):
    """Set the wheel icon to critical or normal state."""
    self._show_wheel_critical = critical

  def set_can_draw_top_icons(self, can_draw_top_icons: bool):
    """Set whether to draw the top part of the HUD."""
    self._can_draw_top_icons = can_draw_top_icons

  def drawing_top_icons(self) -> bool:
    # whether we're drawing any top icons currently
    return bool(self._set_speed_alpha_filter.x > 1e-2 or (self.camera_alert_active and self._can_draw_top_icons))

  def _update_state(self) -> None:
    """Update HUD state based on car state and controls state."""
    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      self.is_cruise_set = False
      self.set_speed = SET_SPEED_NA
      self.speed = 0.0
      self._clear_camera_alert()
      if self._speed_camera_preview_active():
        self._apply_speed_camera_preview()
      return

    controls_state = sm['controlsState']
    car_state = sm['carState']

    v_cruise_cluster = car_state.vCruiseCluster
    set_speed = (
      controls_state.deprecated.vCruise if v_cruise_cluster == 0.0 else v_cruise_cluster
    )
    engaged = sm['selfdriveState'].enabled
    if (set_speed != self.set_speed and engaged) or (engaged and not self._engaged):
      self._set_speed_changed_time = rl.get_time()
    self._engaged = engaged
    self.set_speed = set_speed
    self.is_cruise_set = 0 < self.set_speed < SET_SPEED_NA
    self.is_cruise_available = self.set_speed != -1

    v_ego_cluster = car_state.vEgoCluster
    self.v_ego_cluster_seen = self.v_ego_cluster_seen or v_ego_cluster != 0.0
    v_ego = v_ego_cluster if self.v_ego_cluster_seen else car_state.vEgo
    speed_conversion = CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH
    self.speed = max(0.0, v_ego * speed_conversion)
    self._update_camera_alert(sm)

  def _render(self, rect: rl.Rectangle) -> None:
    """Render HUD elements to the screen."""

    self._torque_bar.render(rect)

    if self.is_cruise_set:
      self._draw_set_speed(rect)

    self._draw_speed_camera_alert(rect)
    self._draw_camera_debug_text(rect)
    self._draw_steering_wheel(rect)

  def _draw_steering_wheel(self, rect: rl.Rectangle) -> None:
    wheel_txt = self._txt_wheel_critical if self._show_wheel_critical else self._txt_wheel

    if self._show_wheel_critical:
      self._wheel_alpha_filter.update(255)
      self._wheel_y_filter.update(0)
    else:
      if ui_state.status == UIStatus.DISENGAGED:
        self._wheel_alpha_filter.update(0)
        self._wheel_y_filter.update(wheel_txt.height / 2)
      else:
        self._wheel_alpha_filter.update(255 * 0.9)
        self._wheel_y_filter.update(0)

    # pos
    pos_x = int(rect.x + 21 + wheel_txt.width / 2)
    pos_y = int(rect.y + rect.height - 14 - wheel_txt.height / 2 + self._wheel_y_filter.x)
    rotation = -ui_state.sm['carState'].steeringAngleDeg

    turn_intent_margin = 25
    self._turn_intent.render(rl.Rectangle(
      pos_x - wheel_txt.width / 2 - turn_intent_margin,
      pos_y - wheel_txt.height / 2 - turn_intent_margin,
      wheel_txt.width + turn_intent_margin * 2,
      wheel_txt.height + turn_intent_margin * 2,
    ))

    src_rect = rl.Rectangle(0, 0, wheel_txt.width, wheel_txt.height)
    dest_rect = rl.Rectangle(pos_x, pos_y, wheel_txt.width, wheel_txt.height)
    origin = (wheel_txt.width / 2, wheel_txt.height / 2)

    # color and draw
    color = rl.Color(255, 255, 255, int(self._wheel_alpha_filter.x))
    rl.draw_texture_pro(wheel_txt, src_rect, dest_rect, origin, rotation, color)

    if self._show_wheel_critical:
      # Draw exclamation point icon
      EXCLAMATION_POINT_SPACING = 10
      exclamation_pos_x = (
        pos_x - self._txt_exclamation_point.width / 2 + wheel_txt.width / 2 + EXCLAMATION_POINT_SPACING
      )
      exclamation_pos_y = pos_y - self._txt_exclamation_point.height / 2
      rl.draw_texture_ex(
        self._txt_exclamation_point, rl.Vector2(exclamation_pos_x, exclamation_pos_y), 0.0, 1.0, rl.WHITE
      )

  def _draw_set_speed(self, rect: rl.Rectangle) -> None:
    """Draw the MAX speed indicator box."""
    alpha = self._set_speed_alpha_filter.update(
      0 < rl.get_time() - self._set_speed_changed_time < SET_SPEED_PERSISTENCE
      and self._can_draw_top_icons
      and self._engaged
    )
    if alpha < 1e-2:
      return

    x = rect.x
    y = rect.y

    # draw drop shadow
    circle_radius = 162 // 2
    rl.draw_circle_gradient(int(x + circle_radius), int(y + circle_radius), circle_radius,
                            rl.Color(0, 0, 0, int(255 / 2 * alpha)), rl.BLANK)

    set_speed_color = rl.Color(255, 255, 255, int(255 * 0.9 * alpha))
    max_color = rl.Color(255, 255, 255, int(255 * 0.9 * alpha))

    set_speed = self.set_speed
    if self.is_cruise_set and not ui_state.is_metric:
      set_speed *= KM_TO_MILE

    set_speed_text = CRUISE_DISABLED_CHAR if not self.is_cruise_set else str(round(set_speed))
    rl.draw_text_ex(
      self._font_display,
      set_speed_text,
      rl.Vector2(x + 13 + 4, y + 3 - 8 - 3 + 4),
      FONT_SIZES.set_speed,
      0,
      set_speed_color,
    )

    max_text = tr("MAX")
    rl.draw_text_ex(
      self._font_semi_bold,
      max_text,
      rl.Vector2(x + 25, y + FONT_SIZES.set_speed - 7 + 4),
      FONT_SIZES.max_speed,
      0,
      max_color,
    )

  def _update_camera_alert(self, sm) -> None:
    if sm.recv_frame["naviCustom"] <= ui_state.started_frame:
      self._clear_camera_alert()
      if self._speed_camera_preview_active():
        self._apply_speed_camera_preview()
      return

    nav = sm["naviCustom"].naviData
    self.camera_alert_active = bool(nav.active and nav.camType != 0 and nav.camLimitSpeedLeftDist > 0)
    self.camera_limit_speed = int(nav.camLimitSpeed)
    self.camera_distance_m = int(nav.camLimitSpeedLeftDist)
    self.camera_type = int(nav.camType)
    self.camera_category = str(getattr(nav, "camCategory", ""))
    self.camera_category_code = int(getattr(nav, "camCategoryCode", self.camera_type))
    self.road_class = str(getattr(nav, "roadClass", ""))
    self.road_class_code = int(getattr(nav, "roadClassCode", 0))
    self.camera_bearing_deg = float(getattr(nav, "camBearingDeg", 0.0))
    self.camera_relative_angle_deg = float(getattr(nav, "camRelativeAngleDeg", 0.0))
    self.camera_candidates_text = str(getattr(nav, "camCandidatesText", ""))
    self.camera_debug_text = str(getattr(nav, "camDebugText", ""))
    if not self.camera_alert_active:
      if self._speed_camera_preview_active():
        self._apply_speed_camera_preview()
      else:
        self._clear_camera_alert()

  def _clear_camera_alert(self) -> None:
    self.camera_alert_active = False
    self.camera_limit_speed = 0
    self.camera_distance_m = 0
    self.camera_type = 0
    self.camera_category = ""
    self.camera_category_code = 0
    self.road_class = ""
    self.road_class_code = 0
    self.camera_bearing_deg = 0.0
    self.camera_relative_angle_deg = 0.0
    self.camera_candidates_text = ""
    self.camera_debug_text = ""
    self._camera_pointer_angle_filter.initialized = False

  def _speed_camera_preview_active(self) -> bool:
    return speed_camera_debug_preview_active()

  def speed_camera_preview_active(self) -> bool:
    return self._speed_camera_preview_active()

  def _apply_speed_camera_preview(self) -> None:
    self.camera_alert_active = True
    self.camera_limit_speed = SPEED_CAMERA_DEBUG_PREVIEW_LIMIT
    self.camera_distance_m = SPEED_CAMERA_DEBUG_PREVIEW_DISTANCE_M
    self.camera_type = SPEED_CAMERA_DEBUG_PREVIEW_TYPE
    self.camera_category = SPEED_CAMERA_DEBUG_PREVIEW_CATEGORY
    self.camera_category_code = SPEED_CAMERA_DEBUG_PREVIEW_TYPE
    self.road_class = SPEED_CAMERA_DEBUG_PREVIEW_ROAD_CLASS
    self.road_class_code = SPEED_CAMERA_DEBUG_PREVIEW_ROAD_CLASS_CODE
    self.camera_bearing_deg = 0.0
    self.camera_relative_angle_deg = SPEED_CAMERA_DEBUG_PREVIEW_RELATIVE_ANGLE_DEG
    self.camera_candidates_text = SPEED_CAMERA_DEBUG_PREVIEW_CANDIDATES
    self.camera_debug_text = SPEED_CAMERA_DEBUG_PREVIEW_TEXT

  def _draw_speed_camera_alert(self, rect: rl.Rectangle) -> None:
    if not self.camera_alert_active or not self._can_draw_top_icons:
      return

    width = 172
    x = rect.x
    y = rect.y + 176

    sign_lines = self._camera_sign_lines()
    distance_text = self._format_distance(self.camera_distance_m)
    info_label = self._camera_info_label().replace(" / ", "/")

    sign_radius = self._speed_sign_radius()
    sign_center_x = x + width / 2
    sign_center_y = y + 70
    self._draw_speed_limit_sign(sign_center_x, sign_center_y, sign_radius, sign_lines)
    if self._is_signal_camera_category(self.camera_category, self.camera_type):
      self._draw_signal_badge(sign_center_x, max(rect.y + 4, sign_center_y - sign_radius + 6))

    distance_size = measure_text_cached(self._font_medium, distance_text, 22)
    rl.draw_text_ex(
      self._font_medium,
      distance_text,
      rl.Vector2(x + (width - distance_size.x) / 2, y + 142),
      22,
      0,
      COLORS.WHITE_TRANSLUCENT,
    )

    label_text, label_font_size, label_size = self._fit_text(info_label, width, 16, 12)
    rl.draw_text_ex(
      self._font_medium,
      label_text,
      rl.Vector2(x + (width - label_size.x) / 2, y + 166),
      label_font_size,
      0,
      COLORS.SPEED_CAMERA,
    )
    self._draw_camera_candidates_text(x, y + 190, width, 3, 13, 16)

  def _draw_speed_limit_sign(self, center_x: float, center_y: float, radius: int, sign_lines: tuple[str, str]) -> None:
    is_speed = self._is_speed_camera_category(self.camera_category, self.camera_type)
    inner_gap = 10 if is_speed else 8
    rl.draw_circle(int(center_x), int(center_y), radius, self._speed_sign_ring_color())
    rl.draw_circle(int(center_x), int(center_y), radius - inner_gap, COLORS.SPEED_SIGN_INNER)
    self._draw_camera_search_area(center_x, center_y, radius - inner_gap - 4)
    self._draw_camera_direction_pointer(center_x, center_y, radius)

    primary_text, secondary_text = sign_lines
    if secondary_text:
      primary_font_size = 21
      secondary_font_size = 32 if len(secondary_text) <= 2 else 27
      primary_size = measure_text_cached(self._font_bold, primary_text, primary_font_size)
      secondary_size = measure_text_cached(self._font_bold, secondary_text, secondary_font_size)
      gap = 0
      y = center_y - (primary_size.y + secondary_size.y + gap) / 2
      rl.draw_text_ex(
        self._font_bold,
        primary_text,
        rl.Vector2(center_x - primary_size.x / 2, y),
        primary_font_size,
        0,
        COLORS.SPEED_SIGN_TEXT,
      )
      rl.draw_text_ex(
        self._font_bold,
        secondary_text,
        rl.Vector2(center_x - secondary_size.x / 2, y + primary_size.y + gap),
        secondary_font_size,
        0,
        COLORS.SPEED_SIGN_TEXT,
      )
      return

    font_size = 54 if is_speed and len(primary_text) <= 2 else 44 if is_speed else 46 if len(primary_text) <= 2 else 38
    text_size = measure_text_cached(self._font_bold, primary_text, font_size)
    rl.draw_text_ex(
      self._font_bold,
      primary_text,
      rl.Vector2(center_x - text_size.x / 2, center_y - text_size.y / 2),
      font_size,
      0,
      COLORS.SPEED_SIGN_TEXT,
    )

  def _draw_signal_badge(self, center_x: float, top_y: float) -> None:
    badge_w = 48
    badge_h = 16
    lamp_r = 4
    lamp_gap = 2
    lamp_d = lamp_r * 2
    lamps_w = lamp_d * 3 + lamp_gap * 2
    badge_x = center_x - badge_w / 2
    badge_y = top_y

    badge_rect = rl.Rectangle(badge_x, badge_y, badge_w, badge_h)
    rl.draw_rectangle_rounded(badge_rect, 0.45, 8, COLORS.SIGNAL_BADGE_BODY)
    rl.draw_rectangle_rounded_lines_ex(badge_rect, 0.45, 8, 1, COLORS.SIGNAL_BADGE_BORDER)

    start_x = badge_x + (badge_w - lamps_w) / 2 + lamp_r
    lamp_y = badge_y + badge_h / 2
    step = lamp_d + lamp_gap
    rl.draw_circle(int(start_x), int(lamp_y), lamp_r, COLORS.SIGNAL_RED)
    rl.draw_circle(int(start_x + step), int(lamp_y), lamp_r, COLORS.SIGNAL_YELLOW)
    rl.draw_circle(int(start_x + step * 2), int(lamp_y), lamp_r, COLORS.SIGNAL_GREEN)

  def _draw_camera_direction_pointer(self, center_x: float, center_y: float, radius: int) -> None:
    angle_rad = math.radians(self._filtered_camera_pointer_angle())
    direction_x = math.sin(angle_rad)
    direction_y = -math.cos(angle_rad)
    perpendicular_x = math.cos(angle_rad)
    perpendicular_y = math.sin(angle_rad)
    pointer_length = max(10.0, radius * 0.23)
    pointer_half_width = max(6.0, radius * 0.11)
    tip_radius = radius - 10.0
    base_radius = max(0.0, tip_radius - pointer_length)

    tip = rl.Vector2(center_x + direction_x * tip_radius, center_y + direction_y * tip_radius)
    base_center_x = center_x + direction_x * base_radius
    base_center_y = center_y + direction_y * base_radius
    left = rl.Vector2(base_center_x + perpendicular_x * pointer_half_width, base_center_y + perpendicular_y * pointer_half_width)
    right = rl.Vector2(base_center_x - perpendicular_x * pointer_half_width, base_center_y - perpendicular_y * pointer_half_width)
    rl.draw_triangle(tip, right, left, self._camera_pointer_color())

  def _draw_camera_search_area(self, center_x: float, center_y: float, radius: float) -> None:
    half_angle = max(0.0, min(180.0, self._camera_search_angle()))
    if radius <= 0.0 or half_angle <= 0.0:
      return

    segments = max(12, int(half_angle * 2.0 / 5.0))
    points = [rl.Vector2(center_x, center_y)]
    for i in range(segments + 1):
      angle_deg = -half_angle + (half_angle * 2.0 * i / segments)
      angle_rad = math.radians(angle_deg)
      points.append(rl.Vector2(center_x + math.sin(angle_rad) * radius, center_y - math.cos(angle_rad) * radius))

    rl.draw_triangle_fan(points, len(points), COLORS.SPEED_SIGN_SEARCH_AREA)

  def _camera_search_angle(self) -> float:
    now = time.time()
    if now - self._camera_search_angle_last_check >= SPEED_CAMERA_DEBUG_PREVIEW_POLL_INTERVAL:
      self._camera_search_angle_last_check = now
      try:
        values = read_custom_params(self._params)
        self.camera_search_angle_deg = max(15.0, min(60.0, float(values.get("SpeedCameraLookaheadAngle", 35))))
        self.show_speed_camera_candidates = bool(values.get("ShowSpeedCameraCandidates", False))
        self.show_speed_camera_debug_text = bool(values.get("ShowSpeedCameraDebugText", False))
      except (TypeError, ValueError):
        self.camera_search_angle_deg = 35.0
        self.show_speed_camera_candidates = False
        self.show_speed_camera_debug_text = False
    return self.camera_search_angle_deg

  def _draw_camera_candidates_text(self, x: float, y: float, width: float, max_lines: int, font_size: int, line_height: int) -> None:
    if not self.show_speed_camera_candidates or not self.camera_candidates_text:
      return

    lines = [line.strip() for line in self.camera_candidates_text.splitlines() if line.strip()][:max_lines]
    for idx, line in enumerate(lines):
      line_text, line_font_size, _ = self._fit_text(line, width, font_size, max(10, font_size - 3))
      rl.draw_text_ex(
        self._font_medium,
        line_text,
        rl.Vector2(x, y + idx * line_height),
        line_font_size,
        0,
        COLORS.WHITE_TRANSLUCENT,
      )

  def _draw_camera_debug_text(self, rect: rl.Rectangle) -> None:
    self._camera_search_angle()
    if not self.camera_alert_active or not self.show_speed_camera_debug_text or not self.camera_debug_text:
      return

    lines = [line.strip() for line in self.camera_debug_text.splitlines() if line.strip()][:6]
    if not lines:
      return

    max_width = min(rect.width * 0.84, 1080)
    font_size = 41
    line_height = 50
    padding_x = 28
    padding_y = 21
    fitted_lines = [self._fit_text(line, max_width - padding_x * 2, font_size, 30) for line in lines]
    box_width = min(max_width, max(size.x for _, _, size in fitted_lines) + padding_x * 2)
    box_height = len(fitted_lines) * line_height + padding_y * 2
    x = rect.x + (rect.width - box_width) / 2
    y = rect.y + rect.height * 0.48
    box_rect = rl.Rectangle(x, y, box_width, box_height)
    rl.draw_rectangle_rounded(box_rect, 0.18, 8, COLORS.BLACK_TRANSLUCENT)

    for idx, (line, line_font_size, line_size) in enumerate(fitted_lines):
      rl.draw_text_ex(
        self._font_medium,
        line,
        rl.Vector2(x + padding_x, y + padding_y + idx * line_height),
        line_font_size,
        0,
        COLORS.WHITE_TRANSLUCENT,
      )

  def _filtered_camera_pointer_angle(self) -> float:
    target_angle = (self.camera_relative_angle_deg + 180.0) % 360.0 - 180.0
    if not self._camera_pointer_angle_filter.initialized:
      return self._camera_pointer_angle_filter.update(target_angle)

    angle_diff = (target_angle - self._camera_pointer_angle_filter.x + 180.0) % 360.0 - 180.0
    return self._camera_pointer_angle_filter.update(self._camera_pointer_angle_filter.x + angle_diff)

  def _camera_sign_lines(self) -> tuple[str, str]:
    if self._is_speed_camera_category(self.camera_category, self.camera_type):
      return (str(self.camera_limit_speed) if self.camera_limit_speed > 0 else "--", "")
    if self._is_signal_camera_category(self.camera_category, self.camera_type):
      return ("SIG", str(self.camera_limit_speed) if self.camera_limit_speed > 0 else "")
    if self._is_security_camera_category(self.camera_category, self.camera_type):
      return ("SEC", "")
    if self._is_protected_zone_category(self.camera_category, self.camera_type):
      return ("ZONE", str(self.camera_limit_speed) if self.camera_limit_speed > 0 else "")
    return ("--", "")

  def _camera_category_label(self, category: str, cam_type: int) -> str:
    if category == "SPEED":
      return tr("Speed")
    if category == "SIGNAL":
      return tr("Signal")
    if category == "SPEED_SIGNAL":
      return tr("Speed+Signal")
    if category == "SECTION_SPEED":
      return tr("Section")
    if category == "PARKING":
      return tr("Parking")
    if category == "BUS_LANE":
      return tr("Bus Lane")
    if category == "TRAFFIC":
      return tr("Traffic")
    if category == "SECURITY":
      return tr("Security")
    if category == "PROTECTED_ZONE":
      return tr("Protected")

    if cam_type == 1:
      return tr("Speed")
    if cam_type == 2:
      return tr("Signal")
    if cam_type == 3:
      return tr("Speed+Signal")
    if cam_type == 4:
      return tr("Section")
    if cam_type == 8:
      return tr("Security")
    if cam_type == 10:
      return tr("Protected")

    return tr("Camera")

  def _road_class_label(self, road_class: str, road_class_code: int) -> str:
    if road_class == "EXPRESSWAY":
      return tr("Expressway")
    if road_class == "NATIONAL_ROAD":
      return tr("National")
    if road_class == "NATIONAL_LOCAL_ROAD":
      return tr("Nat.Local")
    if road_class == "LOCAL_ROAD":
      return tr("Local")
    if road_class == "CITY_ROAD":
      return tr("City")
    if road_class == "COUNTY_ROAD":
      return tr("County")
    if road_class == "DISTRICT_ROAD":
      return tr("District")
    if road_class == "ETC":
      return tr("Road")

    if road_class_code == 1:
      return tr("Expressway")
    if road_class_code == 2:
      return tr("National")
    if road_class_code == 3:
      return tr("Nat.Local")
    if road_class_code == 4:
      return tr("Local")
    if road_class_code == 5:
      return tr("City")

    return ""

  def _camera_info_label(self) -> str:
    category_label = self._camera_category_label(self.camera_category, self.camera_type)
    road_label = self._road_class_label(self.road_class, self.road_class_code)

    if road_label:
      return f"{category_label} / {road_label}"
    return category_label

  def _is_speed_camera_category(self, category: str, cam_type: int) -> bool:
    if category in ("SPEED", "SPEED_SIGNAL", "SECTION_SPEED"):
      return True

    if cam_type in (1, 3, 4):
      return True

    return False

  def _is_signal_camera_category(self, category: str, cam_type: int) -> bool:
    return category in ("SIGNAL", "SPEED_SIGNAL") or cam_type in (2, 3)

  def _is_security_camera_category(self, category: str, cam_type: int) -> bool:
    return category == "SECURITY" or cam_type == 8

  def _is_protected_zone_category(self, category: str, cam_type: int) -> bool:
    return category == "PROTECTED_ZONE" or cam_type == 10

  def _speed_sign_ring_color(self) -> rl.Color:
    if self._is_speed_camera_category(self.camera_category, self.camera_type):
      return COLORS.SPEED_SIGN_RING_RED
    return COLORS.SPEED_SIGN_RING_BLUE

  def _camera_pointer_color(self) -> rl.Color:
    if self._is_speed_camera_category(self.camera_category, self.camera_type):
      return COLORS.SPEED_SIGN_RING_BLUE
    return COLORS.SPEED_SIGN_RING_RED

  def _speed_sign_radius(self) -> int:
    if self._is_speed_camera_category(self.camera_category, self.camera_type):
      return 66
    if self._is_signal_camera_category(self.camera_category, self.camera_type):
      return 58
    if self._is_security_camera_category(self.camera_category, self.camera_type):
      return 58
    if self._is_protected_zone_category(self.camera_category, self.camera_type):
      return 61
    return 52

  def _fit_text(self, text: str, max_width: float, font_size: int, min_font_size: int) -> tuple[str, int, rl.Vector2]:
    for size in range(font_size, min_font_size - 1, -1):
      text_size = measure_text_cached(self._font_medium, text, size)
      if text_size.x <= max_width:
        return text, size, text_size

    fitted = text
    suffix = "..."
    while fitted:
      candidate = fitted + suffix
      text_size = measure_text_cached(self._font_medium, candidate, min_font_size)
      if text_size.x <= max_width:
        return candidate, min_font_size, text_size
      fitted = fitted[:-1]

    text_size = measure_text_cached(self._font_medium, suffix, min_font_size)
    return suffix, min_font_size, text_size

  def _format_distance(self, distance_m: int) -> str:
    if distance_m >= 1000:
      return f"{distance_m / 1000.0:.1f}km"
    return f"{distance_m}m"

  def _draw_current_speed(self, rect: rl.Rectangle) -> None:
    """Draw the current vehicle speed and unit."""
    speed_text = str(round(self.speed))
    speed_text_size = measure_text_cached(self._font_bold, speed_text, FONT_SIZES.current_speed)
    speed_pos = rl.Vector2(rect.x + rect.width / 2 - speed_text_size.x / 2, 180 - speed_text_size.y / 2)
    rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, COLORS.WHITE)

    unit_text = tr("km/h") if ui_state.is_metric else tr("mph")
    unit_text_size = measure_text_cached(self._font_medium, unit_text, FONT_SIZES.speed_unit)
    unit_pos = rl.Vector2(rect.x + rect.width / 2 - unit_text_size.x / 2, 290 - unit_text_size.y / 2)
    rl.draw_text_ex(self._font_medium, unit_text, unit_pos, FONT_SIZES.speed_unit, 0, COLORS.WHITE_TRANSLUCENT)
