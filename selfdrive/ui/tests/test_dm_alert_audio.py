from pathlib import Path
import wave

from cereal import car, log
from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.selfdrived.events import EVENTS, ET
from openpilot.selfdrive.ui.soundd import SAMPLE_RATE, sound_list


def test_first_vision_warning_uses_official_one_shot_audio():
  audible = car.CarControl.HUDControl.AudibleAlert
  assert 'preAlert' in audible.schema.enumerants
  warning = EVENTS[log.OnroadEvent.EventName.preDriverDistracted][ET.PERMANENT]
  assert warning.audible_alert == audible.preAlert
  filename, loops, _ = sound_list[warning.audible_alert]
  assert filename == 'pre_alert.wav'
  assert loops == 1
  with wave.open(str(Path(BASEDIR) / 'selfdrive/assets/sounds' / filename), 'rb') as wav:
    assert wav.getnchannels() == 1
    assert wav.getsampwidth() == 2
    assert wav.getframerate() == SAMPLE_RATE
    assert wav.getnframes() > 0


def test_first_wheeltouch_warning_remains_silent():
  warning = EVENTS[log.OnroadEvent.EventName.preDriverUnresponsive][ET.PERMANENT]
  assert warning.audible_alert == car.CarControl.HUDControl.AudibleAlert.none
