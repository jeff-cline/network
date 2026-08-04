#!/usr/bin/env python3
"""
Corporate mode: check the server, then the sites.

A portfolio of sites on one box shares one failure. Checking each site
independently turns a single stopped server into a hundred identical emails
and buries the one fact that matters. So:

  1. Group the account's sites by resolved IP.
  2. Per IP, probe one sentinel site. If it answers, the server is up.
  3. If it fails, probe a SECOND site on that IP. Two failures on two different
     hostnames is a server fault, not a site fault.
  4. Server down -> ONE email naming the server and everything on it. The
     individual sites are not checked and not alerted; they are consequences.
  5. Server up -> check the sites on their own schedule.

Suppression: a site only alerts if it is expected to be live. Sites that were
never built, or that the back office already knows are broken, are monitored
and displayed but never emailed — an alert for something already on a to-do
list is noise.
"""
import os, sqlite3, subprocess, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor


def resolve(host):
    for res in ("@1.1.1.1", "@8.8.8.8"):
        try:
            p = subprocess.run(["dig", "+short", "+time=2", "+tries=1", res, host, "A"],
                               capture_output=True, text=True, timeout=8)
            for line in p.stdout.splitlines():
                line = line.strip()
                if line and line[0].isdigit() and line.count(".") == 3:
                    return line
        except Exception:
            pass
    return ""


def group_by_ip(sites):
    """sites: rows with .url — returns {ip: [rows]} plus unresolved."""
    with ThreadPoolExecutor(max_workers=20) as ex:
        ips = list(ex.map(lambda s: resolve(s["url"]), sites))
    groups, unresolved = defaultdict(list), []
    for s, ip in zip(sites, ips):
        (groups[ip] if ip else unresolved).append(s)
    return groups, unresolved


def server_state(ip, members, probe, need=2):
    """Return (up, detail, tested). Probes a sentinel, then a second distinct
    hostname before blaming the server."""
    order = sorted(members, key=lambda s: s["url"])
    first = order[0]
    up, detail = probe(first["url"])
    if up:
        return True, f"{first['url']} responded", [first["url"]]
    if len(order) == 1:
        return False, f"{first['url']}: {detail}", [first["url"]]
    second = order[len(order) // 2] if order[len(order) // 2] is not first else order[1]
    up2, detail2 = probe(second["url"])
    if up2:
        # One site down, the server fine. Not a server incident.
        return True, f"{second['url']} responded ({first['url']} did not)", \
               [first["url"], second["url"]]
    return False, f"two hostnames failed on {ip}: {first['url']} and {second['url']}", \
           [first["url"], second["url"]]


def server_email(ip, members, detail, expect_live_count):
    rows = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;font-size:13px">{m["url"]}</td></tr>'
        for m in sorted(members, key=lambda s: s["url"])[:25])
    more = (f'<tr><td style="padding:4px 0;color:#8b93a7;font-size:12.5px">'
            f'…and {len(members) - 25} more</td></tr>') if len(members) > 25 else ""
    return f"""<div style="background:#f6f7f9;padding:26px">
<table style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e2e5ea;
border-radius:12px;width:100%;font:14px/1.6 -apple-system,sans-serif;border-collapse:collapse">
<tr><td style="padding:22px 24px">
<div style="font:800 12px -apple-system,sans-serif;color:#e5484d;letter-spacing:.07em">SERVER DOWN</div>
<h2 style="margin:6px 0 4px;font-size:21px">{ip} is not responding</h2>
<p style="color:#697084;margin:0 0 10px">{detail}</p>
<p style="margin:0 0 14px"><b>{len(members)} site{'s' if len(members) != 1 else ''}</b> are hosted
on this server{f', {expect_live_count} of which should be live' if expect_live_count != len(members) else ''}.
You are getting one email, not {len(members)}.</p>
<table style="border-collapse:collapse;margin-bottom:16px">{rows}{more}</table>
<a href="https://websitedowncheckers.com/app" style="display:inline-block;background:#ff5a1f;
color:#fff;text-decoration:none;font-weight:700;padding:10px 18px;border-radius:8px">
View dashboard</a></td></tr>
<tr><td style="padding:12px 24px;border-top:1px solid #e2e5ea;color:#8b93a7;font-size:12px">
Website Down Checkers · corporate account · server checked before its sites
</td></tr></table></div>"""


def server_recovered_email(ip, members, mins):
    return f"""<div style="background:#f6f7f9;padding:26px">
<table style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e2e5ea;
border-radius:12px;width:100%;font:14px/1.6 -apple-system,sans-serif;border-collapse:collapse">
<tr><td style="padding:22px 24px">
<div style="font:800 12px -apple-system,sans-serif;color:#2ea043;letter-spacing:.07em">RECOVERED</div>
<h2 style="margin:6px 0 4px;font-size:21px">{ip} is back</h2>
<p style="color:#697084;margin:0 0 8px">
{len(members)} site{'s' if len(members) != 1 else ''} restored
{f'after {mins} minutes' if mins else ''}.</p>
</td></tr></table></div>"""
