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
#include <QToolButton>
#include <QPropertyAnimation>
#include <QFrame>

#include "common/params.h"
#include "common/util.h"

#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/custom/custom.h"

// ======================================================================================
// 공통 유틸/상수
// ======================================================================================
namespace {
constexpr double kEPS = 1e-9;

// 버튼 공통 스타일(중복 제거)
static const char *kRoundBtnStyle = R"(
  padding: 0;
  border-radius: 50px;
  font-size: 35px;
  font-weight: 500;
  color: #E4E4E4;
  background-color: #393939;
)";

// 탭 스타일(여러 탭에서 공유)
static const char *kTabStyle = R"(
  QTabBar::tab {
    border: 1px solid #C4C4C3;
    border-bottom-color: #C2C7CB;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    min-width: 45ex;
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
)";

inline void applyListWidgetBaseStyle(QWidget *w) {
  w->setStyleSheet(R"(
    * { color: white; outline: none; font-family: Inter; }
    Updater { color: white; background-color: black; }
  )");
}

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

inline int decimalsFor(double step) {
  if (!(step > 0.0) || !std::isfinite(step)) return 0;
  double scale = 1.0;
  for (int d = 0; d <= 5; ++d) {
    const double scaled = step * scale;
    if (nearInteger(scaled)) return d;
    scale *= 10.0;
  }
  return 8;  // 안전한 fallback
}

} // namespace

// ======================================================================================
// CollapsibleSection
// ======================================================================================
CollapsibleSection::CollapsibleSection(const QString& title, QWidget* parent)
  : QWidget(parent) {
  auto *root = new QVBoxLayout(this);
  root->setContentsMargins(0, 0, 0, 0);
  root->setSpacing(6);

  m_headerBtn = new QToolButton(this);
  m_headerBtn->setText(title);
  m_headerBtn->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
  m_headerBtn->setArrowType(Qt::DownArrow);
  m_headerBtn->setCheckable(true);
  m_headerBtn->setChecked(true);
  m_headerBtn->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
  m_headerBtn->setStyleSheet(
    "QToolButton{ "
    "  background-color:#3a3a3a;"   /* 중간 회색 */
    "font-weight:600; font-size:36px; }"
  );
  root->addWidget(m_headerBtn);

  m_body = new QFrame(this);
  m_body->setFrameShape(QFrame::NoFrame);
  m_bodyLayout = new QVBoxLayout(m_body);
  m_bodyLayout->setContentsMargins(12, 6, 0, 6);
  m_bodyLayout->setSpacing(6);
  root->addWidget(m_body);

  // 애니메이션으로 접기/펼치기 (finished 연결은 1회만)
  m_anim = new QPropertyAnimation(m_body, "maximumHeight", this);
  m_anim->setDuration(150);
  connect(m_anim, &QPropertyAnimation::finished, this, [this]{
    if (!m_expanded) m_body->setVisible(false);
  });

  connect(m_headerBtn, &QToolButton::clicked, this, &CollapsibleSection::toggle);
}

void CollapsibleSection::addWidget(QWidget* w) { m_bodyLayout->addWidget(w); }

void CollapsibleSection::setExpanded(bool on) {
  if (m_expanded == on) return;
  toggle();
}

void CollapsibleSection::toggle() {
  m_expanded = !m_expanded;
  m_headerBtn->setArrowType(m_expanded ? Qt::DownArrow : Qt::RightArrow);

  // 애니메이션 시작 전 보이도록
  m_body->setVisible(true);
  const int start = std::max(0, m_body->maximumHeight());
  int end = 0;

  if (m_expanded) {
    // 펼칠 때 목표 높이 계산: sizeHint 사용
    m_body->setMaximumHeight(QWIDGETSIZE_MAX);
    end = m_body->sizeHint().height();
    m_body->setMaximumHeight(start);
  }

  m_anim->stop();
  m_anim->setStartValue(start);
  m_anim->setEndValue(m_expanded ? end : 0);
  m_anim->start();
}

void CollapsibleSection::setHeaderFont(const QFont& f) { if (m_headerBtn) m_headerBtn->setFont(f); }

void CollapsibleSection::setBodyFont(const QFont& f) {
  if (!m_body) return;
  m_body->setFont(f);
  for (QWidget *w : m_body->findChildren<QWidget*>()) w->setFont(f);
}

void CollapsibleSection::setSectionFont(const QFont& header, const QFont& body) {
  setHeaderFont(header);
  setBodyFont(body);
}

// ======================================================================================
// CValueControl (JSON 기반 숫자 컨트롤)
// ======================================================================================
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

  m_decimal = decimalsFor(m_unit);

  m_label.setAlignment(Qt::AlignVCenter | Qt::AlignRight);
  m_label.setStyleSheet("color: #e0e879");
  hlayout->addWidget(&m_label);

  m_btnMinus.setStyleSheet(kRoundBtnStyle);
  m_btnMinus.setFixedSize(150, 100);
  m_btnMinus.setText(QStringLiteral("－"));
  m_btnMinus.setAutoRepeat(true);
  m_btnMinus.setAutoRepeatDelay(300);
  m_btnMinus.setAutoRepeatInterval(60);
  hlayout->addWidget(&m_btnMinus);

  m_btnPlus.setStyleSheet(kRoundBtnStyle);
  m_btnPlus.setFixedSize(150, 100);
  m_btnPlus.setText(QStringLiteral("＋"));
  m_btnPlus.setAutoRepeat(true);
  m_btnPlus.setAutoRepeatDelay(300);
  m_btnPlus.setAutoRepeatInterval(60);
  hlayout->addWidget(&m_btnPlus);

  bool wroteBack = false;
  const double loaded = loadInitial(wroteBack);
  m_value = std::clamp(loaded, m_min, m_max);
  if (wroteBack || std::abs(loaded - m_value) > kEPS) {
    m_jsonobj[m_key] = m_value; // JSON에 double 기록
  }

  connect(&m_btnMinus, &QPushButton::pressed, this, [this]{ adjust(-m_unit); });
  connect(&m_btnPlus,  &QPushButton::pressed, this, [this]{ adjust(+m_unit); });

  updateLabel();
  updateToolTip();
}

double CValueControl::getValue() const noexcept { return m_value; }

int CValueControl::decimalsFor(double step) { return ::decimalsFor(step); }

void CValueControl::setValue(double value) {
  // 스텝 스냅(격자 정렬)
  if (m_unit > kEPS) {
    const double base = m_min;
    const double steps = std::round((value - base) / m_unit);
    value = base + steps * m_unit;
  }

  const double nv = std::clamp(value, m_min, m_max);
  if (std::abs(m_value - nv) <= kEPS) return;

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
  // 현재 값을 새 스텝에 맞춰 재정렬
  setValue(m_value);
  updateToolTip();
}

void CValueControl::setDefault(double defVal) { m_def = std::clamp(defVal, m_min, m_max); }

void CValueControl::adjust(double delta) { setValue(m_value + delta); }

void CValueControl::updateLabel() { m_label.setText(QString::number(m_value, 'f', m_decimal)); }

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

  if (v.isDouble()) return v.toDouble();

  if (v.isString()) {
    bool ok = false;
    const double d = v.toString().toDouble(&ok);
    if (ok) return d;
    wroteBack = true;
    return m_def;
  }
  if (v.isBool()) return v.toBool() ? 1.0 : 0.0;

  wroteBack = true;
  return m_def;
}

// ======================================================================================
// CValueControl2 (Params 기반 정수 컨트롤)
// ======================================================================================
CValueControl2::CValueControl2(const QString& key, const QString& title, const QString& desc,
                               const QString& icon, int min, int max, int unit)
    : AbstractControl(title, desc, icon), m_key(key), m_min(min), m_max(max), m_unit(unit) {

  label.setAlignment(Qt::AlignVCenter | Qt::AlignRight);
  label.setStyleSheet("color: #e0e879");
  hlayout->addWidget(&label);

  btnminus.setStyleSheet(kRoundBtnStyle);
  btnplus.setStyleSheet(kRoundBtnStyle);
  btnminus.setFixedSize(150, 100);
  btnplus.setFixedSize(150, 100);
  hlayout->addWidget(&btnminus);
  hlayout->addWidget(&btnplus);

  QObject::connect(&btnminus, &QPushButton::released, [=]() {
    int value = QString::fromStdString(params.get(m_key.toStdString())).toInt();
    value = std::max(m_min, value - m_unit);
    params.put(m_key.toStdString(), QString::number(value).toStdString());
    refresh();
  });

  QObject::connect(&btnplus, &QPushButton::released, [=]() {
    int value = QString::fromStdString(params.get(m_key.toStdString())).toInt();
    value = std::min(m_max, value + m_unit);
    params.put(m_key.toStdString(), QString::number(value).toStdString());
    refresh();
  });

  refresh();
}

void CValueControl2::refresh() {
  label.setText(QString::fromStdString(params.get(m_key.toStdString())));
  btnminus.setText("－");
  btnplus.setText("＋");
}

