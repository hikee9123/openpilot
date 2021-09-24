
#include <string>
#include <iostream>
#include <sstream>
#include <cassert>

#include <QMouseEvent>

#include "atomMenu.h"

CAtomMenu::CAtomMenu(QWidget *parent)
    : QWidget(parent)
{
}

CAtomMenu::~CAtomMenu()
{
}

void CAtomMenu::updateAlert(const Alert &a, const QColor &color)
{
}

void CAtomMenu::paintEvent(QPaintEvent *event)
{
  QPainter p(this);
  p.fillRect(rect(), QColor(bg.red(), bg.green(), bg.blue(), 255));
}

void CAtomMenu::ui_draw(UIState *s, int w, int h)
{
}