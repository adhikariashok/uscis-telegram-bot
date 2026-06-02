"""
Handles myUSCIS login by launching real Chrome via subprocess and talking to it
over Chrome DevTools Protocol (CDP). No Selenium — undetectable as automation.
Supports multiple named accounts (e.g. "primary", "wife").
Each account gets its own encrypted session file.
"""
import json
import logging
import os
import socket
import subprocess
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet
from config import APP_DIR, KEY_PATH, USCIS_LOGIN_URL, USCIS_DASHBOARD_URL

logger = logging.getLogger(__name__)

# Tracks accounts for which we've already sent a session-expiry warning this
# process lifetime — prevents the warning from firing every 30 minutes.
_expiry_warned: set[str] = set()
_last_capture_error: dict[str, str] = {}


def last_capture_error(account: str) -> str:
    return _last_capture_error.get(account, "")
_profile_locks: dict[str, threading.Lock] = {}
_profile_locks_guard = threading.Lock()


@contextmanager
def _chrome_profile_lock(account: str):
    """
    Only one Chrome/Playwright session per account profile at a time.
    Prevents silent refresh and /relogin from racing on the same dir.
    """
    lock = None
    with _profile_locks_guard:
        if account not in _profile_locks:
            _profile_locks[account] = threading.Lock()
        lock = _profile_locks[account]
    lock.acquire()
    try:
        yield
    finally:
        lock.release()

# The cookies that actually carry the authenticated myUSCIS session. This site
# is Rails session-cookie auth behind Akamai/AWS bot protection — NOT Okta/OAuth.
# (The trailing names are legacy/other-environment variants kept for safety.)
_SESSION_COOKIE_NAMES = (
    "_uscis_user_session",
    "_myuscis_session_rx",
    "_uscis_userservices_session",
    "sid", "JSESSIONID", "usi_session",
)


def _normalize_cdp_cookie(c: dict) -> dict:
    """
    Keep every field we need to (a) replay the cookie via requests and
    (b) reason about its lifetime. CDP returns `expires` as a Unix timestamp
    (-1 for session cookies). Dropping it — as the old code did — is why
    get_session_expiry() could never find a deadline.
    """
    return {
        "name": c["name"],
        "value": c["value"],
        "domain": c.get("domain", ""),
        "path": c.get("path", "/"),
        "secure": c.get("secure", False),
        "httpOnly": c.get("httpOnly", False),
        "sameSite": c.get("sameSite", ""),
        "expires": c.get("expires", -1),
    }


# ── Encryption helpers ────────────────────────────────────────────────────────

def _get_key() -> bytes:
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    return key


def _cipher() -> Fernet:
    return Fernet(_get_key())


def _session_path(account: str) -> Path:
    return APP_DIR / f"session_{account}.enc"


def _chrome_profile_dir(account: str) -> Path:
    """Persistent Chrome profile dir per account — preserves Okta's full session state."""
    p = APP_DIR / f"chrome_profile_{account}"
    p.mkdir(exist_ok=True)
    return p


def _clear_chrome_locks(profile_dir: Path) -> None:
    """
    Remove Chrome lock files that a previously crashed or force-killed Chrome
    process may have left behind. Without this, the next headless Chrome launch
    sees the profile as 'in use', exits immediately, and the CDP endpoint never
    becomes reachable (manifests as 'Headless Chrome did not start').
    """
    lock_names = [
        "Default/LOCK",
        "Default/lockfile",
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
    ]
    for name in lock_names:
        p = profile_dir / name
        try:
            if p.exists():
                p.unlink()
                logger.info("Cleared stale Chrome lock: %s", p)
        except Exception as exc:
            logger.debug("Could not remove Chrome lock %s: %s", p, exc)


# ── Session persistence ───────────────────────────────────────────────────────

def save_session(cookies: list, extra_headers: dict, account: str = "primary",
                 local_storage: dict | None = None):
    data = {"cookies": cookies, "headers": extra_headers,
            "local_storage": local_storage or {}}
    path = _session_path(account)
    path.write_bytes(_cipher().encrypt(json.dumps(data).encode()))
    logger.info("Session saved for account '%s'.", account)


def load_session(account: str = "primary") -> dict | None:
    path = _session_path(account)
    if not path.exists():
        legacy = APP_DIR / "session.enc"
        if account == "primary" and legacy.exists():
            legacy.rename(path)
            logger.info("Migrated legacy session.enc to session_primary.enc")
        else:
            return None
    try:
        return json.loads(_cipher().decrypt(path.read_bytes()))
    except Exception as exc:
        logger.warning("Could not decrypt session for '%s': %s", account, exc)
        return None


