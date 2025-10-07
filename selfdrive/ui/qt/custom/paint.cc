#include "selfdrive/ui/qt/custom/paint.h"

#include <cmath>

#include <QDebug>
#include <QPaintEvent>
#include <QPainter>
#include <QConicalGradient>
#include <QPen>


#include "selfdrive/ui/qt/util.h"




// OnroadHud
OnPaint::OnPaint()
{
  m_sm = std::make_unique<SubMaster, const std::initializer_list<const char *>>({
    "peripheralState", "gpsLocation", "gpsLocationExternal", "liveParameters",
    "naviCustom",  "uICustom",  //"carControlCustom",
  });



  state = uiState();
  scene = &(state->scene);



  is_debug = 0;//Params().getBool("ShowDebugMessage");
  //img_tire_pressure = QPixmap("qt/custom/images/img_tire_pressure.png");
}


float OnPaint::interp( float xv, float xp[], float fp[], int N)
{
	float dResult = 0;
	int low, hi = 0;

	while ( (hi < N) && (xv > xp[hi]))
	{
		hi += 1;
	}
	low = hi - 1;
	if( low < 0 )
	{
		low = N-1;
		return fp[0];
	}

	if (hi == N && xv > xp[low])
	{
		return fp[N-1];
	}
	else
	{
		if( hi == 0 )
		{
			return fp[0];
		}
		else
		{
			dResult = (xv - xp[low]) * (fp[hi] - fp[low]) / (xp[hi] - xp[low]) + fp[low];
		}
	}
	return  dResult;
}

void OnPaint::configFont(QPainter &p, const QString &family, int size, const QString &style)
{
  QFont f(family);
  f.setPixelSize(size);
  f.setStyleName(style);
  p.setFont(f);
}



void OnPaint::drawText1(QPainter &p, int x, int y, const QString &text, QColor qColor, int nAlign )
{
  QFontMetrics fm(p.font());
  QRect init_rect = fm.boundingRect(text);
  QRect real_rect = fm.boundingRect(init_rect, 0, text);

  if( nAlign == Qt::AlignCenter ) // Qt::AlignLeft )
     real_rect.moveCenter({x, y - real_rect.height() / 2});
  else  if( nAlign ==  Qt::AlignRight  )
    real_rect.moveLeft( x );
  else  if( nAlign ==  Qt::AlignLeft  )
    real_rect.moveRight( x );
  else
    real_rect.moveTo(x, y - real_rect.height() / 2);


  p.setPen( qColor );
  p.drawText(real_rect, nAlign, text);
}


void OnPaint::drawText2(QPainter &p, int x, int y, int flags, const QString &text, const QColor color)
{
  QFontMetrics fm(p.font());
  QRect rect = fm.boundingRect(text);
  rect.adjust(-1, -1, 1, 1);
  p.setPen(color);
  p.drawText(QRect(x, y, rect.width()+1, rect.height()), flags, text);
}

void OnPaint::drawText3(QPainter &p, int x, int y, const QString &text, QColor color)
{
  QRect real_rect = p.fontMetrics().boundingRect(text);
  real_rect.moveCenter({x, y - real_rect.height() / 2});

  p.setPen( color );
  p.drawText(real_rect.x(), real_rect.bottom(), text);
}


void OnPaint::ui_draw_text( QPainter &p, const QRect& rc, const QString& text, float  size, const QColor& crBrush, const QColor& color )
{
    p.setPen( color );
    p.setBrush( crBrush );
    p.drawRoundedRect(rc, 20, 20);
    p.drawText( rc, Qt::AlignCenter, text);
}


int OnPaint::get_param( const std::string &key )
{
    auto str = QString::fromStdString(Params().get( key ));
    int value = str.toInt();
    return value;
}


