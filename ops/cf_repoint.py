"""Decide which Cloudflare zones may be repointed. A zone qualifies only if we
built a site for it AND it currently serves nothing - never on zone membership
alone, since several of these are live sites."""
import json, re, sqlite3, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

APPLY = "--apply" in sys.argv
NET_IP = "207.148.0.22"
TOK = open("/root/.cloudflare").read().strip().split("=", 1)[1]
H = ["-H", f"Authorization: Bearer {TOK}", "-H", "content-type: application/json"]


def cf(method, path, body=None):
    cmd = ["curl", "-sS", "--max-time", "25", "-X", method] + H
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    cmd.append("https://api.cloudflare.com/client/v4" + path)
    p = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except Exception:
        return {"success": False, "raw": p.stdout[:200]}


zones = cf("GET", "/zones?per_page=50").get("result") or []
c = sqlite3.connect("/opt/network-app/network.db"); c.row_factory = sqlite3.Row
built = {r["domain"] for r in c.execute("SELECT domain FROM build_queue WHERE state='built'")}
held = {r["domain"] for r in c.execute("SELECT domain FROM dns_hold")}


def probe(name):
    p = subprocess.run(["curl", "-sk", "-L", "--max-time", "14", "-o", "-",
                        "-w", "\n#S#%{size_download}", f"https://{name}/"],
                       capture_output=True, text=True)
    body, _, size = p.stdout.rpartition("#S#")
    try:
        size = int(size.strip())
    except ValueError:
        size = 0
    m = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
    return name, size, re.sub(r"\s+", " ", (m.group(1) if m else "")).strip()[:44]


with ThreadPoolExecutor(max_workers=10) as ex:
    live = {n: (s, t) for n, s, t in ex.map(probe, [z["name"] for z in zones])}

plan, skip = [], []
for z in sorted(zones, key=lambda r: r["name"]):
    n = z["name"]
    size, title = live.get(n, (0, ""))
    if n in held:
        skip.append((n, "HELD — protected")); continue
    if n not in built:
        skip.append((n, f"not built by us ({size}b)")); continue
    if size > 5000 and "Coming soon" not in title:
        skip.append((n, f"** SERVING REAL CONTENT ** {size}b {title}")); continue
    plan.append((n, z["id"], size, title))

print("WILL REPOINT:" if APPLY else "WOULD REPOINT (dry run):")
for n, zid, size, title in plan:
    print(f"   {n:34} currently {size}b {title}")
print()
print("SKIPPED:")
for n, why in skip:
    print(f"   {n:34} {why}")

if APPLY:
    print("\napplying:")
    for n, zid, _, _ in plan:
        recs = cf("GET", f"/zones/{zid}/dns_records?type=A&name={n}").get("result") or []
        body = {"type": "A", "name": n, "content": NET_IP, "ttl": 600, "proxied": False}
        if recs:
            r = cf("PUT", f"/zones/{zid}/dns_records/{recs[0]['id']}", body)
        else:
            r = cf("POST", f"/zones/{zid}/dns_records", body)
        print(f"   {'OK  ' if r.get('success') else 'FAIL'} {n}"
              + ("" if r.get("success") else f"  {r.get('errors')}"))
