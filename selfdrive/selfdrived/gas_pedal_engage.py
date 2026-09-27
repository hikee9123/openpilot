GAS_PEDAL_ENGAGE_DEBOUNCE_FRAMES = 15  # 150 ms at the 100 Hz controls rate


def update_gas_pedal_press_frames(frames: int, CS, CS_prev) -> int:
  if not (CS.canValid and CS_prev.canValid and CS.gasPressed):
    return 0
  if not CS_prev.gasPressed:
    return 1
  return frames + 1 if frames > 0 else 0


def stock_cruise_disable_requested(cruise_enabled: bool, gas_pedal_engage_active: bool) -> bool:
  return not cruise_enabled and not gas_pedal_engage_active


def gas_pedal_engage_requested(CP, CS, CS_prev, gas_press_frames: int, feature_enabled: bool,
                               disengage_on_accelerator: bool, openpilot_enabled: bool) -> bool:
  return (
    feature_enabled and
    CP.brand == 'hyundai' and
    not CP.openpilotLongitudinalControl and
    not disengage_on_accelerator and
    not openpilot_enabled and
    CS.canValid and
    CS_prev.canValid and
    CS.cruiseState.available and
    not CS.cruiseState.enabled and
    not CS.blockPcmEnable and
    gas_press_frames == GAS_PEDAL_ENGAGE_DEBOUNCE_FRAMES and
    not CS.brakePressed and
    not CS.doorOpen and
    not CS.seatbeltUnlatched and
    not CS.parkingBrake and
    not CS.accFaulted
  )
