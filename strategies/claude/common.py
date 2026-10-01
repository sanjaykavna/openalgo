"""
common.py - shared helpers + SURVIVAL FLOOR for all OpenAlgo strategies (v1, 2026-10-01).
Put this file in the same folder as the strategy scripts.

Settings come from environment variables (set them once in OpenAlgo's strategy page or your shell):
  OPENALGO_API_KEY   your OpenAlgo API key (required)
  OPENALGO_HOST      default http://127.0.0.1:5000
  TELEGRAM_USER      your OpenAlgo-linked Telegram username (optional, for alerts)
  BOT_STATUS_FILE    path to status.txt (optional; contents ACTIVE / EXIT-ONLY / PAUSED)
"""
import os, csv, time, datetime as dt
from zoneinfo import ZoneInfo
from openalgo import api

IST = ZoneInfo("Asia/Kolkata")
HOST = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
API_KEY = os.getenv("OPENALGO_API_KEY", "")
TG_USER = os.getenv("TELEGRAM_USER", "")
STATUS_FILE = os.getenv("BOT_STATUS_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.txt"))
LOG_DIR = os.getenv("BOT_LOG_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

# ---- SURVIVAL FLOOR (same numbers as the trading bots; never loosen here) ----
RISK_PER_TRADE = 0.02      # max loss per trade as share of account value
DAY_LOSS_STOP = 0.03       # stop new entries if day loss > 3% of account value
NO_STOP_SYMBOLS = {"NIFTYBEES", "JUNIORBEES", "GOLDBEES", "SILVERBEES", "LIQUIDBEES"}  # core/hedge ETFs: no stop by design
INTRADAY_PRODUCTS = {"MIS"}
SQUAREOFF_TIME = dt.time(15, 10)
MARKET_OPEN, MARKET_CLOSE = dt.time(9, 15), dt.time(15, 30)


def client():
    if not API_KEY:
        raise SystemExit("Set OPENALGO_API_KEY first")
    return api(api_key=API_KEY, host=HOST)


def now():
    return dt.datetime.now(IST)


def market_open(c=None):
    n = now()
    if n.weekday() >= 5:
        return False
    if not (MARKET_OPEN <= n.time() <= MARKET_CLOSE):
        return False
    if c is not None:
        try:
            hol = c.holidays(year=n.year)
            for h in (hol.get("data") or []):
                if h.get("date") == n.date().isoformat() and "NSE" in (h.get("closed_exchanges") or []):
                    return False
        except Exception:
            pass
    return True


def bot_status():
    """ACTIVE / EXIT-ONLY / PAUSED - mirrors the Trading status in the controller log."""
    try:
        s = open(STATUS_FILE).read().strip().upper()
        return s if s in ("ACTIVE", "EXIT-ONLY", "PAUSED") else "ACTIVE"
    except Exception:
        return "ACTIVE"


def data(resp):
    """Unwrap OpenAlgo responses ({'status':..,'data':..})."""
    if isinstance(resp, dict):
        if resp.get("status") == "error":
            raise RuntimeError(resp.get("message", resp))
        return resp.get("data", resp)
    return resp


def num(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def alert(c, msg, priority=5):
    line = f"[{now():%H:%M}] {msg}"
    print(line, flush=True)
    log("alerts", {"time": now().isoformat(timespec="seconds"), "msg": msg})
    if TG_USER:
        try:
            c.telegram(username=TG_USER, message=line, priority=priority)
        except Exception as e:
            print("telegram failed:", e)


def log(name, row):
    path = os.path.join(LOG_DIR, f"{name}_{now():%Y%m}.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def holdings_list(c):
    """Holdings with a robust qty (Nubra via OpenAlgo sometimes returns quantity 0 / ltp 0)."""
    out = []
    h = data(c.holdings())
    for r in (h.get("holdings") if isinstance(h, dict) else h) or []:
        qty = int(num(r.get("quantity")))
        avg = num(r.get("average_price"))
        if qty <= 0 and avg > 0 and num(r.get("invested_value")) > 0:
            qty = int(round(num(r.get("invested_value")) / avg))
        if qty > 0:
            out.append({"symbol": r["symbol"], "exchange": r.get("exchange", "NSE"), "qty": qty,
                        "avg": avg, "product": r.get("product", "CNC")})
    return out


def positions_list(c):
    out = []
    for r in data(c.positionbook()) or []:
        q = int(num(r.get("quantity")))
        if q != 0:
            out.append({"symbol": r["symbol"], "exchange": r.get("exchange", "NSE"), "qty": q,
                        "avg": num(r.get("average_price")), "product": r.get("product", "MIS")})
    return out


def open_orders(c):
    ob = data(c.orderbook())
    orders = ob.get("orders", []) if isinstance(ob, dict) else (ob or [])
    return [o for o in orders if str(o.get("order_status", "")).lower() in ("open", "pending", "trigger pending", "trigger_pending")]


def ltps(c, items):
    """items: list of (symbol, exchange) -> {symbol: ltp}"""
    out = {}
    if not items:
        return out
    try:
        res = data(c.multiquotes(symbols=[{"symbol": s, "exchange": e} for s, e in items]))
        rows = res.get("results", res) if isinstance(res, dict) else res
        for r in rows or []:
            d = r.get("data", r)
            out[r.get("symbol", d.get("symbol"))] = num(d.get("ltp"))
    except Exception:
        for s, e in items:
            try:
                out[s] = num(data(c.quotes(symbol=s, exchange=e)).get("ltp"))
            except Exception:
                pass
    return out
