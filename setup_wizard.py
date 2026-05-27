"""
First-run setup wizard (tkinter).
Collects the Telegram bot token and triggers the USCIS login flow.
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from config import load_config, save_config
from auth_manager import capture_session, has_session


class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("USCIS Monitor — Setup")
        self.resizable(False, False)
        self.geometry("520x400")
        self._build_ui()
        self._center()

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build_ui(self):
        pad = {"padx": 20, "pady": 8}

        header = tk.Label(
            self,
            text="USCIS Case Monitor Setup",
            font=("Segoe UI", 16, "bold"),
        )
        header.pack(pady=(20, 4))

        sub = tk.Label(
            self,
            text="Complete the two steps below to start monitoring your USCIS cases.",
            font=("Segoe UI", 10),
            fg="#555",
        )
        sub.pack()

        # ── Step 1: Bot token ─────────────────────────────────────────────────
        frame1 = ttk.LabelFrame(self, text=" Step 1 — Telegram Bot Token ", padding=12)
        frame1.pack(fill="x", **pad)

        info1 = tk.Label(
            frame1,
            text="Create a bot via @BotFather on Telegram and paste your token here:",
            font=("Segoe UI", 9),
            wraplength=460,
            justify="left",
        )
        info1.pack(anchor="w")

        self.token_var = tk.StringVar(value=load_config().get("telegram_bot_token", ""))
        token_entry = ttk.Entry(frame1, textvariable=self.token_var, width=55, show="")
        token_entry.pack(fill="x", pady=(6, 0))

        # ── Step 2: USCIS login ───────────────────────────────────────────────
        frame2 = ttk.LabelFrame(self, text=" Step 2 — Log in to myUSCIS ", padding=12)
        frame2.pack(fill="x", **pad)

        info2 = tk.Label(
            frame2,
            text=(
                "A Chromium browser will open. Log in to my.uscis.gov with your account.\n"
                "Once you reach your dashboard the session is captured automatically.\n"
                "You will NEVER need to log in again unless the session expires."
            ),
            font=("Segoe UI", 9),
            wraplength=460,
            justify="left",
        )
        info2.pack(anchor="w")

        self.login_status = tk.StringVar(
            value="✅ Session already saved." if has_session() else "Not logged in yet."
        )
        status_label = tk.Label(frame2, textvariable=self.login_status, font=("Segoe UI", 9, "italic"), fg="#444")
        status_label.pack(anchor="w", pady=(4, 0))

        self.login_btn = ttk.Button(frame2, text="Open USCIS Login Browser", command=self._do_login)
        self.login_btn.pack(anchor="w", pady=(8, 0))

        # ── Save & Start ──────────────────────────────────────────────────────
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=16)

        ttk.Button(btn_frame, text="Save & Start Monitoring", command=self._save_and_close).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="left", padx=6)

    def _do_login(self):
        self.login_btn.config(state="disabled")
        self.login_status.set("⏳ Browser opening — log in then wait…")

        def run():
            ok = capture_session(status_callback=lambda m: self.login_status.set(m))
            if ok:
                self.login_status.set("✅ Session captured successfully!")
            else:
                self.login_status.set("❌ Login failed or cancelled. Try again.")
            self.login_btn.config(state="normal")

        threading.Thread(target=run, daemon=True).start()

    def _save_and_close(self):
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Missing Token", "Please enter your Telegram bot token.")
            return
        if not has_session():
            if not messagebox.askyesno(
                "Skip USCIS Login?",
                "You haven't logged in to myUSCIS yet.\n\n"
                "The monitor will use the public API (no account needed) "
                "but won't show detailed event history.\n\n"
                "Continue anyway?",
            ):
                return
        save_config({"telegram_bot_token": token})
        self.destroy()


def run_wizard():
    app = SetupWizard()
    app.mainloop()


if __name__ == "__main__":
    run_wizard()
