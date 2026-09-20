import pytest

from cereal import log
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.common.realtime import DT_DMON
from openpilot.selfdrive.monitoring.policy import DriverMonitoring
from openpilot.selfdrive.monitoring.test_monitoring import make_msg


@pytest.fixture
def dm():
  with OpenpilotPrefix():
    yield DriverMonitoring()


@pytest.mark.parametrize("sleep_prob, distracted", [(0.0, False), (0.75, False), (0.76, True), (1.0, True)])
def test_official_sleep_threshold_and_state_packet(dm, sleep_prob, distracted):
  msg = make_msg(True)
  msg.leftDriverData.sleepProb = sleep_prob
  dm._update_states(msg, [0., 0., 0.], 30., True, False)

  assert dm.distracted_types['sleep'] == distracted
  assert dm.driver_distracted == distracted
  assert not dm.distracted_types['eye']
  packet = dm.get_state_packet().driverMonitoringState
  assert packet.visionPolicyState.distractedTypes.sleep == distracted


def test_sleep_probability_follows_selected_driver(dm):
  msg = make_msg(True)
  msg.rightDriverData = msg.leftDriverData
  msg.leftDriverData.sleepProb = 0.
  msg.rightDriverData.sleepProb = 1.
  dm.wheel_on_right_default = True
  dm._update_states(msg, [0., 0., 0.], 30., True, False)
  assert dm.distracted_types['sleep']


def test_open_eyes_without_blinks_do_not_create_custom_warning(dm):
  msg = make_msg(True)
  for _ in range(int(30. / DT_DMON)):
    dm._update_states(msg, [0., 0., 0.], 30., True, False)
    dm._update_events(False, True, False, False)
  assert dm.alert_level == log.DriverMonitoringState.AlertLevel.none
  assert not dm.driver_distracted


def test_official_sleep_detection_escalates(dm):
  msg = make_msg(True)
  msg.leftDriverData.sleepProb = 1.
  for _ in range(int((dm.settings._VISION_POLICY_ALERT_3_TIMEOUT + 2.) / DT_DMON)):
    dm._update_states(msg, [0., 0., 0.], 30., True, False)
    dm._update_events(False, True, False, False)
  assert dm.alert_level == log.DriverMonitoringState.AlertLevel.three
