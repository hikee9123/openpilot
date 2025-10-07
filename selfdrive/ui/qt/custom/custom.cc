#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>
#include <tuple>
#include <vector>
#include <cstdlib>
#include <algorithm>   // std::clamp

#include <QTabWidget>
#include <QObject>
#include <QJsonArray>
#include <QProcess>
#include <QDir>
#include <QDebug>
#include <QtConcurrent>
#include <QVariant>

#include <QHBoxLayout>
#include <QScrollArea>

#include "common/watchdog.h"
#include "common/params.h"
#include "common/watchdog.h"
#include "common/util.h"



#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/custom/custom.h"






CollapsibleSection::CollapsibleSection(const QString& title, QWidget* parent)
  : QWidget(parent)
{
  auto* root = new QVBoxLayout(this);
  root->setContentsMargins(0,0,0,0);
  root->setSpacing(6);

  m_headerBtn = new QToolButton(this);
  m_headerBtn->setText(title);
  m_headerBtn->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
  m_headerBtn->setArrowType(Qt::DownArrow);
  m_headerBtn->setCheckable(true);
  m_headerBtn->setChecked(true);
  m_headerBtn->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
  m_headerBtn->setStyleSheet("QToolButton{ font-weight:600; font-size:18px; }");
  root->addWidget(m_headerBtn);

  m_body = new QFrame(this);
  m_body->setFrameShape(QFrame::NoFrame);
  m_bodyLayout = new QVBoxLayout(m_body);
  m_bodyLayout->setContentsMargins(12, 6, 0, 6);
  m_bodyLayout->setSpacing(6);
  root->addWidget(m_body);

  // 애니메이션으로 접기/펼치기
  m_anim = new QPropertyAnimation(m_body, "maximumHeight", this);
  m_anim->setDuration(150);

  connect(m_headerBtn, &QToolButton::clicked, this, [this]{
    toggle();
  });
}

void CollapsibleSection::addWidget(QWidget* w) {
  m_bodyLayout->addWidget(w);
}

void CollapsibleSection::setExpanded(bool on) {
  if (m_expanded == on) return;
  toggle();
}

void CollapsibleSection::toggle() {
  m_expanded = !m_expanded;
  m_headerBtn->setArrowType(m_expanded ? Qt::DownArrow : Qt::RightArrow);

  m_body->setVisible(true); // 애니메이션 시작 전 보이도록
  int start = m_body->maximumHeight();
  int end   = 0;

  if (m_expanded) {
    // 펼칠 때 목표 높이 계산: sizeHint 사용
    m_body->setMaximumHeight(QWIDGETSIZE_MAX);
    end = m_body->sizeHint().height();
    m_body->setMaximumHeight(start); // 애니메이션 시작점 복원
  }

  m_anim->stop();
  m_anim->setStartValue(start < 0 ? 0 : start);
  m_anim->setEndValue(m_expanded ? end : 0);
  m_anim->start();

  if (!m_expanded) {
    connect(m_anim, &QPropertyAnimation::finished, this, [this]{
      if (!m_expanded) m_body->setVisible(false);
    });
  }
}

void CollapsibleSection::setHeaderFont(const QFont& f) {
  if (m_headerBtn) m_headerBtn->setFont(f);
}

void CollapsibleSection::setBodyFont(const QFont& f) {
  if (m_body) {
    m_body->setFont(f);
    // 이미 추가된 자식들에게도 적용하고 싶다면:
    const auto children = m_body->findChildren<QWidget*>();
    for (QWidget* w : children) w->setFont(f);
  }
}

void CollapsibleSection::setSectionFont(const QFont& header, const QFont& body) {
  setHeaderFont(header);
  setBodyFont(body);
}




// json
CValueControl::CValueControl(const QString& param,
                             const QString& title,
                             const QString& desc,
                             const QString& icon,
                             double min, double max, double unit,
                             double defVal,
                             QJsonObject& jsonobj,
                             QWidget* parent)
  : AbstractControl(title, desc, icon, parent)
  , m_jsonobj(jsonobj)
  , m_key(param) {

  if (min > max) std::swap(min, max);
  if (unit <= 0.0) unit = 1.0;
  m_min = min; m_max = max; m_unit = unit;

  m_def = std::clamp(defVal, m_min, m_max);

  m_decimal = decimalsFor( m_unit );

  m_label.setAlignment(Qt::AlignVCenter | Qt::AlignRight);
  m_label.setStyleSheet("color: #e0e879");
  hlayout->addWidget(&m_label);

  static const char* kBtnStyle = R"(
    padding: 0;
    border-radius: 50px;
    font-size: 35px;
    font-weight: 500;
    color: #E4E4E4;
    background-color: #393939;
  )";

  m_btnMinus.setStyleSheet(kBtnStyle);
  m_btnMinus.setFixedSize(150, 100);
  m_btnMinus.setText(QStringLiteral("－"));
  m_btnMinus.setAutoRepeat(true);
  m_btnMinus.setAutoRepeatDelay(300);
  m_btnMinus.setAutoRepeatInterval(60);
  hlayout->addWidget(&m_btnMinus);

  m_btnPlus.setStyleSheet(kBtnStyle);
  m_btnPlus.setFixedSize(150, 100);
  m_btnPlus.setText(QStringLiteral("＋"));
  m_btnPlus.setAutoRepeat(true);
  m_btnPlus.setAutoRepeatDelay(300);
  m_btnPlus.setAutoRepeatInterval(60);
  hlayout->addWidget(&m_btnPlus);

  bool wroteBack = false;
  const double loaded = loadInitial(wroteBack);
  m_value = std::clamp(loaded, m_min, m_max);
  if (wroteBack || std::abs(loaded - m_value) > EPS) {
    m_jsonobj[m_key] = m_value; // JSON에 double 기록
  }

  connect(&m_btnMinus, &QPushButton::pressed, this, [this]{ adjust(-m_unit); });
  connect(&m_btnPlus,  &QPushButton::pressed, this, [this]{ adjust(+m_unit); });

  updateLabel();
  updateToolTip();
}

