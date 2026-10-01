"""
orb_paper.py  (v1, 2026-10-01) - Opening Range Breakout, PAPER ONLY (no orders, ever). Zero AI tokens.
Purpose: build real evidence for the experiments pot before any money is used ("paper-first" rule).
Rules (long and short, liquid stocks, 5-minute bars):
  - Opening range = high/low of 9:15-9:30.
  - Entry: first 5-min close above range high (long) or below range low (short) between 9:35 and 11:30,
    with that bar's volume >= 1.2x the average of the opening-range bars, and the trade direction
    agreeing with the stock vs its 20-day average (long only above, short only below).
  - Stop: other side of the range, capped at 1.2% from entry. Target: 2x risk. Exit at 15:10 otherwise.
  - Size: risk 1% of PAPER_CAPITAL per trade; costs ~0.06% round trip deducted.
Modes:
  python orb_paper.py --backtest 30     -> replays the last 30 sessions from OpenAlgo history
  python orb_paper.py                    -> live paper trading today (polls every 60 s, logs trades)
Output: logs/orb_paper_trades_<yyyymm>.csv  (+ Telegram end-of-day summary)
"""
import sys, time, datetime as dt
import pandas as pd
from common import client, now, num, alert, log, IST

SYMBOLS = "SBIN ICICIBANK HDFCBANK AXISBANK RELIANCE INFY TCS TATASTEEL BEL ITC LT KOTAKBANK".split()
PAPER_CAPITAL = 15000.0
RISK_FRAC, MAX_STOP, COST = 0.01, 0.012, 0.0006
ENTRY_FROM, ENTRY_TO, EXIT_AT = dt.time(9, 35), dt.time(11, 30), dt.time(15, 10)


def bars(c, sym, start, end, interval="5m"):
    df = c.history(symbol=sym, exchange="NSE", interval=interval, start_date=start, end_date=end)
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    df.columns = [x.lower() for x in df.columns]
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    return df


def trend_ok(daily_close, day, side):
    hist = daily_close[daily_close.index.date < day]
    if len(hist) < 20:
        return True
    above = hist.iloc[-1] > hist.tail(20).mean()
    return above if side == "L" else not above


def simulate_day(sym, d5, daily_close, day):
    day_bars = d5[d5.index.date == day]
    orng = day_bars.between_time("09:15", "09:29")
    if len(orng) < 3:
        return None
    hi, lo, ovol = orng["high"].max(), orng["low"].min(), orng["volume"].mean()
    pos = None
    for ts, b in day_bars.iterrows():
        t = ts.time()
        if pos is None and ENTRY_FROM <= t <= ENTRY_TO:
            for side, cond in (("L", b["close"] > hi), ("S", b["close"] < lo)):
                if cond and b["volume"] >= 1.2 * ovol and trend_ok(daily_close, day, side):
                    e = b["close"]
                    stop = lo if side == "L" else hi
                    if abs(e - stop) / e > MAX_STOP:
                        stop = e * (1 - MAX_STOP) if side == "L" else e * (1 + MAX_STOP)
                    risk = abs(e - stop)
                    tgt = e + 2 * risk if side == "L" else e - 2 * risk
                    qty = max(1, min(int(PAPER_CAPITAL * RISK_FRAC / risk), int(PAPER_CAPITAL * 4 / e)))  # 1% risk, exposure <= 4x capital (intraday margin)
                    pos = dict(sym=sym, day=str(day), side=side, entry_t=str(t), entry=round(e, 2), stop=round(stop, 2), tgt=round(tgt, 2), qty=qty)
                    break
            continue
        if pos:
            hit_stop = b["low"] <= pos["stop"] if pos["side"] == "L" else b["high"] >= pos["stop"]
            hit_tgt = b["high"] >= pos["tgt"] if pos["side"] == "L" else b["low"] <= pos["tgt"]
            exit_px = pos["stop"] if hit_stop else (pos["tgt"] if hit_tgt else (b["close"] if t >= EXIT_AT else None))
            if exit_px is not None:
                sign = 1 if pos["side"] == "L" else -1
                gross = sign * (exit_px - pos["entry"]) * pos["qty"]
                cost = COST * pos["entry"] * pos["qty"]
                r = sign * (exit_px - pos["entry"]) / abs(pos["entry"] - pos["stop"])
                pos.update(exit_t=str(t), exit=round(exit_px, 2), pl=round(gross - cost, 2), R=round(r, 2),
                           why="stop" if hit_stop else ("target" if hit_tgt else "time"))
                return pos
    return None


def backtest(sessions):
    c = client()
    end = now().date()
    start = end - dt.timedelta(days=int(sessions * 1.6) + 5)
    trades = []
    for s in SYMBOLS:
        try:
            d5 = bars(c, s, start.isoformat(), end.isoformat())
            dd = c.history(symbol=s, exchange="NSE", interval="D", start_date=(start - dt.timedelta(days=60)).isoformat(), end_date=end.isoformat())
            dd.columns = [x.lower() for x in dd.columns]
            dclose = dd["close"]; dclose.index = pd.to_datetime(dclose.index)
            for day in sorted(set(d5.index.date))[-sessions:]:
                t = simulate_day(s, d5, dclose, day)
                if t:
                    trades.append(t)
            time.sleep(0.3)
        except Exception as e:
            print(s, "skip:", e)
    df = pd.DataFrame(trades)
    if df.empty:
        print("no trades"); return
    wins = df[df.pl > 0]; losses = df[df.pl <= 0]
    pf = wins.pl.sum() / abs(losses.pl.sum()) if len(losses) and losses.pl.sum() else float("inf")
    summary = (f"ORB backtest {sessions} sessions, {len(SYMBOLS)} stocks: {len(df)} trades, win {len(wins)/len(df):.0%}, "
               f"avg R {df.R.mean():+.2f}, PF {pf:.2f}, net Rs {df.pl.sum():+.0f} on Rs {PAPER_CAPITAL:.0f} paper capital")
    df.to_csv(f"logs/orb_backtest_{now():%Y%m%d}.csv", index=False)
    alert(c, summary, 3); print(df.groupby("side").agg(n=("pl", "size"), pl=("pl", "sum"), R=("R", "mean")))


def live():
    c = client()
    today = now().date()
    done, results = set(), []
    while now().time() < dt.time(15, 20):
        if now().weekday() >= 5:
            return
        if now().time() >= dt.time(9, 36):
            for s in SYMBOLS:
                if s in done:
                    continue
                try:
                    d5 = bars(c, s, today.isoformat(), today.isoformat())
                    dd = c.history(symbol=s, exchange="NSE", interval="D", start_date=(today - dt.timedelta(days=60)).isoformat(), end_date=today.isoformat())
                    dd.columns = [x.lower() for x in dd.columns]; dclose = dd["close"]; dclose.index = pd.to_datetime(dclose.index)
                    t = simulate_day(s, d5, dclose, today) if d5 is not None else None
                    if t:
                        done.add(s); results.append(t); log("orb_paper_trades", t)
                        alert(c, f"ORB paper {t['sym']} {t['side']} {t['entry']}->{t['exit']} {t['why']} pl {t['pl']:+.0f} ({t['R']:+.1f}R)", 3)
                except Exception as e:
                    print(s, e)
        time.sleep(60)
    if results:
        tot = sum(r["pl"] for r in results)
        alert(c, f"ORB paper day {today}: {len(results)} trades, net Rs {tot:+.0f}", 4)


if __name__ == "__main__":
    if "--backtest" in sys.argv:
        i = sys.argv.index("--backtest")
        backtest(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 30)
    else:
        live()