// ======================================================================================
// CustomPanel
// ======================================================================================
CustomPanel::CustomPanel(SettingsWindow *parent) : QWidget(parent) {
  pm.reset(new PubMaster({"uICustom"}));
  sm.reset(new SubMaster({"carState"}));
  m_jsonobj = readJsonFile("CustomParam");

  QList<QPair<QString, QWidget *>> panels = {
    {tr("UI"), new UITab(this, m_jsonobj)},
    {tr("Community"), new CommunityTab(this, m_jsonobj)},
    {tr("Git"), new GitTab(this, m_jsonobj)},
    {tr("Model"), new ModelTab(this, m_jsonobj)},
    {tr("Debug"), new Debug(this, m_jsonobj)},
    {tr("Navigation"), new NavigationTab(this, m_jsonobj)},
  };

  // 탭 위젯
  auto *tabWidget = new QTabWidget(this);
  tabWidget->setStyleSheet(kTabStyle);
  for (auto &[name, panel] : panels) {
    panel->setContentsMargins(50, 25, 50, 25);
    ScrollView *panel_frame = new ScrollView(panel, this);
    tabWidget->addTab(panel_frame, name);
  }

  // 탭 위젯을 전체 화면으로 표시
  auto *mainLayout = new QVBoxLayout(this);
  mainLayout->addWidget(tabWidget);
  setLayout(mainLayout);

  QObject::connect(uiState(), &UIState::offroadTransition, this, &CustomPanel::offroadTransition);

  timer = new QTimer(this);
  connect(timer, &QTimer::timeout, this, &CustomPanel::OnTimer);
  timer->start(1000);
}

void CustomPanel::offroadTransition(bool offroad) {
  sm->update(0);
  if (!timer->isActive()) m_cmdIdx = 0;
  updateToggles(false);
}

void CustomPanel::OnTimer() {
  UIState *s = uiState();
  UIScene &scene = s->scene;
  SubMaster &sm2 = *(s->sm);

  sm->update(0);
  if (scene.started) {
    m_time = 0;
    updateToggles(false);
    const auto car_state = sm2["carState"].getCarState();
    float vEgo = car_state.getVEgo();
    if (vEgo > 10) scene.custom.m_powerflag = 1;
  } else {
    m_time++;
    const int powerOff = m_jsonobj.value("ParamPowerOff").toInt();
    if (powerOff && (m_time > powerOff) && (scene.custom.m_powerflag)) {
      scene.custom.m_powerflag = 0;
      params.putBool("DoShutdown", true);
    }
  }
}

void CustomPanel::updateToggles(int /*bSave*/) {
  MessageBuilder msg;
  m_cmdIdx++;

  auto custom = msg.initEvent().initUICustom();
  auto debug = custom.initDebug();

  const bool idx1 = m_jsonobj.value("debug1").toBool();
  const bool idx2 = m_jsonobj.value("debug2").toBool();
  const bool idx3 = m_jsonobj.value("debug3").toBool();
  const bool idx4 = m_jsonobj.value("debug4").toBool();
  const bool idx5 = m_jsonobj.value("debug5").toBool();

  debug.setCmdIdx(m_cmdIdx);
  debug.setIdx1(idx1);
  debug.setIdx2(idx2);
  debug.setIdx3(idx3);
  debug.setIdx4(idx4);
  debug.setIdx5(idx5);

  auto comunity = custom.initCommunity();
  const int cruiseMode = m_jsonobj.value("ParamCruiseMode").toInt();
  const int cruiseGap = m_jsonobj.value("ParamCruiseGap").toInt();
  const int curveSpeedLimit = m_jsonobj.value("ParamCurveSpeedLimit").toInt();
  const float steerRatio = static_cast<float>(m_jsonobj.value("ParamSteerRatio").toDouble());
  const float stiffnessFactor = static_cast<float>(m_jsonobj.value("ParamStiffnessFactor").toDouble());
  const float angleOffsetDeg = static_cast<float>(m_jsonobj.value("ParamAngleOffsetDeg").toDouble());

  comunity.setCmdIdx(m_cmdIdx);
  comunity.setCruiseMode(cruiseMode);
  comunity.setCruiseGap(cruiseGap);
  comunity.setCurveSpeedLimit(curveSpeedLimit);
  comunity.setSteerRatio(steerRatio);
  comunity.setStiffnessFactor(stiffnessFactor);
  comunity.setAngleOffsetDeg(angleOffsetDeg);

  auto ui = custom.initUserInterface();
  const bool bDebug = m_jsonobj.value("ShowDebugMessage").toBool();
  const bool bCarTracking = m_jsonobj.value("ShowCarTracking").toBool();

  const bool tpms = m_jsonobj.value("tpms").toBool();
  const bool ndebug = m_jsonobj.value("ParamDebug").toBool();

  const bool kegman = m_jsonobj.value("kegman").toBool() && bDebug;
  const bool kegmanCPU = m_jsonobj.value("kegmanCPU").toBool();
  const bool kegmanBattery = m_jsonobj.value("kegmanBattery").toBool();
  const bool kegmanGPU = m_jsonobj.value("kegmanGPU").toBool();
  const bool kegmanAngle = m_jsonobj.value("kegmanAngle").toBool();
  const bool kegmanEngine = m_jsonobj.value("kegmanEngine").toBool();
  const bool kegmanDistance = m_jsonobj.value("kegmanDistance").toBool();
  const bool kegmanSpeed = m_jsonobj.value("kegmanSpeed").toBool();

  const int autoScreenOff = m_jsonobj.value("ParamAutoScreenOff").toInt();
  const int brightness = m_jsonobj.value("ParamBrightness").toInt();

  ui.setCmdIdx(m_cmdIdx);
  ui.setShowDebugMessage(bDebug);
  ui.setShowCarTracking(bCarTracking);
  ui.setTpms(tpms);
  ui.setDebug(ndebug);

  ui.setKegman(kegman);
  ui.setKegmanCPU(kegmanCPU);
  ui.setKegmanBattery(kegmanBattery);
  ui.setKegmanGPU(kegmanGPU);
  ui.setKegmanAngle(kegmanAngle);
  ui.setKegmanEngine(kegmanEngine);
  ui.setKegmanDistance(kegmanDistance);
  ui.setKegmanSpeed(kegmanSpeed);

  ui.setAutoScreenOff(autoScreenOff);
  ui.setBrightness(brightness);

  send("uICustom", msg);
}

