#pragma once

#include <cstdint>

#include <QStackedLayout>
#include <QWidget>

#include "common/params.h"
#include "selfdrive/ui/ui.h"
#include "selfdrive/ui/qt/custom/widgetNetImg.h"
#include "selfdrive/ui/qt/custom/osm_minimap.h"


/*
Qt::white,
Qt::black,
Qt::red,
Qt::darkRed,
Qt::green,
Qt::darkGreen,
Qt::blue,
Qt::darkBlue,
Qt::cyan,
Qt::darkCyan,
Qt::magenta,
Qt::darkMagenta,
Qt::yellow,
Qt::darkYellow,
Qt::gray,
Qt::darkGray,
Qt::lightGray
*/


typedef struct {
    int id;
    float x, y, d, v, y_rel, v_lat;
} lead_vertex_data;
class OnPaint : public QObject
{
  Q_OBJECT


public:
  explicit OnPaint();
  void    updateState(const UIState &s);
  void    drawHud(QPainter &p);
  bool    handleMousePress(const QPoint &pt, const QRect &surface);
  bool    handleMouseRelease(const QPoint &pt, const QRect &surface);
  void    drawSpeed(QPainter &p, int x, QString speedStr, QString speedUnit );
  void    drawSpeedCameraAlert(QPainter &p, const QRect &set_speed_rect);
  void    drawLead(QPainter &p, const cereal::RadarState::LeadData::Reader &lead_data, const QPointF &vd, int w, int h );

private:
  void    drawText1(QPainter &p, int x, int y, const QString &text, QColor qColor = QColor(255,255,255,255), int nAlign = Qt::AlignCenter  );
  void    drawText2(QPainter &p, int x, int y, int flags, const QString &text, const QColor color = QColor(255, 255, 255, 220) );
  void    drawText3(QPainter &p, int x, int y, const QString &text, QColor color);

private:
  void   ui_main_navi( QPainter &p );
  bool   speedCameraAlert(int &cam_type, int &limit_speed, int &distance_m, bool &signal_camera);
  QString cameraTypeLabel(int cam_type, bool signal_camera) const;
  void   drawSpeedLimitSign(QPainter &p, const QPointF &center, int radius, int cam_type, int limit_speed, bool signal_camera) const;
  void   drawSignalBadge(QPainter &p, double center_x, double top_y) const;

private:
  inline QColor redColor(int alpha = 255) { return QColor(201, 34, 49, alpha); }
  inline QColor whiteColor(int alpha = 255) { return QColor(255, 255, 255, alpha); }
  inline QColor blackColor(int alpha = 255) { return QColor(0, 0, 0, alpha); }

private:
  UIState  *state;
  UIScene  *scene;

  std::unique_ptr<SubMaster> m_sm;

  int m_width;
  int m_height;
  int bbh_left = 0;
  int bbh_right = 0;
  const int bdr_s = 30;

  int  touched_old = 0;
  Params params;
  bool osm_enabled = false;
  int osm_minimap_position = 3;
  int osm_debug_map_zoom = 0;
  int osm_gps_sim_speed_kph = 60;
  bool osm_debug_zoom_pressed = false;
  bool osm_debug_speed_pressed = false;
  bool osm_show_suspicious_cameras = true;
  bool osm_debug_zoom_controls_enabled = false;
  bool osm_debug_speed_controls_enabled = false;

  struct _PARAM_
  {
    cereal::RadarState::LeadData::Reader lead_radar;
    cereal::CarState::CarSCustom::Tpms::Reader tpmsData;

    cereal::UICustom::Community::Reader community;
    cereal::UICustom::UserInterface::Reader ui;
    cereal::UICustom::Debug::Reader debug;



    int   cpuPerc;
    float cpuTemp;
    int   gpuPerc;
    float gpuTemp;

    int   electGearStep;
    float   breakPos;

    float  angleSteers;
    int   enginRpm = 0;

    float batteryVoltage;

    float altitudeUblox;
    float gpsAccuracyUblox;

    float cumLagMs;

    int   enabled, engaged;
    int   controlsAllowed;
    float vEgo;

  } m_param;

  struct _STATUS_
  {
      std::string alertTextMsg1;
      std::string alertTextMsg2;
      std::string alertTextMsg3;
  } alert;

  struct _NDA
  {
     int activeNDA;
     int camType;
     int roadLimitSpeed;
     int camLimitSpeed;
     int camLimitSpeedLeftDist;
     int cntIdx;
     OsmMinimapData osmRoadOverlay;
  } m_nda;

  uint64_t osm_active_camera_id = 0;


private:
   NetworkImageWidget *icon_01;
   OsmMinimapRenderer osm_minimap;
   //QPixmap img_tire_pressure;
   int  is_debug;
   int  is_carTracking;

   int    m_nBrakeStatus = 0;
   float  m_gasVal = 0;
   float  currentAngle = 0.0;

private:
  void   configFont(QPainter &p, const QString &family, int size, const QString &style);

// navi
private:
  float     interp( float xv, float xp[], float fp[], int N);
  int       get_param( const std::string &key );
  QString   gearGap( int gear_step, QColor &color );
// tpms
private:
  QColor   get_tpms_color(int tpms);
  QString  get_tpms_text(int tpms);
  void     bb_draw_tpms(QPainter &p, int x, int y );
  void     ui_draw_debug1( QPainter &p );
  void     ui_main_debug(QPainter &p);
  void     ui_graph( QPainter &p );

// kegmen
private:
  int  bb_ui_draw_measure(QPainter &p,  const QString &bb_value, const QString &bb_uom, const QString &bb_label,
    int bb_x, int bb_y, int bb_uom_dx,
    QColor bb_valueColor, QColor bb_labelColor, QColor bb_uomColor,
    int bb_valueFontSize, int bb_labelFontSize, int bb_uomFontSize, int bb_uom_dy = 0 );

  void bb_ui_draw_measures_right(QPainter &p, int bb_x, int bb_y, int bb_w );
  void bb_ui_draw_measures_left(QPainter &p, int bb_x, int bb_y, int bb_w );

  QColor  get_color( int nVal, int nRed, int nYellow );
  QColor angleSteersColor( int angleSteers );

  void  bb_ui_draw_UI(QPainter &p);

// apilot
 private:
    void  ui_draw_text( QPainter &p, const QRect& rc, const QString& text, float  size, const QColor& crBrush, const QColor& color=Qt::white );


public:
    int  showCarTracking();

signals:


};
