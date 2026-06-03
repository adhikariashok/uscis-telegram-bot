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
from pathlib import Path

from cryptography.fernet import Fernet
from config import APP_DIR, KEY_PATH, USCIS_LOGIN_URL, USCIS_DASHBOARD_URL

logger = logging.getLogger(__name__)

# Tracks accounts for which we've already sent a session-expiry warning this
# process lifetime — prevents the warning from firing every 30 minutes.
_expiry_warned: set[str] = set()

# ── Refresh serialization / throttling ────────────────────────────────────────
# Two chrome instances cannot share one --user-data-dir profile. The 5-min poll
# fires one refresh per case on 401, and the 20-min keep-alive fires one per
# account — without coordination these launch overlapping headless Chromes on the
# same profile, which lock each other out ("Headless Chrome did not start") and
# leave orphaned processes. _refresh_lock serializes every browser refresh, and
# _REFRESH_COOLDOWN lets a just-completed refresh be reused instead of relaunched.
_refresh_lock = threading.Lock()
_last_refresh: dict[str, tuple[float, bool]] = {}   # account -> (unix_ts, success)
_REFRESH_COOLDOWN = 180.0  # seconds

# Accounts we've already told the user need a manual re-login this episode.
# Cleared on the next successful refresh so a fresh expiry alerts again.
_relogin_alerted: set[str] = set()

# Last error from an automated/manual capture, surfaced to the user via /relogin.
_last_capture_error: dict[str, str] = {}


def last_capture_error(account: str) -> str:
    return _last_capture_error.get(account, "")


# Backoff for automated (credentialed) re-login: a persistent failure (bad
# password, Gmail hiccup, USCIS markup change) must not hammer the login form and
# trip USCIS's soft-lock. Track consecutive failures + earliest next attempt.
_auto_login_fail: dict[str, int] = {}
_auto_login_next_at: dict[str, float] = {}
_AUTO_LOGIN_BACKOFF = (300, 900, 1800, 3600)   # 5m, 15m, 30m, 60m; last repeats
_AUTO_LOGIN_SOFTLOCK_BACKOFF = 2 * 3600        # 2h if USCIS reports a soft-lock

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


def _kill_chrome(proc: "subprocess.Popen | None", profile_dir: str | None = None) -> None:
    """
    Fully tear down the Chrome we launched.

    proc.terminate()/killing proc.pid is NOT enough: with --headless=new the
    process we Popen is just a launcher that spawns a DETACHED browser process
    (a different parent) and exits. Those children survive, keep the profile's
    LOCK held, and pile up as orphans — which is exactly what then makes the
    next refresh fail with "Headless Chrome did not start".

    So we kill two ways: (1) proc's own process tree, and (2) — the reliable one —
    every chrome.exe whose command line points at THIS account's profile dir.
    Refreshes are serialized per profile by _refresh_lock, so (2) can only ever
    match Chromes from this same refresh.
    """
    try:
        import psutil
    except Exception:
        psutil = None

    if psutil is not None:
        targets = []
        if proc is not None:
            try:
                parent = psutil.Process(proc.pid)
                targets += parent.children(recursive=True) + [parent]
            except psutil.NoSuchProcess:
                pass
        if profile_dir:
            needle = os.path.normcase(os.path.abspath(profile_dir))
            for p in psutil.process_iter(["name", "cmdline"]):
                try:
                    name = (p.info.get("name") or "").lower()
                    if "chrome" not in name:
                        continue
                    cl = os.path.normcase(" ".join(p.info.get("cmdline") or []))
                    if needle in cl:
                        targets.append(p)
                except Exception:
                    pass
        for p in targets:
            try:
                p.kill()
            except Exception:
                pass
        try:
            psutil.wait_procs(targets, timeout=5)
        except Exception:
            pass
        return

    # Fallback when psutil is unavailable: taskkill the launcher's tree.
    if proc is not None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass


def _account_receipt(account: str) -> str | None:
    """A receipt number registered under this account, used to verify auth."""
    try:
        from database import get_all_cases
        for c in get_all_cases():
            if c.get("account", "primary") == account:
                return c["receipt_number"].upper()
    except Exception as exc:
        logger.debug("Could not look up a receipt for '%s': %s", account, exc)
    return None


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