void CustomPanel::closeEvent(QCloseEvent *event) {
  if (timer) {
    timer->stop();
    // timer는 부모(this)에 소유되므로 delete 생략 가능
  }
  QWidget::closeEvent(event);
}

void CustomPanel::showEvent(QShowEvent *event) {
  QWidget::setContentsMargins(0, 0, 0, 0);
  QWidget::showEvent(event);

  if (!m_cars.isEmpty()) return;

  sm->update(0);
  UIState *s = uiState();
  SubMaster &sm2 = *(s->sm);

  const auto car_state = sm2["carState"].getCarState();
  const auto carState_custom = car_state.getCarSCustom();
  const auto carSupport = carState_custom.getSupportedCars();

  if (carSupport.size() <= 0) {
    // JSON에서 후보 로드(SurportCars → SupportCars 정정)
    const QJsonArray supportCar = m_jsonobj.value("SupportCars").toArray();
    for (const auto &item : supportCar) m_cars.append(item.toString());
  } else {
    for (int i = 0; i < (int)carSupport.size(); ++i) {
      m_cars.append(QString::fromStdString(carSupport[i]));
    }
  }
}

void CustomPanel::hideEvent(QHideEvent *event) {
  QWidget::hideEvent(event);
  updateToggles(false);
  writeJson();
}

int CustomPanel::send(const char *name, MessageBuilder &msg) { return pm->send(name, msg); }

void CustomPanel::writeJson() { writeJsonToFile(m_jsonobj, "CustomParam"); }

QJsonObject CustomPanel::readJsonFile(const QString& filePath) {
  QJsonObject jsonObject;
  const QString json_str = QString::fromStdString(params.get(filePath.toStdString()));
  if (json_str.isEmpty()) return jsonObject;

  const QJsonDocument doc = QJsonDocument::fromJson(json_str.toUtf8());
  if (doc.isNull()) {
    qWarning() << "Failed to parse JSON:" << filePath;
    return jsonObject;
  }
  return doc.object();
}

void CustomPanel::writeJsonToFile(const QJsonObject& jsonObject, const QString& fileName) {
  const QJsonDocument jsonDoc(jsonObject);
  const QByteArray jsonData = jsonDoc.toJson();
  params.put(fileName.toStdString(), jsonData.toStdString());
}

