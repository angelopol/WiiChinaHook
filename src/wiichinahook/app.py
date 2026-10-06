from __future__ import annotations

import asyncio
from .api import ApiServer
from .dsu import DsuServer


async def run_app(config, duration=None):
    dsu = DsuServer(config.dsu.host, config.dsu.port)
    api = None
    tasks = []
    def publish(state):
        dsu.send_state(state)
        if api:
            api.publish(state)
    if config.mode == "bluetooth":
        from .bt import WiimoteManager as Manager
    else:
        from .dolphinbar import DolphinBarManager as Manager
    manager = Manager(config, publish)
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
        if api:
            await api.close()
        dsu.close()
