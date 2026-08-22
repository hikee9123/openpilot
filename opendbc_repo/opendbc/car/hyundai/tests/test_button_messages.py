from collections import Counter
from types import SimpleNamespace

from opendbc.car.hyundai import carcontroller, hyundaican
from opendbc.car.hyundai.carcontroller import CarController, Clu11ButtonScheduler
from opendbc.car.hyundai.custom.carcontroller import CarControllerCustom
from opendbc.car.hyundai.custom.cruisebuttonctrl import CruiseButtonCtrl, State
from opendbc.car.hyundai.values import Buttons


CONTROL_STEP_NS = 10_000_000


def _make_controller(monkeypatch, custom_button=None, acc_active=True):
  monkeypatch.setattr(carcontroller, "process_hud_alert", lambda *args: (0, 0, 0, 0))
  monkeypatch.setattr(hyundaican, "create_lkas11", lambda *args: ("lkas11",))
  monkeypatch.setattr(hyundaican, "create_mdps12", lambda *args: ("mdps12",))

  controller = object.__new__(CarController)
  controller.CP = SimpleNamespace(openpilotLongitudinalControl=False, flags=0)
  controller.frame = 0
  controller.last_button_frame = 0
  controller.packer = object()
  controller.car_fingerprint = None
  controller.clu11_button_scheduler = Clu11ButtonScheduler()
  controller.community_safety = True
  controller.customCC = SimpleNamespace(
    NC=SimpleNamespace(reset=lambda: None),
    get_button_request=lambda *args: custom_button,
  )

  sent = []

  def create_clu11(_packer, counter, _clu11, button, _cp):
    sent.append((controller.frame, button, counter))
    return ("clu11", controller.frame, button, counter)

  monkeypatch.setattr(hyundaican, "create_clu11", create_clu11)

  cc = SimpleNamespace(
    enabled=True,
    cruiseControl=SimpleNamespace(cancel=False, resume=False, override=False),
  )
  cs = SimpleNamespace(
    lkas11={},
    clu11={
      "CF_Clu_AliveCnt1": 0,
      "CF_Clu_CruiseSwState": Buttons.NONE,
      "CF_Clu_CruiseSwMain": 0,
      "CF_Clu_SldMainSW": 0,
    },
    clu11_ts_nanos=0,
    customCS=SimpleNamespace(mdps12={}, acc_active=acc_active),
    out=SimpleNamespace(
      canValid=True,
      canTimeout=False,
      brakePressed=False,
      cruiseState=SimpleNamespace(available=True),
    ),
  )
  hud_control = SimpleNamespace(leftLaneVisible=False, rightLaneVisible=False)
  return controller, cs, cc, hud_control, sent


def _run_frames(controller, cs, cc, hud_control, frame_count, before_frame=None, update_stock=True):
  for _ in range(frame_count):
    now_nanos = (controller.frame + 1) * CONTROL_STEP_NS
    if update_stock and controller.frame % 2 == 0:
      cs.clu11["CF_Clu_AliveCnt1"] = (cs.clu11["CF_Clu_AliveCnt1"] + 1) & 0xF
      cs.clu11_ts_nanos = now_nanos
    if before_frame is not None:
      before_frame(controller.frame, cs, cc)

    controller.create_can_msgs(False, 0, False, 0, 0.0, False, hud_control, object(), cs, cc, now_nanos)
    controller.frame += 1


def _assert_common_rate_limits(sent):
  frames = [frame for frame, _button, _counter in sent]
  min_frames = Clu11ButtonScheduler.TX_MIN_INTERVAL_NS // CONTROL_STEP_NS
  assert all(next_frame - frame >= min_frames for frame, next_frame in zip(frames, frames[1:], strict=False))
  assert all(count == 1 for count in Counter(frames).values())


