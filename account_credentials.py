"""
Per-account USCIS auto-login credentials (public interface).

Prefers the encrypted store (credentials.py). Falls back to environment / .env
for migration: if plaintext creds are found there, they're copied into the
encrypted store and a warning is logged to remove them from .env.

Env var naming (account label is case-insensitive):
  primary -> USCIS_EMAIL, USCIS_PASSWORD, GMAIL_APP_PASSWORD
  spouse  -> USCIS_EMAIL_SPOUSE, USCIS_PASSWORD_SPOUSE, GMAIL_APP_PASSWORD_SPOUSE
  numbered aliases for primary also work: USCIS_EMAIL_1, USCIS_PASSWORD_1, ...

The account `email` must be the Gmail (or Google Workspace) inbox that receives
the USCIS MFA codes — it's used for IMAP login together with the app password.
"""
import logging
import os

import credentials as _store
from config import _load_raw_env
from mfa_email import normalize_gmail_app_password

logger = logging.getLogger(__name__)


def _env_suffix(account: str) -> str:
    label = (account or "primary").strip().lower()
    return "" if label == "primary" else f"_{label.upper()}"


def _from_env(account: str) -> dict | None:
    raw = _load_raw_env()
    suffix = _env_suffix(account)

    def get(base: str, suf: str) -> str:
        return (raw.get(f"{base}{suf}", "")
                or os.environ.get(f"{base}{suf}", "")).strip()

    email = get("USCIS_EMAIL", suffix)
    password = get("USCIS_PASSWORD", suffix)
    gmail = get("GMAIL_APP_PASSWORD", suffix)

    if not email:  # numbered-alias fallback (primary only)
        email = get("USCIS_EMAIL", "_1")
        password = get("USCIS_PASSWORD", "_1")
        gmail = get("GMAIL_APP_PASSWORD", "_1")

    if email and password and gmail:
        return {
            "email": email,
            "password": password,
            "gmail_app_password": normalize_gmail_app_password(gmail),
        }
    return None


def load_account_credentials(account: str = "primary") -> dict | None:
    """Return {email, password, gmail_app_password} or None if not configured."""
    creds = _store.load_credentials(account)
    if creds and creds.get("email") and creds.get("password") \
            and creds.get("gmail_app_password"):
        creds["gmail_app_password"] = normalize_gmail_app_password(
            creds["gmail_app_password"]
        )
        return creds

    env = _from_env(account)
    if env:
        # Migrate plaintext .env creds into the encrypted store, then nudge.
        try:
            _store.save_credentials(
                account, env["email"], env["password"], env["gmail_app_password"]
            )
            logger.warning(
                "Migrated '%s' credentials from .env into the encrypted store — "
                "please REMOVE USCIS_EMAIL/PASSWORD and GMAIL_APP_PASSWORD from .env.",
                account,
            )
        except Exception as exc:
            logger.warning("Could not migrate '%s' creds to encrypted store: %s",
                           account, exc)
        return env
    return None


def has_auto_login_credentials(account: str = "primary") -> bool:
    return load_account_credentials(account) is not None
