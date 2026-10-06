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
GUIDES_DIR = Path(__file__).resolve().parents[3] / "docs" / "guides"
MODE_TYPES = ("empty", "xbox", "dsu")


def load_guide(name, language, directory=GUIDES_DIR):
    """Guide markdown in the UI language (English fallback), or None outside the repo."""
    for candidate in (f"{name}.{language}.md", f"{name}.md"):
        path = directory / candidate
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
        self.mode_badge = ft.Text("", size=16, weight=ft.FontWeight.BOLD)
        self.mode_buttons = [ft.OutlinedButton(f"{t('gp_mode')} {n}", data=n, on_click=self.on_activate)
                             for n in range(1, 5)]
        self.modifier = ft.Dropdown(label=t("gp_modifier"), value=self.config["modifier"], width=220, dense=True,
                                    options=[ft.DropdownOption(m, source_label(m, t)) for m in MODIFIERS],
                                    on_select=self.on_modifier)
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
        self.edit_select = ft.Dropdown(label=t("gp_edit_mode"), value=str(self.editing), width=160, dense=True,
                                       options=[ft.DropdownOption(str(n), f"{t('gp_mode')} {n}") for n in range(1, 5)],
                                       on_select=self.on_edit_select)
        self.editor = ft.Column(spacing=10)
        self.render_editor()
        self.refresh_header()
        return ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=14, controls=[
            ft.Text(t("gp_intro"), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Row([ft.Text(t("gp_active"), size=14), self.mode_badge], spacing=10),
            ft.Row(self.mode_buttons, wrap=True),
            ft.Row([self.modifier, ft.Text(t("gp_modifier_hint"), size=12, color=ft.Colors.ON_SURFACE_VARIANT)],
                   wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.warnings,
            ft.Row([ft.Container(self.xbox_canvas, width=xbox_view.WIDTH, height=xbox_view.HEIGHT,
                                 border_radius=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST),
                    ft.Column([self.view_select, self.view_hint], spacing=8, width=260)],
                   wrap=True, vertical_alignment=ft.CrossAxisAlignment.START, spacing=16),
            ft.Row([ft.Icon(ft.Icons.VIBRATION, size=16), ft.Text(t("gp_shake_live"), size=12,
                                                                    weight=ft.FontWeight.W_600), self.shake_log],
                   wrap=True),
            ft.Divider(),
            self.edit_select,
            self.editor,
        ])

    def render_editor(self):
        t = self.t
        template = self.config["modes"][self.editing - 1]
        kind = mode_type(template) or "empty"
        self.mode_type = ft.Dropdown(label=t("gp_type"), value=kind, width=260, dense=True,
                                     options=[ft.DropdownOption(k, t(f"gp_type_{k}")) for k in MODE_TYPES],
                                     on_select=self.on_type)
        controls = [self.mode_type]
        if kind == "dsu":
            controls += self.dsu_panel(template)
        elif kind == "xbox":
            self.name = ft.TextField(label=t("gp_name"), value=template["name"], width=240, dense=True)
            self.dropdowns = {}
            rows = []
            sources = button_sources()
            self.combos = {}
            for target in BUTTON_TARGETS:
                current = template["buttons"][target]
                members = current.split("+") if current else []
                # Main input plus up to two more held together (buttons and/or shakes).
                selectors = []
                for index in range(MAX_CHORD):
                    value = members[index] if index < len(members) else None
                    options = sources if value in sources else [*sources, value]  # keep old directional shakes
                    selectors.append(ft.Dropdown(
                        value=value or NONE, width=230 if index == 0 else 200, dense=True,
                        label=None if index == 0 else "+",
                        options=[ft.DropdownOption(s or NONE, source_label(s, t)) for s in options]))
                self.combos[target] = selectors
                rows.append(ft.Row([ft.Text(TARGET_LABELS.get(target, target), width=90), *selectors],
                                   wrap=True, spacing=6))
            for target in STICK_TARGETS:
                dropdown = ft.Dropdown(value=template["sticks"][target] or NONE, width=260, dense=True,
                                       options=[ft.DropdownOption(s or NONE, source_label(s, t))
                                                for s in (None, *STICK_SOURCES)])
                self.dropdowns[target] = dropdown
                rows.append(ft.Row([ft.Text(t("gp_left_stick" if target == "LEFT_STICK" else "gp_right_stick"),
                                            width=110), dropdown]))
            self.numbers = {key: ft.TextField(label=t(f"gp_{key}"), value=str(template[key]), width=200, dense=True)
                            for key in ("gyro_full_dps", "gyro_full_dps_y", "ir_range", "deadzone")}
            self.shake_fields = {
                device: [ft.TextField(label=f"{t('gp_shake_' + device)} {t('gp_axis_' + axis)}",
                                      value=str(template["shake_" + device][i]), width=210, dense=True)
                         for i, axis in enumerate(SHAKE_AXES)]
                for device in ("wm", "nc")}
            controls += [self.name,
                         ft.Text(t("gp_combo_hint"), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                         ft.Column(rows, spacing=6),
                         ft.Row(list(self.numbers.values()), wrap=True),
                         ft.Text(t("gp_shake_title"), weight=ft.FontWeight.W_600),
                         ft.Text(t("gp_shake_hint"), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                         ft.Row(self.shake_fields["wm"], wrap=True),
                         ft.Row(self.shake_fields["nc"], wrap=True),
                         ft.Row([ft.FilledButton(t("gp_save"), icon=ft.Icons.SAVE, on_click=self.on_save),
                                 ft.TextButton(t("gp_reset"), icon=ft.Icons.RESTART_ALT, on_click=self.on_reset)])]
        self.editor.controls = controls

    def dsu_panel(self, template):
        t = self.t
        dsu = self.controller.config.dsu
        self.name = ft.TextField(label=t("gp_name"), value=template["name"], width=240, dense=True)
        table = ft.Column(spacing=2, controls=[
            ft.Row([ft.Text(source, width=170, size=12), ft.Text(target, size=12, selectable=True,
                                                                  font_family="Consolas")])
            for source, target in DSU_BUTTONS])
        self.guide = ft.Markdown("", selectable=True, auto_follow_links=True,
                                 extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
        self.guide_select = ft.Dropdown(label=t("gp_dsu_guide"), value="dolphin", width=200, dense=True,
                                        options=[ft.DropdownOption(k, v) for k, v in GUIDES.items()],
                                        on_select=self.on_guide)
        self.show_guide("dolphin")
        return [ft.Text(t("gp_dsu_intro", host=dsu.host, port=dsu.port), size=12),
                ft.Row([self.name, ft.FilledButton(t("gp_save"), icon=ft.Icons.SAVE, on_click=self.on_save)],
                       wrap=True),
                ft.Text(t("gp_dsu_table"), weight=ft.FontWeight.W_600),
                table,
                ft.Text(t("gp_dsu_limits"), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Divider(),
                self.guide_select,
                ft.Container(self.guide, padding=12, border_radius=8,
                             bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST)]

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
        if mode_type(template) == "dsu":
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
        fresh = {"xbox": GAME_TEMPLATE, "dsu": DSU_TEMPLATE}.get(e.control.value)
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
        config["modes"][self.editing - 1] = copy.deepcopy(GAME_TEMPLATE)
        if await self.apply(config):
            self.render_editor()
            self.controller.page.update()
