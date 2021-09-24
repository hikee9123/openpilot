
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


void CAtomMenu::fill_rect(NVGcontext *vg, const Rect &r, const NVGcolor *color, const NVGpaint *paint, float radius) 
{
  nvgBeginPath(vg);
  radius > 0 ? nvgRoundedRect(vg, r.x, r.y, r.w, r.h, radius) : nvgRect(vg, r.x, r.y, r.w, r.h);
  if (color) nvgFillColor(vg, *color);
  if (paint) nvgFillPaint(vg, *paint);
  nvgFill(vg);
}



void CAtomMenu::draw_text(const UIState *s, float x, float y, const char *string, float size, NVGcolor color, const char *font_name) 
{
  if( font_name )
    nvgFontFace(s->vg, font_name);

  nvgFontSize(s->vg, size);
  nvgFillColor(s->vg, color);
  nvgText(s->vg, x, y, string, NULL);
}

void CAtomMenu::paintEvent(QPaintEvent *event)
{
 // QPainter p(this);
 // p.fillRect(rect(), QColor(bg.red(), bg.green(), bg.blue(), 255));
}

void CAtomMenu::ui_draw(UIState *s, int w, int h)
{

  fill_rect( s->vg, Rect(0,0,100,100), nullptr, nvgRGBA(0, 0, 0, 100), 30. )
}