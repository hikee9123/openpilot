import json
import os
from dataclasses import dataclass
from pathlib import Path

from openpilot.common.file_chunker import get_chunk_name, get_manifest_path
from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

MODELS_DIR = Path(__file__).resolve().parent / 'models'
COMPILED_FLAGS_PATH = MODELS_DIR / 'tg_compiled_flags.json'
SUPERCOMBOS_DIR = MODELS_DIR / 'supercombos'
DEFAULT_MODEL_NAMES = {"1.Stock_Model", "1.default", "7.Current_Model", "7.Current_0.11_6a7d09ad"}


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
def compiled_artifact_exists(path: Path) -> bool:
  if path.is_file():
    return True

  manifest_path = Path(get_manifest_path(str(path)))
  if not manifest_path.is_file():
    return False

  try:
    num_chunks = int(manifest_path.read_text().strip())
  except (OSError, ValueError):
    return False

  if num_chunks <= 0:
    return False

  return all(Path(get_chunk_name(str(path), i, num_chunks)).is_file() for i in range(num_chunks))


def selected_model_dir(cam_w: int, cam_h: int) -> Path:
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog

  raw_name = Params().get("ActiveModelName")
  if raw_name is None:
    return MODELS_DIR

  model_name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
  if not model_name or model_name in DEFAULT_MODEL_NAMES:
    return MODELS_DIR

  candidate = SUPERCOMBOS_DIR / model_name
  metadata_paths = [
    candidate / "driving_vision_metadata.pkl",
    candidate / "driving_policy_metadata.pkl",
  ]
  compiled_paths = [
    Path(CompileConfig(cam_w, cam_h, False, "driving_", candidate).pkl_path),
    Path(CompileConfig(cam_w, cam_h, True, "driving_", candidate).pkl_path),
  ]
  if candidate.is_dir() and all(path.exists() for path in metadata_paths) and all(compiled_artifact_exists(path) for path in compiled_paths):
    cloudlog.warning(f"[custom modeld] using ActiveModelName={model_name}")
    return candidate

  missing = [str(path.name) for path in metadata_paths if not path.exists()]
  missing += [str(path.name) for path in compiled_paths if not compiled_artifact_exists(path)]
  cloudlog.warning(f"[custom modeld] ActiveModelName={model_name} incomplete, using default model. missing={missing}")
  return MODELS_DIR
# #custom end
