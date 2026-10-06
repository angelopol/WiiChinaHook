from __future__ import annotations

import asyncio
import logging

from .api import ApiServer
from .dsu import DsuServer
from .gamepad.xbox import GamepadHub
from .speaker import SpeakerService

log = logging.getLogger(__name__)


async def run_app(config, duration=None):
    dsu = DsuServer(config.dsu.host, config.dsu.port)
    api = None
    tasks = []
    hub = None
    speaker = None
    phases, low_battery = {}, set()

    def speaker_events(state):
        """Connected / low-battery cues (no-ops unless the speaker sounds are enabled)."""
        slot, previous = state.slot, phases.get(state.slot)
        phases[slot] = state.phase
        if state.phase == "ready" and previous != "ready":
            speaker.event(slot, "connect")
        if not state.connected:
            low_battery.discard(slot)
        elif state.battery is not None:
            if state.battery < 0.15 and slot not in low_battery:
                low_battery.add(slot)
                speaker.event(slot, "low_battery")
            elif state.battery > 0.25:
                low_battery.discard(slot)

    def publish(state):
        # DSU carries the remotes in the DSU mode; other modes keep DSU clients
        # connected but idle, so a game never gets the same remote twice.
        dsu.send_state(state, active=hub is None or hub.dsu_active)
        if api:
            api.publish(state)
        if hub:
            try:
                hub.update(state)
            except Exception:  # a mapping bug must never stop DSU/API
                log.exception("Gamepad mapping failed")
        if speaker:
            speaker_events(state)
    if config.mode == "bluetooth":
        from .bt import WiimoteManager as Manager
    else:
        from .dolphinbar import DolphinBarManager as Manager
    manager = Manager(config, publish)

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

    speaker = SpeakerService(config.speaker, config.state_dir.parent, manager.session_for)
    manager.speaker = speaker
    hub = GamepadHub(config.gamepad, rumble=rumble, blink=blink, loop=asyncio.get_running_loop(),
                     sound=lambda slot, mode: speaker.event(slot, "mode", count=mode),
                     on_change=lambda status: api.publish_gamepad(status) if api else None,
                     on_output=lambda output: api.publish_xbox(output) if api else None)
    manager.gamepad = hub
    try:
        api = await ApiServer(manager, config.api.host, config.api.port).start()
        print(f"Mode {config.mode}; DSU {config.dsu.host}:{config.dsu.port}; API ws://{config.api.host}:{config.api.port}", flush=True)
        async def poll():
            while True:
                dsu.poll()
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
