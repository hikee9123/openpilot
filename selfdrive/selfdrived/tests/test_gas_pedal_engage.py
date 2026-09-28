import unittest
from types import SimpleNamespace

from selfdrive.selfdrived.gas_pedal_engage import (
  gas_pedal_engage_requested,
  stock_cruise_disable_requested,
  update_gas_pedal_press_frames,
)


def make_state(*, gas_pressed=False, main_on=True, cruise_enabled=False, can_valid=True, brake_pressed=False,
               door_open=False, seatbelt_unlatched=False, parking_brake=False, acc_faulted=False,
               block_pcm_enable=False):
  return SimpleNamespace(
    canValid=can_valid,
    gasPressed=gas_pressed,
    brakePressed=brake_pressed,
    doorOpen=door_open,
    seatbeltUnlatched=seatbelt_unlatched,
    parkingBrake=parking_brake,
    accFaulted=acc_faulted,
    blockPcmEnable=block_pcm_enable,
    cruiseState=SimpleNamespace(available=main_on, enabled=cruise_enabled),
  )


def make_params(*, brand="hyundai", openpilot_longitudinal=False):
  return SimpleNamespace(brand=brand, openpilotLongitudinalControl=openpilot_longitudinal)


class TestGasPedalEngage(unittest.TestCase):
  def setUp(self):
    self.requested = gas_pedal_engage_requested

  def test_gas_pedal_engages_after_debounced_new_press_with_hyundai_acc_main_on(self):
    params = make_params()
    state = make_state(gas_pressed=True)
    previous_state = make_state()

    self.assertFalse(self.requested(params, state, previous_state, 15, True, False, False,
                                    panda_controls_allowed=False, panda_rx_checks_valid=True))
    self.assertTrue(self.requested(params, state, previous_state, 15, True, False, False,
                                   panda_controls_allowed=True, panda_rx_checks_valid=True))

  def test_gas_pedal_engage_waits_for_valid_panda_permission(self):
    params = make_params()
    state = make_state(gas_pressed=True)
    previous_state = make_state()

    self.assertFalse(self.requested(params, state, previous_state, 15, True, False, False,
                                    panda_controls_allowed=True, panda_rx_checks_valid=False))

  def test_gas_pedal_engage_requires_opt_in_and_safe_vehicle_state(self):
    params = make_params()
    previous_state = make_state()

    self.assertFalse(self.requested(params, make_state(gas_pressed=True), previous_state, 15, False, False, False,
                                    panda_controls_allowed=True, panda_rx_checks_valid=True))
    unsafe_states = (
      make_state(gas_pressed=True, main_on=False),
      make_state(gas_pressed=True, can_valid=False),
      make_state(gas_pressed=True, brake_pressed=True),
      make_state(gas_pressed=True, door_open=True),
      make_state(gas_pressed=True, seatbelt_unlatched=True),
      make_state(gas_pressed=True, parking_brake=True),
      make_state(gas_pressed=True, acc_faulted=True),
    )
    for state in unsafe_states:
      with self.subTest(state=state):
        self.assertFalse(self.requested(params, state, previous_state, 15, True, False, False,
                                        panda_controls_allowed=True, panda_rx_checks_valid=True))

  def test_gas_pedal_reengages_when_stock_acc_is_already_active(self):
    state = make_state(gas_pressed=True, cruise_enabled=True)
    self.assertTrue(self.requested(make_params(), state, make_state(), 15, True, False, False,
                                   panda_controls_allowed=True, panda_rx_checks_valid=True))

  def test_gas_pedal_press_is_allowed_without_recent_cruise_button(self):
    state = make_state(gas_pressed=True, block_pcm_enable=True)
    self.assertTrue(self.requested(make_params(), state, make_state(), 15, True, False, False,
                                   panda_controls_allowed=True, panda_rx_checks_valid=True))

  def test_gas_pedal_engage_requires_valid_previous_sample_and_debounce_window(self):
    params = make_params()
    state = make_state(gas_pressed=True)

    self.assertFalse(self.requested(params, state, make_state(can_valid=False), 15, True, False, False,
                                    panda_controls_allowed=True, panda_rx_checks_valid=True))
    self.assertFalse(self.requested(params, state, make_state(), 14, True, False, False,
                                    panda_controls_allowed=True, panda_rx_checks_valid=True))
    self.assertTrue(self.requested(params, state, make_state(), 16, True, False, False,
                                   panda_controls_allowed=True, panda_rx_checks_valid=True))

  def test_gas_pedal_press_counter_requires_a_fresh_valid_edge_and_resets_on_release(self):
    state = make_state(gas_pressed=True)
    previous_state = make_state()
    self.assertEqual(1, update_gas_pedal_press_frames(0, state, previous_state))
    self.assertEqual(15, update_gas_pedal_press_frames(14, state, make_state(gas_pressed=True)))
    self.assertEqual(0, update_gas_pedal_press_frames(14, state, make_state(can_valid=False)))
    self.assertEqual(0, update_gas_pedal_press_frames(14, make_state(gas_pressed=True, main_on=False),
                                                      make_state(gas_pressed=True)))
    self.assertEqual(0, update_gas_pedal_press_frames(14, make_state(), previous_state))

  def test_stock_acc_inactive_does_not_disengage_after_gas_triggered_engage(self):
    self.assertFalse(stock_cruise_disable_requested(cruise_enabled=False, gas_pedal_engage_active=True))
    self.assertTrue(stock_cruise_disable_requested(cruise_enabled=False, gas_pedal_engage_active=False))
    self.assertFalse(stock_cruise_disable_requested(cruise_enabled=True, gas_pedal_engage_active=False))

  def test_gas_pedal_engage_does_not_conflict_with_longitudinal_or_disengage_setting(self):
    previous_state = make_state()
    state = make_state(gas_pressed=True)

    self.assertFalse(self.requested(make_params(openpilot_longitudinal=True), state, previous_state,
                                    15, True, False, False, panda_controls_allowed=True, panda_rx_checks_valid=True))
    self.assertFalse(self.requested(make_params(), state, previous_state, 15, True, True, False,
                                    panda_controls_allowed=True, panda_rx_checks_valid=True))

  def test_gas_pedal_engage_requires_disengaged_openpilot(self):
    self.assertFalse(self.requested(make_params(), make_state(gas_pressed=True), make_state(),
                                    15, True, False, True, panda_controls_allowed=True, panda_rx_checks_valid=True))

  def test_gas_pedal_engage_is_hyundai_only(self):
    self.assertFalse(self.requested(make_params(brand="toyota"), make_state(gas_pressed=True),
                                    make_state(), 15, True, False, False,
                                    panda_controls_allowed=True, panda_rx_checks_valid=True))
