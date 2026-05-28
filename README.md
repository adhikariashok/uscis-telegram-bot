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
  - no credentials stored
- Saves the encrypted session and silently refreshes it every 10 minutes
- Polls the authenticated USCIS API every 5 minutes for each
  registered case
- Notifies you via Telegram bot when status, updated timestamp,
  or event timeline changes
- Supports **multiple USCIS accounts** (e.g. yourself + spouse)

---

## Features

- ✅ One-time login — Chrome opens, you log in, session is captured automatically
- ✅ Silent background session refresh — never expires mid-monitoring
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
| `/addaccount wife` | Instructions to add a second account |
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

1. Right-click the tray icon -> **Add Account**
2. Type a label (e.g. `wife`)
3. Log in with your spouse's myUSCIS credentials
4. Register their cases: `/register IOE0000000000 wife`

Each account has its own encrypted session file and refreshes independently.

---

## Project Structure

```
├── main.py            Entry point — starts bot, monitor, tray
├── config.py          App-wide constants and config load/save
├── auth_manager.py    Chrome CDP login + session encryption
├── uscis_client.py    USCIS API client (authenticated + public fallback)
├── monitor.py         APScheduler polling + session refresh jobs
├── telegram_bot.py    python-telegram-bot command handlers
├── database.py        SQLite — users, cases, and case history
├── tray_app.py        pystray Windows system tray
├── setup_wizard.py    First-run tkinter wizard (subprocess)
├── log_viewer.py      Log viewer (subprocess)
├── install.bat        One-click installer
└── run.bat            Launch the app
```

Data is stored in `%USERPROFILE%\.uscis_monitor\` and never
inside the repo folder.

---

## Privacy & Security

- **No credentials are stored.** The app captures browser session
  cookies and encrypts them on disk with a local key.
- **No third-party servers.** The app talks only to
  `my.uscis.gov` and `api.telegram.org`.
- This tool is for personal use to monitor your own USCIS cases.

---

## License

MIT — see [LICENSE](LICENSE)
