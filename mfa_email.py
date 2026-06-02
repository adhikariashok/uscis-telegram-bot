"""
Fetch USCIS MFA verification codes from Gmail via IMAP.
Ported from immigration/src/mfa.ts.
"""
import email
import imaplib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
MAX_WAIT_SEC = 120
POLL_INTERVAL_SEC = 5
USCIS_FROM = "uscis.dhs.gov"
# USCIS HTML emails use quoted-printable with soft line breaks inside tags.
_CODE_PATTERNS = [
    re.compile(
        r"verification code[:\s]*(?:<[^>]+>|\s)*(\d{6})",
        re.IGNORECASE,
    ),
    re.compile(
        r"verification code.*?(\d{6})",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r">(\d{6})\s*</span>", re.IGNORECASE),
    re.compile(
        r"font-weight:\s*600;?\s*['\"]?\s*>\s*(\d{6})\s*</span>",
        re.IGNORECASE,
    ),
    re.compile(
        r"secure verification code[^0-9]{0,120}(\d{6})",
        re.IGNORECASE,
    ),
]


def normalize_gmail_app_password(raw: str) -> str:
    """Gmail app passwords are 16 chars; spaces in .env are optional."""
    pwd = re.sub(r"\s+", "", (raw or "").strip())
    return pwd


def validate_gmail_app_password(pwd: str) -> str | None:
    """Return a user-facing hint if the password format looks wrong."""
    if not pwd:
        return "GMAIL_APP_PASSWORD is empty."
    if len(pwd) != 16:
        return (
            f"Gmail app password should be 16 characters "
            f"(got {len(pwd)}). Remove quotes, spaces, or stray "
            f"characters like % at the end of .env."
        )
    if not pwd.isalnum():
        return (
            "Gmail app password should be letters and digits only."
        )
    return None


def _normalize_email_body(body: str) -> str:
    normalized = body.replace("=\r\n", "").replace("=\n", "")
    normalized = re.sub(
        r"=([0-9A-Fa-f]{2})",
        lambda m: chr(int(m.group(1), 16)),
        normalized,
    )
    return normalized


def _decode_part_text(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="ignore")
    except Exception:
        return payload.decode("utf-8", errors="ignore")


def _message_body_text(msg: email.message.Message) -> str:
    """Decode HTML/plain body; handles single-part QP HTML like USCIS sends."""
    chunks = []
    part = None

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_subtype() not in ("html", "plain"):
                continue
            text = _decode_part_text(part)
            if text:
                chunks.append(text)
    else:
        text = _decode_part_text(msg)
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _extract_code(body: str) -> str | None:
    normalized = ""
    pattern = None
    match = None

    normalized = _normalize_email_body(body)
    for pattern in _CODE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(1)
    return None


def _is_uscis_mfa_email(from_addr: str, subject: str) -> bool:
    from_lower = from_addr.lower()
    subject_lower = subject.lower()
    if USCIS_FROM not in from_lower:
        return False
    return (
        "two-step" in subject_lower
        or "secure verification" in subject_lower
    )


def _message_date(msg: email.message.Message) -> datetime | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _try_read_code(
    email_addr: str,
    app_password: str,
    since: datetime,
) -> str | None:
    mail = None
    latest_code = None
    latest_uid = 0

    pwd = normalize_gmail_app_password(app_password)
    hint = validate_gmail_app_password(pwd)
    if hint:
        raise ValueError(hint)

    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        mail.login(email_addr, pwd)
    except imaplib.IMAP4.error as exc:
        err = str(exc)
        if "AUTHENTICATIONFAILED" in err:
            raise RuntimeError(
                "Gmail IMAP login failed — invalid app password. "
                "Create a new App Password at "
                "https://myaccount.google.com/apppasswords "
                "(Google Account → Security → 2-Step Verification → "
                "App passwords). Use the same Gmail as USCIS_EMAIL. "
                "Set GMAIL_APP_PASSWORD_1 in .env as 16 characters "
                "with no quotes."
            ) from exc
        raise
    mail.select("INBOX")

    since_str = since.strftime("%d-%b-%Y")
    uids = []
    typ = ""
    data = None

    # Gmail: prefer X-GM-RAW (same as immigration repo imapflow gmailraw)
    try:
        typ, data = mail.uid(
            "SEARCH",
            None,
            "X-GM-RAW",
            f'"from:{USCIS_FROM} newer_than:1d"',
        )
        uids = data[0].split() if typ == "OK" and data and data[0] else []
    except Exception:
        uids = []

    if not uids:
        typ, data = mail.uid(
            "search",
            None,
            f'(FROM "uscis" SINCE "{since_str}")',
        )
        uids = data[0].split() if typ == "OK" and data[0] else []
    if not uids:
        typ, data = mail.search(None, f'(SINCE "{since_str}")')
        uids = data[0].split() if typ == "OK" and data[0] else []

    for uid in uids[-30:]:
        typ, fetched = mail.uid("fetch", uid, "(RFC822)")
        if typ != "OK" or not fetched or not fetched[0]:
            continue
        raw = fetched[0][1]
        if not raw:
            continue
        msg = email.message_from_bytes(raw)
        from_hdr = msg.get("From", "")
        subject = msg.get("Subject", "")
        if not _is_uscis_mfa_email(from_hdr, subject):
            continue
        msg_date = _message_date(msg)
        if msg_date and msg_date < since:
            continue
        body = _message_body_text(msg)
        code = _extract_code(body)
        if not code:
            logger.debug(
                "USCIS MFA email matched but no code parsed (subject=%s)",
                subject,
            )
            continue
        uid_int = int(uid)
        if uid_int >= latest_uid:
            latest_uid = uid_int
            latest_code = code

    try:
        mail.logout()
    except Exception:
        pass
    return latest_code


def fetch_verification_code(
    email_addr: str,
    app_password: str,
    since_time: datetime | None = None,
) -> str:
    """
    Poll Gmail until a USCIS MFA code arrives (up to MAX_WAIT_SEC).
    """
    since = None
    start = time.time()
    code = None

    if since_time:
        # Allow clock skew; USCIS emails can take a few seconds to arrive
        since = since_time - timedelta(seconds=60)
    else:
        since = datetime.now(timezone.utc) - timedelta(minutes=3)

    while time.time() - start < MAX_WAIT_SEC:
        try:
            code = _try_read_code(email_addr, app_password, since)
        except (RuntimeError, ValueError):
            raise
        except imaplib.IMAP4.error:
            raise
        if code:
            logger.info("USCIS MFA code received from email.")
            return code
        logger.info("No USCIS code in inbox yet, retrying...")
        time.sleep(POLL_INTERVAL_SEC)

    raise TimeoutError(
        "Timed out waiting for USCIS verification email"
    )
