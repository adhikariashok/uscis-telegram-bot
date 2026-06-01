"""
Fetches USCIS case data.

Strategy:
  1. Try authenticated my.uscis.gov API with saved session cookies.
  2. Fall back to public egov.uscis.gov API with browser-like headers.

Returns a normalised dict:
  {
    "receipt_number": str,
    "status": str,
    "description": str,
    "updated_at": str,
    "events": list,
    "raw": dict,
  }
"""
import hashlib
import json
import logging
import requests
from config import load_config
from auth_manager import build_requests_session

logger = logging.getLogger(__name__)

# ── Public session (egov.uscis.gov) ──────────────────────────────────────────

_PUBLIC_BASE = "https://egov.uscis.gov"
_PUBLIC_API  = _PUBLIC_BASE + "/case-status/api/cases/{receipt_number}"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": _PUBLIC_BASE,
    "Referer": _PUBLIC_BASE + "/casestatus/landing.do",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Connection": "keep-alive",
}

_public_session = requests.Session()
_public_session.headers.update(_BROWSER_HEADERS)
_public_warmed = False


def _warm_public_session():
    """Visit the landing page once to pick up any required session cookies."""
    global _public_warmed
    if _public_warmed:
        return
    try:
        _public_session.get(_PUBLIC_BASE + "/casestatus/landing.do", timeout=10)
        _public_warmed = True
    except Exception as exc:
        logger.debug("Could not warm public session: %s", exc)


# ── Authenticated session (my.uscis.gov) ─────────────────────────────────────

# Possible endpoints to try in order
_MY_USCIS_ENDPOINTS = [
    "https://my.uscis.gov/account/case-service/api/cases/{receipt_number}",
    "https://my.uscis.gov/api/cases/{receipt_number}",
]


# ── Response parsers ──────────────────────────────────────────────────────────

def _parse_public(data: dict, receipt: str) -> dict:
    cases = data.get("cases") or []
    case = cases[0] if cases else data
    return {
        "receipt_number": receipt,
        "status": case.get("status") or case.get("formType") or "Unknown",
        "description": case.get("description") or "",
        "updated_at": case.get("updatedDate") or "",
        "events": [],
        "raw": data,
    }


def _parse_my_uscis(data: dict, receipt: str) -> dict:
    # Unwrap the "data" envelope used by account/case-service API
    d = data.get("data", data)

    # Derive a human-readable status from available flags
    if d.get("areAllGroupStatusesComplete"):
        status = "Case Complete"
    elif d.get("actionRequired"):
        status = "Action Required"
    elif d.get("closed"):
        status = "Case Closed"
    else:
        status = "In Progress"

    form = d.get("formType") or ""
    form_name = d.get("formName") or ""
    updated = d.get("updatedAtTimestamp") or d.get("updatedAt") or ""

    events  = d.get("events",  []) if isinstance(d.get("events"),  list) else []
    notices = d.get("notices", []) if isinstance(d.get("notices"), list) else []

    # Build description line
    parts = []
    if form:
        parts.append(f"Form {form}")
    if form_name:
        parts.append(form_name)
    if d.get("applicantName"):
        parts.append(f"Applicant: {d['applicantName']}")
    desc = " — ".join(parts)

    # Latest notice summary
    if notices:
        n = notices[-1]
        action = n.get("actionType", "")
        appt   = n.get("appointmentDateTime", "")
        if action:
            desc += f"\nLatest notice: {action}"
            if appt:
                desc += f" ({appt[:10]})"

    return {
        "receipt_number": receipt,
        "status": status,
        "description": desc,
        "updated_at": str(updated),
        "events": events + notices,   # track both for change detection
        "raw": data,
    }


def _events_hash(case_data: dict) -> str:
    payload = json.dumps(
        {
            "status": case_data["status"],
            "updated_at": case_data["updated_at"],
            "events": case_data["events"],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ── Main fetch function ───────────────────────────────────────────────────────

def fetch_case(receipt_number: str, account: str = "primary",
               _retry_after_refresh: bool = True) -> dict | None:
    """
    Returns normalised case dict (with 'events_hash' key) or None on failure.
    When the auth session is expired and cannot be silently refreshed, falls
    back to the public egov API so monitoring continues in degraded mode.
    The returned dict includes '_session_expired': True in that case so the
    caller can notify the user to re-login.
    """
    receipt = receipt_number.upper()
    session_expired = False

    # ── 1. Authenticated my.uscis.gov ─────────────────────────────────────────
    auth_session = build_requests_session(account)
    if auth_session:
        for endpoint_tpl in _MY_USCIS_ENDPOINTS:
            url = endpoint_tpl.format(receipt_number=receipt)
            try:
                resp = auth_session.get(url, timeout=20)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        continue
                    result = _parse_my_uscis(data, receipt)
                    result["events_hash"] = _events_hash(result)
                    logger.info("Fetched %s via authenticated API (%s)", receipt, url)
                    return result
                if resp.status_code in (401, 403):
                    logger.warning(
                        "Auth session rejected at %s (HTTP %d) — attempting silent refresh",
                        url, resp.status_code,
                    )
                    if _retry_after_refresh:
                        from auth_manager import silent_refresh_session
                        ok = silent_refresh_session(account)
                        if ok:
                            logger.info("Silent refresh succeeded — retrying fetch for %s", receipt)
                            return fetch_case(receipt, account, _retry_after_refresh=False)
                    # Silent refresh failed (or skipped on retry); mark expired and
                    # fall through to public API so monitoring continues.
                    session_expired = True
                    break
            except Exception as exc:
                logger.warning("Auth endpoint %s error: %s", url, exc)

    # ── 2. Public egov.uscis.gov ──────────────────────────────────────────────
    _warm_public_session()
    url = _PUBLIC_API.format(receipt_number=receipt)
    try:
        resp = _public_session.get(url, timeout=20)
        if resp.status_code == 200:
            result = _parse_public(resp.json(), receipt)
            result["events_hash"] = _events_hash(result)
            if session_expired:
                result["_session_expired"] = True
                result["account"] = account
            logger.info("Fetched %s via public API%s", receipt,
                        " (auth expired)" if session_expired else "")
            return result
        logger.warning("Public API returned HTTP %d for %s", resp.status_code, receipt)
    except Exception as exc:
        logger.error("Public API failed for %s: %s", receipt, exc)

    if session_expired:
        return {"_session_expired": True, "receipt_number": receipt, "account": account}
    return None


def verify_session() -> bool:
    """Quick check: does the saved session still work?"""
    auth_session = build_requests_session()
    if not auth_session:
        return False
    try:
        resp = auth_session.get("https://my.uscis.gov/api/cases", timeout=10)
        return resp.status_code not in (401, 403)
    except Exception:
        return False
