#!/usr/bin/env python3
import os
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params

# ----------------------------
# Constants / Paths
# ----------------------------
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

# 결정성(비결정적 해싱 등) 줄이기
os.environ.setdefault("PYTHONHASHSEED", "0")

# ----------------------------
# Helpers
# ----------------------------
def _parse_flags_to_env(flags: str) -> Dict[str, str]:
  """'DEV=LLVM IMAGE=0' → {'DEV':'LLVM','IMAGE':'0'}"""
  d: Dict[str, str] = {}
  if not flags:
    return d
  for tok in flags.split():
    if "=" in tok:
      k, v = tok.split("=", 1)
      if k:
        d[k] = v
  return d


def _run_subprocess(args: list[str], cwd: Path, extra_env: Dict[str, str] | None = None) -> subprocess.CompletedProcess:
  """shell=False + 리스트 인자 방식으로 안전 실행"""
  env = os.environ.copy()
  if extra_env:
    env.update(extra_env)
  cloudlog.warning(f"[modeld.subprocess] cwd={cwd} args={args} env_overrides={list((extra_env or {}).keys())}")
  return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env, shell=False)


def _comma_default_paths() -> Dict[str, Path]:
  """comma 기본 PATH 반환"""
  vis_onnx = MODELS_DIR / VISION_ONNX
  pol_onnx = MODELS_DIR / POLICY_ONNX
  return {
    'vision_onnx': vis_onnx,
    'policy_onnx': pol_onnx,
    'vision_meta': VISION_METADATA_PATH,
    'policy_meta': POLICY_METADATA_PATH,
    'vision_pkl':  VISION_PKL_PATH,
    'policy_pkl':  POLICY_PKL_PATH,
  }


def _stale(target: Path, onnx: Path) -> bool:
  """target이 없거나 ONNX가 더 최신이면 True"""
  return (not target.exists()) or (onnx.stat().st_mtime > target.stat().st_mtime)



