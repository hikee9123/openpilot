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
  float eye_closed_prob = 0.0f;
  float dm_fade_state = 1.0;
  QPixmap dm_img;
  std::vector<vec3> face_kpts_draw;
};
