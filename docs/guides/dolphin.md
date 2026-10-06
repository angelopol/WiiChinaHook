# Dolphin with the DSU mode

*English · [Español](dolphin.es.md)*

This guide sets up an **emulated Wii Remote** in Dolphin that takes your real remote's
buttons, Nunchuk, accelerometer and MotionPlus gyroscope from WiiChinaHook over DSU
(the "cemuhook" protocol).

## 1. Put WiiChinaHook in the DSU mode

1. Start WiiChinaHook and connect the remote (DolphinBar or Bluetooth passthrough).
2. Switch to **mode 2 (DSU)**: hold **B** and press **→** on the remote (it rumbles
   twice and LED 2 blinks), or click *Mode 2* in the *Xbox controller* tab.

In the other modes the DSU server keeps the remotes listed as connected but sends no
input, so a game never receives the same remote twice (Xbox and DSU).

The DSU server listens on `127.0.0.1:26760` (change it in *Settings*).

## 2. Enable the DSU client in Dolphin

1. **Controllers** → **Alternate Input Sources**.
2. In the **DSU Client** tab, tick **Enable**.
3. The list already contains `DS4Windows` at `127.0.0.1:26760`. That is WiiChinaHook's
   default address, so you can keep it. Otherwise click **Add…** and enter
   `127.0.0.1` and `26760` (any description, e.g. `WiiChinaHook`).
4. Close the window.

Dolphin asks the server for its slots every second. With WiiChinaHook running, the
devices appear as `DSUClient/0/<description>`, `DSUClient/1/<description>`, …, where the
number is the remote's slot (slot 0 = remote 1, LED 1).

## 3. Configure the emulated Wii Remote

**Controllers** → *Wii Remote 1*: **Emulated Wii Remote** → **Configure**.

In **Device**, choose `DSUClient/0/<description>`. Every binding below is the name
Dolphin shows for that DSU input. You can click a field and press the button on the
remote, or right-click the field, open the advanced editor and pick the input from the
list. The advanced editor is the reliable way for motion inputs, because moving the
remote triggers several axes at once.

### Buttons (*General and Options* tab)

| Wii Remote | DSU input |
|---|---|
| A | `Circle` |
| B | `Triangle` |
| 1 | `Square` |
| 2 | `Cross` |
| − | `Share` |
| + | `Options` |
| HOME | `PS` |
| D-Pad Up / Down / Left / Right | `Pad N` / `Pad S` / `Pad W` / `Pad E` |

The D-pad is reported as it is on the remote (Up = the arrow towards the tip). For
games played with the remote sideways, Dolphin rotates it when you tick
*Options → Sideways Wii Remote*. Don't swap the bindings for that.

### Extension: Nunchuk

In **Extension**, choose **Nunchuk**. Then, in the extension's buttons and stick:

| Nunchuk | DSU input |
|---|---|
| C | `L1` |
| Z | `L2` |
| Stick Up / Down | `Left Y+` / `Left Y-` |
| Stick Left / Right | `Left X-` / `Left X+` |

### Motion (*Motion Input* tab)

Requires a remote with MotionPlus (built-in or attached) for the gyroscope. The
accelerometer works on every remote.

| Group | Input | DSU input |
|---|---|---|
| Accelerometer | Up / Down | `Accel Up` / `Accel Down` |
| | Left / Right | `Accel Left` / `Accel Right` |
| | Forward / Backward | `Accel Forward` / `Accel Backward` |
| Gyroscope | Pitch Up / Pitch Down | `Gyro Pitch Up` / `Gyro Pitch Down` |
| | Roll Left / Roll Right | `Gyro Roll Left` / `Gyro Roll Right` |
| | Yaw Left / Yaw Right | `Gyro Yaw Left` / `Gyro Yaw Right` |

**Check:** with the remote resting face up, Dolphin's accelerometer indicator shows
gravity pointing down. Tilting or turning the remote moves the indicators the same way.

**Pointer:** DSU carries no IR camera data, so the cursor comes from the gyroscope.
In the *Point* group of *Motion Input*, keep it enabled and bind **Recenter** to an
input you don't use in the game. A good choice is − and + together: in the advanced
editor, type `` `Share` & `Options` ``. Point at the centre of the screen and press it
whenever the cursor drifts. Adjust *Total Yaw* / *Total Pitch* (how far you turn to
cover the screen) to taste.

If the mouse also moves the cursor, clear the *Point* bindings of the
**Motion Simulation** tab.

**Shake:** with the real accelerometer bound, shaking the remote works as on a Wii.
Leave the *Shake* group of *Motion Simulation* empty, or bind it to a button for games
that need very hard shakes.

### Nunchuk motion

DSU has a single motion sensor per slot, and it carries the remote's. The Nunchuk's
accelerometer does not reach Dolphin through DSU. For games that use Nunchuk shakes
(e.g. spin attacks), bind the extension's **Shake** in **Extension Motion Simulation**
to a button such as `` `Pad S` `` or `` `L1` & `L2` `` (C + Z).

Save the profile (*Profile* → name → *Save*) so you can load it for other games and
remotes.

## 4. More remotes

Repeat step 3 for *Wii Remote 2* with `DSUClient/1/<description>`, and so on. The
index follows WiiChinaHook's slot (the LED the remote shows), not the order in which
you turn the remotes on.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No `DSUClient` devices | WiiChinaHook running? DSU client enabled with the right port? Only one program can use port 26760 (close DS4Windows/BetterJoy or change the port). |
| Device appears but nothing moves | WiiChinaHook is not in the DSU mode: switch with B + → (or the GUI). |
| Device keeps disconnecting | Update WiiChinaHook (fixed in this version), then remove and re-add the server. |
| Motion is upside down or mirrored | Bindings swapped. Check the table above, then rest the remote face up. |
| Cursor drifts | Bind **Recenter** (above). WiiChinaHook's quick calibration (*Controllers* tab) also renews the gyro bias. |
| Gyro does nothing | Remote without MotionPlus, or MotionPlus not active (*Controllers* tab shows "MotionPlus"). |

See also: [Cemu guide](cemu.md) · [README](../../README.md)
