from cereal import log
from openpilot.common.realtime import DT_DMON
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.monitoring.policy import BlinkDebugSettings, BlinkEventTracker, DriverMonitoring, DRIVER_MONITOR_SETTINGS

EventName = log.OnroadEvent.EventName
dm_settings = DRIVER_MONITOR_SETTINGS()

TEST_TIMESPAN = 120  # seconds
DISTRACTED_SECONDS_TO_ORANGE = dm_settings._VISION_POLICY_ALERT_2_TIMEOUT + 1
DISTRACTED_SECONDS_TO_RED = dm_settings._VISION_POLICY_ALERT_3_TIMEOUT + 1
INVISIBLE_SECONDS_TO_ORANGE = dm_settings._WHEELTOUCH_POLICY_ALERT_2_TIMEOUT + 1
INVISIBLE_SECONDS_TO_RED = dm_settings._WHEELTOUCH_POLICY_ALERT_3_TIMEOUT + 1

def make_msg(face_detected, distracted=False, model_uncertain=False):
  ds = log.DriverStateV2.new_message()
  ds.leftDriverData.faceOrientation = [0., 0., 0.]
  ds.leftDriverData.facePosition = [0., 0.]
  ds.leftDriverData.faceProb = 1. * face_detected
  ds.leftDriverData.leftEyeProb = 1.
  ds.leftDriverData.rightEyeProb = 1.
  ds.leftDriverData.leftBlinkProb = 1. * distracted
  ds.leftDriverData.rightBlinkProb = 1. * distracted
  ds.leftDriverData.faceOrientationStd = [1.*model_uncertain, 1.*model_uncertain, 1.*model_uncertain]
  ds.leftDriverData.facePositionStd = [1.*model_uncertain, 1.*model_uncertain]
  # TODO: test both separately when e2e is used
  ds.leftDriverData.phoneProb = 0.
  return ds


# driver state from neural net, 20Hz
msg_NO_FACE_DETECTED = make_msg(False)
msg_ATTENTIVE = make_msg(True)
msg_DISTRACTED = make_msg(True, distracted=True)
msg_ATTENTIVE_UNCERTAIN = make_msg(True, model_uncertain=True)
msg_DISTRACTED_UNCERTAIN = make_msg(True, distracted=True, model_uncertain=True)
msg_DISTRACTED_BUT_SOMEHOW_UNCERTAIN = make_msg(True, distracted=True, model_uncertain=dm_settings._HI_STD_THRESHOLD*1.5)

# driver interaction with car
car_interaction_DETECTED = True
car_interaction_NOT_DETECTED = False

# some common state vectors
always_no_face = [msg_NO_FACE_DETECTED] * int(TEST_TIMESPAN / DT_DMON)
always_attentive = [msg_ATTENTIVE] * int(TEST_TIMESPAN / DT_DMON)
always_distracted = [msg_DISTRACTED] * int(TEST_TIMESPAN / DT_DMON)
always_true = [True] * int(TEST_TIMESPAN / DT_DMON)
always_false = [False] * int(TEST_TIMESPAN / DT_DMON)

