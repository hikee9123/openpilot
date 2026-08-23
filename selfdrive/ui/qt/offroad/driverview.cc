#include "selfdrive/ui/qt/offroad/driverview.h"

#include <algorithm>

#include <QPainter>
#include <QString>

#include "selfdrive/ui/qt/util.h"

namespace {

QString alertLevelName(cereal::DriverMonitoringState::AlertLevel level) {
  switch (level) {
    case cereal::DriverMonitoringState::AlertLevel::NONE:
      return "NONE";
    case cereal::DriverMonitoringState::AlertLevel::ONE:
      return "ONE";
    case cereal::DriverMonitoringState::AlertLevel::TWO:
      return "TWO";
    case cereal::DriverMonitoringState::AlertLevel::THREE:
      return "THREE";
    default:
      return "UNKNOWN";
  }
}

QString monitoringPolicyName(cereal::DriverMonitoringState::MonitoringPolicy policy) {
  switch (policy) {
    case cereal::DriverMonitoringState::MonitoringPolicy::VISION:
      return "VISION";
    case cereal::DriverMonitoringState::MonitoringPolicy::WHEELTOUCH:
      return "WHEEL";
    default:
      return "UNKNOWN";
  }
}

QString yn(bool value) {
  return value ? "Y" : "N";
}

QString prob(float value) {
  return QString::number(value, 'f', 2);
}

void drawDriverMonitoringPanel(QPainter &p, const QRect &surface_rect,
                               cereal::DriverStateV2::DriverData::Reader driver_data,
                               cereal::DriverMonitoringState::Reader dm_state, bool is_rhd) {
  const auto vision_state = dm_state.getVisionPolicyState();
  const auto distracted_types = vision_state.getDistractedTypes();
  const auto pose = vision_state.getPose();
  const auto blink_debug = vision_state.getBlinkDebugState();

  const bool is_distracted = vision_state.getIsDistracted();
  const bool has_alert = dm_state.getAlertLevel() != cereal::DriverMonitoringState::AlertLevel::NONE;
  const bool has_distracted_type = distracted_types.getPose() || distracted_types.getEye() || distracted_types.getPhone();

  const int panel_margin = 30;
  const int panel_width = std::clamp(surface_rect.width() - panel_margin * 2, 320, 720);
  const int panel_height = 456;
  const QRect panel_rect(surface_rect.x() + panel_margin, surface_rect.y() + panel_margin, panel_width, panel_height);
  const QColor normal_color(235, 235, 235, 235);
  const QColor dim_color(190, 190, 190, 225);
  const QColor good_color(82, 235, 104, 240);
  const QColor warn_color(255, 190, 70, 245);
  const QColor bad_color(255, 95, 95, 245);

  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  p.setRenderHint(QPainter::TextAntialiasing);
  p.setPen(Qt::NoPen);
  p.setBrush(QColor(0, 0, 0, 150));
  p.drawRoundedRect(panel_rect, 18, 18);

  const int x = panel_rect.x() + 24;
  int y = panel_rect.y() + 24;
  const int line_height = 36;

  p.setFont(InterFont(30, QFont::DemiBold));
  p.setPen(normal_color);
  p.drawText(QRect(x, y, panel_width - 48, line_height), Qt::AlignLeft | Qt::AlignVCenter, "Driver Monitoring");
  y += line_height + 8;

  auto draw_line = [&](const QString &text, const QColor &color) {
    p.setFont(InterFont(25, QFont::Medium));
    p.setPen(color);
    p.drawText(QRect(x, y, panel_width - 48, line_height), Qt::AlignLeft | Qt::AlignVCenter, text);
    y += line_height;
  };

  const QColor decision_color = is_distracted || has_alert ? bad_color : good_color;
  draw_line(QString("Decision %1   Alert %2   Aware %3%")
              .arg(is_distracted ? "DISTRACTED" : "OK")
              .arg(alertLevelName(dm_state.getAlertLevel()))
              .arg(vision_state.getAwarenessPercent()),
            decision_color);
  draw_line(QString("Policy %1   RHD %2   Face %3")
              .arg(monitoringPolicyName(dm_state.getActivePolicy()))
              .arg(yn(is_rhd))
              .arg(yn(vision_state.getFaceDetected())),
            dim_color);
  draw_line(QString("Types pose %1   eye %2   phone %3")
              .arg(yn(distracted_types.getPose()))
              .arg(yn(distracted_types.getEye()))
              .arg(yn(distracted_types.getPhone())),
            has_distracted_type ? warn_color : dim_color);
  const float eyes_visible_prob = std::min(driver_data.getLeftEyeProb(), driver_data.getRightEyeProb());
  draw_line(QString("FaceProb %1   EyesVisible %2   Valid %3/%4%")
              .arg(prob(driver_data.getFaceProb()))
              .arg(prob(eyes_visible_prob))
              .arg(yn(blink_debug.getValid()))
              .arg(blink_debug.getValidPercent10s()),
            normal_color);
  draw_line(QString("Raw L/R %1/%2   Effective %3")
              .arg(prob(blink_debug.getRawLeftBlinkProb()))
              .arg(prob(blink_debug.getRawRightBlinkProb()))
              .arg(prob(blink_debug.getEffectiveBlinkProb())),
            normal_color);
  draw_line(QString("State %1   Blink/10s %2   Candidate %3")
              .arg(blink_debug.getEyeClosed() ? "CLOSED" : "OPEN")
              .arg(blink_debug.getBlinkCount10s())
              .arg(yn(blink_debug.getSleepCandidate())),
            blink_debug.getSleepCandidate() ? bad_color : normal_color);
  draw_line(QString("NoBlink %1s   %2   Cand %3   Alert %4")
              .arg(blink_debug.getNoBlinkMillis() / 1000.0, 0, 'f', 1)
              .arg(blink_debug.getNoBlinkWindowReady() ? "READY" : "WAIT")
              .arg(yn(blink_debug.getNoBlinkCandidate()))
              .arg(blink_debug.getNoBlinkAlertEnabled() ? "ON" : "OFF"),
            blink_debug.getNoBlinkCandidate() ? bad_color : normal_color);
  draw_line(QString("Closed %1s   Max/10s %2s   PERCLOS %3%")
              .arg(blink_debug.getCurrentClosureMillis() / 1000.0, 0, 'f', 2)
              .arg(blink_debug.getMaxClosureMillis10s() / 1000.0, 0, 'f', 2)
              .arg(blink_debug.getClosedPercent10s()),
            normal_color);
  draw_line(QString("SleepProb %1   C/O %2/%3   Blink %4-%5ms   Sleep %6s")
              .arg(prob(blink_debug.getSleepProb()))
              .arg(blink_debug.getCloseThresholdPercent())
              .arg(blink_debug.getOpenThresholdPercent())
              .arg(blink_debug.getMinDurationMillis())
              .arg(blink_debug.getMaxBlinkDurationMillis())
              .arg(blink_debug.getSleepCandidateDurationMillis() / 1000.0, 0, 'f', 1),
            dim_color);
  draw_line(QString("Pitch %1   Yaw %2   Uncertainty %3")
              .arg(prob(pose.getPitch()))
              .arg(prob(pose.getYaw()))
              .arg(prob(pose.getUncertainty())),
            normal_color);

  p.restore();
}

void drawDriverMonitoringWaitingPanel(QPainter &p, const QRect &surface_rect) {
  const int panel_margin = 30;
  const int panel_width = std::clamp(surface_rect.width() - panel_margin * 2, 320, 520);
  const QRect panel_rect(surface_rect.x() + panel_margin, surface_rect.y() + panel_margin, panel_width, 100);

  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  p.setRenderHint(QPainter::TextAntialiasing);
  p.setPen(Qt::NoPen);
  p.setBrush(QColor(0, 0, 0, 150));
  p.drawRoundedRect(panel_rect, 18, 18);
  p.setPen(QColor(235, 235, 235, 235));
  p.setFont(InterFont(28, QFont::DemiBold));
  p.drawText(panel_rect.adjusted(24, 0, -24, 0), Qt::AlignLeft | Qt::AlignVCenter, "Driver Monitoring: waiting");
  p.restore();
}

}  // namespace

