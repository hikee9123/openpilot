#!/usr/bin/env bash
set -euo pipefail


PY=python3

echo "[model_make] ===== START $(date) ====="
echo "[model_make] [${WORKDIR}]"
rem cd "${WORKDIR}"

# 실시간 로그 출력
export PYTHONUNBUFFERED=1

set +e
${PY} model_make.py
RC=$?
set -e

echo "[model_make] ===== END $(date) (rc=${RC}) ====="
exit ${RC}
