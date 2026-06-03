# USCIS Case Monitor

A USCIS case monitor that watches your case status and sends you a
**Telegram notification the moment anything changes** - new events,
updated timestamps, or a status change.

![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## How it works

```
Your machine (or VPS)        myUSCIS API              Telegram
─────────────────────        ─────────────            ─────────────────
Tray or headless app ──────► Polls every 5 min ──────► Sends you a
                             Authenticated             message if
                             session via Chrome        anything changed
```

- Logs into **my.uscis.gov** once using your real Chrome browser
- Saves the encrypted session and silently refreshes it every 10 minutes
- Polls the authenticated USCIS API every 5 minutes for each
  registered case
- Notifies you via Telegram bot when status, updated timestamp,
  or event timeline changes
- Supports **multiple USCIS accounts** (e.g. yourself + spouse)
- **Optional hands-off auto re-login:** the myUSCIS session has a hard
  ~8-hour server-side lifetime. If you save your credentials (encrypted),
  the app re-logs-in by itself when the session expires — reading the
  two-step verification code straight from Gmail — so monitoring never
  needs manual intervention

---

## Features

- ✅ One-time login — Chrome opens, you log in, session is captured automatically
- ✅ Silent background session refresh — never expires mid-monitoring
- ✅ **Automated re-login with email MFA** — optionally store credentials (encrypted) so the app signs back in by itself at the ~8h session cap, reading the verification code from Gmail
- ✅ Multi-account support — monitor your case and your spouse's case separately
- ✅ Telegram bot interface — register cases and check status from your phone
- ✅ Windows system tray mode - lives quietly in your taskbar
- ✅ macOS/Linux headless mode - run in terminal or as a service
- ✅ Fully local — all data stays on your PC, nothing sent to third parties
- ✅ **Case history tracking** — every status change is recorded with timestamps, never overwritten
- ✅ **Full event history** — every fingerprint receipt, notice, and action is logged and shown in `/history`
- ✅ **CSV report export** — download your full timeline as two spreadsheets (status summary + detailed events) after approval

---

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10 / 11 | Optional tray mode |
| macOS / Linux | Headless mode |
| Python 3.13 | [python.org](https://www.python.org/downloads/) |
| Google Chrome | Any recent version |
| Telegram account | Free |

---

## Quick Start

```
1. Clone or download this repo
2. Double-click install.bat
3. Double-click run.bat
4. Follow the setup wizard
```

See **[SETUP.md](SETUP.md)** for the full setup guide with
screenshots and troubleshooting.

## Run Modes

- `tray` - Windows system tray app (default on Windows)
- `headless` - terminal/server mode (default on macOS/Linux)

Examples:

```bash
# macOS/Linux (headless)
python main.py --mode headless

# Windows tray
python main.py --mode tray
```

Configuration now lives in root `.env`. Start from the template:

```bash
cp .env.example .env
```

Then set at least:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

If you are on Windows and prefer the GUI, you can still run setup:

```bash
python setup_wizard.py
```

---

## Telegram Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and command list |
| `/register IOE1234567890` | Start monitoring a case (primary account) |
| `/register IOE1234567890 wife` | Monitor a case under a named account |
| `/unregister IOE1234567890` | Stop monitoring a case |
| `/status` | Check all your cases right now |
| `/status IOE1234567890` | Check one specific case |
| `/list` | Show all cases you're tracking |
| `/history` | Show full status change history for all your cases |
| `/history IOE1234567890` | Show full status change history for one specific case |
| `/report` | Download your complete case history as two CSV files (summary + events detail) |
| `/accounts` | Show saved USCIS accounts |
| `/addaccount wife` | Add a second account (opens Chrome for a manual login) |
| `/relogin` | Refresh the primary account's session |
| `/relogin wife` | Refresh a named account's session (fully automated if credentials are saved) |
| `/help` | Show all commands |

---

## Case History Tracking & Approval Reports

Every time your case status changes, the bot **permanently records** the change
in a local history log. Unlike the live status (which only shows the latest
snapshot), the history is **append-only** — nothing is ever overwritten or
deleted.

### What gets recorded

Each time your case status or events change, the bot permanently saves:

| Field | What it is |
|---|---|
| `receipt_number` | Your case receipt number |
| `account` | Which USCIS account it belongs to |
| `status` | The case status at the time of the change |
| `uscis_updated_at` | The timestamp USCIS reports on their end |
| `bot_recorded_at_utc` | The exact UTC time the bot detected the change |
| `events_snapshot` | Full JSON snapshot of every event at that moment |

### Checking your history

**See history inline in Telegram:**

```
/history                     → full history for all your cases
/history IOE1234567890       → full history for one specific case
```

Each entry shows the status, the USCIS updated timestamp, and every event
that existed at that point — with the event code looked up from the
official NIEM/USCIS code dictionary so you see a human-readable label:

```
History for IOE1234567890:

• Status: In Progress
  USCIS updated: 2024-11-01T09:15:00

  Events:
  ‣ 2024-10-28 — AAB — AAB RECEIVED - FINGERPRINT FEE
  ‣ 2024-10-30 — ABA — ABA RECEIVED, FEE WAIVED

• Status: Case Complete
  USCIS updated: 2025-03-18T07:30:00

  Events:
  ‣ 2024-10-28 — AAB — AAB RECEIVED - FINGERPRINT FEE
  ‣ 2024-10-30 — ABA — ABA RECEIVED, FEE WAIVED
  ‣ 2025-03-17 — APP — APPROVED
```

### Downloading a report

```
/report
```

The bot sends you **two CSV files**:

**1. `uscis_summary_YYYYMMDD_HHMMSS.csv` — one row per status change**

| Column | Description |
|---|---|
| `receipt_number` | Case receipt number |
| `account` | USCIS account label |
| `status` | Status at the time |
| `uscis_updated_at` | When USCIS updated the case |
| `bot_recorded_at_utc` | When the bot detected the change |
| `events_count` | Number of events at that snapshot |

**2. `uscis_events_YYYYMMDD_HHMMSS.csv` — one row per event**

| Column | Description |
|---|---|
| `receipt_number` | Case receipt number |
| `account` | USCIS account label |
| `case_status` | Case status when this event was recorded |
| `uscis_updated_at` | Case updated timestamp at that snapshot |
| `event_timestamp` | Date/time of the individual event |
| `event_code` | Raw USCIS/NIEM event code (e.g. `AAB`) |
| `event_description` | Human-readable label (e.g. `AAB RECEIVED - FINGERPRINT FEE`) |

Open either file in Excel or Google Sheets to filter, sort, and analyse
your full processing timeline.

### Sharing data with others after approval

Once your case is approved, you have a complete machine-readable record
of every status change and every event from the moment you started
monitoring. This is valuable data for others waiting on similar cases
(same form type, same field office, similar priority date).

**To share your timeline:**

1. Send `/report` in the Telegram bot
2. Save the two CSV files the bot sends you
3. Share them in USCIS tracker communities (e.g. trackitt.com, Google
   Sheets groups, Reddit threads) so others can see real processing
   times with exact event-level detail

**What to look for:**

- **Summary CSV** — the gap between `bot_recorded_at_utc` on your first
  entry and your approval entry shows total processing time
- **Events CSV** — filter by `receipt_number` to see the complete
  event-by-event timeline of your case from filing to approval

### Where the data is stored

All history is stored locally in your SQLite database at:

```
%USERPROFILE%\.uscis_monitor\data.db   (Windows)
~/.uscis_monitor/data.db               (macOS / Linux)
```

The `case_history` table inside that file holds every recorded entry.
You can open it with any SQLite browser (e.g. [DB Browser for SQLite](https://sqlitebrowser.org/))
to run custom queries across all your cases.

---

## Multiple Accounts (e.g. spouse)

Each account is just a named label (`primary`, `wife`, `spouse`, …) with its
own encrypted session file that refreshes independently. There are two ways to
add one:

### Option A — Manual login (quickest, no stored password)

1. Right-click the tray icon -> **Add Account** (or send `/addaccount wife`)
2. Type a label (e.g. `wife`)
3. Log in with the account's myUSCIS credentials in the Chrome window that opens
4. Register their cases: `/register IOE0000000000 wife`

With this option, when the session hits its ~8-hour cap you'll need to run
`/relogin wife` and log in again manually.

### Option B — Automated re-login with email MFA (hands-off)

Store the account's credentials (encrypted) once, and the app re-logs-in by
itself whenever the session expires — no manual step, ever. See the next
section.

---

## Hands-off Auto Re-login (email MFA)

The myUSCIS session has a **hard ~8-hour server-side lifetime** that no
keep-alive can extend. To keep monitoring running indefinitely without manual
logins, save the account's credentials once and the app will sign back in
automatically, reading the two-step verification code from Gmail.

### Requirements

- The account's **myUSCIS login email must be the Gmail (or Google Workspace)
  inbox that receives the USCIS verification codes** — the same address is used
  both to sign in and to read the MFA code over IMAP.
- A **Gmail App Password** (16 characters) for that inbox. Create one at
  <https://myaccount.google.com/apppasswords> (requires 2-Step Verification to
  be enabled on the Google account).

### Setup

Run this once on the host machine, from the project folder, and answer the
three prompts (the password fields are hidden as you type):

```bash
python set_credentials.py <account>     # e.g. python set_credentials.py spouse
```

| Prompt | What to enter |
|---|---|
| USCIS email | The Gmail that receives the USCIS MFA codes |
| USCIS password | The account's myUSCIS password |
| Gmail App Password | The 16-character app password for that inbox |

The credentials are stored **Fernet-encrypted** at
`~/.uscis_monitor/credentials_<account>.enc` (using the same local key as the
session cookies) — they are never written to disk in plaintext and never leave
your machine.

### Create the first session, then register cases

```
/relogin spouse                       → signs in, reads the MFA code, saves the session
/register IOE0000000000 spouse        → start monitoring the account's case(s)
/status spouse                        → confirm it's fetching
```

From then on, the app re-logs-in on its own at the ~8h cap. Failed attempts back
off automatically so a bad password or hiccup can't trip USCIS's soft-lock.

> **Tip:** the recurring auto re-login runs headless. The very first login on a
> brand-new account profile can occasionally be blocked by bot-protection in
> headless mode — if `/relogin <account>` fails repeatedly on a fresh account,
> use `/addaccount <account>` once (a visible Chrome window) to seed the
> profile; automated headless re-logins work reliably after that.

To stop deleting the verification emails after reading them, set
`DELETE_MFA_EMAIL=false` in your `.env`.

---

## Project Structure

```
├── main.py                 Entry point — starts bot, monitor, tray
├── config.py               App-wide constants and config load/save
├── auth_manager.py         Chrome CDP login + session encryption + auto re-login
├── uscis_auto_login.py     Automated Playwright login with email MFA
├── credentials.py          Encrypted per-account credential store
├── account_credentials.py  Credential loading (encrypted store / env)
├── set_credentials.py      CLI to save encrypted credentials for an account
├── mfa_email.py            Reads USCIS verification codes from Gmail (IMAP)
├── uscis_client.py         USCIS API client (authenticated + public fallback)
├── monitor.py              APScheduler polling + session refresh jobs
├── telegram_bot.py         python-telegram-bot command handlers
├── database.py             SQLite — users, cases, and case history
├── tray_app.py             pystray Windows system tray
├── setup_wizard.py         First-run tkinter wizard (subprocess)
├── log_viewer.py           Log viewer (subprocess)
├── install.bat             One-click installer
└── run.bat                 Launch the app
```

Data is stored in `%USERPROFILE%\.uscis_monitor\` and never
inside the repo folder.

---

## Privacy & Security

- **Session cookies are encrypted at rest.** The app captures browser
  session cookies and encrypts them on disk with a local key.
- **Credentials are optional and encrypted.** By default no password is
  stored. If you opt into automated re-login (`set_credentials.py`), the
  USCIS password and Gmail App Password are stored **Fernet-encrypted**
  with that same local key — never in plaintext.
- **No third-party servers.** The app talks only to `my.uscis.gov`,
  `imap.gmail.com` (only when automated re-login is enabled), and
  `api.telegram.org`.
- This tool is for personal use to monitor your own USCIS cases.

---

## License

MIT — see [LICENSE](LICENSE)
