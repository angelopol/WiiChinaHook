"""Small layout helpers shared by the tabs: titled section cards, hints and the
two-column responsive layout (one column below ~1000 px)."""
from __future__ import annotations

import flet as ft

TWO_COLUMNS = {"xs": 12, "lg": 6}


def hint(text, size=12):
    return ft.Text(text, size=size, color=ft.Colors.ON_SURFACE_VARIANT)


def section(title, icon=None, controls=(), *, subtitle=None, trailing=None, spacing=10, col=None):
    """A titled card: icon + title (+ a control on the right), an optional hint line
    and its content."""
    head = [ft.Icon(icon, size=18, color=ft.Colors.PRIMARY)] if icon else []
    head.append(ft.Text(title, size=15, weight=ft.FontWeight.W_600))
    if trailing is not None:
        head += [ft.Container(expand=True), trailing]
    body = [ft.Row(head, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if subtitle:
        body.append(hint(subtitle))
    body += list(controls)
    return ft.Container(
        col=col, padding=16, border_radius=14,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        content=ft.Column(body, spacing=spacing, tight=True))


def columns(left, right, spacing=16):
    """Two responsive columns of sections."""
    return ft.ResponsiveRow(
        spacing=spacing, run_spacing=spacing, vertical_alignment=ft.CrossAxisAlignment.START,
        controls=[ft.Column(left, col=TWO_COLUMNS, spacing=spacing),
                  ft.Column(right, col=TWO_COLUMNS, spacing=spacing)])


def number(label, value, width=None, suffix=None, tooltip=None):
    return ft.TextField(label=label, value=str(value), dense=True, width=width, expand=width is None,
                        suffix=suffix, tooltip=tooltip, keyboard_type=ft.KeyboardType.NUMBER)
