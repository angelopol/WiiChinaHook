"""'Xbox controller' tab: active mode, modifier and per-mode Wiimote -> Xbox mapping
(or the DSU mode, with its button table and the emulator guides)."""
from __future__ import annotations

import copy
from pathlib import Path

import flet as ft
import flet.canvas as cv

from ..gamepad.mapping import (AXIS_GESTURES, BUTTON_SOURCES, BUTTON_TARGETS, DSU_TEMPLATE, GAME_TEMPLATE, MAX_CHORD,
                               MODIFIERS, SHAKE_AXES, STICK_SOURCES, STICK_TARGETS, mode_type, validate_config)
from . import xbox_view
from .widgets import columns, hint, number, section
from .pc_editor import PcEditor
from ..gamepad.pc import PC_TEMPLATE

NONE = "none"  # dropdown key for "unassigned"
TARGET_LABELS = {"DPAD_UP": "D-pad ↑", "DPAD_DOWN": "D-pad ↓", "DPAD_LEFT": "D-pad ←", "DPAD_RIGHT": "D-pad →",
                 "LEFT_STICK": "Left stick", "RIGHT_STICK": "Right stick"}
BUTTON_NAMES = {"up": "↑", "down": "↓", "left": "←", "right": "→", "a": "A", "b": "B", "minus": "−",
                "plus": "+", "home": "Home", "1": "1", "2": "2", "c": "C", "z": "Z"}

# What each input is called on the DSU side (Dolphin/Cemu binding names); see dsu_mapping.py.
DSU_BUTTONS = [("Wiimote A", "Circle"), ("Wiimote B", "Triangle"), ("Wiimote 1", "Square"),
               ("Wiimote 2", "Cross"), ("Wiimote −", "Share"), ("Wiimote +", "Options"), ("Wiimote Home", "PS"),
               ("Wiimote ↑ ↓ ← →", "Pad N / Pad S / Pad W / Pad E"), ("Nunchuk C", "L1"), ("Nunchuk Z", "L2"),
               ("Nunchuk stick", "Left X± / Left Y±"),
               ("Accelerometer", "Accel Up/Down/Left/Right/Forward/Backward"),
               ("MotionPlus", "Gyro Pitch Up/Down, Roll Left/Right, Yaw Left/Right")]
GUIDES = {"dolphin": "Dolphin", "cemu": "Cemu"}
# The release executable bundles docs/guides as gui/guides; a checkout reads the repo's.
GUIDE_DIRS = (Path(__file__).resolve().parent / "guides", Path(__file__).resolve().parents[3] / "docs" / "guides")
MODE_TYPES = ("empty", "xbox", "dsu", "pc")
NUMBER_FIELDS = ("chord_window_ms", "deadzone", "angle_full_deg", "angle_full_deg_y", "gyro_deadzone", "gyro_full_dps",
                 "gyro_full_dps_y", "ir_range")


def load_guide(name, language, directories=GUIDE_DIRS):
    """Guide markdown in the UI language (English fallback), or None if not shipped."""
    for directory in directories:
        for candidate in (f"{name}.{language}.md", f"{name}.md"):
            path = Path(directory) / candidate
            if path.is_file():
                return path.read_text(encoding="utf-8")
    return None


def source_label(source, t):
    if source is None:
        return t("gp_none")
    if "+" in source:
        return " + ".join(source_label(m, t) for m in source.split("+"))
    if source in STICK_SOURCES:
        return t(f"gp_src_{source}")
    device, rest = source.split("_", 1)
    name = "Wiimote" if device == "wm" else "Nunchuk"
    if rest.startswith("shake_"):
        kind = rest[6:]
        return f"{t('gp_shake')} {name} {t(('gp_axis_' if kind in SHAKE_AXES else 'gp_dir_') + kind)}"
    return f"{name} {BUTTON_NAMES[rest]}"


def button_sources():
    """Single inputs offered in each of a control's selectors (combined with '+').
    Shakes are per axis: their direction cannot be told apart reliably."""
    return [None, *BUTTON_SOURCES, *AXIS_GESTURES]


