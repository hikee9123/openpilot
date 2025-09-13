#include "selfdrive/ui/qt/custom/csidebar.h"

#include <QMouseEvent>

#include "selfdrive/ui/qt/util.h"


void CSidebar::configFont(QPainter &p, const QString &family, int size, const QString &style) 
{
  QFont f(family);
  f.setPixelSize(size);
  f.setStyleName(style);
  p.setFont(f);
}


CSidebar::CSidebar(QFrame *parent)  
{
  beterrry1_img = loadPixmap("qt/custom/images/battery.png", battery_rc.size());
  beterrry2_img = loadPixmap("qt/custom/images/battery_charging.png", battery_rc.size());
}

void CSidebar::mouseReleaseEvent(QMouseEvent *event, cereal::UserFlag::Builder &userFlag ) 
{
  UIState   *s = uiState();
  UIScene   &scene = s->scene;
  printf( "CSidebar::mouseReleaseEvent  m_idxUserFlag=%d   \n", m_idxUserFlag );
  
  scene.custom.m_powerflag = 0; 
  m_idxUserFlag++;
  userFlag.setIdx( m_idxUserFlag );

}

int CSidebar::updateState(const UIState &s) 
{
  SubMaster &sm = *(s.sm);
  if (sm.frame % (UI_FREQ) != 0) return 0;
  frame_cnt++;
  if( frame_cnt < 2 ) return 0;
  frame_cnt = 0;

  auto peripheralState = sm["peripheralState"].getPeripheralState();
  fBatteryVoltage = peripheralState.getVoltage() * 0.001;

  //auto pandaStates = sm["pandaStates"].getPandaStates();
  //if (pandaStates.size() > 0) {
  //  fBatteryVoltage = pandaStates[0].getVoltage() * 0.001 + 0.2;
  //}
  return 1;
}

void CSidebar::paintEvent(QPainter &p) 
{
  UIState *s = uiState();
  UIScene &scene = s->scene;

  // atom - battery
  float  batteryPercent = 90.0;

  
 QColor  color = QColor( 100, 100, 100 );


  QString beterryValtage;
  beterryValtage.sprintf("%.1f", fBatteryVoltage );

  if( fBatteryVoltage < 5 ) 
  {
    beterryValtage = "-";
  }
  else
  {
    auto interp_color = [=](QColor c1, QColor c2, QColor c3, QColor c4) {
      if( scene.started )  // 충전중.
          return fBatteryVoltage > 0 ? interpColor( fBatteryVoltage, { 11.51, 12.0, 13.0, 14.4 }, {c1, c2, c3, c4}) : c1;
      else
          return fBatteryVoltage > 0 ? interpColor( fBatteryVoltage, {11.51, 11.66, 11.96, 12.62}, {c1, c2, c3, c4}) : c1;
    };

    color = interp_color( QColor( 229, 0, 0 ), QColor( 229, 229, 0 ), QColor(0, 229, 0),  QColor( 0, 229, 229 ));
  }

  const QRect  rect = battery_rc;
  if( fBatteryVoltage > 5 )
  {
    QRect  bq(rect.left() + 6, rect.top() + 5, int((rect.width() - 19) * batteryPercent * 0.01), rect.height() - 11 );
    QBrush bgBrush = color;
    p.fillRect(bq, bgBrush);
  }


  p.drawPixmap( rect.x(), rect.y(), beterrry1_img );
  p.setPen(Qt::black);
  configFont(p, "Open Sans", 25, "Regular");  
  p.drawText(rect, Qt::AlignLeft | Qt::AlignVCenter, beterryValtage);    


  if( scene.custom.m_powerflag )
  {
    const QRect home_btn1 = QRect(60,860,180,180);

    p.setBrush(  QColor( 255,255, 0, 150 ) );
    p.drawEllipse( home_btn1.x(), home_btn1.y(), 180, 180);
  }

}
