# driver monitoring (DM)

## Upstream baseline

The monitoring policy and daemon follow [commaai/openpilot master at
1b1b60ba93bf70d3a37bc306a02048fc71dd0b2c](https://github.com/commaai/openpilot/tree/1b1b60ba93bf70d3a37bc306a02048fc71dd0b2c/openpilot/selfdrive/monitoring).
This includes the Super Leicht model's `sleepProb > 0.75` distraction check.
Local adaptations are limited to this branch's `cereal` imports, `dcam` camera name,
and `liveCalibration` service name. Tests use this branch's `OpenpilotPrefix` fixture.

Custom blink tuning, no-blink/sleep-candidate warnings, CANCEL acknowledgement,
and diagnostic overlays have been removed. The Qt renderer retains its existing
DriverMonitoringState v2 adapter; the camera preview uses the official Qt implementation.
The model runner and alert event/audio interfaces remain compatible with this branch.

## Parameter review

Compared with commaai/openpilot master `3b2a75a4e08e13a35b6995d0295a96559beddb85`
on 2026-09-20: all 52 `DRIVER_MONITOR_SETTINGS` values match, including eye closure
`0.865`, sleep `0.75`, vision warning times `5/8/13` seconds and lockout durations
`1/5/15/30` minutes. No local sensitivity override is applied.

| Parameter | Official type/default | Lifetime |
| --- | --- | --- |
| `AlwaysOnDM` | BOOL, unset reads false | Persistent |
| `IsRhdDetected` | BOOL, unset reads false | Persistent |
| `DriverTooDistracted` | BOOL, unset reads false | Clear at manager start or ignition on |
| `DriverLockoutCount` | INT, default 0 | Clear at manager start or ignition on |
| `IsDriverViewEnabled` | BOOL, unset reads false | Clear at manager start |
| `RecordFront`, `RecordFrontLock` | BOOL, unset reads false | Persistent |
| `Offroad_DriverMonitoringUncertain` | JSON, no default | Clear at manager start or onroad transition |

The missing uncertainty-alert key and message are restored from that official revision.
Existing manager cleanup removes the 17 retired custom DM keys; persistent official
settings are retained. The first vision warning uses the official one-shot `pre_alert.wav`
(SHA-256 `cc9e67cfaba77e8e4f4049f0add9238660e4cf8f886c6915600d8f47a30c98db`).

Uploading driver-facing camera footage is opt-in, but it is encouraged to opt-in to improve the DM model. You can always change your preference using the "Record and Upload Driver Camera" toggle.

## Troubleshooting

Before creating a bug report, go through these troubleshooting steps.

* Ensure the driver-facing camera has a good view of the driver in normal driving positions.
 * This can be checked in Settings -> Device -> Preview Driver Camera (when car is off).
* If the camera can't see the driver, the device should be re-mounted.

## Bug report

In order for us to look into DM bug reports, we'll need the driver-facing camera footage. If you don't normally have this enabled, simply enable the toggle for a single drive. Also ensure the "Upload Raw Logs" toggle is enabled before going for a drive.
