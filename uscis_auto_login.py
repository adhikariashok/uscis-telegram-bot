"""
Automated myUSCIS login with email MFA.
Ported from immigration/src/auth.ts.
"""
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from mfa_email import fetch_verification_code

logger = logging.getLogger(__name__)

MYUSCIS_URL = "https://my.uscis.gov/account/"
MYUSCIS_APPLICANT_URL = "https://my.uscis.gov/account/applicant"
SIGN_IN_URL = "https://myaccount.uscis.gov/sign-in"
LOGIN_TIMEOUT_MS = 90_000


def _needs_mfa(page_url: str) -> bool:
    return "/auth" in page_url or "sign-in" in page_url


def _is_my_uscis_logged_in(page_url: str) -> bool:
    return "my.uscis.gov" in page_url and "sign-in" not in page_url


def _is_account_authenticated(page_url: str) -> bool:
    if _is_my_uscis_logged_in(page_url):
        return True
    return (
        "myaccount.uscis.gov" in page_url
        and "dashboard" in page_url
    )


def _safe_goto(page, url: str) -> None:
    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=LOGIN_TIMEOUT_MS,
        )
    except Exception as exc:
        msg = str(exc)
        if "ERR_ABORTED" not in msg:
            raise
    page.wait_for_load_state(
        "domcontentloaded",
        timeout=LOGIN_TIMEOUT_MS,
    )


def _ensure_my_uscis_access(page) -> None:
    attempt = 0
    current_url = ""

    while attempt < 4:
        current_url = page.url
        if _is_my_uscis_logged_in(current_url):
            logger.info("MyUSCIS ready.")
            return
        if not _is_account_authenticated(current_url):
            break
        logger.info("On USCIS dashboard, opening MyUSCIS...")
        _safe_goto(page, MYUSCIS_URL)
        try:
            page.wait_for_url(
                lambda u: "my.uscis.gov" in u,
                timeout=30_000,
            )
        except Exception:
            pass
        if not _is_my_uscis_logged_in(page.url):
            _safe_goto(page, MYUSCIS_APPLICANT_URL)
            try:
                page.wait_for_url(
                    lambda u: "my.uscis.gov" in u,
                    timeout=30_000,
                )
            except Exception:
                pass
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        attempt += 1

    logger.info("Post-login URL: %s", page.url)


def _complete_mfa(page, email: str, gmail_app_password: str,
                  mfa_requested_at: datetime) -> None:
    logger.info("MFA required — fetching code from email...")
    time.sleep(8)
    code = fetch_verification_code(
        email,
        gmail_app_password,
        mfa_requested_at,
    )
    logger.info("Got verification code.")

    code_input = page.locator(
        'input[aria-label*="Secure Verification"],'
        ' input[aria-label*="verification code"]'
    ).first
    code_input.fill(code)

    remember = page.get_by_role(
        "checkbox",
        name=re.compile(r"Remember this browser", re.I),
    )
    if remember.is_visible():
        remember.check()

    page.get_by_role("button", name="Submit", exact=True).click()
    page.wait_for_url(
        lambda u: "/auth" not in u,
        timeout=LOGIN_TIMEOUT_MS,
    )
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass
    logger.info("After MFA URL: %s", page.url)


def perform_uscis_login(
    page,
    email: str,
    password: str,
    gmail_app_password: str,
) -> None:
    """Fill credentials, complete MFA, reach MyUSCIS dashboard."""
    current_url = ""
    mfa_requested_at = None

    logger.info("Opening MyUSCIS account...")
    _safe_goto(page, MYUSCIS_URL)
    try:
        page.wait_for_load_state("networkidle", timeout=LOGIN_TIMEOUT_MS)
    except Exception:
        pass

    current_url = page.url
    if _is_my_uscis_logged_in(current_url):
        logger.info("Already logged into MyUSCIS.")
        return

    logger.info("Sign-in required...")
    if "sign-in" not in current_url:
        _safe_goto(page, SIGN_IN_URL)

    page.wait_for_selector(
        'input#password, input[data-testid="test-password"]',
        timeout=30_000,
        state="visible",
    )

    logger.info("Filling credentials...")
    email_input = page.locator(
        'input[aria-label*="Email"],'
        ' input[name="email"],'
        ' input[type="email"],'
        ' input#email'
    ).first
    email_input.fill(email)

    pass_input = page.locator(
        'input#password, input[data-testid="test-password"]'
    )
    pass_input.fill(password)

    mfa_requested_at = datetime.now(timezone.utc)
    page.get_by_role("button", name="Sign In", exact=True).click()
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass

    current_url = page.url
    if "soft-locked" in current_url:
        raise RuntimeError(
            "USCIS account is soft-locked. Wait before retrying."
        )

    if _needs_mfa(current_url):
        _complete_mfa(
            page,
            email,
            gmail_app_password,
            mfa_requested_at,
        )

    _ensure_my_uscis_access(page)


