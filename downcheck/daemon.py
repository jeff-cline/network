#!/usr/bin/env python3
"""
Continuous checker. Each site is checked on its plan's interval; a 3-second
tier needs a running loop, not a per-minute cron.

The confirmation policy is the product's core promise. A site is only declared
down after N consecutive independent failures, each a fresh request, with a
short pause between them. A single blip never sends an email. Recovery works
the same way in reverse, so a flapping site does not spam anyone.
"""
import os, re, sqlite3, subprocess, sys, time, json, threading
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from tiers import plan  # noqa: E402
import corporate  # noqa: E402

DB = os.path.join(BASE, "downcheck.db")
CORE = "https://medigap.plus"
CORE_KEY = os.environ.get("CORE_KEY", "")
CORE_SECRET = os.environ.get("CORE_SECRET", "")
RECHECK_GAP = float(os.environ.get("RECHECK_GAP", "2.0"))

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
    r"|website\s+is\s+temporarily\s+unavailable\s+due\s+to\s+billing", re.I)


def sh(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


def probe(url):
    """One independent observation. Returns (up, detail)."""
    ip = ""
    for res in ("@1.1.1.1", "@8.8.8.8"):
        rc, out = sh(["dig", "+short", "+time=2", "+tries=1", res, url, "A"], timeout=8)
        cand = [l.strip() for l in out.splitlines()
                if l.strip() and re.fullmatch(r"[\d.]+", l.strip())]
        if rc == 0 and cand:
            ip = cand[0]
            break
    if not ip:
        return False, "domain does not resolve — DNS record missing or expired"

    if sh(["nc", "-z", "-w", "4", ip, "443"], timeout=8)[0] != 0 and \
       sh(["nc", "-z", "-w", "4", ip, "80"], timeout=8)[0] != 0:
        if sh(["ping", "-c", "2", "-W", "2", ip], timeout=8)[0] != 0:
            return False, f"server unreachable at {ip} — stopped, suspended or offline"
        return False, f"server at {ip} answers but the web server is not running"

    rc, out = sh(["curl", "-sk", "-L", "--max-time", "15", "-o", "-",
                  "-w", "\n#C#%{http_code}", f"https://{url}/"], timeout=22)
    if rc != 0:
        return False, "no HTTP response"
    body, _, code = out.rpartition("#C#")
    code = (code or "").strip()
    if not code.startswith(("2", "3")):
        return False, f"HTTP {code} — the site is returning an error"
    if SUSPENDED.search(body[:200_000]):
        return False, "serving a suspension or parking page — check hosting billing"
    return True, f"HTTP {code}"


def confirmed(url, need):
    """Observe until `need` consecutive results agree. A single blip cannot
    produce an alert, which is the whole point."""
    first_up, first_detail = probe(url)
    if need <= 1:
        return first_up, first_detail, 1
    agree = 1
    detail = first_detail
    for _ in range(need - 1):
        time.sleep(RECHECK_GAP)
        up, d = probe(url)
        if up != first_up:
            # Observations disagree: treat as still-healthy noise, not an outage.
            return None, f"inconclusive ({detail} then {d})", agree + 1
        agree += 1
        detail = d
    return first_up, detail, agree


def send(to, subject, html):
    if not (CORE_KEY and CORE_SECRET):
        return False
    payload = json.dumps({"to": to, "subject": subject, "html": html})
    for i in range(4):
        rc, out = sh(["curl", "-sS", "--max-time", "22", "-X", "POST",
                      "-H", f"x-core-key: {CORE_KEY}", "-H", f"x-core-secret: {CORE_SECRET}",
                      "-H", "content-type: application/json", "-d", payload,
                      CORE + "/api/core/email"], timeout=35)
        try:
            if json.loads(out).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(1.2 * (i + 1))
    return False


def mail_body(url, up, detail, mins, checks):
    if up:
        colour, word, head = "#2ea043", "RECOVERED", "is back online"
        extra = f"<p style='margin:0 0 14px'>It was down for <b>{mins} minutes</b>.</p>" if mins else ""
    else:
        colour, word, head = "#e5484d", "DOWN", "is down"
        extra = ""
    return f"""<div style="background:#f6f7f9;padding:26px">
<table style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e5ea;
border-radius:12px;width:100%;font:14px/1.6 -apple-system,sans-serif;border-collapse:collapse">
<tr><td style="padding:22px 24px">
<div style="font:800 12px -apple-system,sans-serif;color:{colour};letter-spacing:.07em">{word}</div>
<h2 style="margin:6px 0 4px;font-size:21px">{url} {head}</h2>
<p style="color:#697084;margin:0 0 12px">{detail}</p>{extra}
<p style="color:#8b93a7;margin:0 0 16px;font-size:12.5px">
Confirmed by {checks} independent checks before sending — we do not alert on a single blip.</p>
<a href="https://websitedowncheckers.com/app" style="display:inline-block;background:#ff5a1f;
color:#fff;text-decoration:none;font-weight:700;padding:10px 18px;border-radius:8px">
View dashboard</a></td></tr>
<tr><td style="padding:12px 24px;border-top:1px solid #e2e5ea;color:#8b93a7;font-size:12px">
Website Down Checkers · checked from outside your network
</td></tr></table></div>"""


def handle(site_row, suppressed=frozenset()):
    """Check one site and act on a confirmed state change.

    Two reasons an alert is withheld: the site sits on a server already reported
    down (the outage was emailed once, at server level), or the site is not
    expected to be live — never built, or already known-broken in the operator's
    own system. Both are still checked and recorded, just not emailed."""
    sid, url, tier = site_row["id"], site_row["url"], site_row["plan"]
    p = plan(tier)
    up, detail, checks = confirmed(url, p["confirmations"])
    now = time.time()
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        s = con.execute("SELECT * FROM sites WHERE id=?", (sid,)).fetchone()
        if not s:
            return
        if up is None:                       # observations disagreed - record, do not alert
            con.execute("UPDATE sites SET last_checked=?, last_detail=? WHERE id=?",
                        (now, detail, sid))
            con.commit()
            return
        was = s["last_up"]
        first = was is None
        flip = (not first) and bool(was) != up
        since = s["since"] if (not flip and s["since"]) else now
        con.execute("""UPDATE sites SET last_up=?, last_detail=?, last_checked=?, since=?
                       WHERE id=?""", (int(up), detail, now, since, sid))
        alertable = bool(s["expect_live"]) and sid not in suppressed
        if flip:
            mins = None
            if up:
                r = con.execute("""SELECT id, started FROM incidents WHERE site_id=? AND ended IS NULL
                                   ORDER BY started DESC LIMIT 1""", (sid,)).fetchone()
                if r:
                    mins = max(1, int((now - r["started"]) / 60))
                    con.execute("UPDATE incidents SET ended=? WHERE id=?", (now, r["id"]))
            else:
                con.execute("INSERT INTO incidents(site_id,started,detail) VALUES(?,?,?)",
                            (sid, now, detail))
            con.commit()
            if alertable:
                recips = [r["email"] for r in
                          con.execute("SELECT email FROM recipients WHERE site_id=?", (sid,))]
                subj = (f"🔴 {url} is DOWN" if not up else
                        f"🟢 {url} is back up" + (f" — {mins}m outage" if mins else ""))
                body = mail_body(url, up, detail, mins, checks)
                for r in recips:
                    send(r, subj, body)
                print(f"  {'RECOVERED' if up else 'DOWN'} {url} ({p['name']}) — {detail} "
                      f"→ {len(recips)} recipient(s)", flush=True)
            else:
                why = ("server already reported down" if sid in suppressed
                       else "not expected live — suppressed")
                print(f"  (silent) {url} {'down' if not up else 'up'} — {why}", flush=True)
        con.commit()
    finally:
        con.close()



# ---------- corporate mode ----------
def corporate_pass(account_row):
    """Server-first sweep for one corporate account. Returns the set of site ids
    that sit on a server currently believed down, so the per-site pass can skip
    them entirely rather than emailing about each consequence."""
    aid = account_row["id"]
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS servers(
            account_id INTEGER, ip TEXT, up INTEGER, detail TEXT, since REAL,
            checked_at REAL, PRIMARY KEY(account_id, ip))""")
        sites = con.execute("SELECT * FROM sites WHERE account_id=? AND active=1",
                            (aid,)).fetchall()
        if not sites:
            return set()
        groups, unresolved = corporate.group_by_ip(sites)
        prev = {r["ip"]: r for r in
                con.execute("SELECT * FROM servers WHERE account_id=?", (aid,))}
        recips = [r["email"] for r in con.execute(
            """SELECT DISTINCT email FROM recipients WHERE site_id IN
               (SELECT id FROM sites WHERE account_id=?)""", (aid,))]
        now = time.time()
        suppressed = set()

        for ip, members in groups.items():
            up, detail, tested = corporate.server_state(ip, members, probe)
            was = prev.get(ip)
            first = was is None
            flip = (not first) and bool(was["up"]) != up
            since = was["since"] if (was and not flip and was["since"]) else now
            con.execute("""INSERT INTO servers(account_id,ip,up,detail,since,checked_at)
                           VALUES(?,?,?,?,?,?)
                           ON CONFLICT(account_id,ip) DO UPDATE SET
                             up=excluded.up, detail=excluded.detail,
                             since=excluded.since, checked_at=excluded.checked_at""",
                        (aid, ip, int(up), detail, since, now))
            if not up:
                suppressed |= {m["id"] for m in members}
            if flip:
                live_n = sum(1 for m in members if m["expect_live"])
                if not up:
                    subj = (f"🔴 Server {ip} is DOWN — {len(members)} sites affected")
                    body = corporate.server_email(ip, members, detail, live_n)
                else:
                    mins = int((now - (was["since"] or now)) / 60) if was else 0
                    subj = f"🟢 Server {ip} recovered — {len(members)} sites back"
                    body = corporate.server_recovered_email(ip, members, mins)
                for r in recips:
                    send(r, subj, body)
                print(f"  SERVER {'DOWN' if not up else 'UP'} {ip} "
                      f"({len(members)} sites) → {len(recips)} recipient(s)", flush=True)
        con.commit()
        return suppressed
    finally:
        con.close()


def due(now):
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("""SELECT s.*, COALESCE(a.plan,'starter') plan
                              FROM sites s JOIN accounts a ON a.id=s.account_id
                              WHERE s.active=1""").fetchall()
    finally:
        con.close()
    out = []
    for s in rows:
        iv = plan(s["plan"])["interval"]
        if not s["last_checked"] or (now - s["last_checked"]) >= iv:
            out.append(s)
    return out


CORP_INTERVAL = int(os.environ.get("CORP_INTERVAL", "120"))


def main():
    print("checker daemon started", flush=True)
    last_corp = 0.0
    suppressed = set()
    while True:
        start = time.time()
        if start - last_corp >= CORP_INTERVAL:
            con = sqlite3.connect(DB, timeout=20); con.row_factory = sqlite3.Row
            try:
                corps = con.execute(
                    "SELECT * FROM accounts WHERE account_type='corporate'").fetchall()
            except sqlite3.OperationalError:
                corps = []
            finally:
                con.close()
            suppressed = set()
            for a in corps:
                suppressed |= corporate_pass(a)
            last_corp = start
        batch = due(start)
        if batch:
            with ThreadPoolExecutor(max_workers=16) as ex:
                list(ex.map(lambda s: handle(s, suppressed), batch))
        time.sleep(max(0.75, 1.0 - (time.time() - start)))


if __name__ == "__main__":
    if "--once" in sys.argv:
        for s in due(time.time()):
            handle(s)
    else:
        main()
