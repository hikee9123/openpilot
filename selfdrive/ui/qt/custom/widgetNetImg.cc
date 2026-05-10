#include "selfdrive/ui/qt/widgets/controls.h"

#include <QPainter>
#include <QStyleOption>


#include "selfdrive/ui/qt/custom/widgetNetImg.h"

NetworkImageWidget::NetworkImageWidget(QWidget *parent)
    : QWidget(parent)
{
    layout = new QVBoxLayout(this);
    imageLabel = new QLabel(this);
    networkManager = new QNetworkAccessManager(this);
    connect(networkManager, &QNetworkAccessManager::finished, this, &NetworkImageWidget::onImageDownloaded);

    layout->addWidget(imageLabel);
}

void NetworkImageWidget::requestImage(const QString &imageUrl)
{
    if(imageUrl == lastUrl) return;
    lastUrl = imageUrl;
    QNetworkRequest request(imageUrl);
    networkManager->get(request);
}

void NetworkImageWidget::onImageDownloaded(QNetworkReply *reply)
{
    if (reply->error() == QNetworkReply::NoError) {
        QByteArray imageData = reply->readAll();
        QImage image = QImage::fromData(imageData);
        if (!image.isNull()) {
            QPixmap pixmap = QPixmap::fromImage(image);
            imageLabel->setPixmap(pixmap.scaledToWidth(200, Qt::SmoothTransformation));
        }
    }

    reply->deleteLater();
}
