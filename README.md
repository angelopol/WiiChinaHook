# WiiChinaHook

*English · [Español](README.es.md)*

Experimental Windows app that connects up to four Wiimotes (including clones with a
built-in MotionPlus) and publishes controls/motion over DSU and full Wii data over a
local WebSocket API. Dolphin does not need to be running. Two connection modes:

| Mode | Hardware | Notes |
|---|---|---|
| `dolphinbar` (default) | Mayflash DolphinBar in **mode 4** | The PC's Bluetooth stays available to Windows |
| `bluetooth` | USB Bluetooth adapter with **libusbK** (e.g. Intel `8087:0A2A`) | Own passthrough built on Bumble; the adapter is reserved while running |

A graphical app (Flet) configures both modes and shows every controller live,
including a 3D view of the Wiimote's orientation.

## Installation

Tested with Python 3.13 x64; Python 3.11 or later is required.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt
.venv\Scripts\python -m pip install -e . --no-deps
```

`requirements.lock.txt` includes the GUI. For the console only, install with
`pip install -e .`; add the GUI later with `pip install -e .[gui]`.

Close Dolphin before using WiiChinaHook: only one program may control the DolphinBar
or the adapter at a time. To go back to Dolphin, stop the service.

## Graphical app

```powershell
.venv\Scripts\python wiichinahook.py gui
```

- **Controllers:** one card per slot with buttons, accelerometer, MotionPlus rates,
  IR pointer, Nunchuk stick, battery and an **Orientation** view: a 3D Wiimote that
  follows the real controller (MotionPlus + gravity). The heading has no absolute
  reference and drifts slowly; **Recenter** makes the current heading "pointing at
  the screen" (lying flat) or "buttons facing you" (sideways grip). Without
  MotionPlus the view shows tilt only. Rumble, LEDs, gyro bias calibration, MotionPlus
  scale calibration and forget are one click away; in Bluetooth mode a pairing panel
  appears. Each card also has the per-remote **quick calibration** and **sensor bar
  calibration** switches (see below).
- **Settings:** connection mode, DSU/API ports, IR and MotionPlus switches, saved to
  `config.local.json`. In Bluetooth mode the app lists the adapters that use the
  libusbK/WinUSB driver; if there is none it explains how to install one with Zadig
  and offers to open or download it. **Adapter driver** switches an adapter between
  libusbK and its Windows Bluetooth driver without Zadig (see below).
- **Log:** live service log.
- English and Spanish UI (language selector in the header).

The GUI runs the service in its own process and stops it when the window closes. If
a service is already running (for example `hook` from the console), the GUI connects
to it instead.

## Using the DolphinBar (default mode)

1. Set the DolphinBar to **mode 4** (press its mode button until LED 4 lights). In
   this mode Windows sees four HID devices `057E:0306`, one per slot.
2. Pair each Wiimote on the bar: SYNC on the bar, then SYNC on the Wiimote.
3. Start the service and check the state:

```powershell
.venv\Scripts\python wiichinahook.py hook
.venv\Scripts\python wiichinahook.py devices
.venv\Scripts\python wiichinahook.py calibrate --slot 0
```

The bar slot (0–3) is the app slot. A connected remote is detected within about two
seconds and its loss within about ten. `pair` is not used in this mode. `calibrate`
measures the gyro bias (keep the remote still) and stores it per slot in
`.wiichinahook/dolphinbar.json`; `forget --slot N` deletes those settings, not the
pairing stored in the bar.

The bar drops the memory-read replies of clone remotes, so the app initializes
without reads: it detects the Nunchuk from the status report and the MotionPlus from
the shape of its data. The accelerometer uses typical calibration values (zero
`0x80`, 1 g `0x9a`, the factory values of the validated clone) and the MotionPlus
uses nominal values plus the `calibrate` bias. The bar does not expose the remote's
Bluetooth address, so DSU publishes a fixed locally administered MAC per slot
(`02:00:44:42:00:0N`).

## Using Bluetooth passthrough (`--mode bluetooth`)

The reference adapter is an Intel `8087:0A2A` with **libusbK 3.1.0.0**. While it has
that driver, Windows cannot use it as a normal Bluetooth adapter. Install the driver
with [Zadig](https://zadig.akeo.ie/): *Options → List All Devices*, choose the
adapter, select libusbK and *Replace Driver*.

In one terminal:

```powershell
.venv\Scripts\python wiichinahook.py hook --mode bluetooth
```

or set `"mode": "bluetooth"` in `config.local.json`. In another terminal, open a
pairing window and press the red **SYNC** button:

```powershell
.venv\Scripts\python wiichinahook.py pair --seconds 30
.venv\Scripts\python wiichinahook.py devices
.venv\Scripts\python wiichinahook.py monitor
```

To connect with **1 + 2**, use `pair --mode temporary`: the PIN is then the remote's
address, while SYNC uses the host address. If you know the MAC,
`pair --address XX:XX:XX:XX:XX:XX` avoids relying on discovery. Automatic discovery
looks at name/device class: check `devices` and use an explicit address if other
Bluetooth devices are nearby. Reconnection attempts pause while a pairing window is open.

Repeat the synchronization for the other remotes. Slots `0–3`, link keys per adapter
and manual calibration are stored. Known remotes reconnect when switched on (press a
button); the remote must keep the bond (SYNC, not temporary mode).

```powershell
.venv\Scripts\python wiichinahook.py led --slot 0 --mask 0x10
.venv\Scripts\python wiichinahook.py rumble --slot 0 --duration-ms 500
.venv\Scripts\python wiichinahook.py calibrate --slot 0
.venv\Scripts\python wiichinahook.py forget --slot 0
```

`calibrate` measures the gyro bias for three seconds: keep the remote still. The
accelerometer scale comes from the factory calibration; when it is unavailable the
API reports nominal values. A Nunchuk without valid calibration keeps raw
acceleration and a nominally scaled stick.

### MotionPlus scale calibration

Some clones report rotation rates that are too high (the validated clone: ~1.85× in
pitch) or with an inverted axis. `calibrate --slot N --axis pitch|roll|yaw` (or
**Calibrate scale** in the GUI) measures each axis against gravity: hold the axis
horizontal, wait for the first short vibration while still, then after the second one
turn the remote slowly about 90° and hold it until the long vibration. Pitch: lift the
tip from flat. Roll: roll a flat remote onto its side. Yaw: hold it sideways (buttons
facing you) and turn it like a steering wheel. The exact angle does not matter. The
per-axis factor (negative when the axis was inverted) is stored with the remote/slot
and applies to the API, the orientation view and DSU.

| Pitch | Roll | Yaw |
|---|---|---|
| ![Pitch: lift the tip](src/wiichinahook/gui/assets/calibration_pitch.gif) | ![Roll: roll onto its side](src/wiichinahook/gui/assets/calibration_roll.gif) | ![Yaw: steering wheel](src/wiichinahook/gui/assets/calibration_yaw.gif) |

The yellow line is the axis being calibrated; the bar shows the phases (grey: still,
blue: turn, green: hold) and the zigzags mark the vibrations. The GIFs are rendered
from the app's own 3D model by `tools/make_calibration_gifs.py` (needs the `[dev]` extra).

### Quick calibration and sensor bar calibration

Both are per remote (slot), off by default, and can be changed live from each card in
the GUI:

- **Quick calibration** — like the recenter button in games such as *Zelda: Skyward
  Sword*. Hold the chosen combination (− and +, ↓, 1 and 2, A and B, or Home) for
  ~0.6 s: short vibration, keep the remote still ~1 s. A double vibration means the gyro
  bias was refreshed and the orientation recentered; a long one means it moved, so it
  was only recentered. Leave it off for games that calibrate by themselves.
- **Sensor bar calibration** — while the IR camera sees both dots of the sensor bar and
  the remote is roughly level, their horizontal position gives the real direction to
  the screen and slowly removes the heading drift (as the Wii does). The heading then
  becomes absolute: 0 = pointing at the bar.

In `config.local.json` they are stored as
`"slots": [{"quick_calibration": false, "combo": "minus+plus", "ir_calibration": false}, …]`
(combos: `minus+plus`, `down`, `one+two`, `a+b`, `home`).

Rumble lasts at most five seconds and stops when the session closes. `forget`
removes the registry entry and the local link key; it does not change bonds stored
inside the Wiimote. Wait for connection/pairing attempts to finish before using it.

### Switching the adapter driver without Zadig

Windows keeps every installed driver package. Once an adapter has had libusbK (Zadig
the first time), **Settings → Adapter driver** switches it both ways: **Use with
WiiChinaHook (libusbK)** and **Restore Windows Bluetooth**. The app forces the newest
matching package from the driver store (`C:\Windows\INF\oem*.inf`) with
`UpdateDriverForPlugAndPlayDevices`; without a vendor Bluetooth package it falls back to
Microsoft's generic `bth.inf`. Windows asks for administrator permission; stop the
service first if it is using the adapter. The same is available as
`python -m wiichinahook.drivers list --vid 8087 --pid 0a2a`.

Clone "CSR 4.0" dongles (`0A12:0001`, `bcdDevice 0x8891`) declare a duplicated USB
alternate setting; Windows refuses to start them with libusbK, WinUSB or UsbDk (Code
10), which is also why they fail with Dolphin's passthrough. They are not supported.

## Configuration

`hook` and the GUI use `config.local.json` when it exists; otherwise they use the
DolphinBar. Copy `config.example.json` to customize it. `mode` selects `dolphinbar`
or `bluetooth`, and `--mode` on the command line overrides it. The rest of this
section (preloaded remotes, `dongle`) only applies to `bluetooth` mode.

You can preload remotes:

```json
"wiimotes": [
  {"address": "00:11:22:33:44:55", "slot": 0, "pin_mode": "sync"},
  {"address": "00:11:22:33:44:66", "slot": 1, "pin_mode": "sync"}
]
```

Stored slots are never silently reassigned. Remove a remote with `forget` before
changing its slot, and also remove it from the configuration if you do not want it
added again. The legacy configuration with a single `wiimote` object is accepted.
The legacy `report_mode` no longer controls the output: it is chosen from the active
sensors. In `bluetooth` mode, DSU publishes the remote's real MAC.

`dongle.transport` sets an explicit Bumble selector, for example `usb:8087:0a2a#0`.
A legacy `usb:0` together with VID/PID is migrated to VID/PID selection.
`ir: false` and `motionplus: false` help isolate problems.

