import ast
import json
import unittest
from pathlib import Path


OPENPILOT_ROOT = Path(__file__).resolve().parents[3]
HYUNDAI_VALUES = OPENPILOT_ROOT / "opendbc_repo/opendbc/car/hyundai/values.py"
SUPPORTED_CARS_ASSET = OPENPILOT_ROOT / "selfdrive/assets/hyundai_supported_cars.json"


def hyundai_platform_names() -> list[str]:
  module = ast.parse(HYUNDAI_VALUES.read_text(encoding="utf-8"))
  car_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "CAR")

  names = []
  for node in car_class.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
      names.append(node.targets[0].id)
  return names


class TestHyundaiSupportedCars(unittest.TestCase):
  def test_asset_matches_platform_definitions(self):
    supported_cars = json.loads(SUPPORTED_CARS_ASSET.read_text(encoding="utf-8"))
    self.assertEqual(supported_cars, hyundai_platform_names())
    self.assertEqual(len(supported_cars), len(set(supported_cars)))


if __name__ == "__main__":
  unittest.main()
