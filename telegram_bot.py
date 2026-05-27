"""
Telegram bot — users interact here to register cases and receive notifications.

Commands:
  /start              — welcome + instructions
  /register <number>  — start monitoring a case
  /unregister <number>— stop monitoring a case
  /status [number]    — check current status now
  /list               — show all tracked cases
  /help               — show help
"""
import asyncio
import logging
import threading
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode
from database import upsert_user, add_case, remove_case, get_user_cases
from uscis_client import fetch_case
from auth_manager import list_accounts

logger = logging.getLogger(__name__)

_app: Application | None = None
_loop: asyncio.AbstractEventLoop | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _reply(update: Update, text: str, markdown=True):
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN if markdown else None,
    )


def _register_user(update: Update):
    user = update.effective_user
    upsert_user(user.id, user.username or user.first_name or "")


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    await _reply(
        update,
        "👋 *USCIS Case Monitor Bot*\n\n"
        "I notify you whenever your USCIS case status or timeline changes.\n\n"
        "*Commands:*\n"
        "`/register IOE123` — monitor a case (primary account)\n"
        "`/register IOE123 wife` — monitor a case under a named account\n"
        "`/unregister IOE123` — stop monitoring a case\n"
        "`/status` — check all your cases right now\n"
        "`/status wife` — check all cases under a specific account\n"
        "`/status IOE123` — check one specific case\n"
        "`/list` — show all cases you're tracking\n"
        "`/accounts` — show saved USCIS accounts\n"
        "`/addaccount wife` — instructions to add a new account\n"
        "`/help` — show this message",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    if not ctx.args:
        await _reply(update, "Usage: `/register IOE1234567890 [account]`\nExample: `/register IOE123 wife`")
        return

    receipt = ctx.args[0].upper().strip()
    account = ctx.args[1].lower().strip() if len(ctx.args) > 1 else "primary"

    if len(receipt) < 7 or not receipt[:3].isalpha():
        await _reply(update, "❌ That doesn't look like a valid receipt number (e.g. `IOE1234567890`).")
        return

    from auth_manager import has_session
    if not has_session(account):
        await _reply(
            update,
            f"⚠️ No saved session for account *{account}*.\n"
            f"Right-click the tray icon → *Add Account* → type `{account}` to log in first.",
        )
        return

    added = add_case(update.effective_user.id, receipt, account)
    if added:
        await _reply(update, f"✅ `{receipt}` added under *{account}* account.")
    else:
        await _reply(update, f"ℹ️ `{receipt}` is already in your monitoring list.")


async def cmd_accounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    accounts = list_accounts()
    if not accounts:
        await _reply(update, "No USCIS accounts saved yet.")
        return
    lines = ["*Saved USCIS accounts:*\n"]
    for a in accounts:
        lines.append(f"• {a}")
    lines.append("\nTo add a new account, right-click the tray icon → *Add Account*.")
    await _reply(update, "\n".join(lines))


async def cmd_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    name = ctx.args[0].lower().strip() if ctx.args else "new"
    await _reply(
        update,
        f"To add the *{name}* account:\n\n"
        f"1. Right-click the *USCIS Monitor* tray icon (bottom-right taskbar)\n"
        f"2. Click *Add Account*\n"
        f"3. Type `{name}` when prompted\n"
        f"4. Log in to myUSCIS in the Chrome window that opens\n\n"
        f"Then register cases with:\n`/register IOE123456 {name}`",
    )


async def cmd_unregister(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    if not ctx.args:
        await _reply(update, "Usage: `/unregister IOE1234567890`")
        return

    receipt = ctx.args[0].upper().strip()
    removed = remove_case(update.effective_user.id, receipt)
    if removed:
        await _reply(update, f"✅ Stopped monitoring `{receipt}`.")
    else:
        await _reply(update, f"❌ `{receipt}` not found in your list.")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    cases = get_user_cases(update.effective_user.id)
    if not cases:
        await _reply(update, "You have no cases being monitored. Use `/register <number>` to add one.")
        return

    lines = ["*Your monitored cases:*\n"]
    for c in cases:
        status = c.get("last_status") or "Not checked yet"
        updated = c.get("last_updated_at") or "—"
        account = c.get("account") or "primary"
        lines.append(f"• `{c['receipt_number']}` _(account: {account})_\n  Status: {status}\n  Updated: {updated}")
    await _reply(update, "\n\n".join(lines))


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    uid = update.effective_user.id

    all_cases = get_user_cases(uid)
    if ctx.args:
        arg = ctx.args[0].strip()
        # Receipt numbers are 3 alpha chars followed by digits (e.g. IOE1234567890)
        # Anything else is treated as an account name filter
        if len(arg) >= 7 and arg[:3].isalpha() and arg[3:].isdigit():
            target = arg.upper()
            matched = [c for c in all_cases if c["receipt_number"] == target]
            cases_to_check = matched if matched else [{"receipt_number": target, "account": "primary"}]
        else:
            account_filter = arg.lower()
            cases_to_check = [c for c in all_cases if (c.get("account") or "primary") == account_filter]
            if not cases_to_check:
                await _reply(update, f"No cases found under account *{account_filter}*.")
                return
    else:
        cases_to_check = all_cases

    if not cases_to_check:
        await _reply(update, "No cases found. Use `/register <number>` first.")
        return

    await _reply(update, "⏳ Checking status, please wait…")

    for case_row in cases_to_check:
        receipt = case_row["receipt_number"]
        account = case_row.get("account") or "primary"
        result = await asyncio.get_event_loop().run_in_executor(
            None, fetch_case, receipt, account
        )
        if result is None:
            await _reply(update, f"❌ Could not fetch status for `{receipt}`. Try again later.")
        elif result.get("_session_expired"):
            await _reply(
                update,
                "⚠️ USCIS session expired. Please re-login via the Windows tray app.",
            )
        else:
            events_text = ""
            for ev in result.get("events", [])[:5]:
                ts = (ev.get("eventTimestamp") or ev.get("createdAtTimestamp")
                      or ev.get("appointmentDateTime") or ev.get("timestamp")
                      or ev.get("date") or "")[:10]
                label = (ev.get("eventCode") or ev.get("actionType")
                         or ev.get("description") or ev.get("title") or "")
                if label:
                    events_text += f"\n• {ts} — {label}"

            msg = (
                f"📋 *Case Status*\n\n"
                f"*Case:* `{receipt}`\n"
                f"*Status:* {result['status']}\n"
                f"*Updated:* {result['updated_at']}"
            )
            if result.get("description"):
                msg += f"\n\n{result['description'][:500]}"
            if events_text:
                msg += f"\n\n*Timeline:*{events_text}"
            await _reply(update, msg)


async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _reply(update, "Unknown command. Try /help.", markdown=False)


# ── Bot runner (fully inside async context) ───────────────────────────────────

async def _bot_main(token: str):
    """
    Builds and runs the bot entirely inside an async context so that
    asyncio.Event() in Application.__init__ has a running event loop.
    Compatible with Python 3.13.
    """
    global _app

    _app = Application.builder().token(token).build()

    _app.add_handler(CommandHandler("start", cmd_start))
    _app.add_handler(CommandHandler("help", cmd_help))
    _app.add_handler(CommandHandler("register", cmd_register))
    _app.add_handler(CommandHandler("unregister", cmd_unregister))
    _app.add_handler(CommandHandler("list", cmd_list))
    _app.add_handler(CommandHandler("status", cmd_status))
    _app.add_handler(CommandHandler("accounts", cmd_accounts))
    _app.add_handler(CommandHandler("addaccount", cmd_addaccount))
    _app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    async with _app:
        await _app.start()
        await _app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot polling started.")
        # Block until the event is set (i.e. forever, or until stop() is called)
        await asyncio.Event().wait()


# ── Cross-thread notification sender ─────────────────────────────────────────

def send_notification(telegram_id: int, message: str):
    """Called from the monitor thread to push a message to a user."""
    if _app is None or _loop is None:
        logger.warning("Bot not running — cannot notify user %d", telegram_id)
        return

    async def _send():
        try:
            await _app.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:
            logger.error("Failed to send notification to %d: %s", telegram_id, exc)

    asyncio.run_coroutine_threadsafe(_send(), _loop)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def _run_bot(token: str):
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_bot_main(token))
    except Exception:
        logger.exception("Telegram bot thread crashed.")


def start(token: str) -> threading.Thread:
    t = threading.Thread(target=_run_bot, args=(token,), daemon=True, name="TelegramBot")
    t.start()
    return t


def stop():
    if _loop:
        _loop.call_soon_threadsafe(_loop.stop)
