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
    self.sm = messaging.SubMaster(['longitudinalPlan','modelV2','pandaStates','uICustom'], ignore_avg_freq=['uICustom'])
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

    self.controlsAllowed = 0


    try:
      m_jsonobj = read_json_file("CustomParam")
      self.autoLaneChange = m_jsonobj["AutoLaneChange"]
      self.menu_debug = m_jsonobj["debug"]
    except Exception as e:
      self.autoLaneChange = 0
      self.menu_debug = 0

    self.cars = []
    self.get_type_of_car( CP )


  def get_type_of_car( self, CP ):
    cars = []
    for _, member in CAR.__members__.items():
      cars.append(member.value)
    #cars.sort()
    self.cars = cars


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

  def lfa_engage(self, ret):
    if any(ps.controlsAllowed for ps in self.sm['pandaStates']):
      self.controlsAllowed = 1
    else:
      self.controlsAllowed = 0

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


  def get_tpms(self, ret, unit, fl, fr, rl, rr):
    factor = 0.72519 if unit == 1 else 0.1 if unit == 2 else 1 # 0:psi, 1:kpa, 2:bar
    ret.unit = unit
    ret.fl = fl * factor
    ret.fr = fr * factor
    ret.rl = rl * factor
    ret.rr = rr * factor

  def send_carstatus( self, ret, cp, CS ):
    if self.menu_debug == 0:
      return

    carSCustom = car.CarState.CarSCustom.new_message()
    carSCustom.supportedCars = self.cars
    carSCustom.breakPos = self.brakePos
    carSCustom.leadDistance = self.lead_distance
    carSCustom.gapSet = self.gapSet
    carSCustom.electGearStep = cp.vl["ELECT_GEAR"]["Elect_Gear_Step"] # opkr
    self.get_tpms( carSCustom.tpms,
      cp.vl["TPMS11"]["UNIT"],
      cp.vl["TPMS11"]["PRESSURE_FL"],
      cp.vl["TPMS11"]["PRESSURE_FR"],
      cp.vl["TPMS11"]["PRESSURE_RL"],
      cp.vl["TPMS11"]["PRESSURE_RR"],
    )

    ret.carSCustom = carSCustom


    #log
    trace1.printf1( 'MD={:.0f},controlsAllowed={:.0f}'.format( self.control_mode,  self.controlsAllowed ) )
    trace1.printf2( 'CV={:7.5f} , {:.0f} , {:.0f}'.format( self.desiredCurvature, self.mainMode_ACC, self.clu_Main ) )

    #if self.CP.openpilotLongitudinalControl:
    trace1.printf3( 'SW={:.0f},{:.0f},{:.0f} T={:.0f},{:.0f}'.format(
          cp.vl["CLU11"]["CF_Clu_CruiseSwState"], cp.vl["CLU11"]["CF_Clu_CruiseSwMain"], cp.vl["CLU11"]["CF_Clu_SldMainSW"],
          cp.vl["TCS13"]["ACCEnable"], cp.vl["TCS13"]["ACC_REQ"]
    ))


  def cruise_speed_button( self ):
    if self.prev_acc_active != self.acc_active:
      self.old_acc_active = self.prev_acc_active
      self.prev_acc_active = self.acc_active
      self.cruise_set_speed_kph = self.VSetDis

    set_speed_kph = self.cruise_set_speed_kph
    if not self.acc_active:
      return self.cruise_set_speed_kph

    cruise_buttons = self.CS.prev_cruise_buttons   #cruise_buttons[-1]
    if cruise_buttons in (Buttons.RES_ACCEL, Buttons.SET_DECEL):
      self.cruise_buttons_time += 1
    else:
      self.cruise_buttons_time = 0

    # long press should set scc speed with cluster scc number
    if self.cruise_buttons_time >= 55:
      self.cruise_set_speed_kph = self.VSetDis
      return self.cruise_set_speed_kph


    if self.prev_cruise_btn == cruise_buttons:
      return self.cruise_set_speed_kph

    self.prev_cruise_btn = cruise_buttons

    if cruise_buttons == (Buttons.RES_ACCEL):
      set_speed_kph = self.VSetDis + 1
    elif cruise_buttons == (Buttons.SET_DECEL):
      if self.CS.out.gasPressed or not self.old_acc_active:
        set_speed_kph = self.clu_Vanz
      else:
        set_speed_kph = self.VSetDis - 1

    if set_speed_kph < 30:
      set_speed_kph = 30

    self.cruise_set_speed_kph = set_speed_kph
    return  set_speed_kph


  def update(self, ret, CS,  cp, cp_cruise, cp_cam ):
    self.sm.update(0)
    if self.CP.openpilotLongitudinalControl:
      self.mainMode_ACC = cp.vl["TCS13"]["ACCEnable"] == 0
      self.acc_active = cp.vl["TCS13"]["ACC_REQ"] == 1
      self.lead_distance = 0
    else:
      self.mainMode_ACC = cp_cruise.vl["SCC11"]["MainMode_ACC"] == 1
      self.acc_active = (cp_cruise.vl["SCC12"]['ACCMode'] != 0)
      if self.acc_active:
        ret.cruiseState.speed = self.cruise_speed_button() * CV.KPH_TO_MS
      else:
        ret.cruiseState.speed = 0

      self.lead_distance = cp_cruise.vl["SCC11"]["ACC_ObjDist"]
      self.gapSet = cp_cruise.vl["SCC11"]['TauGapSet']
      self.VSetDis = cp_cruise.vl["SCC11"]["VSetDis"]   # kph   ??（利???�젙 ??�룄.

      if not self.mainMode_ACC:
        self.cruise_control_mode()


    # save the entire LFAHDA_MFC
    self.lfahda = copy.copy(cp_cam.vl["LFAHDA_MFC"])
    self.mdps12 = copy.copy(cp.vl["MDPS12"])


    self.brakePos = cp.vl["E_EMS11"]["Brake_Pedal_Pos"]
    self.is_highway = self.lfahda["HDA_Icon_State"] != 0.
    self.clu_Vanz = cp.vl["CLU11"]["CF_Clu_Vanz"]     # kph  ?꾩옱 李⑤?????�룄.
    self.clu_Main = cp.vl["CLU11"]["CF_Clu_CruiseSwMain"]

    self.lfa_engage( ret)

    self.send_carstatus( ret, cp, CS )