# ── Interactive browser login ─────────────────────────────────────────────────

def capture_session(account: str = "primary", status_callback=None) -> bool:
    """
    Save a fresh USCIS session for `account`.

    If credentials are configured for the account (account_credentials — the
    encrypted store or .env), runs a fully automated Playwright login with the
    Gmail MFA code. Otherwise opens real Chrome for a manual login captured via
    CDP. Serialized on _refresh_lock so it can't race a background session
    refresh on the same profile.
    """
    with _refresh_lock:
        return _capture_session_inner(account, status_callback)


def _capture_session_inner(account: str = "primary", status_callback=None) -> bool:
    """Lock-free capture worker — caller must hold _refresh_lock."""
    def _cb(msg):
        logger.info(msg)
        if status_callback:
            status_callback(msg)

    _last_capture_error.pop(account, None)

    # Automated credentialed login when creds are configured.
    from account_credentials import load_account_credentials
    creds = load_account_credentials(account)
    if creds:
        from uscis_auto_login import automated_login_capture
        profile_path = _chrome_profile_dir(account)
        _kill_chrome(None, str(profile_path))   # reap any stragglers on the profile
        _clear_chrome_locks(profile_path)
        result = automated_login_capture(
            profile_path, creds["email"], creds["password"],
            creds["gmail_app_password"], account=account,
            headless=True, status_callback=status_callback,
        )
        if not result:
            return False
        cookies, extra_headers, local_storage = result
        save_session(cookies, extra_headers, account, local_storage)
        _cb(f"Session saved for '{account}' — {len(cookies)} cookies (automated login).")
        return True

    # Manual CDP login (no credentials configured).
    if not _find_chrome():
        _cb("Chrome not found. Please install Google Chrome.")
        return False

    port = _free_port()
    profile_dir = str(_chrome_profile_dir(account))

    _cb(f"Launching Chrome for '{account}' account...")
    try:
        proc = _launch_chrome(port, profile_dir, USCIS_LOGIN_URL, headless=False)
    except Exception as exc:
        _cb(f"Failed to launch Chrome: {exc}")
        return False

    if not _wait_for_cdp(port):
        _cb("Chrome did not start in time.")
        _kill_chrome(proc, profile_dir)
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
        _cb("Login timed out (5 minutes). Please try again from the tray icon.")
        _kill_chrome(proc, profile_dir)
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
        _kill_chrome(proc, profile_dir)
        time.sleep(1)
        # Persistent profile dir is intentionally kept — reused by silent_refresh_session

    if not cookies:
        _cb("No cookies captured — please try again.")
        return False

    save_session(cookies, extra_headers, account, local_storage)
    _cb(f"Session saved for '{account}' — {len(cookies)} cookies captured.")
    return True


# ── Automated credentialed re-login (fallback past the ~8h cap) ───────────────

def _alert_manual_relogin(account: str, notify_fn=None) -> None:
    """One 'please re-login' message per expiry episode (re-armed on success)."""
    if account in _relogin_alerted:
        return
    _relogin_alerted.add(account)
    from account_credentials import has_auto_login_credentials
    if has_auto_login_credentials(account):
        msg = (
            f"⚠️ USCIS session for *{account}* expired and automated re-login "
            "did not succeed (will keep retrying with backoff).\n"
            f"If it persists, run `/relogin {account}` in Telegram."
        )
    else:
        msg = (
            f"⚠️ USCIS session for *{account}* has fully expired.\n"
            f"Run `/relogin {account}` in Telegram to restore full monitoring."
        )
    logger.info("Silent refresh [%s]: %s", account, msg)
    if notify_fn:
        notify_fn(msg)