def clear_session(account: str = "primary"):
    path = _session_path(account)
    if path.exists():
        path.unlink()
    logger.info("Session cleared for account '%s'.", account)


def has_session(account: str = "primary") -> bool:
    if account == "primary" and (APP_DIR / "session.enc").exists():
        return True
    return _session_path(account).exists()


def get_session_expiry(account: str = "primary") -> float | None:
    """
    Return the earliest known session hard-deadline as a Unix timestamp.
    Reads the `expires` of the real myUSCIS auth cookies (see
    _SESSION_COOKIE_NAMES). Many of them are session cookies (no expiry), in
    which case the deadline is server-side only and we return None.
    A defensive Okta refresh-token check is kept for other environments.
    Returns None if no expiry information is available.
    """
    data = load_session(account)
    if not data:
        return None

    expiry: float | None = None

    for value in (data.get("local_storage") or {}).values():
        try:
            obj = json.loads(value)
            if not isinstance(obj, dict):
                continue
            # Okta token storage (if present) keeps the refresh token's deadline
            rt = obj.get("refreshToken") or {}
            rt_exp = rt.get("expiresAt")
            if rt_exp:
                rt_exp = float(rt_exp)
                if expiry is None or rt_exp < expiry:
                    expiry = rt_exp
        except Exception:
            pass

    for c in data.get("cookies", []):
        if c.get("name") in _SESSION_COOKIE_NAMES:
            exp = c.get("expires", 0)
            if exp and exp > 0:
                exp = float(exp)
                if expiry is None or exp < expiry:
                    expiry = exp

    return expiry


def list_accounts() -> list[str]:
    accounts = []
    if (APP_DIR / "session.enc").exists():
        accounts.append("primary")
    for p in APP_DIR.glob("session_*.enc"):
        name = p.stem[len("session_"):]
        if name not in accounts:
            accounts.append(name)
    return sorted(accounts)


# ── Chrome / CDP helpers ──────────────────────────────────────────────────────

def _find_chrome() -> str | None:
    candidates = []
    p = None
    system = ""
    program_files = ""
    program_files_x86 = ""
    local_app_data = ""
    name = ""
    path_val = ""
    cmd = []
    result = None

    system = os.uname().sysname if hasattr(os, "uname") else ""

    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    program_files_x86 = os.environ.get(
        "PROGRAMFILES(X86)",
        r"C:\Program Files (x86)",
    )
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    candidates = [
        Path(program_files) / "Google/Chrome/Application/chrome.exe",
        Path(program_files_x86) / "Google/Chrome/Application/chrome.exe",
        Path(local_app_data) / "Google/Chrome/Application/chrome.exe",
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/chromium"),
    ]

    for p in candidates:
        if p.exists():
            return str(p)

    if system == "Darwin":
        for name in ["google chrome", "Google Chrome"]:
            cmd = ["mdfind", f'kMDItemDisplayName == "{name}"']
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                path_val = result.stdout.strip().splitlines()[0]
                if path_val:
                    p = Path(path_val) / "Contents/MacOS/Google Chrome"
                    if p.exists():
                        return str(p)
            except Exception:
                continue

    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        ) as k:
            return winreg.QueryValue(k, None)
    except Exception:
        pass
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_cdp(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _tab_list(port: int) -> list:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return []


def _cdp_send(ws, method: str, params: dict, cmd_id: int) -> dict:
    """Send one CDP command, drain events until its response arrives."""
    ws.send(json.dumps({"id": cmd_id, "method": method, "params": params}))
    while True:
        raw = ws.recv()
        msg = json.loads(raw)
        if msg.get("id") == cmd_id:
            return msg.get("result", {})


def _launch_chrome(port: int, profile_dir: str, url: str, headless: bool = False) -> subprocess.Popen:
    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found — install Google Chrome.")
    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--disable-extensions",
    ]
    if headless:
        args += [
            "--headless=new",
            "--window-size=1920,1080",
            "--disable-gpu",                    # required on Windows for headless CDP
            "--disable-dev-shm-usage",          # prevents /dev/shm exhaustion
            "--disable-session-crashed-bubble", # prevents 'restore pages?' prompt that blocks startup
            "--disable-infobars",
        ]
    else:
        args.append("--start-maximized")
    args.append(url)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ── Cookie + auth capture ─────────────────────────────────────────────────────

