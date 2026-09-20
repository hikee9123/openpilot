import numpy as np

from cereal import car
from openpilot.selfdrive.ui.soundd import Soundd, sound_list

AudibleAlert = car.CarControl.HUDControl.AudibleAlert


def make_sound(monkeypatch, loops):
  sound = Soundd.__new__(Soundd)
  sound.current_alert = AudibleAlert.promptDistracted
  sound.current_sound_frame = 0
  sound.current_volume = 1.
  sound.loaded_sounds = {sound.current_alert: np.array([0.1, 0.2, 0.3], dtype=np.float32)}
  monkeypatch.setitem(sound_list, sound.current_alert, ("test.wav", loops, 1.))
  return sound


def test_one_shot_stops_at_end_of_sound(monkeypatch):
  sound = make_sound(monkeypatch, 1)
  np.testing.assert_allclose(sound.get_sound_data(8), [0.1, 0.2, 0.3, 0., 0., 0., 0., 0.])
  np.testing.assert_array_equal(sound.get_sound_data(4), np.zeros(4))


def test_repeated_warning_wraps_without_repeating_tail(monkeypatch):
  sound = make_sound(monkeypatch, None)
  sound.current_sound_frame = 1
  np.testing.assert_allclose(sound.get_sound_data(7), [0.2, 0.3, 0.1, 0.2, 0.3, 0.1, 0.2])
  np.testing.assert_allclose(sound.get_sound_data(3), [0.3, 0.1, 0.2])


def test_completed_warning_can_clear_at_exact_sample_boundary(monkeypatch):
  sound = make_sound(monkeypatch, 1)
  sound.get_sound_data(3)
  sound.update_alert(AudibleAlert.none)
  assert sound.current_alert == AudibleAlert.none


def test_warning_escalation_interrupts_current_sound(monkeypatch):
  sound = make_sound(monkeypatch, None)
  sound.get_sound_data(1)
  sound.update_alert(AudibleAlert.warningImmediate)
  assert sound.current_alert == AudibleAlert.warningImmediate
  assert sound.current_sound_frame == 0
