"""Loopback JSON/WebSocket API v1. Slow subscribers receive latest snapshots."""
from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

MAX_HZ = 60  # state/xbox events per second and slot, at most


def stream_hz(value):
    """Subscriber event rate: 1..60 per second, or 0 to pause state/xbox events."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= MAX_HZ:
        raise ValueError(f"hz must be 0..{MAX_HZ}")
    return value


class ApiServer:
    def __init__(self, manager, host="127.0.0.1", port=26761):
        self.manager, self.host, self.port = manager, host, port
        self.subscribers = {}
        self.server = None

    async def start(self):
        self.server = await serve(self.handle, self.host, self.port, max_size=16384,
                                  max_queue=16, origins=[None])
        return self

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    def publish(self, state):
        # Called for every report (~235/s per remote): keep only a reference to the
        # live state; it is converted when the subscriber's next batch goes out.
        for pending, wake, settings in self.subscribers.values():
            pending[state.slot] = state
            if settings["hz"]:
                wake.set()

    def publish_xbox(self, output):
        for pending, wake, settings in self.subscribers.values():
            pending[f"xbox{output['slot']}"] = output
            if settings["hz"]:
                wake.set()

    def publish_gamepad(self, status):
        for pending, wake, settings in self.subscribers.values():
            pending["gamepad"] = status
            wake.set()                       # mode changes go out even when paused

    async def handle(self, socket):
        lock = asyncio.Lock()
        async def send(data):
            async with lock:
                await asyncio.wait_for(socket.send(json.dumps(data)), 5)
        pending, wake, settings = {}, asyncio.Event(), {"hz": MAX_HZ}
        async def stream():
            while True:
                await wake.wait()
                await asyncio.sleep(1 / (settings["hz"] or MAX_HZ))
                wake.clear()
                if settings["hz"]:
                    batch = list(pending.items())
                    pending.clear()
                else:                        # paused: only mode/status changes
                    batch = [("gamepad", pending.pop("gamepad"))] if "gamepad" in pending else []
                for key, data in batch:
                    event = "gamepad" if key == "gamepad" else "xbox" if str(key).startswith("xbox") else "state"
                    if event == "state":
                        data = data.to_dict()
                    await send({"v": 1, "event": event, "data": data})
        sender = None
        try:
            async for raw in socket:
                request_id = None
                try:
                    request = json.loads(raw)
                    if not isinstance(request, dict):
                        raise ValueError("Request must be an object")
                    request_id = request.get("id")
                    if not isinstance(request_id, (int, str)):
                        raise ValueError("id must be an integer or string")
                    if request.get("v") != 1:
                        raise ValueError("Unsupported API version; use v=1")
                    command = request.get("command")
                    args = request.get("args", {})
                    if not isinstance(args, dict):
                        raise ValueError("args must be an object")
                    if command in ("subscribe", "stream_rate") and "hz" in args:
                        settings["hz"] = stream_hz(args["hz"])
                        wake.set()                   # resume with the latest state
                    if command == "stream_rate":
                        result = {"hz": settings["hz"]}
                    elif command == "subscribe":
                        if sender is None:
                            self.subscribers[socket] = (pending, wake, settings)
                            sender = asyncio.create_task(stream())
                            # If a slow/broken sender fails, close its socket to stop the handler.
                            sender.add_done_callback(lambda t: asyncio.create_task(socket.close()) if not t.cancelled() and t.exception() else None)
                        result = self.manager.snapshot()
                    else:
                        result = await self.dispatch(command, args)
                    await send({"v": 1, "id": request_id, "ok": True, "result": result})
                except (ValueError, TypeError, KeyError, RuntimeError) as exc:
                    await send({"v": 1, "id": request_id, "ok": False,
                                "error": {"code": "request_failed", "message": str(exc)}})
                except ConnectionClosed:
                    raise
                except Exception as exc:
                    logging.getLogger(__name__).exception("API command failed")
                    await send({"v": 1, "id": request_id, "ok": False,
                                "error": {"code": "operation_failed", "message": str(exc)}})
        except (ConnectionClosed, TimeoutError):
            pass
        finally:
            self.subscribers.pop(socket, None)
            if sender:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)

    async def dispatch(self, command, args):
        if command == "devices":
            return self.manager.snapshot()
        if command in ("gamepad", "gamepad_mode", "gamepad_config"):
            hub = getattr(self.manager, "gamepad", None)
            if hub is None:
                raise RuntimeError("Gamepad modes are not available in this service")
            if command == "gamepad_mode":
                return hub.set_mode(args.get("mode"))
            if command == "gamepad_config":
                return hub.set_config(args.get("config"))
            return hub.status()
        if command in ("play_sound", "speaker_config"):
            speaker = getattr(self.manager, "speaker", None)
            if speaker is None:
                raise RuntimeError("The speaker is not available in this service")
            if command == "speaker_config":
                return speaker.set_config(args.get("config"))
            return await speaker.play(args.get("slot", 0), args.get("sound", "chime"), args.get("volume"))
        if command == "pair":
            return await self.manager.pair(args.get("seconds", 20), args.get("mode", "sync"), args.get("address"))
        slot = args.get("slot", 0)
        if not isinstance(slot, int) or isinstance(slot, bool) or slot not in range(4):
            raise ValueError("slot must be 0..3")
        if command == "forget":
            return await self.manager.forget(slot)
        if command == "slot_options":
            options = {k: args.get(k) for k in ("quick_calibration", "combo", "ir_calibration", "combo_hold_ms",
                                                 "combo_window_ms", "debounce_ms")}
            return self.manager.set_slot_options(slot, **options)
        if command == "quick_calibrate":
            return await self.manager.session_for(slot).quick_calibrate()
        if command == "calibrate_axis":
            if args.get("axis") not in ("pitch", "roll", "yaw"):
                raise ValueError("axis must be pitch, roll or yaw")
            return await self.manager.calibrate_axis(slot, args["axis"])
        if command == "calibrate":
            return await self.manager.calibrate(slot)
        if command == "calibrate_noise":
            seconds = args.get("seconds", 10)
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 10 <= seconds <= 30:
                raise ValueError("seconds must be 10..30")
            return await self.manager.calibrate_noise(slot, float(seconds), bool(args.get("reset", False)))
        if command == "led":
            await self.manager.session_for(slot).set_led(args["mask"])
            return {"slot": slot}
        if command == "rumble":
            await self.manager.session_for(slot).rumble(args.get("duration_ms", 500))
            return {"slot": slot}
        raise ValueError(f"Unknown command: {command}")
