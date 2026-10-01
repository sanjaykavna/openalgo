"""
risk_guardian.py  (v1, 2026-10-01) - minute-by-minute safety net. Zero AI tokens.
Runs 9:15-15:30 IST on trading days, checks every 60 s:
  1. UNPROTECTED: a non-core holding/position with no open SELL order covering its qty -> alert (once/day).
  2. STOP BREACH: price at/below its stop and shares still held -> alert; in LIVE mode exits ONLY the
     qty not already covered by an open sell order (never a double sell, never a short).
  3. INTRADAY: MIS positions still open at 15:10 -> alert; in LIVE mode squares them off.
  4. DAY LOSS: account down >2% (warn) / >3% (G3) today -> alert.
Default LIVE_ORDERS = False (alerts + log only). Switch to True only after a week of clean alerts.
Stops: edit STOPS below or put {"ITC": 248, ...} in stops.json next to this file (re-read every minute).
"""
import os, json, time
from common import (client, now, market_open, bot_status, data, num, alert, log, holdings_list,
                    positions_list, open_orders, ltps, NO_STOP_SYMBOLS, INTRADAY_PRODUCTS,
                    SQUAREOFF_TIME, DAY_LOSS_STOP)

LIVE_ORDERS = os.getenv("GUARDIAN_LIVE", "0") == "1"
CHECK_EVERY_SEC = 60
STOPS = {"ITC": 248.0, "COALINDIA": 405.0}          # symbol -> stop price (bot stops as of 2026-10-01)
STOPS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stops.json")

_alerted = set()
_exited = set()
_start_value = None


def load_stops():
    s = dict(STOPS)
    try:
        s.update({k.upper(): float(v) for k, v in json.load(open(STOPS_FILE)).items()})
    except Exception:
        pass
    return s


def once(c, key, msg, pr=5):
    k = (now().date(), key)
    if k not in _alerted:
        _alerted.add(k)
        alert(c, msg, pr)


def covered_qty(orders, symbol):
    return sum(int(num(o.get("quantity"))) for o in orders
               if o.get("symbol") == symbol and str(o.get("action")).upper() == "SELL")


def account_value(c, hold, pos, px):
    f = data(c.funds())
    cash = num(f.get("availablecash")) + num(f.get("utiliseddebits"))
    v = cash + sum(h["qty"] * px.get(h["symbol"], h["avg"]) for h in hold)
    return v


def cycle(c):
    global _start_value
    status = bot_status()
    hold, pos, orders = holdings_list(c), positions_list(c), open_orders(c)
    stops = load_stops()
    items = {(h["symbol"], h["exchange"]) for h in hold} | {(p["symbol"], p["exchange"]) for p in pos}
    px = ltps(c, list(items))

    held = {}
    # holdings + today's delivery positions (a CNC sell today shows as a negative position -> reduces held)
    for r in hold + [p for p in pos if p["product"] not in INTRADAY_PRODUCTS]:
        held[r["symbol"]] = held.get(r["symbol"], 0) + r["qty"]
    held = {k: v for k, v in held.items() if v > 0}

    for sym, qty in held.items():
        if sym in NO_STOP_SYMBOLS:
            continue
        cov = covered_qty(orders, sym)
        ltp = px.get(sym, 0)
        if cov < qty:
            once(c, f"unprot-{sym}", f"UNPROTECTED {sym}: {qty - cov} of {qty} shares have no resting sell/stop order (stop {stops.get(sym, 'not set')}).", 7)
        st = stops.get(sym)
        if st and ltp and ltp <= st:
            uncovered = max(0, qty - cov)
            once(c, f"breach-{sym}", f"STOP BREACH {sym}: ltp {ltp} <= stop {st}; held {qty}, covered by open sells {cov}.", 9)
            if LIVE_ORDERS and uncovered > 0 and status != "PAUSED" and (now().date(), sym) not in _exited:
                _exited.add((now().date(), sym))   # one guardian exit per symbol per day, never repeated
                r = c.placeorder(strategy="risk_guardian", symbol=sym, action="SELL", exchange="NSE",
                                 price_type="LIMIT", product="CNC", quantity=uncovered,
                                 price=round(ltp * 0.995, 1))
                alert(c, f"EXIT placed {sym} SELL {uncovered} LMT {round(ltp*0.995,1)}: {r}", 9)
                log("guardian_orders", {"time": now().isoformat(timespec="seconds"), "sym": sym, "qty": uncovered, "resp": str(r)})

    if now().time() >= SQUAREOFF_TIME:
        for p in pos:
            if p["product"] in INTRADAY_PRODUCTS and p["qty"] != 0:
                once(c, f"mis-{p['symbol']}", f"INTRADAY still open at {now():%H:%M}: {p['symbol']} {p['qty']} ({p['product']}).", 8)
                if LIVE_ORDERS and status != "PAUSED":
                    side = "SELL" if p["qty"] > 0 else "BUY"
                    pending = sum(int(num(o.get("quantity"))) for o in orders if o.get("symbol") == p["symbol"] and str(o.get("action")).upper() == side)
                    q = abs(p["qty"]) - pending
                    if q > 0 and (now().date(), "sq-" + p["symbol"]) not in _exited:
                        _exited.add((now().date(), "sq-" + p["symbol"]))
                        r = c.placeorder(strategy="risk_guardian", symbol=p["symbol"], action=side, exchange=p["exchange"],
                                         price_type="MARKET", product=p["product"], quantity=q)
                        alert(c, f"SQUARE-OFF {p['symbol']} {side} {q}: {r}", 8)

    v = account_value(c, hold, pos, px)
    if _start_value is None or (_start_value[0] != now().date()):
        _start_value = (now().date(), v)
    chg = (v - _start_value[1]) / _start_value[1] if _start_value[1] else 0
    if chg <= -0.02:
        once(c, "dayloss2", f"Day loss {chg:.1%} (account ~{v:,.0f}). Warning level.", 7)
    if chg <= -DAY_LOSS_STOP:
        once(c, "dayloss3", f"Day loss {chg:.1%} > 3%: G3 - bots must stop new entries today.", 9)
    log("guardian_cycle", {"time": now().isoformat(timespec="seconds"), "status": status, "av": round(v), "day_chg": round(chg, 4),
                           "held": json.dumps(held), "open_sells": len([o for o in orders if str(o.get('action')).upper() == 'SELL'])})


def main():
    c = client()
    print(f"risk_guardian started, LIVE_ORDERS={LIVE_ORDERS}")
    while True:
        try:
            if market_open(c):
                cycle(c)
            elif now().hour >= 16:
                print("market closed for the day, exiting"); break
        except Exception as e:
            print("cycle error:", e)
            log("guardian_errors", {"time": now().isoformat(timespec="seconds"), "err": str(e)[:300]})
        time.sleep(CHECK_EVERY_SEC)


if __name__ == "__main__":
    main()
