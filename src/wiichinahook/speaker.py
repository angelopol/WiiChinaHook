"""Wii Remote speaker: optional custom sounds (remote connected, mode switch, low
battery, or on demand through the API/CLI/GUI).

Protocol (wiibrew, "Wiimote#Speaker"): enable (report 0x14), mute (0x19), write
0xA20009 = 01, 0xA20001 = 08, the 7-byte configuration at 0xA20001, 0xA20008 = 01,
unmute; then 0x18 reports carrying up to 20 bytes of audio each. To start sounds
without delay, the speaker stays configured (just muted) between sounds and the
register writes are not acknowledged (like Wii games do: the channel keeps their
order); it is switched off after IDLE_OFF seconds of silence. Audio here is 4-bit
Yamaha ADPCM at 3 kHz: 40 samples per report, one report every 13.3 ms. The rate must
be steady, so a thread paces the reports (time.sleep is a high-resolution waitable
timer on Windows since Python 3.11; the asyncio loop only has ~15 ms granularity) and
hands each one to the loop, which owns the transport.

The sound quality is the original remote's: telephone-like, for short effects.
"""
from __future__ import annotations

import array
import asyncio
import copy
import logging
import math
import sys
import threading
import time
import wave
from pathlib import Path

log = logging.getLogger(__name__)

SAMPLE_RATE = 3000
RATE_REGISTER = 6_000_000 // SAMPLE_RATE   # 4-bit ADPCM: rate = 6 MHz / register (0x07D0)
BYTES_PER_REPORT = 20
REPORT_PERIOD = BYTES_PER_REPORT * 2 / SAMPLE_RATE
MAX_SECONDS = 10.0
VOLUME_MAX = 0x7F                          # 0.5 -> 0x40, the usual ADPCM volume
IDLE_OFF = 15.0                            # seconds of silence before switching the speaker off

# Yamaha ADPCM tables, as in Dolphin's speaker decoder (WiimoteEmu/Speaker.cpp).
INDEX_SCALE = (230, 230, 230, 230, 307, 409, 512, 614) * 2
DIFF_LOOKUP = (1, 3, 5, 7, 9, 11, 13, 15, -1, -3, -5, -7, -9, -11, -13, -15)


def _clamp(value, low, high):
    return low if value < low else high if value > high else value


def _div8(value):
    return int(value / 8)  # C integer division truncates toward zero


