from pathlib import Path

import numpy as np
import pytest

from openpilot.selfdrive.modeld import dmonitoringmodeld
from openpilot.selfdrive.modeld.dmonitoringmodeld import (
  FEATURE_LEN,
  LEGACY_OUTPUT_SIZE,
  OUTPUT_SIZE,
  parse_model_result,
)


def test_bundled_model_output_size():
  from tinygrad.frontend.onnx import OnnxPBParser

  model_path = Path(dmonitoringmodeld.__file__).parent / "models/dmonitoring_model.onnx"
  graph = OnnxPBParser(model_path, load_external_data=True).parse()["graph"]

  assert len(graph["output"]) == 1
  assert int(np.prod(graph["output"][0]["parsed_type"].shape)) == OUTPUT_SIZE


def test_current_model_output_layout():
  output = np.zeros(OUTPUT_SIZE, dtype=np.float32)
  output[82] = 1.25
  output[83] = 2.5
  output[-1] = 3.5

  flat_output, result, poor_vision_prob = parse_model_result(output)

  assert flat_output.size == 83 + FEATURE_LEN
  assert poor_vision_prob is None
  assert result.wheel_on_right_prob == pytest.approx(1.25)
  assert result.features[0] == pytest.approx(2.5)
  assert result.features[-1] == pytest.approx(3.5)


def test_legacy_model_output_layout():
  output = np.zeros(LEGACY_OUTPUT_SIZE, dtype=np.float32)
  output[82] = 0.25
  output[83] = 1.25
  output[84] = 2.5
  output[-1] = 3.5

  flat_output, result, poor_vision_prob = parse_model_result(output)

  assert flat_output.size == 84 + FEATURE_LEN
  assert poor_vision_prob == pytest.approx(0.25)
  assert result.wheel_on_right_prob == pytest.approx(1.25)
  assert result.features[0] == pytest.approx(2.5)
  assert result.features[-1] == pytest.approx(3.5)


@pytest.mark.parametrize("size", [OUTPUT_SIZE - 1, LEGACY_OUTPUT_SIZE + 1])
def test_rejects_unknown_model_output_size(size):
  with pytest.raises(ValueError, match="unexpected driver monitoring output size"):
    parse_model_result(np.zeros(size, dtype=np.float32))


def test_normalizes_dtype_and_layout_before_cast():
  output = np.zeros(OUTPUT_SIZE * 2, dtype=np.float64)[::2]
  output[82] = 1.25

  flat_output, result, _ = parse_model_result(output)

  assert flat_output.dtype == np.float32
  assert flat_output.flags.c_contiguous
  assert result.wheel_on_right_prob == pytest.approx(1.25)
