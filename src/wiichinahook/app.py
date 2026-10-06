from __future__ import annotations

import asyncio
from .api import ApiServer
from .bt import WiimoteManager
from .dsu import DsuServer


async def run_app(config, duration=None):
    dsu = DsuServer(config.dsu.host, config.dsu.port)
    api = None
    tasks = []
    def publish(state):
        dsu.send_state(state)
        if api:
            api.publish(state)
    manager = WiimoteManager(config, publish)
    try:
        api = await ApiServer(manager, config.api.host, config.api.port).start()
        print(f"DSU {config.dsu.host}:{config.dsu.port}; API ws://{config.api.host}:{config.api.port}", flush=True)
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
