#pragma once

#include <map>
#include <string>

#include <QButtonGroup>
#include <QFrame>
#include <QLabel>
#include <QPushButton>
#include <QStackedWidget>
#include <QWidget>
#include <QTimer>

class QProcess;

#include <QJsonObject>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>

// tree
#include <QToolButton>
#include <QVBoxLayout>
#include <QPropertyAnimation>

#include "selfdrive/ui/qt/widgets/controls.h"

#include "selfdrive/ui/qt/widgets/input.h"
#include "selfdrive/ui/qt/widgets/scrollview.h"
#include "selfdrive/ui/qt/offroad/settings.h"

#include "selfdrive/ui/ui.h"




class CollapsibleSection : public QWidget {
  Q_OBJECT
public:
  explicit CollapsibleSection(const QString& title, QWidget* parent = nullptr);

  // 섹션 안에 위젯 추가
  void addWidget(QWidget* w);

  // 펼침/접힘 제어
  void setExpanded(bool on);
  bool isExpanded() const { return m_expanded; }

private:
  void toggle();

private:
  QToolButton*        m_headerBtn {nullptr};
  QFrame*             m_body      {nullptr};
  QVBoxLayout*        m_bodyLayout{nullptr};
  QPropertyAnimation* m_anim      {nullptr};
  bool                m_expanded  {true};
};


class JsonControl : public ToggleControl {
  Q_OBJECT

public:
  JsonControl(const QString &param, const QString &title, const QString &desc, const QString &icon, QWidget *parent, QJsonObject &jsonobj)
    : ToggleControl(title, desc, icon, false, parent),m_jsonobj(jsonobj) {
    key = param;
    QObject::connect(this, &JsonControl::toggleFlipped, [=](bool state) {
      QString content("<body><h2 style=\"text-align: center;\">" + title + "</h2><br>"
                      "<p style=\"text-align: center; margin: 0 128px; font-size: 50px;\">" + getDescription() + "</p></body>");
      ConfirmationDialog dialog(content, "Enable", "Cancel", true, this);

      bool confirmed = store_confirm;
      if (!confirm || confirmed || !state || dialog.exec()) {
        m_jsonobj.insert(key, state);
      } else {
        toggle.togglePosition();
      }
    });

  }

  void setConfirmation(bool _confirm, bool _store_confirm) {
    confirm = _confirm;
    store_confirm = _store_confirm;
  }



  void refresh() {
    if (m_jsonobj.contains(key)) {
      bool state =  m_jsonobj[key].toBool();
      if (state != toggle.on) {
        toggle.togglePosition();
      }
    }

  }

  void showEvent(QShowEvent *event) override {
    refresh();
  }

  void setEnabled(bool enabled)
  {
    ToggleControl::setEnabled(enabled);
    QFrame::setEnabled(  enabled );
  }

private:
  QString key;
  QJsonObject &m_jsonobj;
  bool confirm = false;
  bool store_confirm = false;
};


class CValueControl : public AbstractControl {
  Q_OBJECT
  Q_PROPERTY(int value READ getValue WRITE setValue NOTIFY valueChanged)

public:
  explicit CValueControl(const QString& param,
                         const QString& title,
                         const QString& desc,
                         const QString& icon,
                         int min, int max, int unit,
                         int defVal,                 // ★ 기본값 추가
                         QJsonObject& jsonobj,
                         QWidget* parent = nullptr);

  int  getValue() const noexcept;

public slots:
  void setValue(int value);
  void setRange(int min, int max);
  void setStep(int step);
  void setDefault(int defVal);      // ★ 기본값 런타임 교체

signals:
  void valueChanged(int newValue);
  void clicked();              // ★ DEPRECATED: 하위 호환용

private:
  void adjust(int delta);
  void updateLabel();
  void updateToolTip();
  int  loadInitial(bool& wroteBack) const noexcept;  // ★ 저장소 보정 여부 반환

private:
  QJsonObject& m_jsonobj;
  QString      m_key;

  int m_min  {0};
  int m_max  {0};
  int m_unit {1};
  int m_def  {0};                   // ★ 기본값 멤버
  int m_value{0};

  QLabel      m_label;
  QPushButton m_btnMinus;
  QPushButton m_btnPlus;
};


// ajouatom:
class CValueControl2 : public AbstractControl {
    Q_OBJECT

public:
    CValueControl2(const QString& key, const QString& title, const QString& desc, const QString& icon, int min, int max, int unit = 1);

private:
    QPushButton btnplus;
    QPushButton btnminus;
    QLabel label;
    Params params;

    QString m_key;
    int     m_min;
    int     m_max;
    int     m_unit;

    void refresh();
};


class MapboxToken : public AbstractControl {
  Q_OBJECT

public:
  MapboxToken() : AbstractControl("MapboxToken", "Put your MapboxToken", "")
  {
    btn.setStyleSheet(R"(
      padding: -10;
      border-radius: 35px;
      font-size: 35px;
      font-weight: 500;
      color: #E4E4E4;
      background-color: #393939;
    )");

    btn.setFixedSize(200, 100);
    //hlayout->addWidget(&edit);
    hlayout->addWidget(&btn);

    QObject::connect(&btn, &QPushButton::clicked, [=]() {
      QString targetvalue = InputDialog::getText("MapboxToken", this, "Put your MapboxToken starting with sk.", false, 1, QString::fromStdString(params.get("MapboxToken")));
      if (targetvalue.length() > 0 && targetvalue != QString::fromStdString(params.get("MapboxToken"))) {
        params.put("MapboxToken", targetvalue.toStdString());
        refresh();
      }
    });
    refresh();
  }

private:
  QPushButton btn;

