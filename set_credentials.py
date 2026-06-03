"""
Interactively store encrypted USCIS auto-login credentials for an account.

Usage:
    python set_credentials.py [account]      # default account: primary

Secrets are read with getpass (never echoed) and saved Fernet-encrypted to
~/.uscis_monitor/credentials_<account>.enc. Nothing sensitive is printed back.

Requirements per account:
  * USCIS account email — must be the Gmail/Workspace inbox that receives the
    USCIS two-step verification emails (used for IMAP).
  * USCIS password.
  * Gmail App Password (16 chars) for that inbox — create at
    https://myaccount.google.com/apppasswords
"""
import sys
from getpass import getpass

import credentials as store
from mfa_email import normalize_gmail_app_password, validate_gmail_app_password


def main() -> int:
    account = (sys.argv[1] if len(sys.argv) > 1 else "primary").strip().lower()
    print(f"Setting USCIS auto-login credentials for account: {account}")
    print("(input is hidden where sensitive; nothing is echoed or logged)\n")

    email = input("USCIS email (the Gmail that receives USCIS MFA codes): ").strip()
    password = getpass("USCIS password: ")
    gmail = normalize_gmail_app_password(getpass("Gmail App Password (16 chars): "))

    hint = validate_gmail_app_password(gmail)
    if hint:
        print("WARNING:", hint)

    if not (email and password and gmail):
        print("Aborted — email, password, and Gmail App Password are all required.")
        return 1

    store.save_credentials(account, email, password, gmail)
    print(f"\n✅ Saved encrypted credentials for '{account}'.")
    print(f"   You can now run  /relogin {account}  in Telegram, or it will be")
    print("   used automatically when the session hits its ~8h cap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