// ======================================================================================
// CommunityTab
// ======================================================================================
CommunityTab::CommunityTab(CustomPanel *parent, QJsonObject &jsonobj)
  : ListWidget(parent), m_jsonobj(jsonobj), m_pCustom(parent) {
  // 1) 항목 정의
  const std::vector<ValueDef> value_defs = {
    { "ParamCruiseMode", tr("Cruise mode"),
      tr("Bit flags: 0=Off, bit1=Gas control, bit2=Comma speed (CruiseGap)"),
      kIcon, 0, 15, 1, 2 },

    { "ParamCruiseGap", tr("Cruise gap"),
      tr("0=Not used, 1~4=Gap for Comma speed"),
      kIcon, 0, 4, 1, 4 },

    { "ParamCurveSpeedLimit", tr("Curve speed adjust"),
      tr("Adjust maximum speed based on road curvature."),
      kIcon, 30, 100, 5, 70 },

    { "ParamAutoEngage", tr("Auto Cruise Engage Speed"),
      tr("Enables cruise automatically once the vehicle reaches the set speed.\n30: Off · otherwise: engage at that speed (km/h)."),
      kIcon, 30, 100, 5, 60 },

    { "ParamAutoLaneChange", tr("Auto Lane Change Delay"),
      tr("After the turn signal is activated, waits the set time before starting an automatic lane change.\n0: Manual  · value in seconds."),
      kIcon, 0, 100, 10, 30 },

    { "ParamSteerRatio", tr("Steering Ratio"),
      tr("Vehicle-specific ratio between steering wheel angle and road wheel angle (unitless).\nUsed for curvature conversion and lateral control.\nTypical values: ~12–20. Incorrect values can cause poor lane keeping or oscillation.\nChange only if you know the calibrated value."),
      kIcon, -0.2, 0.2, 0.01, 0 },

    { "ParamStiffnessFactor", tr("Lateral Stiffness Factor"),
      tr("Scaling factor for lateral (tire/steering) stiffness used by the lateral controller (unitless).\n1.0 = nominal (recommended). Higher = more aggressive response; lower = smoother but lazier.\nToo high may cause oscillations; too low may cause understeer-like drift."),
      kIcon, -0.1, 0.1, 0.01, 0 },

    { "ParamAngleOffsetDeg", tr("Steering Angle Offset (deg)"),
      tr("Static correction for steering angle sensor zero, in degrees.\nPositive = sensor reads left-of-center as positive (adjust to make straight driving show ~0°).\nChange in small steps and verify on a straight, flat road."),
      kIcon, -2, 2, 0.1, 0 },
  };

  const std::vector<ValueDef> val2_defs = {
    { "ParamBrightness", tr("Screen Brightness"),
      tr("Adjust the brightness level. 0 = Auto, negative = darker, positive = brighter."),
      kIcon, -20, 5, 1, -12 },

    { "ParamAutoScreenOff", tr("Screen Timeout"),
      tr("Set how long the screen stays on before turning off automatically (in 10-second steps). 0 = None."),
      kIcon, 0, 120, 1, 8 },

    { "ParamPowerOff", tr("Power off time"),
      tr("0=Not used, 1~ = power off delay (1 sec)"),
      kIcon, 0, 60, 1, 15 },

    { "DUAL_CAMERA_VIEW", tr("Dual camera view"),
      tr("0=Off, 1=On"),
      kIcon, 0, 1, 1, 0 },
  };

  // 섹션 만들기
  auto *cruiseSec = new CollapsibleSection(tr("Cruise Settings"), this);
  addItem(cruiseSec);
  for (const auto &d : value_defs) {
    auto *value = new CValueControl(d.param, d.title, d.desc, d.icon, d.min, d.max, d.unit, d.def, m_jsonobj);
    cruiseSec->addWidget(value);
    m_valueCtrl.insert(d.param, value);
  }

  auto *screenSec = new CollapsibleSection(tr("Screen & Power"), this);
  addItem(screenSec);
  for (const auto &d : val2_defs) {
    auto *value = new CValueControl(d.param, d.title, d.desc, d.icon, d.min, d.max, d.unit, d.def, m_jsonobj);
    screenSec->addWidget(value);
    m_valueCtrl.insert(d.param, value);
  }

  auto *logSec = new CollapsibleSection(tr("Logging"), this);
  addItem(logSec);
  logSec->addWidget(new ParamControl("EnableLogging", tr("Enable logging"), tr("Record runtime logs"), kIcon, this));

  // CruiseMode ↔ CruiseGap 의존성
  auto syncCruiseGapEnabled = [this]() {
    const int cruiseMode = m_jsonobj.value("ParamCruiseMode").toInt(0);
    if (auto *gap = m_valueCtrl.value("ParamCruiseGap", nullptr)) gap->setEnabled(cruiseMode != 0);
  };

  if (auto *mode = m_valueCtrl.value("ParamCruiseMode", nullptr)) {
    // 시그널 타입 정정: double로 받거나 void(void) 슬랏 사용
    QObject::connect(mode, qOverload<double>(&CValueControl::valueChanged), this, [=](double){
      syncCruiseGapEnabled();
      update();
    });
  }
  syncCruiseGapEnabled();

  // 차종 선택 버튼
  const QString selected_car = QString::fromStdString(Params().get("SelectedCar"));
  auto *changeCar = new ButtonControl(
      selected_car.isEmpty() ? tr("Select your car") : selected_car,
      selected_car.isEmpty() ? tr("SELECT") : tr("CHANGE"), "");

  QObject::connect(changeCar, &ButtonControl::clicked, this, [=] {
    const QStringList items = m_pCustom ? m_pCustom->m_cars : QStringList();

    QJsonArray jsonArray;
    for (const auto &item : items) jsonArray.append(item);
    m_jsonobj["SupportCars"] = jsonArray; // SurportCars → SupportCars 수정 유지

    const QString current = QString::fromStdString(Params().get("SelectedCar"));
    const QString selection = MultiOptionDialog::getSelection(tr("Select a car"), items, current, this);
    if (!selection.isEmpty()) {
      Params().put("SelectedCar", selection.toStdString());
      changeCar->setTitle(selection);
      changeCar->setValue(tr("CHANGE"));
    }
  });
  addItem(changeCar);

  applyListWidgetBaseStyle(this);
}

