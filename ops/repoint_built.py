#!/usr/bin/env python3
"""
Repoint DNS for domains that have been built, so a generated site actually
serves at its own domain.

Safety: only domains present in build_queue are touched. That table can only
contain domains the operator selected, and live sites are excluded from
selection both in the UI and server-side. A hard protected list and an
explicit live-status check back that up.
"""
import json, os, subprocess, sqlite3, sys

NEW_IP = os.environ.get("NEW_IP", "207.148.0.22")
DB = "/opt/network-app/network.db"
INV = "/opt/network-app/data-merged.json"
KEYS = os.path.expanduser("~/.godaddy_keys")
PROTECTED = {"attorney.plus", "r0cketship.com", "jeff-cline.com", "medigap.plus", "medigap.ai"}
LIVE = {"LIVE_MULTIPAGE", "LIVE_SINGLE"}


def sh(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=40).stdout.strip()


def api(tok, method, path, body=None):
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method,
           "-H", f"Authorization: Bearer {tok}", "-H", "content-type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    cmd.append("https://api.godaddy.com" + path)
    out = sh(cmd).rsplit("\n", 1)
    return (out[1] if len(out) > 1 else "000"), (out[0] if out else "")


def main():
    toks = [l.strip() for l in open(KEYS) if l.strip()]
    inv = {r["domain"]: r for r in json.load(open(INV))}
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute("SELECT domain FROM build_queue WHERE state='built'").fetchall()

    for r in rows:
        d = r["domain"]
        if d in PROTECTED:
            print(f"  BLOCKED (protected): {d}"); continue
        rec = inv.get(d)
        if rec and rec.get("status") in LIVE:
            print(f"  BLOCKED (live site): {d}"); continue
        if "cloudflare" in sh(["dig", "+short", d, "NS"]).lower():
            print(f"  SKIP (Cloudflare DNS): {d}"); continue
        if sh(["dig", "+short", d, "A"]).split("\n")[0].strip() == NEW_IP:
            continue                                    # already correct
        for i, tok in enumerate(toks, 1):
            code, _ = api(tok, "GET", f"/v1/domains/{d}")
            if code != "200":
                continue
            code, body = api(tok, "PUT", f"/v1/domains/{d}/records/A",
                             [{"name": "@", "data": NEW_IP, "ttl": 600}])
            print(f"  {'OK  ' if code == '200' else 'FAIL'} {d} (acct {i}) HTTP {code}")
            break
        else:
            print(f"  NOT IN GODADDY: {d}")


if __name__ == "__main__":
    main()
