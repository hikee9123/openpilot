from openpilot.selfdrive.monitoring.blink_auto_tuner import (
  AUTO_APPLY_MIN_CONFIDENCE_PCT, BlinkAutoTuner, apply_auto_tune_on_start,
  eligible_auto_apply_recommendations,
)


CURRENT_SETTINGS = {
  "closeThresholdPct": 87,
  "openThresholdPct": 50,
  "minDurationMs": 100,
  "maxBlinkDurationMs": 1500,
  "sleepCandidateDurationMs": 10000,
  "minValidPct": 80,
}

# Captured from the affected device after 462 valid driving minutes. Its broad,
# overlapping probability distribution is valid but exceeds the old 30% upper-cluster ratio guard.
DEVICE_BROAD_BLINK_HISTOGRAM = [
  0, 0, 0, 0, 0, 12, 34, 98, 260, 573, 947, 1340, 2029, 2808, 3648, 4887, 6118,
  7523, 8308, 8363, 8223, 8282, 8185, 8133, 7987, 8222, 8423, 8384, 8182, 8218,
  8053, 7863, 7578, 7322, 7111, 7109, 7196, 7445, 7583, 7525, 7591, 7580, 7771,
  7681, 7642, 7597, 7710, 7820, 7986, 7881, 7951, 7942, 8081, 7944, 8043, 7999,
  7959, 7964, 8032, 7794, 7672, 7684, 7566, 7339, 7849, 7813, 7767, 7874, 7930,
  7939, 7913, 7817, 7994, 7971, 7746, 7357, 6752, 6209, 5643, 5040, 4804, 4145,
  3866, 3370, 3278, 3098, 2991, 2978, 3233, 2892, 2841, 2650, 2199, 1588, 905,
  523, 215, 44, 5, 0, 0,
]


def add_synthetic_drive(tuner, minutes=10):
  frame_count = minutes * 60 * 20
  closure_ms = 0
  for frame in range(frame_count):
    phase = frame % 100
    closed = phase < 4
    closure_ms = closure_ms + 50 if closed else 0
    tuner.observe(True, 0.90 if closed else 0.05, closed, closure_ms, 90)


def test_requires_enough_driving_data():
  tuner = BlinkAutoTuner()
  add_synthetic_drive(tuner, minutes=9)
  state = tuner.to_dict(CURRENT_SETTINGS, now=123)
  assert not state["ready"]
  assert state["lastUpdated"] == 123


def test_generates_bounded_recommendations():
  tuner = BlinkAutoTuner()
  add_synthetic_drive(tuner)
  state = tuner.to_dict(CURRENT_SETTINGS, now=123)
  recommendations = state["recommendations"]

  assert state["ready"]
  assert state["recommendationMode"] == "clusters"
  assert 50 <= recommendations["closeThresholdPct"] <= 95
  assert 5 <= recommendations["openThresholdPct"] <= recommendations["closeThresholdPct"] - 5
  assert 50 <= recommendations["minDurationMs"] <= 300
  assert recommendations["maxBlinkDurationMs"] == CURRENT_SETTINGS["maxBlinkDurationMs"]
  assert recommendations["sleepCandidateDurationMs"] == CURRENT_SETTINGS["sleepCandidateDurationMs"]
  assert 50 <= recommendations["minValidPct"] <= 95


def test_percentile_fallback_handles_device_distribution():
  tuner = BlinkAutoTuner()
  tuner.sample_count = sum(DEVICE_BROAD_BLINK_HISTOGRAM)
  tuner.valid_sample_count = tuner.sample_count
  tuner.closure_count = 50
  tuner.blink_histogram = DEVICE_BROAD_BLINK_HISTOGRAM.copy()
  tuner.valid_ratio_histogram[90] = tuner.sample_count
  tuner.closure_duration_histogram[4] = tuner.closure_count

  state = tuner.to_dict(CURRENT_SETTINGS, now=123)

  assert state["ready"]
  assert state["confidencePct"] == 100
  assert state["recommendationMode"] == "percentiles"
  assert state["recommendations"]["closeThresholdPct"] == 78
  assert state["recommendations"]["openThresholdPct"] == 42


def test_percentile_fallback_rejects_narrow_distribution():
  tuner = BlinkAutoTuner()
  tuner.sample_count = tuner.valid_sample_count = 30 * 60 * 20
  tuner.closure_count = 50
  tuner.blink_histogram[50] = tuner.valid_sample_count

  state = tuner.to_dict(CURRENT_SETTINGS, now=123)

  assert not state["ready"]
  assert state["confidencePct"] == 0
  assert state["recommendationMode"] == "unavailable"


def test_state_round_trip_preserves_accumulators():
  tuner = BlinkAutoTuner()
  add_synthetic_drive(tuner, minutes=1)
  restored = BlinkAutoTuner.from_dict(tuner.to_dict(CURRENT_SETTINGS, now=123))

  assert restored.sample_count == tuner.sample_count
  assert restored.valid_sample_count == tuner.valid_sample_count
  assert restored.closure_count == tuner.closure_count
  assert restored.blink_histogram == tuner.blink_histogram


