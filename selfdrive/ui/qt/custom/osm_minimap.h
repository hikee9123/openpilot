#pragma once

#include <QString>
#include <QPainter>
#include <QRect>

class QJsonObject;

class OsmMinimapRenderer {
public:
  void draw(QPainter &p, const QRect &surface, const QString &payload);

private:
  void drawRoad(QPainter &p, const QRectF &panel, double scale, const QJsonObject &road);
};