_LOGIN_MARKERS = ("my-account", "dashboard", "/account/")
_LOGIN_TIMEOUT = 300  # 5 minutes


def _find_uscis_tab(port: int) -> dict | None:
    """Return the tab whose URL is on my.uscis.gov, or the first debuggable tab."""
    tabs = _tab_list(port)
    logger.info("CDP tab list (%d tabs):", len(tabs))
    for t in tabs:
        logger.info("  [%s] %s  ws=%s", t.get("type", "?"), t.get("url", "?"),
                    "yes" if t.get("webSocketDebuggerUrl") else "NO")

    # Prefer a tab that's on uscis.gov
    for tab in tabs:
        if "uscis.gov" in tab.get("url", "") and tab.get("webSocketDebuggerUrl"):
            return tab

    # Fall back to the first tab that has a websocket URL
    for tab in tabs:
        if tab.get("webSocketDebuggerUrl"):
            return tab

    return None


def _capture_from_tab(port: int) -> tuple[list, dict, dict]:
    """
    Connect to the best available Chrome tab and pull cookies, auth token,
    and full localStorage (including Okta refresh tokens for long-lived sessions).
    Does NOT navigate — the caller must ensure the browser is already on the
    authenticated page.
    """
    import websocket

    tab = _find_uscis_tab(port)
    if not tab:
        raise RuntimeError("No debuggable Chrome tab found.")

    logger.info("Capturing from tab: %s", tab.get("url"))
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=20)
    cmd = 1

    try:
        # Cookies — Network domain must be enabled first on some Chrome versions
        _cdp_send(ws, "Network.enable", {}, cmd); cmd += 1
        result = _cdp_send(ws, "Network.getAllCookies", {}, cmd); cmd += 1
        raw_cookies = result.get("cookies", [])
        logger.info("getAllCookies: %d cookies returned", len(raw_cookies))

        # Auth token — Okta stores the access token in localStorage
        extra_headers: dict = {}
        token_js = """(function(){
            try {
                var keys = Object.keys(localStorage);
                for (var i = 0; i < keys.length; i++) {
                    var v = localStorage.getItem(keys[i]);
                    if (!v) continue;
                    try {
                        var obj = JSON.parse(v);
                        if (obj && obj.accessToken && obj.accessToken.accessToken)
                            return 'Bearer ' + obj.accessToken.accessToken;
                    } catch(e) {}
                }
            } catch(e) {}
            return '';
        })()"""
        try:
            result = _cdp_send(ws, "Runtime.evaluate",
                               {"expression": token_js, "returnByValue": True}, cmd)
            cmd += 1
            token = result.get("result", {}).get("value", "")
            if token:
                extra_headers["Authorization"] = token
                logger.info("Auth token captured from localStorage.")
            else:
                logger.info("No localStorage auth token found (cookie-only session).")
        except Exception as exc:
            logger.warning("localStorage token read failed: %s", exc)

        # Full localStorage — captures Okta refresh tokens, which let headless
        # Chrome silently renew the session without requiring a new manual login.
        # Without this, sessions expire when the ~4-hour session cookies die.
        local_storage: dict = {}
        ls_js = """(function(){
            try {
                var out = {};
                var keys = Object.keys(localStorage);
                for (var i = 0; i < keys.length; i++) {
                    out[keys[i]] = localStorage.getItem(keys[i]);
                }
                return JSON.stringify(out);
            } catch(e) { return '{}'; }
        })()"""
        try:
            result = _cdp_send(ws, "Runtime.evaluate",
                               {"expression": ls_js, "returnByValue": True}, cmd)
            cmd += 1
            local_storage = json.loads(result.get("result", {}).get("value", "{}") or "{}")
            logger.info("localStorage captured: %d keys", len(local_storage))
        except Exception as exc:
            logger.warning("localStorage capture failed: %s", exc)

    finally:
        try:
            ws.close()
        except Exception:
            pass

    cookies = [_normalize_cdp_cookie(c) for c in raw_cookies]
    # Log domain breakdown to help diagnose empty captures
    from collections import Counter
    domains = Counter(
        c["domain"].lstrip(".").split(".")[-2] if "." in c["domain"] else c["domain"]
        for c in raw_cookies
    )
    logger.info("Cookie domains: %s", dict(domains))

    return cookies, extra_headers, local_storage


# ── Automated re-login (credentials in .env) ───────────────────────────────────