## Outputs

**DSU:** UDP `127.0.0.1:26760`, protocol 1001, four slots. Add this source in
Dolphin/Cemu or another DSU client. Do not enable Dolphin's passthrough on the same
adapter at the same time. DSU is not a real Bluetooth Wiimote: each emulator maps
the inputs it supports.

- Same button mapping as before.
- Nunchuk: left stick, C → L1 and Z → L2.
- Acceleration in g; gyro in degrees/second, with the axes and signs Dolphin's DSU
  client expects (x left, y down, z forward; pitch up, yaw right, roll right).
- Without a valid sensor, DSU numeric fields are zero; the API keeps the difference
  between a missing sensor and a measured zero.
- Full IR, orientation and LED/rumble commands are available through the API, not
  through DSU extensions.

**API:** WebSocket `ws://127.0.0.1:26761`, JSON v1. Loopback only; browser origins
are rejected. It is an interface for local clients; the GUI uses it too.
Specification and examples in [docs/API.md](docs/API.md).

## Diagnostics and tests

```powershell
.venv\Scripts\python wiichinahook.py usb-list
.venv\Scripts\python wiichinahook.py usb-find --vid 0x8087 --pid 0x0a2a
.venv\Scripts\python wiichinahook.py hook --verbose --duration 30
.venv\Scripts\python -m pytest -q
```

