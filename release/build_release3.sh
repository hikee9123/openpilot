#!/usr/bin/env bash
set -e
set -o pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"

export RELEASE_BRANCH="${RELEASE_BRANCH:-release3}"
export PUSH="${PUSH:-1}"

exec "$DIR/build_release.sh" "$@"
