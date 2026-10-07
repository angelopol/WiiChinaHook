from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from .api import ApiServer
from .dsu import DsuServer, IrDsuServer, NunchukDsuServer
from .gamepad.mapping import DSU_TEMPLATE
from .gamepad.xbox import GamepadHub
from .speaker import SpeakerService

log = logging.getLogger(__name__)


class Outputs:
    """Fans every remote's state out to DSU (main + extra servers), the API, the
    gamepad hub and the speaker event cues. All per-remote state is keyed by slot,
    so up to four remotes never share anything here."""

    def __init__(self, dsu, extra=None, api=None, hub=None, speaker=None):
        self.dsu, self.extra = dsu, extra or {}
        self.api, self.hub, self.speaker = api, hub, speaker
        self.phases, self.low_battery = {}, set()

    def publish(self, state):
        # DSU carries the remotes in the DSU mode; other modes keep DSU clients
        # connected but idle, so a game never gets the same remote twice.
        hub = self.hub
        active = hub is None or hub.dsu_active
        self.dsu.send_state(state, active=active)
        if self.extra:
            options = hub.dsu_options if hub else DSU_TEMPLATE
            for name, server in self.extra.items():
                server.enabled = bool(options and options[f"{name}_server"])
                if name == "ir" and options:
                    server.ir_range = options["ir_range"]
                server.send_state(state, active=active)
        if self.api:
            self.api.publish(state)
        if hub:
            try:
                hub.update(state)
            except Exception:  # a mapping bug must never stop DSU/API
                log.exception("Gamepad mapping failed")
        if self.speaker:
            self.speaker_events(state)

    def speaker_events(self, state):
        """Connected / low-battery cues (no-ops unless the speaker sounds are enabled)."""
        slot, previous = state.slot, self.phases.get(state.slot)
        self.phases[slot] = state.phase
        if state.phase == "ready" and previous != "ready":
            self.speaker.event(slot, "connect")
        if not state.connected:
            self.low_battery.discard(slot)
        elif state.battery is not None:
            if state.battery < 0.15 and slot not in self.low_battery:
                self.low_battery.add(slot)
                self.speaker.event(slot, "low_battery")
            elif state.battery > 0.25:
                self.low_battery.discard(slot)


LAST_MODE_FILE = "gamepad_mode.json"


def read_last_mode(state_dir) -> int | None:
    try:
        mode = json.loads((Path(state_dir) / LAST_MODE_FILE).read_text(encoding="utf-8"))["mode"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return mode if mode in (1, 2, 3, 4) else None


def save_last_mode(state_dir, mode):
    try:
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        (Path(state_dir) / LAST_MODE_FILE).write_text(json.dumps({"mode": mode}), encoding="utf-8")
    except OSError as exc:
        log.warning("Could not save the active mode: %s", exc)


def startup_gamepad(config) -> dict:
    """The mapping config the service starts with: the fixed startup mode if one is
    chosen, else the last active mode (saved whenever it changes), else the config's."""
    gamepad = dict(config.gamepad)
    gamepad["mode"] = gamepad.get("startup_mode") or read_last_mode(config.state_dir) or gamepad["mode"]
    return gamepad


async def run_app(config, duration=None):
    dsu = DsuServer(config.dsu.host, config.dsu.port)
    extra = {}  # optional servers; a busy port only disables that server
    for name, cls, port in (("nunchuk", NunchukDsuServer, config.dsu.nunchuk_port),
                            ("ir", IrDsuServer, config.dsu.ir_port)):
        if port:
            try:
                extra[name] = cls(config.dsu.host, port)
            except OSError as exc:
                log.warning("DSU %s server on port %d unavailable: %s", name, port, exc)
    api = None
    tasks = []
    outputs = Outputs(dsu, extra)
    if config.mode == "bluetooth":
        from .bt import WiimoteManager as Manager
    else:
        from .dolphinbar import DolphinBarManager as Manager
    manager = Manager(config, outputs.publish)

    async def rumble(slot, duration_ms):
        try:
            await manager.session_for(slot).rumble(duration_ms)
        except ValueError:
            pass  # slot no longer connected

    async def blink(slot, led_mask):
        try:
            await manager.session_for(slot).blink_led(led_mask)
        except ValueError:
            pass

    speaker = outputs.speaker = SpeakerService(config.speaker, config.state_dir.parent, manager.session_for)
    manager.speaker = speaker
    gamepad = startup_gamepad(config)
    saved_mode = [gamepad["mode"]]

    def on_change(status):
        if status["mode"] != saved_mode[0]:   # remote (B + arrow), GUI or tray: remember it
            saved_mode[0] = status["mode"]
            save_last_mode(config.state_dir, status["mode"])
        if api:
            api.publish_gamepad(status)

    hub = GamepadHub(gamepad, rumble=rumble, blink=blink, loop=asyncio.get_running_loop(),
                     sound=lambda slot, mode: speaker.event(slot, "mode", count=mode),
                     on_change=on_change,
                     on_output=lambda output: api.publish_xbox(output) if api else None)
    manager.gamepad = outputs.hub = hub
    try:
        api = outputs.api = await ApiServer(manager, config.api.host, config.api.port).start()
        ports = ", ".join(f"{name} {server.sock.getsockname()[1]}" for name, server in extra.items())
        print(f"Mode {config.mode}; DSU {config.dsu.host}:{config.dsu.port}"
              f"{f' (+ {ports})' if ports else ''}; API ws://{config.api.host}:{config.api.port}", flush=True)
        async def poll():
            while True:
                dsu.poll()
                for server in extra.values():
                    server.poll()
                await asyncio.sleep(.005)
        tasks = [asyncio.create_task(manager.run()), asyncio.create_task(poll())]
        if duration is None:
            await asyncio.gather(*tasks)
        else:
            await asyncio.sleep(duration)
    finally:
        manager.stopping = True
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        hub.close()
        if api:
            await api.close()
        dsu.close()
        for server in extra.values():
            server.close()
