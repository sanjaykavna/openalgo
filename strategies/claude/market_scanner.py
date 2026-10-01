"""
market_scanner.py  (v1, 2026-10-01) - trend/momentum scanner on OpenAlgo daily data. Zero AI tokens.
Scans a liquid universe, ranks LONG (uptrend + relative strength) and SHORT (downtrend + weakness)
ideas, gives a market phase hint, writes logs/scan_<date>_<time>.csv and sends a Telegram summary.
Run once:  python market_scanner.py          Run at set times all day:  python market_scanner.py --loop
Read-only: never places orders.
"""
import sys, time, datetime as dt
import pandas as pd
from common import client, now, data, num, alert, LOG_DIR, market_open

UNIVERSE = ("RELIANCE TCS HDFCBANK ICICIBANK INFY SBIN BHARTIARTL ITC LT HINDUNILVR KOTAKBANK AXISBANK "
            "BAJFINANCE MARUTI SUNPHARMA HCLTECH TITAN NTPC POWERGRID ONGC COALINDIA TATASTEEL JSWSTEEL "
            "HINDALCO M&M ULTRACEMCO ADANIPORTS BEL HAL TRENT TECHM WIPRO DRREDDY CIPLA NESTLEIND "
            "ASIANPAINT GRASIM INDUSINDBK BAJAJFINSV TATAMOTORS EICHERMOT HEROMOTOCO BPCL IOC GAIL "
            "DLF LUPIN DIVISLAB APOLLOHOSP SIEMENS PIDILITIND DABUR MARICO TVSMOTOR VEDL BANKBARODA "
            "PNB CANBK RECLTD PFC").split()
RUN_TIMES = [dt.time(10, 35), dt.time(13, 35), dt.time(15, 35)]


def daily(c, sym, days=320):
    end = now().date()
    start = end - dt.timedelta(days=int(days * 1.5))
    df = c.history(symbol=sym, exchange="NSE_INDEX" if sym == "NIFTY" else "NSE", interval="D",
                   start_date=start.isoformat(), end_date=end.isoformat())
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    df.columns = [x.lower() for x in df.columns]
    return df.tail(days)


def metrics(df, nifty_ret20):
    cl, vol = df["close"], df.get("volume")
    last = cl.iloc[-1]
    d20, d50, d200 = cl.rolling(20).mean(), cl.rolling(50).mean(), cl.rolling(200).mean()
    ret20 = last / cl.iloc[-21] - 1 if len(cl) > 21 else 0
    hi52, lo52 = cl.tail(250).max(), cl.tail(250).min()
    tr = (df["high"] - df["low"]).tail(14).mean()
    vr = float(vol.iloc[-1] / vol.tail(21).iloc[:-1].mean()) if vol is not None and vol.tail(21).iloc[:-1].mean() > 0 else 1.0
    return {
        "close": round(last, 2), "chg1d%": round((last / cl.iloc[-2] - 1) * 100, 2),
        "ret20%": round(ret20 * 100, 2), "rs20%": round((ret20 - nifty_ret20) * 100, 2),
        "above20": last > d20.iloc[-1], "above50": last > d50.iloc[-1], "above200": bool(len(cl) >= 200 and last > d200.iloc[-1]),
        "rising20": d20.iloc[-1] > d20.iloc[-6], "rising50": d50.iloc[-1] > d50.iloc[-6],
        "from52h%": round((last / hi52 - 1) * 100, 2), "from52l%": round((last / lo52 - 1) * 100, 2),
        "atr%": round(tr / last * 100, 2), "volx": round(vr, 2),
    }


def phase_hint(n):
    cl = n["close"]; d50, d200 = cl.rolling(50).mean(), cl.rolling(200).mean()
    last = cl.iloc[-1]; ll = cl.tail(20).min() <= cl.tail(60).min()
    if last < d200.iloc[-1] and ll:
        return "DOWN (below 200DMA, fresh lows)"
    if last > d50.iloc[-1] and d50.iloc[-1] > d50.iloc[-6]:
        return "UP (above rising 50DMA)" if last < d200.iloc[-1] * 1.12 else "HOT (far above 200DMA)"
    return "BASE (no new low, trend unclear)"


def scan():
    c = client()
    n = daily(c, "NIFTY")
    n_ret20 = n["close"].iloc[-1] / n["close"].iloc[-21] - 1
    rows = []
    for s in UNIVERSE:
        try:
            df = daily(c, s)
            if df is None or len(df) < 60:
                continue
            m = metrics(df, n_ret20); m["symbol"] = s
            m["long_score"] = (2 * m["above20"] + 2 * m["above50"] + m["above200"] + m["rising20"] + m["rising50"]
                               + (m["rs20%"] > 0) * 2 + (m["from52h%"] > -5) + (m["volx"] > 1.5))
            m["short_score"] = (2 * (not m["above20"]) + 2 * (not m["above50"]) + (not m["rising20"]) + (not m["rising50"])
                                + (m["rs20%"] < 0) * 2 + (m["from52l%"] < 5) + (m["volx"] > 1.5 and m["chg1d%"] < 0))
            rows.append(m)
            time.sleep(0.2)
        except Exception as e:
            print(s, "skip:", e)
    df = pd.DataFrame(rows)
    longs = df.sort_values(["long_score", "rs20%"], ascending=False).head(8)
    shorts = df.sort_values(["short_score", "rs20%"], ascending=[False, True]).head(5)
    out = f"{LOG_DIR}/scan_{now():%Y%m%d_%H%M}.csv"
    df.sort_values("long_score", ascending=False).to_csv(out, index=False)
    ph = phase_hint(n)
    msg = (f"SCAN {now():%d-%b %H:%M} | Nifty {n['close'].iloc[-1]:.0f}, 20d {n_ret20:+.1%} | phase hint: {ph}\n"
           "LONG: " + ", ".join(f"{r.symbol}({r['rs20%']:+.1f}% RS)" for _, r in longs.iterrows()) + "\n"
           "SHORT: " + ", ".join(f"{r.symbol}({r['rs20%']:+.1f}% RS)" for _, r in shorts.iterrows()))
    alert(c, msg, 3)
    print("saved", out)


if __name__ == "__main__":
    if "--loop" in sys.argv:
        done = set()
        while now().hour < 16:
            t = now().time().replace(second=0, microsecond=0)
            for rt in RUN_TIMES:
                if t >= rt and rt not in done and now().weekday() < 5:
                    done.add(rt); scan()
            time.sleep(30)
    else:
        scan()