void OnPaint::updateState(const UIState &s)
{
  // user message
  SubMaster &sm1 = *(s.sm);
  SubMaster &sm2 = *(m_sm);


  if ( (sm1.frame % UI_FREQ) != 0 )
      sm2.update(0);

  // 1.
  auto uiCustom = sm2["uICustom"].getUICustom();
  m_param.community  = uiCustom.getCommunity();
  m_param.ui  = uiCustom.getUserInterface();
  m_param.debug  = uiCustom.getDebug();
  is_debug = m_param.ui.getShowDebugMessage();
  is_carTracking = m_param.ui.getShowCarTracking();

  scene->custom.autoScreenOff = m_param.ui.getAutoScreenOff();
  scene->custom.brightness = m_param.ui.getBrightness();


  if( !is_debug ) return;

  // 1.
  if (s.scene.pandaType == cereal::PandaState::PandaType::TRES)
  {
      auto ge_data = sm2["gpsLocation"].getGpsLocation();
      m_param.gpsAccuracyUblox = ge_data.getVerticalAccuracy();
      m_param.altitudeUblox = ge_data.getAltitude();
  }
  else
  {
    auto gps_ext = sm2["gpsLocationExternal"].getGpsLocationExternal();
    m_param.gpsAccuracyUblox = gps_ext.getHorizontalAccuracy();
    m_param.altitudeUblox = gps_ext.getAltitude();
  }

  // 1.
  auto peripheralState = sm2["peripheralState"].getPeripheralState();
  m_param.batteryVoltage = peripheralState.getVoltage() * 0.001;


  // 1.
  auto navi_custom = sm2["naviCustom"].getNaviCustom();
  auto naviData = navi_custom.getNaviData();
  int activeNDA = naviData.getActive();
  int camType  = naviData.getCamType();
  int roadLimitSpeed = naviData.getRoadLimitSpeed();
  int camLimitSpeed = naviData.getCamLimitSpeed();
  int camLimitSpeedLeftDist = naviData.getCamLimitSpeedLeftDist();
  int cntIdx = naviData.getCntIdx();

  m_nda.activeNDA = activeNDA;
  m_nda.camType = camType;
  m_nda.roadLimitSpeed = roadLimitSpeed;
  m_nda.camLimitSpeed = camLimitSpeed;
  m_nda.camLimitSpeedLeftDist = camLimitSpeedLeftDist;
  m_nda.cntIdx = cntIdx;


  // 2.
  auto deviceState = sm1["deviceState"].getDeviceState();
  auto  maxCpuTemp = deviceState.getCpuTempC();
  m_param.cpuPerc = deviceState.getCpuUsagePercent()[0];
  m_param.cpuTemp = maxCpuTemp[0];

  // 2.
  auto radar_state = sm1["radarState"].getRadarState();  // radar
  m_param.lead_radar = radar_state.getLeadOne();


  // 2.
  auto car_state = sm1["carState"].getCarState();
  m_param.angleSteers = car_state.getSteeringAngleDeg();
  m_param.enginRpm =  car_state.getEngineRpmDEPRECATED();
  m_gasVal = car_state.getGasDEPRECATED();
  bool  brakePress = car_state.getBrakePressed();
  bool  brakeLights = car_state.getBrakeLightsDEPRECATED();
  if( brakePress ) m_nBrakeStatus = 1; else m_nBrakeStatus = 0;
  if( brakeLights ) m_nBrakeStatus |= 2;


  // 1.
  auto carState_custom = car_state.getCarSCustom();
  m_param.tpmsData  = carState_custom.getTpms();

  // debug Message
  alert.alertTextMsg1 = carState_custom.getAlertTextMsg1();
  alert.alertTextMsg2 = carState_custom.getAlertTextMsg2();
  alert.alertTextMsg3 = carState_custom.getAlertTextMsg3();
  m_param.electGearStep  = carState_custom.getElectGearStep();
  m_param.breakPos = carState_custom.getBreakPos();
  scene->custom.leadDistance = carState_custom.getLeadDistance();
  int touched = carState_custom.getTouched();
  if( touched_old != touched)
  {
    touched_old = touched;
    scene->custom.touched++;
  }

  // 2.
  if (sm1.frame % (UI_FREQ) != 0)
  {
    auto controls_state = sm1["controlsState"].getControlsState();
    m_param.cumLagMs = controls_state.getCumLagMsDEPRECATED();
    m_param.enabled = controls_state.getEnabledDEPRECATED();

    m_param.engaged = sm1.allAliveAndValid({"controlsState"}) && m_param.enabled;
  }


  auto pandaStates = sm1["pandaStates"].getPandaStates();
  if (pandaStates.size() > 0) {
    m_param.controlsAllowed = pandaStates[0].getControlsAllowed();
  }
}


