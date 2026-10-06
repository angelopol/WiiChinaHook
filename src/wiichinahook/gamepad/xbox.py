"""Virtual Xbox 360 controllers through ViGEmBus (vgamepad) and the mode hub."""
from __future__ import annotations

import asyncio
import logging

from .mapping import DEFAULT_CONFIG, MappingEngine, mode_type, unavailable_bindings, validate_config

log = logging.getLogger(__name__)

BUTTON_NAMES = {
    "A": "XUSB_GAMEPAD_A", "B": "XUSB_GAMEPAD_B", "X": "XUSB_GAMEPAD_X", "Y": "XUSB_GAMEPAD_Y",
    "LB": "XUSB_GAMEPAD_LEFT_SHOULDER", "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "BACK": "XUSB_GAMEPAD_BACK", "START": "XUSB_GAMEPAD_START", "GUIDE": "XUSB_GAMEPAD_GUIDE",
    "L3": "XUSB_GAMEPAD_LEFT_THUMB", "R3": "XUSB_GAMEPAD_RIGHT_THUMB",
    "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP", "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT", "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
}


class XboxPad:
    """One ViGEm Xbox 360 controller. `on_rumble(large, small)` is called from a
    ViGEm thread when a game drives the motors."""

    def __init__(self, on_rumble=None):
        import vgamepad
        self.vg = vgamepad
        self.pad = vgamepad.VX360Gamepad()
        self.pressed = set()
        self.on_rumble = on_rumble
        if on_rumble:
            self.pad.register_notification(callback_function=self._notification)

    def _notification(self, client, target, large_motor, small_motor, led_number, user_data):
        self.on_rumble(large_motor, small_motor)

    def send(self, state):
        for name in state.buttons - self.pressed:
            self.pad.press_button(button=getattr(self.vg.XUSB_BUTTON, BUTTON_NAMES[name]))
        for name in self.pressed - state.buttons:
            self.pad.release_button(button=getattr(self.vg.XUSB_BUTTON, BUTTON_NAMES[name]))
        self.pressed = set(state.buttons)
        self.pad.left_trigger_float(value_float=state.lt)
        self.pad.right_trigger_float(value_float=state.rt)
        self.pad.left_joystick_float(x_value_float=state.lx, y_value_float=state.ly)
        self.pad.right_joystick_float(x_value_float=state.rx, y_value_float=state.ry)
        self.pad.update()

    def close(self):
        try:
            if self.on_rumble:
                self.pad.unregister_notification()
            self.pad.reset()
            self.pad.update()
        finally:
            self.pad = None  # vgamepad removes the device when the object is released


