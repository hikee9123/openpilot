#pragma once



#include <QFrame>
#include <QTimer>

#include "selfdrive/ui/ui.h"

class CAtomMenu : public QWidget 
{
  Q_OBJECT


public:
  CAtomMenu( QWidget* parent );
  ~CAtomMenu();



protected:
  void paintEvent(QPaintEvent*) override;

private:
  QColor bg;


private:
  void  fill_rect(NVGcontext *vg, const Rect &r, const NVGcolor *color, const NVGpaint *paint, float radius);
  void  draw_text(const UIState *s, float x, float y, const char *string, float size, NVGcolor color, const char *font_name = 0);

public:
  void ui_draw( UIState *s, int w, int h );

};

