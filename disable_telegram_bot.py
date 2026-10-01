"""Turn off OpenAlgo's Telegram bot so it no longer starts with OpenAlgo.

Run from the OpenAlgo folder with OpenAlgo CLOSED:
    .venv\\Scripts\\python.exe disable_telegram_bot.py

It backs up db\\openalgo.db first, then switches off every "active / enabled /
auto-start" flag in the Telegram bot tables. The bot token is kept, so you can
turn the bot back on later from OpenAlgo's Telegram page.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

DB = os.path.join("db", "openalgo.db")
FLAG_WORDS = ("active", "enabled", "auto_start", "autostart", "is_running", "running")

if not os.path.exists(DB):
    sys.exit(f"Not found: {DB}  - run this from the OpenAlgo folder (the one with app.py).")

backup = f"{DB}.backup-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(DB, backup)
print(f"Backup saved: {backup}")

con = sqlite3.connect(DB)
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
bot_tables = [t for t in tables if "telegram" in t.lower() or "bot" in t.lower()]
if not bot_tables:
    sys.exit("No Telegram/bot tables found - nothing to change. Tables: " + ", ".join(tables))

changed = 0
for t in bot_tables:
    cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
    flags = [c for c in cols if any(w in c.lower() for w in FLAG_WORDS)]
    print(f"\nTable {t}: columns = {', '.join(cols)}")
    for c in flags:
        n = con.execute(f'UPDATE "{t}" SET "{c}" = 0 WHERE "{c}" IS NOT 0').rowcount
        print(f"  set {c} = off  ({n} row(s) changed)")
        changed += n
con.commit()
con.close()

print(f"\nDone. {changed} setting(s) switched off.")
print("Start OpenAlgo again; the 'Failed to initialize Telegram bot' error should be gone.")
print(f"To undo: close OpenAlgo and copy {backup} back over {DB}.")