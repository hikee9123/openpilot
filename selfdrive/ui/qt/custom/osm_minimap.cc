#include "selfdrive/ui/qt/custom/osm_minimap.h"

#include <algorithm>

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainterPath>

#include "selfdrive/ui/qt/util.h"

namespace {

constexpr double kMapRadiusM = 230.0;

QPointF projectPoint(const QRectF &panel, double scale, double forward_m, double right_m) {
  const QPointF origin(panel.center().x(), panel.bottom() - 58.0);
  return {origin.x() + right_m * scale, origin.y() - forward_m * scale};
}

bool pointNearPanel(const QRectF &panel, const QPointF &point) {
  return panel.adjusted(-30.0, -30.0, 30.0, 30.0).contains(point);
}

QString roadName(const QJsonObject &road) {
  return road.value("name").toString().left(32);
}

}  // namespace

void OsmMinimapRenderer::draw(QPainter &p, const QRect &surface, const QString &payload) {
  if (payload.isEmpty()) return;

  const QJsonDocument doc = QJsonDocument::fromJson(payload.toUtf8());
  if (!doc.isObject()) return;

  const QJsonObject root = doc.object();
  const QJsonArray roads = root.value("mapRoads").toArray();
  if (roads.isEmpty()) return;

  const int panel_w = std::clamp(surface.width() / 4, 310, 390);
  const int panel_h = std::clamp(surface.height() / 4, 250, 330);
  const QRectF panel(surface.right() - panel_w - 44, surface.bottom() - panel_h - 44, panel_w, panel_h);
  const double scale = std::min(panel.width(), panel.height()) / (2.0 * kMapRadiusM);

  p.save();
  p.setRenderHint(QPainter::Antialiasing, true);
  p.setPen(Qt::NoPen);
  p.setBrush(QColor(0, 0, 0, 150));
  p.drawRoundedRect(panel, 18, 18);

  p.setPen(QPen(QColor(255, 255, 255, 42), 1));
  p.drawLine(QPointF(panel.center().x(), panel.top() + 40), QPointF(panel.center().x(), panel.bottom() - 24));
  p.drawLine(QPointF(panel.left() + 18, panel.bottom() - 58), QPointF(panel.right() - 18, panel.bottom() - 58));

  for (const QJsonValue &value : roads) {
    if (value.isObject()) drawRoad(p, panel, scale, value.toObject());
  }

  const QPointF ego(panel.center().x(), panel.bottom() - 58.0);
  QPainterPath ego_path;
  ego_path.moveTo(ego.x(), ego.y() - 15);
  ego_path.lineTo(ego.x() + 11, ego.y() + 13);
  ego_path.lineTo(ego.x(), ego.y() + 7);
  ego_path.lineTo(ego.x() - 11, ego.y() + 13);
  ego_path.closeSubpath();
  p.setPen(QPen(QColor(10, 10, 10, 190), 3));
  p.setBrush(QColor(255, 255, 255, 235));
  p.drawPath(ego_path);

  const QString title = root.value("road").toString().isEmpty() ? QStringLiteral("OSM roads") : root.value("road").toString();
  p.setFont(InterFont(24, QFont::DemiBold));
  p.setPen(QColor(245, 245, 245, 220));
  p.drawText(panel.adjusted(14, 8, -14, -panel.height() + 42), Qt::AlignLeft | Qt::AlignVCenter, title);
  p.restore();
}

void OsmMinimapRenderer::drawRoad(QPainter &p, const QRectF &panel, double scale, const QJsonObject &road) {
  const QPointF a = projectPoint(panel, scale, road.value("x1").toDouble(), road.value("y1").toDouble());
  const QPointF b = projectPoint(panel, scale, road.value("x2").toDouble(), road.value("y2").toDouble());
  if (!pointNearPanel(panel, a) && !pointNearPanel(panel, b)) return;

  const bool current = road.value("current").toBool();
  const bool predicted = road.value("predicted").toBool();
  QColor color(210, 210, 210, 100);
  int width = 3;
  if (predicted) {
    color = QColor(64, 196, 255, 210);
    width = 5;
  }
  if (current) {
    color = QColor(74, 222, 128, 235);
    width = 7;
  }

  p.setPen(QPen(color, width, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
  p.drawLine(a, b);

  if (current && !roadName(road).isEmpty()) {
    const QPointF label = (a + b) / 2.0;
    p.setFont(InterFont(18, QFont::Normal));
    p.setPen(QColor(255, 255, 255, 210));
    p.drawText(QRectF(label.x() - 80, label.y() - 22, 160, 22), Qt::AlignCenter, roadName(road));
  }
}
