#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>
#include <tuple>
#include <vector>


#include <QTabWidget>
#include <QObject>
#include <QJsonArray>
#include <QProcess>

#include "common/watchdog.h"
#include "common/params.h"
#include "common/watchdog.h"
#include "common/util.h"



#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/custom/custom.h"




CValueControl::CValueControl(const QString& param, const QString& title, const QString& desc, const QString& icon, int min, int max, int unit, QJsonObject &jsonobj  )
              : AbstractControl(title, desc, icon) , m_jsonobj(jsonobj)
{
    key = param;
    m_min = min;
    m_max = max;
    m_unit = unit;

    label.setAlignment( Qt::AlignVCenter | Qt::AlignRight );
    label.setStyleSheet("color: #e0e879");
    hlayout->addWidget( &label );

    int state = min;
    if ( !m_jsonobj.contains(key) )
    {
      m_jsonobj.insert(key, state);
    }
    else
    {
      state  = m_jsonobj[key].toInt();
    }

    m_value = state;

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

    btnminus.setFixedSize( 150, 100 );
    btnplus.setFixedSize( 150, 100 );
    hlayout->addWidget( &btnminus );
    hlayout->addWidget( &btnplus );

    QObject::connect(&btnminus, &QPushButton::released, [=]()
    {
        int value = m_value;
        value = value - m_unit;
        if (value < m_min)
            value = m_min;

        setValue( value );
    });

    QObject::connect(&btnplus, &QPushButton::released, [=]()
    {
        int value = m_value;
        value = value + m_unit;
        if (value > m_max)
            value = m_max;

        setValue( value );
    });
    refresh();
}

void CValueControl::refresh()
{
    QString  str;

    str.sprintf("%d", m_value );
    label.setText( str );
    btnminus.setText("－");
    btnplus.setText("＋");
}


int  CValueControl::getValue()
{
  int  ret_code = m_value;
  return  ret_code;
}

void CValueControl::setValue( int value )
{
  if( m_value != value )
  {
    m_jsonobj[key] = value;
    m_value = value;
    refresh();

    emit clicked();
  }
}



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
    printf( "timer %d  endtime =%d", m_time, PowerOff);
    if( PowerOff && (m_time > (PowerOff*UI_FREQ)) && (scene.custom.m_powerflag) )
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
  comunity.setCmdIdx( m_cmdIdx );
  comunity.setCruiseMode( cruiseMode );
  comunity.setCruiseGap( cruiseGap );
  comunity.setCurveSpeedLimit( curveSpeedLimit );


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
      kIcon, 0, 15, 1 }, // min, max, unit

    { "ParamCruiseGap",
      tr("Cruise gap"),
      tr("0=Not used, 1~4=Gap for Comma speed"),
      kIcon, 0, 4, 1 },

    { "ParamCurveSpeedLimit",
      tr("Curve speed adjust"),
      tr("Adjust maximum speed based on road curvature. "),
      kIcon, 30, 120, 10 },


    { "ParamAutoEngage",
      tr("Auto engage"),
      tr("Automatically engages when conditions are met. 0=Manual, 1=Auto"),
      kIcon, 0, 1, 1 },

    { "ParamAutoLaneChange",
      tr("Auto lane change"),
      tr("Automatically changes lanes when conditions are met. 0=Manual, 1=Auto"),
      kIcon, 0, 100, 10 },

    { "ParamBrightness",
      tr("Screen Brightness"),
      tr("Adjust the brightness level. 0 = Auto, negative = darker, positive = brighter."),
      kIcon, -10, 10, 1 },

    { "ParamAutoScreenOff",
      tr("Screen Timeout"),
      tr("Set how long the screen stays on before turning off automatically (in 10-second steps). 0 = None."),
      kIcon, 0, 120, 5 },

    { "ParamPowerOff",
      tr("Power off time"),
      tr("0=Not used, 1~ = power off delay (1 sec)"),
      kIcon, 0, 60, 1 },

    { "DUAL_CAMERA_VIEW",
      tr("Dual camera view"),
      tr("0=Off, 1=On"),
      kIcon, 0, 1, 1 },
  };

  // 2) ValueControl 생성 및 등록 (키는 QString으로 통일)
  for (const auto &d : value_defs) {
    auto *value = new CValueControl(d.param, d.title, d.desc, d.icon, d.min, d.max, d.unit, m_jsonobj);
    addItem(value);
    m_valueCtrl.insert(d.param, value);
  }

  // 3) 토글류 이외의 스위치 예시
  addItem(new ParamControl("EnableLogging",
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
    QObject::connect(mode, &CValueControl::clicked, this, [=] {
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

ModelTab::ModelTab(CustomPanel *parent, QJsonObject &jsonobj) : ListWidget(parent) , m_jsonobj(jsonobj)
{
  m_pCustom = parent;



  QString selected_model = QString::fromStdString(Params().get("SelectedModel"));
  auto changeModel = new ButtonControl(selected_model.length() ? selected_model : tr("Select your model"),
                    selected_model.length() ? tr("CHANGE") : tr("SELECT"), "");

  QObject::connect( changeModel, &ButtonControl::clicked, [=]() {
    QStringList items = {
      "8.Notre Dame Model,supercombo_ND",
      "7.North Dakota Model,supercombo_DM",
      "6.WD40 model,supercombo_WD40",
      "5.Duck_Amigo model,supercombo_DA",
      "4.Recertified_Herbalist,supercombo_RH",
      "3.Los_Angeles model,supercombo_LA",
      "2.Certified_Herbalist2,supercombo_CH2",
      "1.Certified_Herbalist1,supercombo_CH1",
      };

    QString selection = MultiOptionDialog::getSelection(tr("Select a model"), items, selected_model, this);
    if ( !selection.isEmpty() )
    {
      //  int selectedIndex = items.indexOf(selection);
      Params().put("SelectedModel", selection.toStdString());
      //  printf("sected model  %d  %s", selectedIndex, selection.toStdString());
     // qApp->exit(18);
    //  watchdog_kick(0);
    }
  });
  addItem(changeModel);






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
      "",
      "../assets/offroad/icon_shell.png",
    },
    {
      "ShowCarTracking",
      "Show Car Tracking",
      "",
      "../assets/offroad/icon_shell.png",
    },
    {
      "tpms",
      "Show tpms",
      "",
      "../assets/offroad/icon_shell.png",
    },
    {
      "ParamDebug",
      "Show debug trace message",
      "",
      "../assets/offroad/icon_shell.png",
    },
    {
      "kegman",
      "Show kegman",
      "You can choose 4 max from the menu below",
      "../assets/offroad/icon_shell.png",
    },
    {
      "kegmanCPU",
      " - CPU temperature",
      "1. Up to 4 menus can be displayed.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanLag",
      " - Lag(ms) CPU status",
      "2. Up to 4 menus can be displayed.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanBattery",
      " - battery voltage",
      "3. Up to 4 menus can be displayed.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanGPU",
      " - GPS accuracy",
      "4. Up to 4 menus can be displayed.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanAngle",
      " - steering angle",
      "5. Up to 4 menus can be displayed.",
      "",
     // "../assets/offroad/icon_shell.png",
    },
    {
      "kegmanEngine",
      " - engine status",
      "6. Up to 4 menus can be displayed.",
      "",
      //"../assets/offroad/icon_shell.png",
    },
    {
      "kegmanDistance",
      " - radar relative distance",
      "7. Up to 4 menus can be displayed.",
      "",
     // "../assets/offroad/icon_shell.png",
    },
    {
      "kegmanSpeed",
      " - radar relative speed",
      "8. Up to 4 menus can be displayed.",
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
