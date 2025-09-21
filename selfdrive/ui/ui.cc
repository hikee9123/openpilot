#include "selfdrive/ui/ui.h"

#include <algorithm>
#include <cmath>

#include <QtConcurrent>

#include "common/transformations/orientation.hpp"
#include "common/swaglog.h"
#include "common/util.h"
#include "common/watchdog.h"
#include "system/hardware/hw.h"

#define BACKLIGHT_DT 0.05
#define BACKLIGHT_TS 10.00

static void update_sockets(UIState *s) {
  s->sm->update(0);
}

static void update_state(UIState *s) {
  SubMaster &sm = *(s->sm);
  UIScene &scene = s->scene;

  if (sm.updated("liveCalibration")) {
    auto list2rot = [](const capnp::List<float>::Reader &rpy_list) ->Eigen::Matrix3f {
      return euler2rot({rpy_list[0], rpy_list[1], rpy_list[2]}).cast<float>();
    };

    auto live_calib = sm["liveCalibration"].getLiveCalibration();
    if (live_calib.getCalStatus() == cereal::LiveCalibrationData::Status::CALIBRATED) {
      auto device_from_calib = list2rot(live_calib.getRpyCalib());
      auto wide_from_device = list2rot(live_calib.getWideFromDeviceEuler());
      s->scene.view_from_calib = VIEW_FROM_DEVICE * device_from_calib;
      s->scene.view_from_wide_calib = VIEW_FROM_DEVICE * wide_from_device * device_from_calib;
    } else {
      s->scene.view_from_calib = s->scene.view_from_wide_calib = VIEW_FROM_DEVICE;
    }
  }
  if (sm.updated("pandaStates")) {
    auto pandaStates = sm["pandaStates"].getPandaStates();
    if (pandaStates.size() > 0) {
      scene.pandaType = pandaStates[0].getPandaType();

      if (scene.pandaType != cereal::PandaState::PandaType::UNKNOWN) {
        scene.ignition = false;
        for (const auto& pandaState : pandaStates) {
          scene.ignition |= pandaState.getIgnitionLine() || pandaState.getIgnitionCan();
        }
      }
    }
  } else if ((s->sm->frame - s->sm->rcv_frame("pandaStates")) > 5*UI_FREQ) {
    scene.pandaType = cereal::PandaState::PandaType::UNKNOWN;
  }
  if (sm.updated("wideRoadCameraState")) {
    auto cam_state = sm["wideRoadCameraState"].getWideRoadCameraState();
    scene.light_sensor = std::max(100.0f - cam_state.getExposureValPercent(), 0.0f);
  } else if (!sm.allAliveAndValid({"wideRoadCameraState"})) {
    scene.light_sensor = -1;
  }
  scene.started = sm["deviceState"].getDeviceState().getStarted() && scene.ignition;

  auto params = Params();
  scene.recording_audio = params.getBool("RecordAudio") && scene.started;
}

void ui_update_params(UIState *s) {
  auto params = Params();
  s->scene.is_metric = params.getBool("IsMetric");
}

void UIState::updateStatus() {
  if (scene.started && sm->updated("selfdriveState")) {
    auto ss = (*sm)["selfdriveState"].getSelfdriveState();
    auto state = ss.getState();
    if (state == cereal::SelfdriveState::OpenpilotState::PRE_ENABLED || state == cereal::SelfdriveState::OpenpilotState::OVERRIDING) {
      status = STATUS_OVERRIDE;
    } else {
      status = ss.getEnabled() ? STATUS_ENGAGED : STATUS_DISENGAGED;
    }
  }

  if (engaged() != engaged_prev) {
    engaged_prev = engaged();
    emit engagedChanged(engaged());
  }

  // Handle onroad/offroad transition
  if (scene.started != started_prev || sm->frame == 1) {
    if (scene.started) {
      status = STATUS_DISENGAGED;
      scene.started_frame = sm->frame;
    }
    started_prev = scene.started;
    emit offroadTransition(!scene.started);
  }
}