class GamepadTab:
    def __init__(self, controller):
        self.controller = controller
        self.t = controller.t
        self.config = copy.deepcopy(controller.config.gamepad)
        self.editing = self.config["mode"]
        self.status = None

    # -- building ----------------------------------------------------------------
    def build(self):
        t = self.t
        self.mode_badge = ft.Text("", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY)
        self.mode_buttons = [ft.OutlinedButton(f"{t('gp_mode')} {n}", data=n, on_click=self.on_activate)
                             for n in range(1, 5)]
        self.modifier = ft.Dropdown(label=t("gp_modifier"), value=self.config["modifier"], width=220, dense=True,
                                    options=[ft.DropdownOption(m, source_label(m, t)) for m in MODIFIERS],
                                    on_select=self.on_modifier)
        self.startup_mode = ft.Dropdown(
            label=t("gp_startup_mode"), width=220, dense=True,
            value=str(self.config.get("startup_mode") or "last"),
            options=[ft.DropdownOption("last", t("gp_startup_last")),
                     *[ft.DropdownOption(str(n), f"{t('gp_mode')} {n}") for n in range(1, 5)]],
            on_select=self.on_startup_mode)
        self.warnings = ft.Column(spacing=2)
        self.shake_log = ft.Text(self.t("gp_shake_live_idle"), size=12)
        self.shake_seq = None
        self.outputs = {}
        self.view_slot = 0
        self.xbox_canvas = cv.Canvas(shapes=xbox_view.shapes(None), width=xbox_view.WIDTH,
                                     height=xbox_view.HEIGHT)
        self.view_select = ft.Dropdown(label=t("gp_view"), value="0", width=150, dense=True,
                                       options=[ft.DropdownOption(str(n), t("slot", n=n)) for n in range(4)],
                                       on_select=self.on_view_select)
        self.view_hint = ft.Text(t("gp_view_idle"), size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.edit_select = ft.Dropdown(label=t("gp_edit_mode"), value=str(self.editing), width=150, dense=True,
                                       options=[ft.DropdownOption(str(n), f"{t('gp_mode')} {n}") for n in range(1, 5)],
                                       on_select=self.on_edit_select)
        self.editor = ft.Column(spacing=16)
        self.render_editor()
        self.refresh_header()
        active = section(t("gp_active_title"), ft.Icons.SPORTS_ESPORTS, subtitle=t("gp_intro"), controls=[
            ft.Row([ft.Text(t("gp_active"), size=14), self.mode_badge], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row(self.mode_buttons, wrap=True, spacing=8),
            ft.Row([self.modifier, self.startup_mode], wrap=True, spacing=12),
            hint(t("gp_modifier_hint")),
            hint(t("gp_startup_hint")),
            self.warnings])
        live = section(t("gp_live_title"), ft.Icons.VIDEOGAME_ASSET, controls=[
            ft.Row([ft.Container(self.xbox_canvas, width=xbox_view.WIDTH, height=xbox_view.HEIGHT,
                                 border_radius=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST),
                    ft.Column([self.view_select, self.view_hint], spacing=8, width=200)],
                   wrap=True, vertical_alignment=ft.CrossAxisAlignment.START, spacing=16),
            ft.Row([ft.Icon(ft.Icons.VIBRATION, size=16),
                    ft.Text(t("gp_shake_live"), size=12, weight=ft.FontWeight.W_600), self.shake_log], wrap=True)])
        return ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=16, controls=[
            columns([active], [live]),
            ft.Row([ft.Icon(ft.Icons.EDIT, color=ft.Colors.PRIMARY),
                    ft.Text(t("gp_edit_title"), size=17, weight=ft.FontWeight.BOLD), self.edit_select],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.editor,
        ])

    def binding_row(self, target, template, sources):
        """Label + main input + up to two more held together (buttons and/or shakes)."""
        t = self.t
        current = template["buttons"][target]
        members = current.split("+") if current else []
        selectors = []
        for index in range(MAX_CHORD):
            value = members[index] if index < len(members) else None
            options = sources if value in sources else [*sources, value]  # keep old directional shakes
            selectors.append(ft.Dropdown(
                value=value or NONE, dense=True, expand=4 if index == 0 else 3,
                label=None if index == 0 else "+",
                options=[ft.DropdownOption(s or NONE, source_label(s, t)) for s in options]))
        self.combos[target] = selectors
        return ft.Row([ft.Text(TARGET_LABELS.get(target, target), width=76, weight=ft.FontWeight.W_500),
                       *selectors], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def render_editor(self):
        t = self.t
        template = self.config["modes"][self.editing - 1]
        kind = mode_type(template) or "empty"
        self.mode_type = ft.Dropdown(label=t("gp_type"), value=kind, width=240, dense=True,
                                     options=[ft.DropdownOption(k, t(f"gp_type_{k}")) for k in MODE_TYPES],
                                     on_select=self.on_type)
        if kind == "dsu":
            self.editor.controls = self.dsu_panel(template)
            return
        if kind == "pc":
            self.name = ft.TextField(label=t("gp_name"), value=template["name"], width=220, dense=True)
            self.pc_editor = PcEditor(t, source_label)
            header = ft.Row([self.mode_type, self.name, ft.Container(expand=True),
                             ft.FilledButton(t("gp_save"), icon=ft.Icons.SAVE, on_click=self.on_save),
                             ft.TextButton(t("pc_reset"), icon=ft.Icons.RESTART_ALT, on_click=self.on_reset)],
                            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            self.editor.controls = self.pc_editor.build(template, header)
            return
        if kind != "xbox":
            self.editor.controls = [ft.Row([self.mode_type]), hint(t("gp_empty_hint"))]
            return
        self.name = ft.TextField(label=t("gp_name"), value=template["name"], width=220, dense=True)
        header = ft.Row([self.mode_type, self.name, ft.Container(expand=True),
                         ft.FilledButton(t("gp_save"), icon=ft.Icons.SAVE, on_click=self.on_save),
                         ft.TextButton(t("gp_reset"), icon=ft.Icons.RESTART_ALT, on_click=self.on_reset)],
                        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        sources = button_sources()
        self.combos, self.dropdowns = {}, {}
        rows = lambda targets: [self.binding_row(target, template, sources) for target in targets]
        for target in STICK_TARGETS:
            self.dropdowns[target] = ft.Dropdown(
                value=template["sticks"][target] or NONE, dense=True, expand=True,
                label=t("gp_left_stick" if target == "LEFT_STICK" else "gp_right_stick"),
                options=[ft.DropdownOption(s or NONE, source_label(s, t)) for s in (None, *STICK_SOURCES)])
        self.numbers = {key: number(t(f"gp_{key}"), template[key]) for key in NUMBER_FIELDS}
        n = self.numbers
        self.shake_fields = {device: [number(t("gp_axis_" + axis), template["shake_" + device][i], suffix="g")
                                      for i, axis in enumerate(SHAKE_AXES)]
                             for device in ("wm", "nc")}
        left = [
            section(t("gp_cat_combos"), ft.Icons.JOIN_INNER, [ft.Row([self.numbers["chord_window_ms"]])],
                    subtitle=t("gp_combo_hint")),
            section(t("gp_cat_face"), ft.Icons.RADIO_BUTTON_CHECKED, rows(("A", "B", "X", "Y"))),
            section(t("gp_cat_shoulders"), ft.Icons.KEYBOARD_DOUBLE_ARROW_UP, rows(("LB", "RB", "LT", "RT"))),
            section(t("gp_cat_dpad"), ft.Icons.GAMEPAD,
                    rows(("DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"))),
            section(t("gp_cat_menu"), ft.Icons.MENU, rows(("START", "BACK", "GUIDE", "L3", "R3"))),
        ]
        right = [
            section(t("gp_cat_sticks"), ft.Icons.OPEN_WITH, [
                ft.Row([self.dropdowns["LEFT_STICK"]]), ft.Row([self.dropdowns["RIGHT_STICK"]]),
                ft.Row([n["deadzone"]])], subtitle=t("gp_sticks_hint")),
            section(t("gp_cat_aim"), ft.Icons.MY_LOCATION, [
                ft.Row([n["angle_full_deg"], n["angle_full_deg_y"]]), ft.Row([n["gyro_deadzone"]])],
                subtitle=t("gp_aim_hint")),
            section(t("gp_cat_speed"), ft.Icons.SPEED, [ft.Row([n["gyro_full_dps"], n["gyro_full_dps_y"]])],
                    subtitle=t("gp_speed_hint")),
            section(t("gp_cat_ir"), ft.Icons.SENSORS, [ft.Row([n["ir_range"]])]),
            section(t("gp_shake_title"), ft.Icons.VIBRATION, [
                ft.Text(t("gp_shake_wm"), size=13, weight=ft.FontWeight.W_500), ft.Row(self.shake_fields["wm"]),
                ft.Text(t("gp_shake_nc"), size=13, weight=ft.FontWeight.W_500), ft.Row(self.shake_fields["nc"])],
                subtitle=t("gp_shake_hint")),
        ]
        self.editor.controls = [header, columns(left, right)]

    def dsu_panel(self, template):
        t = self.t
        dsu = self.controller.config.dsu
        self.name = ft.TextField(label=t("gp_name"), value=template["name"], width=220, dense=True)
        table = ft.Column(spacing=4, controls=[
            ft.Row([ft.Text(source, width=150, size=12),
                    ft.Text(target, size=12, selectable=True, font_family="Consolas", expand=True)])
            for source, target in DSU_BUTTONS])
        self.guide = ft.Markdown("", selectable=True, auto_follow_links=True,
                                 extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
        self.guide_select = ft.Dropdown(value="dolphin", width=160, dense=True,
                                        options=[ft.DropdownOption(k, v) for k, v in GUIDES.items()],
                                        on_select=self.on_guide)
        self.show_guide("dolphin")
        header = ft.Row([self.mode_type, self.name, ft.Container(expand=True),
                         ft.FilledButton(t("gp_save"), icon=ft.Icons.SAVE, on_click=self.on_save)],
                        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        inputs = section(t("gp_dsu_table"), ft.Icons.TABLE_ROWS, [table, hint(t("gp_dsu_limits"))],
                         subtitle=t("gp_dsu_intro", host=dsu.host, port=dsu.port))
        guide = section(t("gp_dsu_guide"), ft.Icons.MENU_BOOK, [self.guide], trailing=self.guide_select)
        return [header, columns([inputs, self.extra_servers(template, dsu)], [guide])]

    def extra_servers(self, template, dsu):
        """Switches of the Nunchuk-motion and IR-pointer DSU servers (dsu.py)."""
        t = self.t
        self.dsu_switches = {key: ft.Switch(label=t(f"gp_dsu_{key}"), value=template[key])
                             for key in ("nunchuk_server", "ir_server")}
        self.dsu_ir_range = number(t("gp_ir_range"), template["ir_range"], width=200)

        def server(key, port, binds):
            status = t("gp_dsu_port", port=port) if port else t("gp_dsu_port_off")
            return ft.Column([self.dsu_switches[key], hint(status),
                              ft.Text(binds, size=12, selectable=True, font_family="Consolas")], spacing=4)
        return section(t("gp_dsu_extra"), ft.Icons.HUB, [
            server("nunchuk_server", dsu.nunchuk_port, t("gp_dsu_nunchuk_binds")),
            server("ir_server", dsu.ir_port, t("gp_dsu_ir_binds")),
            self.dsu_ir_range], subtitle=t("gp_dsu_extra_hint"))

    def show_guide(self, name):
        text = load_guide(name, self.t.language)
        self.guide.value = text if text is not None else self.t("gp_dsu_guide_missing", name=f"docs/guides/{name}.md")

    def on_guide(self, e):
        self.show_guide(e.control.value)
        self.controller.page.update()

    def refresh_header(self):
        t = self.t
        active = self.config["mode"]
        template = self.config["modes"][active - 1]
        self.mode_badge.value = f"{t('gp_mode')} {active} — {template['name'] if template else t('gp_empty')}"
        for button in self.mode_buttons:
            button.style = ft.ButtonStyle(bgcolor=ft.Colors.PRIMARY_CONTAINER) if button.data == active else None
        lines = []
        status = self.status or {}
        if status.get("error"):
            lines.append(ft.Text(t("gp_vigem_error", error=status["error"]), color=ft.Colors.ERROR, size=12))
        for slot, problems in sorted((status.get("problems") or {}).items()):
            lines.append(ft.Text(t("gp_unavailable", n=slot, items="; ".join(problems)),
                                 color=ft.Colors.AMBER, size=12))
        self.warnings.controls = lines

    # -- events ------------------------------------------------------------------
    def on_status(self, status):
        """Gamepad event from the service (e.g. a mode switched with B + arrow)."""
        self.status = status
        self.config["mode"] = status["mode"]
        shakes = status.get("shakes") or {}
        if shakes.get("seq") and shakes["seq"] != self.shake_seq:
            self.shake_seq = shakes["seq"]
            parts = []
            for slot, events in sorted(shakes.get("by_slot", {}).items()):
                for event in events:
                    device = "Wiimote" if event["device"] == "wm" else "Nunchuk"
                    parts.append(f"{self.t('slot', n=slot)}: {device} {self.t('gp_axis_' + event['axis'])} "
                                 f"{event['g']:.1f} g")
            self.shake_log.value = "   ".join(parts[-4:])
        self.refresh_header()
        self.draw_xbox()

    def on_xbox(self, outputs):
        """Live Xbox output of each slot from the service (only changes arrive)."""
        self.outputs = dict(outputs)
        self.draw_xbox()

    def draw_xbox(self):
        output = self.outputs.get(self.view_slot)
        self.xbox_canvas.shapes = xbox_view.shapes(output)
        if output and output.get("active"):
            self.view_hint.value = self.t("gp_view_live")
        elif mode_type(self.config["modes"][self.config["mode"] - 1]) == "dsu":
            self.view_hint.value = self.t("gp_view_dsu")
        elif mode_type(self.config["modes"][self.config["mode"] - 1]) == "pc":
            self.view_hint.value = self.t("gp_view_pc")
        else:
            self.view_hint.value = self.t("gp_view_idle")

    def on_view_select(self, e):
        self.view_slot = int(e.control.value)
        self.draw_xbox()
        self.controller.page.update()

    def collect(self):
        template = self.config["modes"][self.editing - 1]
        if template is None:
            return None
        result = copy.deepcopy(template)
        result["name"] = self.name.value
        if mode_type(template) == "pc":
            result = self.pc_editor.collect(template)
            result["name"] = self.name.value
            return result
        if mode_type(template) == "dsu":
            for key, switch in self.dsu_switches.items():
                result[key] = bool(switch.value)
            try:
                result["ir_range"] = float(self.dsu_ir_range.value)
            except ValueError:
                raise ValueError("ir_range") from None
            return result
        for target, selectors in self.combos.items():
            members = []
            for selector in selectors:
                value = selector.value
                if value not in (None, "", NONE) and value not in members:
                    members.append(value)
            result["buttons"][target] = "+".join(members) or None
        for target, dropdown in self.dropdowns.items():
            value = None if dropdown.value in (None, "", NONE) else dropdown.value
            result["sticks"][target] = value
        for key, field in self.numbers.items():
            try:
                result[key] = float(field.value)
            except ValueError:
                raise ValueError(key) from None
        for device, fields in self.shake_fields.items():
            try:
                result["shake_" + device] = [float(f.value) for f in fields]
            except ValueError:
                raise ValueError("shake_" + device) from None
        return result

    async def apply(self, config):
        try:
            config = validate_config(config)
        except ValueError as exc:
            self.controller.notify(self.t("invalid", field=exc))
            return False
        self.config = config
        await self.controller.update_gamepad(config)
        self.refresh_header()
        self.controller.page.update()
        return True

    async def on_activate(self, e):
        config = copy.deepcopy(self.config)
        config["mode"] = e.control.data
        await self.apply(config)

    async def on_startup_mode(self, e):
        config = copy.deepcopy(self.config)
        config["startup_mode"] = None if e.control.value == "last" else int(e.control.value)
        await self.apply(config)

    async def on_modifier(self, e):
        config = copy.deepcopy(self.config)
        config["modifier"] = e.control.value
        await self.apply(config)

    def on_edit_select(self, e):
        self.editing = int(e.control.value)
        self.render_editor()
        self.controller.page.update()

    async def on_type(self, e):
        config = copy.deepcopy(self.config)
        fresh = {"xbox": GAME_TEMPLATE, "dsu": DSU_TEMPLATE, "pc": PC_TEMPLATE}.get(e.control.value)
        config["modes"][self.editing - 1] = copy.deepcopy(fresh) if fresh else None
        if await self.apply(config):
            self.render_editor()
            self.controller.page.update()

    async def on_save(self, e):
        config = copy.deepcopy(self.config)
        try:
            config["modes"][self.editing - 1] = self.collect()
        except ValueError as exc:
            self.controller.notify(self.t("invalid", field=exc))
            return
        if await self.apply(config):
            self.controller.notify(self.t("gp_saved", n=self.editing))

    async def on_reset(self, e):
        config = copy.deepcopy(self.config)
        kind = mode_type(config["modes"][self.editing - 1])
        config["modes"][self.editing - 1] = copy.deepcopy(PC_TEMPLATE if kind == "pc" else GAME_TEMPLATE)
        if await self.apply(config):
            self.render_editor()
            self.controller.page.update()
