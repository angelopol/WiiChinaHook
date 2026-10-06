from __future__ import annotations

import asyncio
import logging

from .api import ApiServer
from .dsu import DsuServer
from .gamepad.xbox import GamepadHub

log = logging.getLogger(__name__)


async def run_app(config, duration=None):
    dsu = DsuServer(config.dsu.host, config.dsu.port)
    api = None
    tasks = []
    hub = None
    def publish(state):
        dsu.send_state(state)
        if api:
            api.publish(state)
        if hub:
            try:
                hub.update(state)
            except Exception:  # a mapping bug must never stop DSU/API
                log.exception("Gamepad mapping failed")
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

    hub = GamepadHub(config.gamepad, rumble=rumble, blink=blink, loop=asyncio.get_running_loop(),
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
