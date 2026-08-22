import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpilot.selfdrive.modeld.models import update_comma_model


class TestUpdateCommaModel(unittest.TestCase):
  def test_revert_title_is_not_misidentified_as_reverted_model(self):
    self.assertEqual(update_comma_model.model_name_from_title('Revert "POP model (#37727)" (#37871)', "abc123"),
                     "Revert POP model")

  def test_existing_model_display_name_preserves_bundle_identity(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      bundle = Path(temp_dir) / "10.CD210_Model"
      bundle.mkdir()
      (bundle / "model.json").write_text('{"description": "Comfort profile"}\n')
      self.assertEqual(update_comma_model.existing_model_display_name(bundle), "CD210 Model")

  def test_finds_latest_commit_containing_both_split_models(self):
    def fake_run_git(args: list[str]) -> str:
      if args[0] == "rev-list":
        return "deleted-commit\ncompatible-commit\nolder-commit"
      if args[:2] == ["show", "-s"]:
        self.assertEqual(args[-1], "compatible-commit")
        return "compatible-commit\n2026-01-02T03:04:05Z\nUpdate driving model"
      raise AssertionError(args)

    def fake_object_exists(ref: str, path: str) -> bool:
      self.assertIn(path, update_comma_model.MODEL_FILES.values())
      return ref != "deleted-commit"

    with patch.object(update_comma_model, "run_git", side_effect=fake_run_git), \
         patch.object(update_comma_model, "git_object_exists", side_effect=fake_object_exists):
      commit, date, title = update_comma_model.latest_compatible_model_commit("FETCH_HEAD")

    self.assertEqual(commit, "compatible-commit")
    self.assertEqual(date, "2026-01-02T03:04:05Z")
    self.assertEqual(title, "Update driving model")

  def test_failed_bundle_registration_leaves_no_partial_folder(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      supercombos = Path(temp_dir)
      folder = supercombos / "12.Test_Model"

      def fail_on_policy(source_commit: str, source_path: str, dest: Path, oid: str, size: int) -> None:
        dest.write_bytes(source_path.encode())
        if source_path == update_comma_model.MODEL_FILES["policy"]:
          raise RuntimeError("download failed")

      with patch.object(update_comma_model, "SUPERCOMBOS_DIR", supercombos), \
           patch.object(update_comma_model, "download_lfs_file", side_effect=fail_on_policy):
        with self.assertRaisesRegex(RuntimeError, "download failed"):
          update_comma_model.register_model_bundle(folder, "source-commit", {"oid": "vision", "size": 1},
                                                   {"oid": "policy", "size": 1}, {"name": "Test Model"})

      self.assertFalse(folder.exists())
      self.assertEqual(list(supercombos.iterdir()), [])

  def test_successful_bundle_registration_publishes_complete_folder(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      supercombos = Path(temp_dir)
      folder = supercombos / "12.Test_Model"

      def download(source_commit: str, source_path: str, dest: Path, oid: str, size: int) -> None:
        dest.write_bytes(source_path.encode())

      with patch.object(update_comma_model, "SUPERCOMBOS_DIR", supercombos), \
           patch.object(update_comma_model, "download_lfs_file", side_effect=download):
        update_comma_model.register_model_bundle(folder, "source-commit", {"oid": "vision", "size": 1},
                                                 {"oid": "policy", "size": 1}, {"name": "Test Model"})

      self.assertTrue((folder / update_comma_model.LOCAL_FILES["vision"]).is_file())
      self.assertTrue((folder / update_comma_model.LOCAL_FILES["policy"]).is_file())
      self.assertEqual(json.loads((folder / "model.json").read_text()), {"name": "Test Model"})


if __name__ == "__main__":
  unittest.main()
