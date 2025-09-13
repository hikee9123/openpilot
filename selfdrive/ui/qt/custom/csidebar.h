#pragma once

#include <memory>

#include <QFrame>
#include <QMap>
#include <QDialog>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>

#include "selfdrive/ui/ui.h"



class DigSetup : public QDialog {
public:
    DigSetup(QWidget* parent = nullptr) : QDialog(parent) {
        setWindowTitle("Navigation");

        //QLabel* label = new QLabel("This is a modeless dialog.");
        closeButton = new QPushButton("Close");
        connect(closeButton, &QPushButton::clicked, this, &QDialog::close);

        QVBoxLayout* layout = new QVBoxLayout();
        //layout->addWidget(label);
        layout->addWidget(closeButton);


        setLayout(layout);

        resize( 1024, 768);
        setWindowOpacity(0.5);
        closeButton->move(10, 10);
        closeButton->resize(100, 50);
    }

   ~DigSetup() {
        delete closeButton;
    }

private:
    QPushButton* closeButton;    
};




class CSidebar  {
public:
  explicit CSidebar(QFrame* parent = 0);




public:
  void paintEvent(QPainter &p);
  int  updateState(const UIState &s);
  void mouseReleaseEvent(QMouseEvent *event, cereal::UserFlag::Builder &userFlag );

private:
  void   configFont(QPainter &p, const QString &family, int size, const QString &style);


private:
  QPixmap beterrry1_img, beterrry2_img;
  int    frame_cnt = 0;
  float  fBatteryVoltage = 0.;

  int    m_idxUserFlag = 0;
  

  const QRect battery_rc = QRect(160, 255, 78, 38);
};
