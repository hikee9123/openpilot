#!/usr/bin/env python3
import os
import time
import pickle
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

import numpy as np

from openpilot.system.hardware import TICI
os.environ['DEV'] = 'QCOM' if TICI else 'LLVM'
USBGPU = "USBGPU" in os.environ
if USBGPU:
  os.environ['DEV'] = 'AMD'
  os.environ['AMD_IFACE'] = 'USB'

from tinygrad.tensor import Tensor
from tinygrad.dtype import dtypes
from tinygrad.helpers import fetch
from examples.benchmark_onnx import load_onnx_model

import cereal.messaging as messaging
from cereal import car, log
from cereal.messaging import PubMaster, SubMaster
from msgq.visionipc import VisionIpcClient, VisionStreamType, VisionBuf
from opendbc.car.car_helpers import get_demo_car_params
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import config_realtime_process, DT_MDL
from openpilot.common.transformations.camera import DEVICE_CAMERAS
from openpilot.common.transformations.model import get_warp_matrix
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
from openpilot.selfdrive.controls.lib.drive_helpers import get_accel_from_plan, smooth_value, get_curvature_from_plan
from openpilot.selfdrive.modeld.parse_model_outputs import Parser
from openpilot.selfdrive.modeld.fill_model_msg import fill_model_msg, fill_pose_msg, PublishState
from openpilot.selfdrive.modeld.constants import ModelConstants, Plan
from openpilot.selfdrive.modeld.models.commonmodel_pyx import DrivingModelFrame, CLContext
from openpilot.selfdrive.modeld.runners.tinygrad_helpers import qcom_tensor_from_opencl_address

PROCESS_NAME = "selfdrive.modeld.modeld"
SEND_RAW_PRED = os.getenv('SEND_RAW_PRED')

# 기준 경로 고정: selfdrive/modeld/models/supercombos
PROCESS_ROOT = Path(__file__).parent
SUPERCOMBOS_DIR = PROCESS_ROOT / "models" / "supercombos"

LAT_SMOOTH_SECONDS = 0.1
LONG_SMOOTH_SECONDS = 0.3
MIN_LAT_CONTROL_SPEED = 0.3

VISION_ONNX = "driving_vision.onnx"
POLICY_ONNX = "driving_policy.onnx"
VISION_META = "driving_vision_metadata.pkl"
POLICY_META = "driving_policy_metadata.pkl"

# =========================
# supercombos 선택 로직 (ActiveModelName만)
# =========================
def _list_available_bundles() -> List[str]:
  out: List[str] = []
  if SUPERCOMBOS_DIR.exists():
    for d in sorted(p for p in SUPERCOMBOS_DIR.iterdir() if p.is_dir()):
      if (d / VISION_ONNX).exists() and (d / POLICY_ONNX).exists():
        out.append(d.name)
  return out

def _auto_default_bundle_dir() -> Path:
  c1 = SUPERCOMBOS_DIR / "1.big_driving"
  if (c1 / VISION_ONNX).exists() and (c1 / POLICY_ONNX).exists():
    return c1
  c2 = SUPERCOMBOS_DIR / "default"
  if (c2 / VISION_ONNX).exists() and (c2 / POLICY_ONNX).exists():
    return c2
  bundles = _list_available_bundles()
  if bundles:
    return SUPERCOMBOS_DIR / bundles[0]
  # supercombos가 비어있다면 그대로 반환(후속 단계에서 에러)
  return SUPERCOMBOS_DIR

def _choose_model_dir_from_params_only() -> Path:
  """
  오직 Params('ActiveModelName')만 사용하여 supercombos/<이름> 선택.
  미설정 시 자동 기본 번들로 폴백.
  """
  try:
    pname = Params().get("ActiveModelName")
    if pname:
      pname = pname.decode() if isinstance(pname, (bytes, bytearray)) else pname
      bundle = SUPERCOMBOS_DIR / pname
      return bundle
  except Exception:
    pass
  return _auto_default_bundle_dir()

# =========================
# 모델 메타 처리
# =========================
def _stale(meta: Path, onnx: Path) -> bool:
  return (not meta.exists()) or (onnx.stat().st_mtime > meta.stat().st_mtime)

