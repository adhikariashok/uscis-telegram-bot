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
import time
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet
from config import APP_DIR, KEY_PATH, USCIS_LOGIN_URL, USCIS_DASHBOARD_URL

logger = logging.getLogger(__name__)


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


def _wait_for_cdp(port: int, timeout: float = 20.0) -> bool:
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
        args += ["--headless=new", "--window-size=1920,1080"]
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

    cookies = [
        {
            "name": c["name"], "value": c["value"],
            "domain": c.get("domain", ""), "path": c.get("path", "/"),
            "secure": c.get("secure", False),
        }
        for c in raw_cookies
    ]
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
    Opens real Chrome (no Selenium/WebDriver — completely undetectable),
    waits for the user to finish logging in by watching the tab URL via CDP,
    then captures cookies automatically and closes Chrome.
    No dialogs or prompts shown to the user.
    """
    def _cb(msg):
        logger.info(msg)
        if status_callback:
            status_callback(msg)

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
        _cb("Login timed out (5 minutes). Please try again from the tray icon.")
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
    Headless Chrome loads existing cookies, navigates to the dashboard so the
    browser silently refreshes OAuth tokens, then saves the fresh cookies.
    Returns True on success, False if a full re-login is needed.
    """
    def _alert(msg):
        logger.info("Silent refresh [%s]: %s", account, msg)
        if notify_fn:
            notify_fn(msg)

    data = load_session(account)
    if not data:
        return False

    if not _find_chrome():
        _alert("Chrome not found — cannot refresh session.")
        return False

    port = _free_port()
    # Reuse the persistent profile from login — preserves Okta cookies, localStorage,
    # and IndexedDB so the Okta SDK can silently renew the refresh token itself.
    profile_dir = str(_chrome_profile_dir(account))

    try:
        proc = _launch_chrome(port, profile_dir, USCIS_DASHBOARD_URL, headless=True)
    except Exception as exc:
        _alert(f"Could not launch headless Chrome: {exc}")
        return False

    if not _wait_for_cdp(port):
        _alert("Headless Chrome did not start.")
        proc.terminate()
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

        # Wait for Okta SDK to silently renew tokens via the profile's stored state
        time.sleep(10)

        # Check we landed on an authenticated page (not redirected to login)
        result = _cdp_send(ws, "Runtime.evaluate",
                           {"expression": "window.location.href", "returnByValue": True}, cmd)
        cmd += 1
        current_url = result.get("result", {}).get("value", "")
        logger.info("Silent refresh [%s] landed on: %s", account, current_url)

        if "login" in current_url or "my.uscis.gov" not in current_url:
            ws.close()
            _alert(
                f"Session for *{account}* has fully expired — silent refresh failed.\n"
                "Please re-login via the tray icon."
            )
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

        cookies = [
            {
                "name": c["name"], "value": c["value"],
                "domain": c.get("domain", ""), "path": c.get("path", "/"),
                "secure": c.get("secure", False),
            }
            for c in raw
        ]

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
                _alert(
                    f"⚠️ Session for *{account}* has fully expired — silent refresh failed.\n"
                    "Please re-login via the tray icon."
                )
                return False
        except Exception as exc:
            logger.warning("Silent refresh [%s]: pre-save verify error: %s — saving anyway.", account, exc)

        save_session(cookies, extra_headers, account,
                     new_local_storage or data.get("local_storage") or {})
        logger.info("Silent refresh succeeded for '%s'.", account)

        # Warn if the Okta session cookie will expire soon (3-hour hard limit).
        # The sid cookie carries the absolute session expiry set at login time;
        # no amount of token renewal can push it past that boundary.
        try:
            for c in raw:
                if c.get("name") in ("sid", "JSESSIONID", "usi_session"):
                    exp = c.get("expires", 0)
                    if exp and exp > 0:
                        remaining = exp - time.time()
                        if remaining < 3600:
                            mins = int(remaining / 60)
                            _alert(
                                f"⚠️ USCIS session for *{account}* expires in ~{mins} min.\n"
                                "Please re-login via the tray icon to avoid interruption."
                            )
        except Exception:
            pass

        success = True

    except Exception as exc:
        logger.exception("Silent refresh error for '%s': %s", account, exc)
        _alert(
            f"Silent refresh error for *{account}*: {exc}\n"
            "Please re-login via the tray icon if monitoring stops."
        )
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
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
