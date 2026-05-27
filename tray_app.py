"""
Windows system tray icon and right-click menu.
Must run on the main thread (pystray requirement).
"""
import logging
import subprocess
import sys
import threading
from pathlib import Path
from PIL import Image, ImageDraw
import pystray
from config import LOG_PATH
from auth_manager import capture_session, list_accounts
import monitor

logger = logging.getLogger(__name__)
_HERE = Path(__file__).parent


def _make_icon(size=64) -> Image.Image:
    img = Image.new("RGB", (size, size), (0, 102, 204))
    d = ImageDraw.Draw(img)
    margin = size // 8
    d.ellipse([margin, margin, size - margin, size - margin], fill=(255, 255, 255))
    d.ellipse([margin * 2, margin * 2, size - margin * 2, size - margin * 2], fill=(0, 102, 204))
    return img


def _ask_account_name() -> str | None:
    """Ask the user to type an account name using a native Windows input dialog."""
    import ctypes
    # Windows doesn't have a built-in InputBox — use a small subprocess instead
    import subprocess, json, sys, tempfile, os
    script = (
        "import tkinter as tk\n"
        "from tkinter import simpledialog\n"
        "import json, sys\n"
        "root = tk.Tk(); root.withdraw()\n"
        "name = simpledialog.askstring('Add Account', 'Enter a label for this account\\n(e.g. wife, spouse, self):')\n"
        "print(json.dumps(name))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True
    )
    try:
        val = __import__("json").loads(result.stdout.strip())
        return val.strip().lower() if val else None
    except Exception:
        return None


class TrayApp:
    def __init__(self):
        self._icon: pystray.Icon | None = None

    def _build_menu(self):
        accounts = list_accounts()

        def _make_relogin(acct):
            def action(icon, item):
                self._relogin(acct)
            return action

        relogin_items = [
            pystray.MenuItem(f"Re-login ({a})", _make_relogin(a))
            for a in accounts
        ]

        return pystray.Menu(
            pystray.MenuItem("USCIS Monitor — Running", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Check Now", lambda icon, item: monitor.trigger_now()),
            pystray.MenuItem("Add Account…", lambda icon, item: self._add_account()),
            *relogin_items,
            pystray.MenuItem("View Log", lambda icon, item: self._show_log()),
            pystray.MenuItem("Settings", lambda icon, item: self._open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda icon, item: self._quit(icon)),
        )

    def _relogin(self, account: str):
        def run():
            ok = capture_session(account=account)
            _notify(
                f"Login {'Successful' if ok else 'Failed'}",
                f"Session for '{account}' {'saved.' if ok else 'could not be captured. Try again.'}",
            )
        threading.Thread(target=run, daemon=True).start()

    def _add_account(self):
        def run():
            name = _ask_account_name()
            if not name:
                return
            ok = capture_session(account=name)
            _notify(
                f"Account '{name}' {'Added' if ok else 'Failed'}",
                f"Session for '{name}' {'saved. Use /register IOE123 ' + name + ' in Telegram.' if ok else 'could not be captured.'}",
            )
            # Rebuild the menu so the new account appears
            if self._icon and ok:
                self._icon.menu = self._build_menu()
        threading.Thread(target=run, daemon=True).start()

    def _show_log(self):
        subprocess.Popen(
            [sys.executable, str(_HERE / "log_viewer.py")],
            cwd=str(_HERE),
        )

    def _open_settings(self):
        subprocess.Popen(
            [sys.executable, str(_HERE / "setup_wizard.py")],
            cwd=str(_HERE),
        )

    def _quit(self, icon):
        monitor.stop()
        icon.stop()

    def run(self):
        icon = pystray.Icon(
            "uscis_monitor",
            _make_icon(),
            "USCIS Monitor",
            menu=self._build_menu(),
        )
        self._icon = icon
        icon.run()


def _notify(title: str, msg: str):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x40)
    except Exception:
        logger.info("Notification: %s — %s", title, msg)
