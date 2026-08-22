from opendbc.car.hyundai.custom.avmcontroller import AvmButtonController


def update(controller, now_nanos, view=AvmButtonController.VIEW_OFF, response_age_nanos=0,
           gear_drive=True, standstill=True, brake_pressed=True):
  response_ts_nanos = now_nanos - response_age_nanos
  return controller.update(now_nanos, view, response_ts_nanos, gear_drive, standstill, brake_pressed)


def test_force_on_press_sequence_and_feedback():
  controller = AvmButtonController()
  start = 1_000_000_000
  assert controller.request_on()
  assert update(controller, start) == (True, "press_started")

  for offset in range(controller.PRESS_INTERVAL_NS, controller.PRESS_DURATION_NS, controller.PRESS_INTERVAL_NS):
    assert update(controller, start + offset) == (True, None)

  assert update(controller, start + controller.PRESS_DURATION_NS) == (False, "press_released")
  assert update(controller, start + controller.PRESS_DURATION_NS + 100_000_000,
                view=controller.VIEW_FRONT) == (None, "activated")


def test_already_active_views_do_not_toggle():
  for view, expected in ((AvmButtonController.VIEW_FRONT, "already_on"),
                         (AvmButtonController.VIEW_REAR, "rear_view_active")):
    controller = AvmButtonController()
    now = 1_000_000_000
    assert controller.request_on()
    assert update(controller, now, view=view) == (None, expected)
    assert controller.state == "idle"


def test_request_guards():
  cases = (
    ({"response_age_nanos": AvmButtonController.RESPONSE_MAX_AGE_NS + 1}, "rejected_stale_response"),
    ({"view": 0}, "rejected_unknown_view_0"),
    ({"gear_drive": False}, "rejected_not_in_drive"),
    ({"standstill": False}, "rejected_vehicle_moving"),
    ({"brake_pressed": False}, "rejected_brake_not_pressed"),
  )
  for kwargs, expected in cases:
    controller = AvmButtonController()
    assert controller.request_on()
    assert update(controller, 1_000_000_000, **kwargs) == (None, expected)


def test_state_change_releases_and_cooldown_blocks_repeat():
  controller = AvmButtonController()
  start = 1_000_000_000
  assert controller.request_on()
  assert update(controller, start) == (True, "press_started")
  assert update(controller, start + 10_000_000, brake_pressed=False) == (False, "aborted_state_changed")
  assert not controller.request_on()

  update(controller, start + 10_000_000 + controller.COOLDOWN_NS)
  assert controller.request_on()


def test_response_timeout_does_not_retry():
  controller = AvmButtonController()
  start = 1_000_000_000
  assert controller.request_on()
  assert update(controller, start) == (True, "press_started")
  assert update(controller, start + controller.PRESS_DURATION_NS) == (False, "press_released")
  assert update(controller, start + controller.PRESS_DURATION_NS + controller.RESPONSE_TIMEOUT_NS) == (None, "response_timeout")
  assert not controller.request_on()
