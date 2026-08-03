#!/usr/bin/env python3
"""
Repoint DNS for built domains so each generated site serves at its own domain.

Safety: only domains in build_queue are eligible. That table can only contain
domains the operator selected, and live sites are excluded from selection both
in the UI and server-side. A protected list and a live-status re-check back
that up. Domains whose DNS is not hosted at GoDaddy are skipped and reported,
never silently "changed".
"""
import json, os, subprocess, sqlite3

NEW_IP = os.environ.get("NEW_IP", "207.148.0.22")
DB = "/opt/network-app/network.db"
INV = "/opt/network-app/data-merged.json"
KEYS = "/root/.godaddy_keys"
PROTECTED = {"attorney.plus", "r0cketship.com", "jeff-cline.com", "medigap.plus", "medigap.ai"}
LIVE = {"LIVE_MULTIPAGE", "LIVE_SINGLE"}
GODADDY_NS = ("domaincontrol.com",)


def sh(args, timeout=40):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip()
    except Exception:
        return 1, ""


def api(tok, method, path, body=None):
    """Returns (http_code, body). Distinguishes a transport failure from an HTTP
    status: curl exiting non-zero means we never got a response at all."""
    cmd = ["curl", "-sS", "--max-time", "25", "-w", "\n%{http_code}", "-X", method,
           "-H", f"Authorization: Bearer {tok}", "-H", "content-type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    cmd.append("https://api.godaddy.com" + path)
    rc, out = sh(cmd)
    if rc != 0:
        return "CONN_FAIL", ""
    parts = out.rsplit("\n", 1)
    return (parts[-1].strip() or "000"), (parts[0] if len(parts) > 1 else "")


def main():
    toks = [l.strip() for l in open(KEYS) if l.strip()]
    inv = {r["domain"]: r for r in json.load(open(INV))}
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute("SELECT domain FROM build_queue WHERE state='built'").fetchall()

    done = skipped = failed = already = 0
    for r in rows:
        d = r["domain"]
        if d in PROTECTED:
            print(f"  BLOCKED (protected): {d}"); skipped += 1; continue
        rec = inv.get(d)
        if rec and rec.get("status") in LIVE:
            print(f"  BLOCKED (live site): {d}"); skipped += 1; continue

        _, ns = sh(["dig", "+short", d, "NS"])
        nsl = ns.lower()
        if nsl and not any(g in nsl for g in GODADDY_NS):
            host = nsl.split("\n")[0].strip(".") or "unknown"
            print(f"  SKIP {d} — DNS hosted elsewhere ({host}), change it there")
            skipped += 1; continue
        if not nsl:
            print(f"  SKIP {d} — no nameservers set, domain has no DNS zone")
            skipped += 1; continue

        _, cur = sh(["dig", "+short", d, "A"])
        if cur.split("\n")[0].strip() == NEW_IP:
            already += 1; continue

        for i, tok in enumerate(toks, 1):
            code, _ = api(tok, "GET", f"/v1/domains/{d}/records/A")
            if code != "200":
                continue
            code, body = api(tok, "PUT", f"/v1/domains/{d}/records/A",
                             [{"name": "@", "data": NEW_IP, "ttl": 600}])
            if code == "200":
                print(f"  OK   {d} (acct {i})"); done += 1
            else:
                print(f"  FAIL {d} (acct {i}) HTTP {code} {body[:90]}"); failed += 1
            break
        else:
            print(f"  NOT IN GODADDY DNS: {d}"); skipped += 1

    print(f"  [repointed {done} · already correct {already} · skipped {skipped} · failed {failed}]")


if __name__ == "__main__":
    main()