double CValueControl::getValue() const noexcept { return m_value; }


static inline bool nearInteger(double x) noexcept {
  if (!std::isfinite(x)) return false;

  const double n    = std::round(x);
  const double diff = std::abs(x - n);

  // 값의 크기에 비례한 상대 허용오차(ULP 기반)
  const double ulp  = std::numeric_limits<double>::epsilon();
  const double base = std::max(1.0, std::max(std::abs(x), std::abs(n)));
  const double tol  = ulp * 16 * base;

  return diff <= tol;
}



int CValueControl::decimalsFor(double step)
{
  if (!(step > 0.0) || !std::isfinite(step)) return 0;

  double scale = 1.0;
  for (int d = 0; d <= 5; ++d) {
    const double scaled = step * scale;
    if (nearInteger(scaled)) return d;
    scale *= 10.0;
  }
  return 8;
}

void CValueControl::setValue(double value) {
  // 스텝 스냅(격자 정렬)
  if (m_unit > EPS) {
    const double base = m_min;
    const double steps = std::round((value - base) / m_unit);
    value = base + steps * m_unit;
  }

  const double nv = std::clamp(value, m_min, m_max);
  if (std::abs(m_value - nv) <= EPS) return;

  m_value = nv;
  m_jsonobj[m_key] = m_value;  // QJson은 double로 저장

  updateLabel();
  emit valueChanged(m_value);
  emit clicked();
}

void CValueControl::setRange(double min, double max) {
  if (min > max) std::swap(min, max);
  m_min = min; m_max = max;
  m_def = std::clamp(m_def, m_min, m_max);
  setValue(m_value);   // 재클램프 + 스냅
  updateToolTip();
}

void CValueControl::setStep(double step) {
  if (step <= 0.0) step = 1.0;
  m_unit = step;
  // 현재 값을 새 스텝에 맞춰 재정렬하고 싶다면:
  setValue(m_value);
  updateToolTip();
}

void CValueControl::setDefault(double defVal) {
  m_def = std::clamp(defVal, m_min, m_max);
}

void CValueControl::adjust(double delta) {
  setValue(m_value + delta);
}

void CValueControl::updateLabel() {
  // 보기 좋은 자릿수(불필요한 0 제거). 필요시 고정 소수점으로 바꾸세요.
  m_label.setText(QString::number(m_value, 'f', m_decimal));
}

void CValueControl::updateToolTip() {


  const QString tip = tr("Min: %1, Max: %2, Step: %3, Default: %4")
                        .arg(QString::number(m_min, 'f', m_decimal))
                        .arg(QString::number(m_max, 'f', m_decimal))
                        .arg(QString::number(m_unit, 'f', m_decimal))
                        .arg(QString::number(m_def, 'f', m_decimal));
  this->setToolTip(tip);
  m_label.setToolTip(tip);
  m_btnMinus.setToolTip(tip);
  m_btnPlus.setToolTip(tip);
}

double CValueControl::loadInitial(bool& wroteBack) const noexcept {
  wroteBack = false;

  if (!m_jsonobj.contains(m_key)) {
    wroteBack = true;
    return m_def;
  }
  const QJsonValue v = m_jsonobj.value(m_key);

  if (v.isDouble()) {
    return v.toDouble();
  }
  if (v.isString()) {
    bool ok = false;
    const double d = v.toString().toDouble(&ok);
    if (ok) return d;
    wroteBack = true;
    return m_def;
  }
  if (v.isBool()) {
    return v.toBool() ? 1.0 : 0.0;
  }

  wroteBack = true;
  return m_def;
}


// Params
CValueControl2::CValueControl2(const QString& key, const QString& title, const QString& desc, const QString& icon, int min, int max, int unit/*=1*/)
    : AbstractControl(title, desc, icon)
{

    m_key = key;
    m_min = min;
    m_max = max;
    m_unit = unit;

    label.setAlignment(Qt::AlignVCenter | Qt::AlignRight);
    label.setStyleSheet("color: #e0e879");
    hlayout->addWidget(&label);

    btnminus.setStyleSheet(R"(
    padding: 0;
    border-radius: 50px;
    font-size: 35px;
    font-weight: 500;
    color: #E4E4E4;
    background-color: #393939;
  )");
    btnplus.setStyleSheet(R"(
    padding: 0;
    border-radius: 50px;
    font-size: 35px;
    font-weight: 500;
    color: #E4E4E4;
    background-color: #393939;
  )");
    btnminus.setFixedSize(150, 100);
    btnplus.setFixedSize(150, 100);
    hlayout->addWidget(&btnminus);
    hlayout->addWidget(&btnplus);

    QObject::connect(&btnminus, &QPushButton::released, [=]() {
        auto str = QString::fromStdString(params.get(m_key.toStdString()));
        int value = str.toInt();
        value = value - m_unit;
        if (value < m_min) {
            value = m_min;
        }
        else {
        }


        QString values = QString::number(value);
        params.put(m_key.toStdString(), values.toStdString());
        refresh();
    });

    QObject::connect(&btnplus, &QPushButton::released, [=]() {
        auto str = QString::fromStdString(params.get(m_key.toStdString()));
        int value = str.toInt();
        value = value + m_unit;
        if (value > m_max) {
            value = m_max;
        }
        else {
        }

        QString values = QString::number(value);
        params.put(m_key.toStdString(), values.toStdString());
        refresh();
    });
    refresh();
}

