import codecs
import pickle
from pathlib import Path

import numpy as np
import pytest

from openpilot.selfdrive.modeld import dmonitoringmodeld
from openpilot.selfdrive.modeld.dmonitoringmodeld import parse_model_output, slice_outputs
from openpilot.selfdrive.modeld.get_model_metadata import (
  COMPAT_DM_OUTPUT_SIZE,
  DM_OUTPUT_SIZE,
  LEGACY_DM_OUTPUT_SIZE,
  get_metadata_value_by_name,
  get_dmonitoring_output_slices,
)
from openpilot.selfdrive.modeld.parse_model_outputs import sigmoid


OFFICIAL_MODEL_CHECKPOINT = "586aece6-afd8-4d8b-b7da-5634d6eae5e6"


def parse_compat_output(output: np.ndarray):
  slices = get_dmonitoring_output_slices(output.size)
  flat_output, sliced_output = slice_outputs(output, slices)
  return flat_output, sliced_output, parse_model_output(sliced_output)


def test_bundled_model_output_size():
  import onnx

  model_path = Path(dmonitoringmodeld.__file__).parent / "models/dmonitoring_model.onnx"
  model = onnx.load(str(model_path))
  output_shape = tuple(int(dim.dim_value) for dim in model.graph.output[0].type.tensor_type.shape.dim)
  output_slices = pickle.loads(codecs.decode(get_metadata_value_by_name(model, "output_slices").encode(), "base64"))

  assert len(model.graph.output) == 1
  assert int(np.prod(output_shape)) == DM_OUTPUT_SIZE
  assert max(s.stop for s in output_slices.values()) == DM_OUTPUT_SIZE
  assert get_metadata_value_by_name(model, "model_checkpoint") == OFFICIAL_MODEL_CHECKPOINT


def test_compat_model_output_layout():
  output = np.zeros(COMPAT_DM_OUTPUT_SIZE, dtype=np.float32)
  output[0:3] = [0.1, 0.2, 0.3]
  output[3:5] = [0.4, 0.5]
  output[82] = 1.25
  output[83] = 2.5
  output[-1] = 3.5

  flat_output, sliced_output, parsed_output = parse_compat_output(output)

  assert flat_output.size == COMPAT_DM_OUTPUT_SIZE
  assert 'poor_vision' not in parsed_output
  assert parsed_output['face_orientation_lhd'][0].tolist() == pytest.approx([0.1, 0.2, 0.3])
  assert parsed_output['face_position_lhd'][0].tolist() == pytest.approx([0.4, 0.5])
  assert parsed_output['wheel_on_right'][0, 0] == pytest.approx(sigmoid(1.25))
  assert sliced_output['features'][0, 0] == pytest.approx(2.5)
  assert sliced_output['features'][0, -1] == pytest.approx(3.5)


def test_legacy_compat_model_output_layout():
  output = np.zeros(LEGACY_DM_OUTPUT_SIZE, dtype=np.float32)
  output[82] = 0.25
  output[83] = 1.25
  output[84] = 2.5
  output[-1] = 3.5

  flat_output, sliced_output, parsed_output = parse_compat_output(output)

  assert flat_output.size == LEGACY_DM_OUTPUT_SIZE
  assert parsed_output['poor_vision'][0, 0] == pytest.approx(sigmoid(0.25))
  assert parsed_output['wheel_on_right'][0, 0] == pytest.approx(sigmoid(1.25))
  assert sliced_output['features'][0, 0] == pytest.approx(2.5)
  assert sliced_output['features'][0, -1] == pytest.approx(3.5)


@pytest.mark.parametrize("size", [COMPAT_DM_OUTPUT_SIZE - 1, LEGACY_DM_OUTPUT_SIZE + 1])
def test_rejects_unknown_model_output_size(size):
  with pytest.raises(ValueError, match="unexpected driver monitoring output size"):
    get_dmonitoring_output_slices(size)


def test_normalizes_dtype_and_layout_before_slicing():
  output = np.zeros(COMPAT_DM_OUTPUT_SIZE * 2, dtype=np.float64)[::2]
  output[82] = 1.25

  flat_output, _, parsed_output = parse_compat_output(output)

  assert flat_output.dtype == np.float32
  assert flat_output.flags.c_contiguous
  assert parsed_output['wheel_on_right'][0, 0] == pytest.approx(sigmoid(1.25))


def test_rejects_output_size_not_matching_metadata():
  output_slices = get_dmonitoring_output_slices(COMPAT_DM_OUTPUT_SIZE)
  with pytest.raises(ValueError, match="unexpected driver monitoring output size"):
    slice_outputs(np.zeros(LEGACY_DM_OUTPUT_SIZE, dtype=np.float32), output_slices)


def test_official_face_desc_layout():
  import onnx

  model_path = Path(dmonitoringmodeld.__file__).parent / "models/dmonitoring_model.onnx"
  model = onnx.load(str(model_path))
  output_slices = pickle.loads(codecs.decode(get_metadata_value_by_name(model, "output_slices").encode(), "base64"))
  output = np.zeros(DM_OUTPUT_SIZE, dtype=np.float32)
  output[output_slices['face_descs_lhd']] = [0.1, 0.2, 0.3, 0.4, 0.5, 0., -1., -2., -3., -4., -5., -6.]

  _, sliced_output = slice_outputs(output, output_slices)
  parsed_output = parse_model_output(sliced_output)

  assert parsed_output['face_orientation_lhd'][0].tolist() == pytest.approx([0.1, 0.2, 0.3])
  assert parsed_output['face_position_lhd'][0].tolist() == pytest.approx([0.4, 0.5])
  assert parsed_output['face_orientation_std_lhd'][0].tolist() == pytest.approx(np.exp([-1., -2., -3.]))
  assert parsed_output['face_position_std_lhd'][0].tolist() == pytest.approx(np.exp([-4., -5.]))
  assert 'using_phone_prob_lhd' in parsed_output
  assert 'sleep_prob_lhd' in parsed_output
