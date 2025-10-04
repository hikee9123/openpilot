#!/usr/bin/env bash
# model_make.sh
# 사용법:
#   ./model_make.sh                 # 현재 Params.ActiveModelName 값으로 빌드
#   ./model_make.sh "3.Firehose"    # 모델 이름을 지정해서 설정 후 빌드
#
# 참고: sudo가 있고 루트가 아니라면 sudo로 python을 실행합니다.
#       TG_FLAGS/USBGPU/DEV/AMD_IFACE 등의 환경변수는 그대로 전달됩니다.

set -euo pipefail

# 스크립트 위치로 이동 (…/selfdrive/modeld)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 선택 모델 이름이 인자로 넘어온 경우, Params.ActiveModelName 업데이트
if [[ "${1-}" != "" ]]; then
  SEL="$1"
  echo "[model_make.sh] Set ActiveModelName -> ${SEL}"
  python3 - <<PY
from openpilot.common.params import Params
Params().put("ActiveModelName", "${SEL}")
print("ActiveModelName set to: ${SEL}")
PY
fi

# 실행 커맨드 준비
PYTHON=python3
CMD=( "$PYTHON" "model_make.py" )

echo "[model_make.sh] Working dir: ${PWD}"
echo "[model_make.sh] Running: ${CMD[*]}"
echo "[model_make.sh] ENV passthrough: TG_FLAGS='${TG_FLAGS-}', USBGPU='${USBGPU-}', DEV='${DEV-}', AMD_IFACE='${AMD_IFACE-}'"

# sudo 사용 여부 결정 (sudo가 있고 현재 유저가 루트가 아닐 때만)
if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" != "0" ]]; then
  exec sudo --preserve-env=TG_FLAGS,USBGPU,DEV,AMD_IFACE "${CMD[@]}"
else
  exec "${CMD[@]}"
fi
