class AvmButtonController:
  VIEW_FRONT = 1
  VIEW_REAR = 2
  VIEW_OFF = 3

  PRESS_INTERVAL_NS = 40_000_000
  PRESS_DURATION_NS = 240_000_000
  RESPONSE_MAX_AGE_NS = 500_000_000
  RESPONSE_TIMEOUT_NS = 1_000_000_000
  COOLDOWN_NS = 1_000_000_000

  def __init__(self):
    self.state = "idle"
    self.request_pending = False
    self.next_press_nanos = 0
    self.press_end_nanos = 0
    self.response_deadline_nanos = 0
    self.cooldown_end_nanos = 0

  def request_on(self) -> bool:
    if self.state != "idle" or self.request_pending:
      return False
    self.request_pending = True
    return True

  def _response_is_fresh(self, now_nanos: int, response_ts_nanos: int) -> bool:
    age_nanos = now_nanos - response_ts_nanos
    return response_ts_nanos > 0 and 0 <= age_nanos <= self.RESPONSE_MAX_AGE_NS

  def _start_request(self, now_nanos: int, avm_view: int, response_ts_nanos: int,
                     gear_drive: bool, standstill: bool, brake_pressed: bool):
    self.request_pending = False

    if not self._response_is_fresh(now_nanos, response_ts_nanos):
      return None, "rejected_stale_response"
    if avm_view == self.VIEW_FRONT:
      return None, "already_on"
    if avm_view == self.VIEW_REAR:
      return None, "rear_view_active"
    if avm_view != self.VIEW_OFF:
      return None, f"rejected_unknown_view_{avm_view}"
    if not gear_drive:
      return None, "rejected_not_in_drive"
    if not standstill:
      return None, "rejected_vehicle_moving"
    if not brake_pressed:
      return None, "rejected_brake_not_pressed"

    self.state = "pressing"
    self.next_press_nanos = now_nanos + self.PRESS_INTERVAL_NS
    self.press_end_nanos = now_nanos + self.PRESS_DURATION_NS
    return True, "press_started"

  def _start_cooldown(self, now_nanos: int):
    self.state = "cooldown"
    self.cooldown_end_nanos = now_nanos + self.COOLDOWN_NS

  def update(self, now_nanos: int, avm_view: int, response_ts_nanos: int,
             gear_drive: bool, standstill: bool, brake_pressed: bool):
    if self.state == "cooldown" and now_nanos >= self.cooldown_end_nanos:
      self.state = "idle"

    if self.request_pending:
      return self._start_request(now_nanos, avm_view, response_ts_nanos,
                                 gear_drive, standstill, brake_pressed)

    if self.state == "pressing":
      response_fresh = self._response_is_fresh(now_nanos, response_ts_nanos)
      if response_fresh and avm_view == self.VIEW_FRONT:
        self._start_cooldown(now_nanos)
        return False, "activated"

      valid_press_state = response_fresh and avm_view == self.VIEW_OFF and gear_drive and standstill and brake_pressed
      if not valid_press_state:
        self._start_cooldown(now_nanos)
        return False, "aborted_state_changed"

      if now_nanos >= self.press_end_nanos:
        self.state = "waiting_response"
        self.response_deadline_nanos = now_nanos + self.RESPONSE_TIMEOUT_NS
        self.cooldown_end_nanos = now_nanos + self.COOLDOWN_NS
        return False, "press_released"

      if now_nanos >= self.next_press_nanos:
        self.next_press_nanos += self.PRESS_INTERVAL_NS
        return True, None

    elif self.state == "waiting_response":
      if self._response_is_fresh(now_nanos, response_ts_nanos) and avm_view == self.VIEW_FRONT:
        self.state = "cooldown"
        return None, "activated"
      if now_nanos >= self.response_deadline_nanos:
        self.state = "cooldown"
        return None, "response_timeout"

    return None, None
