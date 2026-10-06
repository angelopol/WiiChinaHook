"""Notification-area (tray) icon: left click opens the window; the right-click menu
opens it, switches the mode and exits.

pystray runs its own Win32 message loop in a daemon thread; every callback is handed
to the GUI's event loop through `page.run_task`, which is thread-safe.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)
ICON = Path(__file__).parent / "assets" / "icon.png"


class Tray:
    def __init__(self, page, t, *, on_open, on_mode, on_exit, current_mode):
        """`on_open`, `on_exit` and `on_mode(n)` are coroutine functions; `current_mode()`
        returns the active mode number (read from the tray thread, so keep it cheap)."""
        self.page, self.t = page, t
        self.on_open, self.on_mode, self.on_exit = on_open, on_mode, on_exit
        self.current_mode = current_mode
        self.icon = None

    @property
    def available(self):
        return self.icon is not None

    def start(self):
        try:
            import pystray
            from PIL import Image
        except ImportError as exc:  # optional: the GUI still works without a tray icon
            log.warning("Tray icon unavailable (%s); install the gui extra", exc)
            return False
        image = Image.open(ICON)
        image.load()
        self.icon = pystray.Icon("WiiChinaHook", image, self.title(), self.menu())
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
        return True

    def title(self):
        return f"WiiChinaHook — {self.t('gp_mode')} {self.current_mode()}"

    def menu(self):
        import pystray
        item = pystray.MenuItem
        modes = [item(f"{self.t('gp_mode')} {n}", self._handler(self.on_mode, n),
                      checked=lambda _, n=n: self.current_mode() == n, radio=True) for n in range(1, 5)]
        return pystray.Menu(
            item(self.t("tray_open"), self._handler(self.on_open), default=True),  # also the left click
            item(self.t("tray_mode"), pystray.Menu(*modes)),
            pystray.Menu.SEPARATOR,
            item(self.t("tray_exit"), self._handler(self.on_exit)))

    def _handler(self, coroutine, *args):
        def run(icon, item):
            self.page.run_task(coroutine, *args)
        return run

    def refresh(self, t=None):
        """Language or mode changed: rebuild the menu and the tooltip."""
        if not self.icon:
            return
        if t is not None:
            self.t = t
            self.icon.menu = self.menu()
        self.icon.title = self.title()
        self.icon.update_menu()

    def stop(self):
        if self.icon:
            icon, self.icon = self.icon, None
            try:
                icon.stop()
            except Exception as exc:  # already gone with the process
                log.debug("Tray stop: %s", exc)
