from dataclasses import dataclass, field
import time


SAMPLE_RATE_HZ = 20
MIN_VALID_MINUTES = 10
MIN_CLOSURE_EVENTS = 10
TARGET_CONFIDENCE_MINUTES = 30
TARGET_CONFIDENCE_CLOSURES = 50
STATE_VERSION = 1
AUTO_APPLY_MIN_CONFIDENCE_PCT = 80
AUTO_APPLY_MIN_NEW_VALID_SAMPLES = 5 * 60 * SAMPLE_RATE_HZ

AUTO_APPLY_PARAM_KEYS = {
  "closeThresholdPct": "DmBlinkCloseThresholdPct",
  "openThresholdPct": "DmBlinkOpenThresholdPct",
  "minDurationMs": "DmBlinkMinDurationMs",
  "minValidPct": "DmBlinkMinValidPct",
}

AUTO_APPLY_MAX_STEP = {
  "closeThresholdPct": 5,
  "openThresholdPct": 5,
  "minDurationMs": 50,
  "minValidPct": 5,
}


def _clamp(value, minimum, maximum):
  return min(max(value, minimum), maximum)


def _bounded_step(current, target, maximum_step):
  return _clamp(target, current - maximum_step, current + maximum_step)


def eligible_auto_apply_recommendations(state):
  if not isinstance(state, dict) or state.get("version") != STATE_VERSION or not state.get("ready"):
    return None

  try:
    confidence_pct = int(state.get("confidencePct", 0))
    recommendations = state.get("recommendations")
    values = {key: int(recommendations[key]) for key in AUTO_APPLY_PARAM_KEYS}
  except (KeyError, TypeError, ValueError, OverflowError):
    return None

  if confidence_pct < AUTO_APPLY_MIN_CONFIDENCE_PCT or not (
    50 <= values["closeThresholdPct"] <= 95 and
    5 <= values["openThresholdPct"] <= values["closeThresholdPct"] - 5 and
    50 <= values["minDurationMs"] <= 300 and
    50 <= values["minValidPct"] <= 95
  ):
    return None
  return values


def apply_auto_tune_on_start(params, now=None):
  if params.get_bool("DmBlinkAutoTuneStartChecked"):
    return None
  # This transition-scoped marker prevents a process restart from changing settings mid-drive.
  params.put_bool("DmBlinkAutoTuneStartChecked", True)

  if not (params.get_bool("DmBlinkAutoTuneEnabled") and params.get_bool("DmBlinkAutoTuneAutoApply")):
    return None

  state = params.get("DmBlinkAutoTuneState") or {}
  targets = eligible_auto_apply_recommendations(state)
  if targets is None:
    return None

  try:
    source_updated = int(state.get("lastUpdated", 0))
    source_valid_sample_count = int(state.get("validSampleCount", 0))
    last_applied = params.get("DmBlinkAutoTuneLastApplied") or {}
    last_applied_valid_sample_count = int(last_applied.get("sourceValidSampleCount", 0))
    same_source = int(last_applied.get("sourceUpdated", 0)) == source_updated
    not_enough_new_data = (
      last_applied_valid_sample_count > 0 and
      source_valid_sample_count - last_applied_valid_sample_count < AUTO_APPLY_MIN_NEW_VALID_SAMPLES
    )
    if source_updated <= 0 or source_valid_sample_count <= 0 or same_source or not_enough_new_data:
      return None
    previous = {
      key: int(params.get(param_key, return_default=True))
      for key, param_key in AUTO_APPLY_PARAM_KEYS.items()
    }
  except (AttributeError, TypeError, ValueError, OverflowError):
    return None

  applied = {
    key: _bounded_step(previous[key], targets[key], AUTO_APPLY_MAX_STEP[key])
    for key in AUTO_APPLY_PARAM_KEYS
  }
  applied["closeThresholdPct"] = _clamp(applied["closeThresholdPct"], 5, 95)
  applied["openThresholdPct"] = _clamp(applied["openThresholdPct"], 5,
                                        applied["closeThresholdPct"] - 5)
  applied["minDurationMs"] = _clamp(applied["minDurationMs"], 50, 500)
  applied["minValidPct"] = _clamp(applied["minValidPct"], 50, 100)

  for key, param_key in AUTO_APPLY_PARAM_KEYS.items():
    params.put(param_key, str(applied[key]))

  record = {
    "sourceUpdated": source_updated,
    "sourceValidSampleCount": source_valid_sample_count,
    "appliedAt": int(time.time() if now is None else now),
    "confidencePct": int(state["confidencePct"]),
    "previous": previous,
    "target": targets,
    "applied": applied,
  }
  # Written last so an interrupted partial write is retried on the next DM start.
  params.put("DmBlinkAutoTuneLastApplied", record)
  return record


