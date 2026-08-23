from dataclasses import dataclass, field
import time


SAMPLE_RATE_HZ = 20
MIN_VALID_MINUTES = 10
MIN_CLOSURE_EVENTS = 10
TARGET_CONFIDENCE_MINUTES = 30
TARGET_CONFIDENCE_CLOSURES = 50
STATE_VERSION = 1


def _clamp(value, minimum, maximum):
  return min(max(value, minimum), maximum)


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
    cluster_centers = _weighted_two_cluster_centers(self.blink_histogram)
    enough_data = self.valid_minutes >= MIN_VALID_MINUTES and self.closure_count >= MIN_CLOSURE_EVENTS
    ready = enough_data and cluster_centers is not None

    recommendations = dict(current)
    if ready:
      low_center, high_center = cluster_centers
      probability_gap = high_center - low_center
      close_pct = _clamp(round(low_center + probability_gap * 0.80), 50, 95)
      open_pct = _clamp(round(low_center + probability_gap * 0.45), 5, close_pct - 5)
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
    confidence_pct = round(100.0 * min(sample_score, closure_score)) if cluster_centers is not None else 0
    return ready, confidence_pct, recommendations

  def to_dict(self, current, now=None):
    ready, confidence_pct, recommendations = self.recommendations(current)
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
      "validMinutes": round(self.valid_minutes, 1),
      "validPercent": self.valid_percent,
      "lastUpdated": int(time.time() if now is None else now),
      "recommendations": recommendations,
    }