void CValueControl2::refresh()
{
    label.setText(QString::fromStdString(params.get(m_key.toStdString())));
    btnminus.setText("－");
    btnplus.setText("＋");
}
//////////////////////////////////////////////////////////////////////////////////////////////////////
//
//

CustomPanel::CustomPanel(SettingsWindow *parent) : QWidget(parent)
{
  pm.reset( new PubMaster({"uICustom"}) );
  sm.reset( new SubMaster({"carState"}) );

  m_jsonobj = readJsonFile( "CustomParam" );

    QList<QPair<QString, QWidget *>> panels = {
        {tr("UI"), new UITab(this, m_jsonobj)},
        {tr("Community"), new CommunityTab(this, m_jsonobj)},
        {tr("Git"), new GitTab(this, m_jsonobj)},
        {tr("Model"), new ModelTab(this, m_jsonobj)},
        {tr("Debug"), new Debug(this,m_jsonobj)},
        {tr("Navigation"), new NavigationTab(this, m_jsonobj)},
    };


    // 탭 위젯
    QTabWidget *tabWidget = new QTabWidget(this);
    tabWidget->setStyleSheet(R"(
        QTabBar::tab {
            border: 1px solid #C4C4C3;
            border-bottom-color: #C2C7CB; /* 위쪽 선 색상 */
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            min-width: 45ex; /* 탭의 최소 너비 */
            padding: 2px; /* 탭의 내부 여백 */
            margin-right: 1px; /* 탭 사이의 간격 조절 */
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #FAFAFA, stop: 0.4 #F4F4F4,
                                        stop: 0.5 #EDEDED, stop: 1.0 #FAFAFA);
            color: black; /* 글씨 색상 */
        }

        QTabBar::tab:selected {
            border-bottom-color: #B1B1B0; /* 선택된 탭의 위쪽 선 색상 */
            background: white; /* 선택된 탭의 배경 색상 */
            color: black; /* 선택된 탭의 글씨 색상 */
        }

        QTabBar::tab:!selected {
            margin-top: 2px; /* 선택되지 않은 탭의 위치 조절 */
            background: black; /* 선택되지 않은 탭의 배경 색상 */
            color: white; /* 선택되지 않은 탭의 글씨 색상 */
        }
    )");
    for (auto &[name, panel] : panels) {
      panel->setContentsMargins(50, 25, 50, 25);
      ScrollView *panel_frame = new ScrollView(panel, this);
      tabWidget->addTab(panel_frame, name);
    }

    // 탭 위젯을 전체 화면으로 표시
    QVBoxLayout *mainLayout = new QVBoxLayout(this);
    mainLayout->addWidget(tabWidget);
    setLayout(mainLayout);


    QObject::connect(uiState(), &UIState::offroadTransition, this, &CustomPanel::offroadTransition);

    timer = new QTimer(this);
    connect(timer, &QTimer::timeout, this, &CustomPanel::OnTimer);
    timer->start(1000);
}


void CustomPanel::offroadTransition( bool offroad  )
{
  sm->update(0);

  int isActive = timer->isActive();
  if( !isActive  )
  {
    m_cmdIdx = 0;
  }
   updateToggles( false );
}

void CustomPanel::OnTimer()
{
  UIState   *s = uiState();
  UIScene   &scene = s->scene;
  SubMaster &sm2 = *(s->sm);



  sm->update(0);
  if( scene.started )
  {
    m_time = 0;

    updateToggles( false );
    const auto car_state = sm2["carState"].getCarState();
    float vEgo = car_state.getVEgo();
    if( vEgo > 10 )
       scene.custom.m_powerflag = 1;
  }
  else
  {
    m_time++;

    int PowerOff = m_jsonobj["ParamPowerOff"].toInt();
    if( PowerOff && (m_time > PowerOff) && (scene.custom.m_powerflag) )
    {
         scene.custom.m_powerflag = 0;
         params.putBool("DoShutdown", true);
    }
  }
}