def test_sustained_cancel_is_one_bounded_burst(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
  cc.cruiseControl.cancel = True

  _run_frames(controller, cs, cc, hud_control, 2_000)

  assert [button for _frame, button, _counter in sent] == [Buttons.CANCEL] * Clu11ButtonScheduler.MAX_BURST_TX
  _assert_common_rate_limits(sent)


def test_direct_resume_has_bounded_bursts_and_cooldown(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
  cc.cruiseControl.resume = True

  _run_frames(controller, cs, cc, hud_control, 300)

  assert len(sent) > Clu11ButtonScheduler.MAX_BURST_TX
  _assert_common_rate_limits(sent)
  burst_starts = [0]
  for index, (previous, current) in enumerate(zip(sent, sent[1:], strict=False), start=1):
    if current[0] - previous[0] >= Clu11ButtonScheduler.DIRECT_RESUME_RETRY_NS // CONTROL_STEP_NS:
      burst_starts.append(index)
  burst_starts.append(len(sent))
  assert all(end - start <= Clu11ButtonScheduler.MAX_BURST_TX for start, end in zip(burst_starts, burst_starts[1:], strict=False))


def test_custom_button_cannot_bypass_common_scheduler(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch, custom_button=Buttons.RES_ACCEL)

  _run_frames(controller, cs, cc, hud_control, 2_000)

  assert [button for _frame, button, _counter in sent] == [Buttons.RES_ACCEL] * Clu11ButtonScheduler.MAX_BURST_TX
  _assert_common_rate_limits(sent)


def test_auto_enable_is_limited_to_three_message_bursts(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch, custom_button=Buttons.SET_DECEL, acc_active=False)

  _run_frames(controller, cs, cc, hud_control, 300)

  assert len(sent) > Clu11ButtonScheduler.AUTO_ENABLE_MAX_BURST_TX
  _assert_common_rate_limits(sent)
  assert sent[Clu11ButtonScheduler.AUTO_ENABLE_MAX_BURST_TX][0] - sent[Clu11ButtonScheduler.AUTO_ENABLE_MAX_BURST_TX - 1][0] >= 100


def test_cancel_has_priority_over_resume_and_custom(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch, custom_button=Buttons.SET_DECEL)
  cc.cruiseControl.cancel = True
  cc.cruiseControl.resume = True

  _run_frames(controller, cs, cc, hud_control, 100)

  assert sent
  assert all(button == Buttons.CANCEL for _frame, button, _counter in sent)
  _assert_common_rate_limits(sent)


def test_scheduler_is_scoped_to_community_safety(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
  controller.community_safety = False
  cc.cruiseControl.cancel = True

  _run_frames(controller, cs, cc, hud_control, 1)

  assert sent == [(0, Buttons.CANCEL, 0)]


def test_noncommunity_resume_path_is_unchanged(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
  controller.community_safety = False
  controller.frame = 16
  cc.cruiseControl.resume = True

  _run_frames(controller, cs, cc, hud_control, 1)

  assert sent == [(16, Buttons.RES_ACCEL, 16)]


def test_noncommunity_custom_path_is_unchanged(monkeypatch):
  button_msg = object()
  monkeypatch.setattr(hyundaican, "create_clu11", lambda *args: button_msg)

  controller = object.__new__(CarControllerCustom)
  controller.CP = SimpleNamespace()
  controller.NC = SimpleNamespace(update=lambda *args: Buttons.RES_ACCEL)
  controller.resume_cnt = 0
  can_sends = []
  cs = SimpleNamespace(clu11={})

  controller.create_button_messages(object(), can_sends, object(), cs, 0)

  assert can_sends == [button_msg]


def test_can_fault_discards_held_request_until_rearmed(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
  cc.cruiseControl.cancel = True

  def set_request_and_can_state(frame, state, control):
    state.out.canValid = frame != 15
    if 30 <= frame < 35:
      control.cruiseControl.cancel = False
    elif frame == 35:
      control.cruiseControl.cancel = True

  _run_frames(controller, cs, cc, hud_control, 60, before_frame=set_request_and_can_state)

  assert any(frame < 15 for frame, _button, _counter in sent)
  assert not any(15 <= frame <= 35 for frame, _button, _counter in sent)
  assert any(frame > 35 for frame, _button, _counter in sent)


def test_can_timeout_discards_held_request_until_rearmed(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
  cc.cruiseControl.cancel = True

  def set_request_and_can_state(frame, state, control):
    state.out.canTimeout = frame == 15
    if 30 <= frame < 35:
      control.cruiseControl.cancel = False
    elif frame == 35:
      control.cruiseControl.cancel = True

  _run_frames(controller, cs, cc, hud_control, 60, before_frame=set_request_and_can_state)

  assert not any(15 <= frame <= 35 for frame, _button, _counter in sent)
  assert any(frame > 35 for frame, _button, _counter in sent)


def test_stale_stock_clu11_stops_transmission(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
  cc.cruiseControl.cancel = True

  _run_frames(controller, cs, cc, hud_control, 1)
  _run_frames(controller, cs, cc, hud_control, 10, update_stock=False)
  _run_frames(controller, cs, cc, hud_control, 10)

  assert len(sent) == 1

  cc.cruiseControl.cancel = False
  _run_frames(controller, cs, cc, hud_control, 6)
  cc.cruiseControl.cancel = True
  _run_frames(controller, cs, cc, hud_control, 3)

  assert len(sent) == 2


def test_stock_counter_wrap_uses_next_counter():
  scheduler = Clu11ButtonScheduler()
  outputs = []
  for index, counter in enumerate((14, 15, 0, 1), start=1):
    now_nanos = index * Clu11ButtonScheduler.TX_MIN_INTERVAL_NS
    outputs.append(scheduler.schedule(
      Buttons.CANCEL,
      Clu11ButtonScheduler.SOURCE_CANCEL,
      now_nanos,
      counter,
      now_nanos,
      True,
      False,
      Buttons.NONE,
      False,
    ))

  assert [output[1] for output in outputs] == [15, 0, 1, 2]


def test_new_stock_frame_can_be_scheduled_within_freshness_limit():
  scheduler = Clu11ButtonScheduler()
  stock_ts_nanos = 1
  delayed_now_nanos = stock_ts_nanos + Clu11ButtonScheduler.STOCK_TX_MAX_AGE_NS - 1

  delayed = scheduler.schedule(
    Buttons.CANCEL,
    Clu11ButtonScheduler.SOURCE_CANCEL,
    delayed_now_nanos,
    1,
    stock_ts_nanos,
    True,
    False,
    Buttons.NONE,
    False,
  )
  stale_now_nanos = delayed_now_nanos + Clu11ButtonScheduler.TX_MIN_INTERVAL_NS
  stale = scheduler.schedule(
    Buttons.CANCEL,
    Clu11ButtonScheduler.SOURCE_CANCEL,
    stale_now_nanos,
    1,
    stock_ts_nanos,
    True,
    False,
    Buttons.NONE,
    False,
  )

  assert delayed == (Buttons.CANCEL, 2)
  assert stale is None


def test_delayed_stock_phase_is_skipped_without_fault_latch():
  scheduler = Clu11ButtonScheduler()
  stock_ts_nanos = 1
  delayed_now_nanos = stock_ts_nanos + Clu11ButtonScheduler.STOCK_TX_MAX_AGE_NS

  delayed = scheduler.schedule(Buttons.CANCEL, scheduler.SOURCE_CANCEL, delayed_now_nanos, 1, stock_ts_nanos,
                               True, False, Buttons.NONE, False)
  fresh_now_nanos = delayed_now_nanos + Clu11ButtonScheduler.TX_MIN_INTERVAL_NS
  fresh = scheduler.schedule(Buttons.CANCEL, scheduler.SOURCE_CANCEL, fresh_now_nanos, 2, fresh_now_nanos,
                             True, False, Buttons.NONE, False)

  assert delayed is None
  assert fresh == (Buttons.CANCEL, 3)


def test_stable_request_change_rearms_after_debounce():
  scheduler = Clu11ButtonScheduler()

  cancel = scheduler.schedule(Buttons.CANCEL, Clu11ButtonScheduler.SOURCE_CANCEL, 100_000_000, 1, 100_000_000, True, False, Buttons.NONE, False)
  switching = scheduler.schedule(Buttons.RES_ACCEL, Clu11ButtonScheduler.SOURCE_DIRECT_RESUME, 200_000_000, 2, 200_000_000, True, False, Buttons.NONE, False)
  too_early = scheduler.schedule(
    Buttons.RES_ACCEL,
    Clu11ButtonScheduler.SOURCE_DIRECT_RESUME,
    200_000_000 + Clu11ButtonScheduler.REARM_RELEASE_NS - 1,
    3,
    200_000_000 + Clu11ButtonScheduler.REARM_RELEASE_NS - 1,
    True,
    False,
    Buttons.NONE,
    False,
  )
  ready_nanos = 200_000_000 + Clu11ButtonScheduler.REARM_RELEASE_NS
  resumed = scheduler.schedule(
    Buttons.RES_ACCEL,
    Clu11ButtonScheduler.SOURCE_DIRECT_RESUME,
    ready_nanos,
    4,
    ready_nanos,
    True,
    False,
    Buttons.NONE,
    False,
  )

  assert cancel == (Buttons.CANCEL, 2)
  assert switching is None
  assert too_early is None
  assert resumed == (Buttons.RES_ACCEL, 5)


def test_fault_during_request_change_requires_release():
  for fault in ("can", "button"):
    scheduler = Clu11ButtonScheduler()
    assert scheduler.schedule(Buttons.CANCEL, scheduler.SOURCE_CANCEL, 100_000_000, 1, 100_000_000,
                              True, False, Buttons.NONE, False) == (Buttons.CANCEL, 2)
    assert scheduler.schedule(Buttons.RES_ACCEL, scheduler.SOURCE_DIRECT_RESUME, 200_000_000, 2, 200_000_000,
                              True, False, Buttons.NONE, False) is None

    can_valid = fault != "can"
    driver_button = Buttons.SET_DECEL if fault == "button" else Buttons.NONE
    assert scheduler.schedule(Buttons.RES_ACCEL, scheduler.SOURCE_DIRECT_RESUME, 220_000_000, 3, 220_000_000,
                              can_valid, False, driver_button, False) is None
    assert scheduler.schedule(Buttons.RES_ACCEL, scheduler.SOURCE_DIRECT_RESUME, 300_000_000, 4, 300_000_000,
                              True, False, Buttons.NONE, False) is None

    scheduler.schedule(None, None, 400_000_000, 5, 400_000_000, True, False, Buttons.NONE, False)
    rearmed = scheduler.schedule(Buttons.RES_ACCEL, scheduler.SOURCE_DIRECT_RESUME, 450_000_000, 6, 450_000_000,
                                 True, False, Buttons.NONE, False)
    assert rearmed == (Buttons.RES_ACCEL, 7)


def test_driver_button_blocks_held_request_until_rearmed():
  scheduler = Clu11ButtonScheduler()

  blocked = scheduler.schedule(Buttons.CANCEL, Clu11ButtonScheduler.SOURCE_CANCEL, 100_000_000, 1, 100_000_000, True, False, Buttons.SET_DECEL, False)
  still_blocked = scheduler.schedule(Buttons.CANCEL, Clu11ButtonScheduler.SOURCE_CANCEL, 200_000_000, 2, 200_000_000, True, False, Buttons.NONE, False)
  scheduler.schedule(None, None, 300_000_000, 3, 300_000_000, True, False, Buttons.NONE, False)
  rearmed = scheduler.schedule(Buttons.CANCEL, Clu11ButtonScheduler.SOURCE_CANCEL, 400_000_000, 4, 400_000_000, True, False, Buttons.NONE, False)

  assert blocked is None
  assert still_blocked is None
  assert rearmed == (Buttons.CANCEL, 5)


def test_driver_main_button_blocks_held_request_until_rearmed():
  scheduler = Clu11ButtonScheduler()

  blocked = scheduler.schedule(Buttons.CANCEL, scheduler.SOURCE_CANCEL, 100_000_000, 1, 100_000_000,
                               True, False, Buttons.NONE, False, driver_main_button=True)
  still_blocked = scheduler.schedule(Buttons.CANCEL, scheduler.SOURCE_CANCEL, 200_000_000, 2, 200_000_000,
                                     True, False, Buttons.NONE, False)
  scheduler.schedule(None, None, 300_000_000, 3, 300_000_000, True, False, Buttons.NONE, False)
  rearmed = scheduler.schedule(Buttons.CANCEL, scheduler.SOURCE_CANCEL, 400_000_000, 4, 400_000_000,
                               True, False, Buttons.NONE, False)

  assert blocked is None
  assert still_blocked is None
  assert rearmed == (Buttons.CANCEL, 5)


def test_controller_blocks_each_physical_main_button(monkeypatch):
  for field in ("CF_Clu_CruiseSwMain", "CF_Clu_SldMainSW"):
    controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
    cc.cruiseControl.cancel = True
    cs.clu11[field] = 1
    _run_frames(controller, cs, cc, hud_control, 10)

    cs.clu11[field] = 0
    _run_frames(controller, cs, cc, hud_control, 10)
    assert sent == []

    cc.cruiseControl.cancel = False
    _run_frames(controller, cs, cc, hud_control, 6)
    cc.cruiseControl.cancel = True
    _run_frames(controller, cs, cc, hud_control, 3)
    assert len(sent) == 1


def test_short_request_dropout_does_not_rearm_cancel_burst(monkeypatch):
  controller, cs, cc, hud_control, sent = _make_controller(monkeypatch)
  cc.cruiseControl.cancel = True
  _run_frames(controller, cs, cc, hud_control, 50)
  assert len(sent) == Clu11ButtonScheduler.MAX_BURST_TX

  cc.cruiseControl.cancel = False
  _run_frames(controller, cs, cc, hud_control, 2)
  cc.cruiseControl.cancel = True
  _run_frames(controller, cs, cc, hud_control, 100)

  assert len(sent) == Clu11ButtonScheduler.MAX_BURST_TX


def test_brake_cancel_waits_for_stock_delay():
  scheduler = Clu11ButtonScheduler()

  first = scheduler.schedule(Buttons.CANCEL, Clu11ButtonScheduler.SOURCE_CANCEL, 1, 1, 1, True, False, Buttons.NONE, True)
  early = scheduler.schedule(
    Buttons.CANCEL,
    Clu11ButtonScheduler.SOURCE_CANCEL,
    Clu11ButtonScheduler.CANCEL_BRAKE_DELAY_NS,
    2,
    Clu11ButtonScheduler.CANCEL_BRAKE_DELAY_NS,
    True,
    False,
    Buttons.NONE,
    True,
  )
  ready_nanos = 1 + Clu11ButtonScheduler.CANCEL_BRAKE_DELAY_NS
  ready = scheduler.schedule(Buttons.CANCEL, Clu11ButtonScheduler.SOURCE_CANCEL, ready_nanos, 3, ready_nanos, True, False, Buttons.NONE, True)

  assert first is None
  assert early is None
  assert ready == (Buttons.CANCEL, 4)


def test_speed_adjustment_request_keeps_short_feedback_cycle():
  controller = object.__new__(CruiseButtonCtrl)
  controller.btn_cnt = 0
  controller.waittime_press = CruiseButtonCtrl.WAIT_PRESS_FRAMES
  controller.target_speed = 40.0
  controller.VSetDis = 30.0
  controller._state = State.ACCEL

  requests = [controller._case_acc(None) for _ in range(CruiseButtonCtrl.WAIT_PRESS_FRAMES + 1)]

  assert requests == [Buttons.RES_ACCEL] * CruiseButtonCtrl.WAIT_PRESS_FRAMES + [None]
  assert controller._state == State.HOLD_NONE


def test_standstill_resume_request_reaches_five_scheduler_slots():
  cs = SimpleNamespace(
    cruise_buttons=[Buttons.NONE],
    customCS=SimpleNamespace(acc_active=True),
    out=SimpleNamespace(brakePressed=False),
  )

  for phase, expected_frames in ((0, [0, 12, 24, 36, 48]), (1, [1, 13, 25, 37, 49])):
    controller = object.__new__(CruiseButtonCtrl)
    controller.btn_cnt = 0
    controller._state = State.RESUME
    scheduler = Clu11ButtonScheduler()
    requests = []
    sent_frames = []
    stock_counter = 0
    stock_ts_nanos = 0

    if phase == 1:
      stock_counter = 1
      stock_ts_nanos = CONTROL_STEP_NS
      scheduler.schedule(None, None, CONTROL_STEP_NS, stock_counter, stock_ts_nanos,
                         True, False, Buttons.NONE, False)

    for request_frame in range(CruiseButtonCtrl.STANDSTILL_RESUME_PRESS + 1):
      frame = request_frame + phase
      request = controller._case_resume(cs)
      requests.append(request)
      now_nanos = (frame + 1) * CONTROL_STEP_NS
      if frame % 2 == 0:
        stock_counter = (stock_counter + 1) & 0xF
        stock_ts_nanos = now_nanos
      scheduled = scheduler.schedule(request, scheduler.SOURCE_CUSTOM if request is not None else None,
                                     now_nanos, stock_counter, stock_ts_nanos, True, False, Buttons.NONE, False)
      if scheduled is not None:
        sent_frames.append(request_frame)

    assert requests == [Buttons.RES_ACCEL] * CruiseButtonCtrl.STANDSTILL_RESUME_PRESS + [None]
    assert sent_frames == expected_frames
    assert controller._state == State.HOLD_NONE
