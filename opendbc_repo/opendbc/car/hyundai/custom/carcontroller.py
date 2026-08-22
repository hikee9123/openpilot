from cereal import car
import cereal.messaging as messaging

from opendbc.car.hyundai.values import HyundaiFlags, HyundaiSafetyFlags
from opendbc.car.hyundai    import hyundaican
from opendbc.car.hyundai.custom.avmcontroller import AvmButtonController
from opendbc.car.hyundai.custom.cruisebuttonctrl  import CruiseButtonCtrl
from opendbc.car.carlog import carlog

import opendbc.custom.loger as trace1


class CarControllerCustom:
  def __init__(self, CP):
    self.CP = CP
    self.NC = CruiseButtonCtrl( CP)
    self.resume_cnt = 0

    community_avm_safety = any(
      cfg.safetyModel == car.CarParams.SafetyModel.hyundaiCommunity and
      cfg.safetyParam & HyundaiSafetyFlags.AVM_BUTTON and
      not (cfg.safetyParam & (HyundaiSafetyFlags.LONG | HyundaiSafetyFlags.CAMERA_SCC))
      for cfg in CP.safetyConfigs
    )
    self.avm_enabled = bool(CP.flags & HyundaiFlags.AVM_BUTTON) and community_avm_safety
    self.avm_controller = AvmButtonController() if self.avm_enabled else None
    self.avm_sm = messaging.SubMaster(["carControlCustom"]) if self.avm_enabled else None
    self.last_avm_cmd_idx = 0


  def get_button_request(self, CC: car.CarControl, CS: car.CarState, frame: int):
    # The main controller owns all CLU11 timing and transmission.
    return self.NC.update(CC, CS, frame)

  def create_button_messages(self, packer, can_sends, CC: car.CarControl, CS: car.CarState, frame: int):
    btn_signal = self.NC.update(CC, CS, frame)
    if btn_signal is not None:
      can_sends.append(hyundaican.create_clu11(packer, self.resume_cnt, CS.clu11, btn_signal, self.CP))
      self.resume_cnt += 1
    else:
      self.resume_cnt = 0

  def create_avm_messages(self, packer, CS, now_nanos: int):
    if not self.avm_enabled or self.avm_controller is None or self.avm_sm is None:
      return []

    self.avm_sm.update(0)
    if self.avm_sm.updated["carControlCustom"]:
      command = self.avm_sm["carControlCustom"]
      cmd_idx = int(command.cmdIdx)
      if cmd_idx != 0 and cmd_idx != self.last_avm_cmd_idx:
        self.last_avm_cmd_idx = cmd_idx
        if command.avmOnRequest:
          if not self.avm_controller.request_on():
            carlog.info(f"AVM ON request ignored while busy: cmdIdx={cmd_idx}")

    pressed, result = self.avm_controller.update(
      now_nanos,
      CS.avm_view,
      CS.avm_view_ts_nanos,
      CS.out.gearShifter == car.CarState.GearShifter.drive,
      CS.out.standstill,
      CS.out.brakePressed,
    )
    if result is not None:
      carlog.info(f"AVM ON request: {result}")

    return [] if pressed is None else [hyundaican.create_avm_button(packer, CS.avm_switch, pressed)]