def encode_adpcm(samples) -> bytes:
    """16-bit samples -> 4-bit Yamaha ADPCM, high nibble first (the order Dolphin's
    decoder reads, i.e. what the remote expects)."""
    predictor, step, nibbles = 0, 127, []
    for sample in samples:
        delta = sample - predictor
        nibble = min(7, abs(delta) * 4 // step) + (8 if delta < 0 else 0)
        predictor = _clamp(predictor + _div8(step * DIFF_LOOKUP[nibble]), -32768, 32767)
        step = _clamp((step * INDEX_SCALE[nibble]) >> 8, 127, 24576)
        nibbles.append(nibble)
    if len(nibbles) % 2:
        nibbles.append(0)
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def decode_adpcm(data: bytes) -> list[int]:
    """Inverse of encode_adpcm (what the remote plays); used by the tests."""
    predictor, step, out = 0, 127, []
    for byte in data:
        for nibble in (byte >> 4, byte & 15):
            predictor = _clamp(predictor + _div8(step * DIFF_LOOKUP[nibble]), -32768, 32767)
            step = _clamp((step * INDEX_SCALE[nibble]) >> 8, 127, 24576)
            out.append(predictor)
    return out


# -- sounds ---------------------------------------------------------------------
def tone(frequency, seconds, amplitude=0.7, fade=0.01):
    """Sine tone with short fades (no clicks). Keep it below ~1.4 kHz (3 kHz rate)."""
    count = int(seconds * SAMPLE_RATE)
    edge = max(1, int(fade * SAMPLE_RATE))
    return [int(32767 * amplitude * min(1.0, i / edge, (count - i) / edge)
                * math.sin(2 * math.pi * frequency * i / SAMPLE_RATE)) for i in range(count)]


def silence(seconds):
    return [0] * int(seconds * SAMPLE_RATE)


def _count(n):
    out = []
    for _ in range(max(1, n)):
        out += tone(1047, 0.07) + silence(0.1)
    return out


# `count` repeats a blip n times (n = the mode number for the "mode" event).
BUILTIN = {
    "beep": lambda n: tone(880, 0.15),
    "blip": lambda n: tone(1320, 0.06),
    "chime": lambda n: tone(659, 0.12) + tone(988, 0.2),
    "alert": lambda n: (tone(440, 0.15) + silence(0.08)) * 3,
    "count": _count,
}
EVENTS = ("connect", "mode", "low_battery")
DEFAULT_SPEAKER = {"enabled": False, "volume": 0.5,
                   "events": {"connect": "chime", "mode": "count", "low_battery": "alert"}}


def resample(samples, source_rate, target_rate=SAMPLE_RATE):
    """Downsampling averages each output interval (a box low-pass against aliasing);
    upsampling interpolates linearly."""
    if source_rate == target_rate or not samples:
        return list(samples)
    ratio = source_rate / target_rate
    count = int(len(samples) / ratio)
    if ratio > 1:
        out = []
        for i in range(count):
            start, end = int(i * ratio), max(int(i * ratio) + 1, int((i + 1) * ratio))
            chunk = samples[start:end]
            out.append(int(sum(chunk) / len(chunk)))
        return out
    last = len(samples) - 1
    out = []
    for i in range(count):
        position = i * ratio
        j = int(position)
        frac = position - j
        out.append(int(samples[j] * (1 - frac) + samples[min(j + 1, last)] * frac))
    return out


def load_wav(path) -> list[int]:
    """8/16-bit PCM WAV, any rate and channel count -> mono 3 kHz, peak-normalized
    (the speaker is quiet), at most MAX_SECONDS."""
    path = Path(path)
    if path.suffix.lower() != ".wav":
        raise ValueError("Custom sounds must be .wav files")
    with wave.open(str(path), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        if width not in (1, 2):
            raise ValueError("WAV must be 8- or 16-bit PCM")
        raw = wav.readframes(min(wav.getnframes(), int(rate * MAX_SECONDS)))
    if width == 2:
        data = array.array("h")
        data.frombytes(raw[:len(raw) // 2 * 2])
        if sys.byteorder == "big":
            data.byteswap()
    else:
        data = [(b - 128) << 8 for b in raw]
    if channels > 1:
        data = [sum(data[i:i + channels]) // channels for i in range(0, len(data) - channels + 1, channels)]
    samples = resample(list(data), rate)
    peak = max((abs(s) for s in samples), default=0)
    if peak:
        gain = min(8.0, 29000 / peak)
        samples = [int(s * gain) for s in samples]
    return samples


def validate_speaker(data) -> dict:
    """Speaker config: {"enabled", "volume" 0..1, "events": {event: built-in name,
    path to a .wav (relative to the config file) or null}}."""
    result = copy.deepcopy(DEFAULT_SPEAKER)
    if data is None:
        return result
    if not isinstance(data, dict):
        raise ValueError("speaker must be an object")
    result["enabled"] = bool(data.get("enabled", False))
    volume = data.get("volume", 0.5)
    if not isinstance(volume, (int, float)) or isinstance(volume, bool) or not 0 <= volume <= 1:
        raise ValueError("speaker volume must be 0..1")
    result["volume"] = float(volume)
    events = data.get("events", {})
    if not isinstance(events, dict) or set(events) - set(EVENTS):
        raise ValueError(f"speaker events must be among {', '.join(EVENTS)}")
    for name, sound in events.items():
        if sound is not None and (not isinstance(sound, str) or not sound
                                  or (sound not in BUILTIN and not sound.lower().endswith(".wav"))):
            raise ValueError(f"speaker sound for {name}: a built-in ({', '.join(BUILTIN)}), a .wav path or null")
        result["events"][name] = sound
    return result


# -- playback --------------------------------------------------------------------
def _write(session, address, data):
    """Register write without waiting for its 0x22 acknowledgement (no round trip)."""
    session.send(0x16, address.to_bytes(4, "big") + bytes([len(data)]) + data.ljust(16, b"\0"))


def setup(session, volume):
    """Initialization sequence, sent back to back."""
    session.send(0x14, b"\x04")               # speaker on
    session.send(0x19, b"\x04")               # muted while configuring
    _write(session, 0x04A20009, b"\x01")
    _write(session, 0x04A20001, b"\x08")
    level = round(_clamp(volume, 0.0, 1.0) * VOLUME_MAX)
    _write(session, 0x04A20001, bytes([0x00, 0x00, RATE_REGISTER & 0xFF, RATE_REGISTER >> 8, level, 0, 0]))
    _write(session, 0x04A20008, b"\x01")


def shutdown(session):
    session.send(0x19, b"\x04")
    session.send(0x14, b"\x00")               # off: no idle hiss, saves battery
    session.speaker_volume = None


def _schedule_off(session):
    def off():
        session.speaker_off = None
        if not session.closed and session.speaker_volume is not None:
            shutdown(session)
    session.speaker_off = asyncio.get_running_loop().call_later(IDLE_OFF, off)


async def stream(session, adpcm: bytes, period=REPORT_PERIOD):
    """Send `adpcm` in 0x18 reports at a steady pace (see the module docstring)."""
    loop = asyncio.get_running_loop()
    done = loop.create_future()
    stop = threading.Event()

    def deliver(chunk):
        if stop.is_set() or session.closed:
            stop.set()
            return
        try:
            session.send(0x18, bytes([len(chunk) << 3]) + chunk.ljust(BYTES_PER_REPORT, b"\0"))
        except Exception as exc:  # channel closed mid-sound
            log.debug("Speaker report: %s", exc)
            stop.set()

    def finish():
        if not done.done():
            done.set_result(None)

    def pace():
        try:
            start = time.perf_counter()
            for index, offset in enumerate(range(0, len(adpcm), BYTES_PER_REPORT)):
                if stop.is_set():
                    break
                delay = start + index * period - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                loop.call_soon_threadsafe(deliver, adpcm[offset:offset + BYTES_PER_REPORT])
            if not stop.is_set():
                time.sleep(2 * period)        # let the remote play its last buffered report
            loop.call_soon_threadsafe(finish)
        except RuntimeError:                  # event loop closed during shutdown
            pass

    threading.Thread(target=pace, name="speaker", daemon=True).start()
    try:
        await done
    finally:
        stop.set()


async def play(session, adpcm: bytes, volume=DEFAULT_SPEAKER["volume"]):
    """Play on a configured speaker: only an unmute when it is still set up from the
    previous sound with the same volume, the full setup otherwise."""
    if getattr(session, "speaker_off", None):
        session.speaker_off.cancel()
        session.speaker_off = None
    if getattr(session, "speaker_volume", None) != volume:
        setup(session, volume)
        session.speaker_volume = volume
    session.send(0x19, b"\x00")               # unmute
    try:
        await stream(session, adpcm)
    finally:
        if not session.closed:
            session.send(0x19, b"\x04")       # muted, still configured for the next sound
            _schedule_off(session)


class SpeakerService:
    """Encodes and caches sounds and plays them on a slot; also the event sounds."""

    def __init__(self, config=None, base_dir=Path("."), session_for=None):
        self.config = validate_speaker(config)
        self.base_dir = Path(base_dir)
        self.session_for = session_for
        self.cache = {}
        self.tasks = set()
        for name in BUILTIN:                     # tiny; ready before the first event
            self.encode(name)

    def set_config(self, config):
        self.config = validate_speaker(config)
        return self.config

    def resolve(self, sound):
        path = Path(sound)
        return path if path.is_absolute() else self.base_dir / path

    def encode(self, sound, count=1):
        if sound in BUILTIN:
            key = (sound, count)
        else:
            path = self.resolve(sound)
            key = (str(path), path.stat().st_mtime_ns)  # re-encode when the file changes
        if key not in self.cache:
            samples = BUILTIN[sound](count) if sound in BUILTIN else load_wav(self.resolve(sound))
            if len(self.cache) > 32:
                self.cache.clear()
            self.cache[key] = encode_adpcm(samples)
        return self.cache[key]

    async def play(self, slot, sound="chime", volume=None, count=1):
        if not isinstance(sound, str) or not sound:
            raise ValueError("sound must be a built-in name or a .wav path")
        if volume is None:
            volume = self.config["volume"]
        if not isinstance(volume, (int, float)) or isinstance(volume, bool) or not 0 <= volume <= 1:
            raise ValueError("volume must be 0..1")
        session = self.session_for(slot)
        try:
            key = (sound, count) if sound in BUILTIN else None
            if key in self.cache:
                adpcm = self.cache[key]          # no thread hop for a cached built-in
            else:
                adpcm = await asyncio.to_thread(self.encode, sound, count)  # WAV decoding is CPU work
        except (OSError, wave.Error, EOFError) as exc:
            raise ValueError(f"Cannot read {sound}: {exc}") from exc
        await session.play_sound(adpcm, volume)
        return {"slot": slot, "sound": sound, "seconds": round(len(adpcm) * 2 / SAMPLE_RATE, 2)}

    def event(self, slot, name, count=1):
        """Fire-and-forget event sound, if enabled and assigned."""
        sound = self.config["events"].get(name)
        if not self.config["enabled"] or not sound:
            return
        task = asyncio.get_running_loop().create_task(self._event(slot, name, sound, count))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _event(self, slot, name, sound, count):
        try:
            await self.play(slot, sound, count=count)
        except Exception as exc:  # a missing file or a busy remote must not break anything
            log.info("Speaker %s sound on slot %d: %s", name, slot, exc)
