#include "selfdrive/ui/qt/onroad/driver_monitoring.h"
#include <algorithm>
#include <cmath>

#include <QString>

#include "selfdrive/ui/qt/onroad/buttons.h"
#include "selfdrive/ui/qt/util.h"

// Default 3D coordinates for face keypoints
static constexpr vec3 DEFAULT_FACE_KPTS_3D[] = {
  {-5.98, -51.20, 8.00}, {-17.64, -49.14, 8.00}, {-23.81, -46.40, 8.00}, {-29.98, -40.91, 8.00}, {-32.04, -37.49, 8.00},
  {-34.10, -32.00, 8.00}, {-36.16, -21.03, 8.00}, {-36.16, 6.40, 8.00}, {-35.47, 10.51, 8.00}, {-32.73, 19.43, 8.00},
  {-29.30, 26.29, 8.00}, {-24.50, 33.83, 8.00}, {-19.01, 41.37, 8.00}, {-14.21, 46.17, 8.00}, {-12.16, 47.54, 8.00},
  {-4.61, 49.60, 8.00}, {4.99, 49.60, 8.00}, {12.53, 47.54, 8.00}, {14.59, 46.17, 8.00}, {19.39, 41.37, 8.00},
  {24.87, 33.83, 8.00}, {29.67, 26.29, 8.00}, {33.10, 19.43, 8.00}, {35.84, 10.51, 8.00}, {36.53, 6.40, 8.00},
  {36.53, -21.03, 8.00}, {34.47, -32.00, 8.00}, {32.42, -37.49, 8.00}, {30.36, -40.91, 8.00}, {24.19, -46.40, 8.00},
  {18.02, -49.14, 8.00}, {6.36, -51.20, 8.00}, {-5.98, -51.20, 8.00},
};

// Colors used for drawing based on monitoring state
static const QColor DMON_ENGAGED_COLOR = QColor::fromRgbF(0.1, 0.945, 0.26);
static const QColor DMON_DISENGAGED_COLOR = QColor::fromRgbF(0.545, 0.545, 0.545);
static constexpr int DROWSY_BACKGROUND_MIN_CLOSURE_MS = 2000;

DriverMonitorRenderer::DriverMonitorRenderer() : face_kpts_draw(std::size(DEFAULT_FACE_KPTS_3D)) {
  dm_img = loadPixmap("../assets/icons/driver_face.png", {img_size + 5, img_size + 5});
}

void DriverMonitorRenderer::updateState(const UIState &s) {
  auto &sm = *(s.sm);
  auto dm_state = sm["driverMonitoringState"].getDriverMonitoringState();
  is_active = dm_state.getActivePolicy() == cereal::DriverMonitoringState::MonitoringPolicy::VISION;
  is_rhd = dm_state.getIsRHD();
  alert_level = static_cast<int>(dm_state.getAlertLevel());
  const auto vision_state = dm_state.getVisionPolicyState();
  face_detected = vision_state.getFaceDetected();
  eye_distracted = vision_state.getDistractedTypes().getEye();
  const auto blink_debug = vision_state.getBlinkDebugState();
  blink_debug_enabled = blink_debug.getEnabled();
  blink_debug_valid = blink_debug.getValid();
  blink_eye_closed = blink_debug.getEyeClosed();
  sleep_candidate = blink_debug.getSleepCandidate();
  no_blink_candidate = blink_debug.getNoBlinkCandidate();
  no_blink_window_ready = blink_debug.getNoBlinkWindowReady();
  no_blink_alert_enabled = blink_debug.getNoBlinkAlertEnabled();
  blink_count_10s = blink_debug.getBlinkCount10s();
  no_blink_ms = blink_debug.getNoBlinkMillis();
  current_closure_ms = blink_debug.getCurrentClosureMillis();
  max_closure_ms_10s = blink_debug.getMaxClosureMillis10s();
  closed_percent_10s = blink_debug.getClosedPercent10s();
  valid_percent_10s = blink_debug.getValidPercent10s();
  raw_left_blink_prob = blink_debug.getRawLeftBlinkProb();
  raw_right_blink_prob = blink_debug.getRawRightBlinkProb();
  effective_blink_prob = blink_debug.getEffectiveBlinkProb();
  sleep_prob = blink_debug.getSleepProb();
  close_threshold_percent = blink_debug.getCloseThresholdPercent();
  open_threshold_percent = blink_debug.getOpenThresholdPercent();
  min_duration_ms = blink_debug.getMinDurationMillis();
  max_blink_duration_ms = blink_debug.getMaxBlinkDurationMillis();
  sleep_candidate_duration_ms = blink_debug.getSleepCandidateDurationMillis();
  const bool alert_visible = sm["selfdriveState"].getSelfdriveState().getAlertSize() != cereal::SelfdriveState::AlertSize::NONE;
  is_visible = sm.rcv_frame("driverStateV2") > s.scene.started_frame && (!alert_visible || blink_debug_enabled);
  if (!is_visible) return;
  dm_fade_state = std::clamp(dm_fade_state + 0.2f * (0.5f - is_active), 0.0f, 1.0f);

  const auto &driverstate = sm["driverStateV2"].getDriverStateV2();
  const auto driver_data = is_rhd ? driverstate.getRightDriverData() : driverstate.getLeftDriverData();
  const auto driver_orient = driver_data.getFaceOrientation();
  eye_closed_prob = std::clamp((driver_data.getLeftBlinkProb() + driver_data.getRightBlinkProb()) * 0.5f, 0.0f, 1.0f);

  for (int i = 0; i < 3; ++i) {
    float v_this = (i == 0 ? (driver_orient[i] < 0 ? 0.7 : 0.9) : 0.4) * driver_orient[i];
    driver_pose_diff[i] = std::abs(driver_pose_vals[i] - v_this);
    driver_pose_vals[i] = 0.8f * v_this + (1 - 0.8) * driver_pose_vals[i];
    driver_pose_sins[i] = std::sin(driver_pose_vals[i] * (1.0f - dm_fade_state));
    driver_pose_coss[i] = std::cos(driver_pose_vals[i] * (1.0f - dm_fade_state));
  }

  auto [sin_y, sin_x, sin_z] = driver_pose_sins;
  auto [cos_y, cos_x, cos_z] = driver_pose_coss;

  // Rotation matrix for transforming face keypoints based on driver's head orientation
  const mat3 r_xyz = {{
    cos_x * cos_z, cos_x * sin_z, -sin_x,
    -sin_y * sin_x * cos_z - cos_y * sin_z, -sin_y * sin_x * sin_z + cos_y * cos_z, -sin_y * cos_x,
    cos_y * sin_x * cos_z - sin_y * sin_z, cos_y * sin_x * sin_z + sin_y * cos_z, cos_y * cos_x,
  }};

  // Transform vertices
  for (int i = 0; i < face_kpts_draw.size(); ++i) {
    vec3 kpt = matvecmul3(r_xyz, DEFAULT_FACE_KPTS_3D[i]);
    face_kpts_draw[i] = {{kpt.v[0], kpt.v[1], kpt.v[2] * (1.0f - dm_fade_state) + 8 * dm_fade_state}};
  }
}

