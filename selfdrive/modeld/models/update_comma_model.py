#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SUPERCOMBOS_DIR = Path(__file__).resolve().parent / "supercombos"
COMMA_REPO = "https://github.com/commaai/openpilot.git"
DEFAULT_BRANCH = "master"
MODEL_FILES = {
  "vision": "selfdrive/modeld/models/driving_vision.onnx",
  "policy": "selfdrive/modeld/models/driving_policy.onnx",
}
LOCAL_FILES = {
  "vision": "driving_vision.onnx",
  "policy": "driving_policy.onnx",
}


def run_git(args: list[str]) -> str:
  res = subprocess.run(["git", *args], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  if res.returncode != 0:
    raise RuntimeError(f"git {' '.join(args)} failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
  return res.stdout.strip()


def fetch_comma_ref(repo: str, branch: str) -> str:
  run_git(["fetch", "--no-tags", repo, branch])
  return run_git(["rev-parse", "FETCH_HEAD"])


def parse_lfs_pointer(ref: str, path: str) -> dict[str, Any]:
  pointer = run_git(["show", f"{ref}:{path}"])
  oid = ""
  size = 0
  for line in pointer.splitlines():
    if line.startswith("oid sha256:"):
      oid = line.removeprefix("oid sha256:").strip()
    elif line.startswith("size "):
      size = int(line.removeprefix("size ").strip())
  if not oid or size <= 0:
    raise RuntimeError(f"{path} is not a valid Git LFS pointer in {ref}")
  return {"oid": oid, "size": size}


def latest_model_commit(ref: str) -> tuple[str, str]:
  paths = list(MODEL_FILES.values())
  out = run_git(["log", "-1", "--format=%H%n%s", ref, "--", *paths])
  lines = out.splitlines()
  if len(lines) < 2:
    raise RuntimeError("Unable to find official model commit title")
  return lines[0], lines[1]


def strip_pr_refs(title: str) -> str:
  return re.sub(r"\s*\(#\d+\)", "", title).strip()


def model_name_from_title(title: str, commit: str) -> str:
  title = strip_pr_refs(title)
  revert = re.match(r'^Revert\s+"(.+)"$', title)
  if revert:
    title = strip_pr_refs(revert.group(1))
  title = title.replace("_", " ").strip()
  if not title:
    return f"Comma Model {commit[:8]}"
  return title


def folder_slug(name: str) -> str:
  slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
  return slug or "Comma_Model"


def next_model_prefix() -> int:
  prefix = 1
  for bundle in SUPERCOMBOS_DIR.iterdir():
    if not bundle.is_dir():
      continue
    match = re.match(r"^(\d+)\.", bundle.name)
    if match:
      prefix = max(prefix, int(match.group(1)))
  return prefix + 1


def sha256(path: Path) -> str:
  h = hashlib.sha256()
  with path.open("rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
      h.update(chunk)
  return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
  if not path.exists():
    return {}
  return json.loads(path.read_text())


def write_json(path: Path, data: dict[str, Any]) -> None:
  path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def emit_result(data: dict[str, Any], json_output: bool) -> None:
  if json_output:
    print(json.dumps(data, sort_keys=True))
    return

  print(f"comma ref: {data['comma_ref']}")
  print(f"model commit: {data['source_commit']}")
  print(f"model title: {data['source_title']}")
  print(f"model name: {data['model_name']}")
  print(f"vision oid: {data['vision_oid']}")
  print(f"policy oid: {data['policy_oid']}")
  if data.get("existing_model"):
    print(f"existing model: {data['existing_model']}")
  if data.get("new_model_folder"):
    print(f"new model folder: {data['new_model_folder']}")
  if data["status"] == "new":
    print("dry run: use --apply to download and register")
  elif data["status"] == "registered":
    print("model registered")
  elif data["status"] == "updated":
    print("metadata updated")


def find_existing_model(vision_oid: str, policy_oid: str) -> Path | None:
  for bundle in sorted(SUPERCOMBOS_DIR.iterdir()):
    if not bundle.is_dir():
      continue
    meta = read_json(bundle / "model.json")
    if meta.get("vision_oid") == vision_oid and meta.get("policy_oid") == policy_oid:
      return bundle

    vision = bundle / LOCAL_FILES["vision"]
    policy = bundle / LOCAL_FILES["policy"]
    if vision.exists() and policy.exists() and sha256(vision) == vision_oid and sha256(policy) == policy_oid:
      return bundle
  return None


def download_lfs_file(commit: str, source_path: str, dest: Path, oid: str, size: int) -> None:
  url = f"https://media.githubusercontent.com/media/commaai/openpilot/{commit}/{source_path}"
  tmp = dest.with_suffix(dest.suffix + ".tmp")
  tmp.unlink(missing_ok=True)
  dest.parent.mkdir(parents=True, exist_ok=True)

  req = urllib.request.Request(url, headers={"User-Agent": "openpilot-comma-model-updater"})
  with urllib.request.urlopen(req, timeout=300) as response, tmp.open("wb") as f:
    while True:
      chunk = response.read(1024 * 1024)
      if not chunk:
        break
      f.write(chunk)

  actual_size = tmp.stat().st_size
  actual_oid = sha256(tmp)
  if actual_size != size or actual_oid != oid:
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"Downloaded {source_path} verification failed: size={actual_size}, sha256={actual_oid}")
  tmp.replace(dest)


def build_metadata(name: str, commit: str, title: str, branch: str, vision: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
  return {
    "name": name,
    "description": "Comma official driving model from commaai/openpilot",
    "source": "commaai/openpilot",
    "source_branch": branch,
    "source_commit": commit,
    "source_title": title,
    "vision_oid": vision["oid"],
    "vision_size": vision["size"],
    "policy_oid": policy["oid"],
    "policy_size": policy["size"],
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
  }


def main() -> int:
  parser = argparse.ArgumentParser(description="Register the latest commaai/openpilot official driving model.")
  parser.add_argument("--apply", action="store_true", help="Create/update the local model folder. Without this, only report.")
  parser.add_argument("--json", action="store_true", help="Print a single JSON object for UI integration.")
  parser.add_argument("--repo", default=COMMA_REPO)
  parser.add_argument("--branch", default=DEFAULT_BRANCH)
  args = parser.parse_args()

  commit = fetch_comma_ref(args.repo, args.branch)
  source_commit, source_title = latest_model_commit("FETCH_HEAD")
  vision = parse_lfs_pointer("FETCH_HEAD", MODEL_FILES["vision"])
  policy = parse_lfs_pointer("FETCH_HEAD", MODEL_FILES["policy"])
  model_name = model_name_from_title(source_title, source_commit)

  existing = find_existing_model(vision["oid"], policy["oid"])
  metadata = build_metadata(model_name, source_commit, source_title, args.branch, vision, policy)
  result = {
    "status": "existing",
    "comma_ref": commit,
    "source_commit": source_commit,
    "source_title": source_title,
    "model_name": model_name,
    "vision_oid": vision["oid"],
    "policy_oid": policy["oid"],
    "existing_model": "",
    "new_model_folder": "",
  }

  if existing:
    result["existing_model"] = str(existing.relative_to(SUPERCOMBOS_DIR))
    if args.apply:
      current = read_json(existing / "model.json")
      current.update(metadata)
      write_json(existing / "model.json", current)
      result["status"] = "updated"
    emit_result(result, args.json)
    return 0

  folder = SUPERCOMBOS_DIR / f"{next_model_prefix()}.{folder_slug(model_name)}"
  result["status"] = "new"
  result["new_model_folder"] = str(folder.relative_to(SUPERCOMBOS_DIR))
  if not args.apply:
    emit_result(result, args.json)
    return 0

  folder.mkdir(parents=True, exist_ok=False)
  download_lfs_file(source_commit, MODEL_FILES["vision"], folder / LOCAL_FILES["vision"], vision["oid"], vision["size"])
  download_lfs_file(source_commit, MODEL_FILES["policy"], folder / LOCAL_FILES["policy"], policy["oid"], policy["size"])
  write_json(folder / "model.json", metadata)
  result["status"] = "registered"
  emit_result(result, args.json)
  return 0


if __name__ == "__main__":
  sys.exit(main())