//
void CustomPanel::updateToggles( int bSave )
{
  MessageBuilder msg;

  m_cmdIdx++;
  auto custom = msg.initEvent().initUICustom();
  auto debug = custom.initDebug();

  int idx1 = m_jsonobj["debug1"].toBool();
  int idx2 = m_jsonobj["debug2"].toBool();
  int idx3 = m_jsonobj["debug3"].toBool();
  int idx4 = m_jsonobj["debug4"].toBool();
  int idx5 = m_jsonobj["debug5"].toBool();

  debug.setCmdIdx( m_cmdIdx );
  debug.setIdx1( idx1 );
  debug.setIdx2( idx2);
  debug.setIdx3( idx3 );
  debug.setIdx4( idx4 );
  debug.setIdx5( idx5 );


  auto comunity = custom.initCommunity();
  int cruiseMode = m_jsonobj["ParamCruiseMode"].toInt();
  int cruiseGap = m_jsonobj["ParamCruiseGap"].toInt();
  int curveSpeedLimit = m_jsonobj["ParamCurveSpeedLimit"].toInt();
  float steerRatio = m_jsonobj["ParamSteerRatio"].toDouble();
  float stiffnessFactor = m_jsonobj["ParamStiffnessFactor"].toDouble();
  float angleOffsetDeg = m_jsonobj["ParamAngleOffsetDeg"].toDouble();




  comunity.setCmdIdx( m_cmdIdx );
  comunity.setCruiseMode( cruiseMode );
  comunity.setCruiseGap( cruiseGap );
  comunity.setCurveSpeedLimit( curveSpeedLimit );

  comunity.setSteerRatio( steerRatio );
  comunity.setStiffnessFactor( stiffnessFactor );
  comunity.setAngleOffsetDeg( angleOffsetDeg );


  auto ui = custom.initUserInterface();
  int bDebug = m_jsonobj["ShowDebugMessage"].toBool();
  int bCarTracking = m_jsonobj["ShowCarTracking"].toBool();

  int tpms = m_jsonobj["tpms"].toBool();
  int ndebug = m_jsonobj["ParamDebug"].toBool();

  int kegman = m_jsonobj["kegman"].toBool();
  int kegmanCPU = m_jsonobj["kegmanCPU"].toBool();
  int kegmanBattery = m_jsonobj["kegmanBattery"].toBool();
  int kegmanGPU = m_jsonobj["kegmanGPU"].toBool();
  int kegmanAngle = m_jsonobj["kegmanAngle"].toBool();
  int kegmanEngine = m_jsonobj["kegmanEngine"].toBool();
  int kegmanDistance = m_jsonobj["kegmanDistance"].toBool();
  int kegmanSpeed = m_jsonobj["kegmanSpeed"].toBool();
  int kegmanLag = m_jsonobj["kegmanLag"].toBool();

  int _autoScreenOff = m_jsonobj["ParamAutoScreenOff"].toInt();
  int _brightness = m_jsonobj["ParamBrightness"].toInt();






  ui.setCmdIdx( m_cmdIdx );
  ui.setShowDebugMessage( bDebug );
  ui.setShowCarTracking( bCarTracking );
  ui.setTpms( tpms );
  ui.setDebug( ndebug );

  ui.setKegman( kegman );
  ui.setKegmanCPU( kegmanCPU );
  ui.setKegmanBattery( kegmanBattery );
  ui.setKegmanGPU( kegmanGPU );
  ui.setKegmanAngle( kegmanAngle );
  ui.setKegmanEngine( kegmanEngine );
  ui.setKegmanDistance( kegmanDistance );
  ui.setKegmanSpeed( kegmanSpeed );
  ui.setKegmanLag( kegmanLag );


  ui.setAutoScreenOff( _autoScreenOff );
  ui.setBrightness( _brightness );

  send("uICustom", msg);
}



void CustomPanel::closeEvent(QCloseEvent *event)
{
  timer->stop();
  delete timer;
  timer = nullptr;

  QWidget::closeEvent( event );
}

void CustomPanel::showEvent(QShowEvent *event)
{
  QWidget::setContentsMargins(0,0,0,0);
  QWidget::showEvent( event );

  int  nCarCnt = m_cars.size();
  if( nCarCnt > 0 ) return;

  sm->update(0);


  UIState   *s = uiState();
 // UIScene   &scene = s->scene;
  SubMaster &sm2 = *(s->sm);

  const auto car_state = sm2["carState"].getCarState();

  auto carState_custom = car_state.getCarSCustom();   // CarSCustom
  auto carSupport = carState_custom.getSupportedCars();
  int  nCnt = carSupport.size();

  // printf("SupportedCars = suport = %d  carcnt = %d \n", nCnt, nCarCnt );
  if( nCnt <= 0 )
  {
      QJsonArray surportCar = m_jsonobj["SurportCars"].toArray();
      for (const auto& item : surportCar) {
            m_cars.append(item.toString());
      }
  }
  else
  {
    for (int i = 0; i<nCnt; i++) {
      QString car = QString::fromStdString( carSupport[i] );
      m_cars.append( car );
    }
  }
}

void CustomPanel::hideEvent(QHideEvent *event)
{
  QWidget::hideEvent(event);

  updateToggles( false );

  writeJson();
}

int CustomPanel::send(const char *name, MessageBuilder &msg)
{
   return pm->send( name, msg );
}

void CustomPanel::writeJson()
{
   writeJsonToFile( m_jsonobj, "CustomParam" );
}



QJsonObject CustomPanel::readJsonFile(const QString& filePath )
{
    QJsonObject jsonObject;


    QString json_str = QString::fromStdString(params.get(filePath.toStdString()));

    if ( json_str.isEmpty() ) return jsonObject;

    QJsonDocument doc = QJsonDocument::fromJson(json_str.toUtf8());
    if (doc.isNull()) {
        printf( "Failed to parse the JSON document: %s  ", filePath.toStdString().c_str() );
        return jsonObject;  // Return an empty object in case of failure
    }
    jsonObject = doc.object();
    return jsonObject;
}

void CustomPanel::writeJsonToFile(const QJsonObject& jsonObject, const QString& fileName)
{
    QJsonDocument jsonDoc(jsonObject);
    QByteArray jsonData = jsonDoc.toJson();
    params.put( fileName.toStdString(), jsonData.toStdString() );
}

////////////////////////////////////////////////////////////////////////////////////////////
//
//