void OnPaint::drawLead(QPainter &p, const cereal::RadarState::LeadData::Reader &lead_data, const QPointF &vd, int width, int height )
{
    const float speedBuff = 10.;
    const float leadBuff = 40.;
    const float d_rel = lead_data.getDRel();
    const float v_rel = lead_data.getVRel();

    float fillAlpha = 0;
    if (d_rel < leadBuff) {
      fillAlpha = 255 * (1.0 - (d_rel / leadBuff));
      if (v_rel < 0) {
        fillAlpha += 255 * (-1 * (v_rel / speedBuff));
      }
      fillAlpha = (int)(fmin(fillAlpha, 255));
    }

    float sz = std::clamp((25 * 30) / (d_rel / 3 + 30), 15.0f, 30.0f) * 2.35;
    float x = std::clamp((float)vd.x(), 0.f, width - sz / 2);
    float y = std::fmin(height - sz * .6, (float)vd.y());

    float g_xo = sz / 5;
    float g_yo = sz / 10;



    float leadDistance = scene->custom.leadDistance;
    QVector<QPointF> polygonData;
    int szFont = 30;
    int szPoint = 0;
    QRect rcText;
    if( leadDistance && leadDistance < 150  ) // real radar State.
    {
      qreal centerX = x;
      qreal centerY = y;
      qreal radius = sz;// * 1.0;
      szPoint = 8;

      currentAngle += 0.1;  // 필요에 따라 회전 속도 조절
      if (currentAngle >= 2 * M_PI)
          currentAngle -= 2 * M_PI;

      const int numPoints = 12;  // 예시로 36개의 점을 사용하여 원을 근사
      for (int i = 0; i < numPoints; ++i)
      {
          qreal angle = i * 2 * M_PI / numPoints;
          qreal pointX = centerX + radius * qCos(angle + currentAngle);
          qreal pointY = centerY + radius * qSin(angle + currentAngle);
          polygonData.append( QPointF(pointX, pointY) );
      }

      szFont = 50;
      rcText = QRect(x - (sz * 1.25), y - (sz*0.45), 2 * (sz * 1.25),  sz );
      p.setBrush(QColor(218, 202, 37, 255));
      p.drawPolygon(polygonData.data(), polygonData.size());

    }
    else  // vision status.
    {
      QPointF glow[] = {{x + (sz * 1.35) + g_xo, y + sz + g_yo}, {x, y - g_yo}, {x - (sz * 1.35) - g_xo, y + sz + g_yo}};
      p.setBrush(QColor(218, 202, 37, 255));
      p.drawPolygon(glow, std::size(glow));

      rcText = QRect(x - (sz * 1.25), y, 2 * (sz * 1.25), sz * 1.25);
      polygonData = {{x + (sz * 1.25), y + sz}, {x, y}, {x - (sz * 1.25), y + sz}};
    }
    p.setBrush(redColor(fillAlpha));
    p.drawPolygon(polygonData.data(), polygonData.size());


    if ( szPoint && !polygonData.isEmpty()) {
        QPointF start = polygonData[0];
        p.setBrush( QColor( 255 - fillAlpha,  fillAlpha, 0) );
        p.drawEllipse(start, szPoint, szPoint);
    }


    QString  str;
    str.sprintf("%.0f",d_rel);
    p.setPen( QColor(0, 0, 0) );
    p.setFont( InterFont(szFont, QFont::Normal));
    p.drawText(rcText, Qt::AlignCenter, str);
}

void OnPaint::drawHud(QPainter &p)
{
  if( !is_debug ) return;

  ui_main_debug( p );

  ui_main_navi( p );

  //ui_graph( p );


  if( m_param.ui.getDebug() )
  {
    ui_draw_debug1( p );
  }

  // 2. tpms
  if( m_param.ui.getTpms() )
  {
    bb_draw_tpms( p, 75, 800);
  }

  if( m_param.ui.getKegman() )
  {
     bb_ui_draw_UI( p );
  }
}


 void OnPaint::ui_graph( QPainter &p )
 {
    /*
    int bottom = 300;
    //int interval = 2;  // 간격을 설정합니다.

    SubMaster &sm2 = *(m_sm);
    auto navModel = sm2["navModel"].getNavModel();
    auto features = navModel.getFeatures();

    float  scale = 500;

    // features의 크기만큼 반복하여 수직 선을 그립니다.
    for (int i = 1; i < features.size(); ++i)
    {
        int x = i;  // 간격을 이용하여 x좌표 계산
       p.drawLine( (x - 1)*5, bottom + features[i - 1]*scale, x*5, bottom + features[i]*scale);
    }
    */
 }


int  OnPaint::showCarTracking()
{
    return  is_carTracking;
}