def _cookies_from_context(context) -> list:
    cookies = []
    raw = None
    item = None

    raw = context.cookies()
    for item in raw:
        cookies.append({
            "name": item["name"],
            "value": item["value"],
            "domain": item.get("domain", ""),
            "path": item.get("path", "/"),
            "secure": item.get("secure", False),
            "httpOnly": item.get("httpOnly", False),
            "sameSite": item.get("sameSite", ""),
            "expires": item.get("expires", -1),
        })
    return cookies


def _local_storage_from_page(page) -> dict:
    raw = page.evaluate("""() => {
        try {
            var out = {};
            var keys = Object.keys(localStorage);
            for (var i = 0; i < keys.length; i++) {
                out[keys[i]] = localStorage.getItem(keys[i]);
            }
            return out;
        } catch (e) {
            return {};
        }
    }""")
    return raw if isinstance(raw, dict) else {}


def _auth_header_from_page(page) -> dict:
    token = page.evaluate("""() => {
        try {
            var keys = Object.keys(localStorage);
            for (var i = 0; i < keys.length; i++) {
                var v = localStorage.getItem(keys[i]);
                if (!v) continue;
                try {
                    var obj = JSON.parse(v);
                    if (obj && obj.accessToken
                        && obj.accessToken.accessToken) {
                        return 'Bearer '
                            + obj.accessToken.accessToken;
                    }
                } catch (e) {}
            }
        } catch (e) {}
        return '';
    }""")
    if token:
        return {"Authorization": token}
    return {}


def automated_login_capture(
    profile_dir: Path,
    email: str,
    password: str,
    gmail_app_password: str,
    account: str = "primary",
    headless: bool = True,
    status_callback=None,
) -> tuple[list, dict, dict] | None:
    """
    Run full automated login in Playwright and return session data.
    Returns (cookies, extra_headers, local_storage) or None on failure.
    """
    from playwright.sync_api import sync_playwright

    def _cb(msg: str):
        logger.info(msg)
        if status_callback:
            status_callback(msg)

    context = None
    page = None
    cookies = []
    extra_headers = {}
    local_storage = {}

    _cb("Starting automated USCIS login...")
    try:
        with sync_playwright() as p:
            launch_args = {
                "user_data_dir": str(profile_dir),
                "headless": headless,
                "locale": "en-US",
                "viewport": {"width": 1280, "height": 720},
                "user_agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            }
            try:
                context = p.chromium.launch_persistent_context(
                    channel="chrome",
                    **launch_args,
                )
            except Exception:
                context = p.chromium.launch_persistent_context(
                    **launch_args,
                )
            page = context.pages[0] if context.pages else context.new_page()
            perform_uscis_login(
                page,
                email,
                password,
                gmail_app_password,
            )
            _cb("Login complete — capturing session...")
            time.sleep(4)
            cookies = _cookies_from_context(context)
            extra_headers = _auth_header_from_page(page)
            local_storage = _local_storage_from_page(page)
            context.close()
    except Exception as exc:
        logger.exception("Automated login failed: %s", exc)
        msg = str(exc)
        if "Gmail" in msg or "app password" in msg.lower():
            _cb(f"❌ {msg}")
        else:
            _cb(f"Automated login failed: {exc}")
        from auth_manager import _last_capture_error
        _last_capture_error[account] = msg
        return None

    if not cookies:
        _cb("No cookies captured after automated login.")
        from auth_manager import _last_capture_error
        _last_capture_error[account] = "No cookies captured after login."
        return None

    _cb(f"Captured {len(cookies)} cookies.")
    return cookies, extra_headers, local_storage
