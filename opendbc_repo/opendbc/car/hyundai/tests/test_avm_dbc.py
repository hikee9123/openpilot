from opendbc.can import CANPacker


def test_avm_button_dbc_payloads():
  packer = CANPacker("hyundai_kia_generic")
  assert packer.make_can_msg("AVM_SWITCH", 0, {"AVM_Button": 0}) == (0x4A1, b"\x00" * 8, 0)
  assert packer.make_can_msg("AVM_SWITCH", 0, {"AVM_Button": 1}) == (0x4A1, b"\x00\x00\x00\x01\x00\x00\x00\x00", 0)
