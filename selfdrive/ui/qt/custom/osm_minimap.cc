#include "selfdrive/ui/qt/custom/osm_minimap.h"

#include <algorithm>
#include <cmath>
#include <limits>

#include <QPainterPath>

#include "selfdrive/ui/qt/util.h"

namespace {

constexpr double kMinMapRadiusM = 230.0;
constexpr double kBaseMaxMapRadiusM = 1000.0;
constexpr double kExtendedMaxMapRadiusM = 1800.0;
constexpr double kDebugMinMapRadiusM = 80.0;
constexpr double kDebugMaxMapRadiusM = 2500.0;
constexpr double kMinRadiusSpeedMps = 30.0 / 3.6;
constexpr double kMaxRadiusSpeedMps = 60.0 / 3.6;
constexpr double kRadiusAnimationAlpha = 0.08;
constexpr int kExtendedPredictionSegmentThreshold = 40;
constexpr int kHudMargin = 30;
constexpr int kHudGap = 24;
constexpr int kButtonSize = 192;
constexpr int kDebugZoomMin = 0;
constexpr int kDebugZoomMax = 4;

constexpr int kTopLeft = 0;
constexpr int kTopRight = 1;
constexpr int kBottomLeft = 2;
constexpr int kBottomRight = 3;
constexpr int kCenter = 4;

bool isCenterPosition(int position) {
  return position == kCenter;
}

double debugRadiusM(int debug_zoom) {
  switch (std::clamp(debug_zoom, kDebugZoomMin, kDebugZoomMax)) {
    case 1:
      return 2000.0;
    case 2:
      return 1000.0;
    case 3:
      return 500.0;
    case 4:
      return 250.0;
    default:
      return 0.0;
  }
}

QString debugDistanceLabel(int debug_zoom) {
  switch (std::clamp(debug_zoom, kDebugZoomMin, kDebugZoomMax)) {
    case 1:
      return QStringLiteral("2km");
    case 2:
      return QStringLiteral("1km");
    case 3:
      return QStringLiteral("500m");
    case 4:
      return QStringLiteral("250m");
    default:
      return QStringLiteral("FIT");
  }
}

QString predictionDistanceLabel(float distance_m) {
  if (!std::isfinite(distance_m) || distance_m <= 0.0f) {
    return QStringLiteral("Pred --");
  }
  if (distance_m >= 1000.0f) {
    return QStringLiteral("Pred %1km").arg(distance_m / 1000.0f, 0, 'f', 1);
  }
  return QStringLiteral("Pred %1m").arg(static_cast<int>(std::round(distance_m)));
}

QPointF egoPoint(const QRectF &panel, bool centered) {
  const double bottom_margin = centered ? 86.0 : 58.0;
  return QPointF(panel.center().x(), panel.bottom() - bottom_margin);
}

QPointF projectPoint(const QRectF &panel, double scale, double forward_m, double right_m, bool centered) {
  const QPointF origin = egoPoint(panel, centered);
  return {origin.x() + right_m * scale, origin.y() - forward_m * scale};
}

bool clipLine(double p, double q, double &u1, double &u2) {
  if (std::abs(p) < 1e-9) {
    return q >= 0.0;
  }
  const double r = q / p;
  if (p < 0.0) {
    if (r > u2) return false;
    u1 = std::max(u1, r);
  } else {
    if (r < u1) return false;
    u2 = std::min(u2, r);
  }
  return true;
}

bool lineIntersectsRect(const QRectF &rect, const QPointF &a, const QPointF &b) {
  double u1 = 0.0;
  double u2 = 1.0;
  const double dx = b.x() - a.x();
  const double dy = b.y() - a.y();
  return clipLine(-dx, a.x() - rect.left(), u1, u2)
      && clipLine(dx, rect.right() - a.x(), u1, u2)
      && clipLine(-dy, a.y() - rect.top(), u1, u2)
      && clipLine(dy, rect.bottom() - a.y(), u1, u2);
}

bool lineNearPanel(const QRectF &panel, const QPointF &a, const QPointF &b) {
  const QRectF expanded = panel.adjusted(-30.0, -30.0, 30.0, 30.0);
  return expanded.contains(a) || expanded.contains(b) || lineIntersectsRect(expanded, a, b);
}

void drawAssistConnector(QPainter &p, const QRectF &panel, double scale,
                         const OsmMinimapRoad &from, const OsmMinimapRoad &to, bool centered) {
  const QPointF from_points[] = {
    projectPoint(panel, scale, from.x1, from.y1, centered),
    projectPoint(panel, scale, from.x2, from.y2, centered),
  };
  const QPointF to_points[] = {
    projectPoint(panel, scale, to.x1, to.y1, centered),
    projectPoint(panel, scale, to.x2, to.y2, centered),
  };

  QPointF best_from = from_points[0];
  QPointF best_to = to_points[0];
  double best_distance_sq = std::numeric_limits<double>::max();
  for (const QPointF &a : from_points) {
    for (const QPointF &b : to_points) {
      const double dx = a.x() - b.x();
      const double dy = a.y() - b.y();
      const double distance_sq = dx * dx + dy * dy;
      if (distance_sq < best_distance_sq) {
        best_distance_sq = distance_sq;
        best_from = a;
        best_to = b;
      }
    }
  }
  if (!lineNearPanel(panel, best_from, best_to)) return;

  QPen pen(QColor(205, 205, 205, 150), 3, Qt::DashLine, Qt::RoundCap, Qt::RoundJoin);
  p.setPen(pen);
  p.drawLine(best_from, best_to);
}

QString roadName(const OsmMinimapRoad &road) {
  return road.name.left(32);
}

double extendedRouteRadiusM(const OsmMinimapData &data) {
  int graph_predicted_count = 0;
  double max_forward_m = 0.0;
  double max_side_m = 0.0;
  for (const OsmMinimapRoad &road : data.roads) {
    if (!road.predicted || road.fallback || road.assist) continue;
    graph_predicted_count++;
    max_forward_m = std::max({max_forward_m, static_cast<double>(road.x1), static_cast<double>(road.x2)});
    max_side_m = std::max({max_side_m, std::abs(static_cast<double>(road.y1)), std::abs(static_cast<double>(road.y2))});
  }
  if (graph_predicted_count <= kExtendedPredictionSegmentThreshold) {
    return kMinMapRadiusM;
  }
  const double route_radius_m = std::max(max_forward_m * 0.65, max_side_m * 1.25);
  return std::clamp(route_radius_m, kMinMapRadiusM, kExtendedMaxMapRadiusM);
}

double debugFitRadiusM(const OsmMinimapData &data, const QRectF &panel) {
  double max_forward_m = 0.0;
  double max_backward_m = 0.0;
  double max_left_m = 0.0;
  double max_right_m = 0.0;
  for (const OsmMinimapRoad &road : data.roads) {
    for (const double forward_m : {static_cast<double>(road.x1), static_cast<double>(road.x2)}) {
      max_forward_m = std::max(max_forward_m, forward_m);
      max_backward_m = std::max(max_backward_m, -forward_m);
    }
    for (const double right_m : {static_cast<double>(road.y1), static_cast<double>(road.y2)}) {
      max_right_m = std::max(max_right_m, right_m);
      max_left_m = std::max(max_left_m, -right_m);
    }
  }

  const QPointF ego = egoPoint(panel, true);
  const double min_panel_px = std::min(panel.width(), panel.height());
  auto fitRadius = [min_panel_px](double meters, double pixels) {
    return pixels > 1.0 ? meters * min_panel_px / (2.0 * pixels) : kDebugMaxMapRadiusM;
  };

  const double radius_m = std::max({
    fitRadius(max_forward_m, ego.y() - (panel.top() + 48.0)),
    fitRadius(max_backward_m, panel.bottom() - 24.0 - ego.y()),
    fitRadius(max_left_m, ego.x() - (panel.left() + 18.0)),
    fitRadius(max_right_m, panel.right() - 18.0 - ego.x()),
  });
  return std::clamp(radius_m * 1.05, kDebugMinMapRadiusM, kDebugMaxMapRadiusM);
}

}  // namespace

