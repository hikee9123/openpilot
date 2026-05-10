#!/usr/bin/env python3
import os
import re
import subprocess
from pathlib import Path

HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = HERE + "/.."

blacklist = [
  ".git/",
  ".github/workflows/",
  ".mypy_cache/",
  ".pytest_cache/",
  ".ruff_cache/",
  ".venv/",
  "__pycache__/",
  ".*\\.py[co]$",
  ".sconsign.dblite",

  "matlab.*.md",

  # no LFS or submodules in release
  ".lfsconfig",
  ".gitattributes",
  ".git$",
  ".gitmodules",
]

# gets you through the blacklist
whitelist: list[str] = [
]

if __name__ == "__main__":
  files = subprocess.check_output(["git", "-C", ROOT, "ls-files", "--recurse-submodules"], encoding="utf-8")
  for rf in files.splitlines():
    f = Path(ROOT) / rf
    if not (f.is_file() or f.is_symlink()):
      continue

    blacklisted = any(re.search(p, rf) for p in blacklist)
    whitelisted = any(re.search(p, rf) for p in whitelist)
    if blacklisted and not whitelisted:
      continue

    print(rf)
