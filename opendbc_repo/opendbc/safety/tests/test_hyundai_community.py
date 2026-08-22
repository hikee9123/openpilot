#!/usr/bin/env python3
import unittest

from opendbc.car.hyundai.values import Buttons, HyundaiSafetyFlags
from opendbc.car.structs import CarParams
from opendbc.safety.tests.common import CANPackerPanda, make_msg
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_hyundai import checksum


class TestHyundaiCommunityClu11Guard(unittest.TestCase):
  STOCK_TIMEOUT = 50_000
  TX_MIN_INTERVAL = 100_000

  def setUp(self):
    self.safety = libsafety_py.libsafety
    self._init_safety()

  def _init_safety(self, safety_param=0):
    self.safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCommunity, safety_param)
    self.safety.init_tests()
    self.stock_counter = 0
    self.last_stock_counter = None

  @staticmethod
  def _scc11_msg(bus=0):
    data = bytearray(8)
    data[0] = 1  # MainMode_ACC
    return make_msg(bus, 0x420, 8, bytes(data))

  @staticmethod
  def _clu11_msg(button=Buttons.NONE, counter=0, bus=0, main_button=False, sld_main_button=False):
    data = bytearray(4)
    data[0] = int(button) | (int(main_button) << 3) | (int(sld_main_button) << 4)
    data[3] = (counter & 0xF) << 4
    return make_msg(bus, 0x4F1, 4, bytes(data))

  def _enable_generated_messages(self, bus=0):
    self.assertTrue(self.safety.safety_rx_hook(self._scc11_msg(bus)))

  def _stock_clu11(self, timestamp, bus=0, button=Buttons.NONE, main_button=False, sld_main_button=False):
    self.safety.set_timer(timestamp)
    msg = self._clu11_msg(button=button, counter=self.stock_counter, bus=bus,
                          main_button=main_button, sld_main_button=sld_main_button)
    accepted = self.safety.safety_rx_hook(msg)
    if accepted:
      self.last_stock_counter = self.stock_counter
      self.stock_counter = (self.stock_counter + 1) & 0xF
    return accepted

  def _host_clu11(self, timestamp, button=Buttons.CANCEL, bus=0, counter=None):
    self.safety.set_timer(timestamp)
    self.safety.set_controls_allowed(True)
    self.safety.set_cruise_engaged_prev(True)
    if counter is None:
      counter = 0 if self.last_stock_counter is None else (self.last_stock_counter + 1) & 0xF
    return self.safety.safety_tx_hook(self._clu11_msg(button=button, counter=counter, bus=bus))

  def test_stock_clu11_is_required(self):
    self._enable_generated_messages()
    self.assertFalse(self._host_clu11(1_000))

  def test_rate_limit_uses_last_accepted_transmission(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000))
    self.assertTrue(self._host_clu11(1_000))

    self.assertTrue(self._stock_clu11(10_000))
    self.assertFalse(self._host_clu11(10_000))
    self.assertTrue(self._stock_clu11(1_000 + self.TX_MIN_INTERVAL - 1))
    self.assertFalse(self._host_clu11(1_000 + self.TX_MIN_INTERVAL - 1))

    self.assertTrue(self._stock_clu11(1_000 + self.TX_MIN_INTERVAL))
    self.assertTrue(self._host_clu11(1_000 + self.TX_MIN_INTERVAL))

  def test_stock_timeout_boundary_and_recovery(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000))
    self.assertFalse(self._host_clu11(1_000 + self.STOCK_TIMEOUT))

    self.assertTrue(self._stock_clu11(1_000 + self.STOCK_TIMEOUT))
    self.assertTrue(self._host_clu11(1_000 + self.STOCK_TIMEOUT))

  def test_fresh_stock_boundary_is_allowed(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000))
    self.assertTrue(self._host_clu11(1_000 + self.STOCK_TIMEOUT - 1))

  def test_host_counter_must_follow_stock_counter(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000))
    self.assertFalse(self._host_clu11(1_000, counter=self.last_stock_counter))
    self.assertTrue(self._host_clu11(1_000))

  def test_newer_stock_frame_invalidates_old_host_counter(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000))
    old_host_counter = (self.last_stock_counter + 1) & 0xF

    self.assertTrue(self._stock_clu11(20_000))
    self.assertFalse(self._host_clu11(21_000, counter=old_host_counter))
    self.assertTrue(self._host_clu11(21_000))

  def test_physical_driver_button_blocks_host_button(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000, button=Buttons.SET_DECEL))
    self.assertFalse(self._host_clu11(1_000))

    self.assertTrue(self._stock_clu11(2_000))
    self.assertTrue(self._host_clu11(2_000))

  def test_physical_main_buttons_block_host_button(self):
    for field in ("main_button", "sld_main_button"):
      with self.subTest(field=field):
        self._init_safety()
        self._enable_generated_messages()
        self.assertTrue(self._stock_clu11(1_000, **{field: True}))
        self.assertFalse(self._host_clu11(1_000))
        self.assertTrue(self._stock_clu11(2_000))
        self.assertTrue(self._host_clu11(2_000))

  def test_changing_button_does_not_bypass_rate_limit(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000))
    self.assertTrue(self._host_clu11(1_000, Buttons.CANCEL))

    self.assertTrue(self._stock_clu11(10_000))
    self.assertFalse(self._host_clu11(10_000, Buttons.RES_ACCEL))

    self.assertTrue(self._stock_clu11(1_000 + self.TX_MIN_INTERVAL))
    self.assertTrue(self._host_clu11(1_000 + self.TX_MIN_INTERVAL, Buttons.SET_DECEL))

  def test_camera_scc_uses_bus_zero_stock_and_bus_two_host(self):
    self._init_safety(HyundaiSafetyFlags.CAMERA_SCC)
    self._enable_generated_messages(bus=2)

    self.assertFalse(self._stock_clu11(1_000, bus=2))
    self.assertFalse(self._host_clu11(1_000, bus=2))

    self.assertTrue(self._stock_clu11(2_000, bus=0))
    self.assertTrue(self._host_clu11(2_000, bus=2))

  def test_reinitialization_clears_rx_and_tx_timing(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000))
    self.assertTrue(self._host_clu11(1_000))

    self._init_safety()
    self._enable_generated_messages()
    self.assertFalse(self._host_clu11(1_000))
    self.assertTrue(self._stock_clu11(1_000))
    self.assertTrue(self._host_clu11(1_000))

  def test_timer_wrap_preserves_rate_limit(self):
    self._enable_generated_messages()
    start = 0xFFFFFF00
    after_interval = (start + self.TX_MIN_INTERVAL) & 0xFFFFFFFF

    self.assertTrue(self._stock_clu11(start))
    self.assertTrue(self._host_clu11(start))
    self.assertTrue(self._stock_clu11(after_interval))
    self.assertTrue(self._host_clu11(after_interval))

  def test_rejected_button_does_not_consume_interval(self):
    self._enable_generated_messages()
    self.assertTrue(self._stock_clu11(1_000))
    self.assertFalse(self._host_clu11(1_000, Buttons.GAP_DIST))

    self.assertTrue(self._stock_clu11(1_001))
    self.assertTrue(self._host_clu11(1_001, Buttons.CANCEL))