def _try_automated_relogin(account: str, notify_fn=None) -> bool:
    """Attempt Playwright login when silent refresh fails."""
    creds = None
    result = None

    from account_credentials import load_account_credentials

    creds = load_account_credentials(account)
    if not creds:
        return False

    logger.info(
        "Silent refresh failed for '%s' — trying automated re-login.",
        account,
    )
    if notify_fn:
        notify_fn(
            f"Session expired for *{account}* — running automated re-login..."
        )

    result = capture_session(account)
    if result and notify_fn:
        notify_fn(f"✅ Automated re-login succeeded for *{account}*.")
    return result


# ── Interactive browser login ─────────────────────────────────────────────────

def capture_session(account: str = "primary", status_callback=None) -> bool:
    """
    Save a fresh USCIS session for *account*.

    If USCIS_EMAIL / USCIS_PASSWORD / GMAIL_APP_PASSWORD are set for the
    account (see account_credentials.py), runs fully automated Playwright
    login with email MFA. Otherwise opens Chrome for manual login via CDP.
    """
    def _cb(msg):
        logger.info(msg)
        if status_callback:
            status_callback(msg)

    from account_credentials import load_account_credentials

    with _chrome_profile_lock(account):
        return _capture_session_locked(
            account, status_callback, _cb,
        )


def _capture_session_locked(
    account: str,
    status_callback,
    _cb,
) -> bool:
    creds = None
    result = None
    profile_path = None
    port = 0
    profile_dir = ""
    proc = None
    logged_in = False
    deadline = 0.0
    cookies = []
    extra_headers = {}
    local_storage = {}

    from account_credentials import load_account_credentials

    _last_capture_error.pop(account, None)
    creds = load_account_credentials(account)
    if creds:
        from uscis_auto_login import automated_login_capture

        profile_path = _chrome_profile_dir(account)
        _clear_chrome_locks(profile_path)
        result = automated_login_capture(
            profile_path,
            creds["email"],
            creds["password"],
            creds["gmail_app_password"],
            account=account,
            headless=True,
            status_callback=status_callback,
        )
        if not result:
            return False
        cookies, extra_headers, local_storage = result
        save_session(cookies, extra_headers, account, local_storage)
        _cb(
            f"Session saved for '{account}' — "
            f"{len(cookies)} cookies (automated login)."
        )
        return True

    if not _find_chrome():
        _cb("Chrome not found. Please install Google Chrome.")
        return False

    profile_path = _chrome_profile_dir(account)
    _clear_chrome_locks(profile_path)
    port = _free_port()
    profile_dir = str(profile_path)

    _cb(f"Launching Chrome for '{account}' account...")
    try:
        proc = _launch_chrome(port, profile_dir, USCIS_LOGIN_URL, headless=False)
    except Exception as exc:
        _cb(f"Failed to launch Chrome: {exc}")
        return False

    if not _wait_for_cdp(port):
        _cb("Chrome did not start in time.")
        proc.terminate()
        return False

    _cb("Waiting for you to log in — the browser will close automatically.")

    # Poll the tab URL every 2 seconds until we see the authenticated dashboard
    logged_in = False
    deadline = time.time() + _LOGIN_TIMEOUT
    while time.time() < deadline:
        for tab in _tab_list(port):
            if any(m in tab.get("url", "") for m in _LOGIN_MARKERS):
                logged_in = True
                break
        if logged_in:
            break
        time.sleep(1)

    if not logged_in:
        _cb("Login timed out (5 minutes). Try `/relogin` again.")
        proc.terminate()
        return False

    # Wait a moment for any final token-refresh XHR calls to complete
    _cb("Login detected — capturing session...")
    time.sleep(4)

    cookies: list = []
    extra_headers: dict = {}
    local_storage: dict = {}
    try:
        cookies, extra_headers, local_storage = _capture_from_tab(port)
    except Exception as exc:
        logger.exception("Cookie capture failed for '%s': %s", account, exc)
        _cb(f"Could not capture cookies: {exc}")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        time.sleep(1)
        # Persistent profile dir is intentionally kept — reused by silent_refresh_session

    if not cookies:
        _cb("No cookies captured — please try again.")
        return False

    save_session(cookies, extra_headers, account, local_storage)
    _cb(f"Session saved for '{account}' — {len(cookies)} cookies captured.")
    return True


# ── Silent (headless) session refresh ────────────────────────────────────────

