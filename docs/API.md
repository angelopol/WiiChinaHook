# Local API v1

*English · [Español](API.es.md)*

JSON over WebSocket at `ws://127.0.0.1:26761`. Each request carries `v`, `id`,
`command` and optionally `args`. The server replies with the same `id` and `ok`.

```json
{"v":1,"id":1,"command":"devices"}
{"v":1,"id":2,"command":"pair","args":{"seconds":30,"mode":"sync"}}
{"v":1,"id":3,"command":"subscribe"}
{"v":1,"id":4,"command":"led","args":{"slot":0,"mask":16}}
{"v":1,"id":5,"command":"rumble","args":{"slot":0,"duration_ms":500}}
{"v":1,"id":6,"command":"calibrate","args":{"slot":0}}
{"v":1,"id":7,"command":"forget","args":{"slot":0}}
{"v":1,"id":8,"command":"calibrate_axis","args":{"slot":0,"axis":"pitch"}}
{"v":1,"id":9,"command":"slot_options","args":{"slot":0,"quick_calibration":true,"combo":"down","ir_calibration":true}}
{"v":1,"id":10,"command":"quick_calibrate","args":{"slot":0}}
{"v":1,"id":11,"command":"gamepad"}
{"v":1,"id":12,"command":"gamepad_mode","args":{"mode":1}}
{"v":1,"id":13,"command":"gamepad_config","args":{"config":{"modifier":"wm_b","mode":1,"modes":[{"buttons":{"A":"wm_a"}},{"type":"dsu"},null,null]}}}
```

`gamepad` returns the mode status: `mode`, `modifier`, `modes` (template names or
null), `types` (`"xbox"`, `"dsu"` or null per mode), `pads` (slots with a virtual controller), `problems` (per slot, bindings it cannot
drive), `error` (e.g. ViGEmBus missing) and the full `config`. `gamepad_mode` switches
every remote, `gamepad_config` replaces the configuration (validated; unspecified Xbox
controls are unassigned). A mode is `null` (empty), an Xbox template (`"type": "xbox"`,
the default) or `{"type": "dsu", "name": "DSU"}`. DSU clients receive input only while a
DSU mode is active; in the other modes the slots stay connected with neutral data (10 packets per second instead of every report). A
configuration without `"version": 2` whose mode 2 is empty gets the DSU mode there.
Sources: `wm_up/down/left/right/a/b/minus/plus/home/1/2`,
`nc_c`, `nc_z`, `wm_shake_x/y/z` and `nc_shake_x/y/z` (shake along an axis, either
direction; the older `*_shake_left/right/up/down/forward/back` are still accepted), or up
to three of them joined with `+` (buttons and/or shakes); per-template `shake_wm` and
`shake_nc` give the per-axis thresholds in g and `gyro_full_dps`/`gyro_full_dps_y` the
horizontal/vertical gyro sensitivity. The status `shakes` (`seq`, last events per slot
with `device`, `axis`, `g`) is meant for tuning; sticks `nc_stick`, `gyro_angle` (aim, holds; `angle_full_deg`/`angle_full_deg_y` degrees for full deflection), `gyro` (speed, springs back), `ir`. After `subscribe`,
`{"event":"gamepad","data":...}` arrives whenever the mode or its warnings change, and
`{"event":"xbox","data":{"slot":0,"active":true,"buttons":["A"],"lt":0,"rt":1,"lx":0,"ly":0,"rx":0,"ry":0}}`
whenever a slot's virtual controller output changes (`"active": false` when it has none).

`subscribe` accepts `"args": {"hz": N}` and `stream_rate` (`{"hz": N}`) changes it later:
at most N `state`/`xbox` events per second and slot (1–60, default 60), or 0 to pause them
while `gamepad` events keep arriving; on resume the latest state is sent. The GUI uses 30,
and 0 while it is hidden in the tray.

`play_sound` (`{"slot": 0, "sound": "chime", "volume": 0.5}`) plays a built-in sound
(`beep`, `blip`, `chime`, `alert`, `count`) or a `.wav` file path on that remote's
speaker. It replies when the sound ends with `slot`, `sound` and `seconds`, and a new
sound cuts the one playing. `speaker_config` (`{"config": {...}}`) replaces the event
sounds (`enabled`, `volume`, `events`); see [SPEAKER.md](SPEAKER.md).

`slot_options` changes a slot's quick/sensor-bar calibration options live (only the
given fields; the reply has all of them) and `quick_calibrate` runs the same quick
calibration as the button combination (reply `{"bias_updated": true|false}`).

