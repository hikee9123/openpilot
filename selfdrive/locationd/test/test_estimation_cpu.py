import unittest
from unittest.mock import Mock, patch

import numpy as np

from openpilot.selfdrive.locationd.lagd import BlockAverage, LateralLagEstimator, Points
from rednose.helpers.kalmanfilter import KalmanFilter


class TestEstimationCpu(unittest.TestCase):
  def make_estimator(self, mode):
    estimator = LateralLagEstimator.__new__(LateralLagEstimator)
    estimator.dt = 0.05
    estimator.okay_window_sec = 25.0
    estimator.min_ncc = 0.95
    estimator.min_confidence = 0.7
    estimator.last_estimate_t = 0.0
    estimator.points = Points(1200)
    estimator.block_avg = BlockAverage(50, 100, 0, 0.4)
    for i in range(1200):
      t = i * estimator.dt
      scale = 0.1 if mode == 'low_range' else 0.3
      okay = mode != 'invalid' and (mode != 'no_new_valid' or i < 1100)
      estimator.points.update(t, scale * np.cos(10 * t), scale * np.cos(10 * (t - 0.3)), okay)
    estimator.t = t
    if mode == 'no_new_valid':
      estimator.last_estimate_t = 1100 * estimator.dt
    elif mode == 'same_time':
      estimator.last_estimate_t = t
    return estimator

  def test_rejected_windows_skip_correlation_and_preserve_state(self):
    for mode in ('invalid', 'low_range', 'no_new_valid', 'same_time'):
      with self.subTest(mode=mode):
        estimator = self.make_estimator(mode)
        old_time = estimator.last_estimate_t
        old_values = estimator.block_avg.values.copy()
        with patch.object(estimator, 'actuator_delay', side_effect=AssertionError('unnecessary correlation')):
          estimator.update_estimate()
        self.assertEqual(estimator.last_estimate_t, old_time)
        self.assertEqual(estimator.block_avg.idx, 0)
        np.testing.assert_array_equal(estimator.block_avg.values, old_values)

  def test_valid_window_still_estimates_delay(self):
    estimator = self.make_estimator('valid')
    with patch.object(estimator, 'actuator_delay', wraps=estimator.actuator_delay) as correlate:
      estimator.update_estimate()
    correlate.assert_called_once()
    self.assertEqual(estimator.block_avg.idx, 1)
    self.assertEqual(estimator.last_estimate_t, estimator.t)
    self.assertAlmostEqual(estimator.block_avg.values[0, 0], 0.3, delta=0.01)

  def test_filter_returns_backend_estimate(self):
    for supplied_noise in (False, True):
      with self.subTest(supplied_noise=supplied_noise):
        kf = KalmanFilter()
        estimate = object()
        kf.filter = Mock()
        kf.filter.predict_and_update_batch.return_value = estimate
        kf.obs_noise = {1: np.eye(3)}
        noise = np.eye(3)[None] if supplied_noise else None
        self.assertIs(kf.predict_and_observe(1.0, 1, np.zeros(3), noise), estimate)
        kf.filter.predict_and_update_batch.assert_called_once()

  def test_filter_preserves_rejected_observation(self):
    kf = KalmanFilter()
    kf.filter = Mock()
    kf.filter.predict_and_update_batch.return_value = None
    self.assertIsNone(kf.predict_and_observe(1.0, 1, np.zeros(3), np.eye(3)[None]))


if __name__ == '__main__':
  unittest.main()
