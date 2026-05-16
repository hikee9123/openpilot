#pragma once

#include <cstdint>
#include <vector>

#include <QString>
#include <QPainter>
#include <QPoint>
#include <QRect>

struct OsmMinimapRoad {
  uint64_t road_id = 0;
  QString name;
  QString highway;
  float x1 = 0.0f;
  float y1 = 0.0f;
  float x2 = 0.0f;
  float y2 = 0.0f;
  bool current = false;
  bool predicted = false;
  bool history = false;
  bool fallback = false;
  bool assist = false;
};

struct OsmMinimapCamera {
  uint64_t camera_id = 0;
  uint64_t road_id = 0;
  QString camera_type;
  int speed_limit_kph = 0;
  float x = 0.0f;
  float y = 0.0f;
  float match_distance_m = 0.0f;
  float match_confidence = 0.0f;
  bool primary_match = false;
  float bearing_deg = -1.0f;
  QString display_class = QStringLiteral("suspicious");
  QString direction_verdict = QStringLiteral("unknown");
  QString reject_reason;
};

struct OsmMinimapData {
  bool available = false;
  QString road;
  float bearing = 0.0f;
  float prediction_distance_m = 0.0f;
  std::vector<OsmMinimapRoad> roads;
  std::vector<OsmMinimapCamera> cameras;

  void clear() {
    available = false;
    road.clear();
    bearing = 0.0f;
    prediction_distance_m = 0.0f;
    roads.clear();
    cameras.clear();
  }
};

class OsmMinimapRenderer {
public:
  void draw(QPainter &p, const QRect &surface, const OsmMinimapData &data, bool enabled, int position,
            float speed_mps, int debug_zoom, int sim_speed_kph, bool debug_zoom_controls, bool debug_speed_controls);
  bool debugZoomControlAt(const QRect &surface, int position, const QPoint &pt, bool debug_zoom_controls, int &delta) const;
  bool debugSpeedControlAt(const QRect &surface, int position, const QPoint &pt, bool debug_speed_controls, int &delta) const;

private:
  double animated_map_radius_m = 230.0;

  QRectF panelRect(const QRect &surface, int position) const;
  QRectF debugZoomInRect(const QRectF &panel) const;
  QRectF debugZoomOutRect(const QRectF &panel) const;
  QRectF debugSpeedUpRect(const QRectF &panel) const;
  QRectF debugSpeedDownRect(const QRectF &panel) const;
  double targetMapRadiusM(float speed_mps, const OsmMinimapData &data, int position, const QRectF &panel) const;
  void drawStatus(QPainter &p, const QRect &surface, const QString &status, int position);
  void drawDebugPredictionDistance(QPainter &p, const QRectF &panel, const OsmMinimapData &data);
  void drawDebugZoomControls(QPainter &p, const QRectF &panel, int debug_zoom);
  void drawDebugSpeedControls(QPainter &p, const QRectF &panel, int sim_speed_kph);
  void drawRoad(QPainter &p, const QRectF &panel, double scale, const OsmMinimapRoad &road, bool centered);
  void drawCamera(QPainter &p, const QRectF &panel, double scale, const OsmMinimapCamera &camera, bool centered);
};