  Params params;

  void refresh()
  {
    QString strMapboxToken = QString::fromStdString(params.get("MapboxToken"));

    if( strMapboxToken.length() )
    {
       setTitle( "Mapbox token" );
       setDescription( strMapboxToken );
       btn.setText("CHANGE");
    }
    else
    {
       setTitle( "input your Mapbox token" );
       setDescription( "Put your MapboxToken starting with sk." );
       btn.setText("SET");
    }


    //edit.setText(QString::fromStdString(strs.toStdString()));
    //QString  strToken = QString::fromStdString(strs.toStdString())
    //setTitle( strMapboxToken );
  }
};



class CustomPanel : public QWidget {
  Q_OBJECT
public:
  explicit CustomPanel(SettingsWindow *parent);

protected:
  void closeEvent(QCloseEvent *event) override;

protected:
  virtual void showEvent(QShowEvent *event) override;
  virtual void hideEvent(QHideEvent *event) override;

signals:


private slots:  // 시그널과 연결되어 특정 이벤트에 응답할 때
  void offroadTransition( bool offroad  );
  void OnTimer();

private:
  void  updateToggles( int bSave );

public:


private:
  QJsonObject m_jsonobj;
  QTimer *timer = nullptr;
  Params params;
  int    m_cmdIdx = 0;
  int    m_time = 0;


private:
  std::unique_ptr<PubMaster> pm;
  std::unique_ptr<SubMaster> sm;

public:
  int send(const char *name, MessageBuilder &msg);
  QStringList m_cars;

public:
   QJsonObject readJsonFile(const QString& fileName);
   void     writeJsonToFile(const QJsonObject& jsonObject, const QString& fileName);
   void     writeJson();
};




class CommunityTab : public ListWidget {
  Q_OBJECT
public:
  explicit CommunityTab(CustomPanel *parent, QJsonObject &jsonobj);


private:
  QMap<QString, CValueControl*> m_valueCtrl;


protected:
  virtual void showEvent(QShowEvent *event) override;
  virtual void hideEvent(QHideEvent *event) override;


protected:

signals:

private slots:

private:
  struct ValueDef {
    QString param;
    QString title;
    QString desc;
    QString icon;
    int min;
    int max;
    int unit;
    int def;
  };
  // 기본 아이콘 경로
  const QString kIcon = "../assets/offroad/icon_shell.png";

private:
  CustomPanel *m_pCustom = nullptr;
  QJsonObject &m_jsonobj;

};



class GitTab : public ListWidget {
  Q_OBJECT
public:
  explicit GitTab(CustomPanel *parent, QJsonObject &jsonobj);


private:
  std::map<std::string, CValueControl*> m_valueCtrl;


protected:
  virtual void showEvent(QShowEvent *event) override;
  virtual void hideEvent(QHideEvent *event) override;


protected:

signals:

private slots:

private:


private:
  CustomPanel *m_pCustom = nullptr;
  QJsonObject &m_jsonobj;

};



class ModelTab : public ListWidget {
  Q_OBJECT
public:
  explicit ModelTab(CustomPanel *parent, QJsonObject &jsonobj);


private:
  std::map<std::string, CValueControl*> m_valueCtrl;
  QString currentModel;
  ButtonControl *changeModelButton = nullptr;
  QProcess *modelProcess = nullptr;


protected:
  virtual void showEvent(QShowEvent *event) override;
  virtual void hideEvent(QHideEvent *event) override;


protected:

signals:

private slots:

private:


private:
  CustomPanel *m_pCustom = nullptr;
  QJsonObject &m_jsonobj;

};

class NavigationTab : public ListWidget {
  Q_OBJECT
public:
  explicit NavigationTab(CustomPanel *parent, QJsonObject &jsonobj);


private:
  std::map<std::string, ParamControl*> toggles;


protected:


protected:

signals:

private slots:



private:
  Params params;
  CustomPanel *m_pCustom = nullptr;
  QJsonObject &m_jsonobj;
};



class UITab : public ListWidget {
  Q_OBJECT
public:
  explicit UITab(CustomPanel *parent, QJsonObject &jsonobj);


private:
  std::map<std::string, JsonControl*> toggles;





  void updateToggles( int bSave );

protected:
  virtual void showEvent(QShowEvent *event) override;
  virtual void hideEvent(QHideEvent *event) override;


protected:
  void closeEvent(QCloseEvent *event) override;

private slots:
  //void offroadTransition( bool offroad  );

private:



private:
  CustomPanel *m_pCustom = nullptr;
  QJsonObject &m_jsonobj;
  int  m_cmdIdx = 0;
};



class Debug : public ListWidget {
  Q_OBJECT
public:
  explicit Debug(CustomPanel *parent, QJsonObject &jsonobj);


private:
  std::map<std::string, JsonControl*> toggles;
  QJsonObject &m_jsonobj;



  void updateToggles( int bSave );

protected:
  virtual void showEvent(QShowEvent *event) override;
  virtual void hideEvent(QHideEvent *event) override;


protected:
  void closeEvent(QCloseEvent *event) override;

signals:

private slots:
  //void offroadTransition( bool offroad  );

private:



private:
  CustomPanel *m_pCustom = nullptr;
  int  m_cmdIdx = 0;
};
