from openpilot.selfdrive.monitoring.blink_auto_tuner import BlinkAutoTuner


CURRENT_SETTINGS = {
  "closeThresholdPct": 87,
  "openThresholdPct": 50,
  "minDurationMs": 100,
  "longClosureMs": 1500,
  "minValidPct": 80,
}


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
  assert 50 <= recommendations["closeThresholdPct"] <= 95
  assert 5 <= recommendations["openThresholdPct"] <= recommendations["closeThresholdPct"] - 5
  assert 50 <= recommendations["minDurationMs"] <= 300
  assert recommendations["longClosureMs"] == CURRENT_SETTINGS["longClosureMs"]
  assert 50 <= recommendations["minValidPct"] <= 95


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
