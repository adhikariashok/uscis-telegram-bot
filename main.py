"""
Entry point for the USCIS Case Monitor Windows tray app.

Start order:
  1. Init database
  2. If first run → show setup wizard (blocks until done)
  3. Start Telegram bot (background thread)
  4. Start monitor/scheduler (background thread via APScheduler)
  5. Run system tray (blocks main thread)
"""
import logging
import os
import subprocess
import sys
from pathlib import Path
from config import LOG_PATH, APP_DIR, load_config, is_first_run
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


def main():
    _acquire_lock()
    import atexit
    atexit.register(_release_lock)
    logger.info("=== USCIS Monitor starting ===")

    # 1. Database
    init_db()

    # 2. First-run wizard (subprocess so tkinter never touches this process)
    if is_first_run():
        logger.info("First run detected — launching setup wizard.")
        subprocess.run([sys.executable, str(_HERE / "setup_wizard.py")], cwd=str(_HERE))
        if is_first_run():
            logger.info("Setup cancelled. Exiting.")
            sys.exit(0)

    cfg = load_config()
    token = cfg.get("telegram_bot_token", "").strip()
    if not token:
        logger.warning("No bot token — re-opening setup.")
        subprocess.run([sys.executable, str(_HERE / "setup_wizard.py")], cwd=str(_HERE))
        cfg = load_config()
        token = cfg.get("telegram_bot_token", "").strip()
        if not token:
            sys.exit(1)

    # 3. Telegram bot
    import telegram_bot
    telegram_bot.start(token)
    logger.info("Telegram bot thread started.")

    # 4. Monitor
    import monitor
    monitor.start(notify_fn=telegram_bot.send_notification)
    logger.info("Case monitor started.")

    # Delay the startup check so the bot thread has time to connect
    import threading
    threading.Timer(5.0, monitor.trigger_now).start()

    # 5. System tray (blocks main thread)
    from tray_app import TrayApp
    tray = TrayApp()
    logger.info("System tray running.")
    tray.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Unhandled exception — app crashed.")
        raise
