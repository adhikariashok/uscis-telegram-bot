"""
Load per-account USCIS login credentials from environment / .env.

Naming (account label is case-insensitive):
  primary  -> USCIS_EMAIL, USCIS_PASSWORD, GMAIL_APP_PASSWORD
  boris    -> USCIS_EMAIL_BORIS, USCIS_PASSWORD_BORIS,
              GMAIL_APP_PASSWORD_BORIS

Also accepts immigration-style numbered vars for any account
when account-specific vars are not set:
  USCIS_EMAIL_1, USCIS_PASSWORD_1, GMAIL_APP_PASSWORD_1
"""
import os
from config import _load_raw_env
from mfa_email import normalize_gmail_app_password


def _env_suffix(account: str) -> str:
    label = (account or "primary").strip().lower()
    if label == "primary":
        return ""
    return f"_{label.upper()}"


def load_account_credentials(account: str = "primary") -> dict | None:
    """
    Return {email, password, gmail_app_password} or None if incomplete.
    """
    suffix = ""
    email = ""
    password = ""
    gmail = ""
    raw = None

    raw = _load_raw_env()
    suffix = _env_suffix(account)

    email = (
        raw.get(f"USCIS_EMAIL{suffix}", "")
        or os.environ.get(f"USCIS_EMAIL{suffix}", "")
    ).strip()
    password = (
        raw.get(f"USCIS_PASSWORD{suffix}", "")
        or os.environ.get(f"USCIS_PASSWORD{suffix}", "")
    ).strip()
    gmail = (
        raw.get(f"GMAIL_APP_PASSWORD{suffix}", "")
        or os.environ.get(f"GMAIL_APP_PASSWORD{suffix}", "")
    ).strip()

    if not email:
        email = (
            raw.get("USCIS_EMAIL_1", "")
            or os.environ.get("USCIS_EMAIL_1", "")
        ).strip()
        password = (
            raw.get("USCIS_PASSWORD_1", "")
            or os.environ.get("USCIS_PASSWORD_1", "")
        ).strip()
        gmail = (
            raw.get("GMAIL_APP_PASSWORD_1", "")
            or os.environ.get("GMAIL_APP_PASSWORD_1", "")
        ).strip()

    if email and password and gmail:
        return {
            "email": email,
            "password": password,
            "gmail_app_password": normalize_gmail_app_password(gmail),
        }
    return None


def has_auto_login_credentials(account: str = "primary") -> bool:
    return load_account_credentials(account) is not None
