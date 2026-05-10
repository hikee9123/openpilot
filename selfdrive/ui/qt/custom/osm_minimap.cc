#include "selfdrive/ui/qt/custom/osm_minimap.h"

#include <algorithm>

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainterPath>

#include "selfdrive/ui/qt/util.h"

namespace {

constexpr double kMapRadiusM = 230.0;
constexpr int kHudMargin = 30;
constexpr int kHudGap = 24;
constexpr int kButtonSize = 192;

constexpr int kTopLeft = 0;
constexpr int kTopRight = 1;
constexpr int kBottomLeft = 2;
constexpr int kBottomRight = 3;

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

QRectF OsmMinimapRenderer::panelRect(const QRect &surface, int position) const {
  const int panel_w = std::clamp(surface.width() / 4, 310, 390);
  const int panel_h = std::clamp(surface.height() / 4, 250, 330);
  const int right = surface.left() + surface.width();
  const int bottom = surface.top() + surface.height();

  switch (std::clamp(position, kTopLeft, kBottomRight)) {
    case kTopLeft:
      return QRectF(surface.left() + 270, surface.top() + 45, panel_w, panel_h);
    case kTopRight:
      return QRectF(right - kHudMargin - kButtonSize - kHudGap - panel_w, surface.top() + kHudMargin, panel_w, panel_h);
    case kBottomLeft:
      return QRectF(surface.left() + kHudMargin + kButtonSize + kHudGap, bottom - kHudMargin - panel_h, panel_w, panel_h);
    case kBottomRight:
    default:
      return QRectF(right - kHudMargin - panel_w, bottom - kHudMargin - panel_h, panel_w, panel_h);
  }
}

void OsmMinimapRenderer::drawStatus(QPainter &p, const QRect &surface, const QString &status, int position) {
  const QRectF panel = panelRect(surface, position);

  p.save();
  p.setRenderHint(QPainter::Antialiasing, true);
  p.setPen(Qt::NoPen);
  p.setBrush(QColor(0, 0, 0, 150));
  p.drawRoundedRect(panel, 18, 18);

  p.setFont(InterFont(24, QFont::DemiBold));
  p.setPen(QColor(245, 245, 245, 225));
  p.drawText(panel.adjusted(16, 10, -16, -panel.height() + 46), Qt::AlignLeft | Qt::AlignVCenter, QStringLiteral("OSM road prediction"));

  p.setFont(InterFont(22, QFont::Normal));
  p.setPen(QColor(220, 220, 220, 205));
  p.drawText(panel.adjusted(16, 58, -16, -16), Qt::AlignCenter, status);
  p.restore();
}

void OsmMinimapRenderer::draw(QPainter &p, const QRect &surface, const QString &payload, bool enabled, int position) {
  if (!enabled) return;
  if (payload.isEmpty()) {
    drawStatus(p, surface, QStringLiteral("Waiting for GPS"), position);
    return;
  }

  const QJsonDocument doc = QJsonDocument::fromJson(payload.toUtf8());
  if (!doc.isObject()) {
    drawStatus(p, surface, QStringLiteral("Waiting for road data"), position);
    return;
  }

  const QJsonObject root = doc.object();
  const QJsonArray roads = root.value("mapRoads").toArray();
  if (roads.isEmpty()) {
    drawStatus(p, surface, QStringLiteral("No nearby road"), position);
    return;
  }

  const QRectF panel = panelRect(surface, position);
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
