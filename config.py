import json
from pathlib import Path

APP_DIR = Path.home() / ".uscis_monitor"
APP_DIR.mkdir(exist_ok=True)

DB_PATH = APP_DIR / "data.db"
SESSION_PATH = APP_DIR / "session.enc"
KEY_PATH = APP_DIR / ".fernet_key"
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "monitor.log"

POLL_INTERVAL_SECONDS = 300  # 5 minutes

USCIS_LOGIN_URL = "https://my.uscis.gov"
USCIS_DASHBOARD_URL = "https://my.uscis.gov/my-account/dashboard/info"
USCIS_PUBLIC_API = "https://egov.uscis.gov/case-status/api/cases/{receipt_number}"
USCIS_MY_API = "https://my.uscis.gov/api/cases/{receipt_number}"

_DEFAULTS = {
    "telegram_bot_token": "",
    "poll_interval": POLL_INTERVAL_SECONDS,
    "uscis_api_mode": "auto",  # "public", "authenticated", or "auto"
    "custom_endpoint": "",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        for k, v in _DEFAULTS.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(_DEFAULTS)


def save_config(data: dict):
    current = load_config()
    current.update(data)
    with open(CONFIG_PATH, "w") as f:
        json.dump(current, f, indent=2)


def is_first_run() -> bool:
    return not load_config().get("telegram_bot_token")
