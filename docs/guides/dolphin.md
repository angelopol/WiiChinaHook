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
3. Add WiiChinaHook's servers with **Add…**. Use the descriptions below: Dolphin names
   the devices after them.

   | Description | Address | Port | Carries |
   |---|---|---|---|
   | `WiiChinaHook` | `127.0.0.1` | `26760` | Buttons, Nunchuk stick/C/Z, remote accelerometer and gyroscope |
   | `WiiChinaHook Nunchuk` | `127.0.0.1` | `26762` | The Nunchuk's accelerometer (optional) |
   | `WiiChinaHook IR` | `127.0.0.1` | `26763` | The IR camera pointer (optional) |

   The list may already contain `DS4Windows` at `127.0.0.1:26760`. That is the same
   address as the first server, so either keep it or replace it with `WiiChinaHook`.
4. Close the window.

A single DSU slot carries one motion sensor and no IR data, which is why the Nunchuk
and the IR pointer have servers of their own. Switch them on or off in WiiChinaHook:
*Xbox controller* tab → edit the DSU mode → *Extra DSU servers* (both on by default).
The ports are under *Settings → Network*.

Dolphin asks every server for its slots each second. With WiiChinaHook running, the
devices appear as `DSUClient/<slot>/<description>`. For example, the first remote
(slot 0, LED 1) gives `DSUClient/0/WiiChinaHook`, `DSUClient/0/WiiChinaHook Nunchuk` and
`DSUClient/0/WiiChinaHook IR`.

**Several devices in one controller.** Each binding can use a different device. Right-click
a field to open the advanced editor, pick the device in its list, then the input. Or type
the full name, e.g. `` `DSUClient/0/WiiChinaHook IR:Right X+` ``.

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

**Pointer.** There are two ways:

- **With the sensor bar: IR server (recommended).** The real camera aims, as on a Wii,
  with no drift.
  1. In **Motion Simulation**, bind the **Point** group to the IR device:

     | Point | Input of `DSUClient/0/WiiChinaHook IR` |
     |---|---|
     | Up / Down | `Right Y+` / `Right Y-` |
     | Left / Right | `Right X-` / `Right X+` |
     | Hide | `Cross` (pressed while the camera does not see the bar) |

  2. In **Motion Input**, untick or clear the **Point** group. Otherwise the gyroscope
     cursor overrides the IR one.
  3. If the cursor reaches the screen edges too soon or too late, change *IR range* in
     WiiChinaHook's DSU mode settings (smaller = less movement for the whole screen).

  The stick holds the last position when the bar leaves the camera's view, and
  `Cross` tells Dolphin to hide the cursor, like a real Wii. *Hide* is in recent
  Dolphin versions. Without it, the cursor stays at the last point.
- **Without a sensor bar: gyroscope.**
  1. Keep the **Point** group of **Motion Input** enabled, and leave the Motion
     Simulation *Point* unbound.
  2. Bind **Recenter** to an input the game doesn't use. A good choice is − and +
     together: in the advanced editor, type `` `Share` & `Options` ``.
  3. Point at the centre of the screen and press it whenever the cursor drifts.
  4. Adjust *Total Yaw* / *Total Pitch* (how far you turn to cover the screen) to taste.

If the mouse also moves the cursor, remove its bindings from the Motion Simulation
*Point* group.

**Shake:** with the real accelerometer bound, shaking the remote works as on a Wii.
Leave the *Shake* group of *Motion Simulation* empty, or bind it to a button for games
that need very hard shakes.

### Nunchuk motion (Nunchuk server)

The Nunchuk's accelerometer arrives through the `WiiChinaHook Nunchuk` server, as that
device's accelerometer. In the Nunchuk's **Extension Motion Input** tab, bind its
**Accelerometer** to `DSUClient/0/WiiChinaHook Nunchuk`:

| Accelerometer | Input |
|---|---|
| Up / Down | `Accel Up` / `Accel Down` |
| Left / Right | `Accel Left` / `Accel Right` |
| Forward / Backward | `Accel Forward` / `Accel Backward` |

Leave **Extension Motion Simulation → Shake** empty, so the real shakes are used (spin
attacks, etc.).

**Checks:**

- Resting flat, the indicator shows gravity pointing down.
- The Nunchuk is read uncalibrated, so very gentle movements may differ slightly from
  a real Wii's. Shakes and tilts work.
- The axes are the same as the remote's, but haven't been verified on this Nunchuk. If
  a direction is inverted, swap that pair of bindings.

If you switch the Nunchuk server off, bind the Nunchuk's **Shake** in **Extension Motion
Simulation** to a button instead, e.g. `` `Pad S` `` or `` `L1` & `L2` `` (C + Z).

Save the profile (*Profile* → name → *Save*) so you can load it for other games and
remotes.

## 4. More remotes

Up to four remotes work at once. Each one has the same three devices with its own
index, in all three servers:

| Dolphin | Remote (LED) | Devices |
|---|---|---|
| Wii Remote 1 | slot 0 (LED 1) | `DSUClient/0/WiiChinaHook`, `DSUClient/0/WiiChinaHook Nunchuk`, `DSUClient/0/WiiChinaHook IR` |
| Wii Remote 2 | slot 1 (LED 2) | `DSUClient/1/…` (the same three) |
| Wii Remote 3 | slot 2 (LED 3) | `DSUClient/2/…` |
| Wii Remote 4 | slot 3 (LED 4) | `DSUClient/3/…` |

The index follows WiiChinaHook's slot (the LED the remote shows), not the order in which
you turn the remotes on.

Dolphin profiles store the device names. The quickest way:

1. Set up *Wii Remote 1* and save it as a profile (e.g. `WiiChinaHook 1`).
2. Load it on *Wii Remote 2*.
3. Change the index from `0` to `1` in the **Device** list and in every binding that names
   a device (the Nunchuk motion and the IR Point). Save it as `WiiChinaHook 2`.
4. Do the same for remotes 3 and 4.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No `DSUClient` devices | WiiChinaHook running? DSU client enabled with the right port? Only one program can use port 26760 (close DS4Windows/BetterJoy or change the port). |
| Device appears but nothing moves | WiiChinaHook is not in the DSU mode: switch with B + → (or the GUI). |
| Device keeps disconnecting | Update WiiChinaHook (fixed in this version), then remove and re-add the server. |
| Motion is upside down or mirrored | Bindings swapped. Check the table above, then rest the remote face up. |
| Cursor drifts | With the sensor bar, use the IR server (above). With the gyroscope cursor, bind **Recenter**; WiiChinaHook's quick calibration (*Controllers* tab) also renews the gyro bias. |
| No `WiiChinaHook Nunchuk` / `IR` devices | Server switched off in the DSU mode settings, its port set to 0 or busy (*Settings → Network*, and the log says so), or not added in Dolphin. |
| IR cursor stuck or jumping to the centre | Unbind the **Motion Input → Point** group (it overrides the IR server). Check that the IR camera sees two dots in WiiChinaHook's *Controllers* tab. |
| IR cursor moves the wrong way vertically | Swap `Right Y+` / `Right Y-` in Point (the vertical IR direction is not verified on hardware yet). |
| Gyro does nothing | Remote without MotionPlus, or MotionPlus not active (*Controllers* tab shows "MotionPlus"). |

See also: [Cemu guide](cemu.md) · [README](../../README.md)