void OnPaint::drawSpeed(QPainter &p, int x, QString speedStr, QString speedUnit )
{
  // x = rect().center().x();
   QColor  val_color = QColor(255, 255, 255, 255); // QColor(0x80, 0xd8, 0xa6, 0xff); // QColor(255, 255, 255, 255);
   int  brakePress = m_nBrakeStatus & 0x01;
   int  brakeLights = m_nBrakeStatus & 0x02;
   float  gasVal = m_gasVal * 100;


  if( m_param.breakPos > 0)
  {
    auto interp_color = [=](QColor c1, QColor c2, QColor c3) {
      return m_param.breakPos > 0 ? interpColor( m_param.breakPos, {0, 60, 130}, {c1, c2, c3}) : c1;
    };
    if( brakeLights )
    {
       val_color = interp_color(QColor(201, 34, 49, 100), QColor(255, 34, 0), QColor(255, 0, 0));
    }
    else
    {
       val_color = interp_color(QColor(255, 255, 255), QColor(200, 100, 50), QColor(255, 0, 0));
    }
  }
  else if( brakeLights ) val_color = QColor(201, 34, 49, 100);
  else if( brakePress  ) val_color = QColor(255, 0, 0, 255);
  else if (gasVal > 0) {
    auto interp_color = [=](QColor c1, QColor c2) {
      return gasVal > 0 ? interpColor( gasVal, { 5,  60}, {c1, c2}) : c1;
    };
    val_color = interp_color(QColor(255, 255, 255), QColor(255, 255, 0));
  }



  // current speed
  p.setFont(InterFont(176, QFont::Bold));
  p.setPen( val_color );
  drawText3(p, x, 210, speedStr, val_color );
  p.setFont(InterFont(66));
  drawText3(p, x, 290, speedUnit, QColor(255,255,255,200) );


  QString  str;
  str.sprintf("%.0f/%.0f", m_param.breakPos, gasVal );
  p.setFont(InterFont(30));
  drawText3(p, x, 335, str, QColor(255,255,255,200) );
}


void OnPaint::ui_main_navi( QPainter &p )
{
  QString text4;
  int     bb_x = 50;
  int     bb_y = 430;
  int     bb_w = 190;


  if( m_nda.camLimitSpeedLeftDist > 0)
  {
    text4.sprintf("%d", m_nda.camLimitSpeedLeftDist );
    QRect rc( bb_x, bb_y, bb_w, 85);
    p.setPen( QColor(0, 0, 0, 255) );
    p.setBrush(QColor(255, 255, 255, 100));
    p.drawRoundedRect(rc, 20, 20);
    p.setFont(InterFont(66, QFont::Bold));
    p.drawText( rc, Qt::AlignCenter, text4);
  }
}


// tpms by neokii
QColor OnPaint::get_tpms_color(int tpms)
{
    if(tpms < 5 || tpms > 60) // N/A
        return QColor(125, 125, 125, 200);
    if(tpms < 30)
        return QColor(255, 90, 90, 200);
    return QColor(255, 255, 255, 200);
}

QString OnPaint::get_tpms_text(int tpms)
{
    if(tpms < 5 || tpms > 200)
        return "-";

    QString str;
    str.sprintf("%d", tpms );
    return str;
}

void OnPaint::bb_draw_tpms(QPainter &p, int x, int y )
{
    int fl = m_param.tpmsData.getFl();
    int fr = m_param.tpmsData.getFr();
    int rl = m_param.tpmsData.getRl();
    int rr = m_param.tpmsData.getRr();

    const int w = 58;
    const int h = 126;
    const int margin = 45;



    p.setFont(InterFont(38, QFont::Bold));
    drawText2( p, x   -margin, y+10,   Qt::AlignRight, get_tpms_text(fl), get_tpms_color(fl)  );
    drawText2( p, x+w +margin, y+10,   Qt::AlignLeft,  get_tpms_text(fr), get_tpms_color(fr)  );

    drawText2( p, x   -margin, y+h+20, Qt::AlignRight, get_tpms_text(rl), get_tpms_color(rl)  );
    drawText2( p, x+w +margin, y+h+20, Qt::AlignLeft,  get_tpms_text(rr), get_tpms_color(rr)  );

    p.setPen( QColor(255, 255, 255, 255) );
}