class TestMonitoring:
  def setup_method(self):
    self.prefix = OpenpilotPrefix()
    self.prefix.__enter__()

  def teardown_method(self):
    self.prefix.__exit__(None, None, None)

  def _run_seq(self, msgs, interaction, engaged, lowspeed):
    DM = DriverMonitoring()
    alert_lvls = []
    for idx in range(len(msgs)):
      DM._update_states(msgs[idx], [0, 0, 0], 0, engaged[idx], lowspeed[idx])
      # cal_rpy and car_speed don't matter here

      # evaluate events at 10Hz for tests
      DM._update_events(interaction[idx], engaged[idx], lowspeed[idx], 0)
      alert_lvls.append(DM.alert_level)
    assert len(alert_lvls) == len(msgs), f"got {len(alert_lvls)} for {len(msgs)} driverState input msgs"
    return alert_lvls, DM


  # engaged, driver is attentive all the time
  def test_fully_aware_driver(self):
    alert_lvls, d_status = self._run_seq(always_attentive, always_false, always_true, always_false)
    assert all(a == 0 for a in alert_lvls)
    assert d_status.active_policy == log.DriverMonitoringState.MonitoringPolicy.vision

  # engaged, driver is distracted and does nothing
  def test_fully_distracted_driver(self):
    alert_lvls, d_status = self._run_seq(always_distracted, always_false, always_true, always_false)
    s = d_status.settings
    assert alert_lvls[int(s._VISION_POLICY_ALERT_1_TIMEOUT / 2 / DT_DMON)] == 0
    assert alert_lvls[int((s._VISION_POLICY_ALERT_1_TIMEOUT + \
                    (s._VISION_POLICY_ALERT_2_TIMEOUT - s._VISION_POLICY_ALERT_1_TIMEOUT) / 2) / DT_DMON)] == 1
    assert alert_lvls[int((s._VISION_POLICY_ALERT_2_TIMEOUT + \
                    (s._VISION_POLICY_ALERT_3_TIMEOUT - s._VISION_POLICY_ALERT_2_TIMEOUT) / 2) / DT_DMON)] == 2
    assert alert_lvls[int((s._VISION_POLICY_ALERT_3_TIMEOUT + \
                    (TEST_TIMESPAN - 10 - s._VISION_POLICY_ALERT_3_TIMEOUT) / 2) / DT_DMON)] == 3
    assert isinstance(d_status.awareness, float)

  # engaged, distracted past red and beyond the no-response window -> unavailability response + lockout
  def test_distracted_lockout(self):
    alert_lvls, d_status = self._run_seq(always_distracted, always_false, always_true, always_false)
    assert alert_lvls[int(DISTRACTED_SECONDS_TO_RED / DT_DMON)] == 3
    assert d_status.lockout_active
    assert d_status.lockout_time_elapsed > 0
    assert d_status.lockout_count >= 1

  # no face -> wheeltouch red, sustained past the no-response timeout -> unavailability response + lockout
  def test_invisible_lockout(self):
    _, d_status = self._run_seq(always_no_face, always_false, always_true, always_false)
    assert d_status.active_policy == log.DriverMonitoringState.MonitoringPolicy.wheeltouch
    assert d_status.lockout_active
    assert d_status.lockout_count >= 1

  # engaged, no face detected the whole time, no action
  def test_fully_invisible_driver(self):
    alert_lvls, d_status = self._run_seq(always_no_face, always_false, always_true, always_false)
    s = d_status.settings
    assert alert_lvls[int(s._WHEELTOUCH_POLICY_ALERT_1_TIMEOUT / 2 / DT_DMON)] == 0
    assert alert_lvls[int((s._WHEELTOUCH_POLICY_ALERT_1_TIMEOUT + \
                    (s._WHEELTOUCH_POLICY_ALERT_2_TIMEOUT - s._WHEELTOUCH_POLICY_ALERT_1_TIMEOUT) / 2) / DT_DMON)] == 1
    assert alert_lvls[int((s._WHEELTOUCH_POLICY_ALERT_2_TIMEOUT + \
                    (s._WHEELTOUCH_POLICY_ALERT_3_TIMEOUT - s._WHEELTOUCH_POLICY_ALERT_2_TIMEOUT) / 2) / DT_DMON)] == 2
    assert alert_lvls[int((s._WHEELTOUCH_POLICY_ALERT_3_TIMEOUT + \
                    (TEST_TIMESPAN - 10 - s._WHEELTOUCH_POLICY_ALERT_3_TIMEOUT) / 2) / DT_DMON)] == 3
    assert d_status.active_policy == log.DriverMonitoringState.MonitoringPolicy.wheeltouch

  # engaged, down to orange, driver pays attention, back to normal; then down to orange, driver touches wheel
  #  - should have short orange recovery time and no green afterwards; wheel touch only recovers when paying attention
  def test_normal_driver(self):
    ds_vector = [msg_DISTRACTED] * int(DISTRACTED_SECONDS_TO_ORANGE/DT_DMON) + \
                [msg_ATTENTIVE] * int(DISTRACTED_SECONDS_TO_ORANGE/DT_DMON) + \
                [msg_DISTRACTED] * int((DISTRACTED_SECONDS_TO_ORANGE+2)/DT_DMON) + \
                [msg_ATTENTIVE] * (int(TEST_TIMESPAN/DT_DMON)-int((DISTRACTED_SECONDS_TO_ORANGE*3+2)/DT_DMON))
    interaction_vector = [car_interaction_NOT_DETECTED] * int(DISTRACTED_SECONDS_TO_ORANGE*3/DT_DMON) + \
                         [car_interaction_DETECTED] * (int(TEST_TIMESPAN/DT_DMON)-int(DISTRACTED_SECONDS_TO_ORANGE*3/DT_DMON))
    alert_lvls, _ = self._run_seq(ds_vector, interaction_vector, always_true, always_false)
    assert alert_lvls[int(DISTRACTED_SECONDS_TO_ORANGE*0.5/DT_DMON)] == 0
    assert alert_lvls[int((DISTRACTED_SECONDS_TO_ORANGE-0.1)/DT_DMON)] == 2
    assert alert_lvls[int(DISTRACTED_SECONDS_TO_ORANGE*1.5/DT_DMON)] == 0
    assert alert_lvls[int((DISTRACTED_SECONDS_TO_ORANGE*3-0.1)/DT_DMON)] == 2
    assert alert_lvls[int((DISTRACTED_SECONDS_TO_ORANGE*3+0.1)/DT_DMON)] == 2
    assert alert_lvls[int((DISTRACTED_SECONDS_TO_ORANGE*3+2.5)/DT_DMON)] == 0

  # engaged, down to orange, driver dodges camera, then comes back still distracted, down to red, \
  #                          driver dodges, and then touches wheel to no avail, disengages and reengages
  #  - orange/red alert should remain after disappearance, and only disengaging clears red
  def test_biggest_comma_fan(self):
    _invisible_time = 2  # seconds
    ds_vector = always_distracted[:]
    interaction_vector = always_false[:]
    op_vector = always_true[:]
    ds_vector[int(DISTRACTED_SECONDS_TO_ORANGE/DT_DMON):int((DISTRACTED_SECONDS_TO_ORANGE+_invisible_time)/DT_DMON)] \
                                                        = [msg_NO_FACE_DETECTED] * int(_invisible_time/DT_DMON)
    ds_vector[int((DISTRACTED_SECONDS_TO_RED+_invisible_time)/DT_DMON):int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time)/DT_DMON)] \
                                                        = [msg_NO_FACE_DETECTED] * int(_invisible_time/DT_DMON)
    interaction_vector[int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+0.5)/DT_DMON):int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+1.5)/DT_DMON)] \
                                                        = [True] * int(1/DT_DMON)
    op_vector[int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+2.5)/DT_DMON):int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+3)/DT_DMON)] \
                                                        = [False] * int(0.5/DT_DMON)
    alert_lvls, _ = self._run_seq(ds_vector, interaction_vector, op_vector, always_false)
    assert alert_lvls[int((DISTRACTED_SECONDS_TO_ORANGE+0.5*_invisible_time)/DT_DMON)] == 2
    assert alert_lvls[int((DISTRACTED_SECONDS_TO_RED+1.5*_invisible_time)/DT_DMON)] == 3
    assert alert_lvls[int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+1.5)/DT_DMON)] == 3
    assert alert_lvls[int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+3.5)/DT_DMON)] == 0

  # engaged, invisible driver, down to orange, driver touches wheel; then down to orange again, driver appears
  #  - both actions should clear the alert, but momentary appearance should not
  def test_sometimes_transparent_commuter(self):
    for _visible_time in (0.5, 10):
      ds_vector = always_no_face[:]*2
      interaction_vector = always_false[:]*2
      ds_vector[int((2*INVISIBLE_SECONDS_TO_ORANGE+1)/DT_DMON):int((2*INVISIBLE_SECONDS_TO_ORANGE+1+_visible_time)/DT_DMON)] = \
                                                                                               [msg_ATTENTIVE] * int(_visible_time/DT_DMON)
      interaction_vector[int((INVISIBLE_SECONDS_TO_ORANGE)/DT_DMON):int((INVISIBLE_SECONDS_TO_ORANGE+1)/DT_DMON)] = [True] * int(1/DT_DMON)
      alert_lvls, _ = self._run_seq(ds_vector, interaction_vector, 2*always_true, 2*always_false)
      assert alert_lvls[int(dm_settings._WHEELTOUCH_POLICY_ALERT_1_TIMEOUT/2/DT_DMON)] == 0
      assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE-0.1)/DT_DMON)] == 2
      assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE+0.1)/DT_DMON)] == 0
      if _visible_time == 0.5:
        assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE*2+1-0.1)/DT_DMON)] == 2
        assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE*2+1+0.1+_visible_time)/DT_DMON)] == 2
      elif _visible_time == 10:
        assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE*2+1-0.1)/DT_DMON)] == 2
        assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE*2+1+0.1+_visible_time)/DT_DMON)] == 0

  # engaged, invisible driver, down to red, driver appears and then touches wheel, then disengages/reengages
  #  - only disengage will clear the alert
  def test_last_second_responder(self):
    _visible_time = 2  # seconds
    ds_vector = always_no_face[:]
    interaction_vector = always_false[:]
    op_vector = always_true[:]
    ds_vector[int(INVISIBLE_SECONDS_TO_RED/DT_DMON):int((INVISIBLE_SECONDS_TO_RED+_visible_time)/DT_DMON)] = [msg_ATTENTIVE] * int(_visible_time/DT_DMON)
    interaction_vector[int((INVISIBLE_SECONDS_TO_RED+_visible_time)/DT_DMON):int((INVISIBLE_SECONDS_TO_RED+_visible_time+1)/DT_DMON)] = [True] * int(1/DT_DMON)
    op_vector[int((INVISIBLE_SECONDS_TO_RED+_visible_time+1)/DT_DMON):int((INVISIBLE_SECONDS_TO_RED+_visible_time+0.5)/DT_DMON)] = [False] * int(0.5/DT_DMON)
    alert_lvls, _ = self._run_seq(ds_vector, interaction_vector, op_vector, always_false)
    assert alert_lvls[int(dm_settings._WHEELTOUCH_POLICY_ALERT_1_TIMEOUT/2/DT_DMON)] == 0
    assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE-0.1)/DT_DMON)] == 2
    assert alert_lvls[int((INVISIBLE_SECONDS_TO_RED-0.1)/DT_DMON)] == 3
    assert alert_lvls[int((INVISIBLE_SECONDS_TO_RED+0.5*_visible_time)/DT_DMON)] == 3
    assert alert_lvls[int((INVISIBLE_SECONDS_TO_RED+_visible_time+0.5)/DT_DMON)] == 3
    assert alert_lvls[int((INVISIBLE_SECONDS_TO_RED+_visible_time+1+0.1)/DT_DMON)] == 0

  # disengaged, always distracted driver
  #  - dm should stay quiet when not engaged
  def test_pure_dashcam_user(self):
    alert_lvls, _ = self._run_seq(always_distracted, always_false, always_false, always_false)
    assert all(a == 0 for a in alert_lvls)

  # engaged, car stops at traffic light, down to orange, no action, then car starts moving
  #  - should only reach green when stopped, but continues counting down on launch
  def test_long_traffic_light_victim(self):
    _redlight_time = 60  # seconds
    lowspeed_vector = always_true[:]
    lowspeed_vector[int(_redlight_time/DT_DMON):] = [False] * int((TEST_TIMESPAN-_redlight_time)/DT_DMON)
    alert_lvls, d_status = self._run_seq(always_distracted, always_false, always_true, lowspeed_vector)
    s = d_status.settings
    assert alert_lvls[int((_redlight_time-0.1)/DT_DMON)] == 0
    _alert_1_to_2 = s._VISION_POLICY_ALERT_2_TIMEOUT - s._VISION_POLICY_ALERT_1_TIMEOUT
    assert alert_lvls[int((_redlight_time+0.5)/DT_DMON)] == 1
    assert alert_lvls[int((_redlight_time+_alert_1_to_2+0.5)/DT_DMON)] == 2

  # engaged, distracted while moving, then car stops after reaching orange
  #  - should reset timer to pre green at low speed
  def test_distracted_then_stops(self):
    _stop_time = DISTRACTED_SECONDS_TO_ORANGE + 1  # stop 1 second after reaching orange
    lowspeed_vector = always_false[:]
    lowspeed_vector[int(_stop_time/DT_DMON):] = [True] * int((TEST_TIMESPAN-_stop_time)/DT_DMON)
    alert_lvls, _ = self._run_seq(always_distracted, always_false, always_true, lowspeed_vector)
    # just before and briefly after stopping: orange alert; goes away quickly after stopped
    assert alert_lvls[int((_stop_time+0.1)/DT_DMON)] == 2
    assert alert_lvls[int((_stop_time+0.5)/DT_DMON)] == 0

  # engaged, model is somehow uncertain and driver is distracted
  #  - should fall back to wheel touch after uncertain alert
  def test_somehow_indecisive_model(self):
    ds_vector = [msg_DISTRACTED_BUT_SOMEHOW_UNCERTAIN] * int(TEST_TIMESPAN/DT_DMON)
    interaction_vector = always_false[:]
    alert_lvls, d_status = self._run_seq(ds_vector, interaction_vector, always_true, always_false)
    s = d_status.settings
    assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE-1+DT_DMON*s._HI_STD_FALLBACK_TIME-0.1)/DT_DMON)] == 1
    assert alert_lvls[int((INVISIBLE_SECONDS_TO_ORANGE-1+DT_DMON*s._HI_STD_FALLBACK_TIME+0.1)/DT_DMON)] == 2
    assert alert_lvls[int((INVISIBLE_SECONDS_TO_RED-1+DT_DMON*s._HI_STD_FALLBACK_TIME+0.1)/DT_DMON)] == 3


