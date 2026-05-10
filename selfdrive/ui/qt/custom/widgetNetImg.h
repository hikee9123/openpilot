#include <string>
#include <vector>

#include <QButtonGroup>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QPainter>
#include <QPushButton>


#include <QWidget>
#include <QtWidgets>
#include <QtNetwork>


class NetworkImageWidget : public QWidget
{
    Q_OBJECT

public:
    explicit NetworkImageWidget(QWidget *parent = nullptr);

public slots:
    void requestImage(const QString &imageUrl);

private slots:
    void onImageDownloaded(QNetworkReply *reply);

private:
    QVBoxLayout *layout;
    QLabel *imageLabel;
    QNetworkAccessManager *networkManager;
    QString lastUrl;
};