void OnPaint::ui_draw_debug1( QPainter &p )
{
  QString text1 = QString::fromStdString(alert.alertTextMsg1);
  QString text2 = QString::fromStdString(alert.alertTextMsg2);
  QString text3 = QString::fromStdString(alert.alertTextMsg3);

  int bb_x = 250;
  int bb_y = 930;
  int bb_w = state->fb_w - 500;// 1600;//width();

  QRect rc( bb_x, bb_y, bb_w, 90);

  p.setPen( QColor(255, 255, 255, 255) );
  p.setBrush(QColor(0, 0, 0, 100));
  p.drawRoundedRect(rc, 20, 20);


  QTextOption  textOpt =  QTextOption( Qt::AlignLeft );
  p.setFont(InterFont(40));
  //configFont( p, "Open Sans",  40, "Regular");


  p.drawText( QRect(bb_x, 0, bb_w, 42), text1, textOpt );
  p.drawText( QRect(bb_x, bb_y, bb_w, 42), text2, textOpt );
  p.drawText( QRect(bb_x, bb_y+45, bb_w, 42), text3, textOpt );
}


void OnPaint::ui_main_debug(QPainter &p)
{
  int  bb_x = 270;
  int  bb_y = 90;
  int  nGap = 30;

  if( m_param.debug.getIdx1() )
  {

  //float steerRatio = m_jsonobj["ParamSteerRatio"].toDouble();
  //float stiffnessFactor = m_jsonobj["ParamStiffnessFactor"].toDouble();
  //float angleOffsetDeg = m_jsonobj["ParamAngleOffsetDeg"].toDouble();


    SubMaster &sm2 = *(m_sm);
    auto lp = sm2["liveParameters"].getLiveParameters();

    float fSR = lp.getSteerRatio();
    float fSF = lp.getStiffnessFactor();

    float fSteerRatio =  m_param.community.getSteerRatio()
    float fStiffnessFactor = m_param.community.getStiffnessFactor()
    float fAngleOffsetDeg = m_param.community.getAngleOffsetDeg()


    QString text;

    p.setFont(InterFont(38));
    p.setPen( QColor(255, 255, 255, 255) );
    text.sprintf("Panda=%d started=%d sensor=%.1f", m_param.controlsAllowed, scene->started, scene->light_sensor );
    p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;

    text.sprintf("ignition=%d", scene->ignition  );               p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;
    text.sprintf("idle_ticks=%d", scene->custom.idle_ticks  );    p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;
    text.sprintf("target=%d", scene->custom.target  );            p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;


    text.sprintf("SR=%.3f", fSR  );            p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;
    text.sprintf("SF=%.3f", fSF  );            p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;

    text.sprintf("ui SR=%.3f", fSteerRatio  );            p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;
    text.sprintf("ui SF=%.3f", fStiffnessFactor  );            p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;
    text.sprintf("ui AO=%.3f", fAngleOffsetDeg  );            p.drawText( bb_x, bb_y+nGap, text ); nGap += 40;

  }
}


//BB START: functions added for the display of various items
int OnPaint::bb_ui_draw_measure(QPainter &p,  const QString &bb_value, const QString &bb_uom, const QString &bb_label,
    int bb_x, int bb_y, int bb_uom_dx,
    QColor bb_valueColor, QColor bb_labelColor, QColor bb_uomColor,
    int bb_valueFontSize, int bb_labelFontSize, int bb_uomFontSize, int bb_uom_dy )
{

  int dx = 0;
  int nLen = bb_uom.length();
  if (nLen > 0) {
    dx = (int)(bb_uomFontSize*2.5/2);
   }


  //print value
  p.setFont(InterFont(bb_valueFontSize*2));
  //configFont( p, "Open Sans",  bb_valueFontSize*2, "SemiBold");
  drawText1( p, bb_x-dx/2, bb_y+ (int)(bb_valueFontSize*2.5)+5,  bb_value, bb_valueColor );
  //print label
  p.setFont(InterFont(bb_valueFontSize));
  //configFont( p, "Open Sans",  bb_valueFontSize*1, "Regular");
  drawText1( p, bb_x, bb_y + (int)(bb_valueFontSize*2.5)+5 + (int)(bb_labelFontSize*2.5)+5,  bb_label, bb_labelColor);

  //print uom
  if (nLen > 0) {

    int rx =bb_x + bb_uom_dx + bb_valueFontSize -3;
    int ry = bb_y + bb_uom_dy + (int)(bb_valueFontSize*2.5/2)+25;
    //configFont( p, "Open Sans",  bb_uomFontSize*2, "Regular");
    p.setFont(InterFont(bb_uomFontSize*2));
    p.save();
    p.translate( rx, ry);
    p.rotate( -90 );
    p.setPen( bb_uomColor ); //QColor(0xff, 0xff, 0xff, alpha));
    p.drawText( 0, 0, bb_uom);
    //drawText( p, 0, 0, bb_uom, bb_uomColor);
    p.restore();
  }
  return (int)((bb_valueFontSize + bb_labelFontSize)*2.5) + 5;
}


