# Setup Guide — USCIS Case Monitor

Complete step-by-step instructions to get the app running from scratch.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Get the Code](#2-get-the-code)
3. [Install the App](#3-install-the-app)
4. [Create a Telegram Bot](#4-create-a-telegram-bot)
5. [First Run & Setup Wizard](#5-first-run--setup-wizard)
6. [Log In to myUSCIS](#6-log-in-to-myuscis)
7. [Register Your Cases](#7-register-your-cases)
8. [Adding a Second Account](#8-adding-a-second-account-eg-spouse)
9. [Running in the Background](#9-running-in-the-background)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

Install all three before continuing.

### Python 3.13

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download **Python 3.13** (the latest 3.13.x release)
3. Run the installer — **check "Add Python to PATH"** before clicking Install

Verify in a terminal:
```
py -3.13 --version
```
Expected output: `Python 3.13.x`

### Google Chrome

Download from [google.com/chrome](https://www.google.com/chrome/) if you don't already have it.
Any recent version works.

### Telegram

Install Telegram on your phone or desktop from [telegram.org](https://telegram.org).
You need a Telegram account to receive notifications.

---

## 2. Get the Code

**Option A — Clone with Git:**
```
git clone https://github.com/YOUR_USERNAME/uscis-monitor.git
cd uscis-monitor
```

**Option B — Download ZIP:**
1. Click the green **Code** button on GitHub
2. Click **Download ZIP**
3. Extract to a folder of your choice (e.g. `C:\uscis-monitor`)

---

## 3. Install the App

Double-click **`install.bat`** inside the folder.

The installer will:
- Create a Python virtual environment
- Install all dependencies
- Create a desktop shortcut

> If Windows asks "Do you want to allow this app to make changes?" — click **Yes**.

If the installer fails, see [Troubleshooting](#10-troubleshooting).

---

## 4. Create a Telegram Bot

You need your own private Telegram bot. This takes about 2 minutes.

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. `My USCIS Monitor`)
4. Choose a username ending in `bot` (e.g. `myuscismonitor_bot`)
5. BotFather will reply with a token like:
   ```
   123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```
6. **Copy that token** — you'll need it in the next step

---

## 5. First Run & Setup Wizard

Double-click **`run.bat`** (or the desktop shortcut created by the installer).

A setup wizard window will appear:

**Step 1 — Telegram Bot Token**
- Paste the token you copied from BotFather
- The token should start with numbers followed by a colon

**Step 2 — Log in to myUSCIS**
- Click **"Open USCIS Login Browser"**
- A Chrome window will open automatically (see next section)

**Step 3 — Save**
- Click **"Save & Start Monitoring"**

---

## 6. Log In to myUSCIS

When you click "Open USCIS Login Browser":

1. A Chrome window opens pointing to **my.uscis.gov**
2. Log in with your myUSCIS credentials (via login.gov)
3. Once you reach your **dashboard or account page**, wait a moment
4. **Chrome will close automatically** — this means the session was captured

> You do not need to click anything in the app. Chrome closing itself is the success signal.

The app silently refreshes your session every 10 minutes in the background, so you should **never need to log in again** unless you manually clear your session data.

---

## 7. Register Your Cases

Open Telegram and find the bot you created. Send:

```
/register IOE1234567890
```

Replace `IOE1234567890` with your actual USCIS receipt number (found on your I-797 Notice of Action).

**Check status manually:**
```
/status
```

**List all tracked cases:**
```
/list
```

**Stop monitoring a case:**
```
/unregister IOE1234567890
```

You'll receive a Telegram message automatically whenever the case status, updated timestamp, or event timeline changes.

---

## 8. Adding a Second Account (e.g. Spouse)

If you want to monitor cases tied to a different myUSCIS login (e.g. your spouse's account):

**From the tray icon:**
1. Right-click the **USCIS Monitor** icon in the taskbar (bottom-right)
2. Click **Add Account**
3. Type a label when prompted — e.g. `wife`
4. A Chrome window opens — log in with your spouse's myUSCIS credentials
5. Chrome closes automatically when done

**Register cases under the new account:**
```
/register IOE0000000000 wife
```

**Check which accounts are saved:**
```
/accounts
```

**Re-login for a specific account** (if the session expires):
- Right-click tray icon → **Re-login (wife)**

---

## 9. Running in the Background

The app runs silently with no console window. To confirm it's running, look for the **blue circular icon** in your Windows system tray (bottom-right taskbar area — you may need to click the `^` arrow to see it).

**Right-click the tray icon for options:**
- **Check Now** — run an immediate poll of all cases
- **Add Account** — add a new USCIS account
- **Re-login (primary)** — re-authenticate if a session expires
- **View Log** — open the live log viewer for debugging
- **Settings** — reopen the setup wizard to change the bot token
- **Exit** — stop the app

**To start on Windows login:**
- Copy the desktop shortcut to your Startup folder:
  Press `Win + R`, type `shell:startup`, press Enter, then drag the shortcut in.

---

## 10. Troubleshooting

### "Python not found" during install

- Make sure Python 3.13 is installed from [python.org](https://www.python.org/downloads/)
- During installation, ensure **"Add Python to PATH"** was checked
- Try restarting your terminal/PowerShell after installing Python

### Chrome closes immediately / no cookies captured

- Make sure you fully logged in and reached the **dashboard** (`my.uscis.gov/account/...`) before Chrome closes
- If Chrome closes too fast, it may have failed to connect to myUSCIS — try again from **Re-login** in the tray menu
- Check **View Log** in the tray for detailed error messages

### Session expired — getting alerts on Telegram

- Right-click the tray icon → **Re-login (primary)** (or the relevant account name)
- Log in again in the Chrome window that opens
- Chrome will close automatically when done

### Bot not responding in Telegram

1. Make sure `run.bat` was started (check for the tray icon)
2. Open **View Log** from the tray — look for `Telegram bot polling started`
3. Verify your bot token is correct via **Settings** in the tray

### "No cases being monitored" after `/list`

- Register a case first: `/register IOE1234567890`
- Make sure you used the correct receipt number (e.g. `IOE`, `MSC`, `WAC` prefix)

### App crashes on startup

- Open **View Log** (or find `monitor.log` in `%USERPROFILE%\.uscis_monitor\`)
- Look for the last error line and open a GitHub Issue with the log

---

## Data Location

All user data is stored in `%USERPROFILE%\.uscis_monitor\` — never inside the repo folder:

| File | Contents |
|---|---|
| `config.json` | Bot token, poll interval |
| `data.db` | SQLite — registered users and cases |
| `session_primary.enc` | Encrypted USCIS session (primary account) |
| `session_wife.enc` | Encrypted session (if you added a second account) |
| `.fernet_key` | Encryption key (never share this) |
| `monitor.log` | Application log |

> To fully reset the app, delete the `%USERPROFILE%\.uscis_monitor\` folder.
