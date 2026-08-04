#!/usr/bin/env python3
"""
Decide which of the owner's sites are allowed to raise an alert.

The rule the operator asked for: only email about sites that SHOULD be live and
then go down. Two categories stay silent —

  never built      : no site exists yet, so "down" is expected, not news
  already known    : the back office already flags it as needing a fix, so an
                     email adds nothing to a list you are already working from

Both are still checked and shown on the dashboard. They just do not email.
Run from the network server, which holds the back office database.
"""
import json, sqlite3, subprocess, sys

NETWORK_DB = "/opt/network-app/network.db"


def decide():
    con = sqlite3.connect(NETWORK_DB)
    con.row_factory = sqlite3.Row
    out = {}

    built = {r["domain"] for r in
             con.execute("SELECT domain FROM build_queue WHERE state='built'")}
    checks = {r["domain"]: r["ok"] for r in con.execute("SELECT domain, ok FROM site_checks")}
    held = {r["domain"] for r in con.execute("SELECT domain FROM dns_hold")}
    queued = {r["domain"] for r in
              con.execute("SELECT domain FROM build_queue WHERE state IN ('ready','queued')")}
    awaiting = {r["domain"] for r in con.execute("SELECT domain FROM selections")}

    for d in built:
        if checks.get(d) == 0:
            out[d] = (0, "back office already reports this as broken")
        else:
            out[d] = (1, None)
    for d in held:
        out[d] = (1, None)              # live on their original hosting
    for d in queued | awaiting:
        out.setdefault(d, (0, "not built yet"))
    return out


if __name__ == "__main__":
    print(json.dumps(decide()))
