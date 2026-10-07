# PC mode (mouse and keyboard)

*English · [Español](PC_MODE.es.md)*

In PC mode the remotes control Windows itself: a mouse, keyboard shortcuts, media
keys and launchers. No virtual Xbox controller is created, so it works in any
program or game that uses a mouse and keyboard.

Mode 3 is the PC mode by default (hold **B** and press **↓** on the remote). Any mode
can be turned into a PC mode in the *Xbox controller* tab → *Edit mode* → *Mode type*.

## Mouse

Pick what moves the pointer:

| Source | How it moves | Settings |
|---|---|---|
| Gyroscope (default) | Turn the remote. Like an air mouse: the pointer moves while you turn | Pixels per degree; dead zone in °/s (hides residual drift and tremor) |
| IR pointer | Point at the sensor bar: the pointer goes where you point | IR range (how much of the camera's view spans the screen); smoothing |
| Nunchuk stick | Push the stick. A curve gives precision near the centre | Pixels per second at full tilt; dead zone |
| Wiimote D-pad | Hold an arrow. Starts slow, then speeds up | Pixels per second |
| Nothing | — | — |

Whatever moves the mouse **cannot also be mapped**. With the D-pad or the Nunchuk stick
as the mouse, their rows are disabled in the editor and the configuration refuses
them.

**A + B together** (both PC modes, *Mouse* card):

- **Recenter the pointer** (default in PC) puts the pointer in the centre of the monitor it is on (with several monitors it stays on that one).
- **Pause the gyro while held** (default in PC Game) means the gyroscope doesn't move the
  mouse while you hold A + B. Re-point the remote comfortably, release, and the aim carries
  on from where it was. In games this is the way to recenter: moving the pointer would jerk
  the camera.
- **Nothing** turns it off.

Pressed together (within 60 ms), A and B don't click. Alone they act as mapped. In PC Game
B (the trigger) never waits; if A follows within 60 ms, the shot stops.

**Freeze the gyro mouse when shaking** (on by default, PC and PC Game): shaking the
Wiimote (e.g. a melee hit) would spin the aim. The gyro is ignored while it shakes, for
0.3 s after, and for any turn faster than the limit (300 °/s by default; aiming never gets
there). The aim stays where it was before the hit.

With the gyroscope, the quick calibration (*Controllers* tab) removes the drift and, with
**Recenter the mouse when recalibrating** (on by default), also puts the pointer in the
centre of the monitor it is on. Point the remote at the centre while you recalibrate, and remote and
pointer line up again. If the
pointer still creeps, raise the dead zone a little.

## Actions

Each input can do one thing:

| Type | Example | Behaviour |
|---|---|---|
| **Keys** | `ctrl+9`, `ctrl+shift+esc`, `win+d`, `alt+f4` | Any number of keys. They are held while you hold the button and released in reverse order |
| **Mouse** | left, right or middle click; scroll up or down | Clicks are held (drag works); scroll repeats while held |
| **System** | mute, volume up/down, next/previous track, play/pause, stop, Start menu | Fires once per press |
| **Open** | `notepad`, `C:\Games\game.exe`, `https://example.com` | Opens a program, file or web page once per press |
| **Toggle** | `ctrl+c \| ctrl+v`, `system:mute \| system:mute` | Each press runs the next step; after the last it starts again |

The inputs you can map:

- **Wiimote:** A, B, 1, 2, −, +, Home and the D-pad.
- **Nunchuk:** C, Z, and **the stick as four buttons** (↑ ↓ ← →; pushed past half way).
- **Shakes:** of the remote or the Nunchuk along an axis.

**Key names:** `a`–`z`, `0`–`9`, `f1`–`f24`, `ctrl`, `shift`, `alt`, `win`, `enter`, `esc`,
`tab`, `space`, `backspace`, `delete`, `insert`, `home`, `end`, `pageup`, `pagedown`, `up`,
`down`, `left`, `right`, `capslock`, `printscreen`, `menu`, `num0`–`num9`, `num_add`,
`num_subtract`, `num_multiply`, `num_divide`, `num_decimal`, `num_enter`, `;` `=` `,` `-` `.`
`/` `` ` `` `[` `\` `]` `'`, and the right-hand `rctrl`, `rshift`, `ralt`, `rwin`. Common
aliases also work (`control`, `escape`, `del`, `pgup`…), in any case.

**Toggle steps** are separated by `|`. A step is keys (no prefix needed), `mouse:…`,
`system:…` or `open:…`, e.g. `toggle:ctrl+c | ctrl+v` or
`toggle:open:notepad | keys:alt+f4`.

## Super shortcuts

Two or three inputs held together can run an action of their own, for example **1 + −**
→ `ctrl+add+oemcomma`. They are off by default: turn them on in the editor's *Super
shortcuts* card (both PC modes), which has up to 8 rows.

- Each shortcut's buttons wait the **shortcut window** (50 ms by default, 0–300) for the
  rest.
- If the shortcut completes, only its action runs. It is held while you hold the shortcut,
  and its buttons do nothing else until released, even if you let go of one first.
- If it does not complete, each button acts on its own after the window.
- Buttons that are in no shortcut never wait.
- Inputs: any button, the Nunchuk stick directions or shakes, but not what moves the
  mouse. Actions: the same as for buttons (only game actions in PC Game).

Windows key names work too: `add`, `subtract`, `multiply`, `divide`, `decimal` (numpad),
`oemcomma`, `oemperiod`, `oemplus`, `oemminus`, `oem1`–`oem7`, with or without `_`.

## PC Game mode

Mode 4 by default (hold **B** and press **←**). It works like PC mode but is meant for
games:

- **Actions:** only **keys, mouse buttons and toggles**. System keys (volume, media, Start
  menu) and **open** are not available, so a misplaced button can't pull you out of a game.
- **Mouse:** always relative (gyroscope, Nunchuk stick or D-pad), which is what games read
  for camera and aim. The IR pointer (absolute) and *Recenter the mouse when recalibrating*
  are not available: moving the pointer jerks the camera.
- **Modifier (B):** acts at once and stays held, so B can be the trigger and hold
  automatic fire. Modifier + arrow still switches mode. B is held for that moment, so in a
  game it fires briefly.

Default layout (shooter-style):

| Input | Key |
|---|---|
| Nunchuk stick | W A S D |
| B (trigger) / Z | Left click (shoot) / right click (aim) |
| C / A | Space (jump) / E (use) |
| 1 / 2 | Ctrl (crouch) / Shift (run, held) |
| Shaking the Nunchuk | Shift (run: a short press, set sprint to *toggle* in the game) |
| D-pad ↑ ↓ ← → | R / Q / F / G |
| − / + / Home | Tab / M / Esc |
| Shaking the Wiimote | V (melee) |
| Gyroscope | Mouse (aim) |

## Defaults

| Input | Action |
|---|---|
| A / B | Left / right click |
| D-pad | Arrow keys |
| − / + | Volume down / up |
| Home | Start menu |
| 1 | `alt+tab` (hold to keep the switcher open) |
| 2 | Play / pause |
| C / Z | Middle click / Enter |
| Nunchuk stick ↑ / ↓ | Scroll up / down |
| Nunchuk stick ← / → | `alt+left` / `alt+right` (back / forward) |

## Details

- **Mode switching still works:** modifier (B) + arrow. In PC mode the modifier's action
  fires **when you release it**, and only if you didn't switch modes. B + arrow never
  right-clicks. With the **A + B** modifier, A and B wait 60 ms for each other: pressed
  together they are the modifier and click nothing; alone they click as usual.
- **Buttons held while the mode starts** (e.g. the B + ↓ that selected it) are ignored
  until you release them.
- **Nothing stays pressed:** switching modes, changing the configuration or a remote
  disconnecting releases every key and mouse button it held.
- **Several remotes** can be in PC mode at once. They all drive the same pointer and
  keyboard.
- **Keys reach games too:** they are sent as scan codes, which games that read raw input
  also see. Windows does not let a normal program send input to a program running as
  administrator. For those, run WiiChinaHook as administrator too.
- **`open:` uses the Windows shell**, like double-clicking. Only put trusted programs
  there. The configuration can be changed by the local API, which is reachable only
  from this PC.