UIState::UIState(QObject *parent) : QObject(parent) {
  sm = std::make_unique<SubMaster>(std::vector<const char*>{
    "modelV2", "controlsState", "liveCalibration", "radarState", "deviceState",
    "pandaStates", "carParams", "driverMonitoringState", "carState", "driverStateV2",
    "wideRoadCameraState", "managerState", "selfdriveState", "longitudinalPlan",
    "peripheralState", // #custom
  });
  prime_state = new PrimeState(this);
  language = QString::fromStdString(Params().get("LanguageSetting"));

  // update timer
  timer = new QTimer(this);
  QObject::connect(timer, &QTimer::timeout, this, &UIState::update);
  timer->start(1000 / UI_FREQ);
}

void UIState::update() {
  update_sockets(this);
  update_state(this);
  updateStatus();

  if (sm->frame % UI_FREQ == 0) {
    watchdog_kick(nanos_since_boot());
  }
  emit uiUpdate(*this);
}

Device::Device(QObject *parent) : brightness_filter(BACKLIGHT_OFFROAD, BACKLIGHT_TS, BACKLIGHT_DT), QObject(parent) {
  setAwake(true);
  resetInteractiveTimeout();

  QObject::connect(uiState(), &UIState::uiUpdate, this, &Device::update);
}

void Device::update(const UIState &s) {
  updateBrightness(s);
  updateWakefulness(s);
}

void Device::setAwake(bool on) {
  if (on != awake) {
    awake = on;
    Hardware::set_display_power(awake);
    LOGD("setting display power %d", awake);
    emit displayPowerChanged(awake);
  }
}

void Device::resetInteractiveTimeout(int timeout) {
  if (timeout == -1) {
    timeout = (ignition_on ? 10 : 30);
  }
  interactive_timeout = timeout * UI_FREQ;
}


