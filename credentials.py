"""
Encrypted per-account USCIS auto-login credentials.

Stored Fernet-encrypted with the SAME key used for session cookies
(~/.uscis_monitor/.fernet_key), at ~/.uscis_monitor/credentials_<account>.enc.
This keeps the USCIS password + Gmail app password off plaintext disk.
"""
import json
import logging
from pathlib import Path

from cryptography.fernet import Fernet
from config import APP_DIR, KEY_PATH

logger = logging.getLogger(__name__)


def _cipher() -> Fernet:
    if KEY_PATH.exists():
        key = KEY_PATH.read_bytes()
    else:
        key = Fernet.generate_key()
        KEY_PATH.write_bytes(key)
    return Fernet(key)


def _cred_path(account: str) -> Path:
    return APP_DIR / f"credentials_{(account or 'primary').strip().lower()}.enc"


def save_credentials(account: str, email: str, password: str,
                     gmail_app_password: str) -> None:
    data = {
        "email": (email or "").strip(),
        "password": password or "",
        "gmail_app_password": (gmail_app_password or "").strip(),
    }
    _cred_path(account).write_bytes(_cipher().encrypt(json.dumps(data).encode()))
    logger.info("Encrypted credentials saved for '%s'.",
                (account or "primary").strip().lower())


def load_credentials(account: str) -> dict | None:
    path = _cred_path(account)
    if not path.exists():
        return None
    try:
        return json.loads(_cipher().decrypt(path.read_bytes()))
    except Exception as exc:
        logger.warning("Could not decrypt credentials for '%s': %s", account, exc)
        return None


def has_credentials(account: str) -> bool:
    return _cred_path(account).exists()


def clear_credentials(account: str) -> None:
    path = _cred_path(account)
    if path.exists():
        path.unlink()
    logger.info("Credentials cleared for '%s'.", (account or "primary").strip().lower())


def list_credential_accounts() -> list[str]:
    return sorted(
        p.stem[len("credentials_"):] for p in APP_DIR.glob("credentials_*.enc")
    )
