#!/usr/bin/env python3
"""
Test every built site the way a visitor would, and record the result.

A green light here means the domain resolved to us, returned 200, served its
own title (not a neighbour's), and carried the lead form and rocket link.
Anything less is red with the reason, so "live" is never an assumption.
"""
import json, os, re, sqlite3, subprocess, time
from concurrent.futures import ThreadPoolExecutor

DB = "/opt/network-app/network.db"
OUR_IP = os.environ.get("NEW_IP", "207.148.0.22")


def sh(args, timeout=30):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


def check(row):
    d, expect_title = row["domain"], (row["title"] or "").strip()
    has_cert = os.path.exists("/etc/letsencrypt/live/" + d)
    scheme = "https" if has_cert else "http"

    # Query a public resolver, not the server's own. The local cache holds
    # pre-repoint values for the full TTL and produced false failures.
    ip = ""
    for resolver in ("@1.1.1.1", "@8.8.8.8", "@9.9.9.9"):
        rc, out = sh(["dig", "+short", "+time=3", "+tries=1", resolver, d, "A"])
        cand = [l.strip() for l in out.splitlines()
                if l.strip() and not l.startswith(";") and re.match(r"^[\d.]+$", l.strip())]
        if rc == 0 and cand:
            ip = cand[0]
            break
    if not ip:
        return d, 0, 0, has_cert, "no DNS record"
    if ip != OUR_IP:
        return d, 0, 0, has_cert, f"DNS points to {ip}"

    rc, out = sh(["curl", "-sL", "--max-time", "20", "-w", "\n#CODE#%{http_code}",
                  "--resolve", f"{d}:443:{OUR_IP}", "--resolve", f"{d}:80:{OUR_IP}",
                  f"{scheme}://{d}/"])
    if rc != 0:
        return d, 0, 0, has_cert, "connection failed"
    body, _, code = out.rpartition("#CODE#")
    try:
        code = int(code.strip())
    except ValueError:
        code = 0
    if code != 200:
        return d, 0, code, has_cert, f"HTTP {code}"

    m = re.search(r"<title>(.*?)</title>", body, re.S)
    got = (m.group(1) if m else "").strip()
    if expect_title and got[:40] != expect_title[:40]:
        return d, 0, code, has_cert, f"wrong title: {got[:40]!r}"
    if "api/lead" not in body:
        return d, 0, code, has_cert, "lead form missing"
    if "r0cketship.com" not in body:
        return d, 0, code, has_cert, "rocket link missing"
    return d, 1, code, has_cert, "https" if has_cert else "http only (no cert)"


def main():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS site_checks(
        domain TEXT PRIMARY KEY, ok INTEGER, code INTEGER,
        https INTEGER, detail TEXT, checked_at REAL)""")
    con.commit()
    rows = con.execute("SELECT domain,title FROM build_queue WHERE state='built'").fetchall()
    if not rows:
        print("  no built sites to check"); return
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check, rows))
    now = time.time()
    for d, ok, code, https, detail in results:
        con.execute("""INSERT INTO site_checks(domain,ok,code,https,detail,checked_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(domain) DO UPDATE SET
                         ok=excluded.ok, code=excluded.code, https=excluded.https,
                         detail=excluded.detail, checked_at=excluded.checked_at""",
                    (d, ok, code, int(https), detail, now))
    con.commit()
    good = sum(r[1] for r in results)
    print(f"  [tested {len(results)} · pass {good} · fail {len(results)-good}]")
    for d, ok, code, https, detail in sorted(results, key=lambda r: (r[1], r[0])):
        if not ok:
            print(f"    RED  {d} — {detail}")


if __name__ == "__main__":
    main()