def _histogram_percentile(histogram, percentile):
  total = sum(histogram)
  if total <= 0:
    return None
  target = max(1, round(total * percentile))
  cumulative = 0
  for index, count in enumerate(histogram):
    cumulative += count
    if cumulative >= target:
      return index
  return len(histogram) - 1


def _weighted_two_cluster_centers(histogram):
  low_center, high_center = 10.0, 90.0
  for _ in range(12):
    low_weight = high_weight = 0
    low_sum = high_sum = 0.0
    midpoint = (low_center + high_center) * 0.5
    for probability, count in enumerate(histogram):
      if probability <= midpoint:
        low_weight += count
        low_sum += probability * count
      else:
        high_weight += count
        high_sum += probability * count
    if low_weight == 0 or high_weight == 0:
      return None
    new_low = low_sum / low_weight
    new_high = high_sum / high_weight
    if abs(new_low - low_center) < 0.01 and abs(new_high - high_center) < 0.01:
      break
    low_center, high_center = new_low, new_high

  total = low_weight + high_weight
  high_ratio = high_weight / total if total else 0.0
  if high_center - low_center < 25.0 or not 0.001 <= high_ratio <= 0.30:
    return None
  return low_center, high_center


def _recommended_probability_thresholds(histogram):
  cluster_centers = _weighted_two_cluster_centers(histogram)
  if cluster_centers is not None:
    low_center, high_center = cluster_centers
    probability_gap = high_center - low_center
    close_pct = _clamp(round(low_center + probability_gap * 0.80), 50, 95)
    open_pct = _clamp(round(low_center + probability_gap * 0.45), 5, close_pct - 5)
    return close_pct, open_pct, "clusters"

  low_tail = _histogram_percentile(histogram, 0.10)
  open_pct = _histogram_percentile(histogram, 0.40)
  close_pct = _histogram_percentile(histogram, 0.90)
  if (low_tail is None or open_pct is None or close_pct is None or
      close_pct - low_tail < 25 or close_pct - open_pct < 15):
    return None

  close_pct = _clamp(close_pct, 50, 95)
  open_pct = _clamp(open_pct, 5, close_pct - 5)
  return close_pct, open_pct, "percentiles"


