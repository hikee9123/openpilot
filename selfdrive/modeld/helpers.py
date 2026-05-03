import json
import os
from dataclasses import dataclass
from pathlib import Path

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

MODELS_DIR = Path(__file__).resolve().parent / 'models'
COMPILED_FLAGS_PATH = MODELS_DIR / 'tg_compiled_flags.json'
SUPERCOMBOS_DIR = MODELS_DIR / 'supercombos'


def set_tinygrad_backend_from_compiled_flags() -> None:
  if os.path.isfile(COMPILED_FLAGS_PATH):
    with open(COMPILED_FLAGS_PATH) as f:
      os.environ['DEV'] = str(json.load(f)['DEV'])


@dataclass
class CompileConfig:
  cam_w: int
  cam_h: int
  prepare_only: bool
  prefix: str
  base_dir: Path = MODELS_DIR

  @property
  def pkl_path(self):
    return str(self.base_dir / f'{self.prefix}{"warp_" if self.prepare_only else ""}{self.cam_w}x{self.cam_h}_tinygrad.pkl')

  @property
  def nv12(self):
    return (self.cam_w, self.cam_h, *get_nv12_info(self.cam_w, self.cam_h))


# #custom start: ActiveModelName bundle selection
def selected_model_dir(cam_w: int, cam_h: int) -> Path:
  raw_name = Params().get("ActiveModelName")
  if raw_name is None:
    return MODELS_DIR

  model_name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
  if not model_name or model_name == "1.default":
    return MODELS_DIR

  candidate = SUPERCOMBOS_DIR / model_name
  required = [
    candidate / "driving_vision_metadata.pkl",
    candidate / "driving_policy_metadata.pkl",
    Path(CompileConfig(cam_w, cam_h, False, "driving_", candidate).pkl_path),
    Path(CompileConfig(cam_w, cam_h, True, "driving_", candidate).pkl_path),
  ]
  if candidate.is_dir() and all(path.exists() for path in required):
    cloudlog.warning(f"[custom modeld] using ActiveModelName={model_name}")
    return candidate

  missing = [str(path.name) for path in required if not path.exists()]
  cloudlog.warning(f"[custom modeld] ActiveModelName={model_name} incomplete, using default model. missing={missing}")
  return MODELS_DIR
# #custom end