def _automated_relogin(account: str, notify_fn=None) -> bool:
    """
    Full credentialed Playwright login (with Gmail MFA) as the fallback when the
    remembered-device silent refresh can no longer renew the session. Throttled
    with exponential backoff so repeated failures can't trip USCIS's soft-lock.
    Caller must hold _refresh_lock (it calls _capture_session_inner directly).
    Returns True on a confirmed fresh session, False otherwise (incl. no creds
    or still within backoff).
    """
    from account_credentials import load_account_credentials
    if not load_account_credentials(account):
        return False  # no creds — only a manual /relogin can recover

    now = time.time()
    next_at = _auto_login_next_at.get(account, 0.0)
    if now < next_at:
        logger.info("Automated re-login [%s]: in backoff %ds more — skipping.",
                    account, int(next_at - now))
        return False

    if notify_fn:
        notify_fn(f"Session for *{account}* expired — attempting automated re-login…")

    ok = False
    try:
        ok = _capture_session_inner(account)   # lock already held by caller
    except Exception as exc:
        logger.exception("Automated re-login error for '%s': %s", account, exc)
        _last_capture_error[account] = str(exc)

    if ok:
        _auto_login_fail.pop(account, None)
        _auto_login_next_at.pop(account, None)
        logger.info("Automated re-login succeeded for '%s'.", account)
        if notify_fn:
            notify_fn(f"✅ Automated re-login succeeded for *{account}* — monitoring restored.")
        return True

    fails = _auto_login_fail.get(account, 0) + 1
    _auto_login_fail[account] = fails
    err = _last_capture_error.get(account, "")
    if "soft-lock" in err.lower():
        delay = _AUTO_LOGIN_SOFTLOCK_BACKOFF
    else:
        delay = _AUTO_LOGIN_BACKOFF[min(fails - 1, len(_AUTO_LOGIN_BACKOFF) - 1)]
    _auto_login_next_at[account] = now + delay
    logger.warning("Automated re-login [%s]: failed (attempt %d), next in %dmin. %s",
                   account, fails, int(delay / 60), err[:160])
    return False


# ── Silent (headless) session refresh ────────────────────────────────────────

def silent_refresh_session(account: str = "primary", notify_fn=None) -> bool:
    """
    Keep the authenticated myUSCIS session alive — and silently re-login when the
    server's hard session cap (~8h, no keep-alive can extend it) is hit.

    Relaunches headless Chrome on the persistent login profile and navigates the
    login entry URL. While the app session is still alive this just re-stamps it;
    once it has expired, hitting the entry URL lets USCIS's remembered-device SSO
    mint a brand-new session with no user interaction — provided MFA isn't
    demanded. Success is confirmed by an in-browser authenticated fetch to the
    real case API returning HTTP 200; a cached SPA shell can fake the landed URL,
    so the URL alone is never trusted. Only verified-good cookies are saved.

    Serialized by _refresh_lock and throttled by _REFRESH_COOLDOWN so the 5-min
    poll (one call per case) and the 20-min keep-alive can never launch
    overlapping headless Chromes on the same profile.

    Returns True if the session is confirmed alive, False if a manual re-login
    is needed (e.g. SSO also expired or MFA required).
    """
    if not load_session(account):
        return False

    with _refresh_lock:
        ts, ok = _last_refresh.get(account, (0.0, False))
        if time.time() - ts < _REFRESH_COOLDOWN:
            logger.info(
                "Silent refresh [%s]: within %ds cooldown — reusing last result (ok=%s)",
                account, int(_REFRESH_COOLDOWN), ok,
            )
            return ok

        result = _do_silent_refresh(account, notify_fn)
        if not result:
            # Remembered-device re-mint failed (session past its ~8h cap). Fall
            # back to a full credentialed login with Gmail MFA, if creds are set.
            result = _automated_relogin(account, notify_fn)
        _last_refresh[account] = (time.time(), result)
        if result:
            _relogin_alerted.discard(account)
            _expiry_warned.discard(account)
        else:
            _alert_manual_relogin(account, notify_fn)
        return result