def silent_refresh_session(account: str = "primary", notify_fn=None) -> bool:
    """
    Keep the authenticated myUSCIS session alive.

    Relaunches headless Chrome on the SAME persistent profile used at login —
    so it already holds the live Rails session cookies plus the short-lived
    Akamai/AWS-WAF bot tokens (__cf_bm, aws-waf-token, bm_sv, …) that a plain
    `requests` poll cannot regenerate on its own. Navigating to the dashboard
    with a real browser refreshes those tokens and re-stamps the session, then
    we capture the full fresh jar back to disk.

    We deliberately do NOT re-inject the previously-saved cookies before
    navigating: the on-disk .enc is only ever a snapshot of a past capture, so
    it can never be fresher than the profile's own jar — injecting it can only
    clobber good cookies with stale values.

    Returns True on success, False if a full re-login is needed.
    """
    def _alert(msg):
        logger.info("Silent refresh [%s]: %s", account, msg)
        if notify_fn:
            notify_fn(msg)

    data = load_session(account)
    if not data:
        return False

    with _chrome_profile_lock(account):
        return _silent_refresh_locked(account, data, notify_fn, _alert)


def _silent_refresh_locked(account, data, notify_fn, _alert) -> bool:
    port = 0
    profile_path = None
    profile_dir = ""
    proc = None
    success = False
    auto_relogin = False

    if not _find_chrome():
        _alert("Chrome not found — cannot refresh session.")
        return False

    port = _free_port()
    profile_path = _chrome_profile_dir(account)
    profile_dir = str(profile_path)

    # Clear any stale lock files left by a previously crashed Chrome process.
    # A locked profile causes headless Chrome to exit immediately without ever
    # exposing the CDP endpoint (shows as "Headless Chrome did not start").
    _clear_chrome_locks(profile_path)

    try:
        # Start headless Chrome on about:blank so we can inject cookies before
        # navigating — avoids the race where Chrome opens the dashboard before
        # the CDP session is ready to set cookies.
        proc = _launch_chrome(port, profile_dir, "about:blank", headless=True)
    except Exception as exc:
        _alert(f"Could not launch headless Chrome: {exc}")
        return False

    if not _wait_for_cdp(port):
        _alert("Headless Chrome did not start.")
        proc.terminate()
        return False

    try:
        import websocket

        tab = _find_uscis_tab(port)
        if not tab:
            raise RuntimeError("No debuggable tab in headless Chrome")

        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=20)
        cmd = 1

        _cdp_send(ws, "Network.enable", {}, cmd); cmd += 1
        _cdp_send(ws, "Page.enable", {}, cmd); cmd += 1

        # No cookie injection — the persistent profile already carries the live
        # session + WAF jar (see docstring). Just navigate the dashboard with a
        # real browser so Akamai/AWS-WAF re-issue their bot tokens and the Rails
        # session is re-stamped.
        _cdp_send(ws, "Page.navigate", {"url": USCIS_DASHBOARD_URL}, cmd); cmd += 1

        # Let the page (and any bot-protection JS challenge) settle before capture
        time.sleep(25)

        # Check we landed on an authenticated page (not redirected to login)
        result = _cdp_send(ws, "Runtime.evaluate",
                           {"expression": "window.location.href", "returnByValue": True}, cmd)
        cmd += 1
        current_url = result.get("result", {}).get("value", "")
        logger.info("Silent refresh [%s] landed on: %s", account, current_url)

        if "login" in current_url or "my.uscis.gov" not in current_url:
            ws.close()
            auto_relogin = True
            return False

        # Get fresh cookies
        result = _cdp_send(ws, "Network.getAllCookies", {}, cmd); cmd += 1
        raw = result.get("cookies", [])
        logger.info("Silent refresh [%s]: %d cookies collected", account, len(raw))

        # Get auth token from localStorage
        extra_headers: dict = {}
        token_js = """(function(){
            try {
                var keys = Object.keys(localStorage);
                for (var i = 0; i < keys.length; i++) {
                    var v = localStorage.getItem(keys[i]);
                    if (!v) continue;
                    try {
                        var obj = JSON.parse(v);
                        if (obj && obj.accessToken && obj.accessToken.accessToken)
                            return 'Bearer ' + obj.accessToken.accessToken;
                    } catch(e) {}
                }
            } catch(e) {}
            return '';
        })()"""
        try:
            result = _cdp_send(ws, "Runtime.evaluate",
                               {"expression": token_js, "returnByValue": True}, cmd)
            cmd += 1
            token = result.get("result", {}).get("value", "")
            if token:
                extra_headers["Authorization"] = token
        except Exception:
            pass

        # Capture refreshed localStorage (updated Okta tokens)
        new_local_storage: dict = {}
        ls_js = """(function(){
            try {
                var out = {};
                var keys = Object.keys(localStorage);
                for (var i = 0; i < keys.length; i++) {
                    out[keys[i]] = localStorage.getItem(keys[i]);
                }
                return JSON.stringify(out);
            } catch(e) { return '{}'; }
        })()"""
        try:
            result = _cdp_send(ws, "Runtime.evaluate",
                               {"expression": ls_js, "returnByValue": True}, cmd)
            cmd += 1
            new_local_storage = json.loads(
                result.get("result", {}).get("value", "{}") or "{}"
            )
        except Exception:
            pass

        ws.close()

        if not raw:
            _alert(f"Silent refresh captured no cookies for *{account}*.")
            return False

        cookies = [_normalize_cdp_cookie(c) for c in raw]

        # Verify new cookies in memory BEFORE saving — the Chrome profile can
        # serve a cached page that looks authenticated while the actual session
        # is dead. If we save first and verify second, we destroy good working
        # cookies before we know the new ones are bad.
        import requests as _req
        test_sess = _req.Session()
        for c in cookies:
            test_sess.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", ""), path=c.get("path", "/"),
            )
        if extra_headers:
            test_sess.headers.update(extra_headers)
        test_sess.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        })
        try:
            r = test_sess.get("https://my.uscis.gov/api/cases", timeout=10)
            if r.status_code in (401, 403):
                logger.warning(
                    "Silent refresh [%s]: new cookies are dead (HTTP %d) — keeping existing session.",
                    account, r.status_code,
                )
                auto_relogin = True
                return False
        except Exception as exc:
            logger.warning("Silent refresh [%s]: pre-save verify error: %s — saving anyway.", account, exc)

        save_session(cookies, extra_headers, account,
                     new_local_storage or data.get("local_storage") or {})
        logger.info("Silent refresh succeeded for '%s'.", account)

        # Warn if an auth cookie carries an absolute expiry that's approaching.
        # Some myUSCIS auth cookies are session-only (no expiry) — in that case
        # the deadline is server-side and we simply can't see it, so no warning.
        # When an expiry IS present, no amount of keep-alive can push past it.
        # We warn at 8 hours so the user can re-login before a long absence.
        # The _expiry_warned set sends at most one warning per account per
        # process lifetime so the alert isn't repeated every refresh cycle.
        try:
            earliest = None
            for c in raw:
                if c.get("name") in _SESSION_COOKIE_NAMES:
                    exp = c.get("expires", 0)
                    if exp and exp > 0 and (earliest is None or exp < earliest):
                        earliest = exp
            if earliest is not None:
                remaining = earliest - time.time()
                if remaining < 8 * 3600 and account not in _expiry_warned:
                    _expiry_warned.add(account)
                    hours = int(remaining / 3600)
                    mins = int((remaining % 3600) / 60)
                    time_str = f"{hours}h {mins}min" if hours else f"{mins} min"
                    _alert(
                        f"⚠️ USCIS session for *{account}* expires in ~{time_str}.\n"
                        f"Run `/relogin {account}` before it expires."
                    )
        except Exception:
            pass

        success = True

    except Exception as exc:
        logger.exception("Silent refresh error for '%s': %s", account, exc)
        _alert(
            f"Silent refresh error for *{account}*: {exc}\n"
            f"If monitoring stops, run `/relogin {account}` in Telegram."
        )
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        time.sleep(1)
        # Persistent profile dir is intentionally kept

    if auto_relogin:
        if _try_automated_relogin(account, _alert):
            return True
        _alert(
            f"Session for *{account}* has fully expired — silent refresh failed.\n"
            f"Run `/relogin {account}` in Telegram."
        )
        return False

    return success


# ── Build requests.Session from saved data ────────────────────────────────────

def build_requests_session(account: str = "primary"):
    """Returns a requests.Session for the given account, or None if no session."""
    import requests

    data = load_session(account)
    if not data:
        return None

    session = requests.Session()
    for c in data.get("cookies", []):
        session.cookies.set(
            c["name"], c["value"],
            domain=c.get("domain", ""), path=c.get("path", "/"),
        )
    if data.get("headers"):
        session.headers.update(data["headers"])
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    })
    return session