class TestHyundaiCommunityHdaTransform(unittest.TestCase):
  TX_MSGS = None
  SCC12_TIMEOUT = 100_000

  def setUp(self):
    self.packer = CANPackerPanda("hyundai_kia_generic")
    self.safety = libsafety_py.libsafety
    self.safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCommunity, 0)
    self.safety.init_tests()
    self.scc12_counter = 0

  def _scc12_msg(self, acc_mode, bus=0):
    values = {"ACCMode": acc_mode, "CR_VSM_Alive": self.scc12_counter % 16}
    self.scc12_counter += 1
    return self.packer.make_can_msg_panda("SCC12", bus, values, fix_checksum=checksum)

  @staticmethod
  def _lfahda_msg(hda_active=1, hda_icon_state=1, lfa_icon_state=1, bus=2):
    data = bytes([
      0x81 | (hda_active << 2) | (hda_icon_state << 3),
      0x57,
      0xB5,
      0xB0 | lfa_icon_state,
    ])
    return make_msg(bus, 0x485, 4, data)

  @staticmethod
  def _data(msg):
    return bytes(msg[0].data[i] for i in range(4))

  def _set_acc_state(self, acc_mode, timestamp=1_000, bus=0):
    self.safety.set_timer(timestamp)
    self.assertTrue(self.safety.safety_rx_hook(self._scc12_msg(acc_mode, bus)))

  def test_hda_wheel_for_all_fresh_acc_modes(self):
    self.safety.set_heartbeat_engaged(True)

    for acc_mode in range(4):
      with self.subTest(acc_mode=acc_mode):
        self._set_acc_state(acc_mode)
        msg = self._lfahda_msg()
        original = self._data(msg)
        self.safety.safety_fwd_transform(msg, 0)

        expected = bytes([
          original[0],
          original[1],
          original[2] | 0x10,
          original[3],
        ])
        self.assertEqual(expected, self._data(msg))

  def test_requires_openpilot_engagement(self):
    self._set_acc_state(1)
    msg = self._lfahda_msg()
    original = self._data(msg)

    self.safety.safety_fwd_transform(msg, 0)
    self.assertEqual(original, self._data(msg))

  def test_scc12_timeout_fails_open(self):
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1)

    fresh_msg = self._lfahda_msg()
    fresh_original = self._data(fresh_msg)
    self.safety.set_timer(1_000 + self.SCC12_TIMEOUT - 1)
    self.safety.safety_fwd_transform(fresh_msg, 0)
    self.assertEqual(fresh_original[0] & 0x18, fresh_msg[0].data[0] & 0x18)
    self.assertEqual(0x10, fresh_msg[0].data[2] & 0x10)

    stale_msg = self._lfahda_msg()
    original = self._data(stale_msg)
    self.safety.set_timer(1_000 + self.SCC12_TIMEOUT)
    self.safety.safety_fwd_transform(stale_msg, 0)
    self.assertEqual(original, self._data(stale_msg))

  def test_vehicle_hda_active_and_icon_states_are_preserved(self):
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1)

    for hda_active in (0, 1):
      for hda_icon_state in range(4):
        with self.subTest(hda_active=hda_active, hda_icon_state=hda_icon_state):
          msg = self._lfahda_msg(hda_active=hda_active, hda_icon_state=hda_icon_state)
          original = self._data(msg)
          self.safety.safety_fwd_transform(msg, 0)

          expected = bytes([
            original[0],
            original[1],
            original[2] | 0x10,
            original[3],
          ])
          self.assertEqual(expected, self._data(msg))

  def test_requires_stock_camera_route(self):
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1)

    for source_bus, destination_bus in ((0, 0), (2, 2)):
      with self.subTest(source_bus=source_bus, destination_bus=destination_bus):
        msg = self._lfahda_msg(bus=source_bus)
        original = self._data(msg)
        self.safety.safety_fwd_transform(msg, destination_bus)
        self.assertEqual(original, self._data(msg))

  def test_camera_scc_uses_bus_two_scc12_state(self):
    self.safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCommunity, HyundaiSafetyFlags.CAMERA_SCC)
    self.safety.init_tests()
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1, bus=2)

    msg = self._lfahda_msg()
    self.safety.safety_fwd_transform(msg, 0)
    self.assertEqual(0x10, msg[0].data[2] & 0x10)

  def test_other_safety_modes_leave_forwarded_data_unchanged(self):
    self.safety.set_safety_hooks(CarParams.SafetyModel.hyundai, 0)
    msg = self._lfahda_msg()
    original = self._data(msg)

    self.safety.safety_fwd_transform(msg, 0)
    self.assertEqual(original, self._data(msg))

  def test_stock_frame_is_forwarded_and_host_duplicate_is_blocked(self):
    self.assertEqual(0, self.safety.safety_fwd_hook(2, 0x485))
    self.assertFalse(self.safety.safety_tx_hook(self._lfahda_msg(bus=0)))

  def test_safety_reinitialization_clears_scc12_state(self):
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1)
    self.safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCommunity, 0)

    msg = self._lfahda_msg()
    original = self._data(msg)
    self.safety.safety_fwd_transform(msg, 0)
    self.assertEqual(original, self._data(msg))


if __name__ == "__main__":
  unittest.main()
