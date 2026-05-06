import math
import time
from dataclasses import dataclass

import pyray as rl
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.selfdrive.ui.custom import SPEED_CAMERA_DEBUG_PREVIEW_UNTIL_KEY, read_custom_params
from openpilot.selfdrive.ui.onroad.exp_button import ExpButton
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

# Constants
SET_SPEED_NA = 255
KM_TO_MILE = 0.621371
CRUISE_DISABLED_CHAR = '–'
SPEED_CAMERA_DEBUG_PREVIEW_POLL_INTERVAL = 0.5
SPEED_CAMERA_DEBUG_PREVIEW_LIMIT = 50
SPEED_CAMERA_DEBUG_PREVIEW_DISTANCE_M = 350
SPEED_CAMERA_DEBUG_PREVIEW_TYPE = 4
SPEED_CAMERA_DEBUG_PREVIEW_CATEGORY = "SECTION_SPEED"
SPEED_CAMERA_DEBUG_PREVIEW_ROAD_CLASS = "EXPRESSWAY"
SPEED_CAMERA_DEBUG_PREVIEW_ROAD_CLASS_CODE = 1
SPEED_CAMERA_DEBUG_PREVIEW_RELATIVE_ANGLE_DEG = 30.0


@dataclass(frozen=True)
class UIConfig:
  header_height: int = 300
  border_size: int = 30
  button_size: int = 192
  set_speed_width_metric: int = 200
  set_speed_width_imperial: int = 172
  set_speed_height: int = 204
  wheel_icon_size: int = 144


@dataclass(frozen=True)
class FontSizes:
  current_speed: int = 176
  speed_unit: int = 66
  max_speed: int = 40
  set_speed: int = 90


@dataclass(frozen=True)
class Colors:
  WHITE = rl.WHITE
  DISENGAGED = rl.Color(145, 155, 149, 255)
  OVERRIDE = rl.Color(145, 155, 149, 255)  # Added
  ENGAGED = rl.Color(128, 216, 166, 255)
  DISENGAGED_BG = rl.Color(0, 0, 0, 153)
  OVERRIDE_BG = rl.Color(145, 155, 149, 204)
  ENGAGED_BG = rl.Color(128, 216, 166, 204)
  GREY = rl.Color(166, 166, 166, 255)
  DARK_GREY = rl.Color(114, 114, 114, 255)
  BLACK_TRANSLUCENT = rl.Color(0, 0, 0, 166)
  WHITE_TRANSLUCENT = rl.Color(255, 255, 255, 200)
  BORDER_TRANSLUCENT = rl.Color(255, 255, 255, 75)
  HEADER_GRADIENT_START = rl.Color(0, 0, 0, 114)
  HEADER_GRADIENT_END = rl.BLANK
  BRAKE_LIGHT = rl.Color(201, 34, 49, 100)
  BRAKE_LIGHT_GLOW = rl.Color(201, 34, 49, 70)
  BRAKE_SOFT = rl.Color(255, 34, 0, 255)
  BRAKE_HARD = rl.Color(255, 0, 0, 255)
  GAS = rl.Color(255, 255, 0, 255)
  SPEED_CAMERA = rl.Color(255, 198, 77, 255)
  SPEED_SIGN_RED = rl.Color(210, 32, 42, 255)
  SPEED_SIGN_RING_RED = rl.Color(210, 32, 42, 255)
  SPEED_SIGN_RING_BLUE = rl.Color(52, 120, 246, 255)
  SPEED_SIGN_INNER = rl.WHITE
  SPEED_SIGN_TEXT = rl.Color(18, 18, 18, 255)


UI_CONFIG = UIConfig()
FONT_SIZES = FontSizes()
COLORS = Colors()


