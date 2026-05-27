# USCIS Case Monitor

A Windows background app that watches your USCIS case status and sends you a **Telegram notification the moment anything changes** — new events, updated timestamps, or a status change.

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## How it works

```
Your PC (runs 24/7)          myUSCIS API              Telegram
─────────────────────        ─────────────            ─────────────────
Windows tray app     ──────► Polls every 5 min ──────► Sends you a
(no console window)          Authenticated             message if
                             session via Chrome        anything changed
```

- Logs into **my.uscis.gov** once using your real Chrome browser — no credentials stored
- Saves the encrypted session and silently refreshes it every 10 minutes
- Polls the authenticated USCIS API every 5 minutes for each registered case
- Notifies you via Telegram bot when status, updated timestamp, or event timeline changes
- Supports **multiple USCIS accounts** (e.g. yourself + spouse)

---

## Features

- ✅ One-time login — Chrome opens, you log in, session is captured automatically
- ✅ Silent background session refresh — never expires mid-monitoring
- ✅ Multi-account support — monitor your case and your spouse's case separately
- ✅ Telegram bot interface — register cases and check status from your phone
- ✅ Windows system tray — lives quietly in your taskbar
- ✅ Fully local — all data stays on your PC, nothing sent to third parties

---

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10 / 11 | Required (tray app, Chrome CDP) |
| Python 3.13 | [python.org](https://www.python.org/downloads/) — check "Add to PATH" |
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

See **[SETUP.md](SETUP.md)** for the full step-by-step guide with screenshots and troubleshooting.

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

1. Right-click the tray icon → **Add Account**
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

Data is stored in `%USERPROFILE%\.uscis_monitor\` — never inside the repo folder.

---

## Privacy & Security

- **No credentials are stored.** The app captures browser session cookies (same as your browser does) and encrypts them on disk with a key that never leaves your machine.
- **No third-party servers.** The app talks only to `my.uscis.gov` and `api.telegram.org`.
- This tool is for personal use to monitor your own USCIS cases.

---

## License

MIT — see [LICENSE](LICENSE)
