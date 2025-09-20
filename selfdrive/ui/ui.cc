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

void Device::updateBrightness(const UIState &s) {
  // ------------- 1) 기본 센서 → 화면 밝기 (CIE 1931 + 10~100% 클램프) -------------
  float clipped_brightness = offroad_brightness;  // offroad 기본
  if (s.scene.started && s.scene.light_sensor >= 0) {
    float Y = s.scene.light_sensor;  // 0~100 범위 가정
    // CIE 1931 psychometric lightness
    if (Y <= 8.0f) {
      Y = Y / 903.3f;
    } else {
      Y = std::pow((Y + 16.0f) / 116.0f, 3.0f);
    }
    clipped_brightness = std::clamp(100.0f * Y, 10.0f, 100.0f);
  }

  // ------------- 2) 사용자 오프셋 적용 (Screen Brightness: -10~+10, 0=Auto) -------------
  // 의도: -10은 약 -50% 어둡게, +10은 약 +50% 밝게 (선형이 직관적)
  // factor = 1.0 + step * 0.05  →  [-10..+10] → [0.5..1.5]
  {
    const int user_step = s.scene.custom.brightness;  // -10..+10, 0=Auto
    if (user_step != 0) {
      const float factor = std::clamp(1.0f + (user_step * 0.05f), 0.2f, 2.0f);
      clipped_brightness = std::clamp(clipped_brightness * factor, 1.0f, 100.0f);
    }
  }

  // ------------- 3) 유휴(터치) 감지 & 화면 타임아웃 (Screen Timeout) -------------
  // Screen Timeout: 0=Auto/Off(미사용), N>0 = N*10초
  // touched가 "변할 때"를 터치 이벤트로 판단

  if (s.scene.custom.touched != touched_old) {
    touched_old = s.scene.custom.touched;
    idle_ticks = 0;            // 유휴 시간 리셋
    awake = true;              // 터치하면 즉시 깨움
  } else {
    ++idle_ticks;
  }

  //s.scene.custom.idle_ticks = idle_ticks;
  int timeout_steps = s.scene.custom.autoScreenOff;  // 0 or 1..60 (10초 단위 가정)
  const int64_t ticks_per_10s = static_cast<int64_t>(UI_FREQ) * 10;
  const int64_t timeout_ticks = (timeout_steps > 0) ? timeout_steps * ticks_per_10s : 0;

  // 두 단계: 디밍(마지막 2초) → 화면 꺼짐
  if (timeout_ticks > 0) {
    const int64_t dim_window_ticks = std::min<int64_t>(2 * UI_FREQ, timeout_ticks / 5); // 최대 2초 또는 20% 윈도우
    if (idle_ticks >= timeout_ticks) {
      awake = false;           // 화면 끔
    } else if (idle_ticks >= (timeout_ticks - dim_window_ticks)) {
      // 선형 디밍: 30% → 10%로 서서히 낮춤
      float t = float(idle_ticks - (timeout_ticks - dim_window_ticks)) / float(dim_window_ticks);
      float dim = 0.30f + (0.10f - 0.30f) * t;   // 0.30 → 0.10
      clipped_brightness = std::max(100.0f * dim, 5.0f);
    }
  }

  // ------------- 4) 최종 적용 -------------
  //int brightness = brightness_filter.update(clipped_brightness);
  //if (!awake) brightness = 0;
  // ------------- 4) 최종 적용 (FirstOrderFilter + on/off 페이드) -------------
  int filtered = (int)std::lround(std::clamp(brightness_filter.update(clipped_brightness), 0.0f, 100.0f));

  // 켜짐/꺼짐 목표값 계산: 평상시엔 필터값, 꺼질 땐 0
  int target = awake ? filtered : 0;

  // awake 전환 감지 → 페이드 시작
  if (prev_awake != awake) {
    fade_active = true;
    fade_from = std::max(0, last_brightness < 0 ? (awake ? 0 : filtered) : last_brightness);
    fade_to   = target;
    fade_start = std::chrono::steady_clock::now();

    // 켜짐/꺼짐에 따라 다른 시간 원하면 여기서 분기
    // fade_duration_ms = awake ? 300 : 200;  // 예시
  }
  prev_awake = awake;

  // 페이드 진행
  int to_apply = target;
  if (fade_active) {
    const auto now = std::chrono::steady_clock::now();
    const float t_ms = std::chrono::duration<float, std::milli>(now - fade_start).count();
    float e = smoothstep01(t_ms / float(fade_duration_ms));
    to_apply = (int)std::lround(fade_from + (fade_to - fade_from) * e);

    if (t_ms >= fade_duration_ms) {
      fade_active = false;
      to_apply = fade_to;
    }
  }



  // 실제 하드웨어 반영
  if (to_apply != last_brightness && !brightness_future.isRunning()) {
    brightness_future = QtConcurrent::run(Hardware::set_brightness, to_apply);
    last_brightness = to_apply;
  }
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
