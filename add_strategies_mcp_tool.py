#!/usr/bin/env python
"""
add_strategies_mcp_tool.py - adds ONE read-only MCP tool to your OpenAlgo: get_python_strategies
so the scheduled Claude bots read your /python strategies' status, logs and results through the
OpenAlgo MCP they already use (no extra URL, no extra tunnel port).

Run once from the OpenAlgo folder (the one with app.py), with OpenAlgo stopped:
    python add_strategies_mcp_tool.py
Then start OpenAlgo again. Safe to run twice (it skips if already added). Backups: *.bak-strategies-tool
Undo: python add_strategies_mcp_tool.py --undo

What the tool returns (read-only, places no orders, needs the read:account scope):
  - every /python strategy: name, exchange, schedule, running or not
  - the last lines of each strategy's newest log (log/strategies/)
  - the helper summary (risk guardian, scanner, paper-strategy records) built by the uploaded
    Helper Feed script's feed() function - the Helper Feed strategy does NOT need to be running.
"""
import os, sys, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(ROOT, "mcp", "mcpserver.py")
REGISTRY = os.path.join(ROOT, "utils", "mcp_tool_registry.py")
MARK = "# >>> get_python_strategies (added by add_strategies_mcp_tool.py)"
END = "# <<< get_python_strategies"
BAK = ".bak-strategies-tool"

TOOL = MARK + r'''
@openalgo_tool('account', title="Get Python Strategies Status and Results", risk=RISK_EXTERNAL_TEXT, open_world=False)
def get_python_strategies(log_lines: int = 25, include_feed: bool = True) -> str:
    """
    Read-only view of the strategies hosted on OpenAlgo's /python page.

    Args:
        log_lines: last N lines of each strategy's newest log (0-80, default 25)
        include_feed: also return the helper summary (risk guardian alerts, market scanner
            lists, paper-strategy records) built from the strategies' result files

    Returns:
        JSON: strategies[] (id, name, exchange, running, schedule, log_file, log_age_min, log_tail),
        feed (plain-text summary or a note why it is unavailable). Places no orders.
    """
    import glob as _glob
    import importlib.util as _ilu
    from datetime import datetime as _dt
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    n = max(0, min(int(log_lines or 0), 80))
    out = {"strategies": [], "feed": None}
    try:
        cfg_path = os.path.join(base, "strategies", "strategy_configs.json")
        cfgs = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
    except Exception as e:
        return _error(f"cannot read strategy configs: {e}")
    try:
        import psutil as _ps
    except Exception:
        _ps = None
    feed_script = None
    for sid, c in (cfgs or {}).items():
        if not isinstance(c, dict):
            continue
        running = bool(c.get("is_running"))
        pid = c.get("pid")
        if running and pid and _ps is not None:
            try:
                running = _ps.pid_exists(int(pid)) and _ps.Process(int(pid)).is_running()
            except Exception:
                pass
        logs = sorted(_glob.glob(os.path.join(base, "log", "strategies", f"{sid}_*.log")), key=os.path.getmtime)
        tail, age, lf = [], None, None
        if logs:
            lf = logs[-1]
            age = int((_dt.now().timestamp() - os.path.getmtime(lf)) // 60)
            if n:
                try:
                    with open(lf, encoding="utf-8", errors="replace") as f:
                        tail = [ln.rstrip()[:300] for ln in f.readlines()[-n:]]
                except Exception as e:
                    tail = [f"(log unreadable: {e})"]
        fp = c.get("file_path") or ""
        fp = fp if os.path.isabs(fp) else os.path.join(base, fp)
        try:
            if os.path.exists(fp) and "def feed(" in open(fp, encoding="utf-8", errors="ignore").read():
                feed_script = fp
        except Exception:
            pass
        out["strategies"].append({
            "id": sid, "name": c.get("name"), "exchange": c.get("exchange"), "running": running,
            "schedule": f"{c.get('schedule_start')}-{c.get('schedule_stop')} {c.get('schedule_days')}",
            "paused_reason": c.get("paused_reason"), "log_file": os.path.basename(lf) if lf else None,
            "log_age_min": age, "log_tail": tail,
        })
    if include_feed:
        if feed_script:
            try:
                spec = _ilu.spec_from_file_location("_oa_helper_feed", feed_script)
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                out["feed"] = mod.feed()
            except Exception as e:
                out["feed"] = f"helper feed failed: {e}"
        else:
            out["feed"] = "no uploaded strategy has a feed() function (upload helper_feed.py)"
    return json.dumps(out, indent=1, default=str)
''' + END + "\n\n"


def backup(p):
    if not os.path.exists(p + BAK):
        shutil.copy2(p, p + BAK)


def main():
    for p in (SERVER, REGISTRY):
        if not os.path.exists(p):
            sys.exit(f"Not found: {p}\nRun this from the OpenAlgo folder (the one with app.py).")
    s = open(SERVER, encoding="utf-8").read()
    r = open(REGISTRY, encoding="utf-8").read()

    if "--undo" in sys.argv:
        for p in (SERVER, REGISTRY):
            if os.path.exists(p + BAK):
                shutil.copy2(p + BAK, p)
                print("restored", p)
        return

    needed = ["def openalgo_tool(", "RISK_EXTERNAL_TEXT", "def _error(", "\n_finalize_registry()\n"]
    missing = [x.strip() for x in needed if x not in s]
    if missing or "TOOL_SCOPES" not in r or "SCOPE_READ_ACCOUNT" not in r:
        sys.exit(f"Your OpenAlgo version looks different (missing: {missing or 'registry entries'}). "
                 "Nothing was changed - send this message to Claude.")

    if MARK in s:
        print("mcpserver.py: tool already added")
    else:
        backup(SERVER)
        i = s.rindex("\n_finalize_registry()\n")
        s = s[:i] + "\n\n" + TOOL + s[i:]
        open(SERVER, "w", encoding="utf-8").write(s)
        print("mcpserver.py: get_python_strategies added")

    if '"get_python_strategies"' in r:
        print("mcp_tool_registry.py: scope already added")
    else:
        anchor = '    "analyzer_status": SCOPE_READ_ACCOUNT,\n'
        if anchor not in r:
            sys.exit("mcp_tool_registry.py: anchor not found - send this message to Claude. "
                     "(mcpserver.py was changed; run with --undo to revert.)")
        backup(REGISTRY)
        r = r.replace(anchor, anchor + '    "get_python_strategies": SCOPE_READ_ACCOUNT,  # read-only /python status + logs\n', 1)
        open(REGISTRY, "w", encoding="utf-8").write(r)
        print("mcp_tool_registry.py: scope added")

    try:   # syntax check
        import py_compile
        py_compile.compile(SERVER, doraise=True)
        py_compile.compile(REGISTRY, doraise=True)
        print("OK - restart OpenAlgo (start-openalgo.bat). The bots will see the tool on their next run.")
    except Exception as e:
        print("Syntax check failed:", e, "\nRun: python add_strategies_mcp_tool.py --undo  and tell Claude.")


if __name__ == "__main__":
    main()