QColor OnPaint::get_color( int nVal, int nRed, int nYellow )
{
  QColor  lab_color =  QColor(255, 255, 255, 255);

      if(nVal > nRed) {
        lab_color = QColor(255, 0, 0, 200);
      } else if( nVal > nYellow) {
        lab_color = QColor(255, 188, 3, 200);
      }

  return lab_color;
}


QColor OnPaint::angleSteersColor( int angleSteers )
{
    QColor val_color = QColor(255, 255, 255, 200);

    if( (angleSteers < -30) || (angleSteers > 30) ) {
      val_color = QColor(255, 175, 3, 200);
    }
    if( (angleSteers < -55) || (angleSteers > 55) ) {
      val_color = QColor(255, 0, 0, 200);
    }

    return val_color;
}


void OnPaint::bb_ui_draw_measures_left(QPainter &p, int bb_x, int bb_y, int bb_w )
{
  int bb_rx = bb_x + (int)(bb_w/2);
  int bb_ry = bb_y;
  int bb_h = 5;
  QColor lab_color = QColor(255, 255, 255, 200);
  QColor uom_color = QColor(255, 255, 255, 200);
  int value_fontSize=25;
  int label_fontSize=15;
  int uom_fontSize = 15;
  int bb_uom_dx =  (int)(bb_w /2 - uom_fontSize*2.5) ;


  if( bbh_left > 5 )
  {
    QRect rc( bb_x, bb_y, bb_w, bbh_left);
    p.setPen(QPen(QColor(0xff, 0xff, 0xff, 100), 3));
    p.setBrush(QColor(0, 0, 0, 100));
    p.drawRoundedRect(rc, 20, 20);
    p.setPen(Qt::NoPen);
  }


  QString val_str;
  QString uom_str;

  //add visual radar relative distance
  if( true )
  {
    QColor val_color = QColor(255, 255, 255, 200);

    if ( m_param.lead_radar.getStatus() ) {
      //show RED if less than 5 meters
      //show orange if less than 15 meters
      float d_rel2 = m_param.lead_radar.getDRel();

      if((int)(d_rel2) < 15) {
        val_color = QColor(255, 188, 3, 200);
      }
      if((int)(d_rel2) < 5) {
        val_color = QColor(255, 0, 0, 200);
      }
      // lead car relative distance is always in meters
      val_str.sprintf("%d", (int)d_rel2 );
    } else {
       val_str = "-";
    }

    auto lead_cam = (*state->sm)["modelV2"].getModelV2().getLeadsV3()[0];  // camera
    if (lead_cam.getProb() > 0.1) {
      float d_rel1 = lead_cam.getX()[0];
      uom_str.sprintf("%d", (int)d_rel1 );
    }
    else
    {
      uom_str = "m";
    }

    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "REL DIST",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }

  //add visual radar relative speed
  if( false )
  {
    QColor val_color = QColor(255, 255, 255, 200);
    if ( m_param.lead_radar.getStatus() ) {
      float v_rel = m_param.lead_radar.getVRel();

      if((int)(v_rel) < 0) {
        val_color = QColor(255, 188, 3, 200);
      }
      if((int)(v_rel) < -5) {
        val_color = QColor(255, 0, 0, 200);
      }
      // lead car relative speed is always in meters
      if (scene->is_metric) {
        val_str.sprintf("%d", (int)(v_rel * 3.6 + 0.5) );
      } else {
        val_str.sprintf("%d", (int)(v_rel * 2.2374144 + 0.5));
      }
    } else {
       val_str = "-";
    }
    if (scene->is_metric) {
      uom_str = "km/h";
    } else {
      uom_str = "mph";
    }
    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "REL SPEED",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }

  //add  steering angle
  if( true )
  {
    QColor val_color = QColor(0, 255, 0, 200);

    val_color = angleSteersColor( (int)(m_param.angleSteers) );

    // steering is in degrees
    val_str.sprintf("%.1f",m_param.angleSteers);

    // steering is in degrees des
    uom_str = "des";

    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "REAL STEER",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }

  //finally draw the frame
  bb_h += 20;
  bbh_left = bb_h;
}

QString OnPaint::gearGap( int gear_step, QColor &color )
{
    QString  strGap;

    color = QColor(0, 180, 255, 220);
    if (gear_step == 0) strGap = "P";
    else if (gear_step == 1) strGap = "■";
    else if (gear_step == 2) strGap = "■■";
    else if (gear_step == 3) strGap = "■■■";
    else if (gear_step == 4) strGap = "■■■■■";
    else if (gear_step == 5) strGap = "■■■■■■";
    else strGap = "■■■■■■■";

    return strGap;
}

