"""Flet desktop app: configure both connection modes and test Wiimotes live."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import collections
import json
import logging
import os
from pathlib import Path
import webbrowser

import flet as ft
import flet.canvas as cv

from ..config import COMBOS, AppConfig, SlotOptions, load_config, parse_int, save_config
from ..orientation import from_axis_angle, multiply, reference_yaw
from .i18n import LANGUAGES, Translator
from .model import (BUTTONS, BUTTON_LABELS, bar_value, config_from_form, fmt, form_from_config,
                    ir_to_canvas, led_mask, pressed_buttons, stick_to_canvas)
from .service import ServiceRuntime
from .wiimote3d import project
from ..drivers import choose, packages_for, switch_adapter
from ..usb_drivers import ZADIG_URL, find_zadig, list_adapters

log = logging.getLogger(__name__)
REFRESH_HZ = 15
STATUS_COLORS = {"stopped": ft.Colors.GREY, "starting": ft.Colors.AMBER, "running": ft.Colors.GREEN,
                 "attached": ft.Colors.BLUE, "error": ft.Colors.RED}
IR_W, IR_H, STICK = 176, 132, 84
POSE_W, POSE_H = 240, 176
GYRO_RANGE_DPS = 250.0  # bar full scale; typical hand rotations stay below it


class LogBuffer(logging.Handler):
    def __init__(self, size=400):
        super().__init__(logging.INFO)
        self.lines = collections.deque(maxlen=size)
        self.version = 0
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.lines.append(self.format(record))
        self.version += 1


def chip(text, width=30):
    return ft.Container(ft.Text(text, size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                        width=width, height=24, border_radius=5, alignment=ft.Alignment.CENTER,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST)


def axis_rows(names):
    bars, labels, rows = [], [], []
    for name in names:
        bar = ft.ProgressBar(value=0.5, width=120, bar_height=8, border_radius=4)
        label = ft.Text("—", size=12, width=64, text_align=ft.TextAlign.RIGHT)
        bars.append(bar)
        labels.append(label)
        rows.append(ft.Row([ft.Text(name, size=12, width=44), bar, label], spacing=6))
    return bars, labels, rows


class SlotCard:
    def __init__(self, slot, t, controller):
        self.slot, self.t, self.controller = slot, t, controller
        self.title = ft.Text(t("slot", n=slot), size=16, weight=ft.FontWeight.BOLD)
        self.status = ft.Text(t("disconnected"), size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.battery = ft.ProgressBar(value=0, width=70, bar_height=8, border_radius=4, tooltip=t("battery"))
        self.details = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
        self.buttons = {name: chip(BUTTON_LABELS[name]) for name, _ in BUTTONS}
        self.nunchuk_buttons = {"c": chip("C"), "z": chip("Z")}
        self.accel_bars, self.accel_labels, accel_rows = axis_rows(("X", "Y", "Z"))
        self.gyro_bars, self.gyro_labels, gyro_rows = axis_rows(("Yaw", "Roll", "Pitch"))
        self.ir_canvas = cv.Canvas(shapes=[], width=IR_W, height=IR_H)
        self.stick_canvas = cv.Canvas(shapes=[], width=STICK, height=STICK)
        self.pose_canvas = cv.Canvas(shapes=[], width=POSE_W, height=POSE_H)
        self.pose_hint = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
        self.yaw_offset = 0.0
        self.referenced = False
        self.orientation = None
        self.recenter = ft.IconButton(ft.Icons.CENTER_FOCUS_STRONG, tooltip=t("recenter"), on_click=self.on_recenter)
        self.recenter_seq = None
        config = getattr(controller, "config", None)
        options = config.slots[slot] if config else SlotOptions()
        self.quick_switch = ft.Switch(label=t("quick_calibration"), value=options.quick_calibration,
                                      tooltip=t("quick_calibration_hint"),
                                      on_change=lambda e: self.option_changed(quick_calibration=e.control.value))
        self.combo_select = ft.Dropdown(value=options.combo, width=150, dense=True, label=t("combo"),
                                        options=[ft.DropdownOption(k, t(f"combo_{k.replace('+', '_')}"))
                                                 for k in COMBOS],
                                        on_select=lambda e: self.option_changed(combo=e.control.value))
        self.ir_switch = ft.Switch(label=t("ir_calibration"), value=options.ir_calibration,
                                   tooltip=t("ir_calibration_hint"),
                                   on_change=lambda e: self.option_changed(ir_calibration=e.control.value))
        self.leds = [ft.Checkbox(value=i == slot % 4, on_change=self.on_led) for i in range(4)]
        self.action_controls = [
            ft.Button(t("rumble"), icon=ft.Icons.VIBRATION, on_click=self.on_rumble),
            ft.Button(t("calibrate"), icon=ft.Icons.TUNE, on_click=self.on_calibrate, tooltip=t("calibrate_hint")),
            ft.Button(t("scale"), icon=ft.Icons.STRAIGHTEN, on_click=self.on_scale, tooltip=t("scale_hint")),
            ft.TextButton(t("forget"), icon=ft.Icons.DELETE_OUTLINE, on_click=self.on_forget),
        ]
        names = [name for name, _ in BUTTONS]
        self.root = ft.Card(content=ft.Container(padding=12, content=ft.Column(spacing=8, controls=[
            ft.Row([self.title, self.status, ft.Container(expand=True), ft.Icon(ft.Icons.BATTERY_FULL, size=16),
                    self.battery]),
            self.details,
            ft.Text(self.t("buttons"), size=12, weight=ft.FontWeight.W_600),
            ft.Row([self.buttons[n] for n in names[:6]], spacing=4, wrap=True),
            ft.Row([self.buttons[n] for n in names[6:]] + [ft.Container(width=12)] +
                   list(self.nunchuk_buttons.values()), spacing=4, wrap=True),
            ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, wrap=True, spacing=16, controls=[
                ft.Column([ft.Row([ft.Text(t("pose"), size=12, weight=ft.FontWeight.W_600), self.recenter],
                                  spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                           ft.Container(self.pose_canvas, width=POSE_W, height=POSE_H, border_radius=8,
                                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST),
                           self.pose_hint], spacing=2),
                ft.Column([ft.Text(t("accel"), size=12, weight=ft.FontWeight.W_600), *accel_rows,
                           ft.Text(t("gyro"), size=12, weight=ft.FontWeight.W_600), *gyro_rows], spacing=4),
                ft.Column([ft.Text(t("ir_view"), size=12, weight=ft.FontWeight.W_600),
                           ft.Container(self.ir_canvas, width=IR_W, height=IR_H, bgcolor=ft.Colors.BLACK,
                                        border_radius=6)], spacing=4),
                ft.Column([ft.Text(t("nunchuk"), size=12, weight=ft.FontWeight.W_600),
                           ft.Container(self.stick_canvas, width=STICK, height=STICK,
                                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=STICK / 2)],
                          spacing=4),
            ]),
            ft.Row(self.action_controls, wrap=True, spacing=6),
            ft.Row([ft.Text(t("leds"), size=12), *self.leds], spacing=2),
            ft.Row([self.quick_switch, self.combo_select, self.ir_switch], wrap=True, spacing=12,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ])))
        self.render(None)

    def render(self, state):
        connected = bool(state and state.get("connected"))
        if state is None:
            self.status.value = self.t("disconnected")
        else:
            self.status.value = state.get("error") or state.get("phase", "")
            if connected:
                self.status.value = f"{state['phase']} · {state['address']}"
        self.status.color = ft.Colors.GREEN if connected else ft.Colors.ON_SURFACE_VARIANT
        self.battery.value = (state or {}).get("battery") or 0
        for control in self.action_controls + self.leds + [self.recenter]:
            control.disabled = not connected
        pressed = pressed_buttons(state["buttons"]) if connected else set()
        for name, control in self.buttons.items():
            control.bgcolor = ft.Colors.PRIMARY if name in pressed else ft.Colors.SURFACE_CONTAINER_HIGHEST
        nunchuk = state.get("nunchuk") if connected else None
        for key, control in self.nunchuk_buttons.items():
            control.bgcolor = ft.Colors.PRIMARY if nunchuk and nunchuk.get(key) else ft.Colors.SURFACE_CONTAINER_HIGHEST
        if connected:
            calibration = ", ".join(f"{k}: {v}" for k, v in state.get("calibration", {}).items() if k != "gyro_bias")
            self.details.value = (f"{self.t('extension')}: {state.get('extension') or '—'}   "
                                  f"{self.t('calibration')}: {calibration or '—'}")
        else:
            self.details.value = ""
        accel = (state or {}).get("accel_g") if connected else None
        gyro = (state or {}).get("gyro_dps") if connected else None
        for i in range(3):
            self.accel_bars[i].value = bar_value(accel[i] if accel else None, 3.0)
            self.accel_labels[i].value = fmt(accel[i] if accel else None)
            self.gyro_bars[i].value = bar_value(gyro[i] if gyro else None, GYRO_RANGE_DPS)
            self.gyro_labels[i].value = fmt(gyro[i] if gyro else None, 1)
        points = ir_to_canvas(state.get("ir") if connected else None, IR_W, IR_H)
        self.ir_canvas.shapes = [cv.Circle(x, y, 5, ft.Paint(color=ft.Colors.WHITE)) for x, y in points]
        shapes = [cv.Circle(STICK / 2, STICK / 2, STICK / 2 - 4,
                            ft.Paint(color=ft.Colors.ON_SURFACE_VARIANT, style=ft.PaintingStyle.STROKE))]
        if nunchuk and nunchuk.get("stick"):
            x, y = stick_to_canvas(nunchuk["stick"], STICK - 12)
            shapes.append(cv.Circle(x + 6, y + 6, 6, ft.Paint(color=ft.Colors.PRIMARY)))
        self.stick_canvas.shapes = shapes
        self.orientation = state.get("orientation") if connected else None
        calibration = state.get("calibration", {}) if connected else {}
        if self.orientation is None:
            self.referenced, self.recenter_seq = False, None
        elif calibration.get("heading") == "ir":
            self.yaw_offset, self.referenced = 0.0, True  # absolute: 0 = sensor bar / screen
        elif not self.referenced or calibration.get("recenter_seq") != self.recenter_seq:
            # First pose after connecting, or the remote ran its quick calibration.
            self.yaw_offset, self.referenced = reference_yaw(tuple(self.orientation)), True
        self.recenter_seq = calibration.get("recenter_seq") if self.orientation is not None else None
        self.render_pose(state if connected else None)

    def render_pose(self, state):
        q = self.orientation
        if q is None:
            q = (1.0, 0.0, 0.0, 0.0)
        else:  # show heading relative to the last "recenter"
            q = multiply(from_axis_angle((0.0, 0.0, 1.0), -self.yaw_offset), tuple(q))
        shapes = []
        for points, color in project(q, POSE_W, POSE_H):
            elements = [cv.Path.MoveTo(*points[0])] + [cv.Path.LineTo(*pt) for pt in points[1:]] + [cv.Path.Close()]
            shapes.append(cv.Path(elements, paint=ft.Paint(color=color, style=ft.PaintingStyle.FILL)))
        self.pose_canvas.shapes = shapes
        self.pose_canvas.opacity = 1.0 if self.orientation else 0.35
        if state is None:
            self.pose_hint.value = ""
        elif state.get("capabilities", {}).get("motionplus"):
            self.pose_hint.value = self.t("pose_gyro")
        else:
            self.pose_hint.value = self.t("pose_tilt")

    def on_recenter(self, e):
        if self.orientation:
            self.yaw_offset = reference_yaw(tuple(self.orientation))
            self.render_pose({"capabilities": {"motionplus": True}})
            self.pose_canvas.update()

    def option_changed(self, **change):
        self.controller.page.run_task(self.controller.update_slot_options, self.slot, change)

    async def on_led(self, e):
        await self.controller.command("led", slot=self.slot, mask=led_mask([c.value for c in self.leds]))

    async def on_rumble(self, e):
        await self.controller.command("rumble", slot=self.slot, duration_ms=500)

    async def on_calibrate(self, e):
        self.controller.notify(self.t("calibrate_hint"))
        if await self.controller.command("calibrate", slot=self.slot) is not None:
            self.on_recenter(None)  # the calibration pose becomes the reference
            self.controller.notify(self.t("calibrated", n=self.slot))

    def on_scale(self, e):
        t = self.t
        rows = []
        for axis in ("pitch", "roll", "yaw"):
            result = ft.Text("", size=12)
            spinner = ft.ProgressRing(width=18, height=18, visible=False)
            button = ft.FilledButton(t("scale_start"), icon=ft.Icons.PLAY_ARROW)
            button.on_click = self.make_axis_runner(axis, button, spinner, result)
            gesture = ft.Image(src=f"calibration_{axis}.gif", width=180, height=135, border_radius=6)
            rows.append(ft.Row([gesture, ft.Column([
                ft.Text(t(f"scale_{axis}"), weight=ft.FontWeight.BOLD),
                ft.Text(t(f"scale_{axis}_how"), size=12),
                ft.Row([button, spinner, result], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
            ], spacing=4, expand=True)], vertical_alignment=ft.CrossAxisAlignment.START, spacing=12))
        dialog = ft.AlertDialog(
            modal=True, title=ft.Text(t("scale_title", n=self.slot)),
            content=ft.Column([ft.Text(t("scale_intro"), size=12), *rows], tight=True, spacing=14, width=640,
                              scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton(t("close"), on_click=lambda e: self.controller.page.pop_dialog())])
        self.controller.page.show_dialog(dialog)

    def make_axis_runner(self, axis, button, spinner, result):
        async def run(e):
            button.disabled, spinner.visible = True, True
            result.value, result.color = self.t("scale_running"), None
            self.controller.page.update()
            reply = await self.controller.command("calibrate_axis", slot=self.slot, axis=axis)
            button.disabled, spinner.visible = False, False
            if reply is None:
                result.value, result.color = self.t("scale_failed"), ft.Colors.ERROR
            else:
                result.value = self.t("scale_done", factor=reply["factor"], degrees=reply["rotation_deg"])
                result.color = ft.Colors.GREEN
                self.on_recenter(None)
            self.controller.page.update()
        return run

    async def on_forget(self, e):
        if await self.controller.command("forget", slot=self.slot) is not None:
            self.controller.notify(self.t("forgot", n=self.slot))


class Controller:
    def __init__(self, page: ft.Page, config_path: Path, prefs_path: Path):
        self.page, self.config_path, self.prefs_path = page, config_path, prefs_path
        self.prefs = self.load_prefs()
        self.t = Translator(self.prefs.get("language", "en"))
        self.config = self.load_config()
        self.states = {}
        self.dirty = set()
        self.service_mode = None
        self.logs = LogBuffer()
        logging.getLogger().addHandler(self.logs)
        logging.getLogger().setLevel(logging.INFO)
        self.log_version = -1
        self.runtime = ServiceRuntime(self.on_state, self.on_status)
        self.cards = []
        self.closing = False

    # -- persistence -------------------------------------------------------
    def load_prefs(self):
        try:
            return json.loads(self.prefs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_prefs(self):
        self.prefs_path.parent.mkdir(parents=True, exist_ok=True)
        self.prefs_path.write_text(json.dumps(self.prefs, indent=2), encoding="utf-8")

    def load_config(self):
        try:
            return load_config(self.config_path)
        except FileNotFoundError:
            return AppConfig()
        except (ValueError, KeyError) as exc:
            log.warning("Ignoring invalid %s: %s", self.config_path, exc)
            return AppConfig()

    # -- service events ----------------------------------------------------
    def on_state(self, state):
        self.states[state["slot"]] = state
        self.dirty.add(state["slot"])

    def on_status(self, status, error):
        self.refresh_status()

    def notify(self, message):
        self.page.show_dialog(ft.SnackBar(ft.Text(message)))

    async def command(self, name, **args):
        if not self.runtime.active:
            self.notify(self.t("service_needed"))
            return None
        try:
            return await self.runtime.request(name, **args)
        except Exception as exc:
            self.notify(self.t("failed", error=exc))
            return None

    # -- UI ----------------------------------------------------------------
    def build(self):
        t = self.t
        page = self.page
        page.controls.clear()
        page.title = t("title")
        self.status_dot = ft.Container(width=12, height=12, border_radius=6)
        self.status_text = ft.Text("", size=13)
        self.toggle = ft.FilledButton(t("start"), icon=ft.Icons.PLAY_ARROW, on_click=self.on_toggle)
        language = ft.Dropdown(value=self.t.language, width=140, dense=True, label=t("language"),
                               options=[ft.DropdownOption(key, text) for key, text in LANGUAGES.items()],
                               on_select=self.on_language)
        header = ft.Row([ft.Icon(ft.Icons.SPORTS_ESPORTS), ft.Text(t("title"), size=20, weight=ft.FontWeight.BOLD),
                         ft.Container(width=16), self.status_dot, self.status_text, ft.Container(expand=True),
                         self.toggle, language], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.cards = [SlotCard(slot, t, self) for slot in range(4)]
        self.pair_panel = self.build_pair_panel()
        controllers = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, controls=[
            self.pair_panel,
            ft.ResponsiveRow([ft.Container(card.root, col={"md": 12, "lg": 6}) for card in self.cards]),
        ])
        self.log_view = ft.ListView(expand=True, spacing=2, auto_scroll=True)
        log_tab = ft.Column(expand=True, controls=[
            ft.Row([ft.TextButton(t("clear_log"), on_click=self.on_clear_log)]), self.log_view])
        tabs = ft.Tabs(length=3, expand=True, content=ft.Column(expand=True, controls=[
            ft.TabBar(tabs=[ft.Tab(label=t("tab_controllers"), icon=ft.Icons.SPORTS_ESPORTS),
                            ft.Tab(label=t("tab_settings"), icon=ft.Icons.SETTINGS),
                            ft.Tab(label=t("tab_log"), icon=ft.Icons.ARTICLE)]),
            ft.TabBarView(expand=True, controls=[controllers, self.build_settings(), log_tab]),
        ]))
        page.add(header, tabs)
        for slot in range(4):
            self.dirty.add(slot)
        self.refresh_status()
        self.render()

    def build_pair_panel(self):
        t = self.t
        self.pair_seconds = ft.TextField(value="30", label=t("pair_seconds"), width=110, dense=True)
        self.pair_mode = ft.Dropdown(value="sync", width=200, dense=True, options=[
            ft.DropdownOption("sync", t("pair_mode_sync")), ft.DropdownOption("temporary", t("pair_mode_temporary"))])
        self.pair_address = ft.TextField(label=t("pair_address"), width=200, dense=True)
        return ft.Card(visible=False, content=ft.Container(padding=12, content=ft.Column([
            ft.Text(t("pair_title"), weight=ft.FontWeight.BOLD),
            ft.Row([self.pair_seconds, self.pair_mode, self.pair_address,
                    ft.FilledButton(t("pair"), icon=ft.Icons.BLUETOOTH_SEARCHING, on_click=self.on_pair)],
                   wrap=True),
        ])))

    def build_settings(self):
        t = self.t
        form = form_from_config(self.config)
        self.fields = {
            "vid": ft.TextField(value=form["vid"], label=t("adapter_vid"), width=150),
            "pid": ft.TextField(value=form["pid"], label=t("adapter_pid"), width=150),
            "transport": ft.TextField(value=form["transport"], label=t("transport"), width=320),
            "dsu_host": ft.TextField(value=form["dsu_host"], label=t("dsu_host"), width=180),
            "dsu_port": ft.TextField(value=form["dsu_port"], label=t("dsu_port"), width=120),
            "api_port": ft.TextField(value=form["api_port"], label=t("api_port"), width=120),
        }
        self.switches = {"ir": ft.Switch(label=t("ir"), value=form["ir"]),
                         "motionplus": ft.Switch(label=t("motionplus"), value=form["motionplus"])}
        self.mode_group = ft.RadioGroup(value=form["mode"], on_change=self.on_mode_change, content=ft.Column([
            ft.Radio(value="dolphinbar", label=t("mode_dolphinbar")),
            ft.Radio(value="bluetooth", label=t("mode_bluetooth"))]))
        self.dolphinbar_help = ft.Text(t("dolphinbar_help"), size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.adapter_select = ft.Dropdown(label=t("adapter_select"), width=520, options=[],
                                          on_select=self.on_adapter_select)
        self.adapter_info = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.zadig_box = ft.Container(visible=False, padding=12, border_radius=8,
                                      bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, content=ft.Column([
            ft.Text(t("adapter_none"), weight=ft.FontWeight.W_600),
            ft.Text(t("zadig_help"), size=12),
            ft.Row([ft.FilledButton(t("zadig_open"), icon=ft.Icons.BUILD, on_click=self.on_zadig_open),
                    ft.OutlinedButton(t("zadig_download"), icon=ft.Icons.DOWNLOAD,
                                      on_click=lambda e: webbrowser.open(ZADIG_URL))], wrap=True)]))
        self.bluetooth_box = ft.Column([
            ft.Text(t("bluetooth_help"), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Row([self.adapter_select, ft.IconButton(ft.Icons.REFRESH, tooltip=t("adapter_refresh"),
                                                       on_click=self.on_adapter_scan)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.adapter_info, self.build_driver_box(), self.zadig_box,
            ft.Row([self.fields["vid"], self.fields["pid"], self.fields["transport"]], wrap=True)])
        self.adapters = []
        self.on_mode_change(None)
        return ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=14, controls=[
            ft.Text(t("mode"), size=16, weight=ft.FontWeight.BOLD), self.mode_group,
            self.dolphinbar_help, self.bluetooth_box, ft.Divider(),
            ft.Row([self.fields["dsu_host"], self.fields["dsu_port"], self.fields["api_port"]], wrap=True),
            ft.Row([self.switches["ir"], self.switches["motionplus"]]),
            ft.Row([ft.FilledButton(t("save"), icon=ft.Icons.SAVE, on_click=self.on_save)]),
        ])

    def refresh_status(self):
        if not self.cards or self.closing:
            return
        status = self.runtime.status
        self.status_dot.bgcolor = STATUS_COLORS[status]
        text = self.t(f"status_{status}")
        if self.runtime.error:
            text += f": {self.runtime.error}"
        mode = self.service_mode or self.config.mode
        self.status_text.value = f"{text}  ·  {self.t('mode_' + mode)}" if self.runtime.active else text
        running = status in ("running", "attached", "starting")
        self.toggle.content = self.t("stop") if running else self.t("start")
        self.toggle.icon = ft.Icons.STOP if running else ft.Icons.PLAY_ARROW
        self.toggle.disabled = status == "starting"
        self.pair_panel.visible = self.runtime.active and mode == "bluetooth"
        if not self.runtime.active:
            for slot in range(4):
                self.states.pop(slot, None)
                self.dirty.add(slot)
        self.page.update()

    def render(self):
        for slot in sorted(self.dirty):
            self.cards[slot].render(self.states.get(slot))
        self.dirty.clear()
        if self.logs.version != self.log_version:
            self.log_version = self.logs.version
            self.log_view.controls = [ft.Text(line, size=11, selectable=True, font_family="Consolas")
                                      for line in list(self.logs.lines)[-200:]]

    async def refresh_loop(self):
        while not self.closing:
            await asyncio.sleep(1 / REFRESH_HZ)
            if self.closing:
                return
            if self.dirty or self.logs.version != self.log_version:
                self.render()
                try:
                    self.page.update()
                except RuntimeError:  # window/session already destroyed
                    return

    # -- handlers ----------------------------------------------------------
    async def on_toggle(self, e):
        if self.runtime.status in ("running", "attached"):
            await self.runtime.stop()
            self.service_mode = None
        else:
            self.config = self.load_config()
            await self.runtime.start(self.config)
            if self.runtime.active:
                try:
                    self.service_mode = (await self.runtime.snapshot()).get("mode", self.config.mode)
                except Exception:
                    self.service_mode = self.config.mode
        self.refresh_status()

    def on_mode_change(self, e):
        bluetooth = self.mode_group.value == "bluetooth"
        self.bluetooth_box.visible = bluetooth
        self.dolphinbar_help.visible = not bluetooth
        if bluetooth:
            self.page.run_task(self.scan_adapters)
        if e is not None:
            self.page.update()

    async def scan_adapters(self):
        try:
            adapters = await asyncio.to_thread(list_adapters)
        except Exception as exc:
            log.warning("Adapter scan failed: %s", exc)
            adapters = []
        if self.closing:
            return
        self.adapters = adapters
        usable = [a for a in adapters if a.usable]
        try:
            vid, pid = parse_int(self.fields["vid"].value), parse_int(self.fields["pid"].value)
            current = f"{vid:04x}:{pid:04x}" if vid is not None and pid is not None else None
        except ValueError:
            current = None
        self.adapter_select.options = [ft.DropdownOption(a.key, a.label()) for a in usable]
        self.adapter_select.value = current if any(a.key == current for a in usable) else None
        notes = []
        windows = [a.name for a in adapters if a.driver == "BTHUSB"]
        broken = [a.label() for a in adapters if a.driver not in ("BTHUSB",) and a.bluetooth and not a.ok]
        if windows:
            notes.append(self.t("adapter_convertible", names=", ".join(windows)))
        if broken:
            notes.append(self.t("adapter_broken", names=", ".join(broken)))
        self.adapter_info.value = "\n".join(notes)
        self.adapter_info.visible = bool(notes)
        self.zadig_box.visible = not usable
        self.refresh_driver_box()
        self.page.update()

    async def on_adapter_scan(self, e):
        await self.scan_adapters()

    def on_adapter_select(self, e):
        adapter = next((a for a in self.adapters if a.key == e.control.value), None)
        if adapter:
            self.fields["vid"].value = f"0x{adapter.vid:04x}"
            self.fields["pid"].value = f"0x{adapter.pid:04x}"
            self.fields["transport"].value = ""
            self.page.update()

    # -- adapter driver switching (no Zadig once a libusbK package exists) ---
    def build_driver_box(self):
        t = self.t
        self.driver_select = ft.Dropdown(label=t("driver_adapter"), width=520, options=[],
                                         on_select=lambda e: self.refresh_driver_buttons())
        self.driver_to_direct = ft.FilledButton(t("driver_to_libusbk"), icon=ft.Icons.SPORTS_ESPORTS,
                                                on_click=lambda e: self.confirm_switch("direct"))
        self.driver_to_windows = ft.OutlinedButton(t("driver_to_windows"), icon=ft.Icons.BLUETOOTH,
                                                   on_click=lambda e: self.confirm_switch("bluetooth"))
        self.driver_status = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        return ft.Container(padding=12, border_radius=8, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                            content=ft.Column([ft.Text(t("driver_title"), weight=ft.FontWeight.W_600),
                                               self.driver_select,
                                               ft.Row([self.driver_to_direct, self.driver_to_windows], wrap=True),
                                               self.driver_status], spacing=8))

    def refresh_driver_box(self):
        bluetooth = [a for a in self.adapters if a.bluetooth]
        current = self.driver_select.value
        self.driver_select.options = [ft.DropdownOption(a.key, a.label()) for a in bluetooth]
        keys = [a.key for a in bluetooth]
        self.driver_select.value = current if current in keys else (keys[0] if keys else None)
        self.refresh_driver_buttons()

    def selected_driver_adapter(self):
        return next((a for a in self.adapters if a.key == self.driver_select.value), None)

    def refresh_driver_buttons(self):
        adapter = self.selected_driver_adapter()
        if adapter is None:
            self.driver_to_direct.disabled = self.driver_to_windows.disabled = True
            self.driver_status.value = self.t("driver_none")
        else:
            packages = packages_for(adapter.vid, adapter.pid)
            has_direct = choose(packages, "direct") is not None
            on_direct = adapter.driver in ("libusbK", "WinUSB")
            self.driver_to_direct.disabled = on_direct or not has_direct
            self.driver_to_windows.disabled = not on_direct
            self.driver_status.value = self.t("driver_current", driver=adapter.driver) + (
                "" if has_direct or on_direct else "  " + self.t("driver_needs_zadig"))
        self.page.update()

    def confirm_switch(self, target):
        adapter = self.selected_driver_adapter()
        if adapter is None:
            return
        if self.runtime.active and (self.service_mode or self.config.mode) == "bluetooth":
            self.notify(self.t("driver_stop_service"))
            return
        t = self.t
        text = t("driver_confirm_libusbk" if target == "direct" else "driver_confirm_windows", name=adapter.name)
        async def go(e):
            self.page.pop_dialog()
            await self.switch_driver(adapter, target)
        self.page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text(t("driver_title")), content=ft.Text(text),
            actions=[ft.TextButton(t("close"), on_click=lambda e: self.page.pop_dialog()),
                     ft.FilledButton(t("driver_continue"), on_click=go)]))

    async def switch_driver(self, adapter, target):
        self.driver_to_direct.disabled = self.driver_to_windows.disabled = True
        self.driver_status.value = self.t("driver_working")
        self.page.update()
        result = await asyncio.to_thread(switch_adapter, adapter.vid, adapter.pid, target)
        if result.get("ok"):
            log.info("Adapter %s switched to %s with %s", adapter.key, target, result.get("package"))
            self.notify(self.t("driver_done_reboot" if result.get("reboot") else "driver_done"))
            await asyncio.sleep(3)  # let Windows re-enumerate the adapter
        else:
            log.warning("Driver switch failed: %s", result)
            self.notify(self.t("failed", error=result.get("message") or result.get("error")))
        await self.scan_adapters()

    def on_zadig_open(self, e):
        zadig = find_zadig()
        if zadig is None:
            webbrowser.open(ZADIG_URL)
            return
        try:
            os.startfile(zadig)  # Windows asks for administrator rights
        except OSError as exc:
            self.notify(self.t("failed", error=exc))

    async def update_slot_options(self, slot, change):
        """Save one slot's options and apply them to the running service at once."""
        slots = list(self.config.slots)
        slots[slot] = replace(slots[slot], **change)
        try:
            config = replace(self.load_config(), slots=tuple(slots))
            save_config(config, self.config_path)
        except (OSError, ValueError) as exc:
            self.notify(self.t("failed", error=exc))
            return
        self.config = config
        if self.runtime.active:
            await self.command("slot_options", slot=slot, **change)

    async def on_save(self, e):
        form = {key: field.value for key, field in self.fields.items()}
        form.update({key: switch.value for key, switch in self.switches.items()})
        form["mode"] = self.mode_group.value
        try:
            config = config_from_form(self.load_config(), form)
            save_config(config, self.config_path)
        except ValueError as exc:
            self.notify(self.t("invalid", field=exc))
            return
        self.config = config
        self.notify(self.t("saved", path=self.config_path))

    async def on_pair(self, e):
        try:
            seconds = float(self.pair_seconds.value)
        except ValueError:
            self.notify(self.t("invalid", field=self.t("pair_seconds")))
            return
        args = {"seconds": seconds, "mode": self.pair_mode.value}
        if self.pair_address.value.strip():
            args["address"] = self.pair_address.value.strip()
        if await self.command("pair", **args) is not None:
            self.notify(self.t("pair_started"))

    def on_language(self, e):
        self.prefs["language"] = e.control.value
        self.save_prefs()
        self.t = Translator(e.control.value)
        self.build()

    def on_clear_log(self, e):
        self.logs.lines.clear()
        self.logs.version += 1

    async def on_window_event(self, e):
        if e.type == ft.WindowEventType.CLOSE:
            self.closing = True
            await self.runtime.stop()  # release the DolphinBar/adapter before exiting
            logging.getLogger().removeHandler(self.logs)
            await self.page.window.destroy()


def run(config_path="config.local.json"):
    config_path = Path(config_path)

    async def main(page: ft.Page):
        page.window.width, page.window.height = 1180, 860
        page.window.min_width, page.window.min_height = 760, 560
        page.padding = 16
        controller = Controller(page, config_path, config_path.parent / ".wiichinahook" / "gui.json")
        page.window.prevent_close = True
        page.window.on_event = controller.on_window_event
        controller.build()
        page.run_task(controller.refresh_loop)

    ft.run(main, assets_dir=str(Path(__file__).parent / "assets"))  # calibration GIFs


def main():
    import argparse
    parser = argparse.ArgumentParser(prog="wiichinahook-gui")
    parser.add_argument("--config", default="config.local.json", help="path to JSON config")
    run(parser.parse_args().config)


if __name__ == "__main__":
    main()
