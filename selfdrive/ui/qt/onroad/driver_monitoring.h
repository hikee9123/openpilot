#pragma once

#include <vector>
#include <QPainter>
#include "selfdrive/ui/ui.h"

class DriverMonitorRenderer {
public:
  DriverMonitorRenderer();
  void updateState(const UIState &s);
  void draw(QPainter &painter, const QRect &surface_rect);

private:
  float driver_pose_vals[3] = {};
  float driver_pose_diff[3] = {};
  float driver_pose_sins[3] = {};
  float driver_pose_coss[3] = {};
  bool is_visible = false;
  bool is_active = false;
  bool is_rhd = false;
  bool face_detected = false;
  bool eye_distracted = false;
  bool blink_debug_enabled = false;
  bool blink_debug_valid = false;
  bool blink_eye_closed = false;
  bool sleep_candidate = false;
  bool no_blink_candidate = false;
  bool no_blink_window_ready = false;
  bool no_blink_alert_enabled = false;
  int blink_count_10s = 0;
  int no_blink_ms = 0;
  int current_closure_ms = 0;
  int max_closure_ms_10s = 0;
  int closed_percent_10s = 0;
  int valid_percent_10s = 0;
  int close_threshold_percent = 0;
  int open_threshold_percent = 0;
  int min_duration_ms = 0;
  int long_closure_ms = 0;
  float raw_left_blink_prob = 0.0f;
  float raw_right_blink_prob = 0.0f;
  float effective_blink_prob = 0.0f;
  float sleep_prob = 0.0f;
  float eye_closed_prob = 0.0f;
  float dm_fade_state = 1.0;
  QPixmap dm_img;
  std::vector<vec3> face_kpts_draw;
};
