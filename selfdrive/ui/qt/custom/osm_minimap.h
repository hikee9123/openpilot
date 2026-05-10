#pragma once

#include <cstdint>
#include <vector>

#include <QString>
#include <QPainter>
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
  void draw(QPainter &p, const QRect &surface, const OsmMinimapData &data, bool enabled, int position);

private:
  QRectF panelRect(const QRect &surface, int position) const;
  void drawStatus(QPainter &p, const QRect &surface, const QString &status, int position);
  void drawRoad(QPainter &p, const QRectF &panel, double scale, const OsmMinimapRoad &road);
};