QRectF OsmMinimapRenderer::panelRect(const QRect &surface, int position) const {
  if (isCenterPosition(position)) {
    const int panel_h = std::clamp(static_cast<int>(surface.height() * 0.68), 520, 760);
    const int panel_w = panel_h * 0.7;
    return QRectF(surface.left() + 250, // + (surface.width() - panel_w) / 2.0,
                  surface.top() + 50,//(surface.height() - panel_h) / 2.0 + 80,
                  panel_w,
                  panel_h);
  }

  const int panel_h = std::clamp(surface.height() / 4, 250, 330);
  const int panel_w = panel_h;
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

QRectF OsmMinimapRenderer::debugZoomOutRect(const QRectF &panel) const {
  return QRectF(panel.right() - 188.0, panel.top() + 12.0, 48.0, 48.0);
}

QRectF OsmMinimapRenderer::debugZoomInRect(const QRectF &panel) const {
  return QRectF(panel.right() - 58.0, panel.top() + 12.0, 48.0, 48.0);
}

QRectF OsmMinimapRenderer::debugSpeedDownRect(const QRectF &panel) const {
  return QRectF(panel.right() - 238.0, panel.top() + 66.0, 48.0, 48.0);
}

QRectF OsmMinimapRenderer::debugSpeedUpRect(const QRectF &panel) const {
  return QRectF(panel.right() - 58.0, panel.top() + 66.0, 48.0, 48.0);
}

bool OsmMinimapRenderer::debugZoomControlAt(const QRect &surface, int position, const QPoint &pt,
                                            bool debug_zoom_controls, int &delta) const {
  delta = 0;
  if (!debug_zoom_controls || !isCenterPosition(position)) {
    return false;
  }

  const QRectF panel = panelRect(surface, position);
  if (!panel.contains(pt)) {
    return false;
  }
  if (debugZoomOutRect(panel).contains(pt)) {
    delta = -1;
    return true;
  }
  if (debugZoomInRect(panel).contains(pt)) {
    delta = 1;
    return true;
  }
  return false;
}

bool OsmMinimapRenderer::debugSpeedControlAt(const QRect &surface, int position, const QPoint &pt,
                                             bool debug_zoom_controls, int &delta) const {
  delta = 0;
  if (!debug_zoom_controls || !isCenterPosition(position)) {
    return false;
  }

  const QRectF panel = panelRect(surface, position);
  if (!panel.contains(pt)) {
    return false;
  }
  if (debugSpeedDownRect(panel).contains(pt)) {
    delta = -10;
    return true;
  }
  if (debugSpeedUpRect(panel).contains(pt)) {
    delta = 10;
    return true;
  }
  return false;
}

double OsmMinimapRenderer::targetMapRadiusM(float speed_mps, const OsmMinimapData &data, int position, const QRectF &panel) const {
  if (isCenterPosition(position)) {
    return debugFitRadiusM(data, panel);
  }

  double speed_radius_m = kMinMapRadiusM;
  if (!std::isfinite(speed_mps)) {
    return std::max(speed_radius_m, extendedRouteRadiusM(data));
  }
  const double bounded_speed = std::clamp<double>(std::max(0.0f, speed_mps), kMinRadiusSpeedMps, kMaxRadiusSpeedMps);
  const double ratio = (bounded_speed - kMinRadiusSpeedMps) / (kMaxRadiusSpeedMps - kMinRadiusSpeedMps);
  speed_radius_m = kMinMapRadiusM + (kBaseMaxMapRadiusM - kMinMapRadiusM) * ratio;
  return std::max(speed_radius_m, extendedRouteRadiusM(data));
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

void OsmMinimapRenderer::draw(QPainter &p, const QRect &surface, const OsmMinimapData &data, bool enabled,
                              int position, float speed_mps, int debug_zoom, int sim_speed_kph,
                              bool debug_zoom_controls) {
  if (!enabled) return;
  if (!data.available) {
    drawStatus(p, surface, QStringLiteral("Waiting for GPS"), position);
    return;
  }

  if (data.roads.empty()) {
    drawStatus(p, surface, QStringLiteral("No nearby road"), position);
    return;
  }

  const QRectF panel = panelRect(surface, position);
  const bool centered = isCenterPosition(position);
  double target_radius_m = targetMapRadiusM(speed_mps, data, position, panel);
  if (centered) {
    const double debug_radius_m = debugRadiusM(debug_zoom);
    if (debug_radius_m > 0.0) {
      target_radius_m = debug_radius_m;
    }
  }
  if (centered || animated_map_radius_m > kExtendedMaxMapRadiusM) {
    animated_map_radius_m = target_radius_m;
  } else {
    animated_map_radius_m += (target_radius_m - animated_map_radius_m) * kRadiusAnimationAlpha;
  }
  animated_map_radius_m = std::clamp(animated_map_radius_m, centered ? kDebugMinMapRadiusM : kMinMapRadiusM,
                                     centered ? kDebugMaxMapRadiusM : kExtendedMaxMapRadiusM);
  const double scale = std::min(panel.width(), panel.height()) / (2.0 * animated_map_radius_m);

  p.save();
  p.setRenderHint(QPainter::Antialiasing, true);
  p.setPen(Qt::NoPen);
  p.setBrush(QColor(0, 0, 0, 150));
  p.drawRoundedRect(panel, 18, 18);

  QPainterPath clip_path;
  clip_path.addRoundedRect(panel, 18, 18);
  p.setClipPath(clip_path);

  p.setPen(QPen(QColor(255, 255, 255, 42), 1));
  const QPointF ego = egoPoint(panel, centered);
  p.drawLine(QPointF(ego.x(), panel.top() + 40), QPointF(ego.x(), panel.bottom() - 24));
  p.drawLine(QPointF(panel.left() + 18, ego.y()), QPointF(panel.right() - 18, ego.y()));

  const OsmMinimapRoad *previous_predicted = nullptr;
  for (const OsmMinimapRoad &road : data.roads) {
    if (!road.predicted) continue;
    if (previous_predicted != nullptr && (previous_predicted->assist || road.assist)) {
      drawAssistConnector(p, panel, scale, *previous_predicted, road, centered);
    }
    previous_predicted = &road;
  }

  for (const OsmMinimapRoad &road : data.roads) {
    if (!road.history && !road.predicted && !road.current) drawRoad(p, panel, scale, road, centered);
  }
  for (const OsmMinimapRoad &road : data.roads) {
    if (road.history && !road.predicted && !road.current) drawRoad(p, panel, scale, road, centered);
  }
  for (const OsmMinimapRoad &road : data.roads) {
    if (road.predicted && !road.current) drawRoad(p, panel, scale, road, centered);
  }
  for (const OsmMinimapRoad &road : data.roads) {
    if (road.current) drawRoad(p, panel, scale, road, centered);
  }

  QPainterPath ego_path;
  ego_path.moveTo(ego.x(), ego.y() - 15);
  ego_path.lineTo(ego.x() + 11, ego.y() + 13);
  ego_path.lineTo(ego.x(), ego.y() + 7);
  ego_path.lineTo(ego.x() - 11, ego.y() + 13);
  ego_path.closeSubpath();
  p.setPen(QPen(QColor(10, 10, 10, 190), 3));
  p.setBrush(QColor(255, 255, 255, 235));
  p.drawPath(ego_path);

  const QString title = data.road.isEmpty() ? QStringLiteral("OSM roads") : data.road;
  p.setFont(InterFont(24, QFont::DemiBold));
  p.setPen(QColor(245, 245, 245, 220));
  p.drawText(panel.adjusted(14, 8, -14, -panel.height() + 42), Qt::AlignLeft | Qt::AlignVCenter, title);
  if (centered) {
    drawDebugPredictionDistance(p, panel, data);
  }
  if (centered && debug_zoom_controls) {
    drawDebugZoomControls(p, panel, debug_zoom);
    drawDebugSpeedControls(p, panel, sim_speed_kph);
  }
  p.restore();
}

void OsmMinimapRenderer::drawDebugPredictionDistance(QPainter &p, const QRectF &panel, const OsmMinimapData &data) {
  const QRectF label_rect(panel.left() + 14.0, panel.top() + 42.0, 170.0, 28.0);

  p.save();
  p.setClipping(false);
  p.setRenderHint(QPainter::Antialiasing, true);
  p.setFont(InterFont(18, QFont::DemiBold));
  p.setPen(QColor(245, 245, 245, 210));
  p.drawText(label_rect, Qt::AlignLeft | Qt::AlignVCenter, predictionDistanceLabel(data.prediction_distance_m));
  p.restore();
}

void OsmMinimapRenderer::drawDebugSpeedControls(QPainter &p, const QRectF &panel, int sim_speed_kph) {
  const QRectF minus = debugSpeedDownRect(panel);
  const QRectF plus = debugSpeedUpRect(panel);
  const QRectF label(minus.right() + 4.0, minus.top(), plus.left() - minus.right() - 8.0, minus.height());

  p.save();
  p.setClipping(false);
  p.setRenderHint(QPainter::Antialiasing, true);
  p.setFont(InterFont(25, QFont::DemiBold));
  p.setPen(QPen(QColor(255, 255, 255, 68), 2));
  p.setBrush(QColor(0, 0, 0, 185));
  p.drawRoundedRect(minus, 12, 12);
  p.drawRoundedRect(plus, 12, 12);

  p.setPen(QColor(245, 245, 245, 235));
  p.drawText(minus, Qt::AlignCenter, QStringLiteral("-"));
  p.drawText(plus, Qt::AlignCenter, QStringLiteral("+"));

  p.setFont(InterFont(17, QFont::DemiBold));
  p.setPen(QColor(245, 245, 245, 215));
  p.drawText(label, Qt::AlignCenter, QStringLiteral("%1km/h").arg(std::clamp(sim_speed_kph, 0, 250)));
  p.restore();
}

void OsmMinimapRenderer::drawDebugZoomControls(QPainter &p, const QRectF &panel, int debug_zoom) {
  const QRectF minus = debugZoomOutRect(panel);
  const QRectF plus = debugZoomInRect(panel);
  const QRectF label(minus.right() + 4.0, minus.top(), plus.left() - minus.right() - 8.0, minus.height());

  p.save();
  p.setClipping(false);
  p.setRenderHint(QPainter::Antialiasing, true);
  p.setFont(InterFont(25, QFont::DemiBold));
  p.setPen(QPen(QColor(255, 255, 255, 68), 2));
  p.setBrush(QColor(0, 0, 0, 185));
  p.drawRoundedRect(minus, 12, 12);
  p.drawRoundedRect(plus, 12, 12);

  p.setPen(QColor(245, 245, 245, 235));
  p.drawText(minus, Qt::AlignCenter, QStringLiteral("-"));
  p.drawText(plus, Qt::AlignCenter, QStringLiteral("+"));

  p.setFont(InterFont(19, QFont::DemiBold));
  p.setPen(QColor(245, 245, 245, 215));
  p.drawText(label, Qt::AlignCenter, debugDistanceLabel(debug_zoom));
  p.restore();
}

void OsmMinimapRenderer::drawRoad(QPainter &p, const QRectF &panel, double scale, const OsmMinimapRoad &road, bool centered) {
  const QPointF a = projectPoint(panel, scale, road.x1, road.y1, centered);
  const QPointF b = projectPoint(panel, scale, road.x2, road.y2, centered);
  if (!lineNearPanel(panel, a, b)) return;

  const bool current = road.current;
  const bool predicted = road.predicted;
  const bool history = road.history;
  const bool fallback = road.fallback;
  const bool assist = road.assist;
  QColor color(210, 210, 210, 100);
  int width = 3;
  if (history) {
    color = QColor(150, 255, 170, 145);
    width = 4;
  }
  if (predicted) {
    if (assist) {
      color = QColor(205, 205, 205, 180);
    } else {
      color = fallback ? QColor(255, 190, 64, 210) : QColor(64, 196, 255, 210);
    }
    width = 5;
  }
  if (current) {
    color = QColor(74, 222, 128, 235);
    width = 7;
  }

  QPen pen(color, width, assist ? Qt::DashLine : Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin);
  p.setPen(pen);
  p.drawLine(a, b);

  const QString name = roadName(road);
  if (current && !name.isEmpty()) {
    const QPointF label = (a + b) / 2.0;
    p.setFont(InterFont(18, QFont::Normal));
    p.setPen(QColor(255, 255, 255, 210));
    p.drawText(QRectF(label.x() - 80, label.y() - 22, 160, 22), Qt::AlignCenter, name);
  }
}