class HudRenderer(Widget):
  def __init__(self):
    super().__init__()
    """Initialize the HUD renderer."""
    self.is_cruise_set: bool = False
    self.is_cruise_available: bool = True
    self.set_speed: float = SET_SPEED_NA
    self.speed: float = 0.0
    self.speed_color: rl.Color = COLORS.WHITE
    self.brake_lights: bool = False
    self.v_ego_cluster_seen: bool = False
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
    self._params = Params()
    self._camera_preview_until: float = 0.0
    self._camera_preview_last_check: float = 0.0

    self._font_semi_bold: rl.Font = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_bold: rl.Font = gui_app.font(FontWeight.BOLD)
    self._font_medium: rl.Font = gui_app.font(FontWeight.MEDIUM)

    self._exp_button: ExpButton = ExpButton(UI_CONFIG.button_size, UI_CONFIG.wheel_icon_size)

  def _update_state(self) -> None:
    """Update HUD state based on car state and controls state."""
    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      self.is_cruise_set = False
      self.set_speed = SET_SPEED_NA
      self.speed = 0.0
      self.speed_color = COLORS.WHITE
      self.brake_lights = False
      self.camera_alert_active = False
      if self._speed_camera_preview_active():
        self._apply_speed_camera_preview()
      return

    controls_state = sm['controlsState']
    car_state = sm['carState']

    v_cruise_cluster = car_state.vCruiseCluster
    self.set_speed = (
      controls_state.deprecated.vCruise if v_cruise_cluster == 0.0 else v_cruise_cluster
    )
    self.is_cruise_set = 0 < self.set_speed < SET_SPEED_NA
    self.is_cruise_available = self.set_speed != -1

    if self.is_cruise_set and not ui_state.is_metric:
      self.set_speed *= KM_TO_MILE

    v_ego_cluster = car_state.vEgoCluster
    self.v_ego_cluster_seen = self.v_ego_cluster_seen or v_ego_cluster != 0.0
    v_ego = v_ego_cluster if self.v_ego_cluster_seen else car_state.vEgo
    speed_conversion = CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH
    self.speed = max(0.0, v_ego * speed_conversion)
    self.brake_lights = bool(getattr(car_state, "brakeLightsDEPRECATED", False))
    self.speed_color = self._speed_color(car_state)
    self._update_camera_alert(sm)

  def _render(self, rect: rl.Rectangle) -> None:
    """Render HUD elements to the screen."""
    # Draw the header background
    rl.draw_rectangle_gradient_v(
      int(rect.x),
      int(rect.y),
      int(rect.width),
      UI_CONFIG.header_height,
      COLORS.HEADER_GRADIENT_START,
      COLORS.HEADER_GRADIENT_END,
    )

    if self.is_cruise_available:
      self._draw_set_speed(rect)

    self._draw_current_speed(rect)
    self._draw_speed_camera_alert(rect)

    button_x = rect.x + rect.width - UI_CONFIG.border_size - UI_CONFIG.button_size
    button_y = rect.y + UI_CONFIG.border_size
    self._exp_button.render(rl.Rectangle(button_x, button_y, UI_CONFIG.button_size, UI_CONFIG.button_size))

  def user_interacting(self) -> bool:
    return self._exp_button.is_pressed

  def _draw_set_speed(self, rect: rl.Rectangle) -> None:
    """Draw the MAX speed indicator box."""
    set_speed_width = UI_CONFIG.set_speed_width_metric if ui_state.is_metric else UI_CONFIG.set_speed_width_imperial
    x = rect.x + 60 + (UI_CONFIG.set_speed_width_imperial - set_speed_width) // 2
    y = rect.y + 45

    set_speed_rect = rl.Rectangle(x, y, set_speed_width, UI_CONFIG.set_speed_height)
    rl.draw_rectangle_rounded(set_speed_rect, 0.35, 10, COLORS.BLACK_TRANSLUCENT)
    rl.draw_rectangle_rounded_lines_ex(set_speed_rect, 0.35, 10, 6, COLORS.BORDER_TRANSLUCENT)

    max_color = COLORS.GREY
    set_speed_color = COLORS.DARK_GREY
    if self.is_cruise_set:
      set_speed_color = COLORS.WHITE
      if ui_state.status == UIStatus.ENGAGED:
        max_color = COLORS.ENGAGED
      elif ui_state.status == UIStatus.DISENGAGED:
        max_color = COLORS.DISENGAGED
      elif ui_state.status == UIStatus.OVERRIDE:
        max_color = COLORS.OVERRIDE

    max_text = tr("MAX")
    max_text_width = measure_text_cached(self._font_semi_bold, max_text, FONT_SIZES.max_speed).x
    rl.draw_text_ex(
      self._font_semi_bold,
      max_text,
      rl.Vector2(x + (set_speed_width - max_text_width) / 2, y + 27),
      FONT_SIZES.max_speed,
      0,
      max_color,
    )

    set_speed_text = CRUISE_DISABLED_CHAR if not self.is_cruise_set else str(round(self.set_speed))
    speed_text_width = measure_text_cached(self._font_bold, set_speed_text, FONT_SIZES.set_speed).x
    rl.draw_text_ex(
      self._font_bold,
      set_speed_text,
      rl.Vector2(x + (set_speed_width - speed_text_width) / 2, y + 77),
      FONT_SIZES.set_speed,
      0,
      set_speed_color,
    )

  def _update_camera_alert(self, sm) -> None:
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
    if not self.camera_alert_active and self._speed_camera_preview_active():
      self._apply_speed_camera_preview()

  def _speed_camera_preview_active(self) -> bool:
    now = time.time()
    if now - self._camera_preview_last_check >= SPEED_CAMERA_DEBUG_PREVIEW_POLL_INTERVAL:
      self._camera_preview_last_check = now
      try:
        values = read_custom_params(self._params)
        self._camera_preview_until = float(values.get(SPEED_CAMERA_DEBUG_PREVIEW_UNTIL_KEY, 0.0))
      except (TypeError, ValueError):
        self._camera_preview_until = 0.0
    return now < self._camera_preview_until

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

  def _draw_speed_camera_alert(self, rect: rl.Rectangle) -> None:
    if not self.camera_alert_active:
      return

    width = UI_CONFIG.set_speed_width_metric if ui_state.is_metric else UI_CONFIG.set_speed_width_imperial
    x = rect.x + 60 + (UI_CONFIG.set_speed_width_imperial - width) // 2
    y = rect.y + 45 + UI_CONFIG.set_speed_height + 16

    limit_text = str(self.camera_limit_speed) if self.camera_limit_speed > 0 else "--"
    distance_text = self._format_distance(self.camera_distance_m)
    info_label = self._camera_info_label()

    label_text, label_font_size, label_size = self._fit_text(info_label, width, 22, 18)
    rl.draw_text_ex(
      self._font_medium,
      label_text,
      rl.Vector2(x + (width - label_size.x) / 2, y + 2),
      label_font_size,
      0,
      COLORS.SPEED_CAMERA,
    )

    sign_radius = self._speed_sign_radius()
    sign_center_x = x + width / 2
    sign_center_y = y + 88
    self._draw_speed_limit_sign(sign_center_x, sign_center_y, sign_radius, limit_text)

    distance_size = measure_text_cached(self._font_medium, distance_text, 30)
    rl.draw_text_ex(
      self._font_medium,
      distance_text,
      rl.Vector2(x + (width - distance_size.x) / 2, y + 160),
      30,
      0,
      COLORS.WHITE_TRANSLUCENT,
    )

  def _draw_speed_limit_sign(self, center_x: float, center_y: float, radius: int, limit_text: str) -> None:
    is_speed = self._is_speed_camera_category(self.camera_category, self.camera_type)
    inner_gap = 10 if is_speed else 8
    self._draw_camera_direction_pointer(center_x, center_y, radius)
    rl.draw_circle(int(center_x), int(center_y), radius, self._speed_sign_ring_color())
    rl.draw_circle(int(center_x), int(center_y), radius - inner_gap, COLORS.SPEED_SIGN_INNER)

    if is_speed:
      font_size = 58 if len(limit_text) <= 2 else 44
    else:
      font_size = 48 if len(limit_text) <= 2 else 38
    text_size = measure_text_cached(self._font_bold, limit_text, font_size)
    rl.draw_text_ex(
      self._font_bold,
      limit_text,
      rl.Vector2(center_x - text_size.x / 2, center_y - text_size.y / 2),
      font_size,
      0,
      COLORS.SPEED_SIGN_TEXT,
    )

  def _draw_camera_direction_pointer(self, center_x: float, center_y: float, radius: int) -> None:
    angle_rad = math.radians(max(-85.0, min(85.0, self.camera_relative_angle_deg)))
    direction_x = math.sin(angle_rad)
    direction_y = -math.cos(angle_rad)
    perpendicular_x = math.cos(angle_rad)
    perpendicular_y = math.sin(angle_rad)
    pointer_length = max(14.0, radius * 0.34)
    pointer_half_width = max(9.0, radius * 0.17)
    base_radius = radius - 2.0
    tip_radius = radius + pointer_length

    tip = rl.Vector2(center_x + direction_x * tip_radius, center_y + direction_y * tip_radius)
    base_center_x = center_x + direction_x * base_radius
    base_center_y = center_y + direction_y * base_radius
    left = rl.Vector2(base_center_x + perpendicular_x * pointer_half_width, base_center_y + perpendicular_y * pointer_half_width)
    right = rl.Vector2(base_center_x - perpendicular_x * pointer_half_width, base_center_y - perpendicular_y * pointer_half_width)
    rl.draw_triangle(tip, left, right, self._camera_pointer_color())

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

    if cam_type == 1:
      return tr("Speed")
    if cam_type == 2:
      return tr("Signal")
    if cam_type == 3:
      return tr("Speed+Signal")
    if cam_type == 4:
      return tr("Section")

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
      return 64
    return 48

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
    rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, self.speed_color)

    unit_text = tr("km/h") if ui_state.is_metric else tr("mph")
    unit_text_size = measure_text_cached(self._font_medium, unit_text, FONT_SIZES.speed_unit)
    unit_pos = rl.Vector2(rect.x + rect.width / 2 - unit_text_size.x / 2, 290 - unit_text_size.y / 2)
    rl.draw_text_ex(self._font_medium, unit_text, unit_pos, FONT_SIZES.speed_unit, 0, COLORS.WHITE_TRANSLUCENT)
    self._draw_brake_light_indicator(rect, unit_text_size)

  def _draw_brake_light_indicator(self, rect: rl.Rectangle, unit_text_size: rl.Vector2) -> None:
    if not self.brake_lights:
      return

    center_x = rect.x + rect.width / 2
    center_y = 290
    lamp_width = 46
    lamp_height = 20
    lamp_gap = 28
    glow_padding = 8
    left_x = center_x - unit_text_size.x / 2 - lamp_gap - lamp_width
    right_x = center_x + unit_text_size.x / 2 + lamp_gap
    y = center_y - lamp_height / 2 + 1

    for x in (left_x, right_x):
      glow_rect = rl.Rectangle(
        x - glow_padding, y - glow_padding, lamp_width + glow_padding * 2, lamp_height + glow_padding * 2
      )
      lamp_rect = rl.Rectangle(x, y, lamp_width, lamp_height)
      rl.draw_rectangle_rounded(glow_rect, 0.8, 10, COLORS.BRAKE_LIGHT_GLOW)
      rl.draw_rectangle_rounded(lamp_rect, 0.75, 10, COLORS.BRAKE_HARD)

  def _speed_color(self, car_state) -> rl.Color:
    car_state_custom = getattr(car_state, "carSCustom", None)
    brake_pos = max(0.0, float(getattr(car_state_custom, "breakPos", 0.0)))
    brake_lights = bool(getattr(car_state, "brakeLightsDEPRECATED", False))
    brake_pressed = bool(getattr(car_state, "brakePressed", False))
    gas_value = max(0.0, float(getattr(car_state, "gasDEPRECATED", 0.0))) * 100.0
    if bool(getattr(car_state, "gasPressed", False)):
      gas_value = max(gas_value, 20.0)

    if brake_pos > 0:
      if brake_lights:
        return self._interp_color(
          brake_pos, 0.0, 60.0, 130.0, COLORS.BRAKE_LIGHT, COLORS.BRAKE_SOFT, COLORS.BRAKE_HARD
        )
      return self._interp_color(
        brake_pos, 0.0, 60.0, 130.0, COLORS.WHITE, rl.Color(200, 100, 50, 255), COLORS.BRAKE_HARD
      )
    if brake_lights:
      return COLORS.BRAKE_LIGHT
    if brake_pressed:
      return COLORS.BRAKE_HARD
    if gas_value > 0:
      return self._interp_color(gas_value, 0.0, 60.0, 60.0, COLORS.WHITE, COLORS.GAS, COLORS.GAS)
    return COLORS.WHITE

  def _interp_color(
    self, value: float, x0: float, x1: float, x2: float, c0: rl.Color, c1: rl.Color, c2: rl.Color
  ) -> rl.Color:
    if value <= x0:
      return c0
    if value >= x2:
      return c2
    if value <= x1:
      return self._mix_color(c0, c1, (value - x0) / max(1e-3, x1 - x0))
    return self._mix_color(c1, c2, (value - x1) / max(1e-3, x2 - x1))

  def _mix_color(self, c0: rl.Color, c1: rl.Color, ratio: float) -> rl.Color:
    ratio = min(1.0, max(0.0, ratio))
    r0, g0, b0, a0 = self._rgba(c0)
    r1, g1, b1, a1 = self._rgba(c1)
    return rl.Color(
      round(r0 + (r1 - r0) * ratio),
      round(g0 + (g1 - g0) * ratio),
      round(b0 + (b1 - b0) * ratio),
      round(a0 + (a1 - a0) * ratio),
    )

  def _rgba(self, color: rl.Color) -> tuple[int, int, int, int]:
    if hasattr(color, "r"):
      return int(color.r), int(color.g), int(color.b), int(color.a)
    return int(color[0]), int(color[1]), int(color[2]), int(color[3])
