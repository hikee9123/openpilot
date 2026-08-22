import numpy as np
from opendbc.can import CANPacker
from opendbc.car import Bus, DT_CTRL, make_tester_present_msg, structs
from opendbc.car.lateral import apply_driver_steer_torque_limits, common_fault_avoidance
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.hyundai import hyundaicanfd, hyundaican
from opendbc.car.hyundai.hyundaicanfd import CanBus
from opendbc.car.hyundai.values import HyundaiFlags, Buttons, CarControllerParams, CAR
from opendbc.car.interfaces import CarControllerBase

from opendbc.car.hyundai.custom.carcontroller import CarControllerCustom   #custom


VisualAlert = structs.CarControl.HUDControl.VisualAlert
LongCtrlState = structs.CarControl.Actuators.LongControlState

# EPS faults if you apply torque while the steering angle is above 90 degrees for more than 1 second
# All slightly below EPS thresholds to avoid fault
MAX_ANGLE = 85
MAX_ANGLE_FRAMES = 89
MAX_ANGLE_CONSECUTIVE_FRAMES = 2


def process_hud_alert(enabled, fingerprint, hud_control):
  sys_warning = (hud_control.visualAlert in (VisualAlert.steerRequired, VisualAlert.ldw))

  # initialize to no line visible
  # TODO: this is not accurate for all cars
  sys_state = 1
  if hud_control.leftLaneVisible and hud_control.rightLaneVisible or sys_warning:  # HUD alert only display when LKAS status is active
    sys_state = 3 if enabled or sys_warning else 4
  elif hud_control.leftLaneVisible:
    sys_state = 5
  elif hud_control.rightLaneVisible:
    sys_state = 6

  # initialize to no warnings
  left_lane_warning = 0
  right_lane_warning = 0
  if hud_control.leftLaneDepart:
    left_lane_warning = 1 if fingerprint in (CAR.GENESIS_G90, CAR.GENESIS_G80) else 2
  if hud_control.rightLaneDepart:
    right_lane_warning = 1 if fingerprint in (CAR.GENESIS_G90, CAR.GENESIS_G80) else 2

  return sys_warning, sys_state, left_lane_warning, right_lane_warning