# ----------------------------
# Generators
# ----------------------------
def _ensure_metadata_generated(onnx_path: Path, meta_path: Path) -> None:
  """ONNX가 더 최신이거나 메타가 없으면 메타 재생성 + ✅ 메타 가드"""
  if meta_path.exists() and meta_path.stat().st_mtime > onnx_path.stat().st_mtime:
    return

  script = Path(__file__).parent / 'get_model_metadata.py'
  if not script.exists():
    msg = f"Metadata script not found: {script}"
    cloudlog.error(msg)
    raise FileNotFoundError(msg)

  # 생성
  res = _run_subprocess(["python3", str(script), str(onnx_path)], cwd=Path(__file__).parent)
  if res.returncode != 0:
    msg = (
      f"Metadata generation failed\n"
      f"cmd: python3 {script} {onnx_path}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
    cloudlog.error(msg)
    raise RuntimeError(msg)

  if not meta_path.exists():
    raise RuntimeError(f"Metadata file not created: {meta_path}")

  cloudlog.warning(f"meta OK: {meta_path}")


def _ensure_pkl_and_metadata(onnx_path: Path, pkl_path: Path, meta_path: Path) -> None:
  """
  - 메타: stale이면 재생성(+검증)
  - PKL: stale이면 compile3.py로 생성(+사이즈 가드)
  """
  # 1) 메타 보장
  if (not meta_path.exists()) or (onnx_path.stat().st_mtime >= meta_path.stat().st_mtime):
    _ensure_metadata_generated(onnx_path, meta_path)


  # tinygrad_repo 탐색 (추가 파일 의존성/스캔 없음)
  base_candidates = [
    Path(__file__).resolve().parents[2] / "tinygrad_repo",
    Path(__file__).resolve().parents[1] / "tinygrad_repo",
    Path.cwd() / "tinygrad_repo",
  ]
  compile3 = None
  tinyroot = None
  for base in base_candidates:
    cand = base / "examples" / "openpilot" / "compile3.py"
    if cand.exists():
      compile3, tinyroot = cand, base
      break
  if compile3 is None:
    raise FileNotFoundError("tinygrad_repo/examples/openpilot/compile3.py file not found.")

  # ENV 주입 (프리픽스 X)
  flags = os.environ.get("TG_FLAGS", "DEV=LLVM IMAGE=0")  # 필요시 한 곳에서만 조절
  env = os.environ.copy()
  env["PYTHONPATH"] = env.get("PYTHONPATH", "") + os.pathsep + str(tinyroot)
  env.update(_parse_flags_to_env(flags))

  # 실행
  args = ["python3", str(compile3), str(onnx_path), str(pkl_path)]
  res = _run_subprocess(args, cwd=Path(__file__).parent, extra_env=env)
  if res.returncode != 0:
    err = (
      f"tinygrad pkl build failed\n"
      f"cmd: {' '.join(args)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
    cloudlog.error(err)
    raise RuntimeError(err)

  if not pkl_path.exists():
    raise RuntimeError(f"pkl not created: {pkl_path}")


  cloudlog.warning(f"pkl OK: {pkl_path}")


# ----------------------------
# Path Resolution
# ----------------------------
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

    vis_meta = model_dir / VISION_META
    pol_meta = model_dir / POLICY_META
    vis_pkl  = model_dir / VISION_PKL
    pol_pkl  = model_dir / POLICY_PKL

    # 메타 갱신(+검증)
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
    cloudlog.error(f"[modeld.resolve] _resolve_onnx_only_paths failed for {model_dir}: {e}. Falling back to comma default PATH.")
    return _comma_default_paths()


def _choose_model_dir_from_params_only() -> Optional[Path]:
  """ActiveModelName 번들을 찾으면 Path, 아니면 None"""
  try:
    pname = Params().get("ActiveModelName")
    if not pname:
      return None
    pname = pname.decode() if isinstance(pname, (bytes, bytearray)) else pname
    if pname == "1.default":
      cloudlog.warning("[modeld.params] ActiveModelName='1.default', using comma default PATH")
      return None
    bundle = SUPERCOMBOS_DIR / pname
    if bundle.exists():
      cloudlog.warning(f"[modeld.params] ActiveModelName='{pname}', bundle_dir={bundle}")
      return bundle
    cloudlog.error(f"[modeld.params] supercombos/{pname} not found.")
  except Exception as e:
    cloudlog.error(f"[modeld.params] reading ActiveModelName failed: {e}")
  return None


# ----------------------------
# Public APIs
# ----------------------------
def choose_model_from_params() -> Dict[str, Path]:
  """
  번들 존재 & 요구 파일 4종(meta 2, pkl 2)이 다 있으면 그대로 사용,
  아니면 comma 기본 경로 사용
  """
  cloudlog.warning("[modeld] choose_model_from_params")
  bundle_dir = _choose_model_dir_from_params_only()

  if not bundle_dir:
    paths = _comma_default_paths()
    return paths

  # 필요한 4종이 모두 존재하는지 빠르게 체크
  vis_meta = bundle_dir / VISION_META
  pol_meta = bundle_dir / POLICY_META
  vis_pkl  = bundle_dir / VISION_PKL
  pol_pkl  = bundle_dir / POLICY_PKL
  required_ok = all(p.exists() for p in (vis_meta, pol_meta, vis_pkl, pol_pkl))
  if not required_ok:
    cloudlog.warning(f"[modeld] missing artifacts in {bundle_dir}, fallback to comma defaults")
    return _comma_default_paths()

  # 최종 경로 구성
  vis_onnx = bundle_dir / VISION_ONNX
  pol_onnx = bundle_dir / POLICY_ONNX
  if not vis_onnx.exists() or not pol_onnx.exists():
    cloudlog.warning(f"[modeld] missing onnx in {bundle_dir}, fallback to comma defaults")
    return _comma_default_paths()


  paths = {
    'vision_onnx': vis_onnx,
    'policy_onnx': pol_onnx,
    'vision_meta': vis_meta,
    'policy_meta': pol_meta,
    'vision_pkl':  vis_pkl,
    'policy_pkl':  pol_pkl,
  }
  cloudlog.warning(f"[modeld]  OK: {paths}")
  return paths


def compile_model_from_params() -> Dict[str, Path]:
  """
  번들이 있으면 해당 번들에서 onnx/meta/pkl을 확인/필요 시 생성 후 반환,
  없으면 comma defaults 반환
  """
  cloudlog.warning("[modeld] compile_model_from_params")
  bundle_dir = _choose_model_dir_from_params_only()

  if bundle_dir and bundle_dir.exists():
    paths = _resolve_onnx_only_paths(bundle_dir)
    cloudlog.warning(f"[modeld] compile OK: {paths}")
    return paths

  paths = _comma_default_paths()
  cloudlog.warning(f"[modeld] compile fallback -> comma defaults: {paths}")
  return paths

# ----------------------------
# CLI
# ----------------------------
def main(demo: bool = False):
  # 현재 목적상 demo 플래그는 경로 선택에 영향 주지 않음
  compile_model_from_params()


if __name__ == "__main__":
  try:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='A boolean for demo mode.')
    args = parser.parse_args()
    main(demo=args.demo)
  except KeyboardInterrupt:
    cloudlog.warning("got SIGINT")
