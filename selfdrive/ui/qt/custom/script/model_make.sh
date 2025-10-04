#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/data/openpilot/logs"
LOG_FILE="${LOG_DIR}/model_make.log"
WORKDIR="/data/openpilot/selfdrive/modeld"
PY=python3

mkdir -p "${LOG_DIR}"

echo "[model_make] ===== START $(date) =====" | tee -a "${LOG_FILE}"

# 필수 경로 확인
if [ ! -d "${WORKDIR}" ]; then
  echo "[model_make] ERROR: workdir not found: ${WORKDIR}" | tee -a "${LOG_FILE}"
  exit 1
fi
cd "${WORKDIR}"

if [ ! -f "${WORKDIR}/model_make.py" ]; then
  echo "[model_make] ERROR: model_make.py not found in ${WORKDIR}" | tee -a "${LOG_FILE}"
  exit 2
fi

# 실시간 로그 출력
export PYTHONUNBUFFERED=1

# sudo가 필요 없는 환경을 우선 사용, 필요 시에만 시도
if command -v sudo >/dev/null 2>&1; then
  if sudo -n true >/dev/null 2>&1; then
    echo "[model_make] run: sudo -n ${PY} model_make.py" | tee -a "${LOG_FILE}"
    set +e
    sudo -n ${PY} model_make.py 2>&1 | tee -a "${LOG_FILE}"
    RC=${PIPESTATUS[0]}
    set -e
  else
    echo "[model_make] sudo 비대화 모드 불가 → 일반 권한으로 실행" | tee -a "${LOG_FILE}"
    set +e
    ${PY} model_make.py 2>&1 | tee -a "${LOG_FILE}"
    RC=${PIPESTATUS[0]}
    set -e
  fi
else
  echo "[model_make] sudo 없음 → 일반 권한으로 실행" | tee -a "${LOG_FILE}"
  set +e
  ${PY} model_make.py 2>&1 | tee -a "${LOG_FILE}"
  RC=${PIPESTATUS[0]}
  set -e
fi

echo "[model_make] ===== END $(date) (rc=${RC}) =====" | tee -a "${LOG_FILE}"
exit ${RC}