class Clu11ButtonScheduler:
  STOCK_TIMEOUT_NS = 50_000_000
  # Copied routes show stock CLU11 reaches the next card TX cycle within 6.93 ms.
  # Skip a delayed cycle instead of transmitting near the following 50 Hz frame.
  STOCK_TX_MAX_AGE_NS = 10_000_000
  # Keep transport jitter margin above Panda's 100 ms hard limit.
  TX_MIN_INTERVAL_NS = 120_000_000
  CANCEL_BRAKE_DELAY_NS = 100_000_000
  REARM_RELEASE_NS = 50_000_000

  MAX_BURST_TX = 5
  AUTO_ENABLE_MAX_BURST_TX = 3
  DIRECT_RESUME_RETRY_NS = 500_000_000
  AUTO_ENABLE_RETRY_NS = 1_000_000_000

  SOURCE_CANCEL = "cancel"
  SOURCE_DIRECT_RESUME = "direct_resume"
  SOURCE_CUSTOM = "custom"
  SOURCE_AUTO_ENABLE = "auto_enable"

  def __init__(self):
    self.last_stock_ts_nanos = 0
    self.last_tx_nanos = None
    self.active_request = None
    self.request_start_nanos = 0
    self.tx_count = 0
    self.cooldown_until_nanos = 0
    self.fault_latched = False
    self.release_start_nanos = None
    self.pending_request = None
    self.pending_start_nanos = 0

  def _reset_request(self):
    self.active_request = None
    self.request_start_nanos = 0
    self.tx_count = 0
    self.cooldown_until_nanos = 0
    self.fault_latched = False
    self.release_start_nanos = None
    self.pending_request = None
    self.pending_start_nanos = 0

  def _activate_request(self, request, now_nanos):
    self.active_request = request
    self.request_start_nanos = now_nanos
    self.tx_count = 0
    self.cooldown_until_nanos = 0
    self.fault_latched = False
    self.release_start_nanos = None
    self.pending_request = None
    self.pending_start_nanos = 0

  def _limits(self, source):
    if source == self.SOURCE_DIRECT_RESUME:
      return self.MAX_BURST_TX, self.DIRECT_RESUME_RETRY_NS
    if source == self.SOURCE_AUTO_ENABLE:
      return self.AUTO_ENABLE_MAX_BURST_TX, self.AUTO_ENABLE_RETRY_NS
    return self.MAX_BURST_TX, 0

  def schedule(self, button, source, now_nanos, stock_counter, stock_ts_nanos, can_valid, can_timeout,
               driver_button, brake_pressed, driver_main_button=False):
    stock_updated = stock_ts_nanos > 0 and stock_ts_nanos != self.last_stock_ts_nanos
    if stock_updated:
      self.last_stock_ts_nanos = stock_ts_nanos

    stock_age_nanos = now_nanos - stock_ts_nanos
    healthy = can_valid and not can_timeout and stock_ts_nanos > 0 and 0 <= stock_age_nanos < self.STOCK_TIMEOUT_NS
    driver_input = driver_button != Buttons.NONE or driver_main_button
    if self.active_request is not None and (not healthy or driver_input):
      # A fault or driver input during a pending request transition must not be
      # cleared by activating the new request.
      self.fault_latched = True

    if self.active_request is not None and self.release_start_nanos is not None and now_nanos - self.release_start_nanos >= self.REARM_RELEASE_NS:
      self._reset_request()

    if button is None or source is None:
      self.pending_request = None
      self.pending_start_nanos = 0
      if self.active_request is not None and self.release_start_nanos is None:
        self.release_start_nanos = now_nanos
      return None

    request = (source, button)
    if self.active_request is None:
      self._activate_request(request, now_nanos)
    elif request != self.active_request:
      self.release_start_nanos = None
      if request != self.pending_request:
        self.pending_request = request
        self.pending_start_nanos = now_nanos
        return None
      if now_nanos - self.pending_start_nanos < self.REARM_RELEASE_NS:
        return None
      if self.fault_latched:
        return None
      self._activate_request(request, now_nanos)
    else:
      self.release_start_nanos = None
      self.pending_request = None
      self.pending_start_nanos = 0

    if not healthy or driver_input:
      # Never replay a request that was held through a CAN fault or a physical button press.
      self.fault_latched = True
      return None
    if self.fault_latched:
      return None

    if source == self.SOURCE_CANCEL and brake_pressed and now_nanos - self.request_start_nanos < self.CANCEL_BRAKE_DELAY_NS:
      return None

    max_tx, retry_interval_nanos = self._limits(source)
    if self.tx_count >= max_tx:
      if retry_interval_nanos == 0 or now_nanos < self.cooldown_until_nanos:
        return None
      self.tx_count = 0

    # One host request may follow each newly parsed stock frame. Panda validates
    # the same counter relationship against the latest frame seen on the bus.
    if not stock_updated or stock_age_nanos >= self.STOCK_TX_MAX_AGE_NS:
      return None
    if self.last_tx_nanos is not None and now_nanos - self.last_tx_nanos < self.TX_MIN_INTERVAL_NS:
      return None

    self.last_tx_nanos = now_nanos
    self.tx_count += 1
    if self.tx_count >= max_tx and retry_interval_nanos > 0:
      self.cooldown_until_nanos = now_nanos + retry_interval_nanos

    return button, (int(stock_counter) + 1) & 0xF