`scan-wiimotes`, `usb-hci-info`, `usb-hci-scan`, `usb-hci-listen` and
`usb-hci-pair-window` remain available. Run them with the service stopped; they are
independent diagnostics. The service never mixes its Bumble transport with
concurrent PyUSB access.

HCI `.btsnoop` traces, `hook.log` and local state are stored in `.wiichinahook/`
(ignored by Git). Traces may contain pairing keys: review them before sharing.
Compare a session with a Dolphin capture if a clone fails.

The test suite uses documented synthetic packets, simulated connections, local
sockets and a few captures from the real clone (`tests/data/`). It is not hardware
certification. See [docs/VALIDATION.md](docs/VALIDATION.md) for physical checks.

## Limitations of this version

No speaker, Windows virtual gamepad or accessories other than the Nunchuk. Basic
four-point IR only (no camera image). The orientation heading drifts (no magnetometer)
and the clone's nominal MotionPlus scale is too high (~1.3–1.85×) until the scale
calibration is run on each axis. Clone quirks are added when reproduced, not through PIN
changes or random sequences.

Protocol references:
[Bumble](https://google.github.io/bumble/),
[Wiimote](https://wiibrew.org/wiki/Wiimote),
[MotionPlus](https://wiibrew.org/wiki/Wiimote/Extension_Controllers/Wii_Motion_Plus),
[Nunchuk](https://wiibrew.org/wiki/Wiimote/Extension_Controllers/Nunchuck),
[DSU](https://v1993.github.io/cemuhook-protocol/).
