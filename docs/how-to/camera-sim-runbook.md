# Camera Simulation Runbook

이 문서는 C3x 실제 기기와 PC 개발 환경에서 카메라 관련 실행 방법을 정리합니다.

## 공통 준비

openpilot repo 루트에서 실행합니다.

```bash
cd /home/bhcho/openpilot
```

기존 실행 프로세스가 남아 있으면 먼저 종료합니다.

```bash
pkill -f 'launch_chffrplus|manager.py|tools.webcam.camerad|tools.cam_sim.road_camerad|tools.cam_sim.dm_simd|selfdrive.ui.ui'
```

PC에서 빌드할 때 시스템 Python 의존성 오류가 나면 repo 가상환경을 우선 사용합니다.

```bash
PATH=/home/bhcho/openpilot/.venv/bin:$PATH scons -j$(nproc)
```

## C3x 실제 기기 기본 실행

```bash
./launch_openpilot.sh
```

동작:

- C3x에서는 기존 native `camerad`를 사용합니다.
- `CAM_SIM`을 지정하지 않으면 PC 카메라 시뮬레이션 프로세스는 실행되지 않습니다.

## PC Web Cam 실행

기본 Web Cam 장치가 `/dev/video0`인 경우:

```bash
env -u DEBUG BIG=1 CAM_SIM=webcam ROAD_CAM=0 ./launch_openpilot.sh
```

Web Cam 장치가 `/dev/video1`인 경우:

```bash
env -u DEBUG BIG=1 CAM_SIM=webcam ROAD_CAM=1 ./launch_openpilot.sh
```

동작:

- `webcamerad`가 `ROAD_CAM` 장치를 road camera로 publish합니다.
- native `camerad`는 비활성화됩니다.
- `dm_simd`가 PC 시뮬레이션용 `driverStateV2`와 `driverMonitoringState`를 publish합니다.
- UI의 DM icon은 표시되지만 실제 얼굴 인식 모델 결과는 아닙니다.

## PC 합성 Road Camera 실행

실제 Web Cam 없이 합성 road camera 화면만 보고 싶을 때 사용합니다.

```bash
env -u DEBUG BIG=1 CAM_SIM=road ./launch_openpilot.sh
```

동작:

- `roadcam_simd`가 synthetic road camera frame을 publish합니다.
- native `camerad`와 `webcamerad`는 실행되지 않습니다.

## 기존 WebCam 방식

기존 openpilot WebCam 실행 방식도 유지됩니다.

```bash
env -u DEBUG BIG=1 USE_WEBCAM=1 ROAD_CAM=0 ./launch_openpilot.sh
```

현재 PC UI 시뮬레이션 테스트에는 `CAM_SIM=webcam` 방식을 권장합니다.

## 상태 확인

실행 중인 주요 프로세스를 확인합니다.

```bash
pgrep -af 'launch_chffrplus|manager.py|webcam.camerad|road_camerad|dm_simd|selfdrive.ui.ui'
```

Web Cam 장치 목록을 확인합니다.

```bash
ls -l /dev/video*
```

최근 실행 로그를 확인합니다.

```bash
tail -n 100 /tmp/openpilot_webcam_run.log
```

## 참고

- `CAM_SIM=webcam`은 PC 개발용 실행 모드입니다.
- `CAM_SIM=road`는 Web Cam 없이 UI road 화면 흐름을 확인하는 모드입니다.
- TPMS는 `carState.carSCustom.tpms` 값과 UI custom `tpms` 토글이 있어야 표시됩니다. 현재 PC camera sim 기본 실행은 실제 차량 CAN 기반 TPMS 값을 publish하지 않습니다.
