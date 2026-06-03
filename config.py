import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
ENV_PATH = ROOT_DIR / ".env"
_DEFAULT_APP_DIR = Path.home() / ".uscis_monitor"

_DEFAULTS = {
    "telegram_bot_token": "",
    "poll_interval": 300,
    "uscis_api_mode": "auto",  # "public", "authenticated", or "auto"
    "custom_endpoint": "",
    "uscis_login_url": "https://my.uscis.gov",
    "uscis_dashboard_url": "https://my.uscis.gov/my-account/dashboard/info",
    "uscis_public_api": (
        "https://egov.uscis.gov/case-status/api/cases/{receipt_number}"
    ),
    "uscis_my_api": "https://my.uscis.gov/api/cases/{receipt_number}",
    "app_dir": str(_DEFAULT_APP_DIR),
    "db_path": str(_DEFAULT_APP_DIR / "data.db"),
    "session_path": str(_DEFAULT_APP_DIR / "session.enc"),
    "key_path": str(_DEFAULT_APP_DIR / ".fernet_key"),
    "log_path": str(_DEFAULT_APP_DIR / "monitor.log"),
    # Comma-separated Telegram user IDs allowed to run /addaccount.
    # Leave empty to allow all users (not recommended on a public bot).
    "allowed_telegram_ids": "",
    # Delete (move to Trash) the USCIS MFA verification email after the code is
    # read, so the inbox isn't crowded with codes. Set to "false" to keep them.
    "delete_mfa_email": "true",
}


def _env_key(name: str) -> str:
    return name.upper()


def _read_env_file() -> dict:
    values = {}
    line = ""
    key = ""
    value = ""

    if not ENV_PATH.exists():
        return values

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and ((value[0] == '"' and value[-1] == '"')
                 or (value[0] == "'" and value[-1] == "'"))
        ):
            value = value[1:-1]
        values[key] = value
    return values


def _load_raw_env() -> dict:
    values = _read_env_file()
    name = ""
    env_name = ""

    for name in _DEFAULTS.keys():
        env_name = _env_key(name)
        if env_name in os.environ:
            values[env_name] = os.environ[env_name]
    return values


def load_config() -> dict:
    raw = _load_raw_env()
    cfg = dict(_DEFAULTS)
    name = ""
    env_name = ""
    value = ""
    default = None

    for name, default in _DEFAULTS.items():
        env_name = _env_key(name)
        value = raw.get(env_name, "")
        if value == "":
            cfg[name] = default
            continue
        if name == "poll_interval":
            try:
                cfg[name] = int(value)
            except ValueError:
                cfg[name] = default
            continue
        cfg[name] = value
    return cfg


def _write_env_file(values: dict):
    lines = []
    name = ""
    env_name = ""
    value = ""

    lines.append("# USCIS monitor runtime configuration")
    lines.append("")
    for name in sorted(values.keys()):
        env_name = _env_key(name)
        value = str(values[name]).replace("\n", "\\n")
        lines.append(f"{env_name}={value}")
    lines.append("")
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")


def _migrate_from_json():
    """One-time migration: copy config.json values into .env on first startup."""
    old_path = _DEFAULT_APP_DIR / "config.json"
    if ENV_PATH.exists() or not old_path.exists():
        return
    try:
        import json as _json
        with open(old_path) as f:
            old_data = _json.load(f)
        merged = dict(_DEFAULTS)
        for k, v in old_data.items():
            if k in merged:
                merged[k] = v
        _write_env_file(merged)
    except Exception:
        pass


def save_config(data: dict):
    current = load_config()
    current.update(data)
    _write_env_file(current)


def _path_from_cfg(key: str, fallback: Path) -> Path:
    cfg = load_config()
    value = cfg.get(key, "")
    if not value:
        return fallback
    return Path(value).expanduser()


_migrate_from_json()

APP_DIR = _path_from_cfg("app_dir", _DEFAULT_APP_DIR)
APP_DIR.mkdir(exist_ok=True)
DB_PATH = _path_from_cfg("db_path", APP_DIR / "data.db")
SESSION_PATH = _path_from_cfg("session_path", APP_DIR / "session.enc")
KEY_PATH = _path_from_cfg("key_path", APP_DIR / ".fernet_key")
LOG_PATH = _path_from_cfg("log_path", APP_DIR / "monitor.log")

POLL_INTERVAL_SECONDS = load_config().get("poll_interval", 300)
USCIS_LOGIN_URL = load_config().get(
    "uscis_login_url",
    _DEFAULTS["uscis_login_url"],
)
USCIS_DASHBOARD_URL = load_config().get(
    "uscis_dashboard_url",
    _DEFAULTS["uscis_dashboard_url"],
)
USCIS_PUBLIC_API = load_config().get(
    "uscis_public_api",
    _DEFAULTS["uscis_public_api"],
)
USCIS_MY_API = load_config().get("uscis_my_api", _DEFAULTS["uscis_my_api"])


def is_first_run() -> bool:
    return not load_config().get("telegram_bot_token")