def test_invalid_saved_state_is_discarded_safely():
  state = {
    "version": 1,
    "sampleCount": "invalid",
    "validSampleCount": -1,
    "closureCount": None,
    "blinkHistogram": ["invalid"] * 101,
  }
  restored = BlinkAutoTuner.from_dict(state)

  assert restored.sample_count == 0
  assert restored.valid_sample_count == 0
  assert restored.closure_count == 0
  assert restored.blink_histogram == [0] * 101


def test_pause_does_not_count_closure_across_driving_sessions():
  tuner = BlinkAutoTuner()
  tuner.observe(True, 0.9, True, 50, 90)
  tuner.pause()
  tuner.observe(True, 0.1, False, 0, 90)

  assert tuner.closure_count == 0


class ParamsStub:
  def __init__(self, state, auto_tune=True, auto_apply=True):
    self.values = {
      "DmBlinkAutoTuneEnabled": auto_tune,
      "DmBlinkAutoTuneAutoApply": auto_apply,
      "DmBlinkAutoTuneStartChecked": False,
      "DmBlinkAutoTuneState": state,
      "DmBlinkCloseThresholdPct": 87,
      "DmBlinkOpenThresholdPct": 50,
      "DmBlinkMinDurationMs": 100,
      "DmBlinkMinValidPct": 80,
      "DmBlinkMaxDurationMs": 1500,
      "DmSleepCandidateDurationMs": 10000,
    }

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def get(self, key, return_default=False):
    return self.values.get(key)

  def put(self, key, value):
    self.values[key] = value if isinstance(value, dict) else int(value)

  def put_bool(self, key, value):
    self.values[key] = bool(value)


def auto_apply_state(confidence_pct=90, last_updated=123):
  return {
    "version": 1,
    "ready": True,
    "confidencePct": confidence_pct,
    "lastUpdated": last_updated,
    "validSampleCount": 30 * 60 * 20,
    "recommendations": {
      "closeThresholdPct": 70,
      "openThresholdPct": 40,
      "minDurationMs": 250,
      "maxBlinkDurationMs": 1500,
      "sleepCandidateDurationMs": 10000,
      "minValidPct": 60,
    },
  }


def test_auto_apply_requires_high_confidence():
  state = auto_apply_state(confidence_pct=AUTO_APPLY_MIN_CONFIDENCE_PCT - 1)
  assert eligible_auto_apply_recommendations(state) is None
  assert apply_auto_tune_on_start(ParamsStub(state), now=456) is None


def test_auto_apply_is_bounded_and_preserves_sleep_settings():
  params = ParamsStub(auto_apply_state())
  record = apply_auto_tune_on_start(params, now=456)

  assert record is not None
  assert record["applied"] == {
    "closeThresholdPct": 82,
    "openThresholdPct": 45,
    "minDurationMs": 150,
    "minValidPct": 75,
  }
  assert params.values["DmBlinkMaxDurationMs"] == 1500
  assert params.values["DmSleepCandidateDurationMs"] == 10000
  assert record["appliedAt"] == 456


def test_auto_apply_runs_only_once_per_recommendation():
  params = ParamsStub(auto_apply_state())
  assert apply_auto_tune_on_start(params, now=456) is not None
  assert apply_auto_tune_on_start(params, now=457) is None


def test_auto_apply_process_restart_is_blocked_for_same_drive():
  params = ParamsStub(auto_apply_state())
  assert apply_auto_tune_on_start(params, now=456) is not None
  params.values["DmBlinkAutoTuneState"] = auto_apply_state(last_updated=124)
  assert apply_auto_tune_on_start(params, now=457) is None


def test_next_auto_apply_requires_five_new_valid_minutes():
  params = ParamsStub(auto_apply_state())
  assert apply_auto_tune_on_start(params, now=456) is not None
  params.values["DmBlinkAutoTuneStartChecked"] = False
  params.values["DmBlinkAutoTuneState"] = auto_apply_state(last_updated=124)
  assert apply_auto_tune_on_start(params, now=457) is None

  params.values["DmBlinkAutoTuneStartChecked"] = False
  params.values["DmBlinkAutoTuneState"]["validSampleCount"] += 5 * 60 * 20
  assert apply_auto_tune_on_start(params, now=458) is not None


def test_auto_apply_step_limits_hold_at_manual_setting_bounds():
  params = ParamsStub(auto_apply_state())
  params.values.update({
    "DmBlinkCloseThresholdPct": 5,
    "DmBlinkOpenThresholdPct": 5,
    "DmBlinkMinDurationMs": 500,
    "DmBlinkMinValidPct": 100,
  })
  record = apply_auto_tune_on_start(params, now=456)

  assert record["applied"] == {
    "closeThresholdPct": 10,
    "openThresholdPct": 5,
    "minDurationMs": 450,
    "minValidPct": 95,
  }


def test_auto_apply_respects_both_toggles():
  state = auto_apply_state()
  assert apply_auto_tune_on_start(ParamsStub(state, auto_tune=False), now=456) is None
  assert apply_auto_tune_on_start(ParamsStub(state, auto_apply=False), now=456) is None