def _ensure_metadata_generated(onnx_path: Path, meta_path: Path) -> None:
  script = Path(__file__).parent / 'get_model_metadata.py'
  if not script.exists():
    raise FileNotFoundError(f"메타데이터 생성 스크립트를 찾을 수 없습니다: {script}")
  cmd = ["python3", str(script), str(onnx_path)]
  res = subprocess.run(cmd, cwd=Path(__file__).parent, capture_output=True, text=True)
  if res.returncode != 0:
    raise RuntimeError(
      f"메타데이터 생성 실패\ncmd: {' '.join(cmd)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
  if not meta_path.exists():
    raise RuntimeError(f"메타 생성 후에도 파일이 없습니다: {meta_path}")

def _resolve_onnx_only_paths(model_dir: Path) -> Dict[str, Path]:
  vis_onnx = model_dir / VISION_ONNX
  pol_onnx = model_dir / POLICY_ONNX
  if not vis_onnx.exists() or not pol_onnx.exists():
    raise FileNotFoundError(f"[{model_dir}] ONNX 누락: {VISION_ONNX}, {POLICY_ONNX} 필요")

  vis_meta = model_dir / VISION_META
  pol_meta = model_dir / POLICY_META
  if _stale(vis_meta, vis_onnx):
    _ensure_metadata_generated(vis_onnx, vis_meta)
  if _stale(pol_meta, pol_onnx):
    _ensure_metadata_generated(pol_onnx, pol_meta)

  return {
    'vision_onnx': vis_onnx,
    'policy_onnx': pol_onnx,
    'vision_meta': vis_meta,
    'policy_meta': pol_meta,
  }

# =========================
# 제어/도메인 로직
# =========================
def get_action_from_model(model_output: dict[str, np.ndarray], prev_action: log.ModelDataV2.Action,
                          lat_action_t: float, long_action_t: float, v_ego: float) -> log.ModelDataV2.Action:
  plan = model_output['plan'][0]
  desired_accel, should_stop = get_accel_from_plan(
    plan[:, Plan.VELOCITY][:, 0],
    plan[:, Plan.ACCELERATION][:, 0],
    ModelConstants.T_IDXS,
    action_t=long_action_t
  )
  desired_accel = smooth_value(desired_accel, prev_action.desiredAcceleration, LONG_SMOOTH_SECONDS)
  desired_curvature = get_curvature_from_plan(
    plan[:, Plan.T_FROM_CURRENT_EULER][:, 2],
    plan[:, Plan.ORIENTATION_RATE][:, 2],
    ModelConstants.T_IDXS,
    v_ego,
    lat_action_t
  )
  if v_ego > MIN_LAT_CONTROL_SPEED:
    desired_curvature = smooth_value(desired_curvature, prev_action.desiredCurvature, LAT_SMOOTH_SECONDS)
  else:
    desired_curvature = prev_action.desiredCurvature
  return log.ModelDataV2.Action(
    desiredCurvature=float(desired_curvature),
    desiredAcceleration=float(desired_accel),
    shouldStop=bool(should_stop),
  )

class FrameMeta:
  frame_id: int = 0
  timestamp_sof: int = 0
  timestamp_eof: int = 0
  def __init__(self, vipc=None):
    if vipc is not None:
      self.frame_id, self.timestamp_sof, self.timestamp_eof = vipc.frame_id, vipc.timestamp_sof, vipc.timestamp_eof

class InputQueues:
  def __init__(self, model_fps, env_fps, n_frames_input):
    assert env_fps % model_fps == 0
    assert env_fps >= model_fps
    self.model_fps = model_fps
    self.env_fps = env_fps
    self.n_frames_input = n_frames_input
    self.dtypes: dict[str, np.dtype] = {}
    self.shapes: dict[str, tuple] = {}
    self.q: dict[str, np.ndarray] = {}

  def update_dtypes_and_shapes(self, input_dtypes, input_shapes) -> None:
    self.dtypes.update(input_dtypes)
    if self.env_fps == self.model_fps:
      self.shapes.update(input_shapes)
    else:
      for k in input_shapes:
        shape = list(input_shapes[k])
        if 'img' in k:
          n_channels = shape[1] // self.n_frames_input
          shape[1] = (self.env_fps // self.model_fps + (self.n_frames_input - 1)) * n_channels
        else:
          shape[1] = (self.env_fps // self.model_fps) * shape[1]
        self.shapes[k] = tuple(shape)

  def reset(self) -> None:
    self.q = {k: np.zeros(self.shapes[k], dtype=self.dtypes[k]) for k in self.dtypes.keys()}

  def enqueue(self, inputs: dict[str, np.ndarray]) -> None:
    for k in inputs.keys():
      if inputs[k].dtype != self.dtypes[k]:
        raise ValueError(f'supplied input <{k}({inputs[k].dtype})> has wrong dtype, expected {self.dtypes[k]}')
      input_shape = list(self.shapes[k])
      input_shape[1] = -1
      single_input = inputs[k].reshape(tuple(input_shape))
      sz = single_input.shape[1]
      self.q[k][:, :-sz] = self.q[k][:, sz:]
      self.q[k][:, -sz:] = single_input

  def get(self, *names) -> dict[str, np.ndarray]:
    if self.env_fps == self.model_fps:
      return {k: self.q[k] for k in names}
    else:
      out = {}
      for k in names:
        shape = self.shapes[k]
        if 'img' in k:
          n_channels = shape[1] // (self.env_fps // self.model_fps + (self.n_frames_input - 1))
          out[k] = np.concatenate(
            [self.q[k][:, s:s + n_channels] for s in np.linspace(0, shape[1] - n_channels, self.n_frames_input, dtype=int)],
            axis=1)
        elif 'pulse' in k:
          out[k] = self.q[k].reshape((shape[0], shape[1] * self.model_fps // self.env_fps, self.env_fps // self.model_fps, -1)).max(axis=2)
        else:
          idxs = np.arange(-1, -shape[1], -self.env_fps // self.model_fps)[::-1]
          out[k] = self.q[k][:, idxs]
      return out

class ModelState:
  frames: dict[str, DrivingModelFrame]
  prev_desire: np.ndarray
  def __init__(self, context: CLContext, paths: dict):
    with open(paths['vision_meta'], 'rb') as f:
      vision_metadata = pickle.load(f)
      self.vision_input_shapes = vision_metadata['input_shapes']
      self.vision_input_names = list(self.vision_input_shapes.keys())
      self.vision_output_slices = vision_metadata['output_slices']
      vision_output_size = vision_metadata['output_shapes']['outputs'][1]

    with open(paths['policy_meta'], 'rb') as f:
      policy_metadata = pickle.load(f)
      self.policy_input_shapes = policy_metadata['input_shapes']
      self.policy_output_slices = policy_metadata['output_slices']
      policy_output_size = policy_metadata['output_shapes']['outputs'][1]

    self.vision_run, vision_specs = load_onnx_model(fetch(str(paths['vision_onnx'])))
    self.policy_run, policy_specs = load_onnx_model(fetch(str(paths['policy_onnx'])))
    self.vision_in_name, self.vision_in_spec = list(vision_specs.items())[0]
    self.policy_in_name, self.policy_in_spec = list(policy_specs.items())[0]

    self.frames = {name: DrivingModelFrame(context, ModelConstants.MODEL_RUN_FREQ // ModelConstants.MODEL_CONTEXT_FREQ)
                   for name in self.vision_input_names}
    self.prev_desire = np.zeros(ModelConstants.DESIRE_LEN, dtype=np.float32)

    self.numpy_inputs = {k: np.zeros(self.policy_input_shapes[k], dtype=np.float32) for k in self.policy_input_shapes}
    self.full_input_queues = InputQueues(ModelConstants.MODEL_CONTEXT_FREQ, ModelConstants.MODEL_RUN_FREQ, ModelConstants.N_FRAMES)
    for k in ['desire_pulse', 'features_buffer']:
      self.full_input_queues.update_dtypes_and_shapes({k: self.numpy_inputs[k].dtype}, {k: self.numpy_inputs[k].shape})
    self.full_input_queues.reset()

    self.vision_output = np.zeros(vision_output_size, dtype=np.float32)
    self.policy_output = np.zeros(policy_output_size, dtype=np.float32)
    self.parser = Parser()
    self.vision_inputs: dict[str, Tensor] = {}

  def _prep_vision_inputs(self, bufs: dict[str, VisionBuf], transforms: dict[str, np.ndarray]) -> dict[str, Tensor]:
    imgs_cl = {name: self.frames[name].prepare(bufs[name], transforms[name].flatten()) for name in self.vision_input_names}
    out: dict[str, Tensor] = {}
    if TICI and not USBGPU:
      for key in imgs_cl:
        if key not in self.vision_inputs:
          self.vision_inputs[key] = qcom_tensor_from_opencl_address(
            imgs_cl[key].mem_address, self.vision_input_shapes[key], dtype=dtypes.uint8)
        out[key] = self.vision_inputs[key]
    else:
      for key in imgs_cl:
        frame_input = self.frames[key].buffer_from_cl(imgs_cl[key]).reshape(self.vision_input_shapes[key])
        out[key] = Tensor(frame_input, dtype=dtypes.uint8).realize()
    return out

  def _adapt_to_spec(self, t: Tensor, expect_dtype) -> Tensor:
    if expect_dtype == dtypes.float32:
      t = (t.cast(dtypes.float32) / 255.0)
      # 필요 시 mean/std 적용 가능:
      # mean = Tensor([0.485, 0.456, 0.406]).reshape(1,-1,1,1)
      # std  = Tensor([0.229, 0.224, 0.225]).reshape(1,-1,1,1)
      # t = (t - mean) / std
    return t

  def slice_outputs(self, model_outputs: np.ndarray, output_slices: dict[str, slice]) -> dict[str, np.ndarray]:
    return {k: model_outputs[np.newaxis, v] for k, v in output_slices.items()}

  def run(self, bufs: dict[str, VisionBuf], transforms: dict[str, np.ndarray],
          inputs: dict[str, np.ndarray], prepare_only: bool) -> dict[str, np.ndarray] | None:
    inputs['desire_pulse'][0] = 0
    new_desire = np.where(inputs['desire_pulse'] - self.prev_desire > .99, inputs['desire_pulse'], 0)
    self.prev_desire[:] = inputs['desire_pulse']

    vin_map = self._prep_vision_inputs(bufs, transforms)
    if prepare_only:
      return None

    first_key = self.vision_input_names[0]
    vi = self._adapt_to_spec(vin_map[first_key], self.vision_in_spec.dtype)
    v_out = self.vision_run(**{self.vision_in_name: vi})
    v_np = v_out.contiguous().realize().uop.base.buffer.numpy()
    self.vision_output[:] = v_np
    vision_outputs_dict = self.parser.parse_vision_outputs(self.slice_outputs(self.vision_output, self.vision_output_slices))

    self.full_input_queues.enqueue({'features_buffer': vision_outputs_dict['hidden_state'], 'desire_pulse': new_desire})
    for k in ['desire_pulse', 'features_buffer']:
      self.numpy_inputs[k][:] = self.full_input_queues.get(k)[k]
    self.numpy_inputs['traffic_convention'][:] = inputs['traffic_convention']

    p_src_name = self.policy_in_name
    p_in = Tensor(self.numpy_inputs[p_src_name], device='NPY').realize()
    p_out = self.policy_run(**{p_src_name: p_in})
    p_np = p_out.contiguous().realize().uop.base.buffer.numpy()
    self.policy_output[:] = p_np
    policy_outputs_dict = self.parser.parse_policy_outputs(self.slice_outputs(self.policy_output, self.policy_output_slices))

    combined_outputs_dict = {**vision_outputs_dict, **policy_outputs_dict}
    if SEND_RAW_PRED:
      combined_outputs_dict['raw_pred'] = np.concatenate([self.vision_output.copy(), self.policy_output.copy()])
    return combined_outputs_dict

def main(demo: bool = False):
  cloudlog.warning("modeld init")
  if not USBGPU:
    config_realtime_process(7, 54)

  st = time.monotonic()
  cloudlog.warning("setting up CL context")
  cl_context = CLContext()

  # ActiveModelName만 사용해 supercombos/<이름> 선택
  bundle_dir = _choose_model_dir_from_params_only()
  paths = _resolve_onnx_only_paths(bundle_dir)
  cloudlog.warning(f"CL context ready; loading ONNX models from: {bundle_dir}")
  model = ModelState(cl_context, paths)
  cloudlog.warning(f"models loaded in {time.monotonic() - st:.1f}s, modeld starting")

  # visionipc clients
  while True:
    available_streams = VisionIpcClient.available_streams("camerad", block=False)
    if available_streams:
      use_extra_client = (VisionStreamType.VISION_STREAM_WIDE_ROAD in available_streams) and \
                         (VisionStreamType.VISION_STREAM_ROAD in available_streams)
      main_wide_camera = VisionStreamType.VISION_STREAM_ROAD not in available_streams
      break
    time.sleep(.1)

  vipc_client_main_stream = VisionStreamType.VISION_STREAM_WIDE_ROAD if main_wide_camera else VisionStreamType.VISION_STREAM_ROAD
  vipc_client_main = VisionIpcClient("camerad", vipc_client_main_stream, True, cl_context)
  vipc_client_extra = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_WIDE_ROAD, False, cl_context)
  cloudlog.warning(f"vision stream set up, main_wide_camera: {main_wide_camera}, use_extra_client: {use_extra_client}")

  while not vipc_client_main.connect(False):
    time.sleep(0.1)
  while use_extra_client and not vipc_client_extra.connect(False):
    time.sleep(0.1)

  cloudlog.warning(f"connected main cam with buffer size: {vipc_client_main.buffer_len} ({vipc_client_main.width} x {vipc_client_main.height})")
  if use_extra_client:
    cloudlog.warning(f"connected extra cam with buffer size: {vipc_client_extra.buffer_len} ({vipc_client_extra.width} x {vipc_client_extra.height})")

  pm = PubMaster(["modelV2", "drivingModelData", "cameraOdometry"])
  sm = SubMaster(["deviceState", "carState", "roadCameraState", "liveCalibration", "driverMonitoringState", "carControl", "liveDelay"])

  publish_state = PublishState()
  params = Params()

  frame_dropped_filter = FirstOrderFilter(0., 10., 1. / ModelConstants.MODEL_RUN_FREQ)
  last_vipc_frame_id = 0
  run_count = 0

  model_transform_main = np.zeros((3, 3), dtype=np.float32)
  model_transform_extra = np.zeros((3, 3), dtype=np.float32)
  live_calib_seen = False
  buf_main, buf_extra = None, None
  meta_main = FrameMeta()
  meta_extra = FrameMeta()

  if demo:
    CP = get_demo_car_params()
  else:
    CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  cloudlog.info("modeld got CarParams: %s", CP.brand)

  long_delay = CP.longitudinalActuatorDelay + LONG_SMOOTH_SECONDS
  prev_action = log.ModelDataV2.Action()
  DH = DesireHelper()

  while True:
    while meta_main.timestamp_sof < meta_extra.timestamp_sof + 25000000:
      buf_main = vipc_client_main.recv()
      meta_main = FrameMeta(vipc_client_main)
      if buf_main is None:
        break

    if buf_main is None:
      cloudlog.debug("vipc_client_main no frame")
      continue

    if use_extra_client:
      while True:
        buf_extra = vipc_client_extra.recv()
        meta_extra = FrameMeta(vipc_client_extra)
        if buf_extra is None or meta_main.timestamp_sof < meta_extra.timestamp_sof + 25000000:
          break
      if buf_extra is None:
        cloudlog.debug("vipc_client_extra no frame")
        continue
      if abs(meta_main.timestamp_sof - meta_extra.timestamp_sof) > 10000000:
        cloudlog.error(
          f"frames out of sync! main: {meta_main.frame_id} ({meta_main.timestamp_sof / 1e9:.5f}), "
          f"extra: {meta_extra.frame_id} ({meta_extra.timestamp_sof / 1e9:.5f})"
        )
    else:
      buf_extra = buf_main
      meta_extra = meta_main

    sm.update(0)
    desire = DH.desire
    is_rhd = sm["driverMonitoringState"].isRHD
    v_ego = max(sm["carState"].vEgo, 0.)
    lat_delay = sm["liveDelay"].lateralDelay + LAT_SMOOTH_SECONDS
    if sm.updated["liveCalibration"] and sm.seen['roadCameraState'] and sm.seen['deviceState']:
      device_from_calib_euler = np.array(sm["liveCalibration"].rpyCalib, dtype=np.float32)
      dc = DEVICE_CAMERAS[(str(sm['deviceState'].deviceType), str(sm['roadCameraState'].sensor))]
      model_transform_main = get_warp_matrix(
        device_from_calib_euler, dc.ecam.intrinsics if main_wide_camera else dc.fcam.intrinsics, False
      ).astype(np.float32)
      model_transform_extra = get_warp_matrix(device_from_calib_euler, dc.ecam.intrinsics, True).astype(np.float32)
      live_calib_seen = True

    traffic_convention = np.zeros(2)
    traffic_convention[int(is_rhd)] = 1

    vec_desire = np.zeros(ModelConstants.DESIRE_LEN, dtype=np.float32)
    if 0 <= desire < ModelConstants.DESIRE_LEN:
      vec_desire[desire] = 1

    vipc_dropped_frames = max(0, meta_main.frame_id - last_vipc_frame_id - 1)
    frames_dropped = frame_dropped_filter.update(min(vipc_dropped_frames, 10))
    if run_count < 10:
      frame_dropped_filter.x = 0.
      frames_dropped = 0.
    run_count += 1

    frame_drop_ratio = frames_dropped / (1 + frames_dropped)
    prepare_only = vipc_dropped_frames > 0
    if prepare_only:
      cloudlog.error(f"skipping model eval. Dropped {vipc_dropped_frames} frames")

    bufs = {name: buf_extra if 'big' in name else buf_main for name in model.vision_input_names}
    transforms = {name: model_transform_extra if 'big' in name else model_transform_main for name in model.vision_input_names}
    inputs: dict[str, np.ndarray] = {'desire_pulse': vec_desire, 'traffic_convention': traffic_convention}

    mt1 = time.perf_counter()
    model_output = model.run(bufs, transforms, inputs, prepare_only)
    mt2 = time.perf_counter()
    model_execution_time = mt2 - mt1

    if model_output is not None:
      modelv2_send = messaging.new_message('modelV2')
      drivingdata_send = messaging.new_message('drivingModelData')
      posenet_send = messaging.new_message('cameraOdometry')

      action = get_action_from_model(model_output, prev_action, lat_delay + DT_MDL, long_delay + DT_MDL, v_ego)
      prev_action = action
      fill_model_msg(
        drivingdata_send, modelv2_send, model_output, action,
        PublishState(), meta_main.frame_id, meta_extra.frame_id, sm["roadCameraState"].frameId,
        frame_drop_ratio, meta_main.timestamp_eof, model_execution_time, live_calib_seen
      )

      desire_state = modelv2_send.modelV2.meta.desireState
      l_lane_change_prob = desire_state[log.Desire.laneChangeLeft]
      r_lane_change_prob = desire_state[log.Desire.laneChangeRight]
      lane_change_prob = l_lane_change_prob + r_lane_change_prob
      DH.update(sm['carState'], sm['carControl'].latActive, lane_change_prob)
      modelv2_send.modelV2.meta.laneChangeState = DH.lane_change_state
      modelv2_send.modelV2.meta.laneChangeDirection = DH.lane_change_direction
      drivingdata_send.drivingModelData.meta.laneChangeState = DH.lane_change_state
      drivingdata_send.drivingModelData.meta.laneChangeDirection = DH.lane_change_direction

      fill_pose_msg(posenet_send, model_output, meta_main.frame_id, vipc_dropped_frames, meta_main.timestamp_eof, live_calib_seen)
      pm.send('modelV2', modelv2_send)
      pm.send('drivingModelData', drivingdata_send)
      pm.send('cameraOdometry', posenet_send)

    last_vipc_frame_id = meta_main.frame_id

if __name__ == "__main__":
  try:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='A boolean for demo mode.')
    # 경로/이름 관련 인자는 더 이상 받지 않음(ActiveModelName만 사용)
    args = parser.parse_args()
    main(demo=args.demo)
  except KeyboardInterrupt:
    cloudlog.warning("got SIGINT")