class TestBlinkEventTracker:
  def setup_method(self):
    self.settings = BlinkDebugSettings(close_threshold=0.87, open_threshold=0.50,
                                       min_duration=0.10, max_blink_duration=1.50,
                                       sleep_candidate_duration=10.0,
                                       min_valid_ratio=0.80)
    self.tracker = BlinkEventTracker(self.settings)

  def update_for(self, seconds, probability, valid=True):
    for _ in range(round(seconds / DT_DMON)):
      self.tracker.update(valid, probability, probability, probability, 0.1)

  def test_counts_one_blink_on_closed_to_open_transition(self):
    self.update_for(0.20, 0.95)
    self.update_for(0.05, 0.10)
    assert self.tracker.blink_count == 1
    assert not self.tracker.eye_closed

  def test_counts_closure_at_configured_maximum_as_blink(self):
    self.update_for(1.50, 0.95)
    self.update_for(0.05, 0.10)
    assert self.tracker.blink_count == 1

  def test_ignores_short_probability_spike(self):
    self.update_for(DT_DMON, 0.95)
    self.update_for(DT_DMON, 0.10)
    assert self.tracker.blink_count == 0

  def test_sleep_candidate_uses_ten_second_closure_not_repeated_blinks(self):
    self.update_for(9.95, 0.95)
    assert not self.tracker.sleep_candidate
    self.update_for(0.10, 0.95)
    assert self.tracker.sleep_candidate
    self.update_for(DT_DMON, 0.10)
    assert self.tracker.blink_count == 0
    assert self.tracker.max_closure >= 10.0

  def test_sleep_candidate_ignores_invalid_frames_until_valid_open(self):
    self.update_for(10.05, 0.95)
    assert self.tracker.sleep_candidate

    self.update_for(0.50, 0.0, valid=False)
    assert self.tracker.sleep_candidate
    assert self.tracker.sleep_warning_candidate
    assert not self.tracker.sleep_warning_candidate_started

    self.update_for(DT_DMON, 0.10)
    assert not self.tracker.sleep_candidate

  def test_closure_above_blink_max_is_not_counted_as_blink(self):
    self.update_for(2.0, 0.95)
    assert not self.tracker.sleep_candidate
    self.update_for(DT_DMON, 0.10)
    assert self.tracker.blink_count == 0

  def test_invalid_samples_do_not_end_or_extend_closure(self):
    self.update_for(0.10, 0.95)
    closed_duration = self.tracker.closed_duration
    self.update_for(0.50, 0.0, valid=False)
    assert self.tracker.eye_closed
    assert self.tracker.closed_duration == closed_duration
    assert not self.tracker.sleep_candidate

  def test_blink_expires_from_ten_second_window(self):
    self.update_for(0.20, 0.95)
    self.update_for(0.05, 0.10)
    assert self.tracker.blink_count == 1
    self.update_for(10.05, 0.10)
    assert self.tracker.blink_count == 0

  def test_no_blink_candidate_requires_full_ten_second_window(self):
    self.update_for(9.95, 0.10)
    assert not self.tracker.no_blink_candidate
    self.update_for(0.05, 0.10)
    assert self.tracker.no_blink_candidate
    assert self.tracker.no_blink_candidate_started

  def test_no_blink_candidate_ignores_invalid_frames(self):
    self.update_for(10.0, 0.10)
    assert self.tracker.no_blink_candidate

    self.update_for(0.50, 0.0, valid=False)
    assert self.tracker.no_blink_candidate
    assert not self.tracker.no_blink_candidate_started
    self.update_for(DT_DMON, 0.10)
    assert self.tracker.no_blink_candidate
    assert not self.tracker.no_blink_candidate_started

  def test_latched_no_blink_candidate_rearms_after_completed_blink(self):
    self.update_for(10.0, 0.10)
    assert self.tracker.no_blink_candidate

    self.update_for(0.20, 0.95)
    assert self.tracker.no_blink_candidate
    self.update_for(DT_DMON, 0.10)
    assert not self.tracker.no_blink_candidate

    self.update_for(9.95, 0.10)
    assert not self.tracker.no_blink_candidate
    self.update_for(DT_DMON, 0.10)
    assert self.tracker.no_blink_candidate

  def test_valid_blink_restarts_no_blink_window(self):
    self.update_for(9.90, 0.10)
    self.update_for(0.20, 0.95)
    self.update_for(0.05, 0.10)
    assert not self.tracker.no_blink_candidate
    self.update_for(9.95, 0.10)
    assert not self.tracker.no_blink_candidate
    self.update_for(0.05, 0.10)
    assert self.tracker.no_blink_candidate

  def test_driver_interaction_restarts_no_blink_window(self):
    self.update_for(10.0, 0.10)
    assert self.tracker.no_blink_candidate
    self.tracker.acknowledge_driver_interaction()
    assert not self.tracker.no_blink_candidate
    self.update_for(9.95, 0.10)
    assert not self.tracker.no_blink_candidate
    self.update_for(0.05, 0.10)
    assert self.tracker.no_blink_candidate

  def test_threshold_param_bounds_and_hysteresis(self):
    class ParamsStub:
      def __init__(self, close_pct, open_pct, extra_values=None):
        self.values = {
          "DmBlinkCloseThresholdPct": str(close_pct),
          "DmBlinkOpenThresholdPct": str(open_pct),
        }
        self.values.update(extra_values or {})

      def get(self, key):
        return self.values.get(key)

      def get_bool(self, key):
        return False

    cases = (
      (0, 0, 0.05, 0.05),
      (5, 5, 0.05, 0.05),
      (9, 9, 0.09, 0.05),
      (10, 10, 0.10, 0.05),
      (95, 99, 0.95, 0.90),
    )
    for close_pct, open_pct, expected_close, expected_open in cases:
      settings = BlinkDebugSettings.from_params(ParamsStub(close_pct, open_pct))
      assert settings.close_threshold == expected_close
      assert settings.open_threshold == expected_open
      assert settings.max_blink_duration == 1.50
      assert settings.sleep_candidate_duration == 10.0

    custom = BlinkDebugSettings.from_params(ParamsStub(87, 50, {
      "DmBlinkMinDurationMs": "500",
      "DmBlinkMaxDurationMs": "500",
      "DmSleepCandidateDurationMs": "2000",
    }))
    assert custom.min_duration == 0.50
    assert custom.max_blink_duration == 0.60
    assert custom.sleep_candidate_duration == 2.0

    bounded = BlinkDebugSettings.from_params(ParamsStub(87, 50, {
      "DmBlinkMaxDurationMs": "9999",
      "DmSleepCandidateDurationMs": "1",
    }))
    assert bounded.max_blink_duration == 3.0
    assert bounded.sleep_candidate_duration == 4.0


