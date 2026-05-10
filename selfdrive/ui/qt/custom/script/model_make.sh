#!/usr/bin/env bash
set -euo pipefail


PY=python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
MODELD_DIR="${REPO_ROOT}/selfdrive/modeld"
WORKDIR="${WORKDIR:-${MODELD_DIR}}"

echo "[model_make] ===== START $(date) ====="
echo "[model_make] [${WORKDIR}]"
cd "${WORKDIR}"


# 실시간 로그 출력
export PYTHONUNBUFFERED=1
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

echo "[model_make] 실행"
set +e
${PY} model_make.py
RC=$?
set -e

echo "[model_make] ===== END $(date) (rc=${RC}) ====="
exit ${RC}
