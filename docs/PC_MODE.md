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

With the gyroscope, the quick calibration (*Controllers* tab) removes the drift. If the
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
  right-clicks.
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
