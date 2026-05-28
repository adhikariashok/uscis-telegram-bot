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
| `/accounts` | Show saved USCIS accounts |
| `/addaccount wife` | Instructions to add a second account |
| `/help` | Show all commands |

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
├── database.py        SQLite — users and cases
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
