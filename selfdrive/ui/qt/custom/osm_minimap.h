#pragma once

#include <QString>
#include <QPainter>
#include <QRect>

class QJsonObject;

class OsmMinimapRenderer {
public:
  void draw(QPainter &p, const QRect &surface, const QString &payload, bool enabled, int position);

private:
  QRectF panelRect(const QRect &surface, int position) const;
  void drawStatus(QPainter &p, const QRect &surface, const QString &status, int position);
  void drawRoad(QPainter &p, const QRectF &panel, double scale, const QJsonObject &road);
};
