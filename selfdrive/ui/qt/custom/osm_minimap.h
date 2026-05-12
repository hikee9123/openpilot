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

struct OsmMinimapData {
  bool available = false;
  QString road;
  float bearing = 0.0f;
  std::vector<OsmMinimapRoad> roads;

  void clear() {
    available = false;
    road.clear();
    bearing = 0.0f;
    roads.clear();
  }
};

class OsmMinimapRenderer {
public:
  void draw(QPainter &p, const QRect &surface, const OsmMinimapData &data, bool enabled, int position,
            float speed_mps, int debug_zoom, bool debug_zoom_controls);
  bool debugZoomControlAt(const QRect &surface, int position, const QPoint &pt, bool debug_zoom_controls, int &delta) const;

private:
  double animated_map_radius_m = 230.0;

  QRectF panelRect(const QRect &surface, int position) const;
  QRectF debugZoomInRect(const QRectF &panel) const;
  QRectF debugZoomOutRect(const QRectF &panel) const;
  double targetMapRadiusM(float speed_mps, const OsmMinimapData &data, int position, const QRectF &panel) const;
  void drawStatus(QPainter &p, const QRect &surface, const QString &status, int position);
  void drawDebugZoomControls(QPainter &p, const QRectF &panel, int debug_zoom);
  void drawRoad(QPainter &p, const QRectF &panel, double scale, const OsmMinimapRoad &road, bool centered);
};
