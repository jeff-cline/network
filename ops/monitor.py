#!/usr/bin/env python3
"""
Uptime monitor with email alerts.

Checks every server and every important site, and emails on STATE CHANGE only -
so a long outage produces one alert, not hundreds, and recovery is reported too.

Deliberately checks servers by IP as well as sites by hostname: a suspended
account or stopped instance takes everything with it, and that is the failure
that went unnoticed.
"""
import json, os, re, sqlite3, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

DB = "/opt/network-app/network.db"
CORE = "https://medigap.plus"
CORE_KEY = os.environ.get("CORE_KEY", "")
CORE_SECRET = os.environ.get("CORE_SECRET", "")
NOTIFY = os.environ.get("NOTIFY_TO", "jeff.cline@me.com")
QUIET = "--quiet" in sys.argv

SERVERS = [
    ("207.148.0.22",   "NETWORK — the site network + back office"),
    ("137.220.56.129", "R0cketShip — r0cketship.com, medigap.plus"),
    ("69.48.151.143",  "A2 suspended-acct server"),
    ("70.32.23.73",    "A2 working-acct server"),
    ("106.0.62.91",    "A2 third server"),
]
# Sites that must never be down quietly.
CRITICAL = [
    "network.r0cketship.com", "r0cketship.com", "medigap.plus", "medigap.ai",
    "1-800-medigap.com", "jeff-cline.com", "vrtcls.com", "keywordcalls.com",
    "alergies.com", "rentablemansions.com", "offtakers.org", "newcozumel.com",
]


def sh(args, timeout=25):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


def check_server(item):
    ip, label = item
    rc, _ = sh(["nc", "-z", "-w", "5", ip, "443"], timeout=12)
    if rc == 0:
        return ("server:" + ip, True, "port 443 open", label)
    rc22, _ = sh(["nc", "-z", "-w", "5", ip, "22"], timeout=12)
    if rc22 == 0:
        return ("server:" + ip, False, "SSH up but web server DOWN", label)
    rcp, _ = sh(["ping", "-c", "2", "-W", "2", ip], timeout=12)
    detail = "host unreachable — instance stopped or suspended" if rcp != 0 else \
             "pings but all services down"
    return ("server:" + ip, False, detail, label)


def check_site(host):
    rc, out = sh(["curl", "-sk", "-L", "--max-time", "20", "-o", "/dev/null",
                  "-w", "%{http_code}", f"https://{host}/"], timeout=30)
    code = (out or "").strip()
    if rc != 0 or code in ("", "000"):
        return ("site:" + host, False, "no response", host)
    if code.startswith(("2", "3")):
        return ("site:" + host, True, "HTTP " + code, host)
    return ("site:" + host, False, "HTTP " + code, host)


def send(subject, html):
    if not (CORE_KEY and CORE_SECRET):
        print("  [no CORE creds — cannot email]")
        return False
    body = json.dumps({"to": NOTIFY, "subject": subject, "html": html})
    for attempt in range(4):
        rc, out = sh(["curl", "-sS", "--max-time", "25", "-X", "POST",
                      "-H", f"x-core-key: {CORE_KEY}", "-H", f"x-core-secret: {CORE_SECRET}",
                      "-H", "content-type: application/json", "-d", body,
                      CORE + "/api/core/email"], timeout=40)
        try:
            if json.loads(out).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return False


def alert_html(changes):
    down = [c for c in changes if not c["up"]]
    up = [c for c in changes if c["up"]]
    rows = ""
    for c in down + up:
        colour = "#cf484d" if not c["up"] else "#2ea043"
        word = "DOWN" if not c["up"] else "RECOVERED"
        mins = int((time.time() - c["since"]) / 60) if c.get("since") else 0
        extra = f" after {mins} min" if c["up"] and mins else ""
        rows += (f'<tr><td style="padding:10px 14px;border-bottom:1px solid #e6e8ec">'
                 f'<b style="color:{colour}">{word}{extra}</b></td>'
                 f'<td style="padding:10px 14px;border-bottom:1px solid #e6e8ec">'
                 f'{c["label"]}<div style="color:#697084;font-size:12.5px">{c["detail"]}</div></td></tr>')
    return f"""<div style="background:#f6f7f9;padding:26px">
<table style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e2e5ea;
border-radius:12px;border-collapse:collapse;width:100%;font:14px -apple-system,sans-serif">
<tr><td colspan="2" style="padding:18px 20px;border-bottom:1px solid #e2e5ea">
<div style="font:700 17px -apple-system,sans-serif">🚀 Network status change</div>
<div style="color:#697084;font-size:13px;margin-top:2px">
{len(down)} down · {len(up)} recovered · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}</div>
</td></tr>{rows}
<tr><td colspan="2" style="padding:13px 20px;border-top:1px solid #e2e5ea;font-size:12px;color:#8b93a7">
<a href="https://network.r0cketship.com/status" style="color:#ff6b1a">View full status</a>
</td></tr></table></div>"""


def main():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS monitor(
        key TEXT PRIMARY KEY, label TEXT, up INTEGER, detail TEXT,
        since REAL, checked_at REAL)""")
    con.commit()
    prev = {r[0]: r for r in con.execute("SELECT key,up,since FROM monitor")}

    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(check_server, SERVERS)) + list(ex.map(check_site, CRITICAL))

    now = time.time()
    changes = []
    for key, up, detail, label in results:
        was = prev.get(key)
        since = now
        if was is not None and bool(was[1]) == up:
            since = was[2] or now
        elif was is not None:
            changes.append({"key": key, "label": label, "up": up,
                            "detail": detail, "since": was[2] or now})
        con.execute("""INSERT INTO monitor(key,label,up,detail,since,checked_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(key) DO UPDATE SET label=excluded.label, up=excluded.up,
                         detail=excluded.detail, since=excluded.since, checked_at=excluded.checked_at""",
                    (key, label, int(up), detail, since, now))
    con.commit()

    total_down = sum(1 for _, up, _, _ in results if not up)
    if not QUIET:
        print(f"  [checked {len(results)} · down {total_down} · changes {len(changes)}]")
        for key, up, detail, label in results:
            if not up:
                print(f"    DOWN {label} — {detail}")

    if changes:
        down_n = sum(1 for c in changes if not c["up"])
        subject = (f"{'🔴' if down_n else '🟢'} "
                   f"{down_n} DOWN" if down_n else "🟢 Recovered") + \
                  f" — {changes[0]['label'][:40]}" + (f" +{len(changes)-1} more" if len(changes) > 1 else "")
        ok = send(subject, alert_html(changes))
        print(f"  [alert emailed: {ok}] {subject}")


if __name__ == "__main__":
    main()
