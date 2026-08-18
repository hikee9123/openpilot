#!/usr/bin/env python3
import unittest

from opendbc.car.hyundai.values import HyundaiSafetyFlags
from opendbc.car.structs import CarParams
from opendbc.safety.tests.common import CANPackerPanda, make_msg
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_hyundai import checksum


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
  def _lfahda_msg(hda_icon_state=1, lfa_icon_state=1, bus=2):
    data = bytes([
      0x85 | (hda_icon_state << 3),
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

  def test_green_lfa_for_active_acc_modes(self):
    self.safety.set_heartbeat_engaged(True)

    for acc_mode in (1, 2):
      with self.subTest(acc_mode=acc_mode):
        self._set_acc_state(acc_mode)
        msg = self._lfahda_msg()
        original = self._data(msg)
        self.safety.safety_fwd_transform(msg, 0)

        expected = original[:3] + bytes([(original[3] & 0xFC) | 0x02])
        self.assertEqual(expected, self._data(msg))

  def test_requires_openpilot_engagement(self):
    self._set_acc_state(1)
    msg = self._lfahda_msg()
    original = self._data(msg)

    self.safety.safety_fwd_transform(msg, 0)
    self.assertEqual(original, self._data(msg))

  def test_requires_active_acc(self):
    self.safety.set_heartbeat_engaged(True)

    for acc_mode in (0, 3):
      with self.subTest(acc_mode=acc_mode):
        self._set_acc_state(acc_mode)
        msg = self._lfahda_msg()
        original = self._data(msg)
        self.safety.safety_fwd_transform(msg, 0)
        self.assertEqual(original, self._data(msg))

  def test_scc12_timeout_fails_open(self):
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1)

    fresh_msg = self._lfahda_msg()
    self.safety.set_timer(1_000 + self.SCC12_TIMEOUT - 1)
    self.safety.safety_fwd_transform(fresh_msg, 0)
    self.assertEqual(2, fresh_msg[0].data[3] & 0x3)

    stale_msg = self._lfahda_msg()
    original = self._data(stale_msg)
    self.safety.set_timer(1_000 + self.SCC12_TIMEOUT)
    self.safety.safety_fwd_transform(stale_msg, 0)
    self.assertEqual(original, self._data(stale_msg))

  def test_requires_white_highway_hda_state(self):
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1)

    for hda_icon_state in (0, 2, 3):
      with self.subTest(hda_icon_state=hda_icon_state):
        msg = self._lfahda_msg(hda_icon_state=hda_icon_state)
        original = self._data(msg)
        self.safety.safety_fwd_transform(msg, 0)
        self.assertEqual(original, self._data(msg))

  def test_requires_stock_camera_route(self):
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1)

    for source_bus, destination_bus in ((0, 0), (2, 2)):
      with self.subTest(source_bus=source_bus, destination_bus=destination_bus):
        msg = self._lfahda_msg(bus=source_bus)
        original = self._data(msg)
        self.safety.safety_fwd_transform(msg, destination_bus)
        self.assertEqual(original, self._data(msg))

  def test_camera_scc_uses_bus_two_acc_state(self):
    self.safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCommunity, HyundaiSafetyFlags.CAMERA_SCC)
    self.safety.init_tests()
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1, bus=2)

    msg = self._lfahda_msg()
    self.safety.safety_fwd_transform(msg, 0)
    self.assertEqual(2, msg[0].data[3] & 0x3)

  def test_other_safety_modes_leave_forwarded_data_unchanged(self):
    self.safety.set_safety_hooks(CarParams.SafetyModel.hyundai, 0)
    msg = self._lfahda_msg()
    original = self._data(msg)

    self.safety.safety_fwd_transform(msg, 0)
    self.assertEqual(original, self._data(msg))

  def test_stock_frame_is_forwarded_and_host_duplicate_is_blocked(self):
    self.assertEqual(0, self.safety.safety_fwd_hook(2, 0x485))
    self.assertFalse(self.safety.safety_tx_hook(self._lfahda_msg(bus=0)))

  def test_safety_reinitialization_clears_acc_state(self):
    self.safety.set_heartbeat_engaged(True)
    self._set_acc_state(1)
    self.safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCommunity, 0)

    msg = self._lfahda_msg()
    original = self._data(msg)
    self.safety.safety_fwd_transform(msg, 0)
    self.assertEqual(original, self._data(msg))


if __name__ == "__main__":
  unittest.main()