void CommunityTab::showEvent(QShowEvent *event) { QWidget::showEvent(event); }
void CommunityTab::hideEvent(QHideEvent *event) { QWidget::hideEvent(event); }

// ======================================================================================
// GitTab
// ======================================================================================
GitTab::GitTab(CustomPanel *parent, QJsonObject &jsonobj)
  : ListWidget(parent), m_jsonobj(jsonobj), m_pCustom(parent) {

  auto gitPruneBtn = new ButtonControl(tr("Fetch All and Prune"), tr("Sync"),
                                       "git fetch --all --prune\n git remote prune origin");
  connect(gitPruneBtn, &ButtonControl::clicked, [=]() {
    QProcess::execute("git fetch --all --prune");
    QProcess::execute("git remote prune origin");
  });
  addItem(gitPruneBtn);

  auto gitRemoteBtn = new ButtonControl(tr("Update from Remote"), tr("Update"),
                                        "git fetch origin\n git reset --hard origin/<branch>");
  connect(gitRemoteBtn, &ButtonControl::clicked, [=]() {
    const QString branch = QString::fromStdString(Params().get("GitBranch"));
    const QString cmdReset = QString("git reset --hard origin/%1").arg(branch);

    QProcess::execute("git fetch origin");
    QProcess::execute(cmdReset);

    const QString verify = QString("git rev-parse --verify %1").arg(branch);
    const int exitCode = QProcess::execute(verify);
    if (exitCode == 0) {
      qWarning() << "Git reset success:" << cmdReset;
    } else {
      qWarning() << "Git reset failed(" << exitCode << "):" << cmdReset;
    }
  });
  addItem(gitRemoteBtn);

  auto gitRevertBtn = new ButtonControl(tr("Revert Commit"), tr("Rollback"),
                                        "git reset --hard <commit>");
  connect(gitRevertBtn, &ButtonControl::clicked, [=]() {
    QProcess::execute("git reset --hard ec448a9");
  });
  addItem(gitRevertBtn);

  applyListWidgetBaseStyle(this);
}

void GitTab::showEvent(QShowEvent *event) { QWidget::showEvent(event); }
void GitTab::hideEvent(QHideEvent *event) { QWidget::hideEvent(event); }

// ======================================================================================
// ModelTab
// ======================================================================================
static inline QString detectOpenpilotRoot()
{
    // 1) 기기(AGNOS/Android) 경로가 실제로 있는지 먼저 확인
    if (QFileInfo::exists("/data/openpilot"))
        return "/data";

    // 2) 개발 PC 기본 경로
    QString pc = QDir::homePath();// + "/openpilot";
    if (QFileInfo::exists(pc))
        return pc;

    // 3) 마지막 fallback: 홈 디렉터리
    return QDir::homePath();
}

