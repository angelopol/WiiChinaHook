import asyncio
import math
import time
import wave

import pytest

from wiichinahook import speaker
from wiichinahook.config import AppConfig, load_config, save_config
from wiichinahook.session import WiimoteSession
from wiichinahook.wiimote import WiimoteState


class AckChannel:
    """Interrupt channel that records output reports and acknowledges 0x16 writes."""
    psm = 0x13

    def __init__(self):
        self.sent = []
        self.session = None

    def write(self, data):
        self.sent.append((time.perf_counter(), bytes(data)))
        if data[1] == 0x16:
            asyncio.get_running_loop().call_soon(self.session.receive, bytes([0xA1, 0x22, 0, 0, 0x16, 0]))

    def on(self, *args):
        pass


def make_session():
    state = WiimoteState("02:00:44:42:00:01", 0, True)
    session = WiimoteSession(state, connection=None, publish=lambda s: None)
    channel = AckChannel()
    channel.session = session
    session.channels[0x13] = channel
    return session, channel


def test_adpcm_round_trip_follows_the_signal():
    samples = speaker.tone(660, 0.2)
    decoded = speaker.decode_adpcm(speaker.encode_adpcm(samples))[:len(samples)]
    error = math.sqrt(sum((a - b) ** 2 for a, b in zip(samples, decoded)) / len(samples))
    level = math.sqrt(sum(a * a for a in samples) / len(samples))
    assert len(speaker.encode_adpcm(samples)) == math.ceil(len(samples) / 2)
    assert error < 0.25 * level                       # ~12 dB SNR or better: recognisable tone


def test_builtin_sounds_are_short_and_count_repeats():
    for name, make in speaker.BUILTIN.items():
        assert 0 < len(make(1)) / speaker.SAMPLE_RATE < 1.5, name
    assert len(speaker.BUILTIN["count"](3)) == 3 * len(speaker.BUILTIN["count"](1))


@pytest.mark.parametrize("width,channels", [(2, 2), (1, 1)])
def test_load_wav_converts_to_mono_3khz(tmp_path, width, channels):
    path = tmp_path / "sound.wav"
    rate, seconds = 44100, 0.5
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            value = math.sin(2 * math.pi * 440 * i / rate) * 0.3
            sample = int(value * 32767).to_bytes(2, "little", signed=True) if width == 2 else bytes([int(128 + value * 127)])
            frames += sample * channels
        wav.writeframes(bytes(frames))
    samples = speaker.load_wav(path)
    assert abs(len(samples) - speaker.SAMPLE_RATE * seconds) <= 2
    assert 25000 < max(samples) <= 32767                 # peak-normalized
    with pytest.raises(ValueError):
        speaker.load_wav(tmp_path / "sound.mp3")


def test_speaker_config_validation_and_round_trip(tmp_path):
    assert speaker.validate_speaker(None)["enabled"] is False
    custom = speaker.validate_speaker({"enabled": True, "volume": 0.8, "events": {"mode": "sounds/mode.wav",
                                                                                  "low_battery": None}})
    assert custom["events"] == {"connect": "chime", "mode": "sounds/mode.wav", "low_battery": None}
    for bad in ({"volume": 2}, {"events": {"jump": "beep"}}, {"events": {"mode": "song.mp3"}}, "on"):
        with pytest.raises(ValueError):
            speaker.validate_speaker(bad)
    path = tmp_path / "config.json"
    save_config(AppConfig(speaker=custom), path)
    assert load_config(path).speaker == custom


async def test_play_sets_up_once_streams_paced_reports_and_stays_ready(monkeypatch):
    session, channel = make_session()
    channel.session = None                                 # never acknowledges: nothing may wait for it
    monkeypatch.setattr(channel, "write", lambda data: channel.sent.append((time.perf_counter(), bytes(data))))
    adpcm = bytes(range(50))                              # 3 reports: 20 + 20 + 10 bytes
    await asyncio.wait_for(speaker.play(session, adpcm, volume=0.5), 1)
    reports = [(t, data[1], data[2:]) for t, data in channel.sent]
    assert [r for _, r, _ in reports] == [0x14, 0x19, 0x16, 0x16, 0x16, 0x16, 0x19, 0x18, 0x18, 0x18, 0x19]
    writes = [(int.from_bytes(p[:4], "big"), p[5:5 + p[4]]) for _, r, p in reports if r == 0x16]
    assert writes == [(0x04A20009, b""), (0x04A20001, b""),
                      (0x04A20001, bytes([0, 0, 0xD0, 0x07, 0x40, 0, 0])), (0x04A20008, b"")]
    assert reports[6][2][0] & 0x04 == 0 and reports[-1][2][0] & 0x04     # unmuted, then muted again
    audio = [(t, p) for t, r, p in reports if r == 0x18]
    assert [p[0] for _, p in audio] == [20 << 3, 20 << 3, 10 << 3] and audio[2][1][1:11] == adpcm[40:]
    gaps = [b[0] - a[0] for a, b in zip(audio, audio[1:])]
    assert all(0.008 < gap < 0.03 for gap in gaps)         # ~13.3 ms apart
    # The setup goes out back to back: the first audio report follows at once.
    assert audio[0][0] - reports[0][0] < 0.01

    channel.sent.clear()                                   # next sound: still configured, only unmute
    await speaker.play(session, adpcm[:20], volume=0.5)
    assert [d[1] for _, d in channel.sent] == [0x19, 0x18, 0x19]
    channel.sent.clear()                                   # another volume: set up again
    await speaker.play(session, adpcm[:20], volume=0.8)
    assert [d[1] for _, d in channel.sent].count(0x16) == 4

    channel.sent.clear()
    monkeypatch.setattr(speaker, "IDLE_OFF", 0.05)
    await speaker.play(session, adpcm[:20], volume=0.8)
    await asyncio.sleep(0.1)                               # idle: switched off
    assert channel.sent[-1][1][1] == 0x14 and channel.sent[-1][1][2] & 0x04 == 0
    assert session.speaker_volume is None


async def test_a_new_sound_cuts_the_current_one():
    session, channel = make_session()
    long_sound = bytes(20 * 200)                            # ~2.7 s
    first = asyncio.create_task(session.play_sound(long_sound, 0.5))
    await asyncio.sleep(0.15)
    assert await session.play_sound(bytes(20), 0.5) is True
    assert await first is False
    assert sum(1 for _, d in channel.sent if d[1] == 0x18) < 60


async def test_event_sounds_only_when_enabled():
    played = []

    class Session:
        async def play_sound(self, adpcm, volume):
            played.append((len(adpcm), volume))
            return True

    service = speaker.SpeakerService(None, session_for=lambda slot: Session())
    service.event(0, "mode", count=2)
    await asyncio.sleep(0.05)
    assert played == []                                     # off by default
    service.set_config({"enabled": True, "volume": 0.3, "events": {"connect": None}})
    service.event(0, "connect")
    service.event(0, "mode", count=2)
    await asyncio.sleep(0.1)
    assert played == [(len(speaker.encode_adpcm(speaker.BUILTIN["count"](2))), 0.3)]
    with pytest.raises(ValueError):
        await service.play(0, "chime", volume=3)