CommunityTab::CommunityTab(CustomPanel *parent, QJsonObject &jsonobj)
  : ListWidget(parent)
  , m_jsonobj(jsonobj)
  , m_pCustom(parent)
{
  // 1) 항목 정의 (오탈자 및 설명 정리, tr 적용)
  const std::vector<ValueDef> value_defs = {
    { "ParamCruiseMode",
      tr("Cruise mode"),
      tr("Bit flags: 0=Off, bit1=Gas control, bit2=Comma speed (CruiseGap)"),
      kIcon, 0, 15, 1, // min, max, unit
      1 },  //def

    { "ParamCruiseGap",
      tr("Cruise gap"),
      tr("0=Not used, 1~4=Gap for Comma speed"),
      kIcon, 0, 4, 1,
      4 }, //def

    { "ParamCurveSpeedLimit",
      tr("Curve speed adjust"),
      tr("Adjust maximum speed based on road curvature."),
      kIcon, 30, 100, 5,
      60 }, //def

    { "ParamAutoEngage",
      tr("Auto Cruise Engage Speed"),
      tr("Enables cruise automatically once the vehicle reaches the set speed."
         "30: Off · otherwise: engage at that speed (km/h)."),
      kIcon, 30, 100, 5,
      60 }, //def

    { "ParamAutoLaneChange",
      tr("Auto Lane Change Delay"),
      tr("After the turn signal is activated, waits the set time before starting an automatic lane change.\n"
         "0: Manual  ·value in seconds."),
      kIcon, 0, 100, 10,
      30 }, //def

    { "ParamSteerRatio",
      tr("Steering Ratio"),
      tr("Vehicle-specific ratio between steering wheel angle and road wheel angle (unitless).\n"
        "Used for curvature conversion and lateral control.\n"
        "Typical values: ~12–20. Incorrect values can cause poor lane keeping or oscillation.\n"
        "Change only if you know the calibrated value."),
      kIcon, -0.2, 0.2, 0.01,
      0 }, // def

    { "ParamStiffnessFactor",
      tr("Lateral Stiffness Factor"),
      tr("Scaling factor for lateral (tire/steering) stiffness used by the lateral controller (unitless).\n"
        "1.0 = nominal (recommended). Higher = more aggressive response; lower = smoother but lazier.\n"
        "Too high may cause oscillations; too low may cause understeer-like drift."),
      kIcon, -0.1, 0.1, 0.01,
      0 }, // def

    { "ParamAngleOffsetDeg",
      tr("Steering Angle Offset (deg)"),
      tr("Static correction for steering angle sensor zero, in degrees.\n"
        "Positive = sensor reads left-of-center as positive (adjust to make straight driving show ~0°).\n"
        "Change in small steps and verify on a straight, flat road."),
      kIcon, -2, 2, 0.1,
      0 }, // def


  };


  const std::vector<ValueDef> val2_defs = {
    { "ParamBrightness",
      tr("Screen Brightness"),
      tr("Adjust the brightness level. 0 = Auto, negative = darker, positive = brighter."),
      kIcon, -20, 5, 1,
      -15 }, //def

    { "ParamAutoScreenOff",
      tr("Screen Timeout"),
      tr("Set how long the screen stays on before turning off automatically (in 10-second steps). 0 = None."),
      kIcon, 0, 120, 1,
      100 }, //def

    { "ParamPowerOff",
      tr("Power off time"),
      tr("0=Not used, 1~ = power off delay (1 sec)"),
      kIcon, 0, 60, 1,
      10 }, //def

    { "DUAL_CAMERA_VIEW",
      tr("Dual camera view"),
      tr("0=Off, 1=On"),
      kIcon, 0, 1, 1,
      0 }, //def
  };




  // 섹션 만들기
  auto* cruiseSec = new CollapsibleSection(tr("Cruise Settings"), this);
  addItem(cruiseSec);
  // 2) ValueControl 생성 및 등록 (키는 QString으로 통일)
  for (const auto &d : value_defs) {
    auto *value = new CValueControl(d.param, d.title, d.desc, d.icon, d.min, d.max, d.unit, d.def, m_jsonobj);
    cruiseSec->addWidget(value);
    m_valueCtrl.insert(d.param, value);
  }

  auto* screenSec = new CollapsibleSection(tr("Screen & Power"), this);
  addItem(screenSec);
   for (const auto &d : val2_defs) {
    auto *value = new CValueControl(d.param, d.title, d.desc, d.icon, d.min, d.max, d.unit, d.def, m_jsonobj);
    screenSec->addWidget(value);
    m_valueCtrl.insert(d.param, value);
  }

  auto* logSec = new CollapsibleSection(tr("Logging"), this);
  addItem(logSec);
  // 3) 토글류 이외의 스위치 예시
  logSec->addWidget(new ParamControl("EnableLogging",
                           tr("Enable logging"),
                           tr("Record runtime logs"),
                           kIcon,
                           this));

  // 4) CruiseMode ↔ CruiseGap 의존성 동기화
  auto syncCruiseGapEnabled = [this]() {
    const int cruiseMode = m_jsonobj.value("ParamCruiseMode").toInt(0);
    if (auto *gap = m_valueCtrl.value("ParamCruiseGap", nullptr)) {
      gap->setEnabled(cruiseMode != 0);
    }
  };

  // CValueControl에 value 변경 신호가 있으면 그걸 쓰는 게 가장 좋음.
  // 여기서는 예제로 clicked에 연결(기존 시그널 유지 가정).
  if (auto *mode = m_valueCtrl.value("ParamCruiseMode", nullptr)) {
    QObject::connect(mode, &CValueControl::valueChanged, this, [=](int v) {
      Q_UNUSED(v);
      // 최신값 반영(컨트롤 내부가 즉시 m_jsonobj를 업데이트한다고 가정)
      syncCruiseGapEnabled();
      update();
    });
  }
  // 최초 진입 시 상태 동기화
  syncCruiseGapEnabled();

  // 5) 차종 선택 버튼
  const QString selected_car = QString::fromStdString(Params().get("SelectedCar"));
  auto *changeCar = new ButtonControl(
      selected_car.isEmpty() ? tr("Select your car") : selected_car,
      selected_car.isEmpty() ? tr("SELECT") : tr("CHANGE"),
      ""
  );

  QObject::connect(changeCar, &ButtonControl::clicked, this, [=] {
    const QStringList items = m_pCustom ? m_pCustom->m_cars : QStringList();

    // 지원 차종을 JSON에 반영(보기/동기화 용도)
    QJsonArray jsonArray;
    for (const auto &item : items) jsonArray.append(item);
    m_jsonobj["SupportCars"] = jsonArray; // SurportCars → SupportCars 로 수정

    const QString current = QString::fromStdString(Params().get("SelectedCar"));
    const QString selection = MultiOptionDialog::getSelection(tr("Select a car"), items, current, this);
    if (!selection.isEmpty()) {
      Params().put("SelectedCar", selection.toStdString());
      // 버튼 라벨도 즉시 갱신
      changeCar->setTitle(selection);
      changeCar->setValue(tr("CHANGE"));
    }
  });
  addItem(changeCar);

  setStyleSheet(R"(
    * {
      color: white;
      outline: none;
      font-family: Inter;
    }
    Updater {
      color: white;
      background-color: black;
    }
  )");
}