ModelTab::ModelTab(CustomPanel *parent, QJsonObject &jsonobj)
    : ListWidget(parent), m_jsonobj(jsonobj), m_pCustom(parent) {
  const QString selected_model = QString::fromStdString(Params().get("ActiveModelName"));
  currentModel = selected_model;

  changeModelButton = new ButtonControl(
      selected_model.isEmpty() ? tr("Select your model") : selected_model,
      selected_model.isEmpty() ? tr("SELECT") : tr("CHANGE"), "");

  QObject::connect(changeModelButton, &ButtonControl::clicked, this, [this]() {
    const QStringList items = {
      "5.North_Nevada",
      "4.The_Cool_Peoples",
      "3.Firehose",
      "2.Steam_Powered",
      "1.default"};

    const QString selection = MultiOptionDialog::getSelection(tr("Select a model"), items, currentModel, this);
    if (selection.isEmpty() || selection == currentModel) return;

    Params params;
    const std::string prev = params.get("ActiveModelName");
    params.put("ActiveModelName", selection.toStdString());

    if (selection == "1.default") {
      currentModel = selection;
      changeModelButton->setTitle(selection);
      changeModelButton->setText(tr("CHANGE"));
      changeModelButton->setDescription(QString());
      qWarning() << "Using Comma default PATH";
      return;
    }

    //QDir root(QDir::homePath());
    //QDir root("/data");
    QDir  root(detectOpenpilotRoot());
    root.cd("openpilot"); // ~/openpilot
    const QString modeldPath = root.filePath("selfdrive/modeld");
    const QString scriptPath = root.filePath("selfdrive/ui/qt/custom/script/model_make.sh");

    QFileInfo fi(scriptPath);
    if (!fi.exists() || !fi.isFile() || !(fi.permissions() & QFile::ExeUser)) {
      changeModelButton->setTitle(tr("Script missing"));
      changeModelButton->setText(tr("RETRY"));
      changeModelButton->setDescription(scriptPath);
      params.put("ActiveModelName", prev);
      return;
    }

    changeModelButton->setEnabled(false);
    changeModelButton->setTitle(tr("Compiling..."));
    changeModelButton->setText(tr("WAIT"));
    changeModelButton->setDescription(selection);

    QProcess *proc = new QProcess(this);
    proc->setProgram(scriptPath);
    proc->setWorkingDirectory(modeldPath);

    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("WORKDIR", modeldPath);
    proc->setProcessEnvironment(env);

    connect(proc, &QProcess::readyReadStandardOutput, this, [this, proc]() {
      const auto out = QString::fromUtf8(proc->readAllStandardOutput());
      qWarning() << "[model_make][out]" << out.trimmed();
      changeModelButton->setDescription(out.right(80));
    });
    connect(proc, &QProcess::readyReadStandardError, this, [this, proc]() {
      const auto err = QString::fromUtf8(proc->readAllStandardError());
      qWarning() << "[model_make][err]" << err.trimmed();
      changeModelButton->setDescription(err.right(80));
    });

    connect(proc, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
            this, [=](int code, QProcess::ExitStatus status) {
      qWarning() << "model_make.sh exit code =" << code << "status=" << status;
      if (status == QProcess::NormalExit && code == 0) {
        currentModel = selection;
        changeModelButton->setTitle(selection);
        changeModelButton->setText(tr("CHANGE"));
      } else {
        Params().put("ActiveModelName", prev);
        changeModelButton->setTitle(tr("Failed"));
        changeModelButton->setText(tr("RETRY"));
      }
      changeModelButton->setEnabled(true);
      proc->deleteLater();
    });

    proc->start();
  });

  addItem(changeModelButton);
  applyListWidgetBaseStyle(this);
}

void ModelTab::showEvent(QShowEvent *event) { QWidget::showEvent(event); }
void ModelTab::hideEvent(QHideEvent *event) { QWidget::hideEvent(event); }

// ======================================================================================
// NavigationTab
// ======================================================================================
NavigationTab::NavigationTab(CustomPanel *parent, QJsonObject &jsonobj)
  : ListWidget(parent), m_jsonobj(jsonobj), m_pCustom(parent) {
  std::vector<std::tuple<QString, QString, QString, QString>> toggle_defs{
    { "UseExternalNaviRoutes", tr("Use external navi routes"), "",
      "../assets/offroad/icon_openpilot.png" },
  };

  for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new ParamControl(param, title, desc, icon, this);
    const bool locked = params.getBool((param + "Lock").toStdString());
    toggle->setEnabled(!locked);
    addItem(toggle);
    toggles[param.toStdString()] = toggle;
  }

  auto *toggle1 = new CValueControl2(
    "ExternalNaviType", tr(" - Use external navi type"),
    "0.comma  1.mappy  2.NDA", "", 0, 5);
  addItem(toggle1);

  addItem(new MapboxToken());
}

