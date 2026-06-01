"""
Entry point for the USCIS Case Monitor.

Modes:
  - tray: Windows tray app flow (existing behavior)
  - headless: no GUI/tray, suitable for macOS/Linux/server
"""
import argparse
import atexit
import logging
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from config import LOG_PATH, APP_DIR, ENV_PATH, load_config, is_first_run
from database import init_db

_LOCK_FILE = APP_DIR / "monitor.pid"


def _acquire_lock():
    """Ensure only one instance runs. Kill the old one if a PID file exists."""
    if _LOCK_FILE.exists():
        old_pid = _LOCK_FILE.read_text().strip()
        try:
            old_pid = int(old_pid)
            import psutil
            try:
                proc = psutil.Process(old_pid)
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass
        except (ValueError, ImportError):
            pass
        _LOCK_FILE.unlink(missing_ok=True)
    _LOCK_FILE.write_text(str(os.getpid()))


def _release_lock():
    _LOCK_FILE.unlink(missing_ok=True)

_HERE = Path(__file__).parent

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def _open_setup_wizard() -> int:
    return subprocess.run(
        [sys.executable, str(_HERE / "setup_wizard.py")],
        cwd=str(_HERE),
    ).returncode


def _ensure_config(mode: str) -> str:
    if is_first_run():
        if mode == "tray":
            logger.info("First run detected - launching setup wizard.")
            _open_setup_wizard()
            if is_first_run():
                logger.info("Setup cancelled. Exiting.")
                sys.exit(0)
        else:
            logger.error(
                "Missing Telegram token. Run setup_wizard.py once, or "
                "write TELEGRAM_BOT_TOKEN to %s",
                str(ENV_PATH),
            )
            sys.exit(1)

    cfg = load_config()
    token = cfg.get("telegram_bot_token", "").strip()
    if not token:
        if mode == "tray":
            logger.warning("No bot token - re-opening setup.")
            _open_setup_wizard()
            cfg = load_config()
            token = cfg.get("telegram_bot_token", "").strip()
        if not token:
            logger.error("Telegram token is required. Exiting.")
            sys.exit(1)

    return token


def _start_services(token: str):
    import telegram_bot
    import monitor

    telegram_bot.start(token)
    logger.info("Telegram bot thread started.")

    monitor.start(notify_fn=telegram_bot.send_notification)
    logger.info("Case monitor started.")

    import threading

    # Delay the first case poll until after the startup session refresh
    # has time to complete for all accounts (~30s per account).
    # 5 seconds was too short — it raced with the headless Chrome refresh,
    # locking the Chrome profile and causing "Headless Chrome did not start".
    threading.Timer(120.0, monitor.trigger_now).start()
    return monitor


def _run_headless():
    logger.info("Headless mode running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down headless mode.")
        import monitor

        monitor.stop()


def _resolve_mode(mode_arg: str | None) -> str:
    if mode_arg in {"tray", "headless"}:
        return mode_arg
    if platform.system() == "Windows":
        return "tray"
    return "headless"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["tray", "headless"],
        default=None,
        help="Run mode. Defaults to tray on Windows, headless elsewhere.",
    )
    parsed = parser.parse_args()
    mode = _resolve_mode(parsed.mode)

    _acquire_lock()
    atexit.register(_release_lock)
    logger.info("=== USCIS Monitor starting (%s mode) ===", mode)

    init_db()
    token = _ensure_config(mode)
    _start_services(token)

    if mode == "tray":
        if platform.system() != "Windows":
            logger.error("Tray mode is only supported on Windows.")
            sys.exit(1)

        from tray_app import TrayApp

        tray = TrayApp()
        logger.info("System tray running.")
        tray.run()
        return

    _run_headless()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Unhandled exception — app crashed.")
        raise
