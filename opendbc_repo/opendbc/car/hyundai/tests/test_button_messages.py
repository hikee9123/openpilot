from types import SimpleNamespace

from opendbc.car.hyundai import carcontroller, hyundaican
from opendbc.car.hyundai.carcontroller import CarController
from opendbc.car.hyundai.custom.carcontroller import CarControllerCustom
from opendbc.car.hyundai.values import Buttons


def test_classic_resume_queues_one_clu11(monkeypatch):
  button_msg = object()
  monkeypatch.setattr(carcontroller, "process_hud_alert", lambda *args: (0, 0, 0, 0))
  monkeypatch.setattr(hyundaican, "create_lkas11", lambda *args: object())
  monkeypatch.setattr(hyundaican, "create_mdps12", lambda *args: object())
  monkeypatch.setattr(hyundaican, "create_clu11", lambda *args: button_msg)

  controller = object.__new__(CarController)
  controller.CP = SimpleNamespace(openpilotLongitudinalControl=False, flags=0)
  controller.frame = 16
  controller.last_button_frame = 0
  controller.packer = object()
  controller.car_fingerprint = None
  controller.customCC = SimpleNamespace(NC=SimpleNamespace(reset=lambda: None))

  cruise_control = SimpleNamespace(cancel=False, resume=True, override=False)
  cc = SimpleNamespace(enabled=True, cruiseControl=cruise_control)
  cs = SimpleNamespace(
    lkas11={},
    clu11={},
    customCS=SimpleNamespace(mdps12={}),
    out=SimpleNamespace(cruiseState=SimpleNamespace(available=True)),
  )
  hud_control = SimpleNamespace(leftLaneVisible=False, rightLaneVisible=False)

  can_sends = controller.create_can_msgs(False, 0, False, 0, 0.0, False, hud_control, object(), cs, cc)

  assert can_sends.count(button_msg) == 1


def test_custom_button_queues_one_clu11(monkeypatch):
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