class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    super().__init__(dbc_names, CP)
    self.CAN = CanBus(CP)
    self.params = CarControllerParams(CP)
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.angle_limit_counter = 0

    self.accel_last = 0
    self.apply_torque_last = 0
    self.car_fingerprint = CP.carFingerprint
    self.last_button_frame = 0

    #custom
    self.customCC = CarControllerCustom(CP)
    self.clu11_button_scheduler = Clu11ButtonScheduler()
    self.community_safety = any(cfg.safetyModel == structs.CarParams.SafetyModel.hyundaiCommunity for cfg in CP.safetyConfigs)

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators
    hud_control = CC.hudControl

    # steering torque
    new_torque = int(round(actuators.torque * self.params.STEER_MAX))
    apply_torque = apply_driver_steer_torque_limits(new_torque, self.apply_torque_last, CS.out.steeringTorque, self.params)

    # >90 degree steering fault prevention
    self.angle_limit_counter, apply_steer_req = common_fault_avoidance(abs(CS.out.steeringAngleDeg) >= MAX_ANGLE, CC.latActive,
                                                                       self.angle_limit_counter, MAX_ANGLE_FRAMES,
                                                                       MAX_ANGLE_CONSECUTIVE_FRAMES)

    if not CC.latActive:
      apply_torque = 0

    # Hold torque with induced temporary fault when cutting the actuation bit
    # FIXME: we don't use this with CAN FD
    torque_fault = CC.latActive and not apply_steer_req

    self.apply_torque_last = apply_torque

    # accel + longitudinal
    accel = float(np.clip(actuators.accel, CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX))
    stopping = actuators.longControlState == LongCtrlState.stopping
    set_speed_in_units = hud_control.setSpeed * (CV.MS_TO_KPH if CS.is_metric else CV.MS_TO_MPH)

    can_sends = []

    # *** common hyundai stuff ***

    # tester present - w/ no response (keeps relevant ECU disabled)
    if self.frame % 100 == 0 and not (self.CP.flags & HyundaiFlags.CANFD_CAMERA_SCC) and self.CP.openpilotLongitudinalControl:
      # for longitudinal control, either radar or ADAS driving ECU
      addr, bus = 0x7d0, self.CAN.ECAN if self.CP.flags & HyundaiFlags.CANFD else 0
      if self.CP.flags & HyundaiFlags.CANFD_LKA_STEERING.value:
        addr, bus = 0x730, self.CAN.ECAN
      can_sends.append(make_tester_present_msg(addr, bus, suppress_response=True))

      # for blinkers
      if self.CP.flags & HyundaiFlags.ENABLE_BLINKERS:
        can_sends.append(make_tester_present_msg(0x7b1, self.CAN.ECAN, suppress_response=True))

    # *** CAN/CAN FD specific ***
    if self.CP.flags & HyundaiFlags.CANFD:
      can_sends.extend(self.create_canfd_msgs(apply_steer_req, apply_torque, set_speed_in_units, accel,
                                              stopping, hud_control, CS, CC))
    else:
      can_sends.extend(self.create_can_msgs(apply_steer_req, apply_torque, torque_fault, set_speed_in_units, accel,
                                            stopping, hud_control, actuators, CS, CC, now_nanos))
      can_sends.extend(self.customCC.create_avm_messages(self.packer, CS, now_nanos))

    new_actuators = actuators.as_builder()
    new_actuators.torque = apply_torque / self.params.STEER_MAX
    new_actuators.torqueOutputCan = apply_torque
    new_actuators.accel = accel

    self.frame += 1
    return new_actuators, can_sends

  def create_can_msgs(self, apply_steer_req, apply_torque, torque_fault, set_speed_in_units, accel, stopping, hud_control, actuators, CS, CC, now_nanos):
    can_sends = []

    # HUD messages
    sys_warning, sys_state, left_lane_warning, right_lane_warning = process_hud_alert(CC.enabled, self.car_fingerprint,
                                                                                      hud_control)

    can_sends.append(hyundaican.create_lkas11(self.packer, self.frame, self.CP, apply_torque, apply_steer_req,
                                              torque_fault, CS.lkas11, sys_warning, sys_state, CC.enabled,
                                              hud_control.leftLaneVisible, hud_control.rightLaneVisible,
                                              left_lane_warning, right_lane_warning))

    # Button messages
    if not self.CP.openpilotLongitudinalControl:
      can_sends.append( hyundaican.create_mdps12( self.packer, self.frame, CS.customCS.mdps12 ) ) #custom  # 100 Hz send mdps12 to LKAS to prevent LKAS error
      if self.community_safety:
        button = None
        source = None
        if CC.cruiseControl.cancel:
          button = Buttons.CANCEL
          source = Clu11ButtonScheduler.SOURCE_CANCEL
          self.customCC.NC.reset()  #custom
        elif CC.cruiseControl.resume:
          button = Buttons.RES_ACCEL
          source = Clu11ButtonScheduler.SOURCE_DIRECT_RESUME
          self.customCC.NC.reset()  #custom
        elif CS.out.cruiseState.available: #custom
          custom_button = self.customCC.get_button_request(CC, CS, self.frame)
          if custom_button in (Buttons.RES_ACCEL, Buttons.SET_DECEL):
            button = custom_button
            source = Clu11ButtonScheduler.SOURCE_CUSTOM if CS.customCS.acc_active else Clu11ButtonScheduler.SOURCE_AUTO_ENABLE

        scheduled_button = self.clu11_button_scheduler.schedule(
          button,
          source,
          now_nanos,
          CS.clu11["CF_Clu_AliveCnt1"],
          CS.clu11_ts_nanos,
          CS.out.canValid,
          CS.out.canTimeout,
          CS.clu11["CF_Clu_CruiseSwState"],
          CS.out.brakePressed,
          bool(CS.clu11["CF_Clu_CruiseSwMain"] or CS.clu11["CF_Clu_SldMainSW"]),
        )
        if scheduled_button is not None:
          button, counter = scheduled_button
          can_sends.append(hyundaican.create_clu11(self.packer, counter, CS.clu11, button, self.CP))
      elif CC.cruiseControl.cancel:
        can_sends.append(hyundaican.create_clu11(self.packer, self.frame, CS.clu11, Buttons.CANCEL, self.CP))
        self.customCC.NC.reset()  #custom
      elif CC.cruiseControl.resume:
        if (self.frame - self.last_button_frame) * DT_CTRL > 0.1:
          can_sends.append(hyundaican.create_clu11(self.packer, self.frame, CS.clu11, Buttons.RES_ACCEL, self.CP))
          if (self.frame - self.last_button_frame) * DT_CTRL >= 0.15:
            self.last_button_frame = self.frame
      elif CS.out.cruiseState.available: #custom
        self.customCC.create_button_messages(self.packer, can_sends, CC, CS, self.frame)

    if self.frame % 2 == 0 and self.CP.openpilotLongitudinalControl:
      # TODO: unclear if this is needed
      jerk = 3.0 if actuators.longControlState == LongCtrlState.pid else 1.0
      use_fca = self.CP.flags & HyundaiFlags.USE_FCA.value
      can_sends.extend(hyundaican.create_acc_commands(self.packer, CC.enabled, accel, jerk, int(self.frame / 2),
                                                      hud_control, set_speed_in_units, stopping,
                                                      CC.cruiseControl.override, use_fca, self.CP))

    # 5 Hz ACC options
    if self.frame % 20 == 0 and self.CP.openpilotLongitudinalControl:
      can_sends.extend(hyundaican.create_acc_opt(self.packer, self.CP))

    # 2 Hz front radar options
    if self.frame % 50 == 0 and self.CP.openpilotLongitudinalControl:
      can_sends.append(hyundaican.create_frt_radar_opt(self.packer))

    return can_sends

  def create_canfd_msgs(self, apply_steer_req, apply_torque, set_speed_in_units, accel, stopping, hud_control, CS, CC):
    can_sends = []

    lka_steering = self.CP.flags & HyundaiFlags.CANFD_LKA_STEERING
    lka_steering_long = lka_steering and self.CP.openpilotLongitudinalControl

    # steering control
    can_sends.extend(hyundaicanfd.create_steering_messages(self.packer, self.CP, self.CAN, CC.enabled, apply_steer_req, apply_torque))

    # prevent LFA from activating on LKA steering cars by sending "no lane lines detected" to ADAS ECU
    if self.frame % 5 == 0 and lka_steering:
      can_sends.append(hyundaicanfd.create_suppress_lfa(self.packer, self.CAN, CS.lfa_block_msg,
                                                        self.CP.flags & HyundaiFlags.CANFD_LKA_STEERING_ALT))

    # LFA and HDA icons
    if self.frame % 5 == 0 and (not lka_steering or lka_steering_long):
      can_sends.append(hyundaicanfd.create_lfahda_cluster(self.packer, self.CAN, CC.enabled))

    # blinkers
    if lka_steering and self.CP.flags & HyundaiFlags.ENABLE_BLINKERS:
      can_sends.extend(hyundaicanfd.create_spas_messages(self.packer, self.CAN, CC.leftBlinker, CC.rightBlinker))

    if self.CP.openpilotLongitudinalControl:
      if lka_steering:
        can_sends.extend(hyundaicanfd.create_adrv_messages(self.packer, self.CAN, self.frame))
      else:
        can_sends.extend(hyundaicanfd.create_fca_warning_light(self.packer, self.CAN, self.frame))
      if self.frame % 2 == 0:
        can_sends.append(hyundaicanfd.create_acc_control(self.packer, self.CAN, CC.enabled, self.accel_last, accel, stopping, CC.cruiseControl.override,
                                                         set_speed_in_units, hud_control))
        self.accel_last = accel
    else:
      # button presses
      if (self.frame - self.last_button_frame) * DT_CTRL > 0.25:
        # cruise cancel
        if CC.cruiseControl.cancel:
          if self.CP.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
            can_sends.append(hyundaicanfd.create_acc_cancel(self.packer, self.CP, self.CAN, CS.cruise_info))
            self.last_button_frame = self.frame
          else:
            for _ in range(20):
              can_sends.append(hyundaicanfd.create_buttons(self.packer, self.CP, self.CAN, CS.buttons_counter + 1, Buttons.CANCEL))
            self.last_button_frame = self.frame

        # cruise standstill resume
        elif CC.cruiseControl.resume:
          if self.CP.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
            # TODO: resume for alt button cars
            pass
          else:
            for _ in range(20):
              can_sends.append(hyundaicanfd.create_buttons(self.packer, self.CP, self.CAN, CS.buttons_counter + 1, Buttons.RES_ACCEL))
            self.last_button_frame = self.frame

    return can_sends
