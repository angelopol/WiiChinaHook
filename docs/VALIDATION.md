# Validation

*English · [Español](VALIDATION.es.md)*

## Checked automatically

- Button reports, accelerometer low bits, basic/extended IR, status, interleaved
  Nunchuk and MotionPlus data; truncated packets.
- Calibration, checksums, memory reassembly and acknowledgement errors.
- Binary PIN through Bumble's real Host callback.
- Disconnection, authentication failure and automatic rumble shutdown.
- Persistent registry of four slots per adapter.
- DSU with local sockets, CRC, slot/MAC selection and expiry.
- Real WebSocket: version, errors, commands and subscriptions.
- Retries with backoff, deletion of a rejected link key, accepting incoming links as
  central; inquiry retried while another remote is being paged.
- Simulated DolphinBar transport with the captured behaviour (lost reads, `0x30`
  filler, MotionPlus/Nunchuk formats).
- Orientation filter: sign conventions, gravity correction and replay of a real clone
  capture (`tests/data/clone_axes_capture.json`).
- Windowless GUI: model, translations, service lifecycle, attaching to a running
  service, slot cards and 3D projection; adapter detection.

Except where marked as captures below, test vectors are synthetic.

## Checked on this PC

Intel `8087:0A2A`, libusbK `3.1.0.0`, Python 3.13 x64: USB enumeration, opening
through Bumble, Classic initialization, reading the controller address, starting
DSU/API and closing the transport normally.

### Clone `00:17:AB:AE:1A:6D` (2026-10-05)

Clone Wiimote with a built-in MotionPlus (`a6 20 00 05`), Nunchuk (`a4 20 00 00`) and
a sensor bar.

| Test | Result |
|---|---|
| Clone with SYNC | OK: binary PIN, both HID channels, slot LED, `0x37` reports |
| Reconnection | OK: after restarting the app, pressing A reconnects with the stored key |
| Acceleration | OK at rest: `[-0.04, 0.04, 1.0] g` with factory calibration |
| MotionPlus | OK in passthrough mode with the Nunchuk; `calibrate` removes the bias |
| IR | OK: 2 points from the sensor bar |
| Nunchuk | OK: stick, C and Z |
| DSU | OK: slot 1 connected, real MAC, battery, Nunchuk stick on LX/LY |
| Shutdown | OK: `--duration` ends with `HCI_RESET` and releases the adapter |

Clone quirks, each backed by a trace and a test built from the captured bytes:

- L2CAP: the *Configure Request* carries the hint option `80 02 20 03`. Bumble
  answered `Unknown options` and the HID channel got stuck (`bumble_compat.py`).
- A link key whose pairing was interrupted before HID is rejected with `0x05`. The
  app deletes the key and falls back to the PIN.
- When reconnecting on its own, the remote drops the link (`0x13`) if the host
  accepts as peripheral or requests authentication. The app accepts as central (like
  the Wii) and lets the remote open HID.
- `0x21` memory replies arrive unpadded (only the requested bytes), and a 32-byte
  read arrives in one oversized report.
- Activating MotionPlus sends transient `0x20` status reports (`0x28` → `0x2a`). The
  app waits 0.5 s before deciding whether the extension really changed.
- The factory calibration of the MotionPlus and of the Nunchuk accelerometer is
  invalid. Nominal values and `calibrate` (gyro bias) are used.

### DolphinBar, mode 4, same clone (2026-10-06)

Mayflash DolphinBar (`0079:1802` in mode 1; in mode 4, four HID `057E:0306`).

| Test | Result |
|---|---|
| Data, `0x22` acknowledgements, `0x20` status | Delivered; ~235 reports/s in mode `0x37` |
| `0x21` memory reads | **None arrive**: the bar drops the clone's unpadded replies |
| MotionPlus without reads | OK with `a600f0=55` and `a600fe=04/05/07`, via `WriteFile` and `HidD_SetOutputReport`. Same bias at rest as over direct Bluetooth (5.6 / −4.7 / 11.2 °/s); rotations up to ±900 °/s |
| Nunchuk | OK: full stick range, C, Z; in passthrough with MotionPlus |
| Unplug/plug Nunchuk | Reflected in the "extension" bit of MotionPlus packets; **no** `0x20` report arrives |
| IR | OK, 2 points (the bar is the IR source) |
| Accelerometer | 1.0 g at rest with the typical calibration (the clone's factory values) |
| Full app (`hook`) | Slot detected in < 0.1 s, ready in ~4 s, `calibrate` stored, DSU with local MAC, immediate shutdown |
| Leaving and coming back | Remote switched off: slot disconnected; switched on: ready again in ~1 s |
| Remote gone from the bar | The empty slot keeps emitting `0x30` filler; liveness uses reports of the configured mode |

The `0x16` write format is `[space|0x02][address 3 bytes][size][16 data]`. The first
manual tests duplicated the space byte and wrongly concluded that MotionPlus could
not be activated through the bar.

### MotionPlus axes (guided capture, 2026-10-06)

Clone through the DolphinBar: remote at rest, then roll, pitch and one full
counter-clockwise turn on the table.

| Movement | Result |
|---|---|
| Pitch (tip up) | Accelerometer Y → +0.81; correlation +0.99 between the gravity angle and integrated pitch |
| Roll | Correlation −0.65 with the raw X/Z gravity angle: consistent with roll + = left side down |
| Counter-clockwise turn | Integrated yaw +469°, roll/pitch ≈ 0 |

This capture alone was misread: its first pitch excursion was taken as "tip up".
A later guided check with held poses (tip at the ceiling read Y = −1 g; right side down
read X = +1 g), the user's sideways photo (X = −1 g with the tip to the left and the
buttons facing the player) and the gravity-based scale calibration (all three factors
positive in this frame) settle it: the raw frame is right-handed with +X = left,
+Y = back (1/2 buttons end), +Z = buttons face, and the MotionPlus pitch/roll/yaw are
right-handed about those axes (pitch + = tip down, roll + = left side down, yaw + =
counter-clockwise). This is also Dolphin's IMU frame (`IMUAccelerometer.cpp`,
`IMUGyroscope.cpp`). The clone's nominal scale is too high: integrated pitch is 1.85× the
gravity angle and the full turn read 469° instead of 360°. With a 1/1.85 scale the
filter tracks pitch with a 2.6° median error.

