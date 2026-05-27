"""Standalone log viewer — launched as a subprocess by tray_app.py."""
import tkinter as tk
from tkinter import scrolledtext
from config import LOG_PATH


def main():
    root = tk.Tk()
    root.title("USCIS Monitor — Log")
    root.geometry("800x450")

    text = scrolledtext.ScrolledText(root, wrap="word", font=("Consolas", 9))
    text.pack(fill="both", expand=True)

    if LOG_PATH.exists():
        text.insert("1.0", LOG_PATH.read_text(errors="replace"))
    else:
        text.insert("1.0", "(No log file found)")

    text.see("end")
    text.configure(state="disabled")

    btn = tk.Button(root, text="Refresh", command=lambda: _refresh(text))
    btn.pack(pady=4)

    root.mainloop()


def _refresh(text):
    text.configure(state="normal")
    text.delete("1.0", "end")
    if LOG_PATH.exists():
        text.insert("1.0", LOG_PATH.read_text(errors="replace"))
    text.see("end")
    text.configure(state="disabled")


if __name__ == "__main__":
    main()
