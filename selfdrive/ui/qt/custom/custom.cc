#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>
#include <tuple>
#include <vector>
#include <cstdlib>
#include <cstdio>
#include <algorithm>   // std::clamp

#include <QTabWidget>
#include <QObject>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QDir>
#include <QDateTime>
#include <QDebug>
#include <QFile>
#include <QFileInfo>
#include <QIODevice>
#include <QCoreApplication>
#include <QtConcurrent>
#include <QVariant>
#include <QHBoxLayout>
#include <QMap>
#include <QProgressBar>
#include <QScrollArea>
#include <QToolButton>
#include <QPropertyAnimation>
#include <QFrame>

#include "common/params.h"
#include "common/util.h"
#include "system/hardware/hw.h"

#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/custom/custom.h"

// ======================================================================================
// 공통 유틸/상수
// ======================================================================================
namespace {
constexpr double kEPS = 1e-9;
constexpr const char *kOsmRoadsInstallSession = "osm_db_install";
constexpr const char *kOsmSpeedCamerasSession = "osm_speed_cameras_update";

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

static QString shellQuote(const QString &value) {
  QString escaped = value;
  escaped.replace("'", "'\\''");
  return "'" + escaped + "'";
}

static QString osmRoadsNavdRoot() {
  return QDir("/data/params/d").exists()
      ? QString("/data/navd")
      : QDir::home().absoluteFilePath(".comma/navd");
}

static QString osmRoadsNavdTmpRoot(bool ensure_dir = false) {
  const QString navdTmpRoot = QDir(osmRoadsNavdRoot()).absoluteFilePath("tmp");
  if (ensure_dir) {
    QDir().mkpath(navdTmpRoot);
  }
  return navdTmpRoot;
}

static QString osmRoadsNavdSourceRoot(bool ensure_dir = false) {
  const QString navdSourceRoot = QDir(osmRoadsNavdRoot()).absoluteFilePath("source");
  if (ensure_dir) {
    QDir().mkpath(navdSourceRoot);
  }
  return navdSourceRoot;
}

static QString osmRoadsNavdLogRoot(bool ensure_dir = false) {
  const QString navdLogRoot = QDir(osmRoadsNavdRoot()).absoluteFilePath("logs");
  if (ensure_dir) {
    QDir().mkpath(navdLogRoot);
  }
  return navdLogRoot;
}

static QString osmRoadsInstalledDbPath() {
  return QDir(QDir(osmRoadsNavdRoot()).absoluteFilePath("db")).absoluteFilePath("osm_roads_kr.sqlite3");
}

static QString osmRoadsInstallLogPath(bool ensure_dir = false) {
  return QDir(osmRoadsNavdLogRoot(ensure_dir)).absoluteFilePath("osm_roads_install.log");
}

static QString osmSpeedCamerasLogPath(bool ensure_dir = false) {
  return QDir(osmRoadsNavdLogRoot(ensure_dir)).absoluteFilePath("osm_speed_cameras_update.log");
}

static QString osmSpeedCamerasCsvPath(bool ensure_dir = false) {
  return QDir(osmRoadsNavdSourceRoot(ensure_dir)).absoluteFilePath("speed_cameras.csv");
}

static QString osmRoadsTmpRepoPath() {
  return QDir(osmRoadsNavdTmpRoot()).absoluteFilePath("osm_roads_git_db/repo");
}

static QString osmRoadsTmpDbPath() {
  return QDir(osmRoadsTmpRepoPath()).absoluteFilePath("db/osm_roads_kr.sqlite3");
}

static bool osmRoadsInstallSessionActive() {
  return QProcess::execute("bash", {"-lc", QString("command -v tmux >/dev/null && tmux has-session -t %1 2>/dev/null").arg(kOsmRoadsInstallSession)}) == 0;
}

static void stopOsmRoadsInstallSession() {
  QProcess::execute("bash", {"-lc", QString("command -v tmux >/dev/null && tmux kill-session -t %1 2>/dev/null || true").arg(kOsmRoadsInstallSession)});
}

static bool osmSpeedCamerasSessionActive() {
  return QProcess::execute("bash", {"-lc", QString("command -v tmux >/dev/null && tmux has-session -t %1 2>/dev/null").arg(kOsmSpeedCamerasSession)}) == 0;
}

static void stopOsmSpeedCamerasSession() {
  QProcess::execute("bash", {"-lc", QString("command -v tmux >/dev/null && tmux kill-session -t %1 2>/dev/null || true").arg(kOsmSpeedCamerasSession)});
}

static QString formatOsmRoadsBytes(qint64 size_bytes) {
  double value = static_cast<double>(std::max<qint64>(0, size_bytes));
  const QStringList units = {"B", "KB", "MB", "GB"};
  for (const QString &unit : units) {
    if (value < 1024.0 || unit == "GB") {
      return unit == "B" ? QString("%1 B").arg(static_cast<qint64>(value)) : QString("%1 %2").arg(value, 0, 'f', 1).arg(unit);
    }
    value /= 1024.0;
  }
  return QString("%1 GB").arg(value, 0, 'f', 1);
}

static QString osmRoadsFileDetail(const QString &label, const QString &path) {
  const QFileInfo info(path);
  if (!info.exists()) {
    return QString();
  }
  const QString modified = info.lastModified().toString("yyyy-MM-dd HH:mm");
  return QString("%1 %2 (%3, %4)").arg(label, path, formatOsmRoadsBytes(info.size()), modified);
}

static qint64 osmRoadsLfsPointerSize() {
  QFile file(osmRoadsTmpDbPath());
  if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
    return 0;
  }
  while (!file.atEnd()) {
    const QByteArray line = file.readLine().trimmed();
    if (line.startsWith("size ")) {
      bool ok = false;
      const qint64 size = QString::fromUtf8(line.mid(5)).toLongLong(&ok);
      return ok ? size : 0;
    }
  }
  return 0;
}