void CommunityTab::showEvent(QShowEvent *event)
{
    QWidget::showEvent(event);
}


void CommunityTab::hideEvent(QHideEvent *event)
{
  QWidget::hideEvent(event);
}


////////////////////////////////////////////////////////////////////////////////////////////////////////
//
//

GitTab::GitTab(CustomPanel *parent, QJsonObject &jsonobj) : ListWidget(parent) , m_jsonobj(jsonobj)
{
  m_pCustom = parent;


  // 1. ***** Local에서 git branch -r 로 보이는 remote branch 는 실제 remote 저장소의 branch 가 아니다.
  //    실제로는 remote 저장소의 branch를 바라보는 참조내역이라 보면 될 듯하다.
  //    원격 저장소의 branch가 삭제되어도 Local에서 git branch -r 로 나오는 list는 변화가 없다
  auto gitpruneBtn = new ButtonControl(tr("Fetch All and Prune"), tr("Sync"), "git fetch --all --prune\n git remote prune origin");
  connect(gitpruneBtn, &ButtonControl::clicked, [=]() {

    QProcess::execute("git fetch --all --prune");   // 원격 브랜치 정리.
    QProcess::execute("git remote prune origin");
  });
  addItem(gitpruneBtn);

  // 2.
  auto gitremoteBtn = new ButtonControl(tr("Update from Remote"), tr("Update"), "git fetch origin\n git reset --hard origin/master-ci");
  connect(gitremoteBtn, &ButtonControl::clicked, [=]() {
    auto current = Params().get("GitBranch");
   // QString gitCommand = QString("git reset --hard origin/%1").arg(current.c_str() );
    QString gitCommand = "git reset --hard origin/"+QString::fromStdString( Params().get("GitBranch") );

    QProcess::execute("git fetch origin"); // 원격 저장소에서 최신 업데이트를 가져옴
    QProcess::execute( gitCommand );  // 지정된 브랜치로 하드 리셋

    QString gitVerify = QString("git rev-parse --verify %1").arg(current.c_str() );;

    int exitCode = QProcess::execute( gitVerify );  // 실행 결과 확인
    if (exitCode == 0) {
        printf("Git command(%s) executed successfully. \n", qPrintable(gitCommand) );
    } else {
        printf("Git command(%s) failed with exit code: %d \n", qPrintable(gitCommand) , exitCode );
    }

  });
  addItem(gitremoteBtn);

  // 3. 특정 commit 으로 되돌리는 방법
  auto gitpruneBtn1 = new ButtonControl(tr("Revert Commit"), tr("Rollback"), "git reset --hard xxxxxxx(commitno)");
  connect(gitpruneBtn1, &ButtonControl::clicked, [=]() {
    QProcess::execute("git reset --hard ec448a9");
  });
  addItem(gitpruneBtn1);


  setStyleSheet(R"(
    * {
      color: white;
      outline: none;
      font-family: Inter;
    }
    Updater {
      color: white;
      background-color: black;
    }
  )");
}

void GitTab::showEvent(QShowEvent *event)
{
    QWidget::showEvent(event);
}


void GitTab::hideEvent(QHideEvent *event)
{
  QWidget::hideEvent(event);
}


////////////////////////////////////////////////////////////////////////////////////////////////////////
//
//