void OnPaint::bb_ui_draw_measures_right( QPainter &p, int bb_x, int bb_y, int bb_w )
{
  int bb_rx = bb_x + (int)(bb_w/2);
  int bb_ry = bb_y;
  int bb_h = 5;
  int value_fontSize=25;
  int label_fontSize=15;
  int uom_fontSize = 15;
  int bb_uom_dx =  (int)(bb_w /2 - uom_fontSize*2.5) ;
  int max_item = 7;

  QColor lab_color = QColor(255, 255, 255, 200);
  QColor uom_color = QColor(255, 255, 255, 200);


  if ( bbh_right > 5 )
  {
    QRect rc( bb_x, bb_y, bb_w, bbh_right);
    p.setPen(QPen(QColor(0xff, 0xff, 0xff, 100), 3));
    p.setBrush(QColor(0, 0, 0, 100));
    p.drawRoundedRect(rc, 20, 20);
    p.setPen(Qt::NoPen);
  }


  QString val_str;
  QString uom_str;
  int     nCnt = 0;

  //add CPU temperature
  if( m_param.ui.getKegmanCPU() )
  {
    nCnt++;
    if( nCnt > max_item ) return;
    if( m_param.cpuTemp > 100 )  m_param.cpuTemp = 0;

    QColor val_color = QColor(255, 255, 255, 200);

     val_color = get_color(  (int)m_param.cpuTemp, 92, 80 );
     lab_color = get_color(  (int)m_param.cpuPerc, 90, 60 );

      // temp is alway in C * 10
      val_str.sprintf("%.1f", m_param.cpuTemp );
      uom_str.sprintf("%d", m_param.cpuPerc);
      bb_h += bb_ui_draw_measure(p,  val_str, uom_str, "CPU TEMP",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );

    bb_ry = bb_y + bb_h;
  }



  if( m_param.ui.getKegmanLag() )
  {
    nCnt++;
    if( nCnt > max_item ) return;
    QColor val_color = QColor(255, 255, 255, 200);
    if( m_param.cumLagMs  < 10 )
      val_color = QColor(0, 255, 0, 200);
    else if( m_param.cumLagMs  > 100 )
      val_color = QColor(255, 0, 0, 200);

    val_str.sprintf("%3.0f", m_param.cumLagMs );
    uom_str = "ms";
    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "Lag",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }


   //add battery voltage
   lab_color = QColor(255, 255, 255, 200);
  if( m_param.ui.getKegmanBattery() )
  {
    nCnt++;
    if( nCnt > max_item ) return;
    QColor val_color = QColor(255, 255, 255, 200);

    if( m_param.batteryVoltage > 14.7 ) val_color = QColor(255, 100, 0, 200);
    else if( m_param.batteryVoltage < 11.7 ) val_color = QColor(255, 0, 0, 200);
    else if( m_param.batteryVoltage < 12.0 ) val_color = QColor(255, 100, 0, 200);


    val_str.sprintf("%.1f", m_param.batteryVoltage );
    uom_str = "volt";
    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "battery",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }


  //add grey panda GPS accuracy
  if( m_param.ui.getKegmanGPU() )
  {
    nCnt++;
    if( nCnt > max_item ) return;
    QColor val_color = QColor(255, 255, 255, 200);
    //show red/orange if gps accuracy is low
     val_color = get_color( (int)m_param.gpsAccuracyUblox, 5, 2 );

    // gps accuracy is always in meters
    if(m_param.gpsAccuracyUblox > 99 || m_param.gpsAccuracyUblox == 0) {
       val_str = "-";
    }else if(m_param.gpsAccuracyUblox > 9.99) {
      val_str.sprintf("%.1f", m_param.gpsAccuracyUblox );
    }
    else {
      val_str.sprintf("%.2f", m_param.gpsAccuracyUblox );
    }
    uom_str.sprintf("%.1f", m_param.altitudeUblox);
    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "GPS PREC",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }


  //add  steering angle
  if( m_param.ui.getKegmanAngle() )
  {
    nCnt++;
    if( nCnt > max_item ) return;
    QColor val_color = QColor(0, 255, 0, 200);

    val_color = angleSteersColor( (int)(m_param.angleSteers) );

    // steering is in degrees
    val_str.sprintf("%.1f",m_param.angleSteers);

    // steering is in degrees des
    uom_str = "des";

    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "REAL STEER",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }


  //add visual radar relative distance
  if( m_param.ui.getKegmanDistance() )
  {
    nCnt++;
    if( nCnt > max_item ) return;
    QColor val_color = QColor(255, 255, 255, 200);
    uom_color = QColor(255, 255, 255, 200);
    if ( m_param.lead_radar.getStatus() ) {
      //show RED if less than 5 meters
      //show orange if less than 15 meters
      float d_rel2 = m_param.lead_radar.getDRel();

      if((int)(d_rel2) < 15) {
        val_color = QColor(255, 188, 3, 200);
      }
      if((int)(d_rel2) < 5) {
        val_color = QColor(255, 0, 0, 200);
      }
      // lead car relative distance is always in meters
      val_str.sprintf("%d", (int)d_rel2 );
    } else {
       val_str = "-";
    }

    auto lead_cam = (*state->sm)["modelV2"].getModelV2().getLeadsV3()[0];  // camera
    if (lead_cam.getProb() > 0.1) {
      float d_rel1 = lead_cam.getX()[0];
      uom_str.sprintf("%d", (int)d_rel1 );
    }
    else
    {
      uom_str = "m";
    }

    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "REL DIST",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }

  //add visual radar relative speed
  if( m_param.ui.getKegmanSpeed()  )
  {
    nCnt++;
    if( nCnt > max_item ) return;
    QColor val_color = QColor(255, 255, 255, 200);
    uom_color = QColor(255, 255, 255, 200);
    if ( m_param.lead_radar.getStatus() ) {
      float v_rel = m_param.lead_radar.getVRel();

      if((int)(v_rel) < 0) {
        val_color = QColor(255, 188, 3, 200);
      }
      if((int)(v_rel) < -5) {
        val_color = QColor(255, 0, 0, 200);
      }
      // lead car relative speed is always in meters
      if (scene->is_metric) {
        val_str.sprintf("%d", (int)(v_rel * 3.6 + 0.5) );
      } else {
        val_str.sprintf("%d", (int)(v_rel * 2.2374144 + 0.5));
      }
    } else {
       val_str = "-";
    }
    if (scene->is_metric) {
      uom_str = "km/h";
    } else {
      uom_str = "mph";
    }
    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "REL SPEED",
        bb_rx, bb_ry, bb_uom_dx,
        val_color, lab_color, uom_color,
        value_fontSize, label_fontSize, uom_fontSize );
    bb_ry = bb_y + bb_h;
  }


  // add engine
  if( m_param.ui.getKegmanEngine() )
  {
    nCnt++;
    if( nCnt > max_item ) return;
    float fEngineRpm = m_param.enginRpm;
    int   electGearStep  = m_param.electGearStep;

    uom_color = QColor(255, 255, 255, 200);
    QColor val_color = QColor(255, 255, 255, 200);

    if (  fEngineRpm <= 0 )
    {
      val_str.sprintf("EV");
      val_color = QColor(0, 255, 0, 200);
    }
    else
    {
      val_str.sprintf("%.0f", fEngineRpm);
      if( fEngineRpm > 2000 ) val_color = QColor(255, 188, 3, 200);
      else if( fEngineRpm > 3000 ) val_color = QColor(255, 0, 0, 200);
    }

    uom_str = gearGap( electGearStep, uom_color );
    bb_h +=bb_ui_draw_measure(p,  val_str, uom_str, "ENGINE",
      bb_rx, bb_ry, bb_uom_dx,
      val_color, lab_color, uom_color,
      value_fontSize, label_fontSize, 8, 60 );
    bb_ry = bb_y + bb_h;
  }





  //finally draw the frame
  bb_h += 20;
  bbh_right = bb_h;
}


void OnPaint::bb_ui_draw_UI(QPainter &p)
{
  //const int bb_dml_w = 180;
  //const int bb_dml_x = (0 + bdr_s) + 20;
  //const int bb_dml_y = (0 + bdr_s) + 430;


  const int bb_dmr_w = 180;
  const int bb_dmr_x = 0 + state->fb_w - bb_dmr_w - bdr_s;
  const int bb_dmr_y = (0 + bdr_s) + 220;


  // 1. kegman ui
  //bb_ui_draw_measures_left(p, bb_dml_x, bb_dml_y, bb_dml_w);
  bb_ui_draw_measures_right(p, bb_dmr_x, bb_dmr_y, bb_dmr_w);
}
//BB END: functions added for the display of various itemsapType


