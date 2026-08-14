#!/usr/bin/env python3
import sys
import pathlib
import codecs
import math
import pickle
from typing import Any


DM_OUTPUT_SIZE = 553
COMPAT_DM_DRIVER_STATE_WIDTH = 41
DM_FEATURE_LEN = 512
COMPAT_DM_OUTPUT_SIZE = (2 * COMPAT_DM_DRIVER_STATE_WIDTH) + 1 + DM_FEATURE_LEN
LEGACY_DM_OUTPUT_SIZE = COMPAT_DM_OUTPUT_SIZE + 1


def get_dmonitoring_output_slices(output_size: int) -> dict[str, slice]:
  if output_size not in (COMPAT_DM_OUTPUT_SIZE, LEGACY_DM_OUTPUT_SIZE):
    raise ValueError(f"unexpected driver monitoring output size: {output_size}, expected {COMPAT_DM_OUTPUT_SIZE} or {LEGACY_DM_OUTPUT_SIZE}")

  output_slices = {}
  for ds_suffix, base in (("lhd", 0), ("rhd", COMPAT_DM_DRIVER_STATE_WIDTH)):
    output_slices.update({
      f"face_orientation_{ds_suffix}": slice(base, base + 3),
      f"face_position_{ds_suffix}": slice(base + 3, base + 5),
      f"face_orientation_std_{ds_suffix}": slice(base + 6, base + 9),
      f"face_position_std_{ds_suffix}": slice(base + 9, base + 11),
      f"face_prob_{ds_suffix}": slice(base + 12, base + 13),
      f"left_eye_prob_{ds_suffix}": slice(base + 21, base + 22),
      f"right_eye_prob_{ds_suffix}": slice(base + 30, base + 31),
      f"left_blink_prob_{ds_suffix}": slice(base + 31, base + 32),
      f"right_blink_prob_{ds_suffix}": slice(base + 32, base + 33),
      f"sunglasses_prob_{ds_suffix}": slice(base + 33, base + 34),
    })

  next_idx = 2 * COMPAT_DM_DRIVER_STATE_WIDTH
  if output_size == LEGACY_DM_OUTPUT_SIZE:
    output_slices["poor_vision"] = slice(next_idx, next_idx + 1)
    next_idx += 1

  output_slices["wheel_on_right"] = slice(next_idx, next_idx + 1)
  output_slices["features"] = slice(next_idx + 1, output_size)
  return output_slices


def get_name_and_shape(value_info: Any) -> tuple[str, tuple[int,...]]:
  shape = tuple([int(dim.dim_value) for dim in value_info.type.tensor_type.shape.dim])
  name = value_info.name
  return name, shape


def get_metadata_value_by_name(model: Any, name:str) -> str | Any:
  for prop in model.metadata_props:
    if prop.key == name:
      return prop.value
  return None


if __name__ == "__main__":
  import onnx

  model_path = pathlib.Path(sys.argv[1])
  model = onnx.load(str(model_path))
  output_slices = get_metadata_value_by_name(model, 'output_slices')
  if output_slices is not None:
    output_slices = pickle.loads(codecs.decode(output_slices.encode(), "base64"))
  elif model_path.stem == "dmonitoring_model" and len(model.graph.output) == 1:
    output_size = math.prod(get_name_and_shape(model.graph.output[0])[1])
    output_slices = get_dmonitoring_output_slices(output_size)
  else:
    raise ValueError('output_slices not found in metadata')

  metadata = {
    'model_checkpoint': get_metadata_value_by_name(model, 'model_checkpoint'),
    'output_slices': output_slices,
    'input_shapes': dict([get_name_and_shape(x) for x in model.graph.input]),
    'output_shapes': dict([get_name_and_shape(x) for x in model.graph.output])
  }

  metadata_path = model_path.parent / (model_path.stem + '_metadata.pkl')
  with open(metadata_path, 'wb') as f:
    pickle.dump(metadata, f)

  print(f'saved metadata to {metadata_path}')
