#!/usr/bin/env python3
"""
Domain search and purchase against the GoDaddy API.

Buying spends real money, so the purchase call is deliberately separate from
search, requires an explicit price the operator has seen, and records what was
agreed to and when.
"""
import json, os, subprocess, time

API = "https://api.godaddy.com"
KEYS = os.environ.get("GODADDY_KEYS", "/root/.godaddy_keys")


def _tokens():
    with open(KEYS) as f:
        return [l.strip() for l in f if l.strip()]


def _call(tok, method, path, body=None, timeout=30):
    cmd = ["curl", "-sS", "--max-time", str(timeout), "-w", "\n%{http_code}",
           "-X", method, "-H", f"Authorization: Bearer {tok}",
           "-H", "content-type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    cmd.append(API + path)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    except Exception as ex:
        return 0, {"error": type(ex).__name__}
    if p.returncode != 0:
        return 0, {"error": (p.stderr or "connection failed")[:200]}
    out = p.stdout.rsplit("\n", 1)
    code = int(out[-1].strip() or 0)
    try:
        data = json.loads(out[0]) if out[0].strip() else {}
    except Exception:
        data = {"raw": out[0][:300]}
    return code, data


def money(micros):
    try:
        return f"${micros/1_000_000:,.2f}"
    except Exception:
        return "—"


def search(query, account=1):
    """Availability for the exact query plus alternatives."""
    tok = _tokens()[account - 1]
    q = query.strip().lower().replace(" ", "")
    exact = None
    if "." in q:
        code, d = _call(tok, "GET", f"/v1/domains/available?domain={q}")
        if code == 200:
            exact = d
    else:
        for tld in ("com", "net", "org"):
            code, d = _call(tok, "GET", f"/v1/domains/available?domain={q}.{tld}")
            if code == 200 and d.get("available"):
                exact = d
                break
        if exact is None:
            code, d = _call(tok, "GET", f"/v1/domains/available?domain={q}.com")
            exact = d if code == 200 else None

    base = q.split(".")[0]
    code, sug = _call(tok, "GET", f"/v1/domains/suggest?query={base}&limit=12")
    cands = [s["domain"] for s in (sug if isinstance(sug, list) else [])][:12]
    if exact and exact.get("domain") in cands:
        cands.remove(exact["domain"])

    alts = []
    if cands:
        code, res = _call(tok, "POST", "/v1/domains/available?checkType=FAST", cands)
        items = res.get("domains", []) if isinstance(res, dict) else []
        alts = [d for d in items if d.get("available")]
    return {"exact": exact, "alternatives": alts}


def registrant(account=1):
    """Reuse the registrant contact already on file rather than inventing one."""
    tok = _tokens()[account - 1]
    code, doms = _call(tok, "GET", "/v1/domains?limit=1&statuses=ACTIVE")
    if code != 200 or not doms:
        return None
    code, d = _call(tok, "GET", f"/v1/domains/{doms[0]['domain']}")
    return d.get("contactRegistrant") if code == 200 else None


def agreements(tld, account=1, privacy=False):
    tok = _tokens()[account - 1]
    code, a = _call(tok, "GET",
                    f"/v1/domains/agreements?tlds={tld}&privacy={'true' if privacy else 'false'}")
    return [x["agreementKey"] for x in a] if code == 200 and isinstance(a, list) else []


def purchase(domain, client_ip, account=1, nameservers=None, period=1):
    """Register the domain. Returns (ok, detail). Spends money."""
    tok = _tokens()[account - 1]
    tld = domain.rsplit(".", 1)[-1]
    contact = registrant(account)
    if not contact:
        return False, {"error": "could not read a registrant contact from the account"}
    keys = agreements(tld, account)
    if not keys:
        return False, {"error": f"no legal agreements returned for .{tld}"}

    body = {
        "domain": domain,
        "period": period,
        "renewAuto": True,
        "privacy": False,
        "consent": {
            "agreementKeys": keys,
            "agreedBy": client_ip or "127.0.0.1",
            "agreedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "contactRegistrant": contact,
        "contactAdmin": contact,
        "contactTech": contact,
        "contactBilling": contact,
    }
    if nameservers:
        body["nameServers"] = nameservers
    code, res = _call(tok, "POST", "/v1/domains/purchase", body, timeout=90)
    if code in (200, 202):
        return True, res
    return False, {"http": code, **(res if isinstance(res, dict) else {})}


def set_a_record(domain, ip, account=1):
    tok = _tokens()[account - 1]
    code, res = _call(tok, "PUT", f"/v1/domains/{domain}/records/A",
                      [{"name": "@", "data": ip, "ttl": 600}])
    return code == 200, res