class GamepadHub:
    """Global mode (1-4) and one virtual controller per connected remote while the
    active mode has a template. Mode changes come from modifier + arrow on any
    remote or from the API/GUI; every remote rumbles the mode number in pulses
    (plus a long one if its active template uses inputs it does not have)."""

    def __init__(self, config=None, rumble=None, on_change=None, pad_factory=XboxPad, loop=None, blink=None,
                 on_output=None):
        self.config = validate_config(config if config is not None else DEFAULT_CONFIG)
        self.rumble = rumble              # async rumble(slot, duration_ms) or None
        self.blink = blink                # async blink(slot, led_mask): flash the mode's LED
        self.on_output = on_output        # called with each slot's Xbox output when it changes
        self.outputs = {}
        self.on_change = on_change        # called with status() after any change
        self.pad_factory = pad_factory
        self.loop = loop
        self.engines, self.pads, self.problems, self.connected = {}, {}, {}, set()
        self.capabilities = {}
        self.shakes, self.shake_seq = {}, 0   # last shakes per slot, for the GUI's live test
        self.error = None
        self.tasks = set()

    @property
    def mode(self):
        return self.config["mode"]

    @property
    def mode_type(self):
        """'xbox', 'dsu' or None (empty) for the active mode."""
        return mode_type(self.config["modes"][self.mode - 1])

    @property
    def template(self):
        """The active Xbox template, or None in DSU/empty modes."""
        current = self.config["modes"][self.mode - 1]
        return current if mode_type(current) == "xbox" else None

    @property
    def dsu_active(self):
        return self.mode_type == "dsu"

    def status(self):
        return {"mode": self.mode, "modifier": self.config["modifier"],
                "modes": [t["name"] if t else None for t in self.config["modes"]],
                "types": [mode_type(t) for t in self.config["modes"]],
                "pads": sorted(self.pads), "problems": {str(k): v for k, v in self.problems.items() if v},
                "error": self.error, "config": self.config,
                "shakes": {"seq": self.shake_seq, "by_slot": {str(k): v for k, v in self.shakes.items()}}}

    def changed(self):
        if self.on_change:
            self.on_change(self.status())

    def spawn(self, coro):
        task = asyncio.ensure_future(coro, loop=self.loop) if self.loop else asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    # -- state from the remotes ------------------------------------------------
    def update(self, state):
        slot = state.slot
        if not state.connected:
            if slot in self.connected:
                self.report_output(slot, None)
                self.connected.discard(slot)
                self.engines.pop(slot, None)
                self.problems.pop(slot, None)
                self.capabilities.pop(slot, None)
                self.close_pad(slot)
                self.changed()
            return
        self.capabilities[slot] = state.capabilities
        if slot not in self.connected:
            self.connected.add(slot)
            self.problems[slot] = unavailable_bindings(self.template, state.capabilities)
            self.changed()
        engine = self.engines.setdefault(slot, MappingEngine())
        snapshot = {"buttons": state.buttons, "timestamp_us": state.timestamp_us, "accel_g": state.accel_g,
                    "gyro_dps": state.gyro_dps, "ir": state.ir, "nunchuk": state.nunchuk}
        template = self.template
        output, request = engine.process(snapshot, template, self.config["modifier"])
        fired = engine.take_fired()
        if fired:
            self.shake_seq += 1
            self.shakes[slot] = [{"device": d, "axis": a, "g": g} for d, a, g in fired]
            self.changed()
        if request is not None and request != self.mode:
            self.set_mode(request)
            return
        if template is None or output is None:
            self.report_output(slot, None)
            return
        self.report_output(slot, output)
        problems = unavailable_bindings(template, state.capabilities)
        if problems != self.problems.get(slot):
            self.problems[slot] = problems
            self.changed()
        pad = self.pads.get(slot) or self.open_pad(slot)
        if pad is not None:
            try:
                pad.send(output)
            except Exception as exc:
                self.error = f"Virtual controller {slot}: {exc}"
                log.warning(self.error)
                self.close_pad(slot)

    def report_output(self, slot, output):
        """Publish what the virtual controller shows (for the GUI's live Xbox view)."""
        if output is None:
            data = {"slot": slot, "active": False}
        else:
            data = {"slot": slot, "active": True, "buttons": sorted(output.buttons),
                    **{k: round(getattr(output, k), 2) for k in ("lt", "rt", "lx", "ly", "rx", "ry")}}
        if self.outputs.get(slot) != data:
            self.outputs[slot] = data
            if self.on_output:
                self.on_output(data)

    # -- virtual controllers -----------------------------------------------------
    def open_pad(self, slot):
        if self.error and "ViGEm" in self.error:
            return None
        try:
            pad = self.pad_factory(on_rumble=lambda large, small, s=slot: self.game_rumble(s, large, small))
        except Exception as exc:  # vgamepad missing or ViGEmBus not installed
            self.error = f"ViGEm unavailable: {exc}"
            log.warning("%s; install ViGEmBus to use the Xbox modes", self.error)
            self.changed()
            return None
        self.pads[slot] = pad
        log.info("Virtual Xbox controller for slot %d", slot)
        self.changed()
        return pad

    def close_pad(self, slot):
        pad = self.pads.pop(slot, None)
        if pad is not None:
            try:
                pad.close()
            except Exception as exc:
                log.debug("Closing virtual controller %d: %s", slot, exc)

    def close(self):
        for slot in list(self.pads):
            self.close_pad(slot)

    def game_rumble(self, slot, large, small):
        # ViGEm calls this from its own thread.
        if self.rumble is None or self.loop is None:
            return
        duration = 5000 if (large or small) else 0
        self.loop.call_soon_threadsafe(lambda: self.spawn(self.rumble(slot, duration)))

    # -- modes and configuration -------------------------------------------------
    def set_mode(self, mode):
        if mode not in (1, 2, 3, 4):
            raise ValueError("mode must be 1..4")
        self.config["mode"] = mode
        if self.template is None:
            self.close()
        for slot in self.connected:  # check the new template against each remote
            self.problems[slot] = unavailable_bindings(self.template, self.capabilities.get(slot, {}))
        current = self.config["modes"][mode - 1]
        log.info("Gamepad mode %d (%s)", mode, current["name"] if current else "empty")
        for slot in sorted(self.connected):
            self.spawn(self.announce(slot, mode))
        self.changed()
        return self.status()

    async def announce(self, slot, mode):
        """Blink LED N and rumble N pulses for mode N; a final long pulse if the
        remote lacks inputs the mode uses."""
        if self.blink is not None:
            self.spawn(self.blink(slot, 0x10 << (mode - 1)))
        if self.rumble is None:
            return
        try:
            for _ in range(mode):
                await self.rumble(slot, 120)
                await asyncio.sleep(0.3)
            if self.problems.get(slot) and self.template is not None:
                await asyncio.sleep(0.2)
                await self.rumble(slot, 700)
        except Exception as exc:
            log.debug("Mode rumble slot %d: %s", slot, exc)

    def set_config(self, config):
        self.config = validate_config(config)
        if self.template is None:
            self.close()
        self.changed()
        return self.status()