@dataclass
class BlinkAutoTuner:
  sample_count: int = 0
  valid_sample_count: int = 0
  closure_count: int = 0
  blink_histogram: list[int] = field(default_factory=lambda: [0] * 101)
  valid_ratio_histogram: list[int] = field(default_factory=lambda: [0] * 101)
  closure_duration_histogram: list[int] = field(default_factory=lambda: [0] * 101)
  was_closed: bool = False
  current_closure_ms: int = 0

  @classmethod
  def from_dict(cls, state):
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
      return cls()

    def nonnegative_int(name):
      try:
        return max(0, int(state.get(name, 0)))
      except (TypeError, ValueError, OverflowError):
        return 0

    def histogram(name):
      values = state.get(name)
      if not isinstance(values, list) or len(values) != 101:
        return [0] * 101
      try:
        return [max(0, int(value)) for value in values]
      except (TypeError, ValueError, OverflowError):
        return [0] * 101

    return cls(
      sample_count=nonnegative_int("sampleCount"),
      valid_sample_count=nonnegative_int("validSampleCount"),
      closure_count=nonnegative_int("closureCount"),
      blink_histogram=histogram("blinkHistogram"),
      valid_ratio_histogram=histogram("validRatioHistogram"),
      closure_duration_histogram=histogram("closureDurationHistogram"),
    )

  def observe(self, valid, effective_blink_prob, eye_closed, current_closure_ms, valid_ratio_percent):
    self.sample_count += 1
    valid_ratio_bin = _clamp(round(valid_ratio_percent), 0, 100)
    self.valid_ratio_histogram[valid_ratio_bin] += 1

    if valid:
      self.valid_sample_count += 1
      probability_bin = _clamp(round(effective_blink_prob * 100.0), 0, 100)
      self.blink_histogram[probability_bin] += 1

    if eye_closed:
      self.current_closure_ms = max(self.current_closure_ms, int(current_closure_ms))
    elif self.was_closed and self.current_closure_ms > 0:
      duration_bin = _clamp(round(self.current_closure_ms / 50.0), 0, 100)
      self.closure_duration_histogram[duration_bin] += 1
      self.closure_count += 1
      self.current_closure_ms = 0
    self.was_closed = bool(eye_closed)

  def pause(self):
    self.was_closed = False
    self.current_closure_ms = 0

  @property
  def valid_minutes(self):
    return self.valid_sample_count / (SAMPLE_RATE_HZ * 60.0)

  @property
  def valid_percent(self):
    return round(100.0 * self.valid_sample_count / self.sample_count) if self.sample_count else 0

  def recommendations(self, current):
    probability_thresholds = _recommended_probability_thresholds(self.blink_histogram)
    enough_data = self.valid_minutes >= MIN_VALID_MINUTES and self.closure_count >= MIN_CLOSURE_EVENTS
    ready = enough_data and probability_thresholds is not None
    recommendation_mode = probability_thresholds[2] if probability_thresholds is not None else "unavailable"

    recommendations = dict(current)
    if ready:
      close_pct, open_pct, _ = probability_thresholds
      min_duration_bin = _histogram_percentile(self.closure_duration_histogram, 0.10)
      min_duration_ms = _clamp((min_duration_bin or 1) * 50, 50, 300)
      valid_pct = _histogram_percentile(self.valid_ratio_histogram, 0.10)
      min_valid_pct = _clamp(((valid_pct or 50) // 5) * 5, 50, 95)
      recommendations.update({
        "closeThresholdPct": close_pct,
        "openThresholdPct": open_pct,
        "minDurationMs": min_duration_ms,
        # Blink upper bounds and sleep timing require labeled events, so baseline tuning preserves them.
        "maxBlinkDurationMs": int(current["maxBlinkDurationMs"]),
        "sleepCandidateDurationMs": int(current["sleepCandidateDurationMs"]),
        "minValidPct": min_valid_pct,
      })

    sample_score = min(self.valid_minutes / TARGET_CONFIDENCE_MINUTES, 1.0)
    closure_score = min(self.closure_count / TARGET_CONFIDENCE_CLOSURES, 1.0)
    confidence_pct = round(100.0 * min(sample_score, closure_score)) if probability_thresholds is not None else 0
    return ready, confidence_pct, recommendations, recommendation_mode

  def to_dict(self, current, now=None):
    ready, confidence_pct, recommendations, recommendation_mode = self.recommendations(current)
    return {
      "version": STATE_VERSION,
      "sampleCount": self.sample_count,
      "validSampleCount": self.valid_sample_count,
      "closureCount": self.closure_count,
      "blinkHistogram": self.blink_histogram,
      "validRatioHistogram": self.valid_ratio_histogram,
      "closureDurationHistogram": self.closure_duration_histogram,
      "ready": ready,
      "confidencePct": confidence_pct,
      "recommendationMode": recommendation_mode,
      "validMinutes": round(self.valid_minutes, 1),
      "validPercent": self.valid_percent,
      "lastUpdated": int(time.time() if now is None else now),
      "recommendations": recommendations,
    }
