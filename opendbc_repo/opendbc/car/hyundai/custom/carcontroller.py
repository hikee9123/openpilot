from cereal import car

from opendbc.car.hyundai    import hyundaican
from opendbc.car.hyundai.custom.cruisebuttonctrl  import CruiseButtonCtrl

import opendbc.custom.loger as trace1


class CarControllerCustom:
  def __init__(self, CP):
    self.CP = CP
    self.NC = CruiseButtonCtrl( CP)
    self.resume_cnt = 0


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
