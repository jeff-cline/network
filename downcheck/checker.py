#!/usr/bin/env python3
"""
The product itself: check every customer site and alert their whole team.

Checks in this order, because these are the failure modes that actually take
small businesses offline:
  1. DNS resolves at all              — a lapsed domain or bad record
  2. The host answers on 80/443       — a stopped or suspended server
  3. HTTP returns a success status    — an application error
  4. The page is not a suspension or parking page — the unpaid-invoice case

Alerts fire on STATE CHANGE only, so one outage sends one email per recipient,
and recovery is reported with how long it lasted.
"""
import json, os, re, sqlite3, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "downcheck.db")
CORE = "https://medigap.plus"
CORE_KEY = os.environ.get("CORE_KEY", "")
CORE_SECRET = os.environ.get("CORE_SECRET", "")
QUIET = "--quiet" in sys.argv

# Phrases that only appear on an actual suspension or parking page. Deliberately
# specific: an earlier version matched the bare word "billing", which would have
# flagged any e-commerce or SaaS site that merely mentions it.
SUSPENDED = re.compile(
    r"suspendedpage\.cgi"
    r"|(?:this\s+)?(?:account|site|website|domain)\s+has\s+been\s+suspended"
    r"|account\s+suspended"
    r"|(?:your\s+)?service\s+has\s+been\s+suspended"
    r"|suspended\s+due\s+to\s+(?:non[- ]?payment|unpaid)"
    r"|(?:this\s+)?domain\s+(?:name\s+)?has\s+expired"
    r"|expired\s+and\s+is\s+pending\s+renewal"
    r"|this\s+domain\s+is\s+(?:for\s+sale|parked)"
    r"|buy\s+this\s+domain"
    r"|website\s+is\s+temporarily\s+unavailable\s+due\s+to\s+billing",
    re.I)


def sh(args, timeout=25):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


def check(url):
    """Return (up, detail)."""
    ip = ""
    for res in ("@1.1.1.1", "@8.8.8.8"):
        rc, out = sh(["dig", "+short", "+time=3", "+tries=1", res, url, "A"], timeout=12)
        cand = [l.strip() for l in out.splitlines()
                if l.strip() and re.fullmatch(r"[\d.]+", l.strip())]
        if rc == 0 and cand:
            ip = cand[0]
            break
    if not ip:
        return False, "domain does not resolve — DNS record missing or expired"

    if sh(["nc", "-z", "-w", "5", ip, "443"], timeout=12)[0] != 0 and \
       sh(["nc", "-z", "-w", "5", ip, "80"], timeout=12)[0] != 0:
        if sh(["ping", "-c", "2", "-W", "2", ip], timeout=12)[0] != 0:
            return False, f"server unreachable at {ip} — stopped, suspended or offline"
        return False, f"server at {ip} answers but the web server is not running"

    rc, out = sh(["curl", "-sk", "-L", "--max-time", "20", "-o", "-",
                  "-w", "\n#C#%{http_code}", f"https://{url}/"], timeout=30)
    if rc != 0:
        return False, "no HTTP response"
    body, _, code = out.rpartition("#C#")
    code = (code or "").strip()
    if not code.startswith(("2", "3")):
        return False, f"HTTP {code} — the site is returning an error"
    if SUSPENDED.search(body[:200_000]):
        return False, "serving a suspension or parking page — check hosting billing"
    return True, f"HTTP {code}"


def send(to, subject, html):
    if not (CORE_KEY and CORE_SECRET):
        return False
    payload = json.dumps({"to": to, "subject": subject, "html": html})
    for i in range(4):
        rc, out = sh(["curl", "-sS", "--max-time", "25", "-X", "POST",
                      "-H", f"x-core-key: {CORE_KEY}", "-H", f"x-core-secret: {CORE_SECRET}",
                      "-H", "content-type: application/json", "-d", payload,
                      CORE + "/api/core/email"], timeout=40)
        try:
            if json.loads(out).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(1.2 * (i + 1))
    return False


def body_html(url, up, detail, mins=None):
    if up:
        head, colour, word = "back online", "#2ea043", "RECOVERED"
        extra = f"<p>It was down for <b>{mins} minutes</b>.</p>" if mins else ""
    else:
        head, colour, word = "is down", "#e5484d", "DOWN"
        extra = ""
    return f"""<div style="background:#f6f7f9;padding:26px">
<table style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e5ea;
border-radius:12px;width:100%;font:14px -apple-system,sans-serif;border-collapse:collapse">
<tr><td style="padding:22px 24px">
<div style="font:800 13px -apple-system,sans-serif;color:{colour};letter-spacing:.06em">{word}</div>
<h2 style="margin:6px 0 4px;font-size:21px">{url} {head}</h2>
<p style="color:#697084;margin:0 0 14px">{detail}</p>{extra}
<a href="https://websitedowncheckers.com/app" style="display:inline-block;background:#ff5a1f;
color:#fff;text-decoration:none;font-weight:700;padding:10px 18px;border-radius:8px">
View dashboard</a>
</td></tr>
<tr><td style="padding:13px 24px;border-top:1px solid #e2e5ea;color:#8b93a7;font-size:12px">
Website Down Checkers · checked from outside your network
</td></tr></table></div>"""


def main():
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    sites = con.execute("SELECT * FROM sites WHERE active=1").fetchall()
    if not sites:
        if not QUIET:
            print("  no sites to check")
        return

    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda s: (s, *check(s["url"])), sites))

    now = time.time()
    changed = 0
    for s, up, detail in results:
        was = s["last_up"]
        first = was is None
        flip = (not first) and bool(was) != up
        since = s["since"] if (not flip and s["since"]) else now

        con.execute("""UPDATE sites SET last_up=?, last_detail=?, last_checked=?, since=?
                       WHERE id=?""", (int(up), detail, now, since, s["id"]))

        if flip:
            changed += 1
            mins = None
            if up:
                row = con.execute("""SELECT id, started FROM incidents WHERE site_id=? AND ended IS NULL
                                     ORDER BY started DESC LIMIT 1""", (s["id"],)).fetchone()
                if row:
                    mins = max(1, int((now - row["started"]) / 60))
                    con.execute("UPDATE incidents SET ended=? WHERE id=?", (now, row["id"]))
            else:
                con.execute("INSERT INTO incidents(site_id,started,detail) VALUES(?,?,?)",
                            (s["id"], now, detail))
            recips = [r["email"] for r in
                      con.execute("SELECT email FROM recipients WHERE site_id=?", (s["id"],))]
            subject = (f"🔴 {s['url']} is DOWN" if not up
                       else f"🟢 {s['url']} is back up" + (f" — {mins}m outage" if mins else ""))
            html = body_html(s["url"], up, detail, mins)
            for r in recips:
                send(r, subject, html)
            if not QUIET:
                print(f"    {'RECOVERED' if up else 'DOWN'} {s['url']} — {detail} "
                      f"→ {len(recips)} recipient(s)")
    con.commit()
    if not QUIET:
        down = sum(1 for _, up, _ in results if not up)
        print(f"  [checked {len(results)} · down {down} · changes {changed}]")


if __name__ == "__main__":
    main()