void DriverMonitorRenderer::draw(QPainter &painter, const QRect &surface_rect) {
  if (!is_visible) return;

  painter.save();

  int offset = UI_BORDER_SIZE + btn_size / 2;
  float x = is_rhd ? surface_rect.width() - offset : offset;
  float y = surface_rect.height() - offset;
  float opacity = is_active ? 0.65f : 0.2f;

  drawIcon(painter, QPoint(x, y), dm_img, QColor(0, 0, 0, 70), opacity);

  QPointF keypoints[std::size(DEFAULT_FACE_KPTS_3D)];
  for (int i = 0; i < std::size(keypoints); ++i) {
    const auto &v = face_kpts_draw[i].v;
    float kp = (v[2] - 8) / 120.0f + 1.0f;
    keypoints[i] = QPointF(v[0] * kp + x, v[1] * kp + y);
  }

  painter.setPen(QPen(QColor::fromRgbF(1.0, 1.0, 1.0, opacity), 5.2, Qt::SolidLine, Qt::RoundCap));
  painter.drawPolyline(keypoints, std::size(keypoints));

  // tracking arcs
  const int arc_l = 133;
  const float arc_t_default = 6.7f;
  const float arc_t_extend = 12.0f;
  QColor arc_color = uiState()->engaged() ? DMON_ENGAGED_COLOR : DMON_DISENGAGED_COLOR;
  arc_color.setAlphaF(0.4 * (1.0f - dm_fade_state));

  const QRectF eye_rect(x - 86, y - btn_size / 2 - 54, 172, 46);
  painter.setPen(Qt::NoPen);
  painter.setBrush(QColor(0, 0, 0, 140));
  painter.drawRoundedRect(eye_rect, 12, 12);
  painter.setFont(InterFont(30, QFont::DemiBold));
  const bool show_eye_prob = is_active && face_detected;
  painter.setPen(show_eye_prob && eye_distracted ? QColor(255, 95, 95) : QColor(255, 255, 255, 230));
  const QString eye_text = show_eye_prob ?
                             QString("EYE %1%").arg(static_cast<int>(std::lround(eye_closed_prob * 100.0f))) : "EYE --";
  painter.drawText(eye_rect, Qt::AlignCenter, eye_text);

  if (blink_debug_enabled) {
    const int panel_width = 510;
    const int panel_height = 270;
    const int panel_x = is_rhd ? surface_rect.right() - UI_BORDER_SIZE - panel_width + 1 : surface_rect.left() + UI_BORDER_SIZE;
    const int panel_y = std::max(surface_rect.top() + UI_BORDER_SIZE,
                                 static_cast<int>(eye_rect.top()) - panel_height - 18);
    const QRectF panel_rect(panel_x, panel_y, panel_width, panel_height);
    const bool long_closure_candidate = sleep_candidate &&
                                        current_closure_ms > DROWSY_BACKGROUND_MIN_CLOSURE_MS;
    const bool candidate_policy_active = no_blink_candidate || long_closure_candidate;
    const bool warning_active = alert_level > 0;
    const bool candidate_debug_active = candidate_policy_active && !warning_active;
    const QString panel_state = warning_active ? QString("WARNING L%1").arg(alert_level) :
                                candidate_debug_active ? QString("CAND DEBUG") :
                                no_blink_alert_enabled ? QString("ARMED") : QString("DEBUG");

    painter.setPen(QPen(candidate_debug_active ? QColor(255, 170, 55, 230) : QColor(160, 170, 180, 150),
                        candidate_debug_active ? 5 : 2));
    const QColor warning_background = alert_level >= 3 ?
                                        QColor(155, 35, 35, 230) : QColor(205, 100, 0, 230);
    painter.setBrush(warning_active ? warning_background : QColor(0, 0, 0, 205));
    painter.drawRoundedRect(panel_rect, 18, 18);

    const int text_x = panel_x + 22;
    int text_y = panel_y + 14;
    const int text_width = panel_width - 44;
    const int line_height = 34;
    auto draw_debug_line = [&](const QString &text, const QColor &color, bool heading = false) {
      painter.setFont(InterFont(heading ? 26 : 23, heading ? QFont::DemiBold : QFont::Medium));
      painter.setPen(color);
      painter.drawText(QRect(text_x, text_y, text_width, line_height), Qt::AlignLeft | Qt::AlignVCenter, text);
      text_y += line_height;
    };

    const QColor normal_color(235, 235, 235, 240);
    const QColor dim_color(190, 195, 200, 235);
    const QColor good_color(82, 235, 104, 245);
    const QColor warn_color(255, 190, 70, 245);
    const QColor bad_color(255, 95, 95, 245);
    draw_debug_line(QString("DM %1   %2 %3%")
                      .arg(panel_state)
                      .arg(blink_debug_valid ? "VALID" : "INVALID")
                      .arg(valid_percent_10s),
                    blink_debug_valid ? good_color : warn_color, true);
    draw_debug_line(QString("Raw L/R %1/%2%   Effective %3%")
                      .arg(static_cast<int>(std::lround(raw_left_blink_prob * 100.0f)))
                      .arg(static_cast<int>(std::lround(raw_right_blink_prob * 100.0f)))
                      .arg(static_cast<int>(std::lround(effective_blink_prob * 100.0f))), normal_color);
    draw_debug_line(QString("State %1   Blink/10s %2")
                      .arg(blink_eye_closed ? "CLOSED" : "OPEN")
                      .arg(blink_count_10s), blink_eye_closed ? warn_color : normal_color);
    draw_debug_line(QString("No Blink %1s   Window %2   Link %3")
                      .arg(no_blink_ms / 1000.0, 0, 'f', 1)
                      .arg(no_blink_window_ready ? "READY" : "WAIT")
                      .arg(no_blink_alert_enabled ? "WARNING" : "DEBUG"),
                    no_blink_candidate ? bad_color : normal_color);
    draw_debug_line(QString("Closed %1s   Max/10s %2s")
                      .arg(current_closure_ms / 1000.0, 0, 'f', 2)
                      .arg(max_closure_ms_10s / 1000.0, 0, 'f', 2), normal_color);
    draw_debug_line(QString("PERCLOS %1%   SleepProb %2%")
                      .arg(closed_percent_10s)
                      .arg(static_cast<int>(std::lround(sleep_prob * 100.0f))), normal_color);
    draw_debug_line(QString("Cand S:%1 N:%2 C%3/%4 B%5-%6 T%7")
                      .arg(sleep_candidate ? "Y" : "N")
                      .arg(no_blink_candidate ? "Y" : "N")
                      .arg(close_threshold_percent)
                      .arg(open_threshold_percent)
                      .arg(min_duration_ms)
                      .arg(max_blink_duration_ms)
                      .arg(sleep_candidate_duration_ms / 1000.0, 0, 'f', 1),
                    (long_closure_candidate || no_blink_candidate) ? bad_color : dim_color);
  }

  float delta_x = -driver_pose_sins[1] * arc_l / 2.0f;
  float delta_y = -driver_pose_sins[0] * arc_l / 2.0f;

  // Draw horizontal tracking arc
  painter.setPen(QPen(arc_color, arc_t_default + arc_t_extend * std::min(1.0, driver_pose_diff[1] * 5.0), Qt::SolidLine, Qt::RoundCap));
  painter.drawArc(QRectF(std::min(x + delta_x, x), y - arc_l / 2, std::abs(delta_x), arc_l), (driver_pose_sins[1] > 0 ? 90 : -90) * 16, 180 * 16);

  // Draw vertical tracking arc
  painter.setPen(QPen(arc_color, arc_t_default + arc_t_extend * std::min(1.0, driver_pose_diff[0] * 5.0), Qt::SolidLine, Qt::RoundCap));
  painter.drawArc(QRectF(x - arc_l / 2, std::min(y + delta_y, y), arc_l, std::abs(delta_y)), (driver_pose_sins[0] > 0 ? 0 : 180) * 16, 180 * 16);

  painter.restore();
}