ModelTab::ModelTab(CustomPanel *parent, QJsonObject &jsonobj)
    : ListWidget(parent), m_jsonobj(jsonobj) {
  m_pCustom = parent;

  // 현재 선택된 모델명 읽기
  QString selected_model = QString::fromStdString(Params().get("ActiveModelName"));
  currentModel = selected_model;

  // 버튼 생성
  changeModelButton = new ButtonControl(
      selected_model.length() ? selected_model : tr("Select your model"),
      selected_model.length() ? tr("CHANGE") : tr("SELECT"),
      "");

      /// connect start
        QObject::connect(changeModelButton, &ButtonControl::clicked, this, [this]() {
          // 1) 모델 후보 (최소 수정: 기존 고정 목록 유지)
          QStringList items = {
            "3.Firehose",
            "2.Steam_Powered",
            "1.default" };

          // 현재 선택 상태 반영
          QString selection = MultiOptionDialog::getSelection(tr("Select a model"), items, currentModel, this);
          if (selection.isEmpty() || selection == currentModel) return;

          // 2) 선택 즉시 Params 반영 (스크립트가 Params를 참조한다고 가정)
          Params params;
          const std::string prev = params.get("ActiveModelName");
          params.put("ActiveModelName", selection.toStdString());

          // 3) 기본 모델이면 스크립트 실행 불필요
          if (selection == "1.default") {
            currentModel = selection;
            changeModelButton->setTitle(selection);
            changeModelButton->setText(tr("CHANGE"));
            changeModelButton->setDescription(QString());
            qWarning() << "Comma default PATH";
            return;
          }

          // 4) 경로 계산 (이중 슬래시 방지)
          QDir root(QDir::homePath());
          root.cd("openpilot");                            // ~/openpilot
          const QString rootPath = root.absolutePath();
          const QString modeldPath = root.filePath("selfdrive/modeld");
          const QString scriptPath = root.filePath("selfdrive/ui/qt/custom/script/model_make.sh");

          // 5) 스크립트 검증
          QFileInfo fi(scriptPath);
          if (!fi.exists() || !fi.isFile() || !(fi.permissions() & QFile::ExeUser)) {
            changeModelButton->setTitle(tr("Script missing"));
            changeModelButton->setText(tr("RETRY"));
            changeModelButton->setDescription(scriptPath);
            // 롤백
            params.put("ActiveModelName", prev);
            return;
          }

          // 6) UI 잠금 + 진행 표시
          changeModelButton->setEnabled(false);
          changeModelButton->setTitle(tr("Compiling..."));
          changeModelButton->setText(tr("WAIT"));
          changeModelButton->setDescription(selection);

          const QString prevCwd = QDir::currentPath();

          // 7) QProcess로 비동기 실행
          QProcess *proc = new QProcess(this);
          proc->setProgram(scriptPath);
          proc->setWorkingDirectory(modeldPath);

          // 환경 변수 설정 (필요 시 WORKDIR 전달)
          QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
          env.insert("WORKDIR", modeldPath);
          proc->setProcessEnvironment(env);

          // 로그 파이프 연결(원하면 별도 텍스트 위젯로 표시 가능)
          connect(proc, &QProcess::readyReadStandardOutput, this, [this, proc]() {
            const auto out = QString::fromUtf8(proc->readAllStandardOutput());
            qWarning() << "[custom.cc][out]" << out.trimmed();
            changeModelButton->setDescription(out.right(80)); // 최근 로그 한 줄 정도
          });
          connect(proc, &QProcess::readyReadStandardError, this, [this, proc]() {
            const auto err = QString::fromUtf8(proc->readAllStandardError());
            qWarning() << "[custom.cc][ret]" << err.trimmed();
            changeModelButton->setDescription(err.right(80));
          });

          // 8) 종료 처리
          connect(proc, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
                  this, [=](int code, QProcess::ExitStatus status) {
            qWarning() << "model_make.sh exit code =" << code << "status=" << status;

            if (status == QProcess::NormalExit && code == 0) {
              // 성공
              currentModel = selection;
              changeModelButton->setTitle(selection);
              changeModelButton->setText(tr("CHANGE"));
              //changeModelButton->setDescription(QString());
            } else {
              // 실패 → 롤백
              Params().put("ActiveModelName", prev);
              changeModelButton->setTitle(tr("Failed"));
              changeModelButton->setText(tr("RETRY"));
              //changeModelButton->setDescription(tr("Check logs"));
            }

            if (!QDir::setCurrent(prevCwd)) {
              qWarning() << "Failed to restore dir to" << prevCwd;
            }
            changeModelButton->setEnabled(true);
            proc->deleteLater();
          });

          // 9) 시작 (인자 필요 없으면 그대로, 필요하면 selection 등 전달)
          // 예: proc->setArguments({ selection });
          proc->start();
        });
  /// connect end.



  addItem(changeModelButton);
  setStyleSheet(R"(
    * {
      color: white;
      outline: none;
      font-family: Inter;
    }
    Updater {
      color: white;
      background-color: black;
    }
  )");
}

void ModelTab::showEvent(QShowEvent *event)
{
    QWidget::showEvent(event);
}


void ModelTab::hideEvent(QHideEvent *event)
{
  QWidget::hideEvent(event);
}

////////////////////////////////////////////////////////////////////////////////////////////
//
//



NavigationTab::NavigationTab(CustomPanel *parent, QJsonObject &jsonobj) : ListWidget(parent), m_jsonobj(jsonobj)
{
  m_pCustom = parent;

  // param, title, desc, icon
  std::vector<std::tuple<QString, QString, QString, QString>> toggle_defs{
    {
      "UseExternalNaviRoutes",
      tr("Use external navi routes"),
      "",
      "../assets/offroad/icon_openpilot.png",
    },
    /*
    {
      "ExternalNaviType",
      tr("Use external navi type"),
      "0.mappy  1.NDA",
      "../assets/offroad/icon_openpilot.png",
    },
    */
  };


  for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new ParamControl(param, title, desc, icon, this);

    bool locked = params.getBool((param + "Lock").toStdString());
    toggle->setEnabled(!locked);

    addItem(toggle);
    toggles[param.toStdString()] = toggle;
  }


  auto toggle1 = new CValueControl2(
    "ExternalNaviType",
    tr(" - Use external navi type"),
    "0.comma  1.mappy  2.NDA",
    "",
    //"../assets/offroad/icon_openpilot.png",
    0,5 );

  addItem(toggle1);


   addItem( new MapboxToken() );
}


////////////////////////////////////////////////////////////////////////////////////////////
//
//

