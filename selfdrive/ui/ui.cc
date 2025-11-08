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
    cmd_awake = on;
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
  // ==== 0) 상수 ====
  constexpr float kMinAutoPct      = 10.0f;   // 센서 기반 최소
  constexpr float kMaxPct          = 100.0f;
  constexpr float kMinDimPct       = 5.0f;    // 디밍 최소 하한
  constexpr float kUserStepPct     = 0.05f;   // -10..+10 → ±50%
  constexpr float kDimStartPct     = 0.30f;   // 디밍 시작 상대 밝기
  constexpr float kDimEndPct       = 0.10f;   // 디밍 종료 상대 밝기
  constexpr int   kDeadbandEnter   = 1;       // 히스테리시스 진입
  constexpr int   kDeadbandExit    = 2;       // 히스테리시스 이탈
  constexpr int   kFadeOnMs        = 1000;
  constexpr int   kFadeOffMs       = 30000;

  // ==== 1) 센서 → 기준 밝기 (동일 소스 고정) ====
  const float light_sensor = s.scene.light_sensor;        // 한 프레임 내 일관성
  float base_pct = offroad_brightness;                    // 1..100 가정
  if (s.scene.started && light_sensor >= 0.0f) {
    const float Y01 = cie1931_from_percent(light_sensor); // 0..1
    base_pct = std::clamp(kMaxPct * Y01, kMinAutoPct, kMaxPct);
  }

  // ==== 2) 사용자 오프셋 ====
  const int user_step = s.scene.custom.brightness;        // -10..+10, 0=Auto
  if (user_step != 0) {
    const float factor = std::clamp(1.0f + user_step * kUserStepPct, 0.2f, 2.0f);
    base_pct = std::clamp(base_pct * factor, 1.0f, kMaxPct);
  }

  // ==== 3) 유휴/디밍/타임아웃 ====
  if (s.scene.custom.touched != touched_old) {
    touched_old = s.scene.custom.touched;
    idle_ticks = 0;
    awake = true;
    cmd_awake = true;
  } else {
    ++idle_ticks;
  }
  UIState *pui = uiState();
  pui->scene.custom.idle_ticks = idle_ticks; // 디버깅 공개

  const int timeout_steps = s.scene.custom.autoScreenOff; // 0 or 1..60 (10s 단위)
  const int64_t ticks_per_10s = static_cast<int64_t>(UI_FREQ) * 10;
  const int64_t timeout_ticks = (timeout_steps > 0) ? timeout_steps * ticks_per_10s : 0;

  float clipped_pct = base_pct;
  if (timeout_ticks > 0) {
    int64_t dim_window_ticks = std::min<int64_t>(2 * UI_FREQ, timeout_ticks / 5);
    dim_window_ticks = std::max<int64_t>(1, dim_window_ticks);

    if (idle_ticks >= timeout_ticks) {
      cmd_awake = false; // 화면 끔
      // idle_ticks 포화로 오버플로 방지
      idle_ticks = timeout_ticks;
    } else if (idle_ticks >= (timeout_ticks - dim_window_ticks)) {
      // 30% → 10% 선형 디밍
      const int64_t tnum = idle_ticks - (timeout_ticks - dim_window_ticks);
      const float t = std::clamp(float(tnum) / float(dim_window_ticks), 0.0f, 1.0f);
      const float dim_rel = kDimStartPct + (kDimEndPct - kDimStartPct) * t;
      clipped_pct = std::max(kMaxPct * dim_rel, kMinDimPct);
    }
  }

  // ==== 4) 1차 필터 ====
  const float filtered_f = std::clamp(brightness_filter.update(clipped_pct), 0.0f, kMaxPct);
  int filtered = (int)std::lround(filtered_f);

  // ==== 5) ON/OFF 타겟 ====
  const int limit_light = (light_sensor > 60.0f) ? 5 : 1; // OFF일 때의 강제 하한
  int target = (s.scene.started && !cmd_awake) ? limit_light : filtered;

  // ==== 6) 히스테리시스 데드밴드 ====
  if (last_brightness >= 0) {
    const int diff = std::abs(target - last_brightness);
    // 이전에 같았으면 '이탈' 임계 사용, 아니면 '진입' 임계 사용
    const int thr = (target == last_brightness) ? kDeadbandExit : kDeadbandEnter;
    if (diff <= thr) target = last_brightness;
  }

  // ==== 7) 페이드 (상태 전환 시에만) ====
  if (prev_awake != cmd_awake) {
    fade_active = true;
    const int start_from = (last_brightness >= 0) ? last_brightness : (cmd_awake ? 0 : filtered);
    fade_from  = std::clamp(start_from, 0, 100);
    fade_to    = std::clamp(target, 0, 100);
    fade_start = std::chrono::steady_clock::now();
    fade_duration_ms = cmd_awake ? kFadeOnMs : kFadeOffMs;
  }
  prev_awake = cmd_awake;

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

  pui->scene.custom.target = to_apply; // 관찰 포인트

  // ==== 8) HW 반영 (Throttle & 캐시) ====
  if (to_apply != last_brightness) {
    const auto now = std::chrono::steady_clock::now();
    static auto last_push = now;
    const auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_push).count();
    const bool can_push = (dt_ms >= 40); // 25Hz 이하로 제한

    if (!brightness_future.isRunning() && can_push) {
      brightness_future = QtConcurrent::run(Hardware::set_brightness, to_apply);
      last_brightness = to_apply;
      pending_brightness = -1;
      last_push = now;
    } else {
      pending_brightness = to_apply; // 최신 목표만 유지
    }
  }

  // (선택) 외부 틱에서:
  // if (!brightness_future.isRunning() && pending_brightness >= 0) { ... }
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
