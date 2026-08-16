#include <algorithm>
#include <cassert>
#include <cmath>
#include <exception>
#include <functional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include <QDebug>
#include <QDialog>
#include <QHBoxLayout>
#include <QVBoxLayout>

#include "common/watchdog.h"
#include "common/util.h"
#include "selfdrive/ui/qt/network/networking.h"
#include "selfdrive/ui/qt/offroad/settings.h"
#include "selfdrive/ui/qt/qt_window.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "selfdrive/ui/qt/widgets/prime.h"
#include "selfdrive/ui/qt/widgets/scrollview.h"
#include "selfdrive/ui/qt/offroad/developer_panel.h"
#include "selfdrive/ui/qt/offroad/firehose.h"

#include "selfdrive/ui/qt/custom/custom.h"   // #custom

namespace {

constexpr int kBlinkCloseDefault = 87;
constexpr int kBlinkOpenDefault = 50;
constexpr int kBlinkMinDurationDefault = 100;
constexpr int kBlinkLongClosureDefault = 1500;
constexpr int kBlinkMinValidDefault = 80;

int getIntParam(Params &params, const std::string &key, int default_value) {
  try {
    const std::string value = params.get(key);
    return value.empty() ? default_value : std::stoi(value);
  } catch (const std::exception &) {
    return default_value;
  }
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

class TouchValueControl : public AbstractControl {
public:
  TouchValueControl(const QString &title, const QString &description, int minimum, int maximum,
                    int step, int value, TouchValueFormat format, QWidget *parent)
      : AbstractControl(title, description, "", parent), minimum_(minimum), maximum_(maximum),
        step_(step), value_(std::clamp(value, minimum, maximum)), format_(format) {
    title_label->setStyleSheet("font-size: 34px; font-weight: 400; text-align: left; border: none;");

    const QString button_style = R"(
      QPushButton {
        min-width: 0; min-height: 0; padding: 0;
        border: 0; border-radius: 45px;
        background-color: #393939; color: white;
        font-size: 50px; font-weight: 500;
      }
      QPushButton:pressed { background-color: #4a4a4a; }
      QPushButton:disabled { color: #666666; background-color: #242424; }
    )";
    minus_button.setText("-");
    plus_button.setText("+");
    for (QPushButton *button : {&minus_button, &plus_button}) {
      button->setFixedSize(150, 100);
      button->setStyleSheet(button_style);
      button->setAutoRepeat(true);
      button->setAutoRepeatDelay(500);
      button->setAutoRepeatInterval(120);
    }

    value_label.setFixedSize(220, 100);
    value_label.setAlignment(Qt::AlignCenter);
    value_label.setStyleSheet(R"(
      QLabel {
        border: 2px solid #414850; border-radius: 18px;
        background-color: #252a30; color: white;
        font-size: 31px; font-weight: 500;
      }
    )");

    hlayout->addWidget(&minus_button);
    hlayout->addWidget(&value_label);
    hlayout->addWidget(&plus_button);

    QObject::connect(&minus_button, &QPushButton::clicked, [this]() { setValue(value_ - step_); });
    QObject::connect(&plus_button, &QPushButton::clicked, [this]() { setValue(value_ + step_); });
    refresh();
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
  }

  void setMaximum(int maximum) {
    maximum_ = std::max(maximum, minimum_);
    setValue(value_);
  }

  void setValueChangedCallback(std::function<void(int)> callback) {
    value_changed_callback_ = std::move(callback);
  }

private:
  QString formattedValue() const {
    switch (format_) {
      case TouchValueFormat::PERCENT:
        return QString("%1%").arg(value_);
      case TouchValueFormat::MILLISECONDS:
        return QString("%1 ms").arg(value_);
      case TouchValueFormat::SECONDS:
        return QString("%1 s").arg(value_ / 1000.0, 0, 'f', 1);
    }
    return QString::number(value_);
  }

  void refresh() {
    value_label.setText(formattedValue());
    minus_button.setEnabled(value_ > minimum_);
    plus_button.setEnabled(value_ < maximum_);
  }

  int minimum_;
  int maximum_;
  int step_;
  int value_;
  TouchValueFormat format_;
  std::function<void(int)> value_changed_callback_;
  QPushButton minus_button;
  QPushButton plus_button;
  QLabel value_label;
};

class BlinkDebugSettingsDialog : public DialogBase {
public:
  explicit BlinkDebugSettingsDialog(QWidget *parent) : DialogBase(parent) {
    setWindowTitle(tr("Driver Monitoring Blink Debug"));
    setModal(true);
    setStyleSheet(R"(
      QDialog { background-color: #101214; color: white; }
      QLabel { color: white; }
      QPushButton {
        min-width: 230px; min-height: 78px; padding: 0 24px;
        border: 0; border-radius: 38px;
        background-color: #393939; color: white; font-size: 28px;
      }
      QPushButton#applyButton { background-color: #00c853; color: #07170d; font-weight: 600; }
    )");

    auto *main_layout = new QVBoxLayout(this);
    main_layout->setContentsMargins(45, 35, 45, 35);
    main_layout->setSpacing(18);

    auto *title = new QLabel(tr("Driver Monitoring Blink Debug"), this);
    title->setStyleSheet("font-size: 42px; font-weight: 600;");
    main_layout->addWidget(title);

    auto *notice = new QLabel(tr("Diagnostic only. These values do not change the current driver-monitoring safety alert threshold."), this);
    notice->setWordWrap(true);
    notice->setStyleSheet("font-size: 24px; color: #e8bd64; padding-bottom: 12px;");
    main_layout->addWidget(notice);

    debug_enabled = new StagedToggleControl(
      tr("Show blink debug overlay"),
      tr("Display the 10-second blink and eye-closure diagnostics while driving."),
      params.getBool("DmBlinkDebugOverlayEnabled"), this);
    main_layout->addWidget(debug_enabled);

    auto *parameter_layout = new QHBoxLayout();
    parameter_layout->setSpacing(42);
    auto *eye_layout = new QVBoxLayout();
    eye_layout->setSpacing(12);
    auto *blink_layout = new QVBoxLayout();
    blink_layout->setSpacing(12);
    parameter_layout->addLayout(eye_layout, 1);
    parameter_layout->addLayout(blink_layout, 1);
    main_layout->addLayout(parameter_layout, 1);

    addSection(eye_layout, tr("Eye closure detection"));
    close_threshold = addTouchValue(eye_layout, tr("Close threshold"),
                                    tr("Start a closed-eye segment at or above this probability."),
                                    75, 95, 1, getIntParam(params, "DmBlinkCloseThresholdPct", kBlinkCloseDefault),
                                    TouchValueFormat::PERCENT);
    open_threshold = addTouchValue(eye_layout, tr("Open threshold"),
                                   tr("Finish the segment at least 5% below Close."),
                                   20, close_threshold->value() - 5, 1,
                                   getIntParam(params, "DmBlinkOpenThresholdPct", kBlinkOpenDefault),
                                   TouchValueFormat::PERCENT);
    eye_layout->addStretch();

    addSection(blink_layout, tr("Blink and sleep candidate"));
    min_duration = addTouchValue(blink_layout, tr("Minimum blink"),
                                 tr("Ignore shorter probability spikes."),
                                 50, 500, 50, getIntParam(params, "DmBlinkMinDurationMs", kBlinkMinDurationDefault),
                                 TouchValueFormat::MILLISECONDS);
    long_closure = addTouchValue(blink_layout, tr("Long eye closure"),
                                 tr("Set Sleep Candidate after continuous valid closure."),
                                 500, 5000, 100, getIntParam(params, "DmBlinkLongClosureMs", kBlinkLongClosureDefault),
                                 TouchValueFormat::SECONDS);
    min_valid = addTouchValue(blink_layout, tr("Minimum valid data"),
                              tr("Required valid samples in the fixed 10-second window."),
                              50, 100, 5, getIntParam(params, "DmBlinkMinValidPct", kBlinkMinValidDefault),
                              TouchValueFormat::PERCENT);

    close_threshold->setValueChangedCallback([this](int value) {
      open_threshold->setMaximum(value - 5);
    });
    min_duration->setValueChangedCallback([this](int value) {
      long_closure->setMinimum(value + 50);
    });
    long_closure->setMinimum(min_duration->value() + 50);

    auto *window_note = new QLabel(tr("Measurement window: 10 seconds (fixed) - Changes apply on the next DM start."), this);
    window_note->setStyleSheet("font-size: 23px; color: #aeb5bc; padding-top: 8px;");
    main_layout->addWidget(window_note);
    main_layout->addStretch();

    auto *button_layout = new QHBoxLayout();
    button_layout->setSpacing(18);
    auto *reset_button = new QPushButton(tr("Reset defaults"), this);
    auto *cancel_button = new QPushButton(tr("Cancel"), this);
    auto *apply_button = new QPushButton(tr("Apply"), this);
    apply_button->setObjectName("applyButton");
    button_layout->addWidget(reset_button);
    button_layout->addStretch();
    button_layout->addWidget(cancel_button);
    button_layout->addWidget(apply_button);
    main_layout->addLayout(button_layout);

    QObject::connect(reset_button, &QPushButton::clicked, [this]() { setDefaults(); });
    QObject::connect(cancel_button, &QPushButton::clicked, this, &QDialog::reject);
    QObject::connect(apply_button, &QPushButton::clicked, [this]() {
      if (save()) accept();
    });
  }

private:
  void addSection(QVBoxLayout *layout, const QString &text) {
    auto *label = new QLabel(text, this);
    label->setStyleSheet("font-size: 27px; font-weight: 600; color: #8de6aa; padding-top: 12px;");
    layout->addWidget(label);
  }

  TouchValueControl *addTouchValue(QVBoxLayout *layout, const QString &title, const QString &description,
                                   int minimum, int maximum, int step, int value, TouchValueFormat format) {
    auto *control = new TouchValueControl(title, description, minimum, maximum, step, value, format, this);
    layout->addWidget(control);
    return control;
  }

  void setDefaults() {
    debug_enabled->setValue(false);
    close_threshold->setValue(kBlinkCloseDefault);
    open_threshold->setValue(kBlinkOpenDefault);
    min_duration->setValue(kBlinkMinDurationDefault);
    long_closure->setValue(kBlinkLongClosureDefault);
    min_valid->setValue(kBlinkMinValidDefault);
  }

  bool save() {
    if (open_threshold->value() > close_threshold->value() - 5) {
      ConfirmationDialog::alert(tr("Open threshold must be at least 5% below Close threshold."), this);
      return false;
    }
    if (min_duration->value() >= long_closure->value()) {
      ConfirmationDialog::alert(tr("Long eye closure must be greater than Minimum blink duration."), this);
      return false;
    }

    params.putBool("DmBlinkDebugOverlayEnabled", debug_enabled->value());
    params.put("DmBlinkCloseThresholdPct", std::to_string(close_threshold->value()));
    params.put("DmBlinkOpenThresholdPct", std::to_string(open_threshold->value()));
    params.put("DmBlinkMinDurationMs", std::to_string(min_duration->value()));
    params.put("DmBlinkLongClosureMs", std::to_string(long_closure->value()));
    params.put("DmBlinkMinValidPct", std::to_string(min_valid->value()));
    return true;
  }

  Params params;
  StagedToggleControl *debug_enabled;
  TouchValueControl *close_threshold;
  TouchValueControl *open_threshold;
  TouchValueControl *min_duration;
  TouchValueControl *long_closure;
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
  const int close_pct = getIntParam(params, "DmBlinkCloseThresholdPct", kBlinkCloseDefault);
  const int min_duration_ms = getIntParam(params, "DmBlinkMinDurationMs", kBlinkMinDurationDefault);
  const int long_closure_ms = getIntParam(params, "DmBlinkLongClosureMs", kBlinkLongClosureDefault);
  blink_debug_settings_btn->setDescription(
    tr("Diagnostic overlay: %1 · Close %2% · Blink %3 ms · Long closure %4 s. "
       "The 10-second tracker does not change the current DM safety alert threshold.")
      .arg(enabled ? tr("ON") : tr("OFF"))
      .arg(close_pct)
      .arg(min_duration_ms)
      .arg(long_closure_ms / 1000.0, 0, 'f', 1));
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