class TestBlinkAlertLink:
  def setup_method(self):
    self.prefix = OpenpilotPrefix()
    self.prefix.__enter__()

  def teardown_method(self):
    self.prefix.__exit__(None, None, None)

  @staticmethod
  def update_for(dm, seconds, probability, update_events=False, driver_interacting=False,
                 op_engaged=True, lowspeed=False, cancel_pressed=False):
    msg = make_msg(True)
    msg.leftDriverData.leftBlinkProb = probability
    msg.leftDriverData.rightBlinkProb = probability
    for _ in range(round(seconds / DT_DMON)):
      dm._update_states(msg, [0, 0, 0], 0, op_engaged, lowspeed)
      if update_events:
        dm._update_events(driver_interacting, op_engaged, lowspeed, False, cancel_pressed)

  def test_linked_sleep_candidate_ignores_closures_below_two_seconds(self):
    blink_settings = BlinkDebugSettings(alert_enabled=True, close_threshold=0.75,
                                        open_threshold=0.50, sleep_candidate_duration=0.10)
    dm = DriverMonitoring(blink_debug_settings=blink_settings)
    self.update_for(dm, 0.15, 0.80)

    assert dm.blink_tracker.sleep_candidate
    assert not dm.blink_tracker.no_blink_candidate
    assert not dm.distracted_types['eye']

  def test_no_blink_mode_starts_first_warning_at_ten_seconds(self):
    dm = DriverMonitoring(blink_debug_settings=BlinkDebugSettings(alert_enabled=True))
    self.update_for(dm, 9.95, 0.10, update_events=True)
    assert dm.alert_level == 0
    self.update_for(dm, 0.05, 0.10, update_events=True)

    assert dm.blink_tracker.no_blink_candidate
    assert dm.distracted_types['eye']
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.one

  def test_no_blink_observation_starts_only_while_monitoring_is_active(self):
    dm = DriverMonitoring(blink_debug_settings=BlinkDebugSettings(alert_enabled=True))
    self.update_for(dm, 20.0, 0.10, op_engaged=False)
    assert dm.blink_tracker.no_blink_duration == 0.0
    assert not dm.blink_tracker.no_blink_candidate

    self.update_for(dm, 10.0, 0.10, update_events=True)
    assert dm.blink_tracker.no_blink_candidate
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.one

  def test_driver_interaction_immediately_clears_no_blink_warning(self):
    dm = DriverMonitoring(blink_debug_settings=BlinkDebugSettings(alert_enabled=True, dismiss_on_driver_input=True))
    self.update_for(dm, 10.0, 0.10, update_events=True)
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.one

    self.update_for(dm, DT_DMON, 0.10, update_events=True, driver_interacting=True)
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.none
    assert dm.awareness == 1.0
    assert not dm.blink_tracker.no_blink_candidate
    assert not dm.distracted_types['eye']

  def test_linked_sleep_candidate_starts_first_warning_immediately(self):
    blink_settings = BlinkDebugSettings(alert_enabled=True, close_threshold=0.75,
                                        open_threshold=0.50, sleep_candidate_duration=2.0)
    dm = DriverMonitoring(blink_debug_settings=blink_settings)
    self.update_for(dm, 2.0, 0.80, update_events=True)
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.none

    self.update_for(dm, 0.05, 0.80, update_events=True)

    assert dm.blink_tracker.sleep_warning_candidate
    assert not dm.blink_tracker.no_blink_candidate
    assert dm.distracted_types['eye']
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.one

  def test_unlinked_sleep_candidate_is_debug_only(self):
    blink_settings = BlinkDebugSettings(enabled=True, alert_enabled=False, close_threshold=0.70,
                                        open_threshold=0.50, sleep_candidate_duration=2.0)
    dm = DriverMonitoring(blink_debug_settings=blink_settings)
    self.update_for(dm, 2.05, 0.75, update_events=True)

    assert dm.blink_tracker.sleep_warning_candidate
    assert not dm.blink_tracker.no_blink_candidate
    assert not dm.distracted_types['eye']
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.none

  def test_debug_visibility_does_not_change_existing_eye_warning(self):
    for debug_enabled in (False, True):
      blink_settings = BlinkDebugSettings(enabled=debug_enabled, alert_enabled=False)
      dm = DriverMonitoring(blink_debug_settings=blink_settings)
      self.update_for(dm, DT_DMON, 0.90)

      assert dm.distracted_types['eye']

  def test_cancel_immediately_resets_warning_even_when_driver_input_dismiss_is_off(self):
    dm = DriverMonitoring(blink_debug_settings=BlinkDebugSettings(alert_enabled=True, dismiss_on_driver_input=False))
    self.update_for(dm, 10.0, 0.10, update_events=True)
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.one

    self.update_for(dm, DT_DMON, 0.10, update_events=True, cancel_pressed=True)
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.none
    assert dm.awareness == 1.0
    assert dm.driver_distraction_filter.x == 0.0
    assert not dm.blink_tracker.no_blink_candidate
    assert not dm.distracted_types['eye']

  def test_cancel_immediately_resets_emergency_warning(self):
    dm = DriverMonitoring(blink_debug_settings=BlinkDebugSettings(alert_enabled=True, dismiss_on_driver_input=False))
    self.update_for(dm, 18.2, 0.10, update_events=True)
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.three
    assert dm.awareness <= 0.0
    alert_3_count = dm.alert_3_cnt

    self.update_for(dm, DT_DMON, 0.10, update_events=True, cancel_pressed=True)
    assert dm.alert_level == log.DriverMonitoringState.AlertLevel.none
    assert dm.awareness == 1.0
    assert dm.alert_3_cnt == alert_3_count
    assert not dm.blink_tracker.no_blink_candidate

  def test_existing_blink_warning_remains_enabled(self):
    blink_settings = BlinkDebugSettings(alert_enabled=False, close_threshold=0.95,
                                        open_threshold=0.50, sleep_candidate_duration=0.10)
    dm = DriverMonitoring(blink_debug_settings=blink_settings)
    self.update_for(dm, DT_DMON, 0.90)

    assert not dm.blink_tracker.sleep_candidate
    assert dm.distracted_types['eye']