static qint64 osmRoadsLfsIncompleteSize() {
  const QDir incompleteDir(QDir(osmRoadsTmpRepoPath()).absoluteFilePath(".git/lfs/incomplete"));
  qint64 largest = 0;
  for (const QFileInfo &file : incompleteDir.entryInfoList(QDir::Files | QDir::NoDotAndDotDot)) {
    largest = std::max(largest, file.size());
  }
  return largest;
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
    scene.custom.powerOffRemaining = 0;
    scene.custom.powerOffProgress = 0.0f;
    updateToggles(false);
    const auto car_state = sm2["carState"].getCarState();
    float vEgo = car_state.getVEgo();
    if (vEgo > 10) scene.custom.m_powerflag = 1;
  } else {
    m_time++;
    const int powerOff = m_jsonobj.value("ParamPowerOff").toInt();
    if (powerOff > 0 && scene.custom.m_powerflag) {
      const int elapsed = std::clamp(m_time, 0, powerOff);
      scene.custom.powerOffRemaining = std::max(powerOff - elapsed, 0);
      scene.custom.powerOffProgress = static_cast<float>(elapsed) / static_cast<float>(powerOff);
    } else {
      scene.custom.powerOffRemaining = 0;
      scene.custom.powerOffProgress = 0.0f;
    }

    if (powerOff && (m_time >= powerOff) && (scene.custom.m_powerflag)) {
      scene.custom.m_powerflag = 0;
      scene.custom.powerOffRemaining = 0;
      scene.custom.powerOffProgress = 0.0f;
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

  const bool kegman = m_jsonobj.value("kegman").toBool();
  const bool kegmanCPU = m_jsonobj.value("kegmanCPU").toBool();
  const bool kegmanLag = m_jsonobj.value("kegmanLag").toBool();
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
  ui.setKegmanLag(kegmanLag);
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

struct ModelCompileStatus {
  QString state;
  QString compiledAt;
  QString vision;
  QString policy;
  QString backend;
};

static QStringList modelOptions()
{
  return {
    "11.POP_Model",
    "10.CD210_Model",
    "9.WMI_Model",
    "8.SC_Driving",
    "7.MacroStiff_Model",
    "6.Dark_Souls_2",
    "5.North_Nevada",
    "4.The_Cool_Peoples",
    "3.Firehose",
    "2.Steam_Powered",
    "1.default",
  };
}

static QString modeldRootPath()
{
  QDir root(detectOpenpilotRoot());
  root.cd("openpilot");
  return root.filePath("selfdrive/modeld");
}

static QString modelBundlePath(const QString &modelName)
{
  QDir modeld(modeldRootPath());
  return modeld.filePath("models/supercombos/" + modelName);
}

static QString formatModelTime(const QDateTime &dt)
{
  return dt.isValid() ? dt.toLocalTime().toString("yyyy-MM-dd HH:mm") : QString();
}

static QString currentModelBackend()
{
  if (QFileInfo::exists("/TICI")) return "QCOM";
  return "LLVM";
}

static QString formatElapsed(qint64 startedAt)
{
  if (startedAt <= 0) return "00:00";
  const qint64 elapsed = std::max<qint64>(0, QDateTime::currentMSecsSinceEpoch() - startedAt) / 1000;
  return QString("%1:%2")
      .arg(elapsed / 60, 2, 10, QChar('0'))
      .arg(elapsed % 60, 2, 10, QChar('0'));
}

static QString artifactState(const QFileInfo &onnx, const QFileInfo &pkl)
{
  if (!onnx.exists()) return "missing onnx";
  if (!pkl.exists()) return "missing";
  if (pkl.lastModified() < onnx.lastModified()) return "stale";
  return "ready";
}

static QString backendFromPkl(const QFileInfo &pkl)
{
  QFile file(pkl.filePath());
  if (!file.open(QIODevice::ReadOnly)) return QString();

  const QByteArray data = file.read(4096);
  QString backend;
  int bestPos = -1;
  for (const QByteArray &candidate : {QByteArray("QCOM"), QByteArray("LLVM"), QByteArray("AMD"), QByteArray("CPU")}) {
    const int pos = data.indexOf(candidate);
    if (pos >= 0 && (bestPos < 0 || pos < bestPos)) {
      bestPos = pos;
      backend = QString::fromLatin1(candidate);
    }
  }
  return backend;
}

static QString backendFromCompileInfo(const QDir &bundle)
{
  QFile file(bundle.filePath("compile_info.json"));
  if (!file.open(QIODevice::ReadOnly)) return QString();

  const QJsonDocument doc = QJsonDocument::fromJson(file.readAll());
  if (!doc.isObject()) return QString();
  return doc.object().value("backend").toString();
}

static QString artifactBackend(const QDir &bundle, const QFileInfo &visionPkl, const QFileInfo &policyPkl)
{
  const QString infoBackend = backendFromCompileInfo(bundle);
  if (!infoBackend.isEmpty()) return infoBackend;

  const QString visionBackend = backendFromPkl(visionPkl);
  const QString policyBackend = backendFromPkl(policyPkl);
  if (!visionBackend.isEmpty() && visionBackend == policyBackend) return visionBackend;
  if (!visionBackend.isEmpty() && !policyBackend.isEmpty()) return "mixed";
  if (!visionBackend.isEmpty()) return visionBackend;
  if (!policyBackend.isEmpty()) return policyBackend;
  return "unknown";
}

static ModelCompileStatus getModelCompileStatus(const QString &modelName)
{
  if (modelName.isEmpty() || modelName == "1.default") {
    return {"Built-in", QString(), "built-in", "built-in", "built-in"};
  }

  const QDir bundle(modelBundlePath(modelName));
  const QFileInfo visionOnnx(bundle.filePath("driving_vision.onnx"));
  const QFileInfo policyOnnx(bundle.filePath("driving_policy.onnx"));
  const QFileInfo visionPkl(bundle.filePath("driving_vision_tinygrad.pkl"));
  const QFileInfo policyPkl(bundle.filePath("driving_policy_tinygrad.pkl"));

  const QString vision = artifactState(visionOnnx, visionPkl);
  const QString policy = artifactState(policyOnnx, policyPkl);
  QString state;
  if (vision == "missing onnx" || policy == "missing onnx") {
    state = "Missing ONNX";
  } else if (vision == "ready" && policy == "ready") {
    state = "Ready";
  } else if (vision == "stale" || policy == "stale") {
    state = "Stale";
  } else if (visionPkl.exists() || policyPkl.exists()) {
    state = "Partial";
  } else {
    state = "Not compiled";
  }

  QDateTime compiledAt;
  if (visionPkl.exists()) compiledAt = visionPkl.lastModified();
  if (policyPkl.exists() && (!compiledAt.isValid() || policyPkl.lastModified() > compiledAt)) {
    compiledAt = policyPkl.lastModified();
  }

  return {state, formatModelTime(compiledAt), vision, policy, artifactBackend(bundle, visionPkl, policyPkl)};
}

static QString modelStatusSummary(const QString &modelName)
{
  const ModelCompileStatus status = getModelCompileStatus(modelName);
  if (status.compiledAt.isEmpty()) return status.state;
  return status.state + " · " + status.compiledAt;
}

static QString modelSelectionLabel(const QString &modelName)
{
  return modelName + "    " + modelStatusSummary(modelName);
}

static QString modelDescription(const QString &modelName)
{
  static const QMap<QString, QString> descriptions = {
    {"11.POP_Model", "Progressive control profile for confident longitudinal response"},
    {"10.CD210_Model", "Comfort-oriented profile tuned for smoother everyday driving"},
    {"9.WMI_Model", "Balanced experimental profile for natural lane keeping"},
    {"8.SC_Driving", "Smooth steering profile with calm corrections"},
    {"7.MacroStiff_Model", "Stable high-speed profile with firm path tracking"},
    {"6.Dark_Souls_2", "Fast response profile with controlled stability"},
    {"5.North_Nevada", "Natural and stable profile for relaxed driving"},
    {"4.The_Cool_Peoples", "Responsive profile with sharper lateral behavior"},
    {"3.Firehose", "Smooth profile with quick reaction timing"},
    {"2.Steam_Powered", "Custom driving model profile"},
    {"1.default", "Built-in comma model"},
  };
  return descriptions.value(modelName, "Custom driving model profile");
}

static QLabel *makeModelStatusLine(QWidget *parent, int fontSize, const QString &color)
{
  QLabel *label = new QLabel(parent);
  label->setStyleSheet(QString(R"(
    font-family: "Roboto Mono", "DejaVu Sans Mono", monospace;
    font-size: %1px;
    color: %2;
  )").arg(fontSize).arg(color));
  label->setWordWrap(true);
  label->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
  return label;
}

static QProgressBar *makeModelProgressBar(QWidget *parent)
{
  auto *bar = new QProgressBar(parent);
  bar->setRange(0, 100);
  bar->setTextVisible(false);
  bar->setFixedHeight(18);
  bar->setStyleSheet(R"(
    QProgressBar {
      border: 1px solid #666;
      background-color: #1b1b1b;
      border-radius: 4px;
    }
    QProgressBar::chunk {
      background-color: #4aa3ff;
      border-radius: 3px;
    }
  )");
  return bar;
}

ModelTab::ModelTab(CustomPanel *parent, QJsonObject &jsonobj)
    : ListWidget(parent), m_jsonobj(jsonobj), m_pCustom(parent) {
  const QString selected_model = QString::fromStdString(Params().get("ActiveModelName"));
  currentModel = selected_model;

  changeModelButton = new ButtonControl(
      selected_model.isEmpty() ? tr("Select your model") : selected_model,
      selected_model.isEmpty() ? tr("SELECT") : tr("CHANGE"), "");

  QObject::connect(changeModelButton, &ButtonControl::clicked, this, [this]() {
    QStringList items;
    QMap<QString, QString> modelByLabel;
    QString currentLabel;
    for (const QString &modelName : modelOptions()) {
      const QString label = modelSelectionLabel(modelName);
      items.append(label);
      modelByLabel.insert(label, modelName);
      if (modelName == currentModel) currentLabel = label;
    }

    const QString selectedLabel = MultiOptionDialog::getSelection(tr("Select a model"), items, currentLabel, this);
    const QString selection = modelByLabel.value(selectedLabel, selectedLabel);
    if (selection.isEmpty() || selection == currentModel) return;

    Params params;
    const std::string prev = params.get("ActiveModelName");
    params.put("ActiveModelName", selection.toStdString());

    if (selection == "1.default") {
      currentModel = selection;
      changeModelButton->setTitle(selection);
      changeModelButton->setText(tr("CHANGE"));
      refreshModelStatus();
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
    changeModelButton->setTitle(selection);
    changeModelButton->setText(tr("WAIT"));
    changeModelButton->setDescription(selection);
    modelCompileStartedAt = QDateTime::currentMSecsSinceEpoch();
    modelCompilingName = selection;
    if (modelDescriptionLabel) modelDescriptionLabel->setText(modelDescription(selection));
    setModelCompileProgress(tr("Preparing files"), 10, currentModelBackend());

    QProcess *proc = new QProcess(this);
    modelProcess = proc;
    proc->setProgram(scriptPath);
    proc->setWorkingDirectory(modeldPath);

    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("WORKDIR", modeldPath);
    proc->setProcessEnvironment(env);

    connect(proc, &QProcess::readyReadStandardOutput, this, [this, proc]() {
      const auto out = QString::fromUtf8(proc->readAllStandardOutput());
      qWarning() << "[model_make][out]" << out.trimmed();
      changeModelButton->setDescription(out.right(80));
      if (out.contains("driving_vision_tinygrad.pkl")) {
        setModelCompileProgress(tr("Vision model"), out.contains("pkl OK") ? 70 : 32, currentModelBackend());
      } else if (out.contains("driving_policy_tinygrad.pkl")) {
        setModelCompileProgress(tr("Policy model"), out.contains("pkl OK") ? 95 : 76, currentModelBackend());
      } else if (out.contains("meta OK")) {
        setModelCompileProgress(tr("Generating metadata"), 20, currentModelBackend());
      }
    });
    connect(proc, &QProcess::readyReadStandardError, this, [this, proc]() {
      const auto err = QString::fromUtf8(proc->readAllStandardError());
      qWarning() << "[model_make][err]" << err.trimmed();
      changeModelButton->setDescription(err.right(80));
      if (err.contains("driving_vision_tinygrad.pkl")) {
        setModelCompileProgress(tr("Vision model"), err.contains("pkl OK") ? 70 : 32, currentModelBackend());
      } else if (err.contains("driving_policy_tinygrad.pkl")) {
        setModelCompileProgress(tr("Policy model"), err.contains("pkl OK") ? 95 : 76, currentModelBackend());
      } else if (err.contains("meta OK")) {
        setModelCompileProgress(tr("Generating metadata"), 20, currentModelBackend());
      }
    });

    connect(proc, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
            this, [=](int code, QProcess::ExitStatus status) {
      qWarning() << "model_make.sh exit code =" << code << "status=" << status;
      if (modelProcess == proc) modelProcess = nullptr;
      if (status == QProcess::NormalExit && code == 0) {
        currentModel = selection;
        changeModelButton->setTitle(selection);
        changeModelButton->setText(tr("CHANGE"));
        modelCompileStartedAt = 0;
        modelCompilingName.clear();
        modelCompileStage.clear();
        modelCompileDetail.clear();
        modelCompilePercent = 0;
        refreshModelStatus();
      } else {
        Params().put("ActiveModelName", prev);
        currentModel = QString::fromStdString(prev);
        changeModelButton->setTitle(tr("Failed"));
        changeModelButton->setText(tr("RETRY"));
        modelCompileStartedAt = 0;
        modelCompilingName.clear();
        modelCompileStage.clear();
        modelCompileDetail.clear();
        modelCompilePercent = 0;
        if (modelStatusTitle && modelDescriptionLabel && modelCompiledAt && modelArtifactStatus && modelProgressBar && modelProgressDetail) {
          const ModelCompileStatus previousStatus = getModelCompileStatus(currentModel);
          modelStatusTitle->setText(tr("Compile failed"));
          modelDescriptionLabel->setText(modelDescription(selection));
          modelCompiledAt->setText(tr("Model: ") + selection);
          modelArtifactStatus->setText("Previous: " + previousStatus.state);
          modelProgressBar->setVisible(false);
          modelProgressDetail->setVisible(true);
          modelProgressDetail->setText("Vision: " + previousStatus.vision + " · Policy: " + previousStatus.policy);
        }
      }
      changeModelButton->setEnabled(true);
      proc->deleteLater();
    });

    connect(proc, &QObject::destroyed, this, [this, proc]() {
      if (modelProcess == proc) modelProcess = nullptr;
    });

    proc->start();
  });

  addItem(changeModelButton);
  modelStatusPanel = new QFrame(this);
  modelStatusPanel->setStyleSheet(R"(
    QFrame {
      border: none;
      background-color: black;
    }
  )");
  auto *statusLayout = new QVBoxLayout(modelStatusPanel);
  statusLayout->setContentsMargins(0, 24, 0, 24);
  statusLayout->setSpacing(10);
  modelStatusTitle = makeModelStatusLine(modelStatusPanel, 38, "#f4f4f4");
  modelDescriptionLabel = makeModelStatusLine(modelStatusPanel, 28, "#a8a8a8");
  modelCompiledAt = makeModelStatusLine(modelStatusPanel, 30, "#d0d0d0");
  modelArtifactStatus = makeModelStatusLine(modelStatusPanel, 30, "#d0d0d0");
  modelProgressBar = makeModelProgressBar(modelStatusPanel);
  modelProgressDetail = makeModelStatusLine(modelStatusPanel, 28, "#bdbdbd");
  statusLayout->addWidget(modelStatusTitle);
  statusLayout->addWidget(modelDescriptionLabel);
  statusLayout->addWidget(modelCompiledAt);
  statusLayout->addWidget(modelProgressBar);
  statusLayout->addWidget(modelProgressDetail);
  statusLayout->addWidget(modelArtifactStatus);
  addItem(modelStatusPanel);
  refreshModelStatus();
  applyListWidgetBaseStyle(this);
}

void ModelTab::refreshModelStatus()
{
  if (!modelStatusTitle || !modelDescriptionLabel || !modelCompiledAt || !modelArtifactStatus || !modelProgressBar || !modelProgressDetail) return;
  if (isModelCompileActive()) {
    setModelCompileProgress(
        modelCompileStage.isEmpty() ? tr("Compiling model") : modelCompileStage,
        modelCompilePercent > 0 ? modelCompilePercent : 10,
        modelCompileDetail.isEmpty() ? currentModelBackend() : modelCompileDetail);
    return;
  }
  const ModelCompileStatus status = getModelCompileStatus(currentModel);
  modelStatusTitle->setText(status.state == "Ready" ? status.state + " · " + status.backend : status.state);
  modelDescriptionLabel->setText(modelDescription(currentModel));
  modelCompiledAt->setText(status.compiledAt.isEmpty() ? "Compiled: -" : "Compiled: " + status.compiledAt);
  modelProgressBar->setVisible(false);
  modelProgressDetail->setVisible(false);
  modelArtifactStatus->setText("Vision: " + status.vision + "\nPolicy: " + status.policy);
}

void ModelTab::setModelCompileProgress(const QString &stage, int percent, const QString &detail)
{
  if (!modelStatusTitle || !modelDescriptionLabel || !modelCompiledAt || !modelArtifactStatus || !modelProgressBar || !modelProgressDetail) return;
  const int boundedPercent = std::clamp(percent, 0, 100);
  modelCompileStage = stage;
  modelCompilePercent = boundedPercent;
  modelCompileDetail = detail;
  const QString displayModel = modelCompilingName.isEmpty() ? currentModel : modelCompilingName;
  modelStatusTitle->setText(tr("Compiling model"));
  modelDescriptionLabel->setText(modelDescription(displayModel));
  modelCompiledAt->setText(QString("%1                                  %2%").arg(stage).arg(boundedPercent));
  modelProgressBar->setVisible(true);
  modelProgressBar->setValue(boundedPercent);
  modelProgressDetail->setVisible(true);
  modelProgressDetail->setText("Backend: " + detail + " · Elapsed: " + formatElapsed(modelCompileStartedAt));
  modelArtifactStatus->setText(QString());
}

bool ModelTab::isModelCompileActive() const
{
  return modelCompileStartedAt > 0 && modelProcess && modelProcess->state() != QProcess::NotRunning;
}

void ModelTab::showEvent(QShowEvent *event) { QWidget::showEvent(event); refreshModelStatus(); }
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

  auto *osmSection = new CollapsibleSection(tr("OSM road prediction"), this);
  addItem(osmSection);

  auto *osmEnable = new ParamControl(
      "OSMEnable",
      tr("Use OSM road prediction"),
      tr("Use the local OSM road DB for current-road matching, forward-road prediction, and the mini map."),
      "../assets/offroad/icon_openpilot.png",
      this);
  const bool osmLocked = params.getBool("OSMEnableLock");
  osmEnable->setEnabled(!osmLocked);
  osmSection->addWidget(osmEnable);
  toggles["OSMEnable"] = osmEnable;

  auto *osmCameraSection = new CollapsibleSection(tr("OSM speed camera"), this);
  addItem(osmCameraSection);

  if (params.get("OsmShowSuspiciousCameras").empty()) {
    params.putBool("OsmShowSuspiciousCameras", true);
  }
  auto *osmShowSuspiciousCameras = new ParamControl(
      "OsmShowSuspiciousCameras",
      tr("Show suspicious OSM cameras"),
      tr("Show suspicious OSM speed camera candidates on the mini map for validation. When disabled, only verified normal speed camera icons are shown."),
      "../assets/offroad/icon_openpilot.png",
      this);
  osmCameraSection->addWidget(osmShowSuspiciousCameras);
  toggles["OsmShowSuspiciousCameras"] = osmShowSuspiciousCameras;

  if (params.get("OsmCameraDisplayDistanceM").empty()) {
    params.put("OsmCameraDisplayDistanceM", "1000");
  }
  auto *osmCameraDisplayDistance = new CValueControl2(
      "OsmCameraDisplayDistanceM",
      tr("OSM camera icon distance"),
      tr("Set how far ahead OSM speed camera icons are shown on the mini map and HUD camera alert."),
      "../assets/offroad/icon_openpilot.png",
      350, 3000, 100);
  osmCameraSection->addWidget(osmCameraDisplayDistance);

  updateOsmSpeedCamerasButton = new ButtonControl(
      tr("Update OSM speed cameras"),
      tr("UPDATE"),
      tr("Download the public speed camera CSV and rematch it into the installed OSM road DB. The road graph DB is not rebuilt."),
      this);
  connect(updateOsmSpeedCamerasButton, &ButtonControl::clicked, this, [=]() {
    Params p;
    if (osmSpeedCamerasUpdateRunning()) {
      if (osmSpeedCamerasSessionActive()) {
        stopOsmSpeedCamerasSession();
        p.put("OsmSpeedCamerasUpdateStatus", "failed");
        p.put("OsmSpeedCamerasUpdateError", "OSM speed camera update stopped by user.");
        p.put("OsmSpeedCamerasUpdateProgress", "0");
        refreshOsmSpeedCamerasStatus();
        return;
      }

      p.put("OsmSpeedCamerasUpdateStatus", "failed");
      p.put("OsmSpeedCamerasUpdateError", "Previous OSM speed camera update process is not running. Starting a new update.");
    }

    if (osmRoadsInstallRunning()) {
      p.put("OsmSpeedCamerasUpdateStatus", "failed");
      p.put("OsmSpeedCamerasUpdateError", "OSM road DB install is running. Retry after the DB install finishes.");
      p.put("OsmSpeedCamerasUpdateProgress", "0");
      refreshOsmSpeedCamerasStatus();
      return;
    }

    const QString dbPath = osmRoadsInstalledDbPath();
    if (!QFileInfo(dbPath).exists()) {
      p.put("OsmSpeedCamerasUpdateStatus", "failed");
      p.put("OsmSpeedCamerasUpdateError", QString("OSM road DB missing: %1").arg(dbPath).toStdString());
      p.put("OsmSpeedCamerasUpdateProgress", "0");
      refreshOsmSpeedCamerasStatus();
      return;
    }

    const QString csvPath = osmSpeedCamerasCsvPath(true);
    p.put("OsmSpeedCamerasUpdateStatus", "running");
    p.put("OsmSpeedCamerasUpdateError", "");
    p.put("OsmSpeedCamerasUpdateProgress", "0");
    p.put("OsmSpeedCamerasCsvPath", csvPath.toStdString());
    p.put("OsmSpeedCamerasDownloadRows", "0");
    p.put("OsmSpeedCamerasDownloadTotalRows", "0");
    p.put("OsmSpeedCamerasImportedCount", "0");
    p.put("OsmSpeedCamerasMatchedCount", "0");
    p.put("OsmSpeedCamerasLookupCount", "0");

    QProcess *proc = new QProcess(this);
    const QString repoRoot = QDir(QCoreApplication::applicationDirPath()).absoluteFilePath("../..");
    const QString canonicalRepoRoot = QDir(repoRoot).canonicalPath();
    const bool navLogsEnabled = p.getBool("NavdLogging");
    const QString tmpRoot = osmRoadsNavdTmpRoot(true);
    const QString logPath = osmSpeedCamerasLogPath(navLogsEnabled);
    if (navLogsEnabled) {
      QFile::remove(logPath);
      QFile logFile(logPath);
      if (logFile.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        logFile.close();
      }
    }
    const QString updateCommand = navLogsEnabled
        ? QString("cd %1 && python3 tools/scripts/update_osm_speed_cameras.py --db %2 --csv %3 --tmp-dir %4 --match-radius-m 65 --require-road-graph 2>&1 | tee %5")
              .arg(shellQuote(canonicalRepoRoot), shellQuote(dbPath), shellQuote(csvPath), shellQuote(tmpRoot), shellQuote(logPath))
        : QString("cd %1 && python3 tools/scripts/update_osm_speed_cameras.py --db %2 --csv %3 --tmp-dir %4 --match-radius-m 65 --require-road-graph >/dev/null 2>&1")
              .arg(shellQuote(canonicalRepoRoot), shellQuote(dbPath), shellQuote(csvPath), shellQuote(tmpRoot));
    const QString tmuxCommand = QString("command -v tmux >/dev/null && "
                                        "(tmux has-session -t %1 2>/dev/null || "
                                        "tmux new-session -d -s %1 %2)")
        .arg(QString::fromLatin1(kOsmSpeedCamerasSession), shellQuote(updateCommand));
    proc->setWorkingDirectory(canonicalRepoRoot);
    proc->setProgram("bash");
    proc->setArguments({"-lc", tmuxCommand});
    proc->setProcessChannelMode(QProcess::MergedChannels);
    connect(proc, &QProcess::readyRead, proc, [proc]() { proc->readAll(); });

    connect(proc, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
            this, [this, proc](int code, QProcess::ExitStatus status) {
      Params finishedParams;
      if (status != QProcess::NormalExit || code != 0) {
        finishedParams.put("OsmSpeedCamerasUpdateStatus", "failed");
        finishedParams.put("OsmSpeedCamerasUpdateError", QString("tmux start failed: exit code %1").arg(code).toStdString());
      }
      proc->deleteLater();
      refreshOsmSpeedCamerasStatus();
    });
    proc->start();
  });
  osmCameraSection->addWidget(updateOsmSpeedCamerasButton);

  auto *speedCameraStatusPanel = new QFrame(this);
  speedCameraStatusPanel->setStyleSheet(R"(
    QFrame {
      border: none;
      background-color: black;
    }
  )");
  auto *speedCameraStatusLayout = new QVBoxLayout(speedCameraStatusPanel);
  speedCameraStatusLayout->setContentsMargins(0, 18, 0, 24);
  speedCameraStatusLayout->setSpacing(10);
  osmSpeedCamerasStatusLabel = makeModelStatusLine(speedCameraStatusPanel, 32, "#f4f4f4");
  osmSpeedCamerasDetailLabel = makeModelStatusLine(speedCameraStatusPanel, 26, "#a8a8a8");
  osmSpeedCamerasProgressBar = makeModelProgressBar(speedCameraStatusPanel);
  speedCameraStatusLayout->addWidget(osmSpeedCamerasStatusLabel);
  speedCameraStatusLayout->addWidget(osmSpeedCamerasProgressBar);
  speedCameraStatusLayout->addWidget(osmSpeedCamerasDetailLabel);
  osmCameraSection->addWidget(speedCameraStatusPanel);

  auto *navdLogging = new ParamControl(
      "NavdLogging",
      tr("Navigation logging"),
      tr("Record navd and OSM diagnostic logs under the navd logs directory."),
      "../assets/offroad/icon_openpilot.png",
      this);
  osmSection->addWidget(navdLogging);
  toggles["NavdLogging"] = navdLogging;

  auto *osmGpsSimulation = new ParamControl(
      "OsmGpsSimulation",
      tr("OSM GPS simulation"),
      tr("Publish simulated GPS only in webcam mode for OSM road prediction testing."),
      "../assets/offroad/icon_openpilot.png",
      this);
  if (!Hardware::PC()) {
    params.putBool("OsmGpsSimulation", false);
    osmGpsSimulation->setEnabled(false);
    osmGpsSimulation->setDescription(tr("Disabled on device hardware. GPS simulation is only available on PC webcam mode."));
  }
  osmSection->addWidget(osmGpsSimulation);
  toggles["OsmGpsSimulation"] = osmGpsSimulation;

  auto *osmPredictionLogging = new ParamControl(
      "OsmPredictionLogging",
      tr("OSM prediction logging"),
      tr("Create OSM route prediction trace and failure logs for validation. Requires Navigation logging and writes under the navd logs directory."),
      "../assets/offroad/icon_openpilot.png",
      this);
  osmSection->addWidget(osmPredictionLogging);
  toggles["OsmPredictionLogging"] = osmPredictionLogging;

  auto *osmMinimapPosition = new ButtonParamControl(
      "OsmMinimapPosition",
      tr("OSM minimap position"),
      tr("Select where the OSM mini map is shown on the driving screen. Center shows a larger debug map fitted to the full OSM road overlay."),
      "../assets/offroad/icon_openpilot.png",
      {tr("LT"), tr("RT"), tr("LB"), tr("RB"), tr("C")},
      120);
  osmSection->addWidget(osmMinimapPosition);

  installOsmDbButton = new ButtonControl(
      tr("Install OSM road DB"),
      tr("INSTALL"),
      tr("Downloads the prebuilt OSM road graph DB from Git LFS and installs it in the navd DB path."),
      this);
  connect(installOsmDbButton, &ButtonControl::clicked, this, [=]() {
    Params p;
    if (osmRoadsInstallRunning()) {
      if (osmRoadsInstallSessionActive()) {
        stopOsmRoadsInstallSession();
        resetOsmRoadsLogReplay(false);
        p.put("OsmRoadsUpdateStatus", "failed");
        p.put("OsmRoadsUpdateError", "OSM road DB install stopped by user.");
        p.put("OsmRoadsUpdateProgress", "0");
        refreshOsmRoadsStatus();
        return;
      }

      p.put("OsmRoadsUpdateStatus", "failed");
      p.put("OsmRoadsUpdateError", "Previous OSM road DB install process is not running. Starting a new install.");
    }

    p.put("OsmRoadsUpdateStatus", "running");
    p.put("OsmRoadsUpdateError", "");
    p.put("OsmRoadsUpdateProgress", "0");
    refreshOsmRoadsStatus();

    QProcess *proc = new QProcess(this);
    const QString repoRoot = QDir(QCoreApplication::applicationDirPath()).absoluteFilePath("../..");
    const QString canonicalRepoRoot = QDir(repoRoot).canonicalPath();
    const bool navLogsEnabled = p.getBool("NavdLogging");
    const QString logPath = osmRoadsInstallLogPath(navLogsEnabled);
    if (navLogsEnabled) {
      QFile::remove(logPath);
      QFile logFile(logPath);
      if (logFile.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        logFile.close();
      }
    }
    resetOsmRoadsLogReplay(true);
    const QString installCommand = navLogsEnabled
        ? QString("cd %1 && python3 tools/scripts/install_osm_roads_db_from_git.py --require-road-graph 2>&1 | tee %2")
              .arg(shellQuote(canonicalRepoRoot), shellQuote(logPath))
        : QString("cd %1 && python3 tools/scripts/install_osm_roads_db_from_git.py --require-road-graph >/dev/null 2>&1")
              .arg(shellQuote(canonicalRepoRoot));
    const QString tmuxCommand = QString("command -v tmux >/dev/null && "
                                        "(tmux has-session -t osm_db_install 2>/dev/null || "
                                        "tmux new-session -d -s osm_db_install %1)")
        .arg(shellQuote(installCommand));
    proc->setWorkingDirectory(canonicalRepoRoot);
    proc->setProgram("bash");
    proc->setArguments({"-lc", tmuxCommand});
    proc->setProcessChannelMode(QProcess::MergedChannels);
    connect(proc, &QProcess::readyRead, proc, [proc]() { proc->readAll(); });

    connect(proc, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
            this, [this, proc](int code, QProcess::ExitStatus status) {
      Params finishedParams;
      if (status != QProcess::NormalExit || code != 0) {
        finishedParams.put("OsmRoadsUpdateStatus", "failed");
        finishedParams.put("OsmRoadsUpdateError", QString("tmux start failed: exit code %1").arg(code).toStdString());
      }
      proc->deleteLater();
      refreshOsmRoadsStatus();
    });
    proc->start();
  });
  osmSection->addWidget(installOsmDbButton);

  auto *statusPanel = new QFrame(this);
  statusPanel->setStyleSheet(R"(
    QFrame {
      border: none;
      background-color: black;
    }
  )");
  auto *statusLayout = new QVBoxLayout(statusPanel);
  statusLayout->setContentsMargins(0, 18, 0, 24);
  statusLayout->setSpacing(10);
  osmRoadsStatusLabel = makeModelStatusLine(statusPanel, 32, "#f4f4f4");
  osmRoadsDetailLabel = makeModelStatusLine(statusPanel, 26, "#a8a8a8");
  osmRoadsProgressBar = makeModelProgressBar(statusPanel);
  statusLayout->addWidget(osmRoadsStatusLabel);
  statusLayout->addWidget(osmRoadsProgressBar);
  statusLayout->addWidget(osmRoadsDetailLabel);
  osmSection->addWidget(statusPanel);

  osmRoadsStatusTimer = new QTimer(this);
  connect(osmRoadsStatusTimer, &QTimer::timeout, this, &NavigationTab::refreshOsmRoadsStatus);
  osmRoadsStatusTimer->start(1000);
  skipOsmRoadsExistingLog();
  refreshOsmRoadsStatus();

  osmSpeedCamerasStatusTimer = new QTimer(this);
  connect(osmSpeedCamerasStatusTimer, &QTimer::timeout, this, &NavigationTab::refreshOsmSpeedCamerasStatus);
  osmSpeedCamerasStatusTimer->start(1000);
  refreshOsmSpeedCamerasStatus();
}

bool NavigationTab::osmRoadsInstallRunning()
{
  return params.get("OsmRoadsUpdateStatus") == "running";
}

bool NavigationTab::osmSpeedCamerasUpdateRunning()
{
  return params.get("OsmSpeedCamerasUpdateStatus") == "running";
}

void NavigationTab::skipOsmRoadsExistingLog()
{
  if (!params.getBool("NavdLogging")) {
    osmRoadsLogReadOffset = -1;
    osmRoadsLastLoggedDownloadBytes = -1;
    return;
  }
  QFile logFile(osmRoadsInstallLogPath(false));
  osmRoadsLogReadOffset = logFile.exists() ? logFile.size() : 0;
  osmRoadsLastLoggedDownloadBytes = -1;
}

void NavigationTab::resetOsmRoadsLogReplay(bool fromBeginning)
{
  osmRoadsLogReadOffset = fromBeginning ? 0 : -1;
  osmRoadsLastLoggedDownloadBytes = -1;
}

void NavigationTab::emitOsmRoadsInstallLog()
{
  if (!params.getBool("NavdLogging")) {
    return;
  }
  const QString logPath = osmRoadsInstallLogPath(true);
  QFile logFile(logPath);
  if (!logFile.exists() && logFile.open(QIODevice::WriteOnly)) {
    logFile.close();
  }

  if (!logFile.open(QIODevice::ReadOnly)) {
    return;
  }

  const qint64 size = logFile.size();
  if (osmRoadsLogReadOffset < 0) {
    osmRoadsLogReadOffset = std::max<qint64>(0, size - 4096);
  }
  if (size < osmRoadsLogReadOffset) {
    osmRoadsLogReadOffset = 0;
  }
  if (size <= osmRoadsLogReadOffset) {
    return;
  }
  if (size - osmRoadsLogReadOffset > 8192) {
    osmRoadsLogReadOffset = size;
    return;
  }

  logFile.seek(osmRoadsLogReadOffset);
  const QByteArray output = logFile.read(8192);
  osmRoadsLogReadOffset = logFile.pos();

  const QStringList lines = QString::fromLocal8Bit(output).split('\n', QString::SkipEmptyParts);
  for (const QString &line : lines) {
    const QByteArray text = line.left(500).toLocal8Bit();
    fprintf(stderr, "[osm_db_install] %s\n", text.constData());
    fflush(stderr);
  }
}

void NavigationTab::refreshOsmSpeedCamerasStatus()
{
  if (!updateOsmSpeedCamerasButton || !osmSpeedCamerasStatusLabel || !osmSpeedCamerasDetailLabel || !osmSpeedCamerasProgressBar) return;

  QString status = QString::fromStdString(params.get("OsmSpeedCamerasUpdateStatus"));
  QString error = QString::fromStdString(params.get("OsmSpeedCamerasUpdateError"));
  const QString updatedAt = QString::fromStdString(params.get("OsmSpeedCamerasUpdatedAt"));
  QString csvPath = QString::fromStdString(params.get("OsmSpeedCamerasCsvPath"));
  if (csvPath.isEmpty()) {
    csvPath = osmSpeedCamerasCsvPath();
  }

  bool ok = false;
  const int progress = std::clamp(QString::fromStdString(params.get("OsmSpeedCamerasUpdateProgress")).toInt(&ok), 0, 100);
  bool rowsOk = false;
  const qint64 downloadRows = QString::fromStdString(params.get("OsmSpeedCamerasDownloadRows")).toLongLong(&rowsOk);
  bool totalOk = false;
  const qint64 downloadTotalRows = QString::fromStdString(params.get("OsmSpeedCamerasDownloadTotalRows")).toLongLong(&totalOk);
  bool importedOk = false;
  const qint64 importedCount = QString::fromStdString(params.get("OsmSpeedCamerasImportedCount")).toLongLong(&importedOk);
  bool matchedOk = false;
  const qint64 matchedCount = QString::fromStdString(params.get("OsmSpeedCamerasMatchedCount")).toLongLong(&matchedOk);
  bool lookupOk = false;
  const qint64 lookupCount = QString::fromStdString(params.get("OsmSpeedCamerasLookupCount")).toLongLong(&lookupOk);
  const QString installedDbDetail = osmRoadsFileDetail("local DB", osmRoadsInstalledDbPath());
  const QString csvDetail = osmRoadsFileDetail("CSV", csvPath);
  const bool navLogsEnabled = params.getBool("NavdLogging");
  const QString logFileDetail = navLogsEnabled ? osmRoadsFileDetail("log", osmSpeedCamerasLogPath()) : tr("navd log disabled");

  bool running = status == "running";
  if (running && !osmSpeedCamerasSessionActive()) {
    running = false;
    status = "failed";
    error = tr("Previous OSM speed camera update process is not running.");
    Params staleParams;
    staleParams.put("OsmSpeedCamerasUpdateStatus", "failed");
    staleParams.put("OsmSpeedCamerasUpdateError", error.toStdString());
  }

  osmSpeedCamerasProgressBar->setValue(ok ? progress : 0);
  osmSpeedCamerasProgressBar->setVisible(running || progress > 0);
  updateOsmSpeedCamerasButton->setEnabled(true);

  auto appendCounts = [&](QStringList &details) {
    if (rowsOk && downloadRows > 0) {
      if (totalOk && downloadTotalRows > 0) {
        details.append(QString("%1 / %2 rows downloaded").arg(downloadRows).arg(downloadTotalRows));
      } else {
        details.append(QString("%1 rows downloaded").arg(downloadRows));
      }
    }
    if (importedOk && importedCount > 0) details.append(QString("%1 cameras").arg(importedCount));
    if (matchedOk && matchedCount > 0) details.append(QString("%1 matched").arg(matchedCount));
    if (lookupOk && lookupCount > 0) details.append(QString("%1 lookup rows").arg(lookupCount));
  };

  if (running) {
    updateOsmSpeedCamerasButton->setText(tr("STOP"));
    osmSpeedCamerasStatusLabel->setText(tr("Updating OSM speed cameras"));
    QStringList details;
    details.append(QString("%1%").arg(ok ? progress : 0));
    appendCounts(details);
    if (!installedDbDetail.isEmpty()) details.append(installedDbDetail);
    details.append(QString("tmux a -t %1").arg(kOsmSpeedCamerasSession));
    if (navLogsEnabled) {
      details.append(QString("tail -f %1").arg(osmSpeedCamerasLogPath()));
    } else {
      details.append(tr("navd log disabled"));
    }
    osmSpeedCamerasDetailLabel->setText(details.join(" | "));
    return;
  }

  if (status == "success") {
    updateOsmSpeedCamerasButton->setText(tr("UPDATE"));
    osmSpeedCamerasStatusLabel->setText(tr("OSM speed cameras ready"));
    QStringList details;
    appendCounts(details);
    if (!updatedAt.isEmpty()) details.append(tr("Updated ") + updatedAt);
    if (!csvDetail.isEmpty()) details.append(csvDetail);
    if (!installedDbDetail.isEmpty()) details.append(installedDbDetail);
    osmSpeedCamerasDetailLabel->setText(details.isEmpty() ? tr("Update completed") : details.join(" | "));
    return;
  }

  if (status == "failed") {
    updateOsmSpeedCamerasButton->setText(tr("RETRY"));
    osmSpeedCamerasStatusLabel->setText(tr("OSM speed camera update failed"));
    QStringList details;
    details.append(error.isEmpty() ? tr("Check network and OSM road DB state.") : error.right(220));
    if (!csvDetail.isEmpty()) details.append(csvDetail);
    if (!installedDbDetail.isEmpty()) details.append(installedDbDetail);
    details.append(logFileDetail.isEmpty() ? QString("log %1").arg(osmSpeedCamerasLogPath()) : logFileDetail);
    osmSpeedCamerasDetailLabel->setText(details.join(" | "));
    return;
  }

  updateOsmSpeedCamerasButton->setText(tr("UPDATE"));
  osmSpeedCamerasStatusLabel->setText(tr("OSM speed cameras"));
  QStringList details;
  if (!csvDetail.isEmpty()) {
    details.append(csvDetail);
  } else {
    details.append(QString("CSV will be downloaded to %1").arg(csvPath));
  }
  if (!installedDbDetail.isEmpty()) {
    details.append(installedDbDetail);
  } else {
    details.append(QString("local DB missing %1").arg(osmRoadsInstalledDbPath()));
  }
  osmSpeedCamerasDetailLabel->setText(details.join(" | "));
}

void NavigationTab::refreshOsmRoadsStatus()
{
  if (!installOsmDbButton || !osmRoadsStatusLabel || !osmRoadsDetailLabel || !osmRoadsProgressBar) return;

  QString status = QString::fromStdString(params.get("OsmRoadsUpdateStatus"));
  QString error = QString::fromStdString(params.get("OsmRoadsUpdateError"));
  const QString updatedAt = QString::fromStdString(params.get("OsmRoadsUpdatedAt"));
  bool ok = false;
  const int progress = std::clamp(QString::fromStdString(params.get("OsmRoadsUpdateProgress")).toInt(&ok), 0, 100);
  bool downloadOk = false;
  qint64 downloadBytes = QString::fromStdString(params.get("OsmRoadsDownloadBytes")).toLongLong(&downloadOk);
  bool downloadTotalOk = false;
  qint64 downloadTotalBytes = QString::fromStdString(params.get("OsmRoadsDownloadTotalBytes")).toLongLong(&downloadTotalOk);
  bool countOk = false;
  const int segmentCount = QString::fromStdString(params.get("OsmRoadsSegmentCount")).toInt(&countOk);
  const QString installedDbDetail = osmRoadsFileDetail("local DB", osmRoadsInstalledDbPath());
  const QString tmpDbDetail = osmRoadsFileDetail("tmp DB", osmRoadsTmpDbPath());
  const bool navLogsEnabled = params.getBool("NavdLogging");
  const QString logFileDetail = navLogsEnabled ? osmRoadsFileDetail("log", osmRoadsInstallLogPath()) : tr("navd log disabled");
  bool running = status == "running";
  if (running && !osmRoadsInstallSessionActive()) {
    running = false;
    status = "failed";
    error = tr("Previous OSM road DB install process is not running.");
    Params staleParams;
    staleParams.put("OsmRoadsUpdateStatus", "failed");
    staleParams.put("OsmRoadsUpdateError", error.toStdString());
  }

  osmRoadsProgressBar->setValue(ok ? progress : 0);
  osmRoadsProgressBar->setVisible(running || progress > 0);
  installOsmDbButton->setEnabled(true);

  if (running) {
    emitOsmRoadsInstallLog();
    if (!downloadOk || downloadBytes <= 0) {
      downloadBytes = osmRoadsLfsIncompleteSize();
      downloadOk = downloadBytes > 0;
    }
    if (!downloadTotalOk || downloadTotalBytes <= 0) {
      downloadTotalBytes = osmRoadsLfsPointerSize();
      downloadTotalOk = downloadTotalBytes > 0;
    }
    if (downloadOk && downloadBytes > 0) {
      const qint64 logStepBytes = 10LL * 1024LL * 1024LL;
      const bool completedDownload = downloadTotalOk && downloadTotalBytes > 0 && downloadBytes >= downloadTotalBytes;
      if (osmRoadsLastLoggedDownloadBytes < 0 ||
          downloadBytes - osmRoadsLastLoggedDownloadBytes >= logStepBytes ||
          completedDownload) {
        const QString downloaded = formatOsmRoadsBytes(downloadBytes);
        const QString total = (downloadTotalOk && downloadTotalBytes > 0) ? formatOsmRoadsBytes(downloadTotalBytes) : QString();
        const QByteArray message = total.isEmpty()
            ? QString("downloaded %1").arg(downloaded).toLocal8Bit()
            : QString("downloaded %1 / %2").arg(downloaded, total).toLocal8Bit();
        fprintf(stderr, "[osm_db_install] %s\n", message.constData());
        fflush(stderr);
        osmRoadsLastLoggedDownloadBytes = downloadBytes;
      }
    }
    installOsmDbButton->setText(tr("STOP"));
    osmRoadsStatusLabel->setText(tr("Installing OSM road DB"));
    QStringList details;
    details.append(QString("%1%").arg(ok ? progress : 0));
    if (downloadOk && downloadBytes > 0) {
      const QString downloaded = formatOsmRoadsBytes(downloadBytes);
      if (downloadTotalOk && downloadTotalBytes > 0) {
        details.append(QString("%1 / %2").arg(downloaded, formatOsmRoadsBytes(downloadTotalBytes)));
      } else {
        details.append(downloaded);
      }
    }
    if (!installedDbDetail.isEmpty()) {
      details.append(installedDbDetail);
    }
    details.append(tr("tmux a -t osm_db_install"));
    if (navLogsEnabled) {
      details.append(QString("tail -f %1").arg(osmRoadsInstallLogPath()));
    } else {
      details.append(tr("navd log disabled"));
    }
    osmRoadsDetailLabel->setText(details.join(" | "));
    return;
  }

  if (status == "success") {
    installOsmDbButton->setText(tr("UPDATE"));
    osmRoadsStatusLabel->setText(tr("OSM road DB ready"));
    QStringList details;
    if (countOk && segmentCount > 0) details.append(QString("%1 segments").arg(segmentCount));
    if (!updatedAt.isEmpty()) details.append(tr("Updated ") + updatedAt);
    if (!installedDbDetail.isEmpty()) details.append(installedDbDetail);
    osmRoadsDetailLabel->setText(details.isEmpty() ? tr("Install completed") : details.join(" | "));
    return;
  }

  if (status == "failed") {
    installOsmDbButton->setText(tr("RETRY"));
    osmRoadsStatusLabel->setText(tr("OSM road DB install failed"));
    QStringList details;
    details.append(error.isEmpty() ? tr("Check network, Git LFS, and storage space.") : error.right(220));
    if (!installedDbDetail.isEmpty()) details.append(installedDbDetail);
    if (!tmpDbDetail.isEmpty()) details.append(tmpDbDetail);
    details.append(logFileDetail.isEmpty() ? QString("log %1").arg(osmRoadsInstallLogPath()) : logFileDetail);
    osmRoadsDetailLabel->setText(details.join(" | "));
    return;
  }

  resetOsmRoadsLogReplay(false);
  if (!installedDbDetail.isEmpty()) {
    installOsmDbButton->setText(tr("UPDATE"));
    osmRoadsStatusLabel->setText(tr("OSM road DB found"));
    osmRoadsDetailLabel->setText(installedDbDetail);
    return;
  }

  installOsmDbButton->setText(tr("INSTALL"));
  osmRoadsStatusLabel->setText(tr("OSM road DB"));
  osmRoadsDetailLabel->setText(QString("Not installed or status unknown | local DB missing %1").arg(osmRoadsInstalledDbPath()));
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
    { "kegmanCPU", "CPU temperature", "1. Shows max CPU temperature and max CPU usage. Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
    { "kegmanLag", "UI Lag", "2. Shows UI frame latency (ms). Counts toward the 4-item HUD limit", "../assets/offroad/icon_shell.png" },
    { "kegmanBattery", "Battery Voltage", "3. Shows system/battery voltage (V). Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
    { "kegmanGPU", "GPU load", "4. Shows GPU temperature and GPU usage. Counts toward the 4-item HUD limit.", "../assets/offroad/icon_shell.png" },
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
  connect(toggles["kegman"], &ToggleControl::toggleFlipped, [=]() {
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
  auto kegman_lag = toggles["kegmanLag"];
  auto kegman_battery = toggles["kegmanBattery"];
  auto kegman_gpu = toggles["kegmanGPU"];
  auto kegman_angle = toggles["kegmanAngle"];
  auto kegman_engine = toggles["kegmanEngine"];
  auto kegman_distance = toggles["kegmanDistance"];
  auto kegman_speed = toggles["kegmanSpeed"];

  tpms_mode_toggle->setEnabled(bDebug);
  debug_mode_toggle->setEnabled(bDebug);
  kegman_mode_toggle->setEnabled(true);

  const bool kegman = m_jsonobj.value("kegman").toBool();
  kegman_cpu->setEnabled(kegman);
  kegman_lag->setEnabled(kegman);
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
