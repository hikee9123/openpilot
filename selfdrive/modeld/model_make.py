#!/usr/bin/env python3
import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

# tinygrad ContextVar int envs can be poisoned by launch shells (for example DEBUG=release).
for env_key in ("DEBUG", "BEAM", "NOOPT"):
  try:
    int(os.environ.get(env_key, "0"))
  except ValueError:
    os.environ.pop(env_key, None)

MODELD_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODELD_DIR.parents[1]
TINYGRAD_DIR = REPO_ROOT / "tinygrad_repo"
for import_path in (str(REPO_ROOT), str(TINYGRAD_DIR)):
  if import_path not in sys.path:
    sys.path.insert(0, import_path)

from tinygrad import Device

from openpilot.common.file_chunker import chunk_file, get_chunk_paths
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.common.transformations.camera import _ar_ox_fisheye, _os_fisheye
from openpilot.common.transformations.model import MEDMODEL_INPUT_SIZE
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.modeld.helpers import CompileConfig, compiled_artifact_exists


# #custom start: compile selected supercombo bundle for current modeld
MODELS_DIR = MODELD_DIR / "models"
SUPERCOMBOS_DIR = MODELS_DIR / "supercombos"
COMPILED_FLAGS_PATH = MODELS_DIR / "tg_compiled_flags.json"
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
]
DEFAULT_MODEL_NAMES = {"1.Stock_Model"}
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
CAMERA_CONFIGS = [
  (_ar_ox_fisheye.width, _ar_ox_fisheye.height),
  (_os_fisheye.width, _os_fisheye.height),
]


def estimate_pickle_max_size(onnx_size: int) -> int:
  return int(1.2 * onnx_size + 10 * 1024 * 1024)


def device_available(device: str) -> bool:
  try:
    return Device[device].device == device
  except Exception:
    return False


def tinygrad_flags() -> str:
  dev = ""
  if device_available("CUDA"):
    dev = "CUDA"
  elif device_available("QCOM"):
    dev = "QCOM"

  if COMPILED_FLAGS_PATH.exists():
    try:
      compiled_dev = str(json.loads(COMPILED_FLAGS_PATH.read_text()).get("DEV", ""))
      if compiled_dev in ("CUDA", "QCOM") and device_available(compiled_dev):
        dev = compiled_dev
      elif compiled_dev.startswith("CPU") and not dev:
        dev = compiled_dev
    except Exception:
      pass

  if not dev:
    dev = "CPU" if platform.system() == "Darwin" else "CPU:LLVM"

  if dev == "QCOM":
    return "DEV=QCOM IMAGE=1 FLOAT16=1 NOLOCALS=1 JIT_BATCH_SIZE=0 OPENPILOT_HACKS=1"
  return f"DEV={dev}"


def selected_model_name(arg_name: str | None) -> str:
  if arg_name:
    return arg_name

  raw = Params().get("ActiveModelName")
  name = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw or "")
  if not name or name in DEFAULT_MODEL_NAMES:
    raise ValueError("ActiveModelName is default. Select a custom model first.")
  return name


def set_compile_status(status: str, model_name: str, error: str = "") -> None:
  params = Params()
  params.put(COMPILE_STATUS_KEY, status)
  params.put(COMPILE_NAME_KEY, model_name)
  if status == STATUS_RUNNING:
    params.put(COMPILE_STARTED_AT_KEY, str(int(time.time())))
    params.put(COMPILE_FINISHED_AT_KEY, "")
    params.put(COMPILE_PROGRESS_KEY, 0)
  if status in (STATUS_SUCCESS, STATUS_FAILED):
    params.put(COMPILE_FINISHED_AT_KEY, str(int(time.time())))
    progress = params.get(COMPILE_PROGRESS_KEY)
    progress_value = int(progress or 0)
    params.put(COMPILE_PROGRESS_KEY, 100 if status == STATUS_SUCCESS else progress_value)
  params.put(COMPILE_ERROR_KEY, error[-500:])


def set_compile_progress(progress: int) -> None:
  Params().put(COMPILE_PROGRESS_KEY, max(0, min(100, progress)))