UITab::UITab(CustomPanel *parent, QJsonObject &jsonobj) : ListWidget(parent), m_jsonobj(jsonobj)
{
  m_pCustom = parent;

  // param, title, desc, icon
  std::vector<std::tuple<QString, QString, QString, QString>> toggle_defs{
    {
      "ShowDebugMessage",
      "Show Debug Message",
      "Display debug popups/log overlays for troubleshooting.",
      "../assets/offroad/icon_shell.png",
    },
    {
      "DisableUpdates",
      "Disable OTA Updates",
      "Prevents downloading and installing software updates.",
      "../assets/offroad/icon_shell.png",
    },
    {
      "ShowCarTracking",
      "how Vehicle Tracking",
      "Display detected vehicles and paths on the HUD.",
      "../assets/offroad/icon_shell.png",
    },
    {
      "tpms",
      "Show tpms",
      "Show tire pressure monitoring values on the HUD.",
      "../assets/offroad/icon_shell.png",
    },
    {
      "ParamDebug",
      "Show debug trace message",
      "Enable verbose internal trace messages for diagnostics.",
      "../assets/offroad/icon_shell.png",
    },
    // ───────── Kegman (HUD Overlay) ─────────
    {
      "kegman",
      "HUD Overlay (Kegman)",
      "Select up to 4 items below to show on the HUD.",
      "../assets/offroad/icon_shell.png",
    },
    {
      "kegmanCPU",
      "CPU temperature",
      "1. Shows CPU temperature (°C). Counts toward the 4-item HUD limit.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanLag",
      "UI Lag",
      "2. Shows UI frame latency (ms). Counts toward the 4-item HUD limit",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanBattery",
      "Battery Voltage",
      "3. Shows system/battery voltage (V). Counts toward the 4-item HUD limit.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanGPU",
      "GPS Accuracy",
      "4. Shows GPS horizontal accuracy (m). Counts toward the 4-item HUD limit.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanAngle",
      "Steering Angle",
      "5. Shows steering angle (°). Counts toward the 4-item HUD limit.",
      "",
     // "../assets/offroad/icon_shell.png",
    },
    {
      "kegmanEngine",
      "Engine Status",
      "6. Shows engine state (e.g., RPM/ON-OFF). Counts toward the 4-item HUD limit.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanDistance",
      "Relative Distance",
      "7. Shows radar relative distance (m). Counts toward the 4-item HUD limit.",
      "",
     // "../assets/offroad/icon_shell.png",
    },
    {
      "kegmanSpeed",
      "Relative Speed",
      "8. Shows radar relative speed (m/s). Counts toward the 4-item HUD limit.",
      "",
      //"../assets/offroad/icon_shell.png",
    },


  };

  for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new JsonControl(param, title, desc, icon, this, m_jsonobj);

    addItem(toggle);
    toggles[param.toStdString()] = toggle;
  }


  connect(toggles["ShowDebugMessage"], &ToggleControl::toggleFlipped, [=]() {
    updateToggles( false );
  });
}



void UITab::closeEvent(QCloseEvent *event)
{
    QWidget::closeEvent(event);
}

void UITab::showEvent(QShowEvent *event)
{
    QWidget::showEvent(event);
}



void UITab::hideEvent(QHideEvent *event)
{
  QWidget::hideEvent(event);

  updateToggles( true );
}


void UITab::updateToggles( int bSave )
{
  if( bSave )
  {
    m_pCustom->writeJson();
  }

  int bDebug = m_jsonobj["ShowDebugMessage"].toBool();
  auto tpms_mode_toggle = toggles["tpms"];
  auto debug_mode_toggle = toggles["ParamDebug"];
  auto kegman_mode_toggle = toggles["kegman"];
  auto kegman_cpu = toggles["kegmanCPU"];
  auto kegman_battery = toggles["kegmanBattery"];
  auto kegman_gpu = toggles["kegmanGPU"];
  auto kegman_angle = toggles["kegmanAngle"];
  auto kegman_engine = toggles["kegmanEngine"];
  auto kegman_distance = toggles["kegmanDistance"];
  auto kegman_speed = toggles["kegmanSpeed"];


  tpms_mode_toggle->setEnabled(bDebug);
  debug_mode_toggle->setEnabled(bDebug);
  kegman_mode_toggle->setEnabled(bDebug);

  int kegman = bDebug;
  if( bDebug )
    kegman = m_jsonobj["kegman"].toBool();

  kegman_cpu->setEnabled(kegman);
  kegman_battery->setEnabled(kegman);
  kegman_gpu->setEnabled(kegman);
  kegman_angle->setEnabled(kegman);
  kegman_engine->setEnabled(kegman);
  kegman_distance->setEnabled(kegman);
  kegman_speed->setEnabled(kegman);
}



////////////////////////////////////////////////////////////////////////////////////////////
//
//

Debug::Debug(CustomPanel *parent, QJsonObject &jsonobj) : ListWidget(parent), m_jsonobj(jsonobj)
{
  m_pCustom = parent;


  // param, title, desc, icon
  std::vector<std::tuple<QString, QString, QString, QString>> toggle_defs{
    {
      "debug1",
      tr("debug1"),
      "",
      "../assets/offroad/icon_shell.png",
    },
    {
      "debug2",
      tr("debug2"),
      "",
      "../assets/offroad/icon_shell.png",
    },
    {
      "debug3",
      tr("debug3"),
      "",
      "../assets/offroad/icon_shell.png",
    },
    {
      "debug4",
      tr("debug4"),
      "",
      "../assets/offroad/icon_shell.png",
    },
    {
      "debug5",
      tr("debug5"),
      "",
      "../assets/offroad/icon_shell.png",
    },
  };

  for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new JsonControl(param, title, desc, icon, this, m_jsonobj);

    addItem(toggle);
    toggles[param.toStdString()] = toggle;
  }

}



void Debug::closeEvent(QCloseEvent *event)
{
    QWidget::closeEvent(event);
}

void Debug::showEvent(QShowEvent *event)
{
    QWidget::showEvent(event);
}

void Debug::hideEvent(QHideEvent *event)
{
  QWidget::hideEvent(event);

  updateToggles( true );
}


void Debug::updateToggles( int bSave )
{
  if( bSave )
  {
    m_pCustom->writeJson();
  }

}
