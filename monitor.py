"""
Background polling scheduler.
Checks all registered cases every POLL_INTERVAL_SECONDS and fires
send_notification(telegram_id, message) for any case that changed.
"""
import json
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from config import load_config
from database import get_all_cases, update_case_status, log_case_history, get_last_history_entry

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_notify_fn = None   # set by start()
_seen_this_session: set[str] = set()  # receipt numbers polled at least once since startup


def _check_all():
    from uscis_client import fetch_case

    cases = get_all_cases()
    if not cases:
        return

    session_expired_notified = set()

    for case in cases:
        receipt = case["receipt_number"]
        tid = case["telegram_id"]
        account = case.get("account", "primary")
        logger.info("Checking %s (%s) for user %d", receipt, account, tid)

        result = fetch_case(receipt, account)
        if result is None:
            logger.warning("No data returned for %s", receipt)
            continue

        # Session expired — notify the user once per poll cycle, but still
        # process whatever public-API data came back so status updates continue.
        if result.get("_session_expired"):
            key = (tid, account)
            if key not in session_expired_notified:
                if _notify_fn:
                    _notify_fn(
                        tid,
                        f"⚠️ USCIS session expired for *{account}* account.\n"
                        "Monitoring continues via public API (limited data).\n"
                        f"Run `/relogin {account}` to restore full monitoring.",
                    )
                session_expired_notified.add(key)

        # If there's no status (pure error sentinel with no public-API fallback), skip
        if not result.get("status"):
            continue

        new_status = result["status"]
        new_updated = result["updated_at"]
        new_hash = result["events_hash"]

        # Compare with stored values
        old_status = case.get("last_status")
        old_hash = case.get("last_events_hash")

        changed = (old_status != new_status) or (old_hash and old_hash != new_hash)
        first_poll = receipt not in _seen_this_session
        _seen_this_session.add(receipt)

        # On first poll after startup, log a baseline only if history is empty
        # or the last recorded entry differs — avoids duplicates across restarts
        if first_poll and not changed:
            last = get_last_history_entry(receipt, tid)
            first_poll = (
                last is None
                or last.get("status") != new_status
                or last.get("updated_at") != new_updated
            )

        # Always update the DB (even if unchanged, to refresh last_checked)
        update_case_status(receipt, new_status, new_updated, new_hash)

        if changed or first_poll:
            log_case_history(
                receipt, tid, account,
                new_status, new_updated, new_hash,
                json.dumps(result.get("events", [])),
            )

        if changed and _notify_fn:
            events_text = ""
            for ev in result.get("events", [])[:3]:
                ts = (ev.get("eventTimestamp") or ev.get("createdAtTimestamp")
                      or ev.get("timestamp") or ev.get("date") or "")[:10]
                label = (ev.get("eventCode") or ev.get("actionType")
                         or ev.get("description") or ev.get("title") or "")
                if label:
                    events_text += f"\n• {ts} — {label}"

            msg = (
                f"🔔 *USCIS Case Update*\n\n"
                f"*Case:* `{receipt}`\n"
                f"*Status:* {new_status}\n"
                f"*Updated:* {new_updated}"
            )
            if result.get("description"):
                msg += f"\n\n{result['description'][:400]}"
            if events_text:
                msg += f"\n\n*Recent events:*{events_text}"

            logger.info("Change detected for %s — notifying user %d", receipt, tid)
            _notify_fn(tid, msg)


def _refresh_all_sessions():
    """Run the browser-based session keep-alive for every saved account."""
    from auth_manager import list_accounts, silent_refresh_session

    accounts = list_accounts()
    if not accounts:
        return

    for account in accounts:
        def _tg_alert(msg, _acct=account):
            if _notify_fn:
                # Find any telegram_id that has cases under this account
                cases = get_all_cases()
                notified = set()
                for c in cases:
                    if c.get("account", "primary") == _acct:
                        tid = c["telegram_id"]
                        if tid not in notified:
                            _notify_fn(tid, f"[Session refresh] {msg}")
                            notified.add(tid)

        ok = silent_refresh_session(account, notify_fn=_tg_alert)
        if not ok:
            # Telegram alert was already sent inside silent_refresh_session via _tg_alert
            logger.warning("Silent refresh failed for account '%s' — user must re-login.", account)


def start(notify_fn):
    """
    Start the background scheduler.
    notify_fn(telegram_id: int, message: str) sends a Telegram message.
    """
    global _scheduler, _notify_fn
    _notify_fn = notify_fn

    cfg = load_config()
    interval = int(cfg.get("poll_interval", 300))

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _check_all,
        trigger=IntervalTrigger(seconds=interval),
        id="uscis_poll",
        max_instances=1,
        coalesce=True,
    )
    # Browser-based session keep-alive every 20 minutes. myUSCIS auth rides on
    # short-lived Akamai/AWS-WAF bot tokens (e.g. __cf_bm ~30 min) that a plain
    # `requests` poll can't regenerate; a real headless Chrome visit re-issues
    # them. 20 min stays ahead of the ~30-min token TTL so the requests poller
    # never starts hitting expired bot tokens.
    # next_run_time=datetime.now() fires immediately on startup so the session
    # is validated (and any expiry warning sent) without waiting.
    _scheduler.add_job(
        _refresh_all_sessions,
        trigger=IntervalTrigger(minutes=20),
        id="session_refresh",
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Monitor started — polling every %d seconds, refreshing sessions every 20 minutes.", interval)


def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Monitor stopped.")


def trigger_now():
    """Run an immediate check outside the normal schedule."""
    import threading
    t = threading.Thread(target=_check_all, daemon=True)
    t.start()