// ======================================================================================
// UITab
// ======================================================================================
UITab::UITab(CustomPanel *parent, QJsonObject &jsonobj)
  : ListWidget(parent), m_jsonobj(jsonobj), m_pCustom(parent) {
  std::vector<std::tuple<QString, QString, QString, QString>> toggle_defs{
    { "ShowDebugMessage", "Show Debug Message",
      "Display debug popups/log overlays for troubleshooting.", "../assets/offroad/icon_shell.png" },
    { "DisableUpdates", "Disable OTA Updates",
      "Prevents downloading and installing software updates.", "../assets/offroad/icon_shell.png" },
    { "ShowCarTracking", "how Vehicle Tracking",
      "Display detected vehicles and paths on the HUD.", "../assets/offroad/icon_shell.png" },
    { "tpms", "Show tpms",
      "Show tire pressure monitoring values on the HUD.", "../assets/offroad/icon_shell.png" },
    { "ParamDebug", "Show debug trace message",
      "Enable verbose internal trace messages for diagnostics.", "../assets/offroad/icon_shell.png" },
  };
  // 섹션 만들기
  auto *normal = new CollapsibleSection(tr("Toggle def"), this);
  addItem(normal);
  for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new JsonControl(param, title, desc, icon, this, m_jsonobj);
    normal->addWidget(toggle);
    toggles[param.toStdString()] = toggle;
  }


  std::vector<std::tuple<QString, QString, QString, QString>> kegman_defs{
    { "kegman", "HUD Overlay (Kegman)",
      "Select up to 4 items below to show on the HUD.", "../assets/offroad/icon_shell.png" },
    { "kegmanCPU", "CPU temperature", "1. Shows CPU temperature (°C). Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
    { "kegmanLag", "UI Lag", "2. Shows UI frame latency (ms). Counts toward the 4-item HUD limit", "../assets/offroad/icon_shell.png" },
    { "kegmanBattery", "Battery Voltage", "3. Shows system/battery voltage (V). Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
    { "kegmanGPU", "GPS Accuracy", "4. Shows GPS horizontal accuracy (m). Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
    { "kegmanAngle", "Steering Angle", "5. Shows steering angle (°). Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
    { "kegmanEngine", "Engine Status", "6. Shows engine state (e.g., RPM/ON-OFF). Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
    { "kegmanDistance", "Relative Distance", "7. Shows radar relative distance (m). Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
    { "kegmanSpeed", "Relative Speed", "8. Shows radar relative speed (m/s). Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
  };
 // 섹션 만들기
  auto *kegman = new CollapsibleSection(tr("Kegman Show"), this);
  addItem(kegman);
  for (auto &[param, title, desc, icon] : kegman_defs) {
    auto toggle = new JsonControl(param, title, desc, icon, this, m_jsonobj);
    kegman->addWidget(toggle);
    toggles[param.toStdString()] = toggle;
  }
  connect(toggles["ShowDebugMessage"], &ToggleControl::toggleFlipped, [=]() {
    updateToggles(false);
  });

 /*
   for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new JsonControl(param, title, desc, icon, this, m_jsonobj);
    addItem(toggle);
    toggles[param.toStdString()] = toggle;
  }
*/

}

void UITab::closeEvent(QCloseEvent *event) { QWidget::closeEvent(event); }
void UITab::showEvent(QShowEvent *event) { QWidget::showEvent(event); }

void UITab::hideEvent(QHideEvent *event) {
  QWidget::hideEvent(event);
  updateToggles(true);
}

void UITab::updateToggles(int bSave) {
  if (bSave) m_pCustom->writeJson();

  const bool bDebug = m_jsonobj.value("ShowDebugMessage").toBool();
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

  const bool kegman = bDebug && m_jsonobj.value("kegman").toBool();
  kegman_cpu->setEnabled(kegman);
  kegman_battery->setEnabled(kegman);
  kegman_gpu->setEnabled(kegman);
  kegman_angle->setEnabled(kegman);
  kegman_engine->setEnabled(kegman);
  kegman_distance->setEnabled(kegman);
  kegman_speed->setEnabled(kegman);
}

// ======================================================================================
// Debug Tab
// ======================================================================================
Debug::Debug(CustomPanel *parent, QJsonObject &jsonobj)
  : ListWidget(parent), m_jsonobj(jsonobj), m_pCustom(parent) {
  std::vector<std::tuple<QString, QString, QString, QString>> toggle_defs{
    {"debug1", tr("debug1"), "", "../assets/offroad/icon_shell.png"},
    {"debug2", tr("debug2"), "", "../assets/offroad/icon_shell.png"},
    {"debug3", tr("debug3"), "", "../assets/offroad/icon_shell.png"},
    {"debug4", tr("debug4"), "", "../assets/offroad/icon_shell.png"},
    {"debug5", tr("debug5"), "", "../assets/offroad/icon_shell.png"},
  };

  for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new JsonControl(param, title, desc, icon, this, m_jsonobj);
    addItem(toggle);
    toggles[param.toStdString()] = toggle;
  }
}

void Debug::closeEvent(QCloseEvent *event) { QWidget::closeEvent(event); }
void Debug::showEvent(QShowEvent *event) { QWidget::showEvent(event); }
void Debug::hideEvent(QHideEvent *event) {
  QWidget::hideEvent(event);
  updateToggles(true);
}

void Debug::updateToggles(int bSave) { if (bSave) m_pCustom->writeJson(); }