DriverViewWindow::DriverViewWindow(QWidget* parent) : CameraWidget("camerad", VISION_STREAM_DRIVER, parent) {
  QObject::connect(this, &CameraWidget::clicked, this, &DriverViewWindow::done);
  QObject::connect(device(), &Device::interactiveTimeout, this, [this]() {
    if (isVisible()) {
      emit done();
    }
  });
}

void DriverViewWindow::showEvent(QShowEvent* event) {
  params.putBool("IsDriverViewEnabled", true);
  device()->resetInteractiveTimeout(60);
  CameraWidget::showEvent(event);
}

void DriverViewWindow::hideEvent(QHideEvent* event) {
  params.putBool("IsDriverViewEnabled", false);
  stopVipcThread();
  CameraWidget::hideEvent(event);
}

void DriverViewWindow::paintGL() {
  CameraWidget::paintGL();

  std::lock_guard lk(frame_lock);
  QPainter p(this);
  // startup msg
  if (frames.empty()) {
    p.setPen(Qt::white);
    p.setRenderHint(QPainter::TextAntialiasing);
    p.setFont(InterFont(100, QFont::Bold));
    p.drawText(geometry(), Qt::AlignCenter, tr("camera starting"));
    return;
  }

  const auto &sm = *(uiState()->sm);
  cereal::DriverStateV2::Reader driver_state = sm["driverStateV2"].getDriverStateV2();
  bool is_rhd = driver_state.getWheelOnRightProb() > 0.5;
  auto driver_data = is_rhd ? driver_state.getRightDriverData() : driver_state.getLeftDriverData();

  bool face_detected = driver_data.getFaceProb() > 0.7;
  if (face_detected) {
    auto fxy_list = driver_data.getFacePosition();
    auto std_list = driver_data.getFaceOrientationStd();
    float face_x = fxy_list[0];
    float face_y = fxy_list[1];
    float face_std = std::max(std_list[0], std_list[1]);

    float alpha = 0.7;
    if (face_std > 0.15) {
      alpha = std::max(0.7 - (face_std-0.15)*3.5, 0.0);
    }
    const int box_size = 220;
    // use approx instead of distort_points
    int fbox_x = 1080.0 - 1714.0 * face_x;
    int fbox_y = -135.0 + (504.0 + std::abs(face_x)*112.0) + (1205.0 - std::abs(face_x)*724.0) * face_y;
    p.setPen(QPen(QColor(255, 255, 255, alpha * 255), 10));
    p.drawRoundedRect(fbox_x - box_size / 2, fbox_y - box_size / 2, box_size, box_size, 35.0, 35.0);
  }

  driver_monitor.updateState(*uiState());
  driver_monitor.draw(p, rect());

  if (sm.rcv_frame("driverMonitoringState") > 0) {
    const auto dm_state = sm["driverMonitoringState"].getDriverMonitoringState();
    const bool dm_is_rhd = dm_state.getIsRHD();
    const auto dm_driver_data = dm_is_rhd ? driver_state.getRightDriverData() : driver_state.getLeftDriverData();
    drawDriverMonitoringPanel(p, rect(), dm_driver_data, dm_state, dm_is_rhd);
  } else {
    drawDriverMonitoringWaitingPanel(p, rect());
  }
}

mat4 DriverViewWindow::calcFrameMatrix() {
  const float driver_view_ratio = 2.0;
  const float yscale = stream_height * driver_view_ratio / stream_width;
  const float xscale = yscale * glHeight() / glWidth() * stream_width / stream_height;
  return mat4{{
    xscale,  0.0, 0.0, 0.0,
    0.0,  yscale, 0.0, 0.0,
    0.0,  0.0, 1.0, 0.0,
    0.0,  0.0, 0.0, 1.0,
  }};
}
