import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pyray as rl
from cereal import car, messaging

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.selfdrive.navd.speed_camera import (
  DEFAULT_CSV_PATH as SPEED_CAMERA_CSV_PATH,
  DEFAULT_DB_PATH as SPEED_CAMERA_DB_PATH,
  DEFAULT_REGION_DIR as SPEED_CAMERA_REGION_DIR,
  OsmRoadEnrichmentStats,
  database_category_counts,
  database_data_date,
  database_osm_road_enrichment_stats,
  database_region_stats,
)
from openpilot.selfdrive.navd.osm_roads import (
  DEFAULT_OSM_ROADS_DB_PATH,
  database_built_at as osm_roads_built_at,
  database_segment_count as osm_roads_segment_count,
)
from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR, DEFAULT_NAVD_TMP_DIR
from openpilot.selfdrive.ui.custom import (
  read_custom_param_map,
  read_custom_params,
  start_speed_camera_debug_preview,
  write_custom_params,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import PC
from openpilot.system.ui.lib.application import FontWeight, MousePos, gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.list_view import ItemAction, ListItem, button_item, text_item, toggle_item
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller


# #custom start: Python port of qt/custom settings panel
MODEL_OPTIONS = [
  "11.POP_Model",
  "10.CD210_Model",
  "9.WMI_Model",
  "8.SC_Driving",
  "7.MacroStiff_Model",
  "6.Dark_Souls_2",
  "5.North_Nevada",
  "4.The_Cool_Peoples",
  "3.Firehose",
  "2.Steam_Powered",
  "1.Stock_Model",
]
DEFAULT_MODEL_NAME = "1.Stock_Model"
DEFAULT_MODEL_NAMES = {DEFAULT_MODEL_NAME, "1.default", "7.Current_Model", "7.Current_0.11_6a7d09ad"}

EXTERNAL_NAVI_OPTIONS = ["0", "1", "2"]
OSM_ROAD_OVERLAY_MODE_OPTIONS = [
  (0, tr_noop("Off")),
  (1, tr_noop("Mini Map")),
]
CAR_TRACKING_DESCRIPTION = tr_noop(
  "Shows a separate CAR TRACKING panel on the onroad screen.<br>"
  "EGO / LEFT / RIGHT: Fuses liveTracks radar points with modelV2 leadsV3 camera candidates, then selects the nearest lead in each lane.<br>"
  "If multiple candidates are in the same lane, one candidate is selected by source priority: FUSED, CAMERA, then RADAR. Ties use the nearest distance.<br>"
  "EGO uses modelV2 path/laneLines at the lead distance when available, so curved roads follow the model lane shape. If lane lines are weak, it falls back to the path center and radarState yRel side offset.<br>"
  "The lead triangle uses the same classification: yellow for EGO, blue for LEFT, green for RIGHT, and red for close or fast-closing leads.<br>"
  "Source shows RADAR#, CAMERA, or FUSED when radar and camera candidates match. If both are unavailable, it falls back to radarState leadOne/leadTwo.<br>"
  "SCC: Shows stock SCC lead distance and current gap from carState.carSCustom when supported vehicle CAN data is available.<br>"
  "If no lead data is available, the panel still appears and displays none so you can confirm the feature is enabled.<br>"
  "This is a visual/debug overlay only; it does not change longitudinal control, radar matching, or cruise behavior."
)
CRUISE_MODE_DESCRIPTION = tr_noop(
  "0: Disabled. Custom cruise button control is not used.<br>"
  "1-15: Enabled. Current code treats all non-zero values the same; higher numbers are reserved for future modes.<br>"
  "When enabled on supported Hyundai stock SCC paths, openpilot simulates RES/SET button presses to move the vehicle cruise set speed toward the planned speed. "
  "It is inactive when openpilot longitudinal control is enabled, when ACC is off, while braking, or while another cruise button is pressed. "
  "If Cruise gap matches the vehicle gap, the target follows longitudinalPlan speed; otherwise it holds the current custom set speed."
)
STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
COMPILE_STATUS_KEY = "CustomModelCompileStatus"
COMPILE_NAME_KEY = "CustomModelCompileName"
COMPILE_STARTED_AT_KEY = "CustomModelCompileStartedAt"
COMPILE_FINISHED_AT_KEY = "CustomModelCompileFinishedAt"
COMPILE_ERROR_KEY = "CustomModelCompileError"
COMPILE_PROGRESS_KEY = "CustomModelCompileProgress"
CUSTOM_TMP_ROOT = Path("/tmp") if PC else Path("/data/tmp")
NAVD_TMP_ROOT = DEFAULT_NAVD_TMP_DIR
COMPILE_LOG_PATH = str(CUSTOM_TMP_ROOT / "openpilot_custom_model_compile.log")
COMPILE_STATUS_CHECK_INTERVAL = 5.0
COMPILE_LOG_CACHE_INTERVAL = 2.0
COMPILE_PROCESS_GRACE_SECONDS = 60
COMPILE_STALE_SECONDS = 2 * 60 * 60
GIT_STATUS_KEY = "CustomGitUpdateStatus"
GIT_ERROR_KEY = "CustomGitUpdateError"
GIT_LOG_PATH = str(CUSTOM_TMP_ROOT / "openpilot_git_update.log")
SPEED_CAMERA_STATUS_KEY = "SpeedCameraUpdateStatus"
SPEED_CAMERA_ERROR_KEY = "SpeedCameraUpdateError"
SPEED_CAMERA_COUNT_KEY = "SpeedCameraUpdateCount"
SPEED_CAMERA_PROGRESS_KEY = "SpeedCameraUpdateProgress"
SPEED_CAMERA_UPDATED_AT_KEY = "SpeedCameraUpdatedAt"
SPEED_CAMERA_DATA_DATE_KEY = "SpeedCameraDataDate"
SPEED_CAMERA_DEBUG_PREVIEW_DURATION_SECONDS = 30
SPEED_CAMERA_LOG_PATH = str(NAVD_TMP_ROOT / "openpilot_speed_camera_update.log")
SPEED_CAMERA_LOCK_PATH = NAVD_TMP_ROOT / "openpilot_speed_camera_update.lock"
SPEED_CAMERA_LOCK_STALE_SECONDS = 30 * 60
OSM_ROADS_STATUS_KEY = "OsmRoadsUpdateStatus"
OSM_ROADS_ERROR_KEY = "OsmRoadsUpdateError"
OSM_ROADS_COUNT_KEY = "OsmRoadsSegmentCount"
OSM_ROADS_PROGRESS_KEY = "OsmRoadsUpdateProgress"
OSM_ROADS_UPDATED_AT_KEY = "OsmRoadsUpdatedAt"
OSM_ROADS_LOG_PATH = str(NAVD_TMP_ROOT / "openpilot_osm_roads_update.log")
OSM_ROADS_LOCK_PATH = NAVD_TMP_ROOT / "openpilot_osm_roads_update.lock"
OSM_ROADS_LOCK_STALE_SECONDS = 2 * 60 * 60
OSM_ROADS_PBF_PATH = DEFAULT_NAVD_SOURCE_DIR / "south-korea-latest.osm.pbf"
REPO_ROOT = Path(BASEDIR)
MODELD_DIR = REPO_ROOT / "selfdrive/modeld"
TAB_HEIGHT = 110
TAB_GAP = 10
TAB_FONT_SIZE = 40
TAB_FONT_MIN_SIZE = 28
TAB_RADIUS = 0.35
TAB_SELECTED = rl.Color(245, 245, 245, 255)
TAB_NORMAL = rl.BLACK
TAB_PRESSED = rl.Color(35, 35, 35, 255)
TAB_BORDER = rl.Color(196, 196, 195, 255)
TAB_TEXT = rl.WHITE
TAB_TEXT_SELECTED = rl.BLACK
STEPPER_BUTTON_WIDTH = 120
STEPPER_VALUE_WIDTH = 170
STEPPER_HEIGHT = 100
STEPPER_GAP = 20
STEPPER_FONT_SIZE = 48
STEPPER_BUTTON_FONT_SIZE = 52
STEPPER_BUTTON_COLOR = rl.Color(57, 57, 57, 255)
STEPPER_BUTTON_PRESSED = rl.Color(74, 74, 74, 255)
STEPPER_VALUE_COLOR = rl.Color(170, 170, 170, 255)
SECTION_HEIGHT = 92
SECTION_FONT_SIZE = 42
SECTION_BG = rl.Color(58, 58, 58, 255)
COMPILE_LOG_HEIGHT = 500
COMPILE_LOG_TITLE_FONT_SIZE = 42
COMPILE_LOG_FONT_SIZE = 28
COMPILE_LOG_LINE_HEIGHT = 34
COMPILE_LOG_PADDING = 26
COMPILE_LOG_BG = rl.Color(23, 23, 23, 255)
COMPILE_LOG_BORDER = rl.Color(96, 96, 96, 255)
COMPILE_LOG_TEXT = rl.Color(190, 190, 190, 255)
SPEED_CAMERA_REGION_PANEL_HEIGHT = 360
SPEED_CAMERA_REGION_FONT_SIZE = 22
SPEED_CAMERA_REGION_LINE_HEIGHT = 32
SPEED_CAMERA_REGION_PADDING = 20
SPEED_CAMERA_DETAIL_TAB_HEIGHT = 42
SPEED_CAMERA_DETAIL_TAB_WIDTH = 120
SPEED_CAMERA_DETAIL_TAB_GAP = 10
COMPACT_INFO_ROW_HEIGHT = 82
COMPACT_INFO_PADDING_X = 34
COMPACT_INFO_PADDING_Y = 8
COMPACT_INFO_LABEL_FONT_SIZE = 38
COMPACT_INFO_VALUE_FONT_SIZE = 38
COMPACT_INFO_VALUE_MIN_FONT_SIZE = 28
COMPACT_INFO_BG = rl.Color(35, 35, 35, 255)
COMPACT_INFO_LABEL_COLOR = rl.WHITE
COMPACT_INFO_VALUE_COLOR = rl.Color(170, 170, 170, 255)
COMPACT_PROGRESS_BAR_BG = rl.Color(72, 72, 72, 255)
COMPACT_PROGRESS_BAR_FILL = rl.Color(52, 168, 83, 255)
COMPACT_PROGRESS_BAR_COMPLETE_FILL = rl.Color(88, 214, 141, 255)
COMPACT_PROGRESS_BAR_HEIGHT = 18
COMPACT_PROGRESS_BAR_WIDTH = 300
COMPACT_PROGRESS_PERCENT_WIDTH = 86
COMPACT_PROGRESS_GAP = 22
COMPACT_STATUS_FONT_SIZE = 30
COMPACT_STATUS_MIN_FONT_SIZE = 24
COMPACT_STATUS_LINE_HEIGHT = 34


def run_logged(command: list[str], cwd: Path, log_path: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
  Path(log_path).parent.mkdir(parents=True, exist_ok=True)
  with open(log_path, "a", encoding="utf-8") as log_file:
    log_file.write(f"\n$ {' '.join(command)}\n")
    log_file.flush()
    return subprocess.run(command, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT, text=True, check=False, env=env)


def clear_log(log_path: str) -> None:
  path = Path(log_path)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text("", encoding="utf-8")


def process_alive(pid: int) -> bool:
  if pid <= 0:
    return False
  if pid == os.getpid():
    return True

  if os.name == "nt":
    import ctypes

    kernel32 = ctypes.windll.kernel32
    synchronize = 0x00100000
    wait_timeout = 0x00000102
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
      return False
    try:
      return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
      kernel32.CloseHandle(handle)

  try:
    os.kill(pid, 0)
    return True
  except OSError:
    return False


def valid_branch_name(branch: str) -> bool:
  if not branch or branch.startswith("-"):
    return False
  return subprocess.run(["git", "check-ref-format", "--branch", branch],
                        cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def origin_branch_exists(branch: str) -> bool:
  return subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
                        cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


class StepperAction(ItemAction):
  def __init__(self, value_text: Callable[[], str], minus_callback: Callable[[], None], plus_callback: Callable[[], None]):
    super().__init__(width=STEPPER_BUTTON_WIDTH * 2 + STEPPER_VALUE_WIDTH + STEPPER_GAP * 2)
    self._value_text = value_text
    self._minus_callback = minus_callback
    self._plus_callback = plus_callback
    self._font = gui_app.font(FontWeight.NORMAL)
    self._button_font = gui_app.font(FontWeight.MEDIUM)
    self._minus_rect = rl.Rectangle(0, 0, 0, 0)
    self._plus_rect = rl.Rectangle(0, 0, 0, 0)

  def _render(self, rect: rl.Rectangle) -> bool:
    y = rect.y + (rect.height - STEPPER_HEIGHT) / 2
    self._minus_rect = rl.Rectangle(rect.x, y, STEPPER_BUTTON_WIDTH, STEPPER_HEIGHT)
    value_rect = rl.Rectangle(
      self._minus_rect.x + self._minus_rect.width + STEPPER_GAP,
      y,
      STEPPER_VALUE_WIDTH,
      STEPPER_HEIGHT,
    )
    self._plus_rect = rl.Rectangle(value_rect.x + value_rect.width + STEPPER_GAP, y, STEPPER_BUTTON_WIDTH, STEPPER_HEIGHT)

    self._draw_button(self._minus_rect, "-")
    self._draw_value(value_rect)
    self._draw_button(self._plus_rect, "+")
    return False

  def _draw_button(self, rect: rl.Rectangle, label: str) -> None:
    pressed = self.is_pressed and rl.check_collision_point_rec(rl.get_mouse_position(), rect)
    color = STEPPER_BUTTON_PRESSED if pressed else STEPPER_BUTTON_COLOR
    if not self.enabled:
      color = rl.Color(color.r, color.g, color.b, 100)
    rl.draw_rectangle_rounded(rect, 1.0, 20, color)
    text_size = measure_text_cached(self._button_font, label, STEPPER_BUTTON_FONT_SIZE)
    text_pos = rl.Vector2(rect.x + (rect.width - text_size.x) / 2, rect.y + (rect.height - text_size.y) / 2)
    text_color = TAB_TEXT if self.enabled else rl.Color(TAB_TEXT.r, TAB_TEXT.g, TAB_TEXT.b, 100)
    rl.draw_text_ex(self._button_font, label, text_pos, STEPPER_BUTTON_FONT_SIZE, 0, text_color)

  def _draw_value(self, rect: rl.Rectangle) -> None:
    label = self._value_text()
    text_size = measure_text_cached(self._font, label, STEPPER_FONT_SIZE)
    text_pos = rl.Vector2(rect.x + (rect.width - text_size.x) / 2, rect.y + (rect.height - text_size.y) / 2)
    text_color = STEPPER_VALUE_COLOR if self.enabled else rl.Color(STEPPER_VALUE_COLOR.r, STEPPER_VALUE_COLOR.g, STEPPER_VALUE_COLOR.b, 100)
    rl.draw_text_ex(self._font, label, text_pos, STEPPER_FONT_SIZE, 0, text_color)

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    if not self.enabled:
      return
    if rl.check_collision_point_rec(mouse_pos, self._minus_rect):
      self._minus_callback()
    elif rl.check_collision_point_rec(mouse_pos, self._plus_rect):
      self._plus_callback()


class SectionHeader(Widget):
  def __init__(self, title: str):
    super().__init__()
    self._title = title
    self._font = gui_app.font(FontWeight.MEDIUM)
    self.set_rect(rl.Rectangle(0, 0, 0, SECTION_HEIGHT))

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.15, 12, SECTION_BG)
    label = tr(self._title)
    text_size = measure_text_cached(self._font, label, SECTION_FONT_SIZE)
    text_pos = rl.Vector2(rect.x + 32, rect.y + (rect.height - text_size.y) / 2)
    rl.draw_text_ex(self._font, label, text_pos, SECTION_FONT_SIZE, 0, TAB_TEXT)


class CompactInfoGroup(Widget):
  def __init__(self, rows: list[tuple[str, Callable[[], str]]]):
    super().__init__()
    self._rows = rows
    self._font_regular = gui_app.font(FontWeight.NORMAL)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    height = COMPACT_INFO_PADDING_Y * 2 + COMPACT_INFO_ROW_HEIGHT * len(self._rows)
    self.set_rect(rl.Rectangle(0, 0, 0, height))

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, rect: rl.Rectangle):
    panel_rect = rl.Rectangle(
      rect.x + COMPACT_INFO_PADDING_X / 2,
      rect.y + COMPACT_INFO_PADDING_Y / 2,
      rect.width - COMPACT_INFO_PADDING_X,
      rect.height - COMPACT_INFO_PADDING_Y,
    )
    rl.draw_rectangle_rounded(panel_rect, 0.05, 8, COMPACT_INFO_BG)

    label_x = panel_rect.x + COMPACT_INFO_PADDING_X
    value_right = panel_rect.x + panel_rect.width - COMPACT_INFO_PADDING_X
    value_x = panel_rect.x + panel_rect.width * 0.38
    value_width = value_right - value_x
    row_y = panel_rect.y + COMPACT_INFO_PADDING_Y / 2

    for label_source, value_callback in self._rows:
      label = tr(label_source)
      value = value_callback()
      self._draw_label(label, label_x, row_y, value_x - label_x - COMPACT_INFO_PADDING_X)
      self._draw_value(value, value_x, row_y, value_width)
      row_y += COMPACT_INFO_ROW_HEIGHT

  def _draw_label(self, label: str, x: float, y: float, max_width: float) -> None:
    text, font_size = self._fit_text(label, self._font_medium, COMPACT_INFO_LABEL_FONT_SIZE,
                                     COMPACT_INFO_LABEL_FONT_SIZE, max_width)
    text_size = measure_text_cached(self._font_medium, text, font_size)
    text_pos = rl.Vector2(x, y + (COMPACT_INFO_ROW_HEIGHT - text_size.y) / 2)
    rl.draw_text_ex(self._font_medium, text, text_pos, font_size, 0, COMPACT_INFO_LABEL_COLOR)

  def _draw_value(self, value: str, x: float, y: float, max_width: float) -> None:
    text, font_size = self._fit_text(value, self._font_regular, COMPACT_INFO_VALUE_FONT_SIZE,
                                     COMPACT_INFO_VALUE_MIN_FONT_SIZE, max_width)
    text_size = measure_text_cached(self._font_regular, text, font_size)
    text_pos = rl.Vector2(x + max(0, max_width - text_size.x), y + (COMPACT_INFO_ROW_HEIGHT - text_size.y) / 2)
    rl.draw_text_ex(self._font_regular, text, text_pos, font_size, 0, COMPACT_INFO_VALUE_COLOR)

  def _fit_text(self, text: str, font: rl.Font, font_size: int, min_font_size: int, max_width: float) -> tuple[str, int]:
    while font_size > min_font_size and measure_text_cached(font, text, font_size).x > max_width:
      font_size -= 2
    if measure_text_cached(font, text, font_size).x <= max_width:
      return text, font_size

    ellipsis = "..."
    fitted = text
    while fitted and measure_text_cached(font, fitted + ellipsis, font_size).x > max_width:
      fitted = fitted[:-1]
    return ((fitted.rstrip() + ellipsis) if fitted else ellipsis), font_size


class CompactStatusProgressGroup(CompactInfoGroup):
  def __init__(self, status_callback: Callable[[], str], progress_callback: Callable[[], str]):
    super().__init__([(tr_noop("Status"), status_callback)])
    self._progress_callback = progress_callback

  def _render(self, rect: rl.Rectangle):
    panel_rect = rl.Rectangle(
      rect.x + COMPACT_INFO_PADDING_X / 2,
      rect.y + COMPACT_INFO_PADDING_Y / 2,
      rect.width - COMPACT_INFO_PADDING_X,
      rect.height - COMPACT_INFO_PADDING_Y,
    )
    rl.draw_rectangle_rounded(panel_rect, 0.05, 8, COMPACT_INFO_BG)
    self._draw_status_progress_row(panel_rect, panel_rect.y + COMPACT_INFO_PADDING_Y / 2)

  def _draw_status_progress_row(self, panel_rect: rl.Rectangle, row_y: float) -> None:
    label_x = panel_rect.x + COMPACT_INFO_PADDING_X
    value_right = panel_rect.x + panel_rect.width - COMPACT_INFO_PADDING_X
    value_x = panel_rect.x + panel_rect.width * 0.15
    self._draw_label(tr("Status"), label_x, row_y, value_x - label_x - COMPACT_INFO_PADDING_X)

    progress = self._progress_percent()
    if progress is None:
      self._draw_value(self._rows[0][1](), value_x, row_y, value_right - value_x)
      return

    bar_width = min(COMPACT_PROGRESS_BAR_WIDTH, max(160, (value_right - value_x) * 0.34))
    status_width = value_right - value_x - COMPACT_PROGRESS_PERCENT_WIDTH - bar_width - COMPACT_PROGRESS_GAP * 2
    self._draw_inline_status(self._rows[0][1](), value_x, row_y, max(80, status_width))

    percent_x = value_x + max(80, status_width) + COMPACT_PROGRESS_GAP
    percent_text = f"{progress}%"
    self._draw_inline_percent(percent_text, percent_x, row_y, COMPACT_PROGRESS_PERCENT_WIDTH)

    bar_x = percent_x + COMPACT_PROGRESS_PERCENT_WIDTH + COMPACT_PROGRESS_GAP
    self._draw_progress_bar(rl.Rectangle(bar_x, row_y, bar_width, COMPACT_INFO_ROW_HEIGHT), progress)

  def _progress_percent(self) -> int | None:
    text = self._progress_callback().strip().removesuffix("%")
    try:
      return max(0, min(100, int(text)))
    except ValueError:
      return None

  def _draw_inline_status(self, status: str, x: float, y: float, max_width: float) -> None:
    lines, font_size = self._wrap_status(status, max_width)
    line_height = COMPACT_STATUS_LINE_HEIGHT
    start_y = y + (COMPACT_INFO_ROW_HEIGHT - line_height * len(lines)) / 2
    for i, line in enumerate(lines):
      rl.draw_text_ex(self._font_regular, line, rl.Vector2(x, start_y + i * line_height),
                      font_size, 0, COMPACT_INFO_VALUE_COLOR)

  def _wrap_status(self, status: str, max_width: float) -> tuple[list[str], int]:
    font_size = COMPACT_STATUS_FONT_SIZE
    while font_size > COMPACT_STATUS_MIN_FONT_SIZE and not self._status_fits(status, font_size, max_width):
      font_size -= 2

    if measure_text_cached(self._font_regular, status, font_size).x <= max_width:
      return [status], font_size

    parts = status.split(" / ")
    if len(parts) > 1:
      lines: list[str] = []
      current = ""
      for part in parts:
        candidate = part if not current else f"{current} / {part}"
        if len(lines) < 1 and measure_text_cached(self._font_regular, candidate, font_size).x <= max_width:
          current = candidate
          continue
        if current:
          lines.append(current)
        current = part
      if current:
        lines.append(current)
      if len(lines) <= 2:
        return [self._elide_status_line(line, font_size, max_width) for line in lines], font_size
      return [lines[0], self._elide_status_line(" / ".join(lines[1:]), font_size, max_width)], font_size

    first = self._fit_status_prefix(status, font_size, max_width)
    second = status[len(first):].strip()
    return [first, self._elide_status_line(second, font_size, max_width)] if second else [first], font_size

  def _status_fits(self, status: str, font_size: int, max_width: float) -> bool:
    if measure_text_cached(self._font_regular, status, font_size).x <= max_width:
      return True
    parts = status.split(" / ")
    if len(parts) > 1:
      lines: list[str] = []
      current = ""
      for part in parts:
        candidate = part if not current else f"{current} / {part}"
        if len(lines) < 1 and measure_text_cached(self._font_regular, candidate, font_size).x <= max_width:
          current = candidate
        else:
          if current:
            lines.append(current)
          current = part
      if current:
        lines.append(current)
      return len(lines) <= 2 and all(measure_text_cached(self._font_regular, line, font_size).x <= max_width for line in lines)
    return True

  def _fit_status_prefix(self, text: str, font_size: int, max_width: float) -> str:
    left, right = 1, len(text)
    while left < right:
      mid = (left + right + 1) // 2
      if measure_text_cached(self._font_regular, text[:mid], font_size).x <= max_width:
        left = mid
      else:
        right = mid - 1
    return text[:left].rstrip()

  def _elide_status_line(self, text: str, font_size: int, max_width: float) -> str:
    if measure_text_cached(self._font_regular, text, font_size).x <= max_width:
      return text
    ellipsis = "..."
    fitted = text
    while fitted and measure_text_cached(self._font_regular, fitted + ellipsis, font_size).x > max_width:
      fitted = fitted[:-1]
    return (fitted.rstrip() + ellipsis) if fitted else ellipsis

  def _draw_inline_percent(self, percent: str, x: float, y: float, max_width: float) -> None:
    text_size = measure_text_cached(self._font_regular, percent, COMPACT_INFO_VALUE_FONT_SIZE)
    text_pos = rl.Vector2(x + max(0, max_width - text_size.x), y + (COMPACT_INFO_ROW_HEIGHT - text_size.y) / 2)
    rl.draw_text_ex(self._font_regular, percent, text_pos, COMPACT_INFO_VALUE_FONT_SIZE, 0, COMPACT_INFO_VALUE_COLOR)

  def _draw_progress_bar(self, rect: rl.Rectangle, progress: int) -> None:
    y = rect.y + (rect.height - COMPACT_PROGRESS_BAR_HEIGHT) / 2
    bg_rect = rl.Rectangle(rect.x, y, rect.width, COMPACT_PROGRESS_BAR_HEIGHT)
    fill_rect = rl.Rectangle(rect.x, y, rect.width * progress / 100.0, COMPACT_PROGRESS_BAR_HEIGHT)
    rl.draw_rectangle_rounded(bg_rect, 1.0, 16, COMPACT_PROGRESS_BAR_BG)
    if fill_rect.width > 0:
      fill_color = COMPACT_PROGRESS_BAR_COMPLETE_FILL if progress >= 100 else COMPACT_PROGRESS_BAR_FILL
      rl.draw_rectangle_rounded(fill_rect, 1.0, 16, fill_color)


class CompactStatusProgressInfoGroup(CompactStatusProgressGroup):
  def __init__(self, status_callback: Callable[[], str], progress_callback: Callable[[], str],
               rows: list[tuple[str, Callable[[], str]]], status_details: list[Callable[[], str]] | None = None,
               progress_detail_callback: Callable[[], str] | None = None):
    super().__init__(status_callback, progress_callback)
    self._extra_rows = rows
    self._status_details = status_details or []
    self._progress_detail_callback = progress_detail_callback
    self._status_row_height = max(
      COMPACT_INFO_ROW_HEIGHT,
      COMPACT_STATUS_LINE_HEIGHT * (1 + len(self._status_details)) + COMPACT_INFO_PADDING_Y,
    )
    height = COMPACT_INFO_PADDING_Y * 2 + self._status_row_height + COMPACT_INFO_ROW_HEIGHT * len(self._extra_rows)
    self.set_rect(rl.Rectangle(0, 0, 0, height))

  def _render(self, rect: rl.Rectangle):
    panel_rect = rl.Rectangle(
      rect.x + COMPACT_INFO_PADDING_X / 2,
      rect.y + COMPACT_INFO_PADDING_Y / 2,
      rect.width - COMPACT_INFO_PADDING_X,
      rect.height - COMPACT_INFO_PADDING_Y,
    )
    rl.draw_rectangle_rounded(panel_rect, 0.05, 8, COMPACT_INFO_BG)

    row_y = panel_rect.y + COMPACT_INFO_PADDING_Y / 2
    self._draw_status_progress_info_row(panel_rect, row_y)
    row_y += self._status_row_height

    label_x = panel_rect.x + COMPACT_INFO_PADDING_X
    value_x = panel_rect.x + panel_rect.width * 0.38
    value_right = panel_rect.x + panel_rect.width - COMPACT_INFO_PADDING_X
    for label_source, value_callback in self._extra_rows:
      self._draw_label(tr(label_source), label_x, row_y, value_x - label_x - COMPACT_INFO_PADDING_X)
      self._draw_value(value_callback(), value_x, row_y, value_right - value_x)
      row_y += COMPACT_INFO_ROW_HEIGHT

  def _draw_status_progress_info_row(self, panel_rect: rl.Rectangle, row_y: float) -> None:
    label_x = panel_rect.x + COMPACT_INFO_PADDING_X
    value_right = panel_rect.x + panel_rect.width - COMPACT_INFO_PADDING_X
    value_x = panel_rect.x + panel_rect.width * 0.15
    self._draw_label(tr("Status"), label_x, row_y, value_x - label_x - COMPACT_INFO_PADDING_X)

    progress = self._progress_percent()
    if progress is None:
      self._draw_status_detail_lines([self._rows[0][1](), *[detail() for detail in self._status_details]],
                                     value_x, row_y, value_right - value_x)
      return

    bar_width = min(COMPACT_PROGRESS_BAR_WIDTH, max(160, (value_right - value_x) * 0.34))
    status_width = value_right - value_x - COMPACT_PROGRESS_PERCENT_WIDTH - bar_width - COMPACT_PROGRESS_GAP * 2
    self._draw_status_detail_lines([self._rows[0][1](), *[detail() for detail in self._status_details]],
                                   value_x, row_y, max(80, status_width))

    percent_x = value_x + max(80, status_width) + COMPACT_PROGRESS_GAP
    percent_text = f"{progress}%"
    self._draw_inline_percent(percent_text, percent_x, row_y, COMPACT_PROGRESS_PERCENT_WIDTH)

    bar_x = percent_x + COMPACT_PROGRESS_PERCENT_WIDTH + COMPACT_PROGRESS_GAP
    self._draw_progress_bar(rl.Rectangle(bar_x, row_y, bar_width, COMPACT_INFO_ROW_HEIGHT), progress)
    if self._progress_detail_callback is not None:
      self._draw_progress_detail(self._progress_detail_callback(), bar_x, row_y, bar_width)

  def _draw_status_detail_lines(self, lines: list[str], x: float, y: float, max_width: float) -> None:
    visible_lines = [line for line in lines if line]
    start_y = y + (self._status_row_height - COMPACT_STATUS_LINE_HEIGHT * len(visible_lines)) / 2
    for i, line in enumerate(visible_lines):
      fitted = self._elide_status_line(line, COMPACT_STATUS_FONT_SIZE, max_width)
      rl.draw_text_ex(self._font_regular, fitted, rl.Vector2(x, start_y + i * COMPACT_STATUS_LINE_HEIGHT),
                      COMPACT_STATUS_FONT_SIZE, 0, COMPACT_INFO_VALUE_COLOR)

  def _draw_progress_detail(self, text: str, x: float, y: float, max_width: float) -> None:
    if not text:
      return
    font_size = COMPACT_STATUS_MIN_FONT_SIZE
    fitted = self._elide_status_line(text, font_size, max_width)
    text_size = measure_text_cached(self._font_regular, fitted, font_size)
    text_pos = rl.Vector2(x + max(0, max_width - text_size.x), y + COMPACT_INFO_ROW_HEIGHT - text_size.y - 1)
    rl.draw_text_ex(self._font_regular, fitted, text_pos, font_size, 0, COMPACT_INFO_VALUE_COLOR)


class CompileLogPanel(Widget):
  def __init__(self, title: str, lines_callback: Callable[[], list[str]], empty_text: str = tr_noop("No compile log yet")):
    super().__init__()
    self._title = title
    self._lines_callback = lines_callback
    self._empty_text = empty_text
    self._font_regular = gui_app.font(FontWeight.NORMAL)
    self._font_bold = gui_app.font(FontWeight.MEDIUM)
    self.set_rect(rl.Rectangle(0, 0, 0, COMPILE_LOG_HEIGHT))

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, rect: rl.Rectangle):
    title = tr(self._title)
    title_size = measure_text_cached(self._font_bold, title, COMPILE_LOG_TITLE_FONT_SIZE)
    title_y = rect.y + COMPILE_LOG_PADDING
    rl.draw_text_ex(self._font_bold, title, rl.Vector2(rect.x + COMPILE_LOG_PADDING, title_y),
                    COMPILE_LOG_TITLE_FONT_SIZE, 0, rl.WHITE)

    log_rect = rl.Rectangle(
      rect.x + COMPILE_LOG_PADDING,
      title_y + title_size.y + 18,
      rect.width - COMPILE_LOG_PADDING * 2,
      rect.height - title_size.y - COMPILE_LOG_PADDING * 2 - 18,
    )
    rl.draw_rectangle_rounded(log_rect, 0.04, 8, COMPILE_LOG_BG)
    rl.draw_rectangle_rounded_lines_ex(log_rect, 0.04, 8, 2, COMPILE_LOG_BORDER)

    lines = self._fit_lines(self._lines_callback(), log_rect.width - COMPILE_LOG_PADDING * 2)
    max_lines = max(1, int((log_rect.height - COMPILE_LOG_PADDING * 2) // COMPILE_LOG_LINE_HEIGHT))
    visible_lines = lines[-max_lines:]

    clip_rect = log_rect
    if self._parent_rect is not None:
      clip_rect = rl.get_collision_rec(log_rect, self._parent_rect)
    if clip_rect.width <= 0 or clip_rect.height <= 0:
      return

    rl.begin_scissor_mode(int(clip_rect.x), int(clip_rect.y), int(clip_rect.width), int(clip_rect.height))
    y = log_rect.y + COMPILE_LOG_PADDING
    for line in visible_lines:
      rl.draw_text_ex(self._font_regular, line, rl.Vector2(log_rect.x + COMPILE_LOG_PADDING, y),
                      COMPILE_LOG_FONT_SIZE, 0, COMPILE_LOG_TEXT)
      y += COMPILE_LOG_LINE_HEIGHT
    rl.end_scissor_mode()

  def _fit_lines(self, lines: list[str], max_width: float) -> list[str]:
    fitted: list[str] = []
    for line in lines:
      fitted.append(self._truncate_line(line, max_width))
    return fitted or [tr(self._empty_text)]

  def _truncate_line(self, line: str, max_width: float) -> str:
    text = line.expandtabs(2).strip()
    if measure_text_cached(self._font_regular, text, COMPILE_LOG_FONT_SIZE).x <= max_width:
      return text

    ellipsis = "..."
    while text and measure_text_cached(self._font_regular, text + ellipsis, COMPILE_LOG_FONT_SIZE).x > max_width:
      text = text[:-1]
    return (text.rstrip() + ellipsis) if text else ellipsis


class SpeedCameraRegionsPanel(Widget):
  def __init__(
    self,
    region_stats_callback: Callable[[], list[tuple[str, int, int, str]]],
    category_counts_callback: Callable[[], list[tuple[str, int]]],
    log_lines_callback: Callable[[], list[str]],
    log_active_callback: Callable[[], bool],
  ):
    super().__init__()
    self._region_stats_callback = region_stats_callback
    self._category_counts_callback = category_counts_callback
    self._log_lines_callback = log_lines_callback
    self._log_active_callback = log_active_callback
    self._font = gui_app.font(FontWeight.NORMAL)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._selected_tab = "stats"
    self._tab_rects: dict[str, rl.Rectangle] = {}
    self.set_rect(rl.Rectangle(0, 0, 0, SPEED_CAMERA_REGION_PANEL_HEIGHT))

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, rect: rl.Rectangle):
    panel_rect = rl.Rectangle(
      rect.x + SPEED_CAMERA_REGION_PADDING,
      rect.y + SPEED_CAMERA_REGION_PADDING / 2,
      rect.width - SPEED_CAMERA_REGION_PADDING * 2,
      rect.height - SPEED_CAMERA_REGION_PADDING,
    )
    rl.draw_rectangle_rounded(panel_rect, 0.04, 8, COMPILE_LOG_BG)
    rl.draw_rectangle_rounded_lines_ex(panel_rect, 0.04, 8, 2, COMPILE_LOG_BORDER)
    self._draw_tabs(panel_rect)

    content_rect = rl.Rectangle(
      panel_rect.x + SPEED_CAMERA_REGION_PADDING,
      panel_rect.y + SPEED_CAMERA_REGION_PADDING + SPEED_CAMERA_DETAIL_TAB_HEIGHT + 8,
      panel_rect.width - SPEED_CAMERA_REGION_PADDING * 2,
      panel_rect.height - SPEED_CAMERA_REGION_PADDING * 2 - SPEED_CAMERA_DETAIL_TAB_HEIGHT - 8,
    )
    if self._active_tab() == "log":
      self._draw_log(content_rect)
      return
    self._draw_stats(content_rect)

  def _draw_stats(self, content_rect: rl.Rectangle) -> None:
    region_stats = self._region_stats_callback()
    category_counts = self._category_counts_callback()
    if not region_stats:
      self._draw_text("--", rl.Vector2(content_rect.x, content_rect.y))
      return

    content_x = content_rect.x
    content_y = content_rect.y
    content_w = content_rect.width
    content_h = content_rect.height
    category_h = SPEED_CAMERA_REGION_LINE_HEIGHT
    header_h = SPEED_CAMERA_REGION_LINE_HEIGHT
    max_rows = max(1, int((content_h - category_h - header_h) // SPEED_CAMERA_REGION_LINE_HEIGHT))
    column_count = 3
    column_gap = 34
    column_width = (content_w - column_gap * (column_count - 1)) / column_count
    all_width = 82
    alert_width = 78
    field_gap = 14
    name_width = column_width - all_width - alert_width - field_gap * 2

    visible_stats = region_stats[:max_rows * column_count]
    rows_per_column = (len(visible_stats) + column_count - 1) // column_count
    header_y = content_y + category_h
    self._draw_category_counts(category_counts, content_x, content_y, content_w)
    self._draw_headers(content_x, header_y, column_count, column_width, column_gap, name_width, all_width, alert_width, field_gap)
    rl.draw_line_ex(
      rl.Vector2(content_x, header_y + header_h - 4),
      rl.Vector2(content_x + content_w, header_y + header_h - 4),
      1,
      COMPILE_LOG_BORDER,
    )

    for idx, (region, total_count, alert_count, latest_updated_at) in enumerate(visible_stats):
      col = idx // rows_per_column
      row = idx % rows_per_column
      x = content_x + col * (column_width + column_gap)
      y = header_y + header_h + row * SPEED_CAMERA_REGION_LINE_HEIGHT
      region_text = self._truncate(str(region), name_width)
      all_text = f"{total_count:,}"
      alert_text = f"{alert_count:,}"
      self._draw_text(region_text, rl.Vector2(x, y))

      all_x = x + name_width + field_gap
      alert_x = all_x + all_width + field_gap
      self._draw_right_aligned(all_text, rl.Rectangle(all_x, y, all_width, SPEED_CAMERA_REGION_LINE_HEIGHT))
      self._draw_right_aligned(alert_text, rl.Rectangle(alert_x, y, alert_width, SPEED_CAMERA_REGION_LINE_HEIGHT))

  def _draw_log(self, content_rect: rl.Rectangle) -> None:
    lines = self._fit_log_lines(self._log_lines_callback(), content_rect.width)
    max_lines = max(1, int(content_rect.height // COMPILE_LOG_LINE_HEIGHT))
    visible_lines = lines[-max_lines:]

    clip_rect = content_rect
    if self._parent_rect is not None:
      clip_rect = rl.get_collision_rec(content_rect, self._parent_rect)
    if clip_rect.width <= 0 or clip_rect.height <= 0:
      return

    rl.begin_scissor_mode(int(clip_rect.x), int(clip_rect.y), int(clip_rect.width), int(clip_rect.height))
    y = content_rect.y
    for line in visible_lines:
      rl.draw_text_ex(self._font, line, rl.Vector2(content_rect.x, y), COMPILE_LOG_FONT_SIZE, 0, COMPILE_LOG_TEXT)
      y += COMPILE_LOG_LINE_HEIGHT
    rl.end_scissor_mode()

  def _draw_tabs(self, panel_rect: rl.Rectangle) -> None:
    active_tab = self._active_tab()
    start_x = panel_rect.x + SPEED_CAMERA_REGION_PADDING
    y = panel_rect.y + SPEED_CAMERA_REGION_PADDING / 2
    for idx, (tab_id, label) in enumerate((("stats", "Stats"), ("log", "Log"))):
      tab_rect = rl.Rectangle(
        start_x + idx * (SPEED_CAMERA_DETAIL_TAB_WIDTH + SPEED_CAMERA_DETAIL_TAB_GAP),
        y,
        SPEED_CAMERA_DETAIL_TAB_WIDTH,
        SPEED_CAMERA_DETAIL_TAB_HEIGHT,
      )
      self._tab_rects[tab_id] = tab_rect
      color = SECTION_BG if tab_id == active_tab else rl.Color(32, 32, 32, 255)
      if self.is_pressed and rl.check_collision_point_rec(rl.get_mouse_position(), tab_rect):
        color = STEPPER_BUTTON_PRESSED
      rl.draw_rectangle_rounded(tab_rect, 0.25, 8, color)
      rl.draw_rectangle_rounded_lines_ex(tab_rect, 0.25, 8, 1, COMPILE_LOG_BORDER)
      text = tr(label)
      text_size = measure_text_cached(self._font_medium, text, SPEED_CAMERA_REGION_FONT_SIZE)
      text_pos = rl.Vector2(tab_rect.x + (tab_rect.width - text_size.x) / 2,
                            tab_rect.y + (tab_rect.height - text_size.y) / 2)
      rl.draw_text_ex(self._font_medium, text, text_pos, SPEED_CAMERA_REGION_FONT_SIZE, 0, TAB_TEXT)

  def _active_tab(self) -> str:
    return "log" if self._log_active_callback() else self._selected_tab

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    for tab_id, tab_rect in self._tab_rects.items():
      if rl.check_collision_point_rec(mouse_pos, tab_rect):
        self._selected_tab = tab_id
        return

  def _draw_text(self, text: str, pos: rl.Vector2) -> None:
    rl.draw_text_ex(self._font, text, pos, SPEED_CAMERA_REGION_FONT_SIZE, 0, COMPILE_LOG_TEXT)

  def _draw_category_counts(self, category_counts: list[tuple[str, int]], x: float, y: float, width: float) -> None:
    if not category_counts:
      return

    label_map = {
      "SPEED": "Speed",
      "SECTION_SPEED": "Section",
      "SIGNAL": "Signal",
      "UNKNOWN": "Unknown",
    }
    sorted_counts = sorted(category_counts, key=lambda item: (-item[1], item[0]))
    display_counts = sorted_counts[:4]
    if len(sorted_counts) > 4:
      display_counts.append(("OTHER", sum(count for _, count in sorted_counts[4:])))
    labels = [f"{label_map.get(category, category.title())} {count:,}" for category, count in display_counts]
    item_width = width / max(1, len(labels))
    for idx, label in enumerate(labels):
      fitted = self._truncate(label, max(1, item_width - SPEED_CAMERA_DETAIL_TAB_GAP))
      self._draw_text(fitted, rl.Vector2(x + idx * item_width, y))

  def _draw_headers(
    self,
    content_x: float,
    content_y: float,
    column_count: int,
    column_width: float,
    column_gap: float,
    name_width: float,
    all_width: float,
    alert_width: float,
    field_gap: float,
  ) -> None:
    for col in range(column_count):
      x = content_x + col * (column_width + column_gap)
      all_x = x + name_width + field_gap
      alert_x = all_x + all_width + field_gap
      self._draw_text("Region", rl.Vector2(x, content_y))
      self._draw_right_aligned("All", rl.Rectangle(all_x, content_y, all_width, SPEED_CAMERA_REGION_LINE_HEIGHT))
      self._draw_right_aligned("Alert", rl.Rectangle(alert_x, content_y, alert_width, SPEED_CAMERA_REGION_LINE_HEIGHT))

  def _draw_right_aligned(self, text: str, rect: rl.Rectangle) -> None:
    text_size = measure_text_cached(self._font, text, SPEED_CAMERA_REGION_FONT_SIZE)
    self._draw_text(text, rl.Vector2(rect.x + rect.width - text_size.x, rect.y))

  def _fit_log_lines(self, lines: list[str], max_width: float) -> list[str]:
    fitted: list[str] = []
    for line in lines:
      fitted.append(self._truncate_log_line(line, max_width))
    return fitted or [tr("No speed camera log yet")]

  def _truncate_log_line(self, line: str, max_width: float) -> str:
    text = line.expandtabs(2).strip()
    if measure_text_cached(self._font, text, COMPILE_LOG_FONT_SIZE).x <= max_width:
      return text

    ellipsis = "..."
    while text and measure_text_cached(self._font, text + ellipsis, COMPILE_LOG_FONT_SIZE).x > max_width:
      text = text[:-1]
    return (text.rstrip() + ellipsis) if text else ellipsis

  def _truncate(self, text: str, max_width: float) -> str:
    if measure_text_cached(self._font, text, SPEED_CAMERA_REGION_FONT_SIZE).x <= max_width:
      return text

    ellipsis = "..."
    while text and measure_text_cached(self._font, text + ellipsis, SPEED_CAMERA_REGION_FONT_SIZE).x > max_width:
      text = text[:-1]
    return (text.rstrip() + ellipsis) if text else ellipsis


class CustomSettingsLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._dialog: MultiOptionDialog | None = None
    self._last_compile_status_check = -COMPILE_STATUS_CHECK_INTERVAL
    self._last_compile_log_check = -COMPILE_LOG_CACHE_INTERVAL
    self._compile_log_tail = ""
    self._last_osm_roads_log_check = -COMPILE_LOG_CACHE_INTERVAL
    self._osm_roads_log_tail = ""
    self._last_speed_camera_log_check = -COMPILE_LOG_CACHE_INTERVAL
    self._speed_camera_log_tail = ""
    self._speed_camera_region_cache_loaded = False
    self._speed_camera_category_counts_cache: list[tuple[str, int]] = []
    self._speed_camera_region_stats_cache: list[tuple[str, int, int, str]] = []
    self._speed_camera_osm_status_loaded = False
    self._speed_camera_osm_status_cache = ""
    self._speed_camera_osm_stats_loaded = False
    self._speed_camera_osm_stats_cache = OsmRoadEnrichmentStats()
    self._speed_camera_verify_log_until = 0.0
    self._speed_camera_preview_callback: Callable | None = None
    self._speed_camera_preview_enabled: Callable[[], bool] | None = None
    self._current_tab = "UI"
    self._tab_rects: dict[str, rl.Rectangle] = {}
    self._tab_font = gui_app.font(FontWeight.MEDIUM)
    self._sections = {
      "UI": [
        SectionHeader(tr_noop("Toggle def")),
        self._toggle_json_item("ShowDebugMessage", tr_noop("Debug overlay"),
                               tr_noop("Shows the three-line trace debug panel on the onroad screen.")),
        self._toggle_param_item("DisableUpdates", tr_noop("Disable OTA updates"),
                                tr_noop("Prevents the updater from downloading and applying openpilot updates.")),
        self._toggle_json_item("ShowCarTracking", tr_noop("Show car tracking"),
                               CAR_TRACKING_DESCRIPTION),
        self._toggle_json_item("tpms", tr_noop("Show TPMS"),
                               tr_noop("Shows tire pressure values around the driver monitoring icon when TPMS data is available.")),
        self._toggle_json_item("kegmanBattery", tr_noop("Battery voltage"),
                               tr_noop("Shows battery voltage in the sidebar status area.")),
        SectionHeader(tr_noop("Kegman Show")),
        self._toggle_json_item("kegman", tr_noop("HUD overlay"),
                               tr_noop("Shows the custom Kegman information panel on the onroad screen.")),
        self._toggle_json_item("kegmanCPU", tr_noop("CPU temperature"),
                               tr_noop("Adds CPU temperature to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanLag", tr_noop("UI lag"),
                               tr_noop("Adds UI render lag to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanGPS", tr_noop("GPS accuracy"),
                               tr_noop("Adds GPS accuracy information to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanGPULoad", tr_noop("GPU load"),
                               tr_noop("Adds GPU load to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanAngle", tr_noop("Steering angle"),
                               tr_noop("Adds current steering angle to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanEngine", tr_noop("Engine status"),
                               tr_noop("Adds engine or EV status to the Kegman onroad panel."), enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanDistance", tr_noop("Relative distance"),
                               tr_noop("Adds lead vehicle distance to the Kegman onroad panel when lead data is available."),
                               enabled=self._kegman_enabled),
        self._toggle_json_item("kegmanSpeed", tr_noop("Relative speed"),
                               tr_noop("Adds lead vehicle relative speed to the Kegman onroad panel when lead data is available."),
                               enabled=self._kegman_enabled),
      ],
      "Community": [
        SectionHeader(tr_noop("Cruise Settings")),
        self._number_item("ParamCruiseMode", tr_noop("Cruise mode"), 0, 15, 1,
                          CRUISE_MODE_DESCRIPTION),
        self._number_item("ParamCruiseGap", tr_noop("Cruise gap"), 0, 4, 1,
                          tr_noop("Sets the custom cruise following gap when a non-zero cruise mode is selected."),
                          enabled=lambda: int(self._values()["ParamCruiseMode"]) != 0),
        self._number_item("ParamCurveSpeedLimit", tr_noop("Curve speed adjust"), 30, 100, 5,
                          tr_noop("Sets the curve speed adjustment percentage used by supported vehicle code.")),
        self._number_item("ParamAutoEngage", tr_noop("Auto cruise engage speed"), 30, 100, 5,
                          tr_noop("Sets the speed threshold used for automatic cruise engagement on supported vehicles.")),
        self._number_item("ParamAutoLaneChange", tr_noop("Auto lane change delay"), 0, 100, 10,
                          tr_noop("Sets the custom auto lane change delay used by supported vehicles.")),
        self._number_item("ParamSteerRatio", tr_noop("Steering ratio"), -0.2, 0.2, 0.01,
                          tr_noop("Applies a small steering ratio adjustment for supported custom lateral tuning.")),
        self._number_item("ParamStiffnessFactor", tr_noop("Lateral stiffness factor"), -0.1, 0.1, 0.01,
                          tr_noop("Applies a small lateral stiffness adjustment for supported custom tuning.")),
        self._number_item("ParamAngleOffsetDeg", tr_noop("Steering angle offset"), -2.0, 2.0, 0.1,
                          tr_noop("Applies a steering angle offset in degrees for supported custom tuning.")),
        SectionHeader(tr_noop("Screen & Power")),
        self._number_item("ParamBrightness", tr_noop("Screen brightness"), -20, 5, 1,
                          tr_noop("Adjusts automatic screen brightness. Negative values dim the screen; positive values brighten it.")),
        self._number_item("ParamAutoScreenOff", tr_noop("Screen timeout"), 0, 120, 1,
                          tr_noop("Sets the idle timeout in 10 second steps before the screen fades while ignition is off.")),
        self._toggle_json_item("ParamScreenOffAfterFade", tr_noop("Screen off after fade"),
                               tr_noop("Turns the display off after fade-out. If disabled, the display stays at minimum brightness.")),
        self._number_item("ParamPowerOff", tr_noop("Power off time"), 0, 60, 1,
                          tr_noop("Sets the delayed power-off timer in minutes after ignition turns off.")),
        self._number_item("DUAL_CAMERA_VIEW", tr_noop("Dual camera view"), 0, 1, 1,
                          tr_noop("Shows road and wide camera views side by side when both streams are available.")),
        SectionHeader(tr_noop("Logging")),
        self._logging_toggle_item(),
        self._selection_item("SelectedCar", tr_noop("Selected car"), self._car_options,
                             tr_noop("Overrides the selected vehicle fingerprint when a supported car option is available.")),
      ],
      "Git": [
        self._command_item(tr_noop("Fetch All and Prune"), tr_noop("SYNC"), ["bash", "-lc", "git fetch --all --prune && git remote prune origin"],
                           confirm=False, description=tr_noop("Fetches remote branch updates and removes stale remote-tracking branches.")),
        self._update_from_remote_item(),
        text_item(lambda: tr("Git status"), self._git_update_status_text,
                  description=lambda: tr("Shows the latest custom Git operation status.")),
      ],
      "Model": [
        self._model_selection_item(),
        text_item(lambda: tr("Compile status"), self._compile_status_text,
                  description=lambda: tr("Shows the current custom model compile state, progress, and last error.")),
        CompileLogPanel(tr_noop("Compile detail"), self._compile_log_lines),
      ],
      "Debug": [
        self._toggle_json_item("debug1", tr_noop("Debug 1"), tr_noop("Enables custom debug flag 1 for supported vehicle or UI code.")),
        self._toggle_json_item("debug2", tr_noop("Debug 2"), tr_noop("Enables custom debug flag 2 for supported vehicle or UI code.")),
        self._toggle_json_item("debug3", tr_noop("Debug 3"), tr_noop("Enables custom debug flag 3 for supported vehicle or UI code.")),
        self._toggle_json_item("debug4", tr_noop("Debug 4"), tr_noop("Enables custom debug flag 4 for supported vehicle or UI code.")),
        self._toggle_json_item("debug5", tr_noop("Debug 5"), tr_noop("Enables custom debug flag 5 for supported vehicle or UI code.")),
        self._toggle_json_item("debug6", tr_noop("Debug 6"), tr_noop("Enables custom debug flag 6 for supported vehicle or UI code.")),
      ],
      "Navigation": [
        SectionHeader(tr_noop("OSM roads DB")),
        self._osm_roads_download_item(),
        self._osm_roads_build_item(),
        self._osm_roads_git_db_item(),
        CompactStatusProgressInfoGroup(
          self._osm_roads_status_text,
          self._osm_roads_progress_text,
          [],
          status_details=[self._osm_roads_updated_status_text, self._osm_roads_pbf_status_text],
          progress_detail_callback=self._osm_roads_progress_detail_text,
        ),
        CompileLogPanel(tr_noop("OSM roads detail"), self._osm_roads_log_lines, tr_noop("No OSM roads log yet")),
        SectionHeader(tr_noop("OSM matching")),
        self._toggle_json_item("UseLocalOsmRoads", tr_noop("Use local OSM roads"),
                               tr_noop("Uses an offline OSM road DB to prefer speed camera candidates on the current road.")),
        self._cycle_choice_item("OsmRoadOverlayMode", tr_noop("OSM road overlay"), OSM_ROAD_OVERLAY_MODE_OPTIONS,
                                tr_noop("Shows or hides the mini map with nearby OSM roads, speed cameras, and ego position.")),
        self._number_item("LocalOsmRoadRadius", tr_noop("OSM road search radius"), 20, 100, 5,
                          description=tr_noop("Sets the local OSM road lookup radius used to infer the current road name."), unit="m"),
        SectionHeader(tr_noop("Speed camera DB")),
        self._speed_camera_update_item(),
        self._speed_camera_verify_item(),
        CompactStatusProgressInfoGroup(self._speed_camera_status_text, self._speed_camera_progress_text, [
          (tr_noop("Data date"), self._speed_camera_data_date_text),
          (tr_noop("Regions"), self._speed_camera_regions_text),
        ], status_details=[
          self._speed_camera_updated_status_text,
          self._speed_camera_osm_summary_status_text,
        ], progress_detail_callback=self._speed_camera_progress_detail_text),
        SpeedCameraRegionsPanel(
          self._speed_camera_region_stats,
          self._speed_camera_category_counts,
          self._speed_camera_log_lines,
          self._speed_camera_log_active,
        ),
        self._speed_camera_icon_preview_item(),
        SectionHeader(tr_noop("Speed camera tuning")),
        self._number_item("SpeedCameraLookaheadDistance", tr_noop("Camera search distance"), 500, 3000, 100,
                          description=tr_noop("Sets how far ahead, in meters, the speed camera lookup searches."), unit="m"),
        self._number_item("SpeedCameraLookaheadAngle", tr_noop("Camera search angle"), 15, 60, 5,
                          description=tr_noop("Sets the allowed angle from the current driving heading to a candidate camera."), unit="deg"),
        self._number_item("SpeedCameraDirectionAngle", tr_noop("Camera direction angle"), 30, 90, 5,
                          description=tr_noop("Sets the allowed difference between the public DB road direction and current driving heading."), unit="deg"),
        self._number_item("SpeedCameraPassingDistance", tr_noop("Camera passing distance"), 10, 80, 5,
                          description=tr_noop("Sets the distance, in meters, used to mark a camera as passed."), unit="m"),
        self._number_item("SpeedCameraPassedIgnoreSeconds", tr_noop("Camera ignore time"), 3, 30, 1,
                          description=tr_noop("Sets how long, in seconds, a passed camera is hidden from repeated alerts."), unit="s"),
        self._number_item("SpeedCameraMinGpsSpeed", tr_noop("Minimum GPS speed"), 0, 10, 1,
                          description=tr_noop("Sets the minimum vehicle speed, in km/h, required before speed camera lookup runs."), unit="km/h"),
        SectionHeader(tr_noop("Speed camera debug")),
        self._toggle_json_item("ShowSpeedCameraCandidates", tr_noop("Show camera candidates"),
                               tr_noop("Shows up to three selected speed camera candidates on the onroad HUD for debugging.")),
        self._toggle_json_item("ShowSpeedCameraDebugText", tr_noop("Show camera debug text"),
                               tr_noop("Shows camera classification debug text in the center of the onroad HUD.")),
        SectionHeader(tr_noop("External navigation")),
        self._toggle_param_item("UseExternalNaviRoutes", tr_noop("Use external navi routes"),
                                tr_noop("Allows navigation to use routes from an external navigation provider.")),
        self._cycle_param_int_item("ExternalNaviType", tr_noop("External navi type"), EXTERNAL_NAVI_OPTIONS,
                                   tr_noop("Selects the external navigation provider type.")),
        self._text_edit_item("MapboxToken", tr_noop("Mapbox token"),
                             tr_noop("Sets the Mapbox access token used by map and navigation features."),
                             value_font_size=25, value_lines=2),
      ],
    }
    self._scrollers = {name: Scroller(items, line_separator=True, spacing=0) for name, items in self._sections.items()}

  def set_speed_camera_preview_callback(self, callback: Callable | None, enabled: Callable[[], bool] | None = None) -> None:
    self._speed_camera_preview_callback = callback
    self._speed_camera_preview_enabled = enabled

  def _values(self):
    return read_custom_params(self._params)

  def _save_value(self, key: str, value: int | float | bool) -> None:
    write_custom_params({key: value}, self._params)
    ui_state.custom_publisher.update(force=True)

  def _kegman_enabled(self) -> bool:
    values = self._values()
    return bool(values["kegman"])

  @staticmethod
  def _decimals(step: int | float) -> int:
    step_text = f"{step:.10f}".rstrip("0").rstrip(".")
    return len(step_text.partition(".")[2])

  def _number_item(
    self,
    key: str,
    title: str,
    min_value: int | float,
    max_value: int | float,
    step_size: int | float,
    description: str | None = None,
    unit: str = "",
    enabled: bool | Callable[[], bool] = True,
  ):
    decimals = self._decimals(step_size)

    def current_numeric() -> int | float:
      value = self._values()[key]
      return float(value) if decimals else int(value)

    def current_value() -> str:
      value = current_numeric()
      value_text = f"{float(value):.{decimals}f}" if decimals else str(int(value))
      return f"{value_text}{unit}" if unit else value_text

    def step(delta: int) -> None:
      next_value = current_numeric() + delta * step_size
      next_value = max(min_value, min(max_value, next_value))
      if decimals:
        next_value = round(float(next_value), decimals)
      else:
        next_value = int(next_value)
      self._save_value(key, next_value)

    action = StepperAction(current_value, lambda: step(-1), lambda: step(1))
    action.set_enabled(enabled)
    return ListItem(title=lambda: tr(title), description=(lambda: tr(description)) if description else None, action_item=action)

  def _cycle_item(self, key: str, title: str, options: list[str], convert: Callable[[str], int | float]):
    def current_value() -> str:
      value = self._values()[key]
      if isinstance(value, float):
        return f"{value:.2f}"
      return str(value)

    def step(delta: int) -> None:
      current = current_value()
      try:
        idx = options.index(current)
      except ValueError:
        idx = 0
      next_idx = max(0, min(len(options) - 1, idx + delta))
      self._save_value(key, convert(options[next_idx]))

    action = StepperAction(current_value, lambda: step(-1), lambda: step(1))
    return ListItem(title=lambda: tr(title), action_item=action)

  def _cycle_int_item(self, key: str, title: str, options: list[str]):
    return self._cycle_item(key, title, options, int)

  def _cycle_float_item(self, key: str, title: str, options: list[str]):
    return self._cycle_item(key, title, options, float)

  def _cycle_choice_item(
    self,
    key: str,
    title: str,
    options: list[tuple[int, str]],
    description: str | None = None,
    enabled: bool | Callable[[], bool] = True,
  ):
    def option_index() -> int:
      value = int(self._values()[key])
      for idx, (option_value, _) in enumerate(options):
        if option_value == value:
          return idx
      return 0

    def current_value() -> str:
      return tr(options[option_index()][1])

    def step(delta: int) -> None:
      next_idx = max(0, min(len(options) - 1, option_index() + delta))
      self._save_value(key, options[next_idx][0])

    action = StepperAction(current_value, lambda: step(-1), lambda: step(1))
    action.set_enabled(enabled)
    return ListItem(title=lambda: tr(title), description=(lambda: tr(description)) if description else None, action_item=action)

  def _toggle_json_item(self, key: str, title: str, description: str | None = None, enabled: bool | Callable[[], bool] = True):
    return toggle_item(
      lambda: tr(title),
      description=(lambda: tr(description)) if description else None,
      initial_state=bool(self._values()[key]),
      callback=lambda state, k=key: self._save_value(k, bool(state)),
      enabled=enabled,
    )

  def _toggle_param_item(self, key: str, title: str, description: str | None = None):
    return toggle_item(
      lambda: tr(title),
      description=(lambda: tr(description)) if description else None,
      initial_state=self._params.get_bool(key),
      callback=lambda state, k=key: self._params.put_bool(k, bool(state)),
    )

  def _logging_toggle_item(self):
    def logging_enabled() -> bool:
      enable_logging = self._params.get("EnableLogging")
      enabled = True if enable_logging is None else self._params.get_bool("EnableLogging")
      return enabled and not self._params.get_bool("DisableLogging")

    def set_logging_enabled(state: bool) -> None:
      self._params.put_bool("EnableLogging", bool(state))
      self._params.put_bool("DisableLogging", not bool(state))

    return toggle_item(
      lambda: tr(tr_noop("Enable logging")),
      description=lambda: tr("Enables route logging and upload-related logger processes when logging is allowed."),
      initial_state=logging_enabled(),
      callback=set_logging_enabled,
    )

  def _cycle_param_int_item(self, key: str, title: str, options: list[str], description: str | None = None):
    def current_value() -> str:
      raw = self._param_text(key)
      return raw if raw in options else options[0]

    def step(delta: int) -> None:
      try:
        idx = options.index(current_value())
      except ValueError:
        idx = 0
      next_idx = max(0, min(len(options) - 1, idx + delta))
      self._params.put(key, options[next_idx])

    action = StepperAction(current_value, lambda: step(-1), lambda: step(1))
    return ListItem(title=lambda: tr(title), description=(lambda: tr(description)) if description else None, action_item=action)

  def _command_item(self, title: str, button_text: str, command: list[str], confirm: bool, description: str | None = None):
    def run() -> None:
      def worker() -> None:
        self._set_git_status(STATUS_RUNNING)
        clear_log(GIT_LOG_PATH)
        result = run_logged(command, REPO_ROOT, GIT_LOG_PATH)
        status = STATUS_SUCCESS if result.returncode == 0 else STATUS_FAILED
        error = "" if result.returncode == 0 else f"exit code {result.returncode}"
        self._set_git_status(status, error)

      threading.Thread(target=worker, daemon=True).start()

    def callback() -> None:
      if not confirm:
        run()
        return

      dialog = ConfirmDialog(tr("Are you sure?"), tr(button_text), callback=lambda result: run() if result == DialogResult.CONFIRM else None)
      gui_app.push_widget(dialog)

    return button_item(lambda: tr(title), lambda: tr(button_text),
                       description=(lambda: tr(description)) if description else None, callback=callback)

  def _update_from_remote_item(self):
    def callback() -> None:
      branch = self._param_text("GitBranch") or "test1-custom-port"

      def run() -> None:
        def worker() -> None:
          self._set_git_status(STATUS_RUNNING)
          clear_log(GIT_LOG_PATH)

          if not valid_branch_name(branch):
            self._set_git_status(STATUS_FAILED, f"invalid branch: {branch}")
            return

          fetch_result = run_logged(["git", "fetch", "origin"], REPO_ROOT, GIT_LOG_PATH)
          if fetch_result.returncode != 0:
            self._set_git_status(STATUS_FAILED, f"fetch failed: {fetch_result.returncode}")
            return

          if not origin_branch_exists(branch):
            self._set_git_status(STATUS_FAILED, f"missing origin/{branch}")
            return

          reset_result = run_logged(["git", "reset", "--hard", f"origin/{branch}"], REPO_ROOT, GIT_LOG_PATH)
          if reset_result.returncode != 0:
            self._set_git_status(STATUS_FAILED, f"reset failed: {reset_result.returncode}")
            return

          sync_result = run_logged(["git", "submodule", "sync", "--recursive"], REPO_ROOT, GIT_LOG_PATH)
          if sync_result.returncode != 0:
            self._set_git_status(STATUS_FAILED, f"submodule sync failed: {sync_result.returncode}")
            return

          submodule_result = run_logged(["git", "submodule", "update", "--init", "--recursive"], REPO_ROOT, GIT_LOG_PATH)
          if submodule_result.returncode != 0:
            self._set_git_status(STATUS_FAILED, f"submodule update failed: {submodule_result.returncode}")
            return

          self._set_git_status(STATUS_SUCCESS, "")

        threading.Thread(target=worker, daemon=True).start()

      content = tr("Update from remote? This will reset local files to origin branch.")
      dialog = ConfirmDialog(content, tr("Update"), callback=lambda result: run() if result == DialogResult.CONFIRM else None)
      gui_app.push_widget(dialog)

    return button_item(lambda: tr("Update from Remote"), lambda: tr("UPDATE"),
                       description=lambda: tr("Fetches the configured origin branch and resets this checkout to match it."),
                       callback=callback)

  def _speed_camera_update_item(self):
    return button_item(
      lambda: tr("Update DB"),
      self._speed_camera_button_text,
      description=lambda: tr("Downloads the national public unmanned traffic enforcement camera CSV and imports it into the local navigation DB."),
      callback=self._handle_speed_camera_update,
      enabled=lambda: self._speed_camera_update_status() != STATUS_RUNNING,
    )

  def _speed_camera_verify_item(self):
    return button_item(
      lambda: tr("Verify DB"),
      lambda: tr("VERIFY"),
      description=lambda: tr("Checks speed camera DB records, data date, regions, and OSM road-name matching without changing the DB."),
      callback=self._handle_speed_camera_verify,
      enabled=lambda: self._speed_camera_update_status() != STATUS_RUNNING,
    )

  def _speed_camera_icon_preview_item(self):
    def enabled() -> bool:
      return self._speed_camera_preview_enabled() if self._speed_camera_preview_enabled is not None else True

    def callback() -> None:
      start_speed_camera_debug_preview(SPEED_CAMERA_DEBUG_PREVIEW_DURATION_SECONDS)
      if self._speed_camera_preview_callback is not None:
        self._speed_camera_preview_callback()

    return button_item(
      lambda: tr("Speed camera icon preview"),
      lambda: tr("SHOW"),
      description=lambda: tr("Shows a 30 second HUD-only speed camera icon preview and switches to the camera screen when openpilot is onroad."),
      callback=callback,
      enabled=enabled,
    )

  def _osm_roads_download_item(self):
    return button_item(
      lambda: tr("Download OSM Data"),
      self._osm_roads_download_button_text,
      description=lambda: tr("Downloads the South Korea OSM PBF used to build the offline road-name DB."),
      callback=self._handle_osm_roads_download,
      enabled=lambda: self._osm_roads_update_status() != STATUS_RUNNING,
    )

  def _osm_roads_build_item(self):
    return button_item(
      lambda: tr("Build OSM DB"),
      self._osm_roads_build_button_text,
      description=lambda: tr("Builds the offline road-name DB from the downloaded South Korea OSM PBF."),
      callback=self._handle_osm_roads_build,
      enabled=lambda: self._osm_roads_update_status() != STATUS_RUNNING and OSM_ROADS_PBF_PATH.exists(),
    )

  def _osm_roads_git_db_item(self):
    return button_item(
      lambda: tr("Install OSM DB from Git"),
      self._osm_roads_git_db_button_text,
      description=lambda: tr("Downloads the prebuilt OSM roads DB from GitHub LFS and installs it."),
      callback=self._handle_osm_roads_git_db,
      enabled=lambda: self._osm_roads_update_status() != STATUS_RUNNING,
    )

  def _handle_speed_camera_update(self) -> None:
    def run() -> None:
      if self._speed_camera_update_running():
        return

      try:
        self._write_speed_camera_update_lock()
      except OSError as e:
        self._set_speed_camera_failed(f"lock open failed: {e}")
        return

      def worker() -> None:
        try:
          self._params.put(SPEED_CAMERA_ERROR_KEY, "")
          self._params.put(SPEED_CAMERA_PROGRESS_KEY, 0)
          self._params.put(SPEED_CAMERA_COUNT_KEY, 0)
          try:
            clear_log(SPEED_CAMERA_LOG_PATH)
          except OSError as e:
            self._set_speed_camera_failed(f"log open failed: {e}")
            return

          try:
            result = run_logged([sys.executable, "tools/scripts/update_speed_cameras.py"], REPO_ROOT, SPEED_CAMERA_LOG_PATH)
          except OSError as e:
            self._set_speed_camera_failed(f"update start failed: {e}")
            return
          if result.returncode != 0:
            self._set_speed_camera_failed(f"exit code {result.returncode}")
            return

          count = self._speed_camera_db_count_from_log()
          self._params.put(SPEED_CAMERA_COUNT_KEY, max(0, count))
          self._params.put(SPEED_CAMERA_PROGRESS_KEY, 100)
          data_date = database_data_date(SPEED_CAMERA_DB_PATH)
          if data_date:
            self._params.put(SPEED_CAMERA_DATA_DATE_KEY, data_date)
          self._refresh_speed_camera_region_counts(force=True)
          self._refresh_speed_camera_osm_status(force=True)
          self._params.put(SPEED_CAMERA_UPDATED_AT_KEY, time.strftime("%Y-%m-%d %H:%M"))
          self._params.put(SPEED_CAMERA_STATUS_KEY, STATUS_SUCCESS)
          self._params.put(SPEED_CAMERA_ERROR_KEY, "")
        finally:
          self._clear_speed_camera_update_lock()

      threading.Thread(target=worker, daemon=True).start()

    content = tr("Download public speed camera CSV and replace the local DB?")
    dialog = ConfirmDialog(content, tr("UPDATE"), callback=lambda result: run() if result == DialogResult.CONFIRM else None)
    gui_app.push_widget(dialog)

  def _handle_speed_camera_verify(self) -> None:
    self._refresh_speed_camera_region_counts(force=True)
    self._refresh_speed_camera_osm_status(force=True)
    lines = self._speed_camera_verify_lines()
    try:
      with open(SPEED_CAMERA_LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"$ verify speed camera DB {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        for line in lines:
          log_file.write(f"{line}\n")
    except OSError as e:
      self._params.put(SPEED_CAMERA_ERROR_KEY, f"verify log failed: {e}")
    self._speed_camera_log_tail = "\n".join(lines)
    self._last_speed_camera_log_check = time.monotonic()
    self._speed_camera_verify_log_until = time.monotonic() + 15.0

  def _handle_osm_roads_command(
    self,
    command: list[str],
    content: str,
    confirm_text: str,
    reset_segment_count: bool,
    mark_db_updated: bool,
  ) -> None:
    def run() -> None:
      if self._osm_roads_update_running():
        return

      try:
        self._write_osm_roads_update_lock()
      except OSError as e:
        self._set_osm_roads_failed(f"lock open failed: {e}")
        return

      def worker() -> None:
        try:
          self._params.put(OSM_ROADS_STATUS_KEY, STATUS_RUNNING)
          self._params.put(OSM_ROADS_ERROR_KEY, "")
          self._params.put(OSM_ROADS_PROGRESS_KEY, 0)
          if reset_segment_count:
            self._params.put(OSM_ROADS_COUNT_KEY, 0)
          try:
            clear_log(OSM_ROADS_LOG_PATH)
          except OSError as e:
            self._set_osm_roads_failed(f"log open failed: {e}")
            return

          try:
            result = run_logged(command, REPO_ROOT, OSM_ROADS_LOG_PATH)
          except OSError as e:
            self._set_osm_roads_failed(f"update start failed: {e}")
            return
          if result.returncode != 0:
            self._set_osm_roads_failed(f"exit code {result.returncode}")
            return

          if mark_db_updated:
            count = osm_roads_segment_count(DEFAULT_OSM_ROADS_DB_PATH)
            self._params.put(OSM_ROADS_COUNT_KEY, max(0, count))
            self._params.put(OSM_ROADS_UPDATED_AT_KEY, time.strftime("%Y-%m-%d %H:%M"))
          self._params.put(OSM_ROADS_PROGRESS_KEY, 100)
          self._params.put(OSM_ROADS_STATUS_KEY, STATUS_SUCCESS)
          self._params.put(OSM_ROADS_ERROR_KEY, "")
        finally:
          self._clear_osm_roads_update_lock()

      threading.Thread(target=worker, daemon=True).start()

    dialog = ConfirmDialog(content, tr(confirm_text), callback=lambda result: run() if result == DialogResult.CONFIRM else None)
    gui_app.push_widget(dialog)

  def _handle_osm_roads_download(self) -> None:
    self._handle_osm_roads_command(
      [sys.executable, "tools/scripts/update_osm_roads.py", "--download-only"],
      tr("Download South Korea OSM data? This can take several minutes."),
      "DOWNLOAD",
      reset_segment_count=False,
      mark_db_updated=False,
    )

  def _handle_osm_roads_build(self) -> None:
    self._handle_osm_roads_command(
      [sys.executable, "tools/scripts/update_osm_roads.py", "--skip-download", "--keep-pbf", "--skip-road-graph"],
      tr("Build the local OSM roads DB from the downloaded OSM data? This can take several minutes."),
      "BUILD",
      reset_segment_count=True,
      mark_db_updated=True,
    )

  def _handle_osm_roads_git_db(self) -> None:
    self._handle_osm_roads_command(
      [sys.executable, "tools/scripts/install_osm_roads_db_from_git.py", "--require-road-graph"],
      tr("Download the prebuilt OSM roads DB from GitHub and replace the local DB? This can take several minutes."),
      "INSTALL",
      reset_segment_count=True,
      mark_db_updated=True,
    )

  def _speed_camera_update_status(self) -> str:
    if self._speed_camera_update_running():
      return STATUS_RUNNING
    status = self._param_text(SPEED_CAMERA_STATUS_KEY)
    if status == STATUS_RUNNING:
      return STATUS_IDLE
    return status or STATUS_IDLE

  def _osm_roads_update_status(self) -> str:
    if self._osm_roads_update_running():
      return STATUS_RUNNING
    status = self._param_text(OSM_ROADS_STATUS_KEY)
    if status == STATUS_RUNNING:
      return STATUS_IDLE
    return status or STATUS_IDLE

  def _write_speed_camera_update_lock(self) -> None:
    SPEED_CAMERA_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_data = {"pid": os.getpid(), "started_at": time.time()}
    SPEED_CAMERA_LOCK_PATH.write_text(json.dumps(lock_data, separators=(",", ":")), encoding="utf-8")

  def _clear_speed_camera_update_lock(self) -> None:
    try:
      SPEED_CAMERA_LOCK_PATH.unlink()
    except OSError:
      pass

  def _speed_camera_update_running(self) -> bool:
    try:
      lock_data = json.loads(SPEED_CAMERA_LOCK_PATH.read_text(encoding="utf-8"))
      pid = int(lock_data.get("pid", 0))
      started_at = float(lock_data.get("started_at", 0.0))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
      self._clear_speed_camera_update_lock()
      return False

    if time.time() - started_at > SPEED_CAMERA_LOCK_STALE_SECONDS or not process_alive(pid):
      self._clear_speed_camera_update_lock()
      return False

    return True

  def _write_osm_roads_update_lock(self) -> None:
    OSM_ROADS_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_data = {"pid": os.getpid(), "started_at": time.time()}
    OSM_ROADS_LOCK_PATH.write_text(json.dumps(lock_data, separators=(",", ":")), encoding="utf-8")

  def _clear_osm_roads_update_lock(self) -> None:
    try:
      OSM_ROADS_LOCK_PATH.unlink()
    except OSError:
      pass

  def _osm_roads_update_running(self) -> bool:
    try:
      lock_data = json.loads(OSM_ROADS_LOCK_PATH.read_text(encoding="utf-8"))
      pid = int(lock_data.get("pid", 0))
      started_at = float(lock_data.get("started_at", 0.0))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
      self._clear_osm_roads_update_lock()
      return False

    if time.time() - started_at > OSM_ROADS_LOCK_STALE_SECONDS or not process_alive(pid):
      self._clear_osm_roads_update_lock()
      return False

    return True

  def _speed_camera_button_text(self) -> str:
    status = self._speed_camera_update_status()
    if status == STATUS_RUNNING:
      return tr("WAIT")
    if status == STATUS_FAILED:
      return tr("RETRY")
    return tr("UPDATE")

  def _osm_roads_download_button_text(self) -> str:
    status = self._osm_roads_update_status()
    if status == STATUS_RUNNING:
      return tr("WAIT")
    if status == STATUS_FAILED:
      return tr("RETRY")
    return tr("DOWNLOAD")

  def _osm_roads_build_button_text(self) -> str:
    status = self._osm_roads_update_status()
    if status == STATUS_RUNNING:
      return tr("WAIT")
    if status == STATUS_FAILED:
      return tr("RETRY")
    return tr("BUILD")

  def _osm_roads_git_db_button_text(self) -> str:
    status = self._osm_roads_update_status()
    if status == STATUS_RUNNING:
      return tr("WAIT")
    if status == STATUS_FAILED:
      return tr("RETRY")
    return tr("INSTALL")

  def _speed_camera_db_count_from_log(self, log_path: str = SPEED_CAMERA_LOG_PATH) -> int:
    try:
      with open(log_path, encoding="utf-8", errors="replace") as log_file:
        for line in reversed(log_file.readlines()):
          if line.startswith("imported "):
            return int(line.split()[1])
          if line.startswith("cameras "):
            return int(line.split()[1].split("/")[0].replace(",", ""))
    except (OSError, ValueError, IndexError):
      pass
    return 0

  def _set_speed_camera_failed(self, error: str) -> None:
    try:
      with open(SPEED_CAMERA_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        tail = log_file.read()[-500:].strip()
    except OSError:
      tail = ""
    self._params.put(SPEED_CAMERA_STATUS_KEY, STATUS_FAILED)
    self._params.put(SPEED_CAMERA_ERROR_KEY, tail or error)

  def _set_osm_roads_failed(self, error: str) -> None:
    try:
      with open(OSM_ROADS_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        tail = log_file.read()[-500:].strip()
    except OSError:
      tail = ""
    self._params.put(OSM_ROADS_STATUS_KEY, STATUS_FAILED)
    self._params.put(OSM_ROADS_ERROR_KEY, tail or error)

  def _speed_camera_progress_text(self) -> str:
    progress = self._param_text(SPEED_CAMERA_PROGRESS_KEY)
    if not progress:
      if self._speed_camera_count() > 0:
        return "100%"
      return "--"
    return f"{progress}%"

  def _osm_roads_progress_text(self) -> str:
    progress = self._param_text(OSM_ROADS_PROGRESS_KEY)
    if not progress:
      if osm_roads_segment_count(DEFAULT_OSM_ROADS_DB_PATH) > 0:
        return "100%"
      return "--"
    return f"{progress}%"

  def _osm_roads_progress_percent(self) -> int:
    try:
      return max(0, min(100, int(self._param_text(OSM_ROADS_PROGRESS_KEY) or 0)))
    except ValueError:
      return 0

  def _speed_camera_data_date_text(self) -> str:
    data_date = self._param_text(SPEED_CAMERA_DATA_DATE_KEY) or database_data_date(SPEED_CAMERA_DB_PATH)
    return data_date or "--"

  def _speed_camera_updated_text(self) -> str:
    return self._param_text(SPEED_CAMERA_UPDATED_AT_KEY) or "--"

  def _speed_camera_updated_status_text(self) -> str:
    updated = self._speed_camera_updated_text()
    return f"{tr('Updated')} {updated}" if updated != "--" else f"{tr('Updated')} --"

  def _osm_roads_updated_text(self) -> str:
    return self._param_text(OSM_ROADS_UPDATED_AT_KEY) or osm_roads_built_at(DEFAULT_OSM_ROADS_DB_PATH) or "--"

  def _osm_roads_updated_status_text(self) -> str:
    updated = self._osm_roads_updated_text()
    return f"{tr('Updated')} {updated}" if updated != "--" else f"{tr('Updated')} --"

  def _format_bytes_text(self, size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024 * 1024:
      return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    if size_bytes >= 1024 * 1024:
      return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
      return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"

  def _osm_roads_pbf_size_text(self) -> str:
    try:
      return self._format_bytes_text(OSM_ROADS_PBF_PATH.stat().st_size)
    except OSError:
      return "--"

  def _osm_roads_pbf_status_text(self) -> str:
    size_text = self._osm_roads_pbf_size_text()
    return f"PBF {size_text}" if size_text != "--" else "PBF --"

  def _osm_roads_log_operation(self) -> str:
    try:
      with open(OSM_ROADS_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        head = log_file.read(4096)
    except OSError:
      return ""
    if "tools/scripts/install_osm_roads_db_from_git.py" in head:
      return "git_db"
    if "--download-only" in head:
      return "download"
    if "--skip-download" in head:
      return "build"
    if "tools/scripts/update_osm_roads.py" in head:
      return "update"
    return ""

  def _osm_roads_download_detail_text(self) -> str:
    for line in reversed(self._osm_roads_log_lines()):
      match = re.search(r"download\s+[0-9]+%\s+\(([0-9]+)/([0-9]+)\)", line)
      if match is not None:
        return f"{self._format_bytes_text(int(match.group(1)))} / {self._format_bytes_text(int(match.group(2)))}"
      match = re.search(r"downloaded\s+([0-9]+)", line)
      if match is not None:
        return self._format_bytes_text(int(match.group(1)))
    return self._osm_roads_pbf_size_text() if OSM_ROADS_PBF_PATH.exists() else ""

  def _osm_roads_git_db_detail_text(self) -> str:
    for line in reversed(self._osm_roads_log_lines()):
      match = re.search(r"downloaded git DB .*\(([0-9]+) bytes\)", line)
      if match is not None:
        return self._format_bytes_text(int(match.group(1)))
      match = re.search(r"validated downloaded DB: ([0-9,]+) segments", line)
      if match is not None:
        return f"segments {match.group(1)}"
    return ""

  def _format_count_text(self, count: str) -> str:
    try:
      return f"{int(count):,}"
    except ValueError:
      return count

  def _osm_roads_current_segment_count(self) -> int:
    try:
      count = int(self._param_text(OSM_ROADS_COUNT_KEY) or 0)
    except ValueError:
      count = 0
    if count > 0:
      return count

    for line in reversed(self._osm_roads_log_lines()):
      match = re.search(r"^segments\s+([0-9,]+)", line.strip())
      if match is not None:
        try:
          return int(match.group(1).replace(",", ""))
        except ValueError:
          return 0
    return 0

  def _osm_roads_progress_detail_text(self) -> str:
    if self._osm_roads_update_status() != STATUS_RUNNING:
      return ""
    if self._osm_roads_log_operation() == "download":
      return self._osm_roads_download_detail_text()
    if self._osm_roads_log_operation() == "git_db":
      return self._osm_roads_git_db_detail_text()
    count = self._osm_roads_current_segment_count()
    return f"segments {count:,}" if count > 0 else ""

  def _osm_roads_status_text(self) -> str:
    status = self._osm_roads_update_status()
    if status == STATUS_RUNNING:
      if self._osm_roads_log_operation() == "download":
        return tr("OSM Downloading")
      if self._osm_roads_log_operation() == "git_db":
        return tr("OSM DB Installing")
      return tr("OSM Building")
    if status == STATUS_SUCCESS:
      if self._osm_roads_log_operation() == "download":
        return f"{tr('PBF Ready')} / {self._osm_roads_pbf_size_text()}"
      count = self._format_count_text(self._param_text(OSM_ROADS_COUNT_KEY) or str(osm_roads_segment_count(DEFAULT_OSM_ROADS_DB_PATH)))
      return f"{tr('Ready')} / {count} segments"
    if status == STATUS_FAILED:
      error = self._param_text(OSM_ROADS_ERROR_KEY)
      if len(error) > 80:
        error = error[-80:]
      return f"{tr('Failed')}: {error}".strip(": ")

    count = osm_roads_segment_count(DEFAULT_OSM_ROADS_DB_PATH)
    if count > 0:
      return f"{tr('Ready')} / {count:,} segments"
    if OSM_ROADS_PBF_PATH.exists():
      return f"{tr('PBF Ready')} / {self._osm_roads_pbf_size_text()}"
    return tr("Idle")

  def _osm_roads_log_lines(self) -> list[str]:
    now = time.monotonic()
    if now - self._last_osm_roads_log_check < COMPILE_LOG_CACHE_INTERVAL:
      return self._osm_roads_log_tail.splitlines()
    self._last_osm_roads_log_check = now

    try:
      with open(OSM_ROADS_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        lines = [line.rstrip() for line in log_file.readlines()[-120:]]
    except OSError:
      error = self._param_text(OSM_ROADS_ERROR_KEY)
      self._osm_roads_log_tail = error or ""
      return self._osm_roads_log_tail.splitlines()

    visible_lines = [line for line in lines if line.strip()]
    self._osm_roads_log_tail = "\n".join(visible_lines[-80:])
    return self._osm_roads_log_tail.splitlines()

  def _speed_camera_log_lines(self) -> list[str]:
    now = time.monotonic()
    if now - self._last_speed_camera_log_check < COMPILE_LOG_CACHE_INTERVAL:
      return self._speed_camera_log_tail.splitlines()
    self._last_speed_camera_log_check = now

    try:
      with open(SPEED_CAMERA_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        lines = [line.rstrip() for line in log_file.readlines()[-120:]]
    except OSError:
      error = self._param_text(SPEED_CAMERA_ERROR_KEY)
      self._speed_camera_log_tail = error or ""
      return self._speed_camera_log_tail.splitlines()

    visible_lines = [line for line in lines if line.strip()]
    self._speed_camera_log_tail = "\n".join(visible_lines[-80:])
    return self._speed_camera_log_tail.splitlines()

  def _speed_camera_log_active(self) -> bool:
    return self._speed_camera_update_status() == STATUS_RUNNING or time.monotonic() < self._speed_camera_verify_log_until

  def _speed_camera_verify_lines(self) -> list[str]:
    stats = self._speed_camera_osm_stats(force=True)
    region_stats = self._speed_camera_region_stats()
    alert_total = sum(alert_count for _, _, alert_count, _ in region_stats)
    total_count = stats.total_count or self._speed_camera_count()

    lines = [
      f"db: {SPEED_CAMERA_DB_PATH}",
      f"cameras {total_count:,}",
      f"data date {self._speed_camera_data_date_text()}",
      f"regions {len(region_stats)} / alerts {alert_total:,}",
    ]

    if DEFAULT_OSM_ROADS_DB_PATH.exists():
      lines.append(f"osm roads DB: {DEFAULT_OSM_ROADS_DB_PATH} ({osm_roads_segment_count(DEFAULT_OSM_ROADS_DB_PATH):,} segments)")
    else:
      lines.append("osm roads DB: missing")

    lines.extend([
      f"osm road names matched {stats.matched_count:,} ({stats.match_percent}%)",
      f"osm road names primary {stats.primary_match_count:,}",
      f"osm road names extended {stats.extended_match_count:,} ({stats.extended_radius_m:.1f}m)",
      f"osm road names unmatched {stats.unmatched_count:,}",
    ])
    if stats.unmatched_by_category:
      category_text = ", ".join(f"{category} {count:,}" for category, count in stats.unmatched_by_category[:8])
      lines.append(f"unmatched by category: {category_text}")
    return lines


  def _refresh_speed_camera_region_counts(self, force: bool = False) -> None:
    if force or not self._speed_camera_region_cache_loaded:
      self._speed_camera_category_counts_cache = database_category_counts(SPEED_CAMERA_DB_PATH)
      self._speed_camera_region_stats_cache = database_region_stats(SPEED_CAMERA_DB_PATH)
      self._speed_camera_region_cache_loaded = True

  def _speed_camera_category_counts(self) -> list[tuple[str, int]]:
    return self._speed_camera_category_counts_cache

  def _speed_camera_region_stats(self) -> list[tuple[str, int, int, str]]:
    return self._speed_camera_region_stats_cache

  def _speed_camera_regions_text(self) -> str:
    region_stats = self._speed_camera_region_stats()
    if not region_stats:
      return "--"

    region_total = len(region_stats)
    alert_total = sum(alert_count for _, _, alert_count, _ in region_stats)
    return f"{region_total} regions / {alert_total:,} alerts"

  def _speed_camera_count(self) -> int:
    try:
      count = int(self._param_text(SPEED_CAMERA_COUNT_KEY) or 0)
      if count > 0:
        return count
    except ValueError:
      pass

    region_stats = self._speed_camera_region_stats()
    if region_stats:
      return sum(total_count for _, total_count, _, _ in region_stats)

    try:
      with sqlite3.connect(SPEED_CAMERA_DB_PATH) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM speed_cameras").fetchone()[0])
    except (OSError, sqlite3.Error, TypeError):
      return 0

  def _format_speed_camera_count(self) -> str:
    return f"{self._speed_camera_count():,}"

  def _speed_camera_current_update_count(self) -> int:
    try:
      count = int(self._param_text(SPEED_CAMERA_COUNT_KEY) or 0)
    except ValueError:
      count = 0
    if count > 0:
      return count
    return self._speed_camera_db_count_from_log()

  def _speed_camera_progress_detail_text(self) -> str:
    if self._speed_camera_update_status() != STATUS_RUNNING:
      return ""
    progress = self._param_text(SPEED_CAMERA_PROGRESS_KEY)
    try:
      progress_value = int(progress or 0)
    except ValueError:
      progress_value = 0
    if progress_value >= 99:
      return tr("Saving camera DB")
    if progress_value >= 95 and DEFAULT_OSM_ROADS_DB_PATH.exists():
      return tr("Applying OSM road names")
    count = self._speed_camera_current_update_count()
    return f"cameras {count:,}" if count > 0 else ""

  def _speed_camera_osm_stats(self, force: bool = False) -> OsmRoadEnrichmentStats:
    if force or not self._speed_camera_osm_stats_loaded:
      self._speed_camera_osm_stats_cache = database_osm_road_enrichment_stats(SPEED_CAMERA_DB_PATH)
      self._speed_camera_osm_stats_loaded = True
    return self._speed_camera_osm_stats_cache

  def _refresh_speed_camera_osm_status(self, force: bool = False) -> str:
    if not force and self._speed_camera_osm_status_loaded:
      return self._speed_camera_osm_status_cache
    if force:
      self._speed_camera_osm_stats(force=True)
    self._speed_camera_osm_status_cache = self._read_speed_camera_osm_status()
    self._speed_camera_osm_status_loaded = True
    return self._speed_camera_osm_status_cache

  def _read_speed_camera_osm_status(self) -> str:
    if not DEFAULT_OSM_ROADS_DB_PATH.exists():
      return tr("OSM roads DB missing")
    if not SPEED_CAMERA_DB_PATH.exists():
      return tr("OSM road names: no camera DB")

    stats = self._speed_camera_osm_stats()
    if stats.total_count <= 0:
      return tr("OSM road names: unavailable")

    if stats.matched_count > 0:
      extended_text = f" / +{stats.extended_match_count:,} ext" if stats.extended_match_count > 0 else ""
      return f"{tr('OSM road names')}: {stats.matched_count:,} {tr('matched')}{extended_text} / {stats.unmatched_count:,} empty"
    return tr("OSM road names: not applied")

  def _speed_camera_osm_matched_status_text(self) -> str:
    if self._speed_camera_update_status() == STATUS_RUNNING:
      progress = self._param_text(SPEED_CAMERA_PROGRESS_KEY)
      try:
        progress_value = int(progress or 0)
      except ValueError:
        progress_value = 0
      if progress_value >= 95 and DEFAULT_OSM_ROADS_DB_PATH.exists():
        return tr("Applying OSM road names")
      return tr("OSM road names: pending")

    stats = self._speed_camera_osm_stats()
    if stats.total_count <= 0:
      return self._refresh_speed_camera_osm_status()
    extended_text = f" / +{stats.extended_match_count:,} ext" if stats.extended_match_count > 0 else ""
    return f"OSM matched {stats.matched_count:,}{extended_text}"

  def _speed_camera_osm_empty_status_text(self) -> str:
    if self._speed_camera_update_status() == STATUS_RUNNING:
      return tr("OSM empty: calculating")

    stats = self._speed_camera_osm_stats()
    if stats.total_count <= 0:
      return ""
    return f"OSM empty {stats.unmatched_count:,}"

  def _speed_camera_osm_summary_status_text(self) -> str:
    if self._speed_camera_update_status() == STATUS_RUNNING:
      return self._speed_camera_osm_matched_status_text()

    stats = self._speed_camera_osm_stats()
    if stats.total_count <= 0:
      return self._refresh_speed_camera_osm_status()
    extended_text = f" / +{stats.extended_match_count:,} ext" if stats.extended_match_count > 0 else ""
    return f"OSM matched {stats.matched_count:,}{extended_text} / empty {stats.unmatched_count:,}"

  def _speed_camera_status_text(self) -> str:
    status = self._speed_camera_update_status()
    if status == STATUS_RUNNING:
      progress = self._param_text(SPEED_CAMERA_PROGRESS_KEY)
      try:
        progress_value = int(progress or 0)
      except ValueError:
        progress_value = 0
      if progress_value >= 95 and DEFAULT_OSM_ROADS_DB_PATH.exists():
        return tr("Importing")
      return tr("Downloading")
    if status == STATUS_SUCCESS:
      count = self._format_speed_camera_count()
      return f"{tr('Ready')} / {count} cameras"
    if status == STATUS_IDLE and self._speed_camera_count() > 0:
      count = self._format_speed_camera_count()
      return f"{tr('Ready')} / {count} cameras"
    if status == STATUS_FAILED:
      error = self._param_text(SPEED_CAMERA_ERROR_KEY)
      if len(error) > 80:
        error = error[-80:]
      return f"{tr('Failed')}: {error}".strip(": ")
    return tr("Idle")

  def _set_git_status(self, status: str, error: str = "") -> None:
    self._params.put(GIT_STATUS_KEY, status)
    self._params.put(GIT_ERROR_KEY, error[-500:])

  def _git_update_status_text(self) -> str:
    status = self._param_text(GIT_STATUS_KEY) or STATUS_IDLE
    if status == STATUS_RUNNING:
      return tr("Running")
    if status == STATUS_SUCCESS:
      return tr("Ready")
    if status == STATUS_FAILED:
      error = self._param_text(GIT_ERROR_KEY)
      if len(error) > 80:
        error = error[-80:]
      return f"{tr('Failed')}: {error}".strip(": ")
    return tr("Idle")

  def _text_edit_item(self, key: str, title: str, description: str | None = None, value_font_size: int = 50,
                      value_lines: int = 1):
    item = button_item(lambda: tr(title), lambda: tr("EDIT"),
                       description=(lambda: tr(description)) if description else None,
                       callback=lambda k=key, t=title: self._show_keyboard(k, t),
                       value_font_size=value_font_size,
                       value_lines=value_lines)
    item.action_item.set_value(lambda k=key: self._param_text(k, return_default=True))
    return item

  def _show_keyboard(self, key: str, title: str) -> None:
    keyboard = Keyboard(max_text_size=512, callback=lambda result, k=key: self._handle_keyboard_result(k, keyboard, result))
    keyboard.set_title(tr(title), "")
    keyboard.set_text(self._param_text(key, return_default=True))
    gui_app.push_widget(keyboard)

  def _handle_keyboard_result(self, key: str, keyboard: Keyboard, result: DialogResult) -> None:
    if result == DialogResult.CONFIRM:
      self._params.put(key, keyboard.text)

  def _param_text(self, key: str, return_default: bool = False) -> str:
    raw = self._params.get(key, return_default=return_default)
    if raw is None:
      return ""
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

  def _selection_item(self, key: str, title: str, options_fn: Callable[[], list[str]], description: str | None = None):
    item = button_item(
      lambda: tr(title),
      lambda: tr("CHANGE"),
      description=(lambda: tr(description)) if description else None,
      callback=lambda k=key, t=title, fn=options_fn: self._show_selection(k, t, fn()),
    )
    item.action_item.set_value(lambda k=key: self._param_text(k))
    return item

  def _model_selection_item(self):
    item = button_item(
      lambda: tr("Active model"),
      self._model_button_text,
      description=lambda: tr("Selects and compiles the active driving model. Retry appears after a failed compile."),
      callback=self._handle_model_button,
      enabled=lambda: self._compile_status() != STATUS_RUNNING,
    )
    item.action_item.set_value(self._active_model_text)
    return item

  def _active_model_text(self) -> str:
    model_name = self._param_text("ActiveModelName")
    return DEFAULT_MODEL_NAME if not model_name or model_name in DEFAULT_MODEL_NAMES else model_name

  def _set_compile_failed(self, model_name: str, error: str) -> None:
    self._params.put(COMPILE_STATUS_KEY, STATUS_FAILED)
    self._params.put(COMPILE_NAME_KEY, model_name)
    self._params.put(COMPILE_FINISHED_AT_KEY, str(int(time.time())))
    self._params.put(COMPILE_ERROR_KEY, error[-500:])

  def _set_compile_success(self, model_name: str) -> None:
    self._params.put(COMPILE_STATUS_KEY, STATUS_SUCCESS)
    self._params.put(COMPILE_NAME_KEY, model_name)
    self._params.put(COMPILE_FINISHED_AT_KEY, str(int(time.time())))
    self._params.put(COMPILE_ERROR_KEY, "")
    self._params.put(COMPILE_PROGRESS_KEY, 100)

  def _compile_progress(self) -> int:
    raw = self._param_text(COMPILE_PROGRESS_KEY)
    try:
      return max(0, min(100, int(raw)))
    except ValueError:
      return 0

  def _compile_process_running(self, model_name: str) -> bool | None:
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
      return None

    process_names = ("model_make.py", "compile_modeld.py", "compile3.py")
    for path in proc_dir.iterdir():
      if not path.name.isdigit():
        continue
      try:
        cmdline = (path / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
      except OSError:
        continue
      if any(process_name in cmdline for process_name in process_names):
        if not model_name or model_name in cmdline or "compile_modeld.py" in cmdline or "compile3.py" in cmdline:
          return True
    return False

  def _refresh_compile_status(self) -> None:
    status = self._param_text(COMPILE_STATUS_KEY)
    if status != STATUS_RUNNING:
      return

    now = time.monotonic()
    if now - self._last_compile_status_check < COMPILE_STATUS_CHECK_INTERVAL:
      return
    self._last_compile_status_check = now

    model_name = self._param_text(COMPILE_NAME_KEY)
    started_at = self._param_text(COMPILE_STARTED_AT_KEY)
    try:
      elapsed = int(time.time()) - int(started_at)
    except ValueError:
      self._set_compile_failed(model_name, "compile status was running without a valid start time")
      return

    if elapsed >= COMPILE_STALE_SECONDS:
      self._set_compile_failed(model_name, f"compile timed out after {elapsed}s")
      return

    process_running = self._compile_process_running(model_name)
    if process_running is False and elapsed >= COMPILE_PROCESS_GRACE_SECONDS:
      self._set_compile_failed(model_name, "compile process stopped before finishing")

  def _compile_status(self) -> str:
    self._refresh_compile_status()
    return self._param_text(COMPILE_STATUS_KEY) or STATUS_IDLE

  def _compile_status_text(self) -> str:
    status = self._compile_status()
    model_name = self._param_text(COMPILE_NAME_KEY)
    if status == STATUS_RUNNING:
      started_at = self._param_text(COMPILE_STARTED_AT_KEY)
      elapsed = ""
      if started_at:
        try:
          elapsed = f" ({max(0, int(time.time()) - int(started_at))}s)"
        except ValueError:
          elapsed = ""
      return f"{tr('Compiling...')} {self._compile_progress()}% {model_name}{elapsed}".strip()
    if status == STATUS_SUCCESS:
      return f"{tr('Ready')} {model_name}".strip()
    if status == STATUS_FAILED:
      error = self._param_text(COMPILE_ERROR_KEY)
      error = error.splitlines()[-1] if error else ""
      if len(error) > 80:
        error = error[-80:]
      return f"{tr('Failed')} {model_name}: {error}".strip(": ")
    return tr("Idle")

  def _compile_log_tail_text(self) -> str:
    lines = self._compile_log_lines()
    return lines[-1][-100:] if lines else ""

  def _compile_log_lines(self) -> list[str]:
    now = time.monotonic()
    if now - self._last_compile_log_check < COMPILE_LOG_CACHE_INTERVAL:
      return self._compile_log_tail.splitlines()
    self._last_compile_log_check = now

    try:
      with open(COMPILE_LOG_PATH, encoding="utf-8", errors="replace") as log_file:
        lines = [line.rstrip() for line in log_file.readlines()[-120:]]
    except OSError:
      error = self._param_text(COMPILE_ERROR_KEY)
      self._compile_log_tail = error or ""
      return self._compile_log_tail.splitlines()

    visible_lines = [line for line in lines if line.strip()]
    self._compile_log_tail = "\n".join(visible_lines[-80:])
    return self._compile_log_tail.splitlines()

  def _model_button_text(self) -> str:
    status = self._compile_status()
    if status == STATUS_RUNNING:
      return tr("WAIT")
    if status == STATUS_FAILED:
      return tr("RETRY")
    return tr("CHANGE")

  def _handle_model_button(self) -> None:
    if self._compile_status() == STATUS_FAILED:
      model_name = self._param_text(COMPILE_NAME_KEY) or self._param_text("ActiveModelName")
      if model_name and model_name not in DEFAULT_MODEL_NAMES:
        self._compile_selected_model(model_name)
        return
    self._show_selection("ActiveModelName", tr_noop("Active model"), MODEL_OPTIONS)

  def _show_selection(self, key: str, title: str, options: list[str]) -> None:
    current = self._param_text(key)
    if key == "ActiveModelName" and current in DEFAULT_MODEL_NAMES:
      current = DEFAULT_MODEL_NAME

    def handle_selection(result: DialogResult) -> None:
      if result == DialogResult.CONFIRM and self._dialog is not None:
        self._params.put(key, self._dialog.selection)
        if key == "ActiveModelName":
          ui_state.custom_publisher.update(force=True)
          self._compile_selected_model(self._dialog.selection)
      self._dialog = None

    self._dialog = MultiOptionDialog(tr(title), options, current, callback=handle_selection)
    gui_app.push_widget(self._dialog)

  def _compile_selected_model(self, model_name: str) -> None:
    if not model_name or model_name in DEFAULT_MODEL_NAMES:
      self._params.put(COMPILE_STATUS_KEY, STATUS_IDLE)
      self._params.put("ActiveModelName", DEFAULT_MODEL_NAME)
      self._params.put(COMPILE_NAME_KEY, "")
      self._params.put(COMPILE_ERROR_KEY, "")
      self._params.put(COMPILE_PROGRESS_KEY, 0)
      return

    self._params.put(COMPILE_STATUS_KEY, STATUS_RUNNING)
    self._params.put(COMPILE_NAME_KEY, model_name)
    self._params.put(COMPILE_STARTED_AT_KEY, str(int(time.time())))
    self._params.put(COMPILE_FINISHED_AT_KEY, "")
    self._params.put(COMPILE_ERROR_KEY, "")
    self._params.put(COMPILE_PROGRESS_KEY, 0)

    def worker() -> None:
      result: subprocess.CompletedProcess | None = None
      error = ""
      try:
        Path(COMPILE_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(COMPILE_LOG_PATH, "w") as log_file:
          result = subprocess.run([sys.executable, "model_make.py", "--model", model_name], cwd=MODELD_DIR,
                                  stdout=log_file, stderr=subprocess.STDOUT, text=True, check=False)
      except Exception as e:
        error = f"{type(e).__name__}: {e}"
        try:
          with open(COMPILE_LOG_PATH, "a") as log_file:
            log_file.write(f"\n{error}\n")
        except OSError:
          pass

      status = self._param_text(COMPILE_STATUS_KEY)
      running_model = self._param_text(COMPILE_NAME_KEY)
      if status != STATUS_RUNNING or running_model != model_name:
        return

      if result is not None and result.returncode == 0:
        self._set_compile_success(model_name)
      else:
        try:
          with open(COMPILE_LOG_PATH) as log_file:
            error = error or log_file.read()[-500:]
        except OSError:
          error = error or f"exit code {result.returncode if result is not None else 'unknown'}"
        self._set_compile_failed(model_name, error)

    threading.Thread(target=worker, daemon=True).start()

  def _car_options(self) -> list[str]:
    options: list[str] = []

    def add_options(car_names) -> None:
      for car_name in car_names:
        option = str(car_name)
        if option and option not in options:
          options.append(option)

    try:
      add_options(ui_state.sm["carState"].carSCustom.supportedCars)
    except Exception:
      pass

    if options:
      custom_params = read_custom_param_map(self._params)
      custom_params["SupportCars"] = options
      self._params.put("CustomParam", json.dumps(custom_params, separators=(",", ":"), sort_keys=True))

    support_cars = read_custom_param_map(self._params).get("SupportCars", [])
    if isinstance(support_cars, list):
      add_options(support_cars)

    cp_bytes = self._params.get("CarParamsPersistent")
    if cp_bytes is not None:
      try:
        cp = messaging.log_from_bytes(cp_bytes, car.CarParams)
        if cp.carFingerprint:
          add_options([cp.carFingerprint])
      except Exception:
        pass

    return options or ["MOCK"]

  def show_event(self):
    super().show_event()
    if self._current_tab == "Navigation":
      self._refresh_speed_camera_region_counts()
    self._scrollers[self._current_tab].show_event()

  def hide_event(self):
    super().hide_event()
    self._scrollers[self._current_tab].hide_event()

  def _render(self, rect: rl.Rectangle):
    scroller_rect = rl.Rectangle(rect.x, rect.y + TAB_HEIGHT + TAB_GAP, rect.width, rect.height - TAB_HEIGHT - TAB_GAP)
    self._scrollers[self._current_tab].render(scroller_rect)
    self._draw_tabs(rect)

  def _draw_tabs(self, rect: rl.Rectangle):
    self._tab_rects.clear()
    tab_names = list(self._sections.keys())
    tab_w = (rect.width - TAB_GAP * (len(tab_names) - 1)) / len(tab_names)
    mouse_pos = rl.get_mouse_position()

    for idx, name in enumerate(tab_names):
      tab_rect = rl.Rectangle(rect.x + idx * (tab_w + TAB_GAP), rect.y, tab_w, TAB_HEIGHT)
      self._tab_rects[name] = tab_rect
      selected = name == self._current_tab
      pressed = self.is_pressed and rl.check_collision_point_rec(mouse_pos, tab_rect)
      color = TAB_SELECTED if selected else (TAB_PRESSED if pressed else TAB_NORMAL)
      text_color = TAB_TEXT_SELECTED if selected else TAB_TEXT

      rl.draw_rectangle_rounded(tab_rect, TAB_RADIUS, 12, color)
      rl.draw_rectangle_rounded_lines_ex(tab_rect, TAB_RADIUS, 12, 2, TAB_BORDER)
      label = tr(name)
      font_size = TAB_FONT_SIZE
      text_size = measure_text_cached(self._tab_font, label, font_size)
      while text_size.x > tab_rect.width - 20 and font_size > TAB_FONT_MIN_SIZE:
        font_size -= 2
        text_size = measure_text_cached(self._tab_font, label, font_size)
      text_pos = rl.Vector2(tab_rect.x + (tab_rect.width - text_size.x) / 2,
                            tab_rect.y + (tab_rect.height - text_size.y) / 2)
      rl.draw_text_ex(self._tab_font, label, text_pos, font_size, 0, text_color)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    for name, tab_rect in self._tab_rects.items():
      if rl.check_collision_point_rec(mouse_pos, tab_rect):
        if name != self._current_tab:
          self._scrollers[self._current_tab].hide_event()
          self._current_tab = name
          if self._current_tab == "Navigation":
            self._refresh_speed_camera_region_counts()
          self._scrollers[self._current_tab].show_event()
        return
# #custom end