def run(command: list[str], env: dict[str, str]) -> None:
  cloudlog.warning(f"[custom model_make] {' '.join(command)}")
  subprocess.run(command, cwd=MODELD_DIR, env=env, check=True)


def ensure_metadata(model_dir: Path, env: dict[str, str]) -> None:
  for name in ("driving_vision", "driving_policy"):
    onnx = model_dir / f"{name}.onnx"
    metadata = model_dir / f"{name}_metadata.pkl"
    if not onnx.exists():
      raise FileNotFoundError(onnx)
    if not metadata.exists() or onnx.stat().st_mtime >= metadata.stat().st_mtime:
      run([sys.executable, str(MODELD_DIR / "get_model_metadata.py"), str(onnx)], env)


def compile_bundle(model_dir: Path, env: dict[str, str]) -> None:
  model_w, model_h = MEDMODEL_INPUT_SIZE
  frame_skip = ModelConstants.MODEL_RUN_FREQ // ModelConstants.MODEL_CONTEXT_FREQ
  onnx_size = (model_dir / "driving_vision.onnx").stat().st_size + (model_dir / "driving_policy.onnx").stat().st_size

  for cam_w, cam_h in CAMERA_CONFIGS:
    for prepare_only in (False, True):
      cfg = CompileConfig(cam_w, cam_h, prepare_only, "driving_", model_dir)
      pkl_path = Path(cfg.pkl_path)
      chunk_targets = get_chunk_paths(str(pkl_path), estimate_pickle_max_size(onnx_size))

      if compiled_artifact_exists(pkl_path):
        cloudlog.warning(f"[custom model_make] already compiled: {pkl_path}")
        set_compile_progress(30 + (CAMERA_CONFIGS.index((cam_w, cam_h)) * 2 + int(prepare_only) + 1) * 15)
        continue

      run([
        sys.executable, str(MODELD_DIR / "compile_modeld.py"),
        "--model-size", f"{model_w}x{model_h}",
        "--nv12", ",".join(str(x) for x in cfg.nv12),
        "--vision-onnx", str(model_dir / "driving_vision.onnx"),
        "--policy-onnx", str(model_dir / "driving_policy.onnx"),
        "--output", str(pkl_path),
        "--frame-skip", str(frame_skip),
        *(["--prepare-only"] if prepare_only else []),
      ], env)
      chunk_file(str(pkl_path), chunk_targets)
      set_compile_progress(30 + (CAMERA_CONFIGS.index((cam_w, cam_h)) * 2 + int(prepare_only) + 1) * 15)


def main() -> None:
  parser = argparse.ArgumentParser(description="Compile a custom supercombo bundle for current modeld.")
  parser.add_argument("--model", choices=MODEL_OPTIONS, default=None)
  args = parser.parse_args()

  model_name = selected_model_name(args.model)
  model_dir = SUPERCOMBOS_DIR / model_name
  if not model_dir.is_dir():
    raise FileNotFoundError(model_dir)

  env = os.environ.copy()
  env["PYTHONUNBUFFERED"] = "1"
  python_paths = [str(REPO_ROOT), str(TINYGRAD_DIR)]
  if env.get("PYTHONPATH"):
    python_paths.append(env["PYTHONPATH"])
  env["PYTHONPATH"] = os.pathsep.join(python_paths)
  for flag in tinygrad_flags().split():
    key, value = flag.split("=", 1)
    env[key] = value

  cloudlog.warning(f"[custom model_make] compile {model_name} in {model_dir}")
  set_compile_status(STATUS_RUNNING, model_name)
  try:
    set_compile_progress(5)
    ensure_metadata(model_dir, env)
    set_compile_progress(30)
    compile_bundle(model_dir, env)
  except Exception as e:
    set_compile_status(STATUS_FAILED, model_name, str(e))
    raise
  set_compile_status(STATUS_SUCCESS, model_name)
  cloudlog.warning(f"[custom model_make] done {model_name}")


if __name__ == "__main__":
  main()
# #custom end
