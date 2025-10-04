#!/usr/bin/env python3
import os
from openpilot.system.hardware import TICI
os.environ['DEV'] = 'QCOM' if TICI else 'LLVM'
USBGPU = "USBGPU" in os.environ
if USBGPU:
  os.environ['DEV'] = 'AMD'
  os.environ['AMD_IFACE'] = 'USB'

import subprocess
from pathlib import Path
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from typing import Optional, Dict


MODELS_DIR = Path(__file__).parent / "models"

VISION_PKL_PATH = MODELS_DIR / "driving_vision_tinygrad.pkl"
POLICY_PKL_PATH = MODELS_DIR / "driving_policy_tinygrad.pkl"
VISION_METADATA_PATH = MODELS_DIR / "driving_vision_metadata.pkl"
POLICY_METADATA_PATH = MODELS_DIR / "driving_policy_metadata.pkl"



SUPERCOMBOS_DIR = MODELS_DIR / "supercombos"

VISION_ONNX = "driving_vision.onnx"
POLICY_ONNX = "driving_policy.onnx"
VISION_META = "driving_vision_metadata.pkl"
POLICY_META = "driving_policy_metadata.pkl"
VISION_PKL  = "driving_vision_tinygrad.pkl"
POLICY_PKL  = "driving_policy_tinygrad.pkl"




def _comma_default_paths() -> Dict[str, Path]:
  """comma 기본 PATH를 그대로 사용 (상수 4개 + models/*.onnx)"""
  vis_onnx = Path(__file__).parent / 'models' / VISION_ONNX
  pol_onnx = Path(__file__).parent / 'models' / POLICY_ONNX
  return {
    'vision_onnx': vis_onnx,
    'policy_onnx': pol_onnx,
    'vision_meta': VISION_METADATA_PATH,
    'policy_meta': POLICY_METADATA_PATH,
    'vision_pkl':  VISION_PKL_PATH,
    'policy_pkl':  POLICY_PKL_PATH,
  }


def _stale(meta: Path, onnx: Path) -> bool:
  return (not meta.exists()) or (onnx.stat().st_mtime > meta.stat().st_mtime)


def _ensure_metadata_generated(onnx_path: Path, meta_path: Path) -> None:
  script = Path(__file__).parent / 'get_model_metadata.py'
  if not script.exists():
    msg = f"Metadata script not found: {script}"
    cloudlog.error(f"[modeld] {msg}")
    raise FileNotFoundError(msg)

  cloudlog.warning(f"[modeld] Generating metadata for {onnx_path.name}")


  cmd = ["python3", str(script), str(onnx_path)]
  res = subprocess.run(cmd, cwd=Path(__file__).parent, capture_output=True, text=True)
  if res.returncode != 0:
    msg = f"Metadata generation failed\ncmd: {' '.join(cmd)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    cloudlog.error(f"[modeld] {msg}")
    raise RuntimeError(msg)


  if not meta_path.exists():
    msg = f"Metadata file not created: {meta_path}"
    cloudlog.error(f"[modeld] {msg}")
    raise RuntimeError(msg)

  cloudlog.warning(f"meta OK: {meta_path}")


def _ensure_pkl_and_metadata(onnx_path: Path, pkl_path: Path, meta_path: Path) -> None:
  """
  - 메타데이터(pkl)가 없거나 ONNX보다 오래되었으면 생성 (get_model_metadata.py)
  - tinygrad 실행 pkl이 없거나 ONNX보다 오래되었으면 tinygrad_repo의 compile3.py로 생성
  """
  # 1) 메타 보장 (이미 있으나 여기서도 방어적으로)
  if _stale(meta_path, onnx_path):
    _ensure_metadata_generated(onnx_path, meta_path)

  # 2) tinygrad pkl 보장
  if (not pkl_path.exists()) or (onnx_path.stat().st_mtime > pkl_path.stat().st_mtime):
    # tinygrad_repo 위치 추정
    base_candidates = [
      Path(__file__).resolve().parents[2] / "tinygrad_repo",
      Path(__file__).resolve().parents[1] / "tinygrad_repo",
      Path.cwd() / "tinygrad_repo",
    ]
    compile3 = None
    for base in base_candidates:
      cand = base / "examples" / "openpilot" / "compile3.py"
      if cand.exists():
        compile3 = cand
        break
    if compile3 is None:
      raise FileNotFoundError("tinygrad_repo/examples/openpilot/compile3.py file not finded.")

    # 환경 플래그 (기본 CPU/LLVM; 필요시 DEV=QCOM/AMD 등으로 조정)
    flags = os.environ.get("TG_FLAGS", "DEV=LLVM IMAGE=0")
    # PYTHONPATH에 tinygrad_repo 추가
    env = os.environ.copy()
    env["PYTHONPATH"] = env.get("PYTHONPATH", "") + os.pathsep + str(compile3.parents[2])

    cmd = f'{flags} python3 "{compile3}" "{onnx_path}" "{pkl_path}"'
    res = subprocess.run(cmd, shell=True, cwd=Path(__file__).parent, capture_output=True, text=True, env=env)
    if res.returncode != 0:
      err = f"tinygrad pkl build failed\ncmd: {cmd}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
      cloudlog.error(f"[modeld] {err}")
      raise RuntimeError(err)

    if not pkl_path.exists():
      err = f"pkl not created: {pkl_path}"
      cloudlog.error(f"[modeld] {err}")
      raise RuntimeError(err)

    cloudlog.warning(f"pkl OK: {pkl_path}")




