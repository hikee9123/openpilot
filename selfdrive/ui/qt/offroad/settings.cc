#include <algorithm>
#include <cassert>
#include <cmath>
#include <exception>
#include <functional>
#include <iterator>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include <QDebug>
#include <QDateTime>
#include <QDialog>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTimer>
#include <QVBoxLayout>

#include "common/watchdog.h"
#include "common/util.h"
#include "selfdrive/ui/qt/network/networking.h"
#include "selfdrive/ui/qt/offroad/settings.h"
#include "selfdrive/ui/qt/qt_window.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "selfdrive/ui/qt/widgets/prime.h"
#include "selfdrive/ui/qt/widgets/scrollview.h"
#include "selfdrive/ui/qt/widgets/swipeable_tab.h"
#include "selfdrive/ui/qt/offroad/developer_panel.h"
#include "selfdrive/ui/qt/offroad/firehose.h"

#include "selfdrive/ui/qt/custom/custom.h"   // #custom

namespace {

constexpr int kBlinkCloseDefault = 87;
constexpr int kBlinkOpenDefault = 50;
constexpr int kBlinkThresholdMin = 5;
constexpr int kBlinkThresholdHysteresis = 5;
constexpr int kBlinkMinDurationDefault = 100;
constexpr int kBlinkMaxDurationDefault = 1500;
constexpr int kSleepCandidateDurationDefault = 10000;
constexpr int kBlinkMinValidDefault = 80;
constexpr int kBlinkAutoApplyMinConfidence = 80;
constexpr int kBlinkAutoApplyMinNewValidSamples = 5 * 60 * 20;
constexpr int kBlinkAutoTuneSensitivityDefault = 2;
constexpr int kBlinkAutoTuneSensitivityOffsets[] = {-10, -5, 0, 5, 10};

int getIntParam(Params &params, const std::string &key, int default_value) {
  try {
    const std::string value = params.get(key);
    return value.empty() ? default_value : std::stoi(value);
  } catch (const std::exception &) {
    return default_value;
  }
}

int maximumOpenThreshold(int close_threshold) {
  return std::max(kBlinkThresholdMin, close_threshold - kBlinkThresholdHysteresis);
}

int minimumMaxBlinkDuration(int min_duration_ms) {
  return std::max(500, (min_duration_ms / 100 + 1) * 100);
}

int minimumSleepCandidateDuration(int max_blink_duration_ms) {
  return std::max(2000, (max_blink_duration_ms / 1000 + 1) * 1000);
}

int blinkAutoTuneSensitivityLevel(int level) {
  return std::clamp(level, 0, static_cast<int>(std::size(kBlinkAutoTuneSensitivityOffsets)) - 1);
}

int blinkAutoTuneSensitivityOffset(int level) {
  return kBlinkAutoTuneSensitivityOffsets[blinkAutoTuneSensitivityLevel(level)];
}

bool blinkAutoTuneProfileMayAutoApply(int level) {
  level = blinkAutoTuneSensitivityLevel(level);
  return 1 <= level && level <= 3;
}

QString blinkAutoTuneSensitivityName(int level) {
  switch (blinkAutoTuneSensitivityLevel(level)) {
    case 0: return QObject::tr("Very sensitive");
    case 1: return QObject::tr("Sensitive");
    case 3: return QObject::tr("Dull");
    case 4: return QObject::tr("Very dull");
    default: return QObject::tr("Normal");
  }
}

struct BlinkAutoTuneState {
  bool ready = false;
  bool stable = false;
  bool auto_apply_eligible = false;
  int confidence_pct = 0;
  int coverage_pct = 0;
  int valid_percent = 0;
  int closure_count = 0;
  int stable_bucket_count = 0;
  int required_stable_buckets = 3;
  int data_epoch = 0;
  double valid_minutes = 0.0;
  int valid_sample_count = 0;
  qint64 last_updated = 0;
  qint64 last_applied = 0;
  int last_applied_valid_sample_count = 0;
  int last_applied_data_epoch = -1;
  int last_applied_confidence_pct = 0;
  QString recommendation_mode = "unavailable";
  int close_threshold_pct = kBlinkCloseDefault;
  int open_threshold_pct = kBlinkOpenDefault;
  int min_duration_ms = kBlinkMinDurationDefault;
  int max_blink_duration_ms = kBlinkMaxDurationDefault;
  int sleep_candidate_duration_ms = kSleepCandidateDurationDefault;
  int min_valid_pct = kBlinkMinValidDefault;
};

BlinkAutoTuneState getBlinkAutoTuneState(Params &params) {
  BlinkAutoTuneState state;
  state.close_threshold_pct = getIntParam(params, "DmBlinkCloseThresholdPct", kBlinkCloseDefault);
  state.open_threshold_pct = getIntParam(params, "DmBlinkOpenThresholdPct", kBlinkOpenDefault);
  state.min_duration_ms = getIntParam(params, "DmBlinkMinDurationMs", kBlinkMinDurationDefault);
  state.max_blink_duration_ms = getIntParam(params, "DmBlinkMaxDurationMs", kBlinkMaxDurationDefault);
  state.sleep_candidate_duration_ms = getIntParam(params, "DmSleepCandidateDurationMs", kSleepCandidateDurationDefault);
  state.min_valid_pct = getIntParam(params, "DmBlinkMinValidPct", kBlinkMinValidDefault);

  const std::string raw_applied = params.get("DmBlinkAutoTuneLastApplied");
  if (!raw_applied.empty()) {
    QJsonParseError applied_error;
    const QJsonDocument applied_document = QJsonDocument::fromJson(QByteArray::fromStdString(raw_applied), &applied_error);
    if (applied_error.error == QJsonParseError::NoError && applied_document.isObject()) {
      const QJsonObject applied_root = applied_document.object();
      state.last_applied = std::max(static_cast<qint64>(applied_root.value("appliedAt").toDouble(0.0)), qint64{0});
      state.last_applied_valid_sample_count = std::max(applied_root.value("sourceValidSampleCount").toInt(0), 0);
      state.last_applied_data_epoch = applied_root.value("sourceDataEpoch").toInt(-1);
      state.last_applied_confidence_pct = std::clamp(applied_root.value("confidencePct").toInt(0), 0, 100);
    } else {
      qWarning() << "Failed to parse DmBlinkAutoTuneLastApplied:" << applied_error.errorString();
    }
  }

  const std::string raw_state = params.get("DmBlinkAutoTuneState");
  if (raw_state.empty()) {
    return state;
  }

  QJsonParseError error;
  const QJsonDocument document = QJsonDocument::fromJson(QByteArray::fromStdString(raw_state), &error);
  if (error.error != QJsonParseError::NoError || !document.isObject()) {
    qWarning() << "Failed to parse DmBlinkAutoTuneState:" << error.errorString();
    return state;
  }

  const QJsonObject root = document.object();
  if (root.value("version").toInt(0) != 2) {
    return state;
  }
  const QJsonObject recommendations = root.value("recommendations").toObject();
  const QJsonObject quality = root.value("quality").toObject();
  state.ready = root.value("ready").toBool(false) && !recommendations.isEmpty();
  state.stable = quality.value("stable").toBool(false);
  state.auto_apply_eligible = root.value("autoApplyEligible").toBool(false);
  state.confidence_pct = std::clamp(root.value("confidencePct").toInt(0), 0, 100);
  state.coverage_pct = std::clamp(root.value("coveragePct").toInt(0), 0, 100);
  state.recommendation_mode = root.value("recommendationMode").toString("unavailable");
  state.valid_percent = std::clamp(root.value("validPercent").toInt(0), 0, 100);
  state.closure_count = std::max(root.value("closureCount").toInt(0), 0);
  state.valid_minutes = std::max(root.value("validMinutes").toDouble(0.0), 0.0);
  state.valid_sample_count = std::max(root.value("epochValidSampleCount").toInt(root.value("validSampleCount").toInt(0)), 0);
  state.stable_bucket_count = std::max(quality.value("stableBucketCount").toInt(0), 0);
  state.required_stable_buckets = std::max(quality.value("requiredStableBuckets").toInt(3), 1);
  state.data_epoch = std::max(root.value("dataEpoch").toInt(0), 0);
  state.last_updated = std::max(static_cast<qint64>(root.value("lastUpdated").toDouble(0.0)), qint64{0});
  state.close_threshold_pct = recommendations.value("closeThresholdPct").toInt(state.close_threshold_pct);
  state.open_threshold_pct = recommendations.value("openThresholdPct").toInt(state.open_threshold_pct);
  state.min_duration_ms = recommendations.value("minDurationMs").toInt(state.min_duration_ms);
  state.max_blink_duration_ms = recommendations.value("maxBlinkDurationMs").toInt(state.max_blink_duration_ms);
  state.sleep_candidate_duration_ms = recommendations.value("sleepCandidateDurationMs").toInt(state.sleep_candidate_duration_ms);
  state.min_valid_pct = recommendations.value("minValidPct").toInt(state.min_valid_pct);
  state.close_threshold_pct = std::clamp(state.close_threshold_pct, kBlinkThresholdMin, 95);
  state.open_threshold_pct = std::clamp(state.open_threshold_pct, kBlinkThresholdMin,
                                        maximumOpenThreshold(state.close_threshold_pct));
  state.min_duration_ms = std::clamp(state.min_duration_ms, 50, 500);
  state.max_blink_duration_ms = std::clamp(state.max_blink_duration_ms,
                                           minimumMaxBlinkDuration(state.min_duration_ms), 3000);
  state.sleep_candidate_duration_ms = std::clamp(state.sleep_candidate_duration_ms,
                                                  minimumSleepCandidateDuration(state.max_blink_duration_ms), 30000);
  state.min_valid_pct = std::clamp(state.min_valid_pct, 50, 100);
  return state;
}

enum class TouchValueFormat {
  PERCENT,
  MILLISECONDS,
  SECONDS,
};

class StagedToggleControl : public ToggleControl {
public:
  StagedToggleControl(const QString &title, const QString &description, bool state, QWidget *parent)
      : ToggleControl(title, description, "", state, parent) {}

