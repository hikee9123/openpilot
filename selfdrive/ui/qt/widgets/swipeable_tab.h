#pragma once

#include <algorithm>
#include <cmath>

#include <QMouseEvent>
#include <QTabBar>
#include <QTabWidget>
#include <QWheelEvent>

inline constexpr char kSwipeableTabStyle[] = R"(
  QTabBar::tab {
    border: 1px solid #C4C4C3;
    border-bottom-color: #C2C7CB;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    min-width: 45ex;
    font-size: 50px;
    font-weight: 500;
    padding: 2px;
    margin-right: 1px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #FAFAFA, stop: 0.4 #F4F4F4,
                                stop: 0.5 #EDEDED, stop: 1.0 #FAFAFA);
    color: black;
  }
  QTabBar::tab:selected {
    border-bottom-color: #B1B1B0;
    background: white;
    color: black;
  }
  QTabBar::tab:!selected {
    margin-top: 2px;
    background: black;
    color: white;
  }
  QTabBar QToolButton {
    min-width: 92px;
    min-height: 64px;
    margin: 2px;
    border: 1px solid #666;
    border-radius: 4px;
    background-color: #393939;
  }
  QTabBar QToolButton:pressed {
    background-color: #4a4a4a;
  }
)";

class SwipeableTabBar : public QTabBar {
public:
  explicit SwipeableTabBar(QWidget *parent = nullptr) : QTabBar(parent) {
    setUsesScrollButtons(true);
    setExpanding(false);
    setElideMode(Qt::ElideNone);
  }

protected:
  void mousePressEvent(QMouseEvent *event) override {
    drag_start_pos = event->pos();
    drag_switched = false;
    QTabBar::mousePressEvent(event);
  }

  void mouseMoveEvent(QMouseEvent *event) override {
    const int dx = event->pos().x() - drag_start_pos.x();
    if (std::abs(dx) >= kSwipeThresholdPx) {
      stepCurrentTab(dx < 0 ? 1 : -1);
      drag_start_pos = event->pos();
      drag_switched = true;
      event->accept();
      return;
    }
    QTabBar::mouseMoveEvent(event);
  }

  void mouseReleaseEvent(QMouseEvent *event) override {
    if (drag_switched) {
      drag_switched = false;
      event->accept();
      return;
    }
    QTabBar::mouseReleaseEvent(event);
  }

  void wheelEvent(QWheelEvent *event) override {
    const QPoint delta = event->angleDelta();
    if (!delta.isNull()) {
      const int step = std::abs(delta.x()) > std::abs(delta.y()) ? -delta.x() : -delta.y();
      if (step != 0) {
        stepCurrentTab(step > 0 ? 1 : -1);
        event->accept();
        return;
      }
    }
    QTabBar::wheelEvent(event);
  }

private:
  void stepCurrentTab(int step) {
    if (count() <= 0) {
      return;
    }
    const int next = std::clamp(currentIndex() + step, 0, count() - 1);
    if (next != currentIndex()) {
      setCurrentIndex(next);
    }
  }

  static constexpr int kSwipeThresholdPx = 90;
  QPoint drag_start_pos;
  bool drag_switched = false;
};

class SwipeableTabWidget : public QTabWidget {
public:
  explicit SwipeableTabWidget(QWidget *parent = nullptr) : QTabWidget(parent) {
    setTabBar(new SwipeableTabBar(this));
  }
};
