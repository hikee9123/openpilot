import importlib.util
import sys
import types
from pathlib import Path


def _load_navid_module():
  repo_root = Path(__file__).resolve().parents[2]

  import selfdrive.navd.speed_camera as speed_camera

  cereal = sys.modules.setdefault("cereal", types.ModuleType("cereal"))
  messaging = types.ModuleType("cereal.messaging")
  messaging.PubMaster = object
  messaging.SubMaster = object
  messaging.new_message = lambda *args, **kwargs: None
  cereal.messaging = messaging
  sys.modules["cereal.messaging"] = messaging

  sys.modules.setdefault("openpilot", types.ModuleType("openpilot"))
  sys.modules.setdefault("openpilot.common", types.ModuleType("openpilot.common"))

  realtime = types.ModuleType("openpilot.common.realtime")
  realtime.Ratekeeper = object
  sys.modules["openpilot.common.realtime"] = realtime

  swaglog = types.ModuleType("openpilot.common.swaglog")
  swaglog.cloudlog = types.SimpleNamespace(exception=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
  sys.modules["openpilot.common.swaglog"] = swaglog

  sys.modules.setdefault("openpilot.selfdrive", types.ModuleType("openpilot.selfdrive"))
  sys.modules.setdefault("openpilot.selfdrive.navd", types.ModuleType("openpilot.selfdrive.navd"))
  sys.modules["openpilot.selfdrive.navd.speed_camera"] = speed_camera

  ui_custom = types.ModuleType("openpilot.selfdrive.ui.custom")
  ui_custom.read_custom_params = lambda: {}
  sys.modules.setdefault("openpilot.selfdrive.ui", types.ModuleType("openpilot.selfdrive.ui"))
  sys.modules["openpilot.selfdrive.ui.custom"] = ui_custom

  spec = importlib.util.spec_from_file_location("navid_test_module", repo_root / "selfdrive" / "navd" / "navid.py")
  assert spec is not None and spec.loader is not None
  navid = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = navid
  spec.loader.exec_module(navid)
  return navid


def test_format_camera_debug_text_includes_current_road_and_candidates() -> None:
  navid = _load_navid_module()
  camera = types.SimpleNamespace(
    camera_category="SPEED",
    camera_type_code=1,
    distance_m=180.0,
    relative_angle_deg=8.0,
    local_road_match=True,
    is_expressway=True,
  )

  assert navid._format_camera_debug_text([camera], "Current Road").splitlines() == [
    "ROAD Current Road",
    "1 SPD 180m +8 O R",
  ]


def test_format_debug_road_name_truncates_long_names() -> None:
  navid = _load_navid_module()
  road_line = navid._format_debug_road_name("1234567890123456789012345")

  assert road_line == "ROAD 1234567890123456789..."