  bool value() const {
    return toggle.on;
  }

  void setValue(bool state) {
    if (state != toggle.on) {
      toggle.togglePosition();
    }
  }
};

class StagedButtonControl : public MultiButtonControl {
public:
  StagedButtonControl(const QString &title, const QString &description,
                      const std::vector<QString> &button_texts, int value, int button_width = 330)
      : MultiButtonControl(title, description, "", button_texts, button_width) {
    setValue(value);
  }

  int value() const {
    return button_group->checkedId();
  }

  void setValue(int value) {
    const int max_index = static_cast<int>(button_group->buttons().size()) - 1;
    setCheckedButton(std::clamp(value, 0, max_index));
  }
};

class TouchValueControl : public AbstractControl {
public:
  TouchValueControl(const QString &title, const QString &description, int minimum, int maximum,
                    int step, int value, TouchValueFormat format, QWidget *parent)
      : AbstractControl(title, description, "", parent), minimum_(minimum), maximum_(maximum),
        step_(step), value_(std::clamp(value, minimum, maximum)), format_(format) {
    title_label->setStyleSheet("font-size: 48px; font-weight: 400; text-align: left; border: none;");

    const QString button_style = R"(
      QPushButton {
        min-width: 0; min-height: 0; padding: 0;
        border: 0; border-radius: 45px;
        background-color: #393939; color: white;
        font-size: 60px; font-weight: 500;
      }
      QPushButton:pressed { background-color: #4a4a4a; }
      QPushButton:disabled { color: #666666; background-color: #242424; }
    )";
    minus_button.setText("-");
    plus_button.setText("+");
    for (QPushButton *button : {&minus_button, &plus_button}) {
      button->setFixedSize(300, 100);
      button->setStyleSheet(button_style);
      button->setAutoRepeat(true);
      button->setAutoRepeatDelay(500);
      button->setAutoRepeatInterval(120);
    }

    value_label.setFixedSize(240, 100);
    value_label.setAlignment(Qt::AlignCenter);
    value_label.setStyleSheet(R"(
      QLabel {
        border: 2px solid #414850; border-radius: 18px;
        background-color: #252a30; color: white;
        font-size: 42px; font-weight: 500;
      }
    )");

    auto_value_label.setFixedSize(280, 100);
    auto_value_label.setAlignment(Qt::AlignCenter);
    auto_value_label.setStyleSheet(R"(
      QLabel {
        border: 2px solid #414850; border-radius: 18px;
        background-color: #1f2522; color: #8de6aa;
        font-size: 34px; font-weight: 500;
      }
    )");

    use_auto_button.setText(tr("USE"));
    use_auto_button.setFixedSize(160, 100);
    use_auto_button.setStyleSheet(R"(
      QPushButton {
        min-width: 0; min-height: 0; padding: 0;
        border: 0; border-radius: 45px;
        background-color: #2d7040; color: white;
        font-size: 34px; font-weight: 600;
      }
      QPushButton:pressed { background-color: #388c50; }
      QPushButton:disabled { color: #666666; background-color: #242424; }
    )");

    hlayout->addWidget(&minus_button);
    hlayout->addWidget(&value_label);
    hlayout->addWidget(&plus_button);
    hlayout->addWidget(&auto_value_label);
    hlayout->addWidget(&use_auto_button);

    QObject::connect(&minus_button, &QPushButton::clicked, [this]() { setValue(value_ - step_); });
    QObject::connect(&plus_button, &QPushButton::clicked, [this]() { setValue(value_ + step_); });
    QObject::connect(&use_auto_button, &QPushButton::clicked, [this]() {
      if (auto_value_available_) setValue(auto_value_);
    });
    refresh();
    refreshAutoValue();
  }

  int value() const {
    return value_;
  }

  void setValue(int value) {
    const int clamped = std::clamp(value, minimum_, maximum_);
    if (clamped == value_) {
      refresh();
      return;
    }
    value_ = clamped;
    refresh();
    if (value_changed_callback_) {
      value_changed_callback_(value_);
    }
  }

  void setMinimum(int minimum) {
    minimum_ = std::min(minimum, maximum_);
    setValue(value_);
    refreshAutoValue();
  }

  void setMaximum(int maximum) {
    maximum_ = std::max(maximum, minimum_);
    setValue(value_);
    refreshAutoValue();
  }

  void setValueChangedCallback(std::function<void(int)> callback) {
    value_changed_callback_ = std::move(callback);
  }

  void setAutoValue(int value, bool available, int confidence_pct) {
    auto_value_ = value;
    auto_value_available_ = available;
    auto_confidence_pct_ = std::clamp(confidence_pct, 0, 100);
    refreshAutoValue();
  }

  void useAutoValue() {
    if (auto_value_available_) setValue(auto_value_);
  }

private:
  QString formattedValue(int value) const {
    switch (format_) {
      case TouchValueFormat::PERCENT:
        return QString("%1%").arg(value);
      case TouchValueFormat::MILLISECONDS:
        return QString("%1 ms").arg(value);
      case TouchValueFormat::SECONDS:
        return QString("%1 s").arg(value / 1000.0, 0, 'f', 1);
    }
    return QString::number(value);
  }

  void refresh() {
    value_label.setText(tr("CUR %1").arg(formattedValue(value_)));
    minus_button.setEnabled(value_ > minimum_);
    plus_button.setEnabled(value_ < maximum_);
  }

  void refreshAutoValue() {
    auto_value_label.setText(auto_value_available_ ?
      tr("AUTO %1\n%2%").arg(formattedValue(auto_value_)).arg(auto_confidence_pct_) : tr("AUTO --"));
    const bool value_in_range = auto_value_ >= minimum_ && auto_value_ <= maximum_;
    use_auto_button.setEnabled(auto_value_available_ && value_in_range);
    use_auto_button.setToolTip(auto_value_available_ && !value_in_range ?
      tr("Apply the related recommendation first, or use all recommendations.") : QString());
  }

  int minimum_;
  int maximum_;
  int step_;
  int value_;
  int auto_value_ = 0;
  int auto_confidence_pct_ = 0;
  bool auto_value_available_ = false;
  TouchValueFormat format_;
  std::function<void(int)> value_changed_callback_;
  QPushButton minus_button;
  QPushButton plus_button;
  QLabel value_label;
  QLabel auto_value_label;
  QPushButton use_auto_button;
};

class BlinkDebugSettingsDialog : public DialogBase {
public:
  explicit BlinkDebugSettingsDialog(QWidget *parent) : DialogBase(parent) {
    setWindowTitle(tr("Driver Monitoring Blink Debug"));
    setModal(true);
    auto_tune_state = getBlinkAutoTuneState(params);
    setStyleSheet(R"(
      QDialog { background-color: #101214; color: white; }
      QLabel { color: white; }
      QTabWidget::pane { border: 0; background-color: transparent; }
      QPushButton#dialogButton, QPushButton#applyButton {
        min-width: 270px; min-height: 100px; padding: 0 32px;
        border: 0; border-radius: 50px;
        background-color: #393939; color: white; font-size: 44px;
      }
      QPushButton#applyButton { background-color: #00c853; color: #07170d; font-weight: 600; }
    )");

    auto *main_layout = new QVBoxLayout(this);
    main_layout->setContentsMargins(55, 35, 55, 35);
    main_layout->setSpacing(16);

    auto *title = new QLabel(tr("Driver Monitoring Blink Debug"), this);
    title->setStyleSheet("font-size: 60px; font-weight: 600;");
    main_layout->addWidget(title);

    auto *notice = new QLabel(
      tr("NO BLINK 10s replaces the instantaneous eye-blink warning with a full 10-second valid observation. Pose, phone, and no-face warnings remain active."), this);
    notice->setWordWrap(true);
    notice->setStyleSheet("font-size: 38px; color: #e8bd64; padding-bottom: 8px;");
    main_layout->addWidget(notice);

    auto *swipe_hint = new QLabel(tr("Swipe the tabs left or right to change the settings page."), this);
    swipe_hint->setStyleSheet("font-size: 34px; color: #aeb5bc; padding-bottom: 4px;");
    main_layout->addWidget(swipe_hint);

    auto *tab_widget = new SwipeableTabWidget(this);
    tab_widget->setStyleSheet(kSwipeableTabStyle);

    auto *display_layout = createPage(tab_widget, tr("Display & Alert"));
    debug_enabled = new StagedToggleControl(
      tr("Show blink debug overlay"),
      tr("Show or hide the 10-second blink and eye-closure diagnostics while driving. This display setting does not change warning behavior."),
      params.getBool("DmBlinkDebugOverlayEnabled"), display_layout->parentWidget());
    display_layout->addWidget(debug_enabled);

    alert_mode = new StagedButtonControl(
      tr("Candidate warning link"),
      tr("OFF leaves No-blink and Sleep candidates as diagnostics only. ON immediately adds either candidate to the existing distraction warning. Existing eye, pose, phone, and no-face warnings remain active."),
      {tr("OFF (DEBUG)"), tr("ON (WARNING)")},
      params.getBool("DmBlinkAlertEnabled") ? 1 : 0);
    display_layout->addWidget(alert_mode);

    dismiss_on_driver_input = new StagedToggleControl(
      tr("Dismiss linked warning on driver input"),
      tr("A new steering, accelerator, or brake input clears level 1/2 linked eye warnings. CANCEL resets all warning levels, including emergency, and restarts the 10-second observation."),
      params.getBool("DmBlinkDismissOnDriverInput"), display_layout->parentWidget());
    display_layout->addWidget(dismiss_on_driver_input);
    display_layout->addStretch();

    auto *eye_layout = createPage(tab_widget, tr("Eye Closure"));
    close_threshold = addTouchValue(eye_layout, tr("Close threshold"),
                                    tr("Start a closed-eye segment at or above this probability."),
                                    kBlinkThresholdMin, 95, 1, getIntParam(params, "DmBlinkCloseThresholdPct", kBlinkCloseDefault),
                                    TouchValueFormat::PERCENT);
    open_threshold = addTouchValue(eye_layout, tr("Open threshold"),
                                   tr("Finish the segment below Close, using a 5% gap whenever the selected range allows."),
                                   kBlinkThresholdMin, maximumOpenThreshold(close_threshold->value()), 1,
                                   getIntParam(params, "DmBlinkOpenThresholdPct", kBlinkOpenDefault),
                                   TouchValueFormat::PERCENT);
    eye_layout->addStretch();

    auto *blink_layout = createPage(tab_widget, tr("Blink & Sleep"));
    min_duration = addTouchValue(blink_layout, tr("Minimum blink"),
                                 tr("Ignore shorter probability spikes."),
                                 50, 500, 50, getIntParam(params, "DmBlinkMinDurationMs", kBlinkMinDurationDefault),
                                 TouchValueFormat::MILLISECONDS);
    max_blink_duration = addTouchValue(blink_layout, tr("Maximum blink"),
                                       tr("Count only closures up to this duration as a normal blink."),
                                       500, 3000, 100, getIntParam(params, "DmBlinkMaxDurationMs", kBlinkMaxDurationDefault),
                                       TouchValueFormat::SECONDS);
    sleep_candidate_duration = addTouchValue(blink_layout, tr("Sleep Candidate"),
                                              tr("Set Sleep Candidate after this continuous valid eye closure."),
                                              2000, 30000, 1000,
                                              getIntParam(params, "DmSleepCandidateDurationMs", kSleepCandidateDurationDefault),
                                              TouchValueFormat::SECONDS);
    min_valid = addTouchValue(blink_layout, tr("Minimum valid data"),
                              tr("Required valid samples in the fixed 10-second window."),
                              50, 100, 5, getIntParam(params, "DmBlinkMinValidPct", kBlinkMinValidDefault),
                              TouchValueFormat::PERCENT);

    close_threshold->setValueChangedCallback([this](int value) {
      open_threshold->setMaximum(maximumOpenThreshold(value));
    });
    min_duration->setValueChangedCallback([this](int value) {
      max_blink_duration->setMinimum(minimumMaxBlinkDuration(value));
    });
    max_blink_duration->setValueChangedCallback([this](int value) {
      sleep_candidate_duration->setMinimum(minimumSleepCandidateDuration(value));
    });
    max_blink_duration->setMinimum(minimumMaxBlinkDuration(min_duration->value()));
    sleep_candidate_duration->setMinimum(minimumSleepCandidateDuration(max_blink_duration->value()));

    auto *window_note = new QLabel(
      tr("No-blink uses a fixed 10-second window. Sleep Candidate uses the adjustable continuous closure time and ignores closures of 2 seconds or less. Changes apply on the next DM start."),
      blink_layout->parentWidget());
    window_note->setWordWrap(true);
    window_note->setStyleSheet("font-size: 38px; color: #aeb5bc; padding: 18px 8px;");
    blink_layout->addWidget(window_note);
    blink_layout->addStretch();

    auto *auto_tune_layout = createPage(tab_widget, tr("Auto Tune"));
    auto_tune_enabled = new StagedToggleControl(
      tr("Enable Auto Tune"),
      tr("Collect numeric driver-monitoring data while openpilot is enabled above 10 km/h and calculate recommendations. "
         "Learning runs during the drive; active DM values do not change during that drive."),
      params.getBool("DmBlinkAutoTuneEnabled"), auto_tune_layout->parentWidget());
    auto_tune_layout->addWidget(auto_tune_enabled);

    auto_tune_sensitivity = new StagedButtonControl(
      tr("Eye-closure sensitivity"),
      tr("Shift the learned Close/Open recommendation without changing Minimum blink, valid-data, Maximum blink, or Sleep Candidate. "
         "This controls eye-closure detection only, not overall warning frequency."),
      {tr("VERY SENSITIVE"), tr("SENSITIVE"), tr("NORMAL"), tr("DULL"), tr("VERY DULL")},
      getIntParam(params, "DmBlinkAutoTuneSensitivityLevel", kBlinkAutoTuneSensitivityDefault), 230);
    auto_tune_layout->addWidget(auto_tune_sensitivity);

    auto_apply_next_drive = new StagedToggleControl(
      tr("Auto apply on next drive"),
      tr("Apply a bounded recommendation only at the next DM start when recent cluster data is stable and confidence is at least 80%. "
         "Very sensitive and Very dull require manual review. Maximum blink and Sleep Candidate remain manual."),
      params.getBool("DmBlinkAutoTuneAutoApply"), auto_tune_layout->parentWidget());
    auto_tune_layout->addWidget(auto_apply_next_drive);

    auto_tune_status = new QLabel(auto_tune_layout->parentWidget());
    auto_tune_status->setWordWrap(true);
    auto_tune_status->setStyleSheet(
      "font-size: 42px; color: white; padding: 24px; background-color: #20262b; border-radius: 20px;");
    auto_tune_layout->addWidget(auto_tune_status);

    auto *auto_tune_note = new QLabel(
      tr("Recommendations use the most recent approximately 30 valid driving minutes. Manual recommendations appear after 10 minutes and 10 eye closures. "
         "Auto apply additionally requires three stable 5-minute cluster periods. Percentile fallback is manual review only. "
         "Maximum blink and Sleep Candidate remain manual."),
      auto_tune_layout->parentWidget());
    auto_tune_note->setWordWrap(true);
    auto_tune_note->setStyleSheet("font-size: 36px; color: #aeb5bc; padding: 16px 8px;");
    auto_tune_layout->addWidget(auto_tune_note);

    auto *auto_button_layout = new QHBoxLayout();
    auto_button_layout->setSpacing(24);
    apply_all_auto_button = new QPushButton(tr("Use tunable recommendations"), auto_tune_layout->parentWidget());
    reset_auto_data_button = new QPushButton(tr("Reset learned data"), auto_tune_layout->parentWidget());
    apply_all_auto_button->setObjectName("dialogButton");
    reset_auto_data_button->setObjectName("dialogButton");
    auto_button_layout->addWidget(apply_all_auto_button);
    auto_button_layout->addWidget(reset_auto_data_button);
    auto_button_layout->addStretch();
    auto_tune_layout->addLayout(auto_button_layout);
    auto_tune_layout->addStretch();

    refreshAutoTuneUi();

    main_layout->addWidget(tab_widget, 1);

    auto *button_layout = new QHBoxLayout();
    button_layout->setSpacing(18);
    auto *reset_button = new QPushButton(tr("Reset defaults"), this);
    auto *cancel_button = new QPushButton(tr("Cancel"), this);
    auto *apply_button = new QPushButton(tr("Apply"), this);
    reset_button->setObjectName("dialogButton");
    cancel_button->setObjectName("dialogButton");
    apply_button->setObjectName("applyButton");
    button_layout->addWidget(reset_button);
    button_layout->addStretch();
    button_layout->addWidget(cancel_button);
    button_layout->addWidget(apply_button);
    main_layout->addLayout(button_layout);

    QObject::connect(reset_button, &QPushButton::clicked, [this]() { setDefaults(); });
    QObject::connect(cancel_button, &QPushButton::clicked, this, &QDialog::reject);
    QObject::connect(auto_tune_enabled, &ToggleControl::toggleFlipped, [this](bool enabled) {
      if (!enabled) auto_apply_next_drive->setValue(false);
      refreshAutoTuneUi();
    });
    QObject::connect(auto_tune_sensitivity, &MultiButtonControl::buttonClicked, [this](int) { refreshAutoTuneUi(); });
    QObject::connect(auto_apply_next_drive, &ToggleControl::toggleFlipped, [this](bool) { refreshAutoTuneUi(); });
    QObject::connect(apply_all_auto_button, &QPushButton::clicked, [this]() { useAllAutoRecommendations(); });
    QObject::connect(reset_auto_data_button, &QPushButton::clicked, [this]() {
      if (ConfirmationDialog::confirm(tr("Reset all learned Blink Auto Tune data?"), tr("Reset"), this)) {
        const int reset_generation = std::max(getIntParam(params, "DmBlinkAutoTuneResetGeneration", 0), 0);
        params.put("DmBlinkAutoTuneResetGeneration", std::to_string(reset_generation >= 1000000000 ? 1 : reset_generation + 1));
        params.remove("DmBlinkAutoTuneState");
        params.remove("DmBlinkAutoTuneLastApplied");
        params.remove("DmBlinkAutoTunePendingApply");
        auto_tune_state = getBlinkAutoTuneState(params);
        refreshAutoTuneUi();
      }
    });
    QObject::connect(apply_button, &QPushButton::clicked, [this]() {
      if (save()) accept();
    });

    auto *auto_tune_refresh_timer = new QTimer(this);
    QObject::connect(auto_tune_refresh_timer, &QTimer::timeout, [this]() {
      auto_tune_state = getBlinkAutoTuneState(params);
      refreshAutoTuneUi();
    });
    auto_tune_refresh_timer->start(2000);
  }

private:
  QVBoxLayout *createPage(SwipeableTabWidget *tabs, const QString &name) {
    auto *page = new QWidget(tabs);
    auto *layout = new QVBoxLayout(page);
    layout->setContentsMargins(12, 16, 24, 20);
    layout->setSpacing(14);
    tabs->addTab(new ScrollView(page, tabs), name);
    return layout;
  }

  TouchValueControl *addTouchValue(QVBoxLayout *layout, const QString &title, const QString &description,
                                   int minimum, int maximum, int step, int value, TouchValueFormat format) {
    auto *control = new TouchValueControl(title, description, minimum, maximum, step, value, format, layout->parentWidget());
    layout->addWidget(control);
    return control;
  }

  void refreshAutoTuneUi() {
    const bool ready = auto_tune_state.ready;
    const int sensitivity_level = blinkAutoTuneSensitivityLevel(auto_tune_sensitivity->value());
    const int sensitivity_offset = blinkAutoTuneSensitivityOffset(sensitivity_level);
    const int profile_close_threshold = std::clamp(auto_tune_state.close_threshold_pct + sensitivity_offset, 50, 95);
    const int profile_open_threshold = std::clamp(auto_tune_state.open_threshold_pct + sensitivity_offset,
                                                  kBlinkThresholdMin,
                                                  maximumOpenThreshold(profile_close_threshold));
    auto_apply_next_drive->setEnabled(auto_tune_enabled->value());
    close_threshold->setAutoValue(profile_close_threshold, ready, auto_tune_state.confidence_pct);
    open_threshold->setAutoValue(profile_open_threshold, ready, auto_tune_state.confidence_pct);
    min_duration->setAutoValue(auto_tune_state.min_duration_ms, ready, auto_tune_state.confidence_pct);
    max_blink_duration->setAutoValue(auto_tune_state.max_blink_duration_ms, ready, auto_tune_state.confidence_pct);
    sleep_candidate_duration->setAutoValue(auto_tune_state.sleep_candidate_duration_ms, ready,
                                           auto_tune_state.confidence_pct);
    min_valid->setAutoValue(auto_tune_state.min_valid_pct, ready, auto_tune_state.confidence_pct);
    apply_all_auto_button->setEnabled(ready);

    QString status;
    if (!auto_tune_enabled->value()) {
      status = tr("AUTO TUNE OFF - Learned recommendations are preserved.");
    } else if (!ready) {
      status = tr("LEARNING - More valid driving data is required.");
    } else {
      status = tr("READY - Review the AUTO values beside each current value before applying.");
    }

    QString auto_apply_status;
    if (!auto_tune_enabled->value() || !auto_apply_next_drive->value()) {
      auto_apply_status = tr("NEXT-DRIVE AUTO APPLY OFF");
    } else if (!ready) {
      auto_apply_status = tr("NEXT-DRIVE AUTO APPLY WAITING - Requires 10 valid minutes and 10 eye closures.");
    } else if (!blinkAutoTuneProfileMayAutoApply(sensitivity_level)) {
      auto_apply_status = tr("NEXT-DRIVE AUTO APPLY WAITING - Extreme sensitivity profiles require manual review.");
    } else if (auto_tune_state.recommendation_mode == "percentiles") {
      auto_apply_status = tr("NEXT-DRIVE AUTO APPLY WAITING - Percentile fallback requires manual review.");
    } else if (!auto_tune_state.stable) {
      auto_apply_status = tr("NEXT-DRIVE AUTO APPLY WAITING - Requires three stable 5-minute cluster periods.");
    } else if (!auto_tune_state.auto_apply_eligible || auto_tune_state.confidence_pct < kBlinkAutoApplyMinConfidence) {
      auto_apply_status = tr("NEXT-DRIVE AUTO APPLY WAITING - Requires 80% stable confidence.");
    } else if (auto_tune_state.last_applied_valid_sample_count > 0 &&
               auto_tune_state.last_applied_data_epoch == auto_tune_state.data_epoch &&
               auto_tune_state.valid_sample_count - auto_tune_state.last_applied_valid_sample_count <
                 kBlinkAutoApplyMinNewValidSamples) {
      auto_apply_status = tr("NEXT-DRIVE AUTO APPLY WAITING - Requires 5 new valid driving minutes.");
    } else {
      auto_apply_status = tr("NEXT-DRIVE AUTO APPLY READY - A bounded step will apply at the next DM start.");
    }

    QString updated = tr("Never");
    if (auto_tune_state.last_updated > 0) {
      updated = QDateTime::fromSecsSinceEpoch(auto_tune_state.last_updated).toString("yyyy-MM-dd HH:mm");
    }
    QString applied = tr("Never");
    if (auto_tune_state.last_applied > 0) {
      applied = tr("%1 (%2% confidence)")
                  .arg(QDateTime::fromSecsSinceEpoch(auto_tune_state.last_applied).toString("yyyy-MM-dd HH:mm"))
                  .arg(auto_tune_state.last_applied_confidence_pct);
    }
    QString mode = tr("Unavailable");
    if (auto_tune_state.recommendation_mode == "clusters") {
      mode = tr("Clusters");
    } else if (auto_tune_state.recommendation_mode == "percentiles") {
      mode = tr("Percentile fallback");
    }
    const QString profile = tr("%1 | Base C%2/%3 -> Profile C%4/%5")
                              .arg(blinkAutoTuneSensitivityName(sensitivity_level))
                              .arg(auto_tune_state.close_threshold_pct)
                              .arg(auto_tune_state.open_threshold_pct)
                              .arg(profile_close_threshold)
                              .arg(profile_open_threshold);
    auto_tune_status->setText(
      tr("%1\n%2\nProfile: %3\nRecent valid: %4 min | Valid data: %5% | Closures: %6 | Coverage: %7% | Stable confidence: %8%\nRecent periods: %9/%10 | Mode: %11\nLast update: %12 | Last auto apply: %13")
        .arg(status)
        .arg(auto_apply_status)
        .arg(profile)
        .arg(auto_tune_state.valid_minutes, 0, 'f', 1)
        .arg(auto_tune_state.valid_percent)
        .arg(auto_tune_state.closure_count)
        .arg(auto_tune_state.coverage_pct)
        .arg(auto_tune_state.confidence_pct)
        .arg(auto_tune_state.stable_bucket_count)
        .arg(auto_tune_state.required_stable_buckets)
        .arg(mode)
        .arg(updated)
        .arg(applied));
  }

  void useAllAutoRecommendations() {
    if (!auto_tune_state.ready) return;
    close_threshold->useAutoValue();
    open_threshold->useAutoValue();
    min_duration->useAutoValue();
    min_valid->useAutoValue();
  }

  void setDefaults() {
    debug_enabled->setValue(false);
    alert_mode->setValue(0);
    dismiss_on_driver_input->setValue(true);
    auto_tune_enabled->setValue(false);
    auto_apply_next_drive->setValue(false);
    auto_tune_sensitivity->setValue(kBlinkAutoTuneSensitivityDefault);
    close_threshold->setValue(kBlinkCloseDefault);
    open_threshold->setValue(kBlinkOpenDefault);
    min_duration->setValue(kBlinkMinDurationDefault);
    max_blink_duration->setValue(kBlinkMaxDurationDefault);
    sleep_candidate_duration->setValue(kSleepCandidateDurationDefault);
    min_valid->setValue(kBlinkMinValidDefault);
    refreshAutoTuneUi();
  }

  bool save() {
    if (open_threshold->value() > maximumOpenThreshold(close_threshold->value())) {
      ConfirmationDialog::alert(tr("Open threshold exceeds the allowed value for the selected Close threshold."), this);
      return false;
    }
    if (min_duration->value() >= max_blink_duration->value()) {
      ConfirmationDialog::alert(tr("Maximum blink must be greater than Minimum blink duration."), this);
      return false;
    }
    if (max_blink_duration->value() >= sleep_candidate_duration->value()) {
      ConfirmationDialog::alert(tr("Sleep Candidate must be greater than Maximum blink duration."), this);
      return false;
    }

    params.putBool("DmBlinkDebugOverlayEnabled", debug_enabled->value());
    params.putBool("DmBlinkAlertEnabled", alert_mode->value() == 1);
    params.putBool("DmBlinkDismissOnDriverInput", dismiss_on_driver_input->value());
    params.putBool("DmBlinkAutoTuneEnabled", auto_tune_enabled->value());
    params.putBool("DmBlinkAutoTuneAutoApply", auto_tune_enabled->value() && auto_apply_next_drive->value());
    params.put("DmBlinkAutoTuneSensitivityLevel", std::to_string(blinkAutoTuneSensitivityLevel(auto_tune_sensitivity->value())));
    params.put("DmBlinkCloseThresholdPct", std::to_string(close_threshold->value()));
    params.put("DmBlinkOpenThresholdPct", std::to_string(open_threshold->value()));
    params.put("DmBlinkMinDurationMs", std::to_string(min_duration->value()));
    params.put("DmBlinkMaxDurationMs", std::to_string(max_blink_duration->value()));
    params.put("DmSleepCandidateDurationMs", std::to_string(sleep_candidate_duration->value()));
    params.put("DmBlinkMinValidPct", std::to_string(min_valid->value()));
    return true;
  }

  Params params;
  BlinkAutoTuneState auto_tune_state;
  StagedToggleControl *debug_enabled;
  StagedButtonControl *alert_mode;
  StagedToggleControl *dismiss_on_driver_input;
  StagedToggleControl *auto_tune_enabled;
  StagedButtonControl *auto_tune_sensitivity;
  StagedToggleControl *auto_apply_next_drive;
  QLabel *auto_tune_status;
  QPushButton *apply_all_auto_button;
  QPushButton *reset_auto_data_button;
  TouchValueControl *close_threshold;
  TouchValueControl *open_threshold;
  TouchValueControl *min_duration;
  TouchValueControl *max_blink_duration;
  TouchValueControl *sleep_candidate_duration;
  TouchValueControl *min_valid;
};

}  // namespace

TogglesPanel::TogglesPanel(SettingsWindow *parent) : ListWidget(parent) {
  // param, title, desc, icon, restart needed
  std::vector<std::tuple<QString, QString, QString, QString, bool>> toggle_defs{
    {
      "OpenpilotEnabledToggle",
      tr("Enable openpilot"),
      tr("Use the openpilot system for adaptive cruise control and lane keep driver assistance. Your attention is required at all times to use this feature."),
      "../assets/icons/chffr_wheel.png",
      true,
    },
    {
      "ExperimentalMode",
      tr("Experimental Mode"),
      "",
      "../assets/icons/experimental_white.svg",
      false,
    },
    {
      "DisengageOnAccelerator",
      tr("Disengage on Accelerator Pedal"),
      tr("When enabled, pressing the accelerator pedal will disengage openpilot."),
      "../assets/icons/disengage_on_accelerator.svg",
      false,
    },
    {
      "IsLdwEnabled",
      tr("Enable Lane Departure Warnings"),
      tr("Receive alerts to steer back into the lane when your vehicle drifts over a detected lane line without a turn signal activated while driving over 31 mph (50 km/h)."),
      "../assets/icons/warning.png",
      false,
    },
    {
      "AlwaysOnDM",
      tr("Always-On Driver Monitoring"),
      tr("Enable driver monitoring even when openpilot is not engaged."),
      "../assets/icons/monitoring.png",
      false,
    },
    {
      "RecordFront",
      tr("Record and Upload Driver Camera"),
      tr("Upload data from the driver facing camera and help improve the driver monitoring algorithm."),
      "../assets/icons/monitoring.png",
      true,
    },
    {
      "RecordAudio",
      tr("Record and Upload Microphone Audio"),
      tr("Record and store microphone audio while driving. The audio will be included in the dashcam video in comma connect."),
      "../assets/icons/microphone.png",
      true,
    },
    {
      "IsMetric",
      tr("Use Metric System"),
      tr("Display speed in km/h instead of mph."),
      "../assets/icons/metric.png",
      false,
    },
  };


  std::vector<QString> longi_button_texts{tr("Aggressive"), tr("Standard"), tr("Relaxed")};
  long_personality_setting = new ButtonParamControl("LongitudinalPersonality", tr("Driving Personality"),
                                          tr("Standard is recommended. In aggressive mode, openpilot will follow lead cars closer and be more aggressive with the gas and brake. "
                                             "In relaxed mode openpilot will stay further away from lead cars. On supported cars, you can cycle through these personalities with "
                                             "your steering wheel distance button."),
                                          "../assets/icons/speed_limit.png",
                                          longi_button_texts);

  // set up uiState update for personality setting
  QObject::connect(uiState(), &UIState::uiUpdate, this, &TogglesPanel::updateState);

  for (auto &[param, title, desc, icon, needs_restart] : toggle_defs) {
    auto toggle = new ParamControl(param, title, desc, icon, this);

    bool locked = params.getBool((param + "Lock").toStdString());
    toggle->setEnabled(!locked);

    if (needs_restart && !locked) {
      toggle->setDescription(toggle->getDescription() + tr(" Changing this setting will restart openpilot if the car is powered on."));

      QObject::connect(uiState(), &UIState::engagedChanged, [toggle](bool engaged) {
        toggle->setEnabled(!engaged);
      });

      QObject::connect(toggle, &ParamControl::toggleFlipped, [=](bool state) {
        params.putBool("OnroadCycleRequested", true);
      });
    }

    addItem(toggle);
    toggles[param.toStdString()] = toggle;

    if (param == "AlwaysOnDM") {
      blink_debug_settings_btn = new ButtonControl(
        tr("Driver Monitoring Blink Debug"), tr("SETTINGS"), "", this);
      updateBlinkDebugDescription();
      QObject::connect(blink_debug_settings_btn, &ButtonControl::clicked, [this]() {
        BlinkDebugSettingsDialog dialog(this);
        if (dialog.exec() == QDialog::Accepted) {
          updateBlinkDebugDescription();
        }
      });
      QObject::connect(uiState(), &UIState::offroadTransition, [this](bool offroad) {
        blink_debug_settings_btn->setEnabled(offroad);
      });
      blink_debug_settings_btn->setEnabled(!uiState()->scene.started);
      addItem(blink_debug_settings_btn);
    }

    // insert longitudinal personality after NDOG toggle
    if (param == "DisengageOnAccelerator") {
      addItem(long_personality_setting);
    }
  }

  // Toggles with confirmation dialogs
  toggles["ExperimentalMode"]->setActiveIcon("../assets/icons/experimental.svg");
  toggles["ExperimentalMode"]->setConfirmation(true, true);
}

void TogglesPanel::updateBlinkDebugDescription() {
  const bool enabled = params.getBool("DmBlinkDebugOverlayEnabled");
  const bool alert_enabled = params.getBool("DmBlinkAlertEnabled");
  const bool dismiss_on_driver_input = params.getBool("DmBlinkDismissOnDriverInput");
  const bool auto_tune_enabled = params.getBool("DmBlinkAutoTuneEnabled");
  const bool auto_apply_enabled = params.getBool("DmBlinkAutoTuneAutoApply");
  const int sensitivity_level = blinkAutoTuneSensitivityLevel(
    getIntParam(params, "DmBlinkAutoTuneSensitivityLevel", kBlinkAutoTuneSensitivityDefault));
  const int close_pct = getIntParam(params, "DmBlinkCloseThresholdPct", kBlinkCloseDefault);
  const int min_duration_ms = getIntParam(params, "DmBlinkMinDurationMs", kBlinkMinDurationDefault);
  const int max_blink_duration_ms = getIntParam(params, "DmBlinkMaxDurationMs", kBlinkMaxDurationDefault);
  const int sleep_candidate_duration_ms = getIntParam(params, "DmSleepCandidateDurationMs", kSleepCandidateDurationDefault);
  blink_debug_settings_btn->setDescription(
    tr("Diagnostic overlay: %1 | Candidate link: %2 | Driver input dismiss: %3 | Auto Tune: %4 (%5) | Next-drive apply: %6 | Close %7% | Blink %8-%9 ms | Sleep Candidate %10 s. "
       "The overlay only controls show/hide. Link OFF disables candidate-generated warnings; existing DM warnings remain active.")
      .arg(enabled ? tr("ON") : tr("OFF"))
      .arg(alert_enabled ? tr("ON (WARNING)") : tr("OFF (DEBUG)"))
      .arg(dismiss_on_driver_input ? tr("ON") : tr("OFF"))
      .arg(auto_tune_enabled ? tr("ON") : tr("OFF"))
      .arg(blinkAutoTuneSensitivityName(sensitivity_level))
      .arg(auto_apply_enabled ? tr("ON") : tr("OFF"))
      .arg(close_pct)
      .arg(min_duration_ms)
      .arg(max_blink_duration_ms)
      .arg(sleep_candidate_duration_ms / 1000.0, 0, 'f', 1));
}

void TogglesPanel::updateState(const UIState &s) {
  const SubMaster &sm = *(s.sm);

  if (sm.updated("selfdriveState")) {
    auto personality = sm["selfdriveState"].getSelfdriveState().getPersonality();
    if (personality != s.scene.personality && s.scene.started && isVisible()) {
      long_personality_setting->setCheckedButton(static_cast<int>(personality));
    }
    uiState()->scene.personality = personality;
  }
}

void TogglesPanel::expandToggleDescription(const QString &param) {
  toggles[param.toStdString()]->showDescription();
}

void TogglesPanel::scrollToToggle(const QString &param) {
  if (auto it = toggles.find(param.toStdString()); it != toggles.end()) {
    auto scroll_area = qobject_cast<QScrollArea*>(parent()->parent());
    if (scroll_area) {
      scroll_area->ensureWidgetVisible(it->second);
    }
  }
}

void TogglesPanel::showEvent(QShowEvent *event) {
  updateToggles();
}

void TogglesPanel::updateToggles() {
  updateBlinkDebugDescription();
  auto experimental_mode_toggle = toggles["ExperimentalMode"];
  const QString e2e_description = QString("%1<br>"
                                          "<h4>%2</h4><br>"
                                          "%3<br>"
                                          "<h4>%4</h4><br>"
                                          "%5<br>")
                                  .arg(tr("openpilot defaults to driving in <b>chill mode</b>. Experimental mode enables <b>alpha-level features</b> that aren't ready for chill mode. Experimental features are listed below:"))
                                  .arg(tr("End-to-End Longitudinal Control"))
                                  .arg(tr("Let the driving model control the gas and brakes. openpilot will drive as it thinks a human would, including stopping for red lights and stop signs. "
                                          "Since the driving model decides the speed to drive, the set speed will only act as an upper bound. This is an alpha quality feature; "
                                          "mistakes should be expected."))
                                  .arg(tr("New Driving Visualization"))
                                  .arg(tr("The driving visualization will transition to the road-facing wide-angle camera at low speeds to better show some turns. The Experimental mode logo will also be shown in the top right corner."));

  const bool is_release = params.getBool("IsReleaseBranch");
  auto cp_bytes = params.get("CarParamsPersistent");
  if (!cp_bytes.empty()) {
    AlignedBuffer aligned_buf;
    capnp::FlatArrayMessageReader cmsg(aligned_buf.align(cp_bytes.data(), cp_bytes.size()));
    cereal::CarParams::Reader CP = cmsg.getRoot<cereal::CarParams>();

    if (hasLongitudinalControl(CP)) {
      // normal description and toggle
      experimental_mode_toggle->setEnabled(true);
      experimental_mode_toggle->setDescription(e2e_description);
      long_personality_setting->setEnabled(true);
    } else {
      // no long for now
      experimental_mode_toggle->setEnabled(false);
      long_personality_setting->setEnabled(false);
      params.remove("ExperimentalMode");

      const QString unavailable = tr("Experimental mode is currently unavailable on this car since the car's stock ACC is used for longitudinal control.");

      QString long_desc = unavailable + " " + \
                          tr("openpilot longitudinal control may come in a future update.");
      if (CP.getAlphaLongitudinalAvailable()) {
        if (is_release) {
          long_desc = unavailable + " " + tr("An alpha version of openpilot longitudinal control can be tested, along with Experimental mode, on non-release branches.");
        } else {
          long_desc = tr("Enable the openpilot longitudinal control (alpha) toggle to allow Experimental mode.");
        }
      }
      experimental_mode_toggle->setDescription("<b>" + long_desc + "</b><br><br>" + e2e_description);
    }

    experimental_mode_toggle->refresh();
  } else {
    experimental_mode_toggle->setDescription(e2e_description);
  }
}

DevicePanel::DevicePanel(SettingsWindow *parent) : ListWidget(parent) {
  setSpacing(50);
  addItem(new LabelControl(tr("Dongle ID"), getDongleId().value_or(tr("N/A"))));
  addItem(new LabelControl(tr("Serial"), params.get("HardwareSerial").c_str()));

  pair_device = new ButtonControl(tr("Pair Device"), tr("PAIR"),
                                  tr("Pair your device with comma connect (connect.comma.ai) and claim your comma prime offer."));
  connect(pair_device, &ButtonControl::clicked, [=]() {
    PairingPopup popup(this);
    popup.exec();
  });
  addItem(pair_device);

  // offroad-only buttons

  auto dcamBtn = new ButtonControl(tr("Driver Camera"), tr("PREVIEW"),
                                   tr("Preview the driver facing camera to ensure that driver monitoring has good visibility. (vehicle must be off)"));
  connect(dcamBtn, &ButtonControl::clicked, [=]() { emit showDriverView(); });
  addItem(dcamBtn);

  resetCalibBtn = new ButtonControl(tr("Reset Calibration"), tr("RESET"), "");
  connect(resetCalibBtn, &ButtonControl::showDescriptionEvent, this, &DevicePanel::updateCalibDescription);
  connect(resetCalibBtn, &ButtonControl::clicked, [&]() {
    if (!uiState()->engaged()) {
      if (ConfirmationDialog::confirm(tr("Are you sure you want to reset calibration?"), tr("Reset"), this)) {
        // Check engaged again in case it changed while the dialog was open
        if (!uiState()->engaged()) {
          params.remove("CalibrationParams");
          params.remove("LiveTorqueParameters");
          params.remove("LiveParameters");
          params.remove("LiveParametersV2");
          params.remove("LiveDelay");
          params.putBool("OnroadCycleRequested", true);
          updateCalibDescription();
        }
      }
    } else {
      ConfirmationDialog::alert(tr("Disengage to Reset Calibration"), this);
    }
  });
  addItem(resetCalibBtn);

  auto retrainingBtn = new ButtonControl(tr("Review Training Guide"), tr("REVIEW"), tr("Review the rules, features, and limitations of openpilot"));
  connect(retrainingBtn, &ButtonControl::clicked, [=]() {
    if (ConfirmationDialog::confirm(tr("Are you sure you want to review the training guide?"), tr("Review"), this)) {
      emit reviewTrainingGuide();
    }
  });
  addItem(retrainingBtn);

  if (Hardware::TICI()) {
    auto regulatoryBtn = new ButtonControl(tr("Regulatory"), tr("VIEW"), "");
    connect(regulatoryBtn, &ButtonControl::clicked, [=]() {
      const std::string txt = util::read_file("../assets/offroad/fcc.html");
      ConfirmationDialog::rich(QString::fromStdString(txt), this);
    });
    addItem(regulatoryBtn);
  }

  auto translateBtn = new ButtonControl(tr("Change Language"), tr("CHANGE"), "");
  connect(translateBtn, &ButtonControl::clicked, [=]() {
    QMap<QString, QString> langs = getSupportedLanguages();
    QString selection = MultiOptionDialog::getSelection(tr("Select a language"), langs.keys(), langs.key(uiState()->language), this);
    if (!selection.isEmpty()) {
      // put language setting, exit Qt UI, and trigger fast restart
      params.put("LanguageSetting", langs[selection].toStdString());
      qApp->exit(18);
      watchdog_kick(0);
    }
  });
  addItem(translateBtn);

  QObject::connect(uiState()->prime_state, &PrimeState::changed, [this] (PrimeState::Type type) {
    pair_device->setVisible(type == PrimeState::PRIME_TYPE_UNPAIRED);
  });
  QObject::connect(uiState(), &UIState::offroadTransition, [=](bool offroad) {
    for (auto btn : findChildren<ButtonControl *>()) {
      if (btn != pair_device && btn != resetCalibBtn) {
        btn->setEnabled(offroad);
      }
    }
  });

  // power buttons
  QHBoxLayout *power_layout = new QHBoxLayout();
  power_layout->setSpacing(30);

  QPushButton *reboot_btn = new QPushButton(tr("Reboot"));
  reboot_btn->setObjectName("reboot_btn");
  power_layout->addWidget(reboot_btn);
  QObject::connect(reboot_btn, &QPushButton::clicked, this, &DevicePanel::reboot);

  QPushButton *poweroff_btn = new QPushButton(tr("Power Off"));
  poweroff_btn->setObjectName("poweroff_btn");
  power_layout->addWidget(poweroff_btn);
  QObject::connect(poweroff_btn, &QPushButton::clicked, this, &DevicePanel::poweroff);

  if (!Hardware::PC()) {
    connect(uiState(), &UIState::offroadTransition, poweroff_btn, &QPushButton::setVisible);
  }

  setStyleSheet(R"(
    #reboot_btn { height: 120px; border-radius: 15px; background-color: #393939; }
    #reboot_btn:pressed { background-color: #4a4a4a; }
    #poweroff_btn { height: 120px; border-radius: 15px; background-color: #E22C2C; }
    #poweroff_btn:pressed { background-color: #FF2424; }
  )");
  addItem(power_layout);
}

void DevicePanel::updateCalibDescription() {
  QString desc = tr("openpilot requires the device to be mounted within 4° left or right and within 5° up or 9° down.");
  std::string calib_bytes = params.get("CalibrationParams");
  if (!calib_bytes.empty()) {
    try {
      AlignedBuffer aligned_buf;
      capnp::FlatArrayMessageReader cmsg(aligned_buf.align(calib_bytes.data(), calib_bytes.size()));
      auto calib = cmsg.getRoot<cereal::Event>().getLiveCalibration();
      if (calib.getCalStatus() != cereal::LiveCalibrationData::Status::UNCALIBRATED) {
        double pitch = calib.getRpyCalib()[1] * (180 / M_PI);
        double yaw = calib.getRpyCalib()[2] * (180 / M_PI);
        desc += tr(" Your device is pointed %1° %2 and %3° %4.")
                    .arg(QString::number(std::abs(pitch), 'g', 1), pitch > 0 ? tr("down") : tr("up"),
                         QString::number(std::abs(yaw), 'g', 1), yaw > 0 ? tr("left") : tr("right"));
      }
    } catch (kj::Exception) {
      qInfo() << "invalid CalibrationParams";
    }
  }

  int lag_perc = 0;
  std::string lag_bytes = params.get("LiveDelay");
  if (!lag_bytes.empty()) {
    try {
      AlignedBuffer aligned_buf;
      capnp::FlatArrayMessageReader cmsg(aligned_buf.align(lag_bytes.data(), lag_bytes.size()));
      lag_perc = cmsg.getRoot<cereal::Event>().getLiveDelay().getCalPerc();
    } catch (kj::Exception) {
      qInfo() << "invalid LiveDelay";
    }
  }
  if (lag_perc < 100) {
    desc += tr("\n\nSteering lag calibration is %1% complete.").arg(lag_perc);
  } else {
    desc += tr("\n\nSteering lag calibration is complete.");
  }

  std::string torque_bytes = params.get("LiveTorqueParameters");
  if (!torque_bytes.empty()) {
    try {
      AlignedBuffer aligned_buf;
      capnp::FlatArrayMessageReader cmsg(aligned_buf.align(torque_bytes.data(), torque_bytes.size()));
      auto torque = cmsg.getRoot<cereal::Event>().getLiveTorqueParameters();
      // don't add for non-torque cars
      if (torque.getUseParams()) {
        int torque_perc = torque.getCalPerc();
        if (torque_perc < 100) {
          desc += tr(" Steering torque response calibration is %1% complete.").arg(torque_perc);
        } else {
          desc += tr(" Steering torque response calibration is complete.");
        }
      }
    } catch (kj::Exception) {
      qInfo() << "invalid LiveTorqueParameters";
    }
  }

  desc += "\n\n";
  desc += tr("openpilot is continuously calibrating, resetting is rarely required. "
             "Resetting calibration will restart openpilot if the car is powered on.");
  resetCalibBtn->setDescription(desc);
}

void DevicePanel::reboot() {
  if (!uiState()->engaged()) {
    if (ConfirmationDialog::confirm(tr("Are you sure you want to reboot?"), tr("Reboot"), this)) {
      // Check engaged again in case it changed while the dialog was open
      if (!uiState()->engaged()) {
        params.putBool("DoReboot", true);
      }
    }
  } else {
    ConfirmationDialog::alert(tr("Disengage to Reboot"), this);
  }
}

void DevicePanel::poweroff() {
  if (!uiState()->engaged()) {
    if (ConfirmationDialog::confirm(tr("Are you sure you want to power off?"), tr("Power Off"), this)) {
      // Check engaged again in case it changed while the dialog was open
      if (!uiState()->engaged()) {
        params.putBool("DoShutdown", true);
      }
    }
  } else {
    ConfirmationDialog::alert(tr("Disengage to Power Off"), this);
  }
}

void SettingsWindow::showEvent(QShowEvent *event) {
  setCurrentPanel(0);
}

void SettingsWindow::setCurrentPanel(int index, const QString &param) {
  if (!param.isEmpty()) {
    // Check if param ends with "Panel" to determine if it's a panel name
    if (param.endsWith("Panel")) {
      QString panelName = param;
      panelName.chop(5); // Remove "Panel" suffix

      // Find the panel by name
      for (int i = 0; i < nav_btns->buttons().size(); i++) {
        if (nav_btns->buttons()[i]->text() == tr(panelName.toStdString().c_str())) {
          index = i;
          break;
        }
      }
    } else {
      emit expandToggleDescription(param);
      emit scrollToToggle(param);
    }
  }

  panel_widget->setCurrentIndex(index);
  nav_btns->buttons()[index]->setChecked(true);
}

SettingsWindow::SettingsWindow(QWidget *parent) : QFrame(parent) {

  // setup two main layouts
  sidebar_widget = new QWidget;
  QVBoxLayout *sidebar_layout = new QVBoxLayout(sidebar_widget);
  panel_widget = new QStackedWidget();

  // close button
  QPushButton *close_btn = new QPushButton(tr("×"));
  close_btn->setStyleSheet(R"(
    QPushButton {
      font-size: 140px;
      padding-bottom: 20px;
      border-radius: 100px;
      background-color: #292929;
      font-weight: 400;
    }
    QPushButton:pressed {
      background-color: #3B3B3B;
    }
  )");
  close_btn->setFixedSize(200, 200);
  sidebar_layout->addSpacing(45);
  sidebar_layout->addWidget(close_btn, 0, Qt::AlignCenter);
  QObject::connect(close_btn, &QPushButton::clicked, this, &SettingsWindow::closeSettings);

  // setup panels
  DevicePanel *device = new DevicePanel(this);
  QObject::connect(device, &DevicePanel::reviewTrainingGuide, this, &SettingsWindow::reviewTrainingGuide);
  QObject::connect(device, &DevicePanel::showDriverView, this, &SettingsWindow::showDriverView);

  TogglesPanel *toggles = new TogglesPanel(this);
  QObject::connect(this, &SettingsWindow::expandToggleDescription, toggles, &TogglesPanel::expandToggleDescription);
  QObject::connect(this, &SettingsWindow::scrollToToggle, toggles, &TogglesPanel::scrollToToggle);

  auto networking = new Networking(this);
  QObject::connect(uiState()->prime_state, &PrimeState::changed, networking, &Networking::setPrimeType);

  QList<QPair<QString, QWidget *>> panels = {
    {tr("Device"), device},
    {tr("Network"), networking},
    {tr("Toggles"), toggles},
    {tr("Software"), new SoftwarePanel(this)},
    {tr("Firehose"), new FirehosePanel(this)},
    {tr("Developer"), new DeveloperPanel(this)},
    {tr("Custom"), new CustomPanel(this)},    // #custom
  };

  nav_btns = new QButtonGroup(this);
  for (auto &[name, panel] : panels) {
    QPushButton *btn = new QPushButton(name);
    btn->setCheckable(true);
    btn->setChecked(nav_btns->buttons().size() == 0);
    btn->setStyleSheet(R"(
      QPushButton {
        color: grey;
        border: none;
        background: none;
        font-size: 65px;
        font-weight: 500;
      }
      QPushButton:checked {
        color: white;
      }
      QPushButton:pressed {
        color: #ADADAD;
      }
    )");
    btn->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Expanding);
    nav_btns->addButton(btn);
    sidebar_layout->addWidget(btn, 0, Qt::AlignRight);

    const int lr_margin = name != tr("Network") ? 50 : 0;  // Network panel handles its own margins
    panel->setContentsMargins(lr_margin, 25, lr_margin, 25);

    ScrollView *panel_frame = new ScrollView(panel, this);
    panel_widget->addWidget(panel_frame);

    QObject::connect(btn, &QPushButton::clicked, [=, w = panel_frame]() {
      btn->setChecked(true);
      panel_widget->setCurrentWidget(w);
    });
  }
  sidebar_layout->setContentsMargins(50, 50, 100, 50);

  // main settings layout, sidebar + main panel
  QHBoxLayout *main_layout = new QHBoxLayout(this);

  sidebar_widget->setFixedWidth(500);
  main_layout->addWidget(sidebar_widget);
  main_layout->addWidget(panel_widget);

  setStyleSheet(R"(
    * {
      color: white;
      font-size: 50px;
    }
    SettingsWindow {
      background-color: black;
    }
    QStackedWidget, ScrollView {
      background-color: #292929;
      border-radius: 30px;
    }
  )");
}
