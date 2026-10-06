"""Service lifecycle for the GUI: run the hook in-process (or attach to one that
is already running) and talk to it through the local WebSocket API v1."""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from ..app import run_app

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


class ApiClient:
    """Request/response plus subscription events over one WebSocket."""

    def __init__(self, url, on_event, on_closed=None):
        self.url, self.on_event, self.on_closed = url, on_event, on_closed
        self.socket = None
        self.reader = None
        self.pending = {}
        self.ids = itertools.count(1)

    async def open(self, timeout=5.0):
        self.socket = await connect(self.url, open_timeout=timeout, max_size=262144)
        self.reader = asyncio.create_task(self.read())

    async def read(self):
        try:
            async for raw in self.socket:
                message = json.loads(raw)
                future = self.pending.pop(message.get("id"), None)
                if future is not None:
                    if not future.done():
                        future.set_result(message)
                elif message.get("event") == "state":
                    self.on_event(message["data"])
        except ConnectionClosed:
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ApiError("Service connection closed"))
            self.pending.clear()
            if self.on_closed:
                self.on_closed()

    async def request(self, command, timeout=15.0, **args):
        if self.socket is None:
            raise ApiError("Service is not running")
        request_id = next(self.ids)
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        await self.socket.send(json.dumps({"v": 1, "id": request_id, "command": command, "args": args}))
        reply = await asyncio.wait_for(future, timeout)
        if not reply.get("ok"):
            raise ApiError(reply.get("error", {}).get("message", "request failed"))
        return reply["result"]

    async def close(self):
        if self.socket is not None:
            await self.socket.close()
        if self.reader is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader
        self.socket = self.reader = None


def address_in_use(exc: BaseException) -> bool:
    # WSAEADDRINUSE (10048) on Windows, EADDRINUSE (98/48) elsewhere.
    return isinstance(exc, OSError) and (exc.errno in (98, 48, 10048) or getattr(exc, "winerror", None) == 10048)


class ServiceRuntime:
    """status: stopped | starting | running | attached | error"""

    def __init__(self, on_state, on_status, runner=run_app):
        self.on_state, self.on_status, self.runner = on_state, on_status, runner
        self.task = None
        self.client = None
        self.status = "stopped"
        self.error = None

    def set_status(self, status, error=None):
        self.status, self.error = status, error
        self.on_status(status, error)

    @property
    def active(self):
        return self.status in ("running", "attached")

    async def start(self, config):
        if self.status in ("starting", "running", "attached"):
            return
        self.set_status("starting")
        url = f"ws://{config.api.host}:{config.api.port}"
        self.task = asyncio.create_task(self.runner(config))
        try:
            for _ in range(50):  # wait up to ~5 s for the API to listen
                if self.task.done():
                    break
                with contextlib.suppress(OSError, TimeoutError):
                    await self.connect(url)
                    break
                await asyncio.sleep(0.1)
            if self.task.done():
                exc = self.task.exception()
                self.task = None
                if exc is not None and address_in_use(exc):
                    # Another hook (e.g. the CLI) already owns the ports: attach to it.
                    await self.connect(url)
                    self.set_status("attached")
                    return
                raise exc or RuntimeError("Service stopped during start")
            if self.client is None:
                raise TimeoutError("Service API did not start")
            self.task.add_done_callback(self.service_ended)
            self.set_status("running")
        except Exception as exc:
            await self.stop()
            self.set_status("error", f"{type(exc).__name__}: {exc}")

    async def connect(self, url):
        client = ApiClient(url, self.on_state, self.client_closed)
        await client.open(timeout=1.0)
        self.client = client
        snapshot = await client.request("subscribe")
        for state in snapshot.get("devices", []):
            self.on_state(state)

    def client_closed(self):
        if self.status == "attached":
            self.client = None
            self.set_status("stopped", "The external service stopped")

    def service_ended(self, task):
        if task.cancelled() or self.task is not task:
            return
        self.task = None
        exc = task.exception()
        self.set_status("error" if exc else "stopped", f"{type(exc).__name__}: {exc}" if exc else None)

    async def stop(self):
        client, task = self.client, self.task
        self.client = self.task = None
        if client is not None:
            await client.close()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self.status != "error":
            self.set_status("stopped")

    async def request(self, command, **args):
        if self.client is None:
            raise ApiError("Service is not running")
        return await self.client.request(command, **args)

    async def snapshot(self):
        return await self.request("devices")