def _resolve_onnx_only_paths(model_dir: Path) -> Dict[str, Path]:
  """
  주어진 model_dir에서 ONNX/메타/PKL을 확인/생성한다.
  - 어떤 단계에서라도 예외가 발생하면 comma 기본 PATH로 폴백한다.
  """
  try:
    vis_onnx = model_dir / VISION_ONNX
    pol_onnx = model_dir / POLICY_ONNX
    if not vis_onnx.exists() or not pol_onnx.exists():
      raise FileNotFoundError(f"[{model_dir}] Missing ONNX files: {VISION_ONNX}, {POLICY_ONNX} are required")

    cloudlog.warning(f"[modeld] ONNX found: vision={vis_onnx}, policy={pol_onnx}")

    vis_meta = model_dir / VISION_META
    pol_meta = model_dir / POLICY_META
    vis_pkl  = model_dir / VISION_PKL
    pol_pkl  = model_dir / POLICY_PKL

    # 메타 갱신
    if _stale(vis_meta, vis_onnx):
      _ensure_metadata_generated(vis_onnx, vis_meta)
    if _stale(pol_meta, pol_onnx):
      _ensure_metadata_generated(pol_onnx, pol_meta)

    # pkl 갱신
    if _stale(vis_pkl, vis_onnx):
      _ensure_pkl_and_metadata(vis_onnx, vis_pkl, vis_meta)
    if _stale(pol_pkl, pol_onnx):
      _ensure_pkl_and_metadata(pol_onnx, pol_pkl, pol_meta)

    return {
      'vision_onnx': vis_onnx,
      'policy_onnx': pol_onnx,
      'vision_meta': vis_meta,
      'policy_meta': pol_meta,
      'vision_pkl':  vis_pkl,
      'policy_pkl':  pol_pkl,
    }

  except Exception as e:
    # 어떤 오류든 comma 기본 PATH로 폴백
    cloudlog.error(f"[modeld] _resolve_onnx_only_paths failed for {model_dir}: {e}. Falling back to comma default PATH.")
    paths = _comma_default_paths()
    return paths




def _choose_model_dir_from_params_only() -> Optional[Path]:
  """ActiveModelName 번들을 찾으면 Path, 아니면 None"""
  try:
    pname = Params().get("ActiveModelName")
    if pname:
      pname = pname.decode() if isinstance(pname, (bytes, bytearray)) else pname
      bundle = SUPERCOMBOS_DIR / pname
      if bundle.exists():
        cloudlog.warning(f"[modeld] ActiveModelName='{pname}' -> {bundle}")
        return bundle
      cloudlog.error(f"[modeld] supercombos/{pname} not found.")
  except Exception as e:
    cloudlog.error(f"[modeld] reading ActiveModelName failed: {e}")
  return None



def choose_model_from_params() -> Dict[str, Path]:
  cloudlog.warning("choose_model_from_params")
  bundle_dir = _choose_model_dir_from_params_only()
  if bundle_dir is not None and bundle_dir.exists():
    cloudlog.warning(f"[modeld] bundle_dir = {bundle_dir}")
    return _resolve_onnx_only_paths(bundle_dir)

  cloudlog.warning("[modeld] fallback to comma default PATH constants")
  return _comma_default_paths()




def main(demo=False):
  paths = choose_model_from_params()
  cloudlog.warning(f"modeld paths : {paths}")


if __name__ == "__main__":
  try:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='A boolean for demo mode.')
    args = parser.parse_args()
    main(demo=args.demo)
  except KeyboardInterrupt:
    cloudlog.warning("got SIGINT")