### GUI (2026-10-06)

Tested by the user in both modes: connection, buttons, accelerometer, MotionPlus,
LEDs and rumble. Closing the window stops the service and leaves no orphan processes.

### Clone "CSR 4.0" adapter `0A12:0001` (2026-10-06)

`bcdDevice 0x8891`. Its descriptor declares alternate setting 5 of interface 1 twice.
Windows does not start it with libusbK or WinUSB (Code 10,
`STATUS_INVALID_DEVICE_REQUEST`), and UsbDk 1.0.22 enumerates it but cannot redirect
it. Not supported.

### DSU axes (2026-10-06)

Derived from Dolphin's source (`DualShockUDPClient.cpp` and `IMUAccelerometer.cpp`):
"Accel Up" = −y, "Accel Left" = +x, "Accel Forward" = +z, and at rest Dolphin expects
+1 g up; "Gyro Pitch Up" = +pitch, "Roll Right" = +roll, "Yaw Right" = +yaw. Its IMU
groups combine them as x = Left − Right, y = Backward − Forward, z = Up − Down and
x = PitchDown − PitchUp, y = RollLeft − RollRight, z = YawLeft − YawRight: the Wii frame.
DSU therefore sends `(X, −Z, −Y)` and `(−pitch, −yaw, −roll)`. Still to confirm in
Dolphin itself (see below).

### DSU connection flapping in Dolphin (2026-10-06)

Reported: Dolphin's DSU device kept connecting and disconnecting. Dolphin asks for port
info every second and removes a server's devices when no port-info reply arrives for
1 s; it also recreates them whenever a slot's model changes. On Windows, pad data sent
to a client that had closed its socket (Dolphin reconfiguring) came back as
WSAECONNRESET on every `recvfrom`, and the server stopped reading on that error, so
the port-info requests went unanswered (reproduced: 4 of 11 answered). Fixed by
disabling `SIO_UDP_CONNRESET`, continuing to read after such errors (11 of 11) and
reporting a constant "full gyro" model for connected remotes. Regression test in
`tests/test_dsu.py`; still to confirm in Dolphin itself.

### MotionPlus scale calibration

Fit against gravity tested with simulated turns about every axis (scale 1.85, inverted
signs, bias) and with the real clone pitch capture (factor ≈ 1/1.85).

## Pending physical checks

| Test | Acceptance |
|---|---|
| 30-minute session | No hangs; continuous samples and recovery after disconnection |
| Acceleration | Close to 1 g on the vertical axis in six orientations |
| MotionPlus scale | After `calibrate --axis` on the three axes, a 90° turn reads ≈ 90° |
| DSU in Dolphin | Emulated Wiimote with DSU motion: at rest gravity points down in Dolphin's indicators; tilting/turning moves them the same way |
| GUI orientation | The 3D model follows the remote on all three axes; slow heading drift |
| IR | At most four points; they disappear when the camera is covered |
| Nunchuk | Remove/insert with and without MotionPlus |
| Several remotes | Persistent slots, no crossed data/LEDs/rumble (both modes) |
| USB unplugged | Disconnected states and recovery when plugged back |
| Back to Dolphin | Close the service and use the adapter from Dolphin again |
| Driver switch | Settings → Adapter driver: Intel to libusbK and back to Windows Bluetooth, with UAC, no Zadig |
| Quick calibration | Holding the combo ~0.6 s: double rumble when still (bias refreshed, recentered), long rumble when moving |
| Sensor bar calibration | Pointing at the bar removes heading drift; **check the IR image sign** (turning left must keep the bar straight ahead) |
| DSU mode | Following [the Dolphin guide](guides/dolphin.md): B + → switches to DSU and Dolphin's emulated Wii Remote gets buttons, Nunchuk, accelerometer and gyro; in mode 1 the DSU device stays connected but idle. Same with Cemu ([guide](guides/cemu.md)), "Use motion" on |
| Xbox modes | B + arrows switch modes with N rumbles; game template drives a virtual Xbox controller (Windows "Game controllers" panel / a game); games' rumble reaches the Wiimote |
| Xbox shakes / IR stick | Wiimote and Nunchuk shake directions and the IR right-stick vertical direction match the movement |

For each test record the remote/accessory model, configuration, result and trace path.
