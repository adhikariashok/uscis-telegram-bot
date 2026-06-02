# Setup Guide — USCIS Case Monitor

Complete step-by-step instructions to get the app running from scratch.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Get the Code](#2-get-the-code)
3. [Install the App](#3-install-the-app)
4. [Configure `.env`](#4-configure-env)
5. [Create a Telegram Bot](#5-create-a-telegram-bot)
6. [First Run](#6-first-run)
7. [Log In to myUSCIS](#7-log-in-to-myuscis)
8. [Register Your Cases](#8-register-your-cases)
9. [Adding a Second Account](#9-adding-a-second-account-eg-spouse)
10. [Session Refresh & Re-login](#10-session-refresh--re-login)
11. [Running in the Background](#11-running-in-the-background)
12. [Telegram Commands](#12-telegram-commands)
13. [Troubleshooting](#13-troubleshooting)
14. [Data Location](#14-data-location)

---

## 1. Prerequisites

Install all of the following before continuing.

### Python 3.13

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download **Python 3.13**
3. Run the installer — on Windows, check **"Add Python to PATH"**

Verify:

```bash
python3 --version
# or on Windows: py -3.13 --version
```

Expected: `Python 3.13.x`

### Google Chrome

Download from [google.com/chrome](https://www.google.com/chrome/).
Required for session capture and background refresh.

### Telegram

Install from [telegram.org](https://telegram.org).
You need an account to receive notifications.

### Playwright (automated login on macOS/Linux)

If you use **automated login** (recommended on macOS), install Playwright
browsers after the Python dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## 2. Get the Code

**Option A — Clone with Git:**

```bash
git clone https://github.com/YOUR_USERNAME/uscis-telegram-bot.git
cd uscis-telegram-bot
```

**Option B — Download ZIP:**

1. Click **Code → Download ZIP** on GitHub
2. Extract to a folder of your choice

---

## 3. Install the App

### Windows

Double-click **`install.bat`**.

The installer will:

- Create a Python virtual environment
- Install dependencies
- Create a desktop shortcut

Then use **`run.bat`** or the desktop shortcut to start (tray mode).

### macOS / Linux

```bash
cd uscis-telegram-bot
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Edit `.env` (see next section), then start headless mode:

```bash
python main.py --mode headless
```

---

## 4. Configure `.env`

Copy the template and edit the root `.env` file:

```bash
cp .env.example .env
```

### Required

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |

### Optional — security

| Variable | Description |
|---|---|
| `ALLOWED_TELEGRAM_IDS` | Comma-separated Telegram user IDs allowed to run `/addaccount` and `/relogin`. Get your ID from @userinfobot. Leave empty to allow all users (not recommended on a public bot). |

### Optional — automated USCIS login (recommended on macOS)

Enables **hands-free** `/relogin` and automatic recovery when a session
expires. The bot signs in to myUSCIS, reads the MFA code from Gmail via
IMAP, and saves the session — no manual Chrome window.

**Primary account** (use either set of names):

```bash
USCIS_EMAIL=you@gmail.com
USCIS_PASSWORD=your-myuscis-password
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
```

**Or immigration-style numbered vars** (work for any account label if
account-specific vars are not set):

```bash
USCIS_EMAIL_1=you@gmail.com
USCIS_PASSWORD_1=your-myuscis-password
GMAIL_APP_PASSWORD_1=xxxxxxxxxxxxxxxx
```

**Named account** (example label `boris`):

```bash
USCIS_EMAIL_BORIS=you@gmail.com
USCIS_PASSWORD_BORIS=your-myuscis-password
GMAIL_APP_PASSWORD_BORIS=xxxxxxxxxxxxxxxx
```

#### Gmail App Password

1. Enable **2-Step Verification** on your Google Account
2. Open [App passwords](https://myaccount.google.com/apppasswords)
3. Create a password for **Mail**
4. Paste the **16-character** password into `.env` (spaces are OK; do not
   add quotes or extra characters like `%`)

Use the **same Gmail address** as `USCIS_EMAIL` — USCIS sends MFA codes
there.

> **Privacy:** Credentials stay in `.env` on your machine only. They are
> never sent to third parties except myUSCIS and Gmail (for MFA).

---

## 5. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a display name and a username ending in `bot`
4. Copy the token (format: `123456789:ABCdef...`)
5. Paste it into `.env` as `TELEGRAM_BOT_TOKEN`

---

## 6. First Run

### Windows (tray mode — default)

1. Double-click **`run.bat`**
2. Complete the **setup wizard** (bot token, optional manual USCIS login)
3. Look for the blue icon in the system tray

### macOS / Linux (headless mode — default)

```bash
source venv/bin/activate
python main.py --mode headless
```

You should see:

```
Telegram bot polling started.
Monitor started — polling every 300 seconds...
```

Open your bot in Telegram and send `/start`.

**Optional — setup wizard on any OS:**

```bash
python setup_wizard.py
```

---

## 7. Log In to myUSCIS

You need a saved USCIS session before registering cases. Choose **one**
method.

### Method A — Automated login (recommended)

Requires `USCIS_EMAIL`, `USCIS_PASSWORD`, and `GMAIL_APP_PASSWORD` in
`.env` (see [section 4](#4-configure-env)).

In Telegram:

```
/addaccount boris
```

or, to refresh an existing account:

```
/relogin boris
```

The bot will:

1. Open a headless browser and sign in to myUSCIS
2. Wait for the MFA email from `uscis.dhs.gov`
3. Read the 6-digit code from Gmail (IMAP)
4. Complete MFA and save the encrypted session

You should get a success message in Telegram within about a minute.

### Method B — Manual login (Chrome window)

Use this if you do not want credentials in `.env`, or automated login
fails.

**Windows:** Right-click tray icon → **Add Account…**, or use Telegram:

```
/addaccount wife
```

**macOS / Linux:** Telegram only (no tray):

```
/addaccount primary
```

A **visible Chrome window** opens:

1. Log in to myUSCIS (login.gov)
2. Reach your **dashboard**
3. Chrome closes automatically when the session is captured

---

## 8. Register Your Cases

In Telegram (replace with your receipt number):

```
/register IOE1234567890
```

With a named account:

```
/register IOE1234567890 boris
```

**Other commands:**

```
/status          # check all cases now
/status IOE123   # one case
/list            # cases you track
/unregister IOE1234567890
```

You receive a Telegram message when status, timestamps, or events change.

---

## 9. Adding a Second Account (e.g. Spouse)

Each account has its own encrypted session file and label (e.g. `wife`,
`boris`).

1. Add credentials to `.env` (automated) **or** run `/addaccount wife`
   (manual Chrome login)
2. Register cases with the label:

```
/register IOE0000000000 wife
```

3. List saved accounts:

```
/accounts
```

---

## 10. Session Refresh & Re-login

The monitor **refreshes sessions every 20 minutes** in the background
(headless Chrome on the saved profile).

If a session expires, you may get:

```
⚠️ USCIS session expired for boris account.
Run /relogin boris in Telegram to restore full monitoring.
```

**With automated login configured:**

```
/relogin boris
```

Runs headless — no action needed on your Mac/PC.

**Without automated login:**

```
/relogin boris
```

Opens Chrome; complete login manually.

> Only one login operation runs per account at a time. Wait for startup
> refresh to finish before sending `/relogin` right after a restart.

---

## 11. Running in the Background

### Windows (tray)

- App runs from `run.bat` with no console window
- Tray icon (bottom-right, may be under `^`)
- **Check Now**, **Add Account**, **Re-login**, **View Log**, **Settings**, **Exit**
- Auto-start: copy desktop shortcut to `shell:startup`

### macOS / Linux (headless)

Keep a terminal open, or run as a service, e.g. with `launchd` or
`systemd`. Example:

```bash
cd /path/to/uscis-telegram-bot
source venv/bin/activate
nohup python main.py --mode headless >> ~/.uscis_monitor/nohup.log 2>&1 &
```

Logs: `~/.uscis_monitor/monitor.log` (or path in `LOG_PATH`).

### Run modes

| Mode | Command | Default on |
|---|---|---|
| Tray | `python main.py --mode tray` | Windows |
| Headless | `python main.py --mode headless` | macOS, Linux |

---

## 12. Telegram Commands

| Command | Description |
|---|---|
| `/start` | Welcome and command list |
| `/help` | Same as `/start` |
| `/register IOE123` | Monitor a case (primary account) |
| `/register IOE123 wife` | Monitor under named account |
| `/unregister IOE123` | Stop monitoring |
| `/status` | Check all your cases |
| `/status IOE123` | Check one case |
| `/status wife` | Check all cases for an account |
| `/list` | List tracked cases |
| `/history` | Full status change history |
| `/history IOE123` | History for one case |
| `/report` | Download CSV report (summary + events) |
| `/accounts` | List saved USCIS accounts |
| `/addaccount wife` | Save a new account session |
| `/relogin` | Refresh session (primary or only account) |
| `/relogin boris` | Refresh a named account session |

`/addaccount` and `/relogin` use **automated login** when `.env`
credentials are set; otherwise they open Chrome for manual login.

---

## 13. Troubleshooting

### Python not found

- Install Python 3.13 from [python.org](https://www.python.org/downloads/)
- On Windows, enable **Add Python to PATH** and restart the terminal

### Chrome did not start in time

- Another login or refresh may be using the same profile — wait 30s and
  retry `/relogin`
- Restart the app after a failed login
- On macOS, ensure Google Chrome is installed

### Re-login failed — Gmail / MFA

- `GMAIL_APP_PASSWORD` must be **16 characters** (Gmail App Password, not
  your normal Gmail password)
- No quotes, no trailing `%` or other stray characters in `.env`
- Same Gmail as `USCIS_EMAIL`
- Test: enable IMAP in Gmail settings
- USCIS subject line: **Secure two-step verification notification**

### Re-login failed — USCIS credentials

- Check `USCIS_PASSWORD` in `.env`
- Soft-lock: wait and try again later

### Session expired alerts but monitoring works

- Limited data may still come from the public API
- Run `/relogin <account>` for full authenticated monitoring

### Bot not responding

1. Confirm the process is running (`monitor.log` updates)
2. Look for `Telegram bot polling started` in the log
3. Verify `TELEGRAM_BOT_TOKEN` in `.env`

### Automated login works on immigration repo but not here

- Use the same `.env` variable names (`USCIS_EMAIL_1`, etc.) or the
  `_BORIS` suffix for named accounts
- Run `playwright install chromium` after `pip install`

### View logs

| OS | Log path |
|---|---|
| Default | `~/.uscis_monitor/monitor.log` |
| Windows tray | Right-click tray → **View Log** |

---

## 14. Data Location

All data is stored under **`~/.uscis_monitor/`** (macOS/Linux) or
**`%USERPROFILE%\.uscis_monitor\`** (Windows) — not inside the repo.

| File | Contents |
|---|---|
| `.env` | Bot token and optional login credentials (in repo root) |
| `data.db` | Registered users and cases |
| `session_<account>.enc` | Encrypted USCIS session per account |
| `chrome_profile_<account>/` | Persistent Chrome profile per account |
| `.fernet_key` | Local encryption key — **never share** |
| `monitor.log` | Application log |

To fully reset: stop the app, delete `~/.uscis_monitor/`, and start over.

---

## Quick reference — macOS headless

```bash
git clone <repo>
cd uscis-telegram-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Edit .env: TELEGRAM_BOT_TOKEN, USCIS_EMAIL_1, USCIS_PASSWORD_1,
#            GMAIL_APP_PASSWORD_1
python main.py --mode headless
```

In Telegram:

```
/addaccount boris
/register IOE1234567890 boris
/relogin boris    # when session expires
```