`calibrate_axis` (axis `pitch`, `roll` or `yaw`) runs the guided MotionPlus scale
calibration described in the README and replies after about 7 s with `factor`,
`rotation_deg`, `correlation` and the new `gyro_scale`; it fails with a message when
the axis was not horizontal, the turn was too small or the remote moved at the start.

`pair` also accepts `address` and `mode: "temporary"`. Its reply confirms that the
pairing window was scheduled, not that a remote is already connected. `devices` and
the `subscribe` reply contain `adapter`, `mode` (`dolphinbar` or `bluetooth`),
`ready`, `error`, `pairing` and `devices`.

In `dolphinbar` mode, `pair` returns an error (remotes are paired on the bar),
`forget` deletes the slot's stored settings, and `address` is a fixed locally
administered MAC per slot (`02:00:44:42:00:0N`) because the bar does not expose the
remote's address.

Valid slots: 0–3. LED takes a mask 0x10–0xF0 (high bits only); rumble duration:
0–5000 ms. Zero stops the motor.

```json
{"v":1,"id":4,"ok":true,"result":{"slot":0}}
{"v":1,"id":4,"ok":false,"error":{"code":"request_failed","message":"Slot is not connected"}}
```

After `subscribe`, events arrive:

```json
{"v":1,"event":"state","data":{"address":"00:11:22:33:44:55","slot":0,"connected":true,"phase":"ready","buttons":8}}
```

The example is abbreviated. The full state contains:

| Field | Meaning |
|---|---|
| `phase`, `error` | disconnected, connecting, authenticating, opening, initializing or ready; last error |
| `capabilities` | buttons, accelerometer, ir, motionplus, nunchuk |
| `buttons` | 16-bit Wii mask; accelerometer bits removed |
| `battery` | Fraction 0–1 or null |
| `accel_raw`, `accel_g` | Three Wii axes X/Y/Z, raw 10-bit and in g |
| `gyro_raw`, `gyro_dps` | Yaw, roll, pitch; raw and degrees/second |
| `orientation` | Body-to-world quaternion `[w,x,y,z]`; null without data (see below) |
| `ir` | Four points `{x,y,size}`; invisible point = null; sensor without reading = null |
| `nunchuk` | Normalized `stick` [-1,1], `stick_raw`, `c`, `z`, `accel_raw`, `accel_g` |
| `extension` | null, nunchuk, motionplus or motionplus+nunchuk |
| `timestamp_us` | Monotonic time of the last report/state in microseconds |
| `accel_timestamp_us`, `gyro_timestamp_us`, `ir_timestamp_us`, `nunchuk_timestamp_us` | Time of each sample; 0 before the first one |
| `calibration` | Calibration sources, manual gyro bias and `gyro_scale` (yaw, roll, pitch factors), if any; `recenter_seq` increases on every quick calibration; `heading: "ir"` once the sensor bar corrects the heading |

**Axes.** `accel_g` uses the raw Wii frame, which is right-handed: +X to the remote's
**left**, +Y towards the **back** (the 1/2 buttons end), +Z out of the buttons face.
Lying face up it reads Z = +1 g; pointing at the ceiling, Y = −1 g. `gyro_dps` rates are
right-handed about the same axes: pitch + = tip down, roll + = left side down, yaw + =
counter-clockwise seen from above (Dolphin's IMU uses this frame too). `orientation`
uses the body frame X right, Y tip, Z buttons face (the raw frame turned 180° about Z)
and maps it to a world with X right, Y towards the screen and Z up. With a MotionPlus it is estimated
by a complementary filter at the full report rate; the heading (yaw) has no absolute
reference and drifts. Without MotionPlus it reflects accelerometer tilt only (yaw 0).

Times are process-monotonic, not UTC dates. Samples are kept across interleaved
reports and each sensor keeps its own time. Measurements are cleared on disconnect.
Basic IR yields `size: null`; its coordinates are raw, not a screen cursor. DSU axes
are adapted at the output boundary to Dolphin's DSU client (`DualShockUDPClient.cpp`):
acceleration `(X, −Z, −Y)` and gyro `(−pitch, −yaw, −roll)`, i.e. x left, y down, z forward,
pitch up, yaw right, roll right.

Telemetry events are coalesced to at most 60 Hz per remote. Slow clients receive the
latest state; this is not a lossless capture channel. Use `.btsnoop` to inspect every
packet. Requests are limited to 16 KiB. Close the WebSocket to stop a subscription.
Commands run in the process that owns the adapter, avoiding a second USB open.
