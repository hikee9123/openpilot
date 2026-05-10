#!/usr/bin/env bash
set -e
set -o pipefail
set -x

# git diff --name-status origin/release3-staging | grep "^A" | less

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"

cd "$DIR"

SOURCE_DIR="$(git rev-parse --show-toplevel)"

if [ -z "${RELEASE_BRANCH:-}" ]; then
  echo "RELEASE_BRANCH is not set"
  exit 1
fi

DEFAULT_BUILD_ROOT="/data"
if [ ! -d "$DEFAULT_BUILD_ROOT" ] || [ ! -w "$DEFAULT_BUILD_ROOT" ]; then
  DEFAULT_BUILD_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}"
fi
BUILD_DIR="${BUILD_DIR:-$DEFAULT_BUILD_ROOT/openpilot-release-$RELEASE_BRANCH}"
RELEASE_REMOTE="${RELEASE_REMOTE:-$(git -C "$SOURCE_DIR" remote get-url origin)}"
PANDA_RELEASE_CERT="${PANDA_RELEASE_CERT:-/data/pandaextra/certs/release}"
PUSH="${PUSH:-0}"
if [ -z "${SCONS:-}" ]; then
  if [ -x "$SOURCE_DIR/.venv/bin/scons" ]; then
    SCONS="$SOURCE_DIR/.venv/bin/scons"
  else
    SCONS="scons"
  fi
fi
if [ -d "$SOURCE_DIR/.venv/bin" ]; then
  export PATH="$SOURCE_DIR/.venv/bin:$PATH"
fi

if [ "$BUILD_DIR" = "$SOURCE_DIR" ]; then
  echo "BUILD_DIR must not be the source checkout"
  exit 1
fi

# set git identity
source "$DIR/identity.sh"

echo "[-] Setting up repo T=$SECONDS"
echo "[-] source: $SOURCE_DIR"
echo "[-] build: $BUILD_DIR"
echo "[-] remote: $RELEASE_REMOTE"
echo "[-] scons: $SCONS"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
git init
git remote add origin "$RELEASE_REMOTE"
git checkout --orphan "$RELEASE_BRANCH"

# do the files copy
echo "[-] copying files T=$SECONDS"
cd "$SOURCE_DIR"
./release/release_files.py | tar -cf - -T - | tar -C "$BUILD_DIR" -xf -

# in the directory
cd "$BUILD_DIR"

rm -f panda/board/obj/panda.bin.signed
rm -f panda/board/obj/panda_h7.bin.signed

VERSION=$(cat common/version.h | awk -F[\"-]  '{print $2}')
echo "[-] committing version $VERSION T=$SECONDS"
git add -f .
git commit -a -m "openpilot v$VERSION release"

# Build
export PYTHONPATH="$BUILD_DIR"
"$SCONS" -j$(nproc) --minimal

if [ -z "${PANDA_DEBUG_BUILD:-}" ] && [ -e "$PANDA_RELEASE_CERT" ]; then
  # release panda fw
  CERT="$PANDA_RELEASE_CERT" RELEASE=1 "$SCONS" -j$(nproc) panda/
else
  # build without release cert to enable features like experimental longitudinal
  "$SCONS" -j$(nproc) panda/
fi

# Ensure no submodules in release
if test "$(git submodule--helper list | wc -l)" -gt "0"; then
  echo "submodules found:"
  git submodule--helper list
  exit 1
fi
git submodule status

# Cleanup
find . -name '*.a' -delete
find . -name '*.o' -delete
find . -name '*.os' -delete
find . -name '*.pyc' -delete
find . -name 'moc_*' -delete
find . -name '__pycache__' -delete
rm -rf .sconsign.dblite Jenkinsfile release/
rm selfdrive/modeld/models/driving_vision.onnx
rm selfdrive/modeld/models/driving_policy.onnx

find third_party/ -name '*x86*' -exec rm -r {} +
find third_party/ -name '*Darwin*' -exec rm -r {} +

# Split large generated model artifacts so release branches can be pushed to GitHub without LFS.
while IFS= read -r model_file; do
  echo "[-] splitting large model artifact: $model_file"
  rm -f "$model_file.part-"*
  split -b 50m "$model_file" "$model_file.part-"
  rm "$model_file"
done < <(find selfdrive/modeld/models -name '*_tinygrad.pkl' -type f -size +95M)

# Ensure files are within GitHub's limit
BIG_FILES="$(find . -type f -not -path './.git/*' -size +95M)"
if [ -n "$BIG_FILES" ]; then
  printf '\n\n\n'
  echo "Found files exceeding GitHub's 100MB limit:"
  echo "$BIG_FILES"
  exit 1
fi

# Restore third_party
git checkout third_party/

# Mark as prebuilt release
touch prebuilt

# Add built files to git
git add -f .
git commit --amend -m "openpilot v$VERSION"

# Run tests
cd "$BUILD_DIR"
RELEASE=1 pytest -n0 -s selfdrive/test/test_onroad.py
#pytest selfdrive/car/tests/test_car_interfaces.py

if [ "$PUSH" = "1" ]; then
  echo "[-] pushing release T=$SECONDS"
  git push -f origin "$RELEASE_BRANCH:$RELEASE_BRANCH"
else
  echo "[-] push skipped; set PUSH=1 to push $RELEASE_BRANCH to $RELEASE_REMOTE"
fi

echo "[-] done T=$SECONDS"