def _do_silent_refresh(account: str, notify_fn=None) -> bool:
    """Heavy lifting for silent_refresh_session. Assumes the caller holds
    _refresh_lock so no other Chrome is touching this profile."""
    def _alert(msg):
        logger.info("Silent refresh [%s]: %s", account, msg)
        if notify_fn:
            notify_fn(msg)

    if not _find_chrome():
        _alert("Chrome not found — cannot refresh session.")
        return False

    data = load_session(account)
    port = _free_port()
    profile_path = _chrome_profile_dir(account)
    profile_dir = str(profile_path)

    # Clear stale lock files from any previously crashed Chrome so the launch
    # isn't rejected for an "in use" profile.
    _clear_chrome_locks(profile_path)

    try:
        proc = _launch_chrome(port, profile_dir, "about:blank", headless=True)
    except Exception as exc:
        _alert(f"Could not launch headless Chrome: {exc}")
        return False

    if not _wait_for_cdp(port):
        _alert("Headless Chrome did not start.")
        _kill_chrome(proc, profile_dir)
        return False

    success = False
    try:
        import websocket

        tab = _find_uscis_tab(port)
        if not tab:
            raise RuntimeError("No debuggable tab in headless Chrome")

        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=20)
        cmd = 1

        _cdp_send(ws, "Network.enable", {}, cmd); cmd += 1
        _cdp_send(ws, "Page.enable", {}, cmd); cmd += 1

        # Navigate the LOGIN entry URL (not the deep dashboard link): when the app
        # session has hit its cap, this is what triggers the remembered-device SSO
        # handshake that re-mints a fresh session. When it's still alive, the entry
        # URL simply redirects to the dashboard and re-stamps it.
        _cdp_send(ws, "Page.navigate", {"url": USCIS_LOGIN_URL}, cmd); cmd += 1

        # Let navigation, any SSO redirects, and the bot-protection JS settle.
        time.sleep(22)

        result = _cdp_send(ws, "Runtime.evaluate",
                           {"expression": "window.location.href", "returnByValue": True}, cmd)
        cmd += 1
        current_url = result.get("result", {}).get("value", "")
        logger.info("Silent refresh [%s] landed on: %s", account, current_url)

        # Authoritative auth check: make a real authenticated request to the case
        # API from inside the browser (carries the fresh WAF/CF tokens) and require
        # HTTP 200. This both PROVES the session is live and re-stamps it. A cached
        # dashboard shell can render while logged-out, so we never trust the URL.
        receipt = _account_receipt(account)
        api_status = None
        if receipt:
            fetch_js = (
                "(async () => { try {"
                "  const r = await fetch("
                "    'https://my.uscis.gov/account/case-service/api/cases/" + receipt + "',"
                "    {credentials:'include', headers:{'Accept':'application/json'}});"
                "  return r.status;"
                "} catch(e) { return -1; } })()"
            )
            result = _cdp_send(ws, "Runtime.evaluate",
                               {"expression": fetch_js, "returnByValue": True,
                                "awaitPromise": True}, cmd)
            cmd += 1
            api_status = result.get("result", {}).get("value")
            logger.info("Silent refresh [%s]: in-browser API check -> HTTP %s",
                        account, api_status)
            if api_status != 200:
                ws.close()
                return False
        else:
            # No registered case to verify against — fall back to the URL heuristic.
            if "login" in current_url or "my.uscis.gov" not in current_url:
                ws.close()
                return False
            logger.info("Silent refresh [%s]: no receipt to verify with — "
                        "trusting landed URL.", account)

        # Session confirmed alive — capture the fresh jar.
        result = _cdp_send(ws, "Network.getAllCookies", {}, cmd); cmd += 1
        raw = result.get("cookies", [])
        logger.info("Silent refresh [%s]: %d cookies collected", account, len(raw))

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
        save_session(cookies, extra_headers, account,
                     new_local_storage or (data.get("local_storage") if data else {}) or {})
        if api_status == 200:
            logger.info("Silent refresh confirmed live session for '%s' (API 200).", account)
        else:
            logger.info("Silent refresh saved session for '%s'.", account)
        success = True

    except Exception as exc:
        logger.exception("Silent refresh error for '%s': %s", account, exc)
        _alert(
            f"Silent refresh error for *{account}*: {exc}\n"
            "Please re-login via the tray icon if monitoring stops."
        )
    finally:
        _kill_chrome(proc, profile_dir)
        time.sleep(1)
        # Persistent profile dir is intentionally kept

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
