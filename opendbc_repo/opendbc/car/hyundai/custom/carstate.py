import copy
import opendbc.custom.loger as  trace1
import cereal.messaging as messaging

from cereal import car, log
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.hyundai.values import CAR, Buttons

from opendbc.custom.params_json import read_json_file
from openpilot.common.params import Params


LaneChangeState = log.LaneChangeState

class CarStateCustom():
  def __init__(self, CP, CS):
    self.CS = CS
    self.CP = CP
    self.params = Params()
    self.oldCruiseStateEnabled = False
    self.frame = 0
    self.acc_active = 0

    self.cruise_buttons_old = 0
    self.control_mode = 0
    self.clu_Vanz = 0
    self.is_highway = False


    self.timer_init = 500   # 5sec
    self.timer_resume = 500

    # cruise_speed_button
    self.old_acc_active = 0
    self.prev_acc_active = 0
    self.cruise_set_speed_kph = 0
    self.cruise_buttons_time = 0
    self.VSetDis = 0
    self.prev_cruise_btn = 0
    self.lead_distance = 0


    self.timer_engaged = 0
    self.slow_engage = 1

    self.leftLaneTime = 50
    self.rightLaneTime = 50

    self.desiredCurvature = 0
    self.modelxDistance = 0

  def cruise_control_mode( self ):
    cruise_buttons = self.CS.prev_cruise_buttons
    if cruise_buttons == self.cruise_buttons_old:
       return

    self.cruise_buttons_old = cruise_buttons
    if cruise_buttons == (Buttons.RES_ACCEL):
      self.control_mode += 1
    elif cruise_buttons == (Buttons.SET_DECEL):
      self.control_mode -= 1

    if self.control_mode < 0:
      self.control_mode = 0
    elif self.control_mode > 5:
      self.control_mode = 0


  def update(self, ret, CS,  cp, cp_cruise, cp_cam ):
    if self.CP.openpilotLongitudinalControl:
      mainMode_ACC = cp.vl["TCS13"]["ACCEnable"] == 0
      self.acc_active = cp.vl["TCS13"]["ACC_REQ"] == 1
      self.lead_distance = 0
    else:
      mainMode_ACC = cp_cruise.vl["SCC11"]["MainMode_ACC"] == 1
      self.acc_active = (cp_cruise.vl["SCC12"]['ACCMode'] != 0)
      if self.acc_active:
        ret.cruiseState.speed = self.cruise_speed_button() * CV.KPH_TO_MS
      else:
        ret.cruiseState.speed = 0

      self.lead_distance = cp_cruise.vl["SCC11"]["ACC_ObjDist"]
      self.gapSet = cp_cruise.vl["SCC11"]['TauGapSet']
      self.VSetDis = cp_cruise.vl["SCC11"]["VSetDis"]   # kph   크루즈 설정 속도.

      if not mainMode_ACC:
        self.cruise_control_mode()

    # save the entire LFAHDA_MFC
    self.lfahda = copy.copy(cp_cam.vl["LFAHDA_MFC"])
    self.mdps12 = copy.copy(cp.vl["MDPS12"])


    self.brakePos = cp.vl["E_EMS11"]["Brake_Pedal_Pos"]
    self.is_highway = self.lfahda["HDA_Icon_State"] != 0.
    self.clu_Vanz = cp.vl["CLU11"]["CF_Clu_Vanz"]     # kph  현재 차량의 속도.

    if self.timer_init > 0:
      self.timer_init -= 1
      ret.cruiseState.enabled = False
    elif not self.CP.openpilotLongitudinalControl:
      if self.acc_active:
        pass
      elif ret.parkingBrake:
        self.timer_engaged = 100
        self.oldCruiseStateEnabled = False
      elif ret.doorOpen:
        self.timer_engaged = 100
        self.oldCruiseStateEnabled = False
      elif ret.seatbeltUnlatched:
        self.timer_engaged = 100
        self.oldCruiseStateEnabled = False
      elif ret.gearShifter != car.CarState.GearShifter.drive:
        self.timer_engaged = 100
        self.oldCruiseStateEnabled = False
      elif not ret.cruiseState.available:
        self.slow_engage = 1
        self.timer_engaged = 0
        self.oldCruiseStateEnabled = True
      elif self.oldCruiseStateEnabled:
        ret.cruiseState.enabled = True
