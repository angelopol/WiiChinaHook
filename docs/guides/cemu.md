# Cemu with the DSU mode

*English · [Español](cemu.es.md)*

Cemu reads controllers over DSU and uses the motion data for the **Wii U GamePad gyro**
(aiming in Splatoon, BotW shrines and the like) and for emulated Wii Remotes. This guide
uses the remote's buttons, Nunchuk, accelerometer and MotionPlus gyroscope.

## 1. Put WiiChinaHook in the DSU mode

1. Start WiiChinaHook and connect the remote.
2. Switch to **mode 2 (DSU)**: hold **B** and press **→** on the remote (two rumbles,
   LED 2 blinks), or click *Mode 2* in the *Xbox controller* tab.

In the other modes the remotes stay listed but send no input. The server listens on
`127.0.0.1:26760`.

## 2. Add the remote in Cemu

1. **Options** → **Input settings**.
2. Pick the **emulated controller** for *Controller 1*:
   - **Wii U GamePad** for most games. The gyro aims or steers.
   - **Wiimote** for games that support Wii Remotes (e.g. New Super Mario Bros. U,
     Mario Kart 8). Choose the *Nunchuk* extension if you use it.
3. Click **+** (add controller). In **API**, choose **DSUController**.
4. Click the **settings** button next to the API and check **IP** `127.0.0.1` and
   **Port** `26760`.
5. In **Controller**, choose **Controller 1** (= WiiChinaHook slot 0, LED 1) and click
   **Add**.
6. Open that controller's **Settings** and tick **Use motion**. Without it, Cemu ignores
   the accelerometer and gyroscope.

## 3. Bind the buttons

Click each field and press the remote button. Cemu stores what it receives, so the
table below is only a suggested layout. The names in brackets are the DSU inputs Cemu
records.

### As a Wii U GamePad

The remote alone has few buttons. With a Nunchuk it covers most of a GamePad:

| GamePad | Remote | DSU input |
|---|---|---|
| A / B | A / B | `Circle` / `Triangle` |
| X / Y | 1 / 2 | `Square` / `Cross` |
| L / ZL | C / Z | `L1` / `L2` |
| + / − | + / − | `Options` / `Share` |
| Home | HOME | `PS` |
| D-pad | D-pad | `Pad N/S/W/E` |
| Left stick | Nunchuk stick | `Left X` / `Left Y` |

R, ZR and the right stick have no free input. If a game needs them, map them to an
Xbox template instead (WiiChinaHook mode 1). There, combos and shakes can stand in for
the missing buttons.

### As a Wiimote

Bind each Wiimote button to the same name on the remote (A → `Circle`, B → `Triangle`,
1 → `Square`, 2 → `Cross`, − → `Share`, + → `Options`, Home → `PS`, D-pad →
`Pad N/S/W/E`). For the Nunchuk extension: C → `L1`, Z → `L2`, stick → `Left X/Y`.

## 4. Motion

- **Use motion** must be ticked in the controller settings (step 2.6).
- Cemu uses the DSU accelerometer and gyroscope directly. Put the remote down for a
  moment after connecting so the gyro bias settles. WiiChinaHook's quick calibration
  (*Controllers* tab) or `calibrate` removes the remaining drift.
- The GamePad's motion is meant for a tablet held in both hands. With a remote, hold it
  **flat, buttons up, tip away from you** like the GamePad's screen: tilting and turning
  it then match the GamePad's.
- Cemu cannot use the IR camera over DSU. Pointer games use the gyro, or the mouse
  pointer if you bind one.

## 5. More remotes

Add *Controller 2*, 3 or 4 with **Controller 2**, … (WiiChinaHook slots 1, 2, 3) for
local multiplayer. Each needs **Use motion** if the game reads its motion.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Controller 1" not listed / not connected | WiiChinaHook running and the port matches? Only one DSU server can own port 26760. |
| Buttons work in mode 2 only | Expected: the other modes keep DSU idle. |
| No gyro | **Use motion** off, or the remote has no active MotionPlus. |
| Drifting aim | Rest the remote and run the quick calibration, or `calibrate` in the CLI. |

See also: [Dolphin guide](dolphin.md) · [README](../../README.md)
