# Wiimote speaker

*English · [Español](SPEAKER.es.md)*

WiiChinaHook can play short sounds on the remote's speaker: when a remote connects,
when the mode changes, when the battery is low, or on demand. It is **optional and off
by default**, and it is not yet verified on hardware (see [Limits](#limits)).

## Using it

**GUI.** *Settings → Speaker (optional)*:

1. Turn on *Play event sounds* and set the volume.
2. For each event, choose a built-in sound, *Off* or *Custom .wav…* (then type the
   file's path). ▶ plays it on the first connected remote.
3. *Save*. It applies at once if the service is running.

Each controller card also has a **Sound** button that plays a chime on that remote.

**CLI** (with the hook running):

```powershell
wiichinahook sound --slot 0                         # chime
wiichinahook sound --slot 1 --sound alert --volume 0.8
wiichinahook sound --slot 0 --sound C:\Sounds\coin.wav
```

**API:** `play_sound` `{"slot": 0, "sound": "chime" | "<path>.wav", "volume": 0..1}`
replies after the sound ends, with `seconds`. `speaker_config` replaces the settings
below. See [API.md](API.md).

**Configuration** (`config.local.json`):

```json
"speaker": {
  "enabled": true,
  "volume": 0.5,
  "events": {"connect": "chime", "mode": "count", "low_battery": "sounds/battery.wav"}
}
```

| Event | When |
|---|---|
| `connect` | A remote becomes ready |
| `mode` | The mode switches (B + arrow, the GUI or the tray). `count` plays N blips for mode N |
| `low_battery` | The battery drops below 15% (once, until it rises above 25%) |

- **Built-in sounds:** `beep`, `blip`, `chime`, `alert`, `count`. `null` turns an event
  off.
- **Custom sounds:** `.wav` files, 8- or 16-bit PCM, any rate and channel count, at most
  10 s. They are converted to 3 kHz mono and normalized, since the speaker is quiet.
  Relative paths start at the folder of the config file.
- **Playback:** a new sound cuts the one playing on that remote.

## How it works

The speaker is set up as described on [wiibrew](https://wiibrew.org/wiki/Wiimote#Speaker):

1. Enable it (report `0x14`) and mute it (`0x19`).
2. Write `0xA20009 = 01` and `0xA20001 = 08`.
3. Write the configuration at `0xA20001`: format 4-bit Yamaha ADPCM, rate register
   `0x07D0` (6 MHz / 2000 = 3 kHz), volume.
4. Write `0xA20008 = 01`, then unmute.

Audio goes out in `0x18` reports: 20 bytes, that is 40 samples, every 13.3 ms. To start
each sound without delay:

- The setup writes are sent back to back, without waiting for acknowledgements, as Wii
  games do. The channel keeps them in order.
- After a sound, the speaker is only muted. It stays configured, so the next sound with
  the same volume needs just an unmute. The first audio report goes out within a few
  milliseconds.
- After 15 s of silence it is switched off, which avoids hiss and saves battery.

The encoder uses the same tables as Dolphin's speaker decoder, and the nibble order
(high first) is the one that decoder reads.

Timing is the delicate part. If reports arrive late, the remote's buffer empties and
the sound stutters. If they arrive early, it overflows. The asyncio loop on Windows has
about 15 ms granularity, so a dedicated thread paces the reports with absolute
deadlines. Since Python 3.11, `time.sleep` uses a high-resolution timer on Windows.
With the DolphinBar, that thread writes each report straight to the slot's writer queue.
Over Bluetooth it hands each report to the event loop that owns the transport. If the OS
stalls the thread, it carries on one period after the last report instead of sending the
overdue ones in a burst, which would overflow the remote's buffer.

## Limits

- **Untested on this clone:** many clones have a weak speaker, decode ADPCM
  differently, or have no working speaker at all.
- **DolphinBar:** we know it forwards register writes (`0x16`), but not whether it
  forwards `0x18` audio reports or with what latency. Bluetooth passthrough (Bumble)
  controls L2CAP directly and should be fine.
- **Quality:** like the original remote, telephone-like. Good for effects, not music.
- **Real-time audio:** streaming the PC's audio to the remote is not implemented. It
  would add noticeable latency.

To try it: connect the remote, then click **Sound** on its card or run
`wiichinahook sound --slot 0`. Do it first over Bluetooth passthrough, then over the
DolphinBar. If the clone sounds wrong or doesn't sound, the rest is not worth it.

## Integration with Dolphin (not implemented)

Today the speaker works only with WiiChinaHook's own sounds. In a game emulated by
Dolphin, the remote's speaker audio does **not** reach the remote:

- DSU (cemuhook) carries input only. It has no message for audio.
- With an emulated Wii Remote, Dolphin receives the game's speaker data (`0x18`
  reports and the speaker registers) in its emulated speaker
  (`Source/Core/Core/HW/WiimoteEmu/Speaker.cpp`). It decodes that data and mixes it
  into the PC's normal audio output. It never sends it to anyone else.

The possible routes, from best to worst:

### 1. Dolphin forwards the raw speaker data to WiiChinaHook (recommended)

A small Dolphin patch (a fork, or an upstream PR proposing an "external speaker" option
for emulated remotes) would send, per emulated remote, what the game writes:

- the speaker configuration (format, rate, volume, mute/enable);
- each `0x18` payload, as is.

The target would be a local UDP port (e.g. 26764; 26760–26763 are taken by DSU and the API). WiiChinaHook would apply the same configuration
on the real remote and relay the payloads with its pacing thread. The game's audio is
already in the remote's own format, so there is nothing to re-encode, and latency is a
single local hop. Most of the work on WiiChinaHook's side already exists: setup,
pacing and the `0x18` reports. What's missing is the listener.

A possible packet format (a proposal, not implemented):

| Field | Size | Value |
|---|---|---|
| magic | 4 | `WCHS` |
| version | 1 | `1` |
| slot | 1 | 0–3 (the DSU slot of that remote) |
| type | 1 | `0` = config, `1` = audio, `2` = off |
| payload | ≤ 21 | config: format, rate register (2 bytes LE), volume · audio: length + up to 20 bytes |

Pros: exact game audio, low latency, no audio hacks. Cons: it needs that Dolphin
change, built and maintained, or accepted upstream.

### 2. Capture the PC's audio (not viable)

Dolphin mixes the speaker audio with the game audio into one stream. Routing Dolphin
through a virtual audio cable would send *all* the game's audio to the remote. It would
also add latency and need re-encoding to 3 kHz. Not worth it.

### 3. Let Dolphin own the remote ("Real Wii Remote")

In that mode Dolphin itself sends the speaker data to the remote (*Enable Speaker
Data* in Dolphin's Wii Remote settings). It is the official route, and it works with
original remotes. But WiiChinaHook must then be closed, since only one program can
own the remote, so its features (DSU, Xbox modes) are lost. Also, with this clone it
failed for the reasons in [VALIDATION.md](VALIDATION.md): the DolphinBar drops the
clone's memory-read replies, and the Windows Bluetooth stack did not pair it.

### Cemu

Cemu emulates the Wii U. As far as we know, it does not output Wii Remote speaker
audio through any external interface. Not viable.
