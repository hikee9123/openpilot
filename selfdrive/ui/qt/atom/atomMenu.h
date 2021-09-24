#pragma once



#include <QFrame>
#include <QTimer>



class CAtomMenu : public QWidget 
{
  Q_OBJECT


public:
  CAtomMenu( QWidget* parent );
  ~CAtomMenu();

  void updateAlert(const Alert &a, const QColor &color);

protected:
  void paintEvent(QPaintEvent*) override;

private:
  QColor bg;
  Alert alert = {};


protected:
  void ui_draw( UIState *s, int w, int h );

};