// 부드러운 이징: smoothstep(0..1)
static inline float smoothstep01(float t) {
  t = std::clamp(t, 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}

// 지각 밝기(CIE 1931) 보정: 입력 0..100 → 0..1
static inline float cie1931_from_percent(float Ypct) {
  if (!std::isfinite(Ypct)) return 0.0f;
  float Y = std::clamp(Ypct, 0.0f, 100.0f);
  if (Y <= 8.0f) {
    return Y / 903.3f;
  } else {
    return std::pow((Y + 16.0f) / 116.0f, 3.0f);
  }
}

void Device::updateBrightness(const UIState &s) {
  // ------------- 1) 센서 → 화면 밝기 (CIE 1931 + 10~100%) -------------
  float clipped_brightness = offroad_brightness;  // offroad 기본 (1..100 가정)
  if (s.scene.started && s.scene.light_sensor >= 0) {
    const float Y01 = cie1931_from_percent(s.scene.light_sensor); // 0..1
    clipped_brightness = std::clamp(100.0f * Y01, 10.0f, 100.0f);
  }

  // ------------- 2) 사용자 오프셋 (-10..+10 → 0.5..1.5) -------------
  {
    const int user_step = s.scene.custom.brightness;  // -10..+10, 0=Auto
    if (user_step != 0) {
      const float factor = std::clamp(1.0f + (user_step * 0.05f), 0.2f, 2.0f);
      clipped_brightness = std::clamp(clipped_brightness * factor, 1.0f, 100.0f);
    }
  }

  // ------------- 3) 유휴 감지 & 화면 타임아웃 -------------
  // touched 플립을 '터치'로 간주
  if (s.scene.custom.touched != touched_old) {
    touched_old = s.scene.custom.touched;
    idle_ticks = 0;
    awake = true; // 즉시 깨움
  } else {
    ++idle_ticks;
  }

  UIState *pui = uiState();
  pui->scene.custom.idle_ticks = idle_ticks;

  const int timeout_steps = s.scene.custom.autoScreenOff;  // 0 or 1..60 (10초 단위)
  const int64_t ticks_per_10s = static_cast<int64_t>(UI_FREQ) * 10;
  const int64_t timeout_ticks = (timeout_steps > 0) ? timeout_steps * ticks_per_10s : 0;

  if (timeout_ticks > 0) {
    // 디밍 윈도우: 최대 2초 또는 전체의 20% 중 작은 값, 최소 1틱 보장
    int64_t dim_window_ticks = std::min<int64_t>(2 * UI_FREQ, timeout_ticks / 5);
    dim_window_ticks = std::max<int64_t>(1, dim_window_ticks);

    if (idle_ticks >= timeout_ticks) {
      awake = false; // 화면 끔
    } else if (idle_ticks >= (timeout_ticks - dim_window_ticks)) {
      // 30% → 10% 선형 디밍
      const int64_t tnum = idle_ticks - (timeout_ticks - dim_window_ticks);
      const float t = std::clamp(float(tnum) / float(dim_window_ticks), 0.0f, 1.0f);
      const float dim = 0.30f + (0.10f - 0.30f) * t;   // 0.30 → 0.10
      clipped_brightness = std::max(100.0f * dim, 5.0f);
    }
  }

  // ------------- 4) 1차 필터 + on/off 페이드 -------------
  // 1) FirstOrderFilter 출력을 0..100으로 제한
  const float filtered_f = std::clamp(brightness_filter.update(clipped_brightness), 0.0f, 100.0f);
  const int filtered = (int)std::lround(filtered_f);

  // 2) 켜짐/꺼짐 목표값
  int target = awake ? filtered : 5;
  pui->scene.custom.target = target;
  // 3) Deadband로 소진동 제거 (±1% 이내는 무시)
  if (last_brightness >= 0) {
    if (std::abs(target - last_brightness) <= 1) {
      target = last_brightness;
    }
  }

  // 4) 상태 전환시 페이드 시퀀스 재시작 (중간값에서 이어가기)
  if (prev_awake != awake) {
    fade_active = true;
    // last_brightness가 유효하면 그 값에서 시작, 아니면 논리적 시작점
    const int start_from = (last_brightness >= 0) ? last_brightness : (awake ? 0 : filtered);
    fade_from  = std::clamp(start_from, 0, 100);
    fade_to    = std::clamp(target, 0, 100);
    fade_start = std::chrono::steady_clock::now();
    // 필요시 서로 다른 시간 적용 가능
    fade_duration_ms = awake ? 300 : 5000;
  }
  prev_awake = awake;

  int to_apply = target;
  if (fade_active) {
    const auto now = std::chrono::steady_clock::now();
    const float t_ms = std::chrono::duration<float, std::milli>(now - fade_start).count();
    const float e = smoothstep01(t_ms / float(std::max(1, fade_duration_ms)));
    to_apply = (int)std::lround(fade_from + (fade_to - fade_from) * e);

    if (t_ms >= fade_duration_ms) {
      fade_active = false;
      to_apply = fade_to;
    }
  }

  // ------------- 5) 실제 하드웨어 반영 (스큐/중복 방지) -------------
  // future 실행 중이면 직전 값과 동일 변화는 스킵하고, 목표를 캐시
  // (watcher 등에서 future 완료시 캐시를 반영하는 패턴 추천)
  if (to_apply != last_brightness) {
    if (!brightness_future.isRunning()) {
      brightness_future = QtConcurrent::run(Hardware::set_brightness, to_apply);
      last_brightness = to_apply;
      pending_brightness = -1; // 캐시 클리어
    } else {
      // 실행 중이면 최신 목표만 저장해두고 중복 호출 방지
      pending_brightness = to_apply;
    }
  }

  // (선택) 어디선가 주기적으로 호출되는 틱/타이머에서 future 완료 체크 후 반영:
  // if (!brightness_future.isRunning() && pending_brightness >= 0) {
  //   int v = pending_brightness; pending_brightness = -1;
  //   brightness_future = QtConcurrent::run(Hardware::set_brightness, v);
  //   last_brightness = v;
  // }
}


void Device::updateWakefulness(const UIState &s) {
  bool ignition_just_turned_off = !s.scene.ignition && ignition_on;
  ignition_on = s.scene.ignition;

  if (ignition_just_turned_off) {
    resetInteractiveTimeout();
  } else if (interactive_timeout > 0 && --interactive_timeout == 0) {
    emit interactiveTimeout();
  }

  setAwake(s.scene.ignition || interactive_timeout > 0);
}

UIState *uiState() {
  static UIState ui_state;
  return &ui_state;
}

Device *device() {
  static Device _device;
  return &_device;
}
