import copy
import numpy as np
import opendbc.custom.loger as trace1
import cereal.messaging as messaging

from cereal import car, log
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.hyundai.values import CAR, Buttons
from opendbc.custom.params_json import read_json_file
from openpilot.common.params import Params

LaneChangeState = log.LaneChangeState


class CarStateCustom:
  # ----------------------------
  # Tunables / Guard constants
  # ----------------------------
  INIT_DELAY_FRAMES = 500           # 초기 5s 동안 강제 disengage
  RESUME_LONGPRESS_FRAMES = 55      # 버튼 길게 누름 임계
  TARGET_MIN_KPH = 30               # SCC 세트 최소 속도

  def __init__(self, CP, CS):
    self.CS = CS
    self.CP = CP
    self.sm = messaging.SubMaster(
      ['longitudinalPlan', 'modelV2', 'pandaStates', 'uICustom'],
      ignore_avg_freq=['uICustom']
    )
    self.params = Params()

    # 상태/타이머
    self.frame = 0
    self.timer_init = self.INIT_DELAY_FRAMES


    # ACC/크루즈 상태
    self.acc_active = 0
    self.old_acc_active = 0
    self.prev_acc_active = 0
    self.oldCruiseStateEnabled = False
    self.controlsAllowed = 0

    # 버튼/세트 속도
    self.cruise_buttons_old = 0
    self.prev_cruise_btn = 0
    self.cruise_buttons_time = 0
    self.cruise_set_speed_kph = 0.0
    self.VSetDis = 0.0
    self.lead_distance = 0.0
    self.gapSet = 0

    # 차량/주행 상태
    self.clu_Vanz = 0.0
    self.is_highway = False
    self.desiredCurvature = 0.0
    self.modelxDistance = 0.0
    self.modelyDistance = 0.0
    self.model_v2 = None
    self.brakePos = 0.0
    self.clu_Main = 0
    self.mainMode_ACC = False


    # 외부/플래너 파생
    self.speed_plan_kph = 0.0
    self.cruise_set_mode = 0
    self.cruiseGap = 0

    # 좌/우 차선변경 헬퍼(유지)
    self.leftLaneTime = 50
    self.rightLaneTime = 50

    self.control_mode = 0

    # 커스텀 메뉴
    try:
      m_jsonobj = read_json_file("CustomParam")
      self.autoLaneChange = m_jsonobj.get("AutoLaneChange", 0)
      self.menu_debug = m_jsonobj.get("debug", 0)
    except Exception:
      self.autoLaneChange = 0
      self.menu_debug = 0

    # 지원 차량 목록
    self.cars = self._get_supported_cars(CP)

  # ----------------------------
  # Misc
  # ----------------------------
  @staticmethod
  def _safe_vl_map(cp, msg: str):
    """메시지 맵 복사 (없을 경우 빈 dict)"""
    try:
      return cp.vl[msg]
    except Exception:
      return {}

  # ----------------------------
  # Helpers: CAN value access
  # ----------------------------
  @staticmethod
  def _vl(cp, msg: str, sig: str, default=0):
    """안전한 단일 신호 읽기"""
    try:
      return cp.vl[msg][sig]
    except Exception:
      return default

  @staticmethod
  def _vla(cp, msg: str, sig: str, default=0):
    """안전한 배열형 신호 읽기 (vl_all)"""
    try:
      return cp.vl_all[msg][sig]
    except Exception:
      return default

  # ----------------------------
  # Public-ish helpers
  # ----------------------------
  def _get_supported_cars(self, CP):
    cars = []
    for _, member in CAR.__members__.items():
      cars.append(member.value)
    return cars

  def set_cruise_speed(self, set_speed_kph: float):
    """CruiseButtonCtrl에서 호출하는 setter (존재 가드용)"""
    self.cruise_set_speed_kph = float(set_speed_kph)

  def cruise_control_mode(self):
    """RES/SET 버튼으로 메뉴 모드 토글(기존 로직 유지)"""
    cruise_buttons = self.CS.prev_cruise_buttons
    if cruise_buttons == self.cruise_buttons_old:
      return

    self.cruise_buttons_old = cruise_buttons
    if cruise_buttons == Buttons.RES_ACCEL:
      self.control_mode +=   1
    elif cruise_buttons == Buttons.SET_DECEL:
      self.control_mode -=  1

    if self.control_mode < 0 or self.control_mode > 5:
      self.control_mode = 0

  def _update_controls_allowed(self):
    """pandaStates 기반 제어 허용 플래그 업데이트"""
    self.controlsAllowed = 1 if any(ps.controlsAllowed for ps in self.sm['pandaStates']) else 0

  # ----------------------------
  # Engage management (LFA/ACC)
  # ----------------------------
  def lfa_engage(self, ret):
    self._update_controls_allowed()

    # 초기 쿨다운
    if self.timer_init > 0:
      self.timer_init -= 1
      ret.cruiseState.enabled = False
      return

    # OP Long on이면 여기서 추가 처리 없음 (원 코드 의도 유지)
    if self.CP.openpilotLongitudinalControl:
      return

    # 안전 조건 불만족 시 타이머 재가동 & 이전 상태 해제
    unsafe = (
      ret.parkingBrake or
      ret.doorOpen or
      ret.seatbeltUnlatched or
      ret.gearShifter != car.CarState.GearShifter.drive
    )
    if unsafe:
      self.oldCruiseStateEnabled = False
      self.timer_init = self.INIT_DELAY_FRAMES  # 주석과 동작 일치
      return

    # 메인 ACC 사용불가 → 표시만 on
    if not ret.cruiseState.available:
      self.oldCruiseStateEnabled = True
      return

    # 이전에 enable 표시를 켰다면 유지
    if self.oldCruiseStateEnabled:
      ret.cruiseState.enabled = True

  # ----------------------------
  # Debug / telemetry
  # ----------------------------
  def _fill_tpms(self, tpms_msg, unit, fl, fr, rl, rr):
    # unit: 0:psi, 1:kpa, 2:bar
    factor = 0.72519 if unit == 1 else (0.1 if unit == 2 else 1.0)
    tpms_msg.unit = unit
    tpms_msg.fl = fl * factor
    tpms_msg.fr = fr * factor
    tpms_msg.rl = rl * factor
    tpms_msg.rr = rr * factor

  def send_carstatus(self, ret, cp):
    if self.menu_debug == 0:
      return

    carSCustom = car.CarState.CarSCustom.new_message()
    carSCustom.supportedCars = self.cars
    carSCustom.breakPos = float(self.brakePos)
    carSCustom.leadDistance = float(self.lead_distance)
    carSCustom.gapSet = int(self.gapSet)
    carSCustom.electGearStep = self._vl(cp, "ELECT_GEAR", "Elect_Gear_Step", 0)

    self._fill_tpms(
      carSCustom.tpms,
      self._vl(cp, "TPMS11", "UNIT", 0),
      self._vl(cp, "TPMS11", "PRESSURE_FL", 0.0),
      self._vl(cp, "TPMS11", "PRESSURE_FR", 0.0),
      self._vl(cp, "TPMS11", "PRESSURE_RL", 0.0),
      self._vl(cp, "TPMS11", "PRESSURE_RR", 0.0),
    )

    cruise_buttons = self.CS.prev_cruise_buttons
    if cruise_buttons in (Buttons.CANCEL, Buttons.RES_ACCEL, Buttons.SET_DECEL):
      carSCustom.touched += 1

    ret.carSCustom = carSCustom

    # 로그 (원 포맷 유지)
    trace1.printf1('MD={:.0f},controlsAllowed={:.0f}'.format(getattr(self, "control_mode", 0), self.controlsAllowed))
    trace1.printf2('CV={:7.5f} , {:.0f} , {:.0f}'.format(self.desiredCurvature, int(self.mainMode_ACC), int(self.clu_Main)))
    trace1.printf3('SW={:.0f},{:.0f},{:.0f} T={:.0f},{:.0f}'.format(
      self._vl(cp, "CLU11", "CF_Clu_CruiseSwState", 0),
      self._vl(cp, "CLU11", "CF_Clu_CruiseSwMain", 0),
      self._vl(cp, "CLU11", "CF_Clu_SldMainSW", 0),
      self._vl(cp, "TCS13", "ACCEnable", 0),
      self._vl(cp, "TCS13", "ACC_REQ", 0),
    ))

  # ----------------------------
  # Cruise set-speed via buttons
  # ----------------------------
  def _update_button_press_timer(self, cruise_buttons: int):
    """RES/SET 길게 누름 카운팅"""
    if cruise_buttons in (Buttons.RES_ACCEL, Buttons.SET_DECEL):
      self.cruise_buttons_time += 1
    else:
      self.cruise_buttons_time = 0

  def _handle_longpress_set_vset(self) -> bool:
    """길게 누름이면 클러스터 세트속도로 고정 (True 반환 시 처리 완료)"""
    if self.cruise_buttons_time >= self.RESUME_LONGPRESS_FRAMES:
      self.cruise_set_speed_kph = self.VSetDis
      return True
    return False

  def cruise_speed_button(self) -> float:
    """버튼 입력 기반의 세트 속도 관리(원 로직 유지, 가드 추가)"""
    # ACC 활성/비활성 전환 감지
    if self.prev_acc_active != self.acc_active:
      self.old_acc_active = self.prev_acc_active
      self.prev_acc_active = self.acc_active
      self.cruise_set_speed_kph = self.VSetDis

    _gas_now = self.CS.out.gasPressed
    if not self.acc_active:
      self._gas_pressed_prev = _gas_now
      return float(self.cruise_set_speed_kph)


    # === 가속 페달 해제 시 현재 속도로 동기화 ===
    if not _gas_now and self._gas_pressed_prev:
        diff = float(self.clu_Vanz) - float(self.cruise_set_speed_kph)
        if diff >= 5.0:
            self.cruise_set_speed_kph = max(float(self.clu_Vanz), float(self.TARGET_MIN_KPH))
    self._gas_pressed_prev = _gas_now


    cruise_buttons = getattr(self.CS, "prev_cruise_buttons", 0)
    self._update_button_press_timer(cruise_buttons)

    # 길게 누름 처리
    if self._handle_longpress_set_vset():
      return float(self.cruise_set_speed_kph)

    # 같은 버튼 반복 입력 → 무시
    if self.prev_cruise_btn == cruise_buttons:
      return float(self.cruise_set_speed_kph)
    self.prev_cruise_btn = cruise_buttons



    set_speed_kph = self.cruise_set_speed_kph

    if cruise_buttons == Buttons.RES_ACCEL:
      set_speed_kph = self.VSetDis + 1
    elif cruise_buttons == Buttons.SET_DECEL:
      # 가속 페달 중이거나 방금 ACC가 꺼져 있었다면 현재 속도로 세팅
      if _gas_now or (not self.old_acc_active):
        set_speed_kph = self.clu_Vanz
      else:
        set_speed_kph = self.VSetDis - 1

    if set_speed_kph < self.TARGET_MIN_KPH:
      set_speed_kph = self.TARGET_MIN_KPH

    self.cruise_set_speed_kph = float(set_speed_kph)
    return float(set_speed_kph)

  # ----------------------------
  # Model-based helpers
  # ----------------------------
  @staticmethod
  def max_distance(model_v2):
    """modelV2 position의 마지막 포인트를 가져와 범위를 클램프"""
    if model_v2 is None or getattr(model_v2, "position", None) is None:
      return None, None

    x_positions = getattr(model_v2.position, "x", []) or []
    y_positions = getattr(model_v2.position, "y", []) or []

    last_x_value = x_positions[-1] if len(x_positions) else None
    last_y_value = y_positions[-1] if len(y_positions) else None

    x_distance = float(np.clip(last_x_value, 10, 500)) if last_x_value is not None else None
    y_distance = float(np.clip(last_y_value, -60, 60)) if last_y_value is not None else None
    return x_distance, y_distance

  def _update_from_submaster(self):
    """SubMaster에서 보조 신호 갱신. sm.update(0)는 여기서만 호출합니다."""
    self.sm.update(0)

    # Planner 기반 속도 (kph)
    speeds = self.sm['longitudinalPlan'].speeds
    if len(speeds):
      self.speed_plan_kph = float(speeds[-1]) * CV.MS_TO_KPH

    # UI Custom (모드/갭)
    if self.sm.updated["uICustom"]:
      cruiseMode = self.sm['uICustom'].community.cruiseMode
      if self.cruise_set_mode != cruiseMode:
        self.cruise_set_mode = int(cruiseMode)

      cruiseGap = self.sm['uICustom'].community.cruiseGap
      if self.cruiseGap != cruiseGap:
        self.cruiseGap = int(cruiseGap)

    # 모델 곡률/이격
    self.model_v2 = self.sm['modelV2']
    x_d, y_d = self.max_distance(self.model_v2)
    # None 대비 기본값 0.0
    self.modelxDistance = x_d if x_d is not None else 0.0
    self.modelyDistance = y_d if y_d is not None else 0.0

    if self.clu_Vanz > 60:
      # 곡률 기반 속도 페널티(간단한 예: 곡률 y 편차 10~60 → 0~10 kph 감속)
      # np.interp 사용 (x, xp, fp)
      spd_curv = float(np.interp(abs(self.modelyDistance), [10.0, 60.0], [0.0, 10.0], left=0.0, right=10.0))
      self.speed_plan_kph -= spd_curv
      self.speed_plan_kph = max(0.0, self.speed_plan_kph)
    else:
      spd_curv = float(np.interp(abs(self.modelyDistance), [20.0, 60.0], [1.0, 0.5], left=0.0, right=10.0))
      self.speed_plan_kph *= spd_curv
      self.speed_plan_kph = max(0.0, self.speed_plan_kph)


  # ----------------------------
  # Update (entry point from CarState)
  # ----------------------------
  def update(self, ret, CS, cp, cp_cruise, cp_cam):
    # SubMaster는 여기서만 업데이트
    self._update_from_submaster()


    # openpilot Long on/off 에 따라 분리
    if self.CP.openpilotLongitudinalControl:
      self.mainMode_ACC = self._vl(cp, "TCS13", "ACCEnable", 1) == 0
      self.acc_active = self._vl(cp, "TCS13", "ACC_REQ", 0) == 1
      self.lead_distance = 0.0
      # OP long 때는 ret.cruiseState.speed는 OP가 관리
    else:
      self.mainMode_ACC = self._vl(cp_cruise, "SCC11", "MainMode_ACC", 0) == 1
      self.acc_active = self._vl(cp_cruise, "SCC12", "ACCMode", 0) != 0
      if self.acc_active:
        # 버튼 로직 기반 세트 속도 → m/s로 변환해 대시 표시
        ret.cruiseState.speed = self.cruise_speed_button() * CV.KPH_TO_MS
      else:
        ret.cruiseState.speed = 0.0

      self.lead_distance = self._vl(cp_cruise, "SCC11", "ACC_ObjDist", 0.0)
      self.gapSet = self._vl(cp_cruise, "SCC11", "TauGapSet", 0)
      self.VSetDis = self._vl(cp_cruise, "SCC11", "VSetDis", 0.0)

      if not self.mainMode_ACC:
        self.cruise_control_mode()

    # 원본 프레임 보관
    self.lfahda = copy.copy(self._safe_vl_map(cp_cam, "LFAHDA_MFC"))
    self.mdps12 = copy.copy(self._safe_vl_map(cp, "MDPS12"))

    # 기타 값 갱신
    self.brakePos = self._vl(cp, "E_EMS11", "Brake_Pedal_Pos", 0.0)
    self.is_highway = bool(self._vl(cp_cam, "LFAHDA_MFC", "HDA_Icon_State", 0.0))
    self.clu_Vanz = self._vl(cp, "CLU11", "CF_Clu_Vanz", 0.0)          # kph
    self.clu_Main = self._vl(cp, "CLU11", "CF_Clu_CruiseSwMain", 0)



    # LFA/Engage 관리
    self.lfa_engage(ret)

    # 디버그 전송
    self.send_carstatus(ret, cp)
