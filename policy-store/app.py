"""Policy Store — the first fully autonomous insurance agency.

A conversational quoting agent that rates from the carrier's own sheet, enrols
by text, hands payment to the third-party administrator, and posts the sale into
a ping-post endpoint. Everything a human agency does, minus the humans.

Two things are deliberate and worth knowing before reading further:

1. The demo gate. The whole site sits behind one password until it is switched
   off in the admin panel. Nothing leaks while the carrier paperwork is pending.

2. Rates. Travel 365 prices are real — they came off the carrier's pricing
   sheet. AD&D, Accident Medical and Critical Illness rates were NOT in the
   workbook we were given, so they load from rates.json and ship as clearly
   marked demo values. Every quote built from them says so, on screen, in the
   quote record, and in the ping-post payload. Replacing them is one paste in
   Admin → Rates.
"""
import hashlib, hmac, html, json, os, re, secrets, sqlite3, subprocess, time
from contextlib import closing
from datetime import datetime, date, timedelta

from fastapi import FastAPI, Form, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import plans as P
import content as C

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "policystore.db")
RATES_FILE = os.path.join(BASE, "rates.json")
SITE = os.environ.get("SITE", "https://policystore.com")
SECRET = os.environ.get("SESSION_SECRET") or "policy-store-dev-secret"
CORE_BASE = os.environ.get("CORE_API_BASE", "https://medigap.plus")
CORE_KEY = os.environ.get("CORE_KEY", "")
CORE_SECRET = os.environ.get("CORE_SECRET", "")
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", C.OWNER_EMAIL)
GOD_EMAIL = "jeff.cline@me.com"
TEMP_PASSWORD = "TEMP!234"
DEFAULT_GATE_PASSWORD = "jeffcline"

app = FastAPI(title="Policy Store")
app.add_middleware(SessionMiddleware, secret_key=SECRET, https_only=True,
                   same_site="lax", max_age=60 * 60 * 24 * 30)
os.makedirs(os.path.join(BASE, "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


def e(s):
    return html.escape("" if s is None else str(s), quote=True)


def money(n, cents=True):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    return f"${n:,.2f}" if cents else f"${n:,.0f}"


# ================================================================== data =====
def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, pw TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'customer', first TEXT, last TEXT, phone TEXT,
  state TEXT, dob TEXT, must_change INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);

CREATE TABLE IF NOT EXISTS quotes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE,
  session TEXT, user_id INTEGER,
  first TEXT, last TEXT, email TEXT, phone TEXT,
  state TEXT, age INTEGER, tier TEXT, spouse_age INTEGER, child_ages TEXT,
  product TEXT, benefit INTEGER, deductible INTEGER, ci_benefit INTEGER,
  t365_plan TEXT, term TEXT,
  monthly REAL, annual REAL, demo_rates INTEGER NOT NULL DEFAULT 1,
  target_premium REAL, transcript TEXT, status TEXT NOT NULL DEFAULT 'quoted',
  created REAL NOT NULL);

CREATE TABLE IF NOT EXISTS policies(
  id INTEGER PRIMARY KEY AUTOINCREMENT, quote_id INTEGER, user_id INTEGER,
  policy_no TEXT, status TEXT NOT NULL DEFAULT 'pending',
  free_look_ends TEXT, tpa_ref TEXT, created REAL NOT NULL);

CREATE TABLE IF NOT EXISTS links(
  code TEXT PRIMARY KEY, target TEXT NOT NULL, quote_id INTEGER,
  hits INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, last_hit REAL);

CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, quote_id INTEGER,
  detail TEXT, payload TEXT, ok INTEGER, ts REAL NOT NULL);

CREATE TABLE IF NOT EXISTS calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, caller TEXT, moneyword TEXT, product TEXT,
  source TEXT, state TEXT, disposition TEXT, quote_id INTEGER, ts REAL NOT NULL);

CREATE INDEX IF NOT EXISTS ix_q_created ON quotes(created);
CREATE INDEX IF NOT EXISTS ix_ev_ts ON events(ts);
"""


def init_db():
    with closing(db()) as c:
        c.executescript(SCHEMA)
        c.commit()


def setting(k, default=None):
    with closing(db()) as c:
        r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except Exception:
        return r["v"]


def set_setting(k, v):
    with closing(db()) as c:
        c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=?",
                  (k, json.dumps(v), json.dumps(v)))
        c.commit()


def log(kind, detail="", quote_id=None, payload=None, ok=None):
    with closing(db()) as c:
        c.execute("INSERT INTO events(kind,quote_id,detail,payload,ok,ts) VALUES(?,?,?,?,?,?)",
                  (kind, quote_id, detail, json.dumps(payload) if payload else None,
                   ok, time.time()))
        c.commit()


# ================================================================== auth =====
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return salt.hex() + "$" + dk.hex()


def check_pw(pw, stored):
    try:
        s, d = stored.split("$", 1)
        dk = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(s), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), d)
    except Exception:
        return False


def acct(uid):
    if not uid:
        return None
    with closing(db()) as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None


def me(request: Request):
    return acct(request.session.get("uid"))


def require_admin(request: Request):
    u = me(request)
    if not u or u["role"] != "admin":
        raise HTTPException(307, headers={"Location": "/login?next=/admin"})
    return u


def require_user(request: Request):
    u = me(request)
    if not u:
        raise HTTPException(307, headers={"Location": "/login?next=/account"})
    return u


@app.exception_handler(HTTPException)
async def _redir(request: Request, exc: HTTPException):
    if exc.status_code == 307 and (exc.headers or {}).get("Location"):
        return RedirectResponse(exc.headers["Location"], status_code=303)
    if exc.status_code == 404:
        return HTMLResponse(shell("<section class='wrap pad'><div class='panel center'>"
                                  "<h1>Not found</h1><p class='mut'>That page does not exist.</p>"
                                  "<a class='btn' href='/'>Back to the start</a></div></section>",
                                  me(request)), status_code=404)
    return HTMLResponse(f"<h1>{exc.status_code}</h1><p>{e(exc.detail)}</p>",
                        status_code=exc.status_code)


# ============================================================== demo gate ====
GATE_OPEN_PATHS = ("/static", "/healthz", "/gate", "/favicon.ico")


@app.middleware("http")
async def demo_gate(request: Request, call_next):
    """One password in front of everything until it is switched off in Admin.
    The toggle lives here rather than at the registrar because the registrar
    cannot see this application — see the note on the admin page."""
    path = request.url.path
    if setting("gate_enabled", True) and not path.startswith(GATE_OPEN_PATHS):
        if request.cookies.get("ps_gate") != gate_cookie():
            if request.method == "POST":
                return RedirectResponse("/gate", status_code=303)
            return HTMLResponse(gate_page(), status_code=200)
    return await call_next(request)


def gate_cookie():
    pw = setting("gate_password", DEFAULT_GATE_PASSWORD)
    return hashlib.sha256(f"{SECRET}:{pw}".encode()).hexdigest()[:32]


def gate_page(err=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fully Autonomous Insurance Agency Demo</title>
<meta name="robots" content="noindex,nofollow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
 background:radial-gradient(1200px 600px at 50% -10%,#173a68 0%,#0a1a2f 55%,#06111f 100%);
 font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
 color:#e8f0fa}}
.box{{max-width:520px;width:100%;text-align:center}}
.logo{{font-size:34px;font-weight:800;letter-spacing:-1px;color:#fff;margin-bottom:6px}}
.logo b{{color:#5aa9ff}}
h1{{font-size:clamp(26px,4.6vw,38px);font-weight:800;letter-spacing:-.9px;line-height:1.14;
 margin:22px 0 10px;color:#fff}}
h1 em{{font-style:normal;color:#5aa9ff}}
p.sub{{color:#9dbcdd;font-size:16px;margin-bottom:26px}}
form{{display:flex;gap:10px;background:rgba(255,255,255,.07);padding:9px;border-radius:14px;
 border:1px solid rgba(90,169,255,.3)}}
input{{flex:1;min-width:0;background:transparent;border:0;outline:0;color:#fff;font-size:16px;
 padding:12px 14px;font-family:inherit}}
input::placeholder{{color:#6f8fb3}}
button{{background:linear-gradient(135deg,#2f7fd8,#5aa9ff);color:#fff;border:0;border-radius:10px;
 padding:12px 28px;font-size:16px;font-weight:750;cursor:pointer;font-family:inherit}}
button:hover{{filter:brightness(1.08)}}
.err{{background:rgba(220,80,60,.16);border:1px solid rgba(220,80,60,.45);color:#ffb9ab;
 padding:10px 14px;border-radius:10px;margin-bottom:14px;font-size:14.5px}}
.foot{{margin-top:26px;color:#5d7b9c;font-size:12.5px;line-height:1.6}}
.foot a{{color:#7fb4e8}}
</style></head><body>
<div class="box">
  <div class="logo">Policy<b>Store</b></div>
  <h1>Full Autonomous <em>Insurance Agency</em> Demo</h1>
  <p class="sub">Please enter the password below and then hit the Go button.</p>
  {f'<div class="err">{e(err)}</div>' if err else ''}
  <form method="post" action="/gate">
    <input type="password" name="pw" placeholder="Password" autofocus autocomplete="off"
      aria-label="Demo password">
    <button type="submit">Go</button>
  </form>
  <div class="foot">Private demonstration. Nothing here is an offer of insurance.<br>
  Jeff Cline · {e(C.PHONE)} · <a href="mailto:{e(OWNER_EMAIL)}">{e(OWNER_EMAIL)}</a></div>
</div></body></html>"""


@app.get("/gate", response_class=HTMLResponse)
def gate_get():
    return HTMLResponse(gate_page())


@app.post("/gate")
def gate_post(pw: str = Form("")):
    if pw.strip() == str(setting("gate_password", DEFAULT_GATE_PASSWORD)):
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("ps_gate", gate_cookie(), max_age=60 * 60 * 24 * 30,
                     httponly=True, samesite="lax", secure=True)
        log("gate_pass", "demo gate opened")
        return r
    log("gate_fail", "bad demo password")
    return HTMLResponse(gate_page("That password is not right. Try again."), status_code=401)


# ========================================================== rating engine ====
DEMO_RATES = {
    "_note": ("DEMO RATES. The workbook supplied benefit amounts, tiers and age bands but no "
              "premium rates for AD&D, AME or Critical Illness. These values exist so the flow "
              "is testable end to end. Replace them in Admin → Rates with the carrier sheet."),
    "_demo": True,
    # monthly premium per $1,000 of benefit, by age band
    "add": {"18-24": .038, "25-34": .042, "35-44": .055, "45-54": .078, "55-64": .118,
            "65-74": .195, "75+": .320},
    # monthly premium per $1,000 of benefit, by age band
    "ame": {"18-24": .72, "25-29": .76, "30-34": .81, "35-39": .88, "40-44": .97,
            "45-49": 1.09, "50-54": 1.24, "55-59": 1.43, "60-64": 1.67, "65-69": 1.98,
            "70-74": 2.34, "75-79": 2.79, "80-84": 3.32, "85+": 3.95},
    # monthly premium per $1,000 of benefit, by age band
    "ci": {"18-24": .34, "25-29": .41, "30-34": .52, "35-39": .71, "40-44": 1.02,
           "45-49": 1.48, "50-54": 2.11, "55-59": 2.92, "60-64": 3.96},
    # multiplier applied to the AME rate for the chosen deductible
    "ame_deductible_factor": {"0": 1.00, "25": .96, "50": .93, "100": .88, "150": .85,
                              "200": .82, "250": .79, "300": .77, "400": .73, "500": .70,
                              "1000": .62},
    # spouse is rated on their own age; children are a flat load on the base
    "child_load": {"1": .18, "2": .28, "3": .34, "4": .38},
    "policy_fee_monthly": 2.00,
}


def rates():
    try:
        with open(RATES_FILE) as f:
            r = json.load(f)
            if r:
                return r
    except Exception:
        pass
    return DEMO_RATES


def rates_are_demo():
    return bool(rates().get("_demo", True))


def _rate_for(product, age, benefit, deductible=None):
    """Monthly premium for one insured life on one product."""
    r = rates()
    band = P.band_for(product, age)
    if not band:
        return None
    per_k = (r.get(product) or {}).get(band)
    if per_k is None:
        return None
    prem = float(per_k) * (float(benefit) / 1000.0)
    if product == "ame" and deductible is not None:
        f = (r.get("ame_deductible_factor") or {}).get(str(int(deductible)), 1.0)
        prem *= float(f)
    return prem


def quote_premium(products, state, age, benefit, deductible=0, ci_benefit=0,
                  spouse_age=None, children=0):
    """Rate a selection. Returns (monthly, breakdown, problems)."""
    r = rates()
    total, lines, problems = 0.0, [], []
    for prod in products:
        if prod not in P.state_products(state):
            problems.append(f"{P.PRODUCTS[prod]['short']} is not available in {state}.")
            continue
        amt = ci_benefit if prod == "ci" else benefit
        if prod == "ci" and not amt:
            amt = P.PRODUCTS["ci"]["benefits"][3]
        base = _rate_for(prod, age, amt, deductible if prod == "ame" else None)
        if base is None:
            problems.append(f"{P.PRODUCTS[prod]['short']} has no filed rate at age {age}.")
            continue
        lines.append((f"{P.PRODUCTS[prod]['short']} · {money(amt, False)} · you", base))
        total += base
        if spouse_age:
            sp = _rate_for(prod, spouse_age, amt, deductible if prod == "ame" else None)
            if sp is None:
                problems.append(f"{P.PRODUCTS[prod]['short']} has no filed rate at age "
                                f"{spouse_age} for your spouse.")
            else:
                lines.append((f"{P.PRODUCTS[prod]['short']} · {money(amt, False)} · spouse", sp))
                total += sp
        if children:
            load = float((r.get("child_load") or {}).get(str(min(int(children), 4)), 0))
            kid = base * load
            lines.append((f"{P.PRODUCTS[prod]['short']} · {children} "
                          f"child{'ren' if int(children) != 1 else ''}", kid))
            total += kid
    if lines:
        fee = float(r.get("policy_fee_monthly", 0) or 0)
        if fee:
            lines.append(("Policy fee", fee))
            total += fee
    return round(total, 2), lines, problems


def t365_quote(state, term="monthly"):
    tier = P.t365_tier(state)
    if not tier:
        return None
    out = []
    for key, name, colour in P.T365_PLANS:
        r = P.T365_RATES[tier][key]
        out.append({"key": key, "name": name, "colour": colour, "tier": tier,
                    "yearly": r["yearly"], "monthly": r["monthly"], "biweekly": r["biweekly"],
                    "price": r.get(term, r["monthly"])})
    return out


def best_fit(products, state, age, target, spouse_age=None, children=0):
    """Walk the filed benefit amounts and return the largest that lands at or
    under the customer's stated monthly budget — the number they asked for is
    the constraint, not an afterthought."""
    prod_list = [p for p in products if p in P.state_products(state)]
    if not prod_list:
        return None
    grid = P.PRODUCTS[prod_list[0]]["benefits"]
    best = None
    for amt in grid:
        ci_amt = 0
        if "ci" in prod_list:
            ci_amt = max([b for b in P.PRODUCTS["ci"]["benefits"] if b <= max(amt, 2500)]
                         or [P.PRODUCTS["ci"]["benefits"][0]])
        m, lines, probs = quote_premium(prod_list, state, age, amt, 100, ci_amt,
                                        spouse_age, children)
        if probs or not lines:
            continue
        if target and m > float(target):
            break
        best = {"benefit": amt, "ci_benefit": ci_amt, "monthly": m, "lines": lines}
    if best is None:                       # even the smallest exceeds the budget
        amt = grid[0]
        ci_amt = P.PRODUCTS["ci"]["benefits"][0] if "ci" in prod_list else 0
        m, lines, probs = quote_premium(prod_list, state, age, amt, 100, ci_amt,
                                        spouse_age, children)
        if lines:
            best = {"benefit": amt, "ci_benefit": ci_amt, "monthly": m, "lines": lines,
                    "over_budget": True}
    return best


# ================================================= outbound: core, sms, ping ==
def _post(url, payload, headers=None, timeout=15):
    cmd = ["curl", "-sS", "-w", "\n%{http_code}", "--max-time", str(timeout), "-X", "POST",
           "-H", "content-type: application/json"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    cmd += ["-d", json.dumps(payload), url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        body, _, code = (p.stdout or "").rpartition("\n")
        return int(code or 0), body
    except Exception as ex:
        return 0, str(ex)


def core_post(path, payload, timeout=15):
    if not (CORE_KEY and CORE_SECRET):
        return False
    code, _ = _post(f"{CORE_BASE}{path}", payload,
                    {"x-core-key": CORE_KEY, "x-core-secret": CORE_SECRET}, timeout)
    return 200 <= code < 300


def send_email(to, subject, html_body, tries=4):
    for i in range(tries):
        if core_post("/api/core/email",
                     {"to": to, "subject": subject, "html": html_body, "provider": "zapmail"}):
            return True
        time.sleep(min(2 ** i, 6))
    return False


def send_sms(to, body, quote_id=None):
    """SMS goes out through whichever provider is configured in Integrations. If
    nothing is configured we record exactly what would have been sent, so the
    flow is demonstrable without a live account."""
    cfg = setting("sms", {}) or {}
    provider = cfg.get("provider", "")
    if provider == "core":
        ok = core_post("/api/core/sms", {"to": to, "message": body})
        log("sms", f"core → {to}", quote_id, {"to": to, "body": body}, ok)
        return ok
    if provider == "webhook" and cfg.get("url"):
        code, resp = _post(cfg["url"], {"to": to, "message": body},
                           json.loads(cfg.get("headers") or "{}") if cfg.get("headers") else None)
        ok = 200 <= code < 300
        log("sms", f"webhook {code} → {to}", quote_id, {"to": to, "body": body, "resp": resp[:400]}, ok)
        return ok
    log("sms", f"SIMULATED → {to} (no provider configured)", quote_id,
        {"to": to, "body": body}, None)
    return None


def ping_post(quote, kind="post"):
    """Ping-post to the buyer/TPA endpoint. Field names are remapped through the
    mapping saved in Integrations, so a new buyer spec is a settings change
    rather than a code change."""
    cfg = setting("pingpost", {}) or {}
    url = cfg.get("ping_url") if kind == "ping" else cfg.get("post_url")
    payload = {
        "lead_id": quote["token"], "type": kind,
        "first_name": quote["first"], "last_name": quote["last"],
        "email": quote["email"], "phone": quote["phone"],
        "state": quote["state"], "age": quote["age"],
        "product": quote["product"], "benefit": quote["benefit"],
        "deductible": quote["deductible"], "tier": quote["tier"],
        "monthly_premium": quote["monthly"], "annual_premium": quote["annual"],
        "target_premium": quote["target_premium"],
        "rates_are_demo": bool(quote["demo_rates"]),
        "source": "policystore.com", "created": quote["created"],
    }
    mapping = cfg.get("mapping") or {}
    if mapping:
        payload = {mapping.get(k, k): v for k, v in payload.items()}
    for k, v in (cfg.get("static") or {}).items():
        payload[k] = v
    if not url:
        log("pingpost", f"SIMULATED {kind} (no endpoint configured)", quote["id"], payload, None)
        return None, payload
    headers = {}
    try:
        headers = json.loads(cfg.get("headers") or "{}")
    except Exception:
        pass
    code, body = _post(url, payload, headers)
    ok = 200 <= code < 300
    log("pingpost", f"{kind} → {url} → HTTP {code}", quote["id"],
        {"sent": payload, "response": body[:600]}, ok)
    return ok, payload


def tpa_submit(quote, policy_no):
    """Hand the enrolment to the third-party administrator. Same pattern: real
    call if configured, recorded simulation if not."""
    cfg = setting("tpa", {}) or {}
    url = cfg.get("enroll_url")
    payload = {"policy_number": policy_no, "quote_ref": quote["token"],
               "applicant": {"first": quote["first"], "last": quote["last"],
                             "email": quote["email"], "phone": quote["phone"],
                             "state": quote["state"], "age": quote["age"]},
               "coverage": {"product": quote["product"], "benefit": quote["benefit"],
                            "deductible": quote["deductible"], "tier": quote["tier"]},
               "premium": {"monthly": quote["monthly"], "annual": quote["annual"]},
               "free_look_days": 30}
    if not url:
        log("tpa", "SIMULATED enrolment (no endpoint configured)", quote["id"], payload, None)
        return None
    headers = {}
    try:
        headers = json.loads(cfg.get("headers") or "{}")
    except Exception:
        pass
    code, body = _post(url, payload, headers)
    ok = 200 <= code < 300
    log("tpa", f"enrol → HTTP {code}", quote["id"], {"sent": payload, "response": body[:600]}, ok)
    return ok


# ============================================================== shortener ====
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"


def short_link(target, quote_id=None):
    with closing(db()) as c:
        for _ in range(12):
            code = "".join(secrets.choice(ALPHABET) for _ in range(5))
            if not c.execute("SELECT 1 FROM links WHERE code=?", (code,)).fetchone():
                c.execute("INSERT INTO links(code,target,quote_id,created) VALUES(?,?,?,?)",
                          (code, target, quote_id, time.time()))
                c.commit()
                return code
    return None


@app.get("/s/{code}")
def follow(code: str):
    with closing(db()) as c:
        r = c.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
        if not r:
            raise HTTPException(404, "Unknown link")
        c.execute("UPDATE links SET hits=hits+1,last_hit=? WHERE code=?", (time.time(), code))
        c.commit()
    log("link_click", f"/s/{code}", r["quote_id"])
    return RedirectResponse(r["target"], status_code=302)


# ================================================================= chrome ====
CSS = """
:root{--navy:#0b1f38;--navy2:#123a63;--blue:#2f7fd8;--sky:#5aa9ff;--ink:#16202e;
 --mut:#5b6b80;--soft:#8496ab;--line:#dde5ef;--line2:#c6d4e4;--bg:#f5f8fc;--card:#fff;
 --ok:#17924f;--amber:#e09b12;--red:#cf4b34;
 --sh:0 1px 2px rgba(11,31,56,.05),0 8px 24px rgba(11,31,56,.07);
 --sh2:0 4px 12px rgba(11,31,56,.09),0 20px 48px rgba(11,31,56,.14);--rad:14px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:16px/1.6 ui-sans-serif,-apple-system,
 "Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
img{max-width:100%;display:block}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
h1,h2,h3,h4{line-height:1.16;letter-spacing:-.02em;color:var(--navy)}
h1{font-size:clamp(29px,4.3vw,48px);font-weight:800}
h2{font-size:clamp(23px,3vw,34px);font-weight:800}
h3{font-size:19px;font-weight:800}
p{margin:0 0 14px}
.wrap{max-width:1160px;margin:0 auto;padding:0 22px}
.narrow{max-width:760px;margin:0 auto}
.pad{padding:54px 0}.pad-s{padding:32px 0}
.lead{font-size:clamp(17px,1.7vw,20px);color:var(--mut);line-height:1.6}
.mut{color:var(--mut)}.small{font-size:13.5px}.center{text-align:center}
.kicker{font-size:11.5px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;
 color:var(--blue)}
.navy-bg{background:linear-gradient(150deg,#06152a,var(--navy2) 55%,#1f5490);color:#dce9f7}
.navy-bg h1,.navy-bg h2,.navy-bg h3{color:#fff}
.navy-bg .lead,.navy-bg .mut{color:#a9c8e8}

.btn{display:inline-flex;align-items:center;justify-content:center;gap:9px;white-space:nowrap;
 background:linear-gradient(135deg,var(--blue),var(--sky));color:#fff;font-weight:750;
 padding:12px 24px;border-radius:10px;border:0;cursor:pointer;font-size:15.5px;
 font-family:inherit;box-shadow:0 2px 10px rgba(47,127,216,.28);transition:.13s}
.btn:hover{text-decoration:none;transform:translateY(-1px);box-shadow:0 6px 18px rgba(47,127,216,.36)}
.btn.ghost{background:transparent;color:var(--navy);border:1.5px solid var(--line2);box-shadow:none}
.btn.ghost:hover{border-color:var(--blue);color:var(--blue);box-shadow:none}
.btn.onnavy{background:rgba(255,255,255,.13);border:1.5px solid rgba(255,255,255,.38);
 color:#fff;box-shadow:none}
.btn.green{background:linear-gradient(135deg,#14804a,#1aa85f);box-shadow:0 2px 10px rgba(20,128,74,.3)}
.btn.lg{padding:15px 32px;font-size:17px}.btn.sm{padding:8px 15px;font-size:13.5px}
.btn.block{width:100%}

header.nav{position:sticky;top:0;z-index:60;background:rgba(255,255,255,.94);
 backdrop-filter:saturate(1.6) blur(12px);border-bottom:1px solid var(--line)}
header.nav .in{display:flex;align-items:center;gap:14px;height:62px}
.brand{font-weight:850;font-size:21px;color:var(--navy);letter-spacing:-.6px;white-space:nowrap}
.brand b{color:var(--blue)}
nav.links{display:flex;gap:2px;margin-left:auto}
nav.links a{color:var(--navy);font-weight:600;font-size:14.5px;padding:8px 11px;border-radius:8px;
 white-space:nowrap}
nav.links a:hover{background:#eaf2fb;text-decoration:none;color:var(--blue)}
.navright{display:flex;gap:8px;align-items:center}
@media(max-width:980px){nav.links a.opt{display:none}}
@media(max-width:720px){nav.links{display:none}}

.grid{display:grid;gap:20px}
.g2{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:repeat(3,1fr)}
.g4{grid-template-columns:repeat(4,1fr)}
@media(max-width:980px){.g3,.g4{grid-template-columns:repeat(2,1fr)}}
@media(max-width:640px){.g2,.g3,.g4{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--rad);
 padding:22px;box-shadow:var(--sh);display:flex;flex-direction:column}
a.card:hover{text-decoration:none;transform:translateY(-2px);box-shadow:var(--sh2)}
.card .ic{font-size:30px;margin-bottom:10px}
.card h3{margin-bottom:6px}
.card p{font-size:14.6px;color:var(--mut);margin-bottom:10px}
.card .foot{margin-top:auto;padding-top:10px;display:flex;justify-content:space-between;
 align-items:center;font-size:13.5px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--rad);
 padding:26px;box-shadow:var(--sh)}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
 box-shadow:var(--sh)}
.stat .n{font-size:26px;font-weight:850;color:var(--navy);letter-spacing:-.02em;line-height:1.1}
.stat .l{font-size:12.5px;color:var(--soft);margin-top:3px}

label{display:block;font-size:13px;font-weight:700;color:var(--navy);margin-bottom:5px}
input[type=text],input[type=email],input[type=password],input[type=tel],input[type=number],
input[type=url],select,textarea{width:100%;border:1.5px solid var(--line2);border-radius:10px;
 padding:12px 13px;font-size:16px;font-family:inherit;color:var(--ink);background:#fff;outline:0}
input:focus,select:focus,textarea:focus{border-color:var(--blue);
 box-shadow:0 0 0 4px rgba(47,127,216,.14)}
textarea{min-height:104px;resize:vertical;font-size:14px;line-height:1.5}
.fr{display:grid;gap:14px;margin-bottom:14px}
.fr.two{grid-template-columns:1fr 1fr}.fr.three{grid-template-columns:1fr 1fr 1fr}
@media(max-width:620px){.fr.two,.fr.three{grid-template-columns:1fr}}
.hint{font-size:12.5px;color:var(--soft);margin-top:5px}
.err{background:#fdeeea;border:1px solid #f6c9bd;color:#a33f22;padding:11px 14px;
 border-radius:10px;margin-bottom:16px;font-size:14.5px}
.okmsg{background:#e9f7f0;border:1px solid #b6e3cd;color:#0f6b46;padding:11px 14px;
 border-radius:10px;margin-bottom:16px;font-size:14.5px}
.warn{background:#fff6e5;border:1px solid #f3dcae;color:#8a5d08;padding:11px 14px;
 border-radius:10px;margin-bottom:16px;font-size:14.5px}

table.data{width:100%;border-collapse:collapse;font-size:14px}
table.data th{text-align:left;font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;
 color:var(--soft);padding:0 12px 9px 0;border-bottom:1px solid var(--line);font-weight:800}
table.data td{padding:10px 12px 10px 0;border-bottom:1px solid #eef3f8;vertical-align:top}
.tablewrap{overflow-x:auto}
.pill{display:inline-block;background:#fff;border:1.5px solid var(--line2);color:var(--navy);
 padding:6px 13px;border-radius:20px;font-size:13.5px;font-weight:650;margin:0 6px 7px 0}
a.pill:hover{border-color:var(--blue);color:var(--blue);text-decoration:none}
.tag{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:750;
 padding:3px 9px;border-radius:20px}
.tag.ok{background:#e4f5eb;color:var(--ok)}.tag.warn{background:#fdf1dc;color:var(--amber)}
.tag.off{background:#eef2f6;color:var(--soft)}.tag.red{background:#fceae6;color:var(--red)}

/* ---------------- conversation ---------------- */
.chat{max-width:720px;margin:0 auto}
.msg{display:flex;gap:12px;margin-bottom:18px;align-items:flex-start}
.av{flex:0 0 40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--navy),var(--blue));
 color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:800}
.bubble{background:#fff;border:1px solid var(--line);border-radius:4px 15px 15px 15px;
 padding:15px 18px;box-shadow:var(--sh);flex:1}
.bubble p:last-child{margin-bottom:0}
.msg.you{flex-direction:row-reverse}
.msg.you .av{background:#e6edf5;color:var(--navy)}
.msg.you .bubble{background:#eaf2fb;border-color:#cfe0f2;border-radius:15px 4px 15px 15px}
.ask{background:#fff;border:1px solid var(--line);border-radius:var(--rad);padding:22px;
 box-shadow:var(--sh2);margin-top:6px}
.opts{display:flex;flex-wrap:wrap;gap:9px;margin-top:6px}
.opts button,.opts .o{background:#fff;border:1.5px solid var(--line2);color:var(--navy);
 padding:11px 17px;border-radius:10px;font-size:15px;font-weight:650;cursor:pointer;
 font-family:inherit}
.opts button:hover{border-color:var(--blue);color:var(--blue);background:#f4f9ff}
.progress{height:4px;background:#e3ebf4;border-radius:4px;overflow:hidden;margin-bottom:22px}
.progress i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--sky))}

/* ---------------- quote ---------------- */
.qbox{background:linear-gradient(150deg,#06152a,var(--navy2) 60%,#1f5490);color:#fff;
 border-radius:var(--rad);padding:26px;box-shadow:var(--sh2)}
.qbox .amt{font-size:46px;font-weight:850;letter-spacing:-1.6px;line-height:1;color:#fff}
.qbox .per{font-size:15px;color:#9dc3ea}
.qline{display:flex;justify-content:space-between;gap:14px;padding:8px 0;
 border-bottom:1px solid rgba(255,255,255,.14);font-size:14.5px;color:#c8dcf1}
.qline:last-child{border-bottom:0}.qline b{color:#fff}
.demo-flag{background:#fff6e5;border:1px solid #f3dcae;color:#8a5d08;padding:9px 13px;
 border-radius:9px;font-size:12.8px;margin-bottom:14px;line-height:1.45}

.sms{max-width:300px;margin:0 auto;background:#0b1f38;border:3px solid #2c4666;
 border-radius:26px;padding:16px 13px 20px}
.sms .notch{width:70px;height:5px;background:#2c4666;border-radius:4px;margin:0 auto 14px}
.bub{background:var(--blue);color:#fff;border-radius:14px 14px 14px 4px;padding:11px 14px;
 font-size:13.5px;line-height:1.45;margin-bottom:9px}
.bub .who{font-size:10px;letter-spacing:1.3px;text-transform:uppercase;opacity:.8;margin-bottom:3px}
.bub a{color:#cfe6ff;text-decoration:underline}

footer{background:linear-gradient(165deg,#06152a,#0d2c4d);color:#93b3d4;margin-top:56px;
 padding:44px 0 24px;font-size:14px}
footer h4{color:#fff;font-size:12.5px;letter-spacing:.11em;text-transform:uppercase;
 margin-bottom:12px}
footer a{color:#93b3d4;display:block;padding:3px 0}
footer a:hover{color:var(--sky);text-decoration:none}
.fgrid{display:grid;grid-template-columns:1.5fr repeat(3,1fr);gap:26px}
@media(max-width:860px){.fgrid{grid-template-columns:1fr 1fr}}
@media(max-width:520px){.fgrid{grid-template-columns:1fr}}
.legal{margin-top:26px;padding-top:18px;border-top:1px solid rgba(255,255,255,.11);
 font-size:11.5px;color:#5f7d9d;line-height:1.6}

.dash{display:grid;grid-template-columns:220px 1fr;gap:24px;align-items:start}
@media(max-width:900px){.dash{grid-template-columns:1fr}}
.side{background:#fff;border:1px solid var(--line);border-radius:var(--rad);padding:14px;
 box-shadow:var(--sh);position:sticky;top:78px}
@media(max-width:900px){.side{position:static}}
.side a{display:block;padding:9px 11px;border-radius:9px;color:var(--navy);font-weight:640;
 font-size:14.3px}
.side a:hover{background:#eef4fb;text-decoration:none}
.side a.on{background:linear-gradient(135deg,var(--blue),var(--sky));color:#fff}
code{background:#eef3f8;padding:2px 6px;border-radius:5px;font-size:13px;
 font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:#0b1f38;color:#cfe4ff;padding:14px;border-radius:10px;overflow-x:auto;
 font-size:12.5px;line-height:1.5}
"""


def nav_links(u):
    out = ('<a href="/quote">Get a quote</a>'
           '<a class="opt" href="/products/add">AD&amp;D</a>'
           '<a class="opt" href="/products/ame">Accident Medical</a>'
           '<a class="opt" href="/products/ci">Critical Illness</a>'
           '<a href="/products/t365">Travel 365</a>')
    if u:
        out += '<a href="/account">My account</a>'
        if u["role"] == "admin":
            out += '<a href="/admin">Admin</a>'
    return out


def shell(body, user=None, title=None, desc=None, canon="/"):
    title = title or f"{C.BRAND} — {C.TAGLINE}"
    right = ('<a class="btn ghost sm" href="/login">Log in</a>'
             '<a class="btn sm" href="/quote">Get a quote</a>') if not user else \
            (f'<a class="btn ghost sm" href="/account">{e(user["first"] or "Account")}</a>'
             '<a class="btn sm" href="/logout">Sign out</a>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="description" content="{e(desc or C.HERO['sub'])}">
<meta name="robots" content="noindex,nofollow">
<link rel="canonical" href="{SITE}{e(canon)}">
<style>{CSS}</style></head><body>
<header class="nav"><div class="wrap in">
<a class="brand" href="/">Policy<b>Store</b></a>
<nav class="links">{nav_links(user)}</nav>
<div class="navright">{right}</div>
</div></header>
{body}
<footer><div class="wrap">
<div class="fgrid">
<div><div style="font-size:22px;font-weight:850;color:#fff;letter-spacing:-.6px">
Policy<span style="color:var(--sky)">Store</span></div>
<p style="margin-top:8px;max-width:32ch">{e(C.TAGLINE)}</p>
<p style="color:var(--sky);font-weight:700;margin-top:12px">{e(C.PHONE)}</p></div>
<div><h4>Products</h4>
<a href="/products/add">Accidental Death &amp; Dismemberment</a>
<a href="/products/ame">Accident Medical Expense</a>
<a href="/products/ci">Critical Illness</a>
<a href="/products/t365">Travel 365</a></div>
<div><h4>Get covered</h4>
<a href="/quote">Talk to the agent</a>
<a href="/coverage">Where we're licensed</a>
<a href="/free-look">30-day free look</a>
<a href="/account">Manage my policy</a></div>
<div><h4>Company</h4>
<a href="/how-it-works">How it works</a>
<a href="/login">Log in</a>
<a href="tel:{e(C.PHONE)}">{e(C.PHONE)}</a></div>
</div>
<div class="legal">{e(C.COMPLIANCE)}<br><br>
&copy; {time.strftime('%Y')} Policy Store. Carrier: {e(P.CARRIER)}. Underwritten by
{e(P.UNDERWRITER)}.</div>
</div></footer>
</body></html>"""


def demo_banner():
    if not rates_are_demo():
        return ""
    return ('<div class="demo-flag"><b>Demo rates.</b> AD&amp;D, Accident Medical and Critical '
            'Illness premiums below come from a placeholder table — the workbook supplied '
            'benefit amounts, tiers and age bands but no rates. Travel 365 pricing is real. '
            'Load the carrier sheet in Admin → Rates and every quote switches over.</div>')


# =============================================================== landing =====
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    u = me(request)
    cards = ""
    for code in ("add", "ame", "ci", "t365"):
        p = C.PRODUCTS[code]
        cards += f"""<a class="card" href="/products/{code}">
<div class="ic">{p['icon']}</div><h3>{e(p['name'])}</h3>
<p>{e(p['tag'])}</p>
<div class="foot"><span class="mut">Read the case</span><span>→</span></div></a>"""
    why = "".join(f"""<div class="card"><div class="ic">{i}</div><h3>{e(t)}</h3>
<p>{e(b)}</p></div>""" for i, t, b in C.WHY_AUTONOMOUS)
    bundles = "".join(f"""<div class="card"><h3>{e(n)}</h3><p>{e(d)}</p></div>"""
                      for _, n, d in C.BUNDLES)
    live = ", ".join(sorted(P.LIVE))
    return HTMLResponse(shell(f"""
<section class="navy-bg"><div class="wrap pad">
<div class="kicker" style="color:var(--sky)">{e(C.HERO['kicker'])}</div>
<h1 style="margin:12px 0 14px;max-width:19ch">{e(C.HERO['h1'])}</h1>
<p class="lead" style="max-width:64ch">{e(C.HERO['sub'])}</p>
<p style="margin-top:26px"><a class="btn lg" href="/quote">Talk to the agent</a>
<a class="btn onnavy lg" href="/how-it-works">See how it works</a></p>
<div class="grid g4" style="margin-top:34px">
<div class="stat" style="background:rgba(255,255,255,.07);border-color:rgba(90,169,255,.28)">
<div class="n" style="color:#fff">24/7/365</div>
<div class="l" style="color:#8fb6dc">Always answered, never a queue</div></div>
<div class="stat" style="background:rgba(255,255,255,.07);border-color:rgba(90,169,255,.28)">
<div class="n" style="color:#fff">3</div>
<div class="l" style="color:#8fb6dc">Questions between hello and a real quote</div></div>
<div class="stat" style="background:rgba(255,255,255,.07);border-color:rgba(90,169,255,.28)">
<div class="n" style="color:#fff">30 days</div>
<div class="l" style="color:#8fb6dc">Free look on every policy</div></div>
<div class="stat" style="background:rgba(255,255,255,.07);border-color:rgba(90,169,255,.28)">
<div class="n" style="color:#fff">{len(P.LIVE)}</div>
<div class="l" style="color:#8fb6dc">States writing today</div></div>
</div></div></section>

<section class="wrap pad">
<div class="kicker">The products</div>
<h2 style="margin:6px 0 8px">Four ways to cover what your health plan hands back to you.</h2>
<p class="lead" style="max-width:66ch;margin-bottom:24px">Written by {e(P.CARRIER)}. Quoted
from the carrier's own rate sheet, in the states where each product is actually filed.</p>
<div class="grid g4">{cards}</div></section>

<section style="background:#fff;border-top:1px solid var(--line);border-bottom:1px solid var(--line)">
<div class="wrap pad">
<div class="kicker">Bought together</div>
<h2 style="margin:6px 0 20px">The combinations that actually make sense.</h2>
<div class="grid g3">{bundles}</div>
<p class="small mut" style="margin-top:14px">These six combinations are what the carrier
files. There is no all-three bundle, so the agent will not offer you one.</p>
</div></section>

<section class="wrap pad">
<div class="kicker">Why autonomous</div>
<h2 style="margin:6px 0 20px">An agency that does not sleep, forget, or have a bad day.</h2>
<div class="grid g3">{why}</div></section>

<section class="navy-bg"><div class="wrap pad center">
<h2>Ready when you are.</h2>
<p class="lead" style="max-width:54ch;margin:10px auto 22px">Three questions, a real quote, and
a link to your phone. If you would rather talk to a person, call {e(C.PHONE)}.</p>
<a class="btn lg" href="/quote">Get my quote</a></div></section>

<section class="wrap pad-s"><p class="small mut center">Currently writing in: {e(live)}.
<a href="/coverage">See the full availability map</a>.</p></section>
""", u, canon="/"))


@app.get("/products/{code}", response_class=HTMLResponse)
def product_page(request: Request, code: str):
    p = C.PRODUCTS.get(code)
    if not p:
        raise HTTPException(404, "No such product")
    why = "".join(f"""<div style="border-left:3px solid var(--blue);padding-left:16px;
margin-bottom:20px"><h3>{e(t)}</h3><p class="mut" style="margin:4px 0 0">{e(b)}</p></div>"""
                  for t, b in p["why"])
    who = "".join(f"<li style='margin-bottom:7px'>{e(x)}</li>" for x in p["who"])
    faq = "".join(f"""<details style="background:#fff;border:1px solid var(--line);
border-radius:11px;padding:14px 18px;margin-bottom:10px;box-shadow:var(--sh)">
<summary style="font-weight:750;color:var(--navy);cursor:pointer;font-size:16px">{e(q)}</summary>
<p class="mut" style="margin:10px 0 0;font-size:15px">{e(a)}</p></details>""" for q, a in p["faq"])
    if code == "t365":
        detail = f"""<div class="panel"><h3>What it costs</h3>
<p class="mut">Real published rates, per person, per year — the figure varies slightly by your
state of residence.</p>
<div class="tablewrap"><table class="data"><tr><th>Plan</th><th>Yearly</th><th>Monthly</th>
<th>Bi-weekly</th></tr>
{"".join(f'<tr><td><b>{e(n)}</b></td><td>{money(P.T365_RATES[2][k]["yearly"])}</td>'
         f'<td>{money(P.T365_RATES[2][k]["monthly"])}</td>'
         f'<td>{money(P.T365_RATES[2][k]["biweekly"])}</td></tr>'
         for k, n, _ in P.T365_PLANS)}
</table></div>
<p class="hint">Shown at the most common state tier. Your exact rate is confirmed in the quote.
{" ".join(P.T365_NOTES)}</p></div>"""
    else:
        pl = P.PRODUCTS[code]
        detail = f"""<div class="panel"><h3>Benefit amounts you can choose</h3>
<p class="mut">Filed amounts, straight from the carrier's plan options.</p>
<p style="margin-top:10px">{"".join(f'<span class="pill">{money(b, False)}</span>' for b in pl["benefits"])}</p>
{f'<h3 style="margin-top:18px">Deductible options</h3><p style="margin-top:8px">' + "".join(f'<span class="pill">{money(d, False)}</span>' for d in pl["deductibles"]) + '</p>' if pl.get("deductibles") else ''}
<h3 style="margin-top:18px">How it is rated</h3>
<p class="mut">By age band and state. The bands for this product are
{", ".join(pl["bands"])}. Florida is filed unbanded — one rate for all ages.</p>
<h3 style="margin-top:18px">Who you can cover</h3>
<p class="mut">Yourself, your spouse, your children, or the whole household. Because rates are
age-banded, the agent asks each adult's age before it quotes.</p></div>"""
    return HTMLResponse(shell(f"""
<section class="navy-bg"><div class="wrap pad">
<div class="kicker" style="color:var(--sky)">{p['icon']} {e(p['short'])}</div>
<h1 style="margin:10px 0 12px">{e(p['tag'])}</h1>
<p class="lead" style="max-width:66ch">{e(p['lede'])}</p>
<p style="margin-top:24px"><a class="btn lg" href="/quote?want={code}">Quote this</a>
<a class="btn onnavy lg" href="/quote">Not sure — help me choose</a></p>
</div></section>
<section class="wrap pad"><div class="grid g2" style="gap:36px;align-items:start">
<div><h2 style="margin-bottom:20px">Why people buy it</h2>{why}
<h3 style="margin-top:26px">Who it tends to suit</h3>
<ul class="mut" style="margin:10px 0 0 20px">{who}</ul></div>
<div>{detail}
<div class="panel" style="margin-top:18px;background:#eef7f1;border-color:#b6e3cd">
<h3 style="color:var(--ok)">↩︎ 30-day free look</h3>
<p class="mut" style="margin:6px 0 0;font-size:14.5px">{e(C.FREE_LOOK)}</p></div>
</div></div></section>
<section class="wrap pad-s"><div class="narrow"><h2 style="margin-bottom:16px">Questions</h2>
{faq}</div></section>
<section class="navy-bg"><div class="wrap pad center">
<h2>Get a real number in about a minute.</h2>
<p class="lead" style="margin:10px auto 20px;max-width:50ch">Three questions and the agent
quotes you from the rate sheet.</p>
<a class="btn lg" href="/quote?want={code}">Quote {e(p['short'])}</a></div></section>
""", me(request), title=f"{p['name']} — Policy Store", desc=p["lede"],
        canon=f"/products/{code}"))


@app.get("/how-it-works", response_class=HTMLResponse)
def how_it_works(request: Request):
    steps = [
        ("1", "You call, or you start here", "The agent answers on the first ring at any hour."),
        ("2", "Three questions", "Your age, your state, and what you want to spend a month."),
        ("3", "The rate sheet does the work", "Filed rates only. The agent never invents a price."),
        ("4", "A real quote, spoken back", "Coverage and premium, in the same conversation."),
        ("5", "Questions or enroll?", "Questions loop back. Ready moves forward."),
        ("6", "A text with a short link", "Lands on your phone while you are still on the line."),
        ("7", "The agent waits", "No transfer, no callback. It stays with you."),
        ("8", "Payment to the administrator", "Card details never touch the call."),
        ("9", "Acceptance posts back", "The policy issues and documents go out."),
        ("10", "Thank you — and then?", "The agent asks what else it can help with."),
    ]
    body = "".join(f"""<div style="display:flex;gap:16px;margin-bottom:18px;align-items:flex-start">
<div style="flex:0 0 42px;height:42px;border-radius:50%;background:linear-gradient(135deg,
var(--navy),var(--blue));color:#fff;display:flex;align-items:center;justify-content:center;
font-weight:800">{n}</div>
<div class="card" style="flex:1;padding:16px 20px"><h3>{e(t)}</h3>
<p style="margin:2px 0 0">{e(d)}</p></div></div>""" for n, t, d in steps)
    return HTMLResponse(shell(f"""
<section class="navy-bg"><div class="wrap pad">
<div class="kicker" style="color:var(--sky)">How it works</div>
<h1 style="margin:10px 0 12px">One conversation, start to covered.</h1>
<p class="lead" style="max-width:62ch">No hold music, no callback, no "an agent will reach out."
The whole thing happens while you are still on the line.</p></div></section>
<section class="wrap pad"><div class="narrow">{body}
<div class="panel" style="margin-top:22px;background:#eef7f1;border-color:#b6e3cd">
<h3 style="color:var(--ok)">↩︎ And then thirty days to change your mind</h3>
<p class="mut" style="margin:6px 0 0">{e(C.FREE_LOOK)}</p></div>
<p style="margin-top:24px"><a class="btn lg" href="/quote">Start the conversation</a></p>
</div></section>""", me(request), title="How it works — Policy Store", canon="/how-it-works"))


@app.get("/coverage", response_class=HTMLResponse)
def coverage(request: Request):
    rows = ""
    for st in sorted(set(list(P.LIVE) + list(P.PENDING) + P.UNAVAILABLE)):
        status = P.state_status(st)
        if status == "live":
            s = P.LIVE[st]
            prods = " ".join(f'<span class="tag ok">{P.PRODUCTS[k]["short"]}</span>'
                             for k in ("add", "ame", "ci") if s.get(k))
            badge = '<span class="tag ok">Writing</span>'
        elif status == "pending":
            prods = '<span class="mut small">Filed, launch ' + e(P.PENDING[st]) + '</span>'
            badge = '<span class="tag warn">Pending</span>'
        else:
            prods = '<span class="mut small">Not offered</span>'
            badge = '<span class="tag off">Unavailable</span>'
        t365 = P.t365_tier(st)
        tr = (f'<span class="tag ok">Tier {t365}</span>' if t365 else
              ('<span class="tag warn">No published rate</span>' if st in P.T365_NO_RATE
               else '<span class="tag off">—</span>'))
        rows += (f"<tr><td><b>{st}</b> <span class='mut small'>{e(P.STATE_NAMES.get(st,''))}</span>"
                 f"</td><td>{badge}</td><td>{prods}</td><td>{tr}</td></tr>")
    return HTMLResponse(shell(f"""
<section class="navy-bg"><div class="wrap pad-s" style="padding:38px 0 32px">
<h1>Where we're writing</h1>
<p class="lead">Accident products are live in {len(P.LIVE)} states. Travel 365 is filed
separately and covers considerably more ground. The agent checks this table before it quotes
anything — it will not offer you a product your state cannot buy.</p></div></section>
<section class="wrap pad"><div class="panel"><div class="tablewrap">
<table class="data"><tr><th>State</th><th>Accident products</th><th>Available</th>
<th>Travel 365</th></tr>{rows}</table></div></div>
<p class="small mut" style="margin-top:14px">Travel 365 tiers are the carrier's own pricing
bands. Four states appear on Chubb's availability sheet but carry no published rate on ours, so
they are quoted on request rather than guessed at.</p>
</section>""", me(request), title="State availability — Policy Store", canon="/coverage"))


@app.get("/free-look", response_class=HTMLResponse)
def free_look(request: Request):
    return HTMLResponse(shell(f"""
<section class="wrap pad"><div class="narrow">
<div class="kicker">Your right to change your mind</div>
<h1 style="margin:8px 0 14px">The 30-day free look</h1>
<p class="lead">{e(C.FREE_LOOK)}</p>
<div class="panel" style="margin-top:24px">
<h3>How it works in practice</h3>
<ul class="mut" style="margin:12px 0 0 20px">
<li style="margin-bottom:8px">Your policy documents arrive by email the moment the
administrator confirms payment.</li>
<li style="margin-bottom:8px">The thirty days run from that delivery date, and the exact date
is shown in your account.</li>
<li style="margin-bottom:8px">Cancel from your account, or call {e(C.PHONE)}. There is no
retention script — the agent processes it.</li>
<li style="margin-bottom:8px">Premium is refunded in full, provided no claim has been filed
against the policy.</li></ul></div>
<p style="margin-top:22px"><a class="btn" href="/quote">Get a quote</a>
<a class="btn ghost" href="/account">Manage my policy</a></p>
</div></section>""", me(request), title="30-day free look — Policy Store", canon="/free-look"))


# ===================================================== the conversation ======
AGENT = "Avery"          # the autonomous agent's name, used in the transcript

GOALS = [
    ("add", "If something happened to me, my family would need money",
     "That is exactly what Accidental Death &amp; Dismemberment is for."),
    ("ame", "An emergency room bill would really hurt right now",
     "Then Accident Medical Expense is the one to look at."),
    ("ci", "A serious diagnosis would derail us financially",
     "Critical Illness pays you a lump sum on a covered diagnosis."),
    ("t365", "I travel a lot and want to be covered abroad",
     "Travel 365 covers a whole year of trips rather than one at a time."),
    ("add+ame", "Both — the worst case and the expensive case",
     "AD&amp;D and Accident Medical together is the most common pairing we write."),
    ("", "Honestly, I'm not sure — help me choose",
     "No problem at all. Let me ask one more thing."),
]


def q_get(request):
    return request.session.get("q") or {}


def q_set(request, q):
    request.session["q"] = q


def say(q, who, text):
    q.setdefault("transcript", []).append({"who": who, "text": text, "ts": time.time()})


def next_step(q):
    if not q.get("state"):
        return "state"
    if P.state_status(q["state"]) != "live" and q.get("want") != "t365" \
            and not q.get("t365_only"):
        return "unavailable"
    if not q.get("age"):
        return "age"
    if not q.get("want"):
        return "goal"
    if q["want"] == "t365":
        return "quote"
    if not q.get("household"):
        return "household"
    if q.get("need_spouse_age") and not q.get("spouse_age"):
        return "spouse_age"
    if q.get("need_kid_count") and q.get("children") is None:
        return "children"
    if not q.get("budget_asked"):
        return "budget"
    return "quote"


def msg_html(q):
    out = ""
    for m in q.get("transcript", [])[-14:]:
        if m["who"] == "agent":
            out += (f'<div class="msg"><div class="av">A</div>'
                    f'<div class="bubble">{m["text"]}</div></div>')
        else:
            out += (f'<div class="msg you"><div class="av">You</div>'
                    f'<div class="bubble">{e(m["text"])}</div></div>')
    return out


def ask_block(step, q):
    """Render the question the agent is currently waiting on."""
    if step == "state":
        opts = "".join(f'<option value="{s}">{e(P.STATE_NAMES.get(s,s))} ({s})</option>'
                       for s in sorted(P.STATE_NAMES))
        return f"""<form method="post" action="/quote/step"><input type="hidden" name="step" value="state">
<label for="st">Your state of residence</label>
<select id="st" name="value" required autofocus><option value="">Choose your state…</option>
{opts}</select>
<button class="btn block lg" style="margin-top:14px" type="submit">Continue</button></form>"""
    if step == "age":
        return """<form method="post" action="/quote/step"><input type="hidden" name="step" value="age">
<label for="ag">Your age</label>
<input id="ag" type="number" name="value" min="18" max="99" required autofocus
 placeholder="e.g. 42" inputmode="numeric">
<p class="hint">Rates are age-banded, so this changes the number.</p>
<button class="btn block lg" style="margin-top:10px" type="submit">Continue</button></form>"""
    if step == "goal":
        btns = "".join(f"""<form method="post" action="/quote/step" style="display:inline">
<input type="hidden" name="step" value="goal"><input type="hidden" name="value" value="{k}">
<button type="submit">{t}</button></form>""" for k, t, _ in GOALS)
        return f'<div class="opts">{btns}</div>'
    if step == "household":
        opts = [("single", "Just me"), ("spouse", "Me and my spouse"),
                ("kids", "Me and my children"), ("family", "Me, my spouse and our children")]
        btns = "".join(f"""<form method="post" action="/quote/step" style="display:inline">
<input type="hidden" name="step" value="household"><input type="hidden" name="value" value="{k}">
<button type="submit">{e(t)}</button></form>""" for k, t in opts)
        return f'<div class="opts">{btns}</div>'
    if step == "spouse_age":
        return """<form method="post" action="/quote/step">
<input type="hidden" name="step" value="spouse_age">
<label for="sa">Your spouse's age</label>
<input id="sa" type="number" name="value" min="18" max="99" required autofocus
 inputmode="numeric">
<button class="btn block lg" style="margin-top:12px" type="submit">Continue</button></form>"""
    if step == "children":
        btns = "".join(f"""<form method="post" action="/quote/step" style="display:inline">
<input type="hidden" name="step" value="children"><input type="hidden" name="value" value="{n}">
<button type="submit">{n}{'+' if n == 4 else ''}</button></form>""" for n in (1, 2, 3, 4))
        return f'<div class="opts">{btns}</div>'
    if step == "budget":
        return """<form method="post" action="/quote/step"><input type="hidden" name="step" value="budget">
<label for="bd">What would you like to spend a month?</label>
<input id="bd" type="number" name="value" min="0" step="1" autofocus placeholder="e.g. 45"
 inputmode="decimal">
<p class="hint">Give me a number and I'll fit the largest benefit that lands under it. Leave it
blank if you'd rather see the options first.</p>
<button class="btn block lg" style="margin-top:10px" type="submit">Show me the quote</button>
</form>"""
    return ""


PROMPTS = {
    "state": "First — which state do you live in? Coverage is filed state by state, so this "
             "decides what I'm allowed to offer you.",
    "age": "Thanks. And how old are you? Rates are banded by age, so this is the other half of "
           "the calculation.",
    "goal": "Now the useful question: what's actually on your mind?",
    "household": "Would you like this to cover anyone else? Adding a spouse or children changes "
                 "the price, and I'll need their ages if you do.",
    "spouse_age": "How old is your spouse? Their rate is calculated on their own age band.",
    "children": "How many children would you like on the plan?",
    "budget": "Last one. What would you like to spend a month?",
}


@app.get("/quote", response_class=HTMLResponse)
def quote_start(request: Request, want: str = "", restart: int = 0):
    q = q_get(request)
    if restart or not q:
        q = {"transcript": [], "started": time.time()}
        say(q, "agent", f"Hi, I'm {AGENT} — I'm the agent here, and I'm not a person. "
                        f"I can quote you and get you covered in about a minute, at any hour. "
                        f"Nothing I show you is a guess: I read from the carrier's rate sheet.")
    if want in ("add", "ame", "ci", "t365", "add+ame", "add+ci", "ame+ci"):
        q["want"] = want
        if want == "t365":
            q["t365_only"] = True
    q_set(request, q)
    return RedirectResponse("/quote/ask", status_code=303)


@app.get("/quote/ask", response_class=HTMLResponse)
def quote_ask(request: Request):
    q = q_get(request)
    if not q:
        return RedirectResponse("/quote?restart=1", status_code=303)
    step = next_step(q)
    if step == "quote":
        return RedirectResponse("/quote/result", status_code=303)
    if step == "unavailable":
        st = q["state"]
        status = P.state_status(st)
        why = ("is filed and due to launch " + P.PENDING.get(st, "shortly")
               if status == "pending" else "is not offered in your state yet")
        t365 = P.t365_tier(st)
        alt = ""
        if t365:
            r = P.T365_RATES[t365]["basics"]
            alt = (f"<p>Travel 365 <b>is</b> available where you are — from "
                   f"{money(r['monthly'])} a month. Would that be useful?</p>"
                   f"<p style='margin-top:14px'><a class='btn' href='/quote?want=t365&restart=1'>"
                   f"Quote Travel 365</a></p>")
        say(q, "agent", f"I have to be straight with you — accident coverage {why} "
                        f"({e(P.STATE_NAMES.get(st, st))}). I won't quote you something I can't "
                        f"actually sell you.")
        q_set(request, q)
        return HTMLResponse(shell(f"""<section class="wrap pad"><div class="chat">
{msg_html(q)}
<div class="ask"><div class="warn"><b>Not available in {e(st)}.</b> Accident products are live
in {len(P.LIVE)} states today.</div>{alt}
<p style="margin-top:12px"><a class="btn ghost" href="/coverage">See the availability map</a>
<a class="btn ghost" href="/quote?restart=1">Start over</a></p></div>
</div></section>""", me(request), title="Quote — Policy Store"))
    if not q.get("transcript") or q["transcript"][-1]["who"] != "agent" or \
            q.get("_asked") != step:
        say(q, "agent", PROMPTS.get(step, ""))
        q["_asked"] = step
        q_set(request, q)
    order = ["state", "age", "goal", "household", "spouse_age", "children", "budget"]
    pct = int(100 * (order.index(step) + 1) / (len(order) + 1)) if step in order else 90
    return HTMLResponse(shell(f"""<section class="wrap pad"><div class="chat">
<div class="progress"><i style="width:{pct}%"></i></div>
{msg_html(q)}
<div class="ask">{ask_block(step, q)}</div>
<p class="small mut center" style="margin-top:16px">Prefer a person? Call {e(C.PHONE)}.
· <a href="/quote?restart=1">Start over</a></p>
</div></section>""", me(request), title="Talk to the agent — Policy Store", canon="/quote"))


@app.post("/quote/step")
def quote_step(request: Request, step: str = Form(...), value: str = Form("")):
    q = q_get(request)
    if not q:
        return RedirectResponse("/quote?restart=1", status_code=303)
    v = (value or "").strip()
    if step == "state":
        q["state"] = v.upper()
        say(q, "you", P.STATE_NAMES.get(q["state"], q["state"]))
        if P.state_status(q["state"]) == "live":
            avail = [P.PRODUCTS[p]["short"] for p in P.state_products(q["state"])]
            say(q, "agent", f"Good — {e(P.STATE_NAMES.get(q['state'], q['state']))} is live for "
                            f"<b>{', '.join(avail)}</b>.")
    elif step == "age":
        try:
            q["age"] = max(18, min(99, int(float(v))))
        except ValueError:
            return RedirectResponse("/quote/ask", status_code=303)
        say(q, "you", f"{q['age']}")
    elif step == "goal":
        q["want"] = v
        label = next((t for k, t, _ in GOALS if k == v), v)
        reply = next((r for k, _, r in GOALS if k == v), "")
        say(q, "you", re.sub("<[^>]+>", "", label).replace("&amp;", "&"))
        if v == "":
            # undecided: recommend from what the state allows and what most people take
            avail = P.state_products(q["state"])
            q["want"] = "add+ame" if ("add" in avail and "ame" in avail) else (avail[0] if avail else "add")
            picked = " and ".join(P.PRODUCTS[p]["short"] for p in q["want"].split("+"))
            say(q, "agent", f"Then let me put you where most people land. In your state I can "
                            f"write <b>{picked}</b> — one covers the worst case, the other covers "
                            f"the expensive one. I'll price that and you can change it after.")
        else:
            say(q, "agent", reply)
        if q["want"] == "t365":
            q["t365_only"] = True
    elif step == "household":
        q["household"] = v
        labels = {"single": "Just me", "spouse": "Me and my spouse",
                  "kids": "Me and my children", "family": "Me, my spouse and our children"}
        say(q, "you", labels.get(v, v))
        q["need_spouse_age"] = v in ("spouse", "family")
        q["need_kid_count"] = v in ("kids", "family")
        if v == "single":
            q["children"] = 0
            say(q, "agent", "Understood — just you.")
        else:
            say(q, "agent", "Good. Rates are age-banded, so I need an age for each adult.")
    elif step == "spouse_age":
        try:
            q["spouse_age"] = max(18, min(99, int(float(v))))
        except ValueError:
            return RedirectResponse("/quote/ask", status_code=303)
        say(q, "you", f"My spouse is {q['spouse_age']}")
        if not q.get("need_kid_count"):
            q["children"] = 0
    elif step == "children":
        try:
            q["children"] = max(0, min(4, int(float(v))))
        except ValueError:
            q["children"] = 0
        say(q, "you", f"{q['children']}{'+' if q['children'] == 4 else ''} "
                      f"child{'ren' if q['children'] != 1 else ''}")
        say(q, "agent", "Children are covered as a group on this plan, so I don't need each "
                        "of their ages.")
    elif step == "budget":
        q["budget_asked"] = True
        try:
            q["budget"] = float(v) if v else None
        except ValueError:
            q["budget"] = None
        say(q, "you", money(q["budget"]) + " a month" if q.get("budget") else
            "Show me the options first")
    q.pop("_asked", None)
    q_set(request, q)
    return RedirectResponse("/quote/ask", status_code=303)


# ============================================================ quote result ====
def save_quote(request, q, monthly, annual, product, benefit, ci_benefit=0, deductible=100,
               t365_plan=None, term="monthly"):
    token = secrets.token_urlsafe(9)
    with closing(db()) as c:
        qid = c.execute("""INSERT INTO quotes(token,session,user_id,first,last,email,phone,state,
            age,tier,spouse_age,child_ages,product,benefit,deductible,ci_benefit,t365_plan,term,
            monthly,annual,demo_rates,target_premium,transcript,status,created)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'quoted',?)""",
            (token, request.session.get("sid") or "", (me(request) or {}).get("id"),
             q.get("first"), q.get("last"), q.get("email"), q.get("phone"), q.get("state"),
             q.get("age"), q.get("household"), q.get("spouse_age"),
             json.dumps(q.get("children") or 0), product, benefit, deductible, ci_benefit,
             t365_plan, term, monthly, annual,
             1 if (rates_are_demo() and product != "t365") else 0,
             q.get("budget"), json.dumps(q.get("transcript") or []), time.time())).lastrowid
        c.commit()
    log("quote", f"{product} {money(monthly)}/mo in {q.get('state')}", qid)
    return token, qid


@app.get("/quote/result", response_class=HTMLResponse)
def quote_result(request: Request, benefit: int = 0, ded: int = 100, plan: str = "",
                 term: str = "monthly"):
    q = q_get(request)
    if not q or not q.get("state") or not q.get("age"):
        return RedirectResponse("/quote?restart=1", status_code=303)
    st, age = q["state"], q["age"]
    u = me(request)

    # ---------- Travel 365 ----------
    if q.get("want") == "t365":
        if age > P.T365_MAX_AGE:
            return HTMLResponse(shell(f"""<section class="wrap pad"><div class="chat">
{msg_html(q)}<div class="ask"><div class="warn">Travel 365 is not available for travellers over
{P.T365_MAX_AGE}. I won't quote something that can't be issued.</div>
<a class="btn ghost" href="/quote?restart=1">Look at something else</a></div></div></section>""",
                u, title="Quote — Policy Store"))
        opts = t365_quote(st, term)
        if not opts:
            return HTMLResponse(shell(f"""<section class="wrap pad"><div class="chat">
{msg_html(q)}<div class="ask"><div class="warn">Travel 365 is filed in {e(st)} but our rate
sheet has no published price for it yet, so I'd be guessing. Call {e(C.PHONE)} and we'll get you
the real number.</div><a class="btn ghost" href="/quote?restart=1">Start over</a></div>
</div></section>""", u, title="Quote — Policy Store"))
        chosen = plan or "essentials"
        pick = next(o for o in opts if o["key"] == chosen)
        token, qid = save_quote(request, q, pick["monthly"], pick["yearly"], "t365", 0,
                                t365_plan=chosen, term=term)
        q["token"] = token
        q_set(request, q)
        cards = ""
        for o in opts:
            on = o["key"] == chosen
            cards += f"""<div class="card" style="{'border:2px solid var(--blue)' if on else ''}">
<div style="height:5px;background:{o['colour']};border-radius:4px;margin-bottom:12px"></div>
<h3>{e(o['name'])}</h3>
<div style="font-size:30px;font-weight:850;color:var(--navy);letter-spacing:-1px;margin:6px 0 2px">
{money(o['monthly'])}<span style="font-size:14px;font-weight:600;color:var(--soft)">/mo</span></div>
<p class="small mut">{money(o['yearly'])} a year · {money(o['biweekly'])} bi-weekly</p>
<div class="foot">{'<span class="tag ok">Selected</span>' if on else
 f'<a class="btn ghost sm" href="/quote/result?plan={o["key"]}">Choose this</a>'}</div></div>"""
        return HTMLResponse(shell(f"""<section class="wrap pad"><div class="chat">
{msg_html(q)}
<div class="msg"><div class="av">A</div><div class="bubble">
<p>Here's what Travel 365 costs where you are. These are the carrier's real published rates —
per person, for a full year of trips.</p></div></div></div>
<div style="max-width:960px;margin:22px auto 0">
<div class="grid g3">{cards}</div>
<div class="qbox" style="margin-top:22px">
<div class="kicker" style="color:var(--sky)">Your selection</div>
<div class="amt" style="margin-top:6px">{money(pick['monthly'])}<span class="per">/month</span></div>
<p style="color:#9dc3ea;margin-top:6px">{e(pick['name'])} · {money(pick['yearly'])} annually ·
state rate tier {pick['tier']}</p>
<div style="margin-top:18px">{text_me_form(q, token)}</div></div>
<p class="small mut" style="margin-top:14px">{" ".join(P.T365_NOTES)}</p>
</div></section>""", u, title="Your Travel 365 quote — Policy Store"))

    # ---------- accident products ----------
    prods = [p for p in q.get("want", "add").split("+") if p in P.PRODUCTS]
    prods = [p for p in prods if p in P.state_products(st)]
    if not prods:
        return RedirectResponse("/quote/ask", status_code=303)
    spouse = q.get("spouse_age")
    kids = int(q.get("children") or 0)
    if not benefit:
        fit = best_fit(prods, st, age, q.get("budget"), spouse, kids)
        if not fit:
            return HTMLResponse(shell(f"""<section class="wrap pad"><div class="chat">
{msg_html(q)}<div class="ask"><div class="warn">I can't build a quote from the filed rates at
that age for this product. Call {e(C.PHONE)} and a person will sort it.</div></div></div>
</section>""", u, title="Quote — Policy Store"))
        benefit, ci_ben = fit["benefit"], fit["ci_benefit"]
        monthly, lines = fit["monthly"], fit["lines"]
        over = fit.get("over_budget")
    else:
        ci_ben = min(P.PRODUCTS["ci"]["benefits"],
                     key=lambda x: abs(x - benefit)) if "ci" in prods else 0
        monthly, lines, probs = quote_premium(prods, st, age, benefit, ded, ci_ben, spouse, kids)
        over = bool(q.get("budget") and monthly > float(q["budget"]))
    token, qid = save_quote(request, q, monthly, round(monthly * 12, 2), "+".join(prods),
                            benefit, ci_ben, ded)
    q["token"] = token
    q_set(request, q)
    names = " and ".join(P.PRODUCTS[p]["name"] for p in prods)
    breakdown = "".join(f'<div class="qline"><span>{e(l)}</span><b>{money(v)}</b></div>'
                        for l, v in lines)
    grid = P.PRODUCTS[prods[0]]["benefits"]
    alts = "".join(
        f'<a class="pill" href="/quote/result?benefit={b}&ded={ded}" '
        f'style="{"border-color:var(--blue);color:var(--blue)" if b == benefit else ""}">'
        f'{money(b, False)}</a>' for b in grid)
    deds = ""
    if "ame" in prods:
        deds = ('<p class="small mut" style="margin:14px 0 4px"><b>Accident Medical deductible</b>'
                '</p>' + "".join(
                    f'<a class="pill" href="/quote/result?benefit={benefit}&ded={d}" '
                    f'style="{"border-color:var(--blue);color:var(--blue)" if d == ded else ""}">'
                    f'{money(d, False)}</a>' for d in P.PRODUCTS["ame"]["deductibles"]))
    budget_note = ""
    if q.get("budget"):
        if over:
            budget_note = (f'<div class="warn">The smallest filed benefit still comes to '
                           f'{money(monthly)}, which is over the {money(q["budget"])} you '
                           f'mentioned. I would rather tell you that than quietly quote you '
                           f'something else.</div>')
        else:
            budget_note = (f'<div class="okmsg">You said about {money(q["budget"])} a month — '
                           f'this is the largest benefit that fits under it.</div>')
    say(q, "agent", f"Here it is. {money(monthly)} a month for {money(benefit, False)} of "
                    f"{names.replace('&', '&amp;')}.")
    q_set(request, q)
    return HTMLResponse(shell(f"""<section class="wrap pad"><div class="chat">{msg_html(q)}</div>
<div style="max-width:960px;margin:22px auto 0"><div class="grid g2" style="gap:24px">
<div>{demo_banner()}{budget_note}
<div class="qbox">
<div class="kicker" style="color:var(--sky)">Your quote</div>
<div class="amt" style="margin-top:6px">{money(monthly)}<span class="per">/month</span></div>
<p style="color:#9dc3ea;margin:6px 0 16px">{e(names)} · {money(benefit, False)} benefit ·
{e(P.STATE_NAMES.get(st, st))}</p>
{breakdown}
<div class="qline" style="border-top:2px solid rgba(255,255,255,.25);margin-top:6px;
padding-top:10px"><span><b>Total monthly</b></span><b>{money(monthly)}</b></div>
<div style="margin-top:18px">{text_me_form(q, token)}</div></div></div>
<div><div class="panel"><h3>Adjust the benefit</h3>
<p class="small mut">Every amount below is a filed option for this product.</p>
<div style="margin-top:10px">{alts}</div>{deds}</div>
<div class="panel" style="margin-top:16px;background:#eef7f1;border-color:#b6e3cd">
<h3 style="color:var(--ok)">↩︎ 30 days to change your mind</h3>
<p class="mut" style="margin:6px 0 0;font-size:14.3px">{e(C.FREE_LOOK)}</p></div>
<div class="panel" style="margin-top:16px"><h3>Want to add someone?</h3>
<p class="mut small">Spouse and children change the price, and I'll need their ages.
<a href="/quote?restart=1">Start again</a> and tell me about them.</p></div>
</div></div></div></section>""", u, title="Your quote — Policy Store"))


def text_me_form(q, token):
    return f"""<form method="post" action="/quote/text" style="display:grid;gap:9px">
<input type="hidden" name="token" value="{e(token)}">
<div style="display:grid;grid-template-columns:1fr 1fr;gap:9px">
<input type="text" name="first" placeholder="First name" required value="{e(q.get('first',''))}"
 style="background:rgba(255,255,255,.94)">
<input type="text" name="last" placeholder="Last name" value="{e(q.get('last',''))}"
 style="background:rgba(255,255,255,.94)"></div>
<input type="tel" name="phone" placeholder="Mobile number" required value="{e(q.get('phone',''))}"
 style="background:rgba(255,255,255,.94)">
<input type="email" name="email" placeholder="Email" required value="{e(q.get('email',''))}"
 style="background:rgba(255,255,255,.94)">
<button class="btn green block lg" type="submit">📱 Text me the link to enroll</button>
<p style="font-size:12px;color:#9dc3ea;margin:0">A short link lands on your phone. You pay the
administrator — card details never touch this conversation.</p></form>"""


@app.post("/quote/text")
def quote_text(request: Request, token: str = Form(...), first: str = Form(""),
               last: str = Form(""), phone: str = Form(""), email: str = Form("")):
    q = q_get(request)
    with closing(db()) as c:
        row = c.execute("SELECT * FROM quotes WHERE token=?", (token,)).fetchone()
        if not row:
            raise HTTPException(404, "Quote not found")
        c.execute("UPDATE quotes SET first=?,last=?,phone=?,email=?,status='texted' WHERE id=?",
                  (first.strip(), last.strip(), phone.strip(), email.strip(), row["id"]))
        c.commit()
        row = dict(c.execute("SELECT * FROM quotes WHERE id=?", (row["id"],)).fetchone())
    q.update({"first": first.strip(), "last": last.strip(), "phone": phone.strip(),
              "email": email.strip()})
    code = short_link(f"{SITE}/checkout/{token}", row["id"])
    link = f"{SITE}/s/{code}"
    body = (f"Policy Store: here's your quote — {money(row['monthly'])}/mo. "
            f"Review and enroll securely: {link} (30-day free look)")
    sent = send_sms(phone, body, row["id"])
    ping_post(row, "ping")
    say(q, "you", f"Text it to {phone}")
    say(q, "agent", f"Sent. Check your phone — the link is {link}. I'll stay right here while "
                    f"you look at it.")
    q_set(request, q)
    if row["email"]:
        send_email(row["email"], "Your Policy Store quote",
                   f"<p>Your quote is {money(row['monthly'])} a month.</p>"
                   f"<p><a href='{link}'>Review and enrol</a></p>"
                   f"<p>{e(C.FREE_LOOK)}</p>")
    send_email(OWNER_EMAIL, f"[Policy Store] Quote texted — {first} {last}",
               f"<p>{e(first)} {e(last)} · {e(phone)} · {e(email)}</p>"
               f"<p>{e(row['product'])} · {money(row['monthly'])}/mo · {e(row['state'])}</p>"
               f"<p>Link: {link}</p>")
    status = ("Sent." if sent else
              ("Simulated — no SMS provider is configured yet." if sent is None
               else "The SMS provider rejected it."))
    return HTMLResponse(shell(f"""<section class="wrap pad"><div class="chat">
{msg_html(q)}
<div class="ask center">
<div class="sms"><div class="notch"></div>
<div class="bub"><div class="who">Policy Store</div>Here's your quote —
{money(row['monthly'])}/mo. Review and enroll securely:<br>
<a href="/checkout/{e(token)}">{e(link)}</a><br><br>30-day free look.</div></div>
<p class="small mut" style="margin-top:16px"><b>{e(status)}</b> The agent stays on the line
while you complete it.</p>
<p style="margin-top:14px"><a class="btn lg" href="/checkout/{e(token)}">Open it here instead</a></p>
</div></div></section>""", me(request), title="Check your phone — Policy Store"))


# =============================================================== checkout ====
@app.get("/checkout/{token}", response_class=HTMLResponse)
def checkout(request: Request, token: str):
    with closing(db()) as c:
        r = c.execute("SELECT * FROM quotes WHERE token=?", (token,)).fetchone()
    if not r:
        raise HTTPException(404, "That link has expired")
    r = dict(r)
    log("checkout_view", f"quote {token}", r["id"])
    if r["product"] == "t365":
        pname = next((n for k, n, _ in P.T365_PLANS if k == r["t365_plan"]), "Travel 365")
        detail = f"{pname} · annual term · per person"
    else:
        names = " and ".join(P.PRODUCTS[p]["name"] for p in (r["product"] or "").split("+")
                             if p in P.PRODUCTS)
        detail = f"{names} · {money(r['benefit'], False)} benefit"
        if "ame" in (r["product"] or ""):
            detail += f" · {money(r['deductible'], False)} deductible"
    return HTMLResponse(shell(f"""
<section class="wrap pad"><div class="narrow">
<div class="kicker">Enrolment</div>
<h1 style="margin:8px 0 6px">You're one step from covered.</h1>
<p class="lead">Review it, then pay the administrator. Nothing is charged by us and no card
details pass through this site.</p>
{demo_banner() if r['demo_rates'] else ''}
<div class="panel" style="margin-top:20px">
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px;
flex-wrap:wrap">
<div><h3>{e(detail)}</h3>
<p class="mut small" style="margin-top:4px">{e(P.STATE_NAMES.get(r['state'], r['state']))} ·
age {r['age']} · quote {e(token)}</p></div>
<div style="text-align:right"><div style="font-size:34px;font-weight:850;color:var(--navy);
letter-spacing:-1.2px;line-height:1">{money(r['monthly'])}</div>
<div class="small mut">per month · {money(r['annual'])} a year</div></div></div>
<hr style="border:0;border-top:1px solid var(--line);margin:18px 0">
<h4 style="margin-bottom:8px">What happens when you press the button</h4>
<ol class="mut" style="margin:0 0 0 20px;font-size:14.5px">
<li style="margin-bottom:6px">You're handed to the third-party administrator to pay.</li>
<li style="margin-bottom:6px">They post acceptance back to us automatically.</li>
<li style="margin-bottom:6px">Your policy issues and documents go to your email.</li>
<li style="margin-bottom:6px">Your 30-day free look starts from that delivery.</li>
</ol></div>
<div class="panel" style="margin-top:16px;background:#eef7f1;border-color:#b6e3cd">
<h3 style="color:var(--ok)">↩︎ 30-day free look</h3>
<p class="mut" style="margin:6px 0 0;font-size:14.5px">{e(C.FREE_LOOK)}</p></div>
<form method="post" action="/enrol" style="margin-top:20px">
<input type="hidden" name="token" value="{e(token)}">
<div class="fr two">
<div><label>First name</label><input name="first" required value="{e(r['first'])}"></div>
<div><label>Last name</label><input name="last" value="{e(r['last'])}"></div></div>
<div class="fr two">
<div><label>Email</label><input type="email" name="email" required value="{e(r['email'])}"></div>
<div><label>Mobile</label><input type="tel" name="phone" required value="{e(r['phone'])}"></div>
</div>
<label style="display:flex;gap:9px;align-items:flex-start;font-weight:500;font-size:14px;
color:var(--mut);margin:8px 0 16px"><input type="checkbox" required style="width:auto;
margin-top:3px"> I've read how this works and I want to enrol. I understand coverage begins when
the administrator accepts payment, and that full terms are in the policy documents.</label>
<button class="btn green block lg" type="submit">Continue to secure payment →</button>
<p class="hint center">Payment is taken by the third-party administrator, not by Policy Store.</p>
</form></div></section>""", me(request), title="Enrol — Policy Store",
        canon=f"/checkout/{token}"))


@app.post("/enrol")
def enrol(request: Request, token: str = Form(...), first: str = Form(""), last: str = Form(""),
          email: str = Form(""), phone: str = Form("")):
    with closing(db()) as c:
        r = c.execute("SELECT * FROM quotes WHERE token=?", (token,)).fetchone()
        if not r:
            raise HTTPException(404, "Quote not found")
        c.execute("UPDATE quotes SET first=?,last=?,email=?,phone=?,status='enrolling' WHERE id=?",
                  (first.strip(), last.strip(), email.strip(), phone.strip(), r["id"]))
        c.commit()
        r = dict(c.execute("SELECT * FROM quotes WHERE id=?", (r["id"],)).fetchone())

    policy_no = "PS-" + secrets.token_hex(4).upper()
    ok_ping, payload = ping_post(r, "post")
    ok_tpa = tpa_submit(r, policy_no)
    free_look_ends = (date.today() + timedelta(days=30)).isoformat()
    with closing(db()) as c:
        pid = c.execute("""INSERT INTO policies(quote_id,user_id,policy_no,status,free_look_ends,
                           created) VALUES(?,?,?,?,?,?)""",
                        (r["id"], r["user_id"], policy_no,
                         "active" if ok_tpa is not False else "pending",
                         free_look_ends, time.time())).lastrowid
        c.execute("UPDATE quotes SET status='enrolled' WHERE id=?", (r["id"],))
        c.commit()
    send_email(r["email"], f"Your policy {policy_no} — Policy Store",
               f"<p>Thank you. Your coverage is being issued.</p>"
               f"<p><b>Policy:</b> {policy_no}<br><b>Premium:</b> {money(r['monthly'])}/month</p>"
               f"<p>Your 30-day free look runs to {free_look_ends}.</p>"
               f"<p><a href='{SITE}/account'>Create your account to manage billing</a></p>")
    send_email(OWNER_EMAIL, f"[Policy Store] ENROLLED {policy_no} — {first} {last}",
               f"<p>{e(first)} {e(last)} · {e(email)} · {e(phone)}</p>"
               f"<p>{e(r['product'])} · {money(r['monthly'])}/mo · {e(r['state'])}</p>"
               f"<p>Ping-post: {ok_ping} · TPA: {ok_tpa}</p>")

    tpa_note = ("Sent to the administrator and accepted." if ok_tpa else
                ("Simulated — no administrator endpoint is configured yet, so nothing was "
                 "actually charged." if ok_tpa is None else
                 "The administrator did not accept it; we'll call you."))
    pp_note = ("Posted." if ok_ping else
               ("Simulated — no ping-post endpoint configured." if ok_ping is None
                else "The endpoint rejected the post."))
    q = q_get(request)
    say(q, "agent", f"That's done — you're covered. Your policy number is {policy_no}. "
                    f"Is there anything else I can help you with today?")
    q_set(request, q)
    return HTMLResponse(shell(f"""
<section class="wrap pad"><div class="narrow">
<div class="panel center" style="border-color:#b6e3cd;background:#f4fbf7">
<div style="font-size:46px">✅</div>
<h1 style="margin:8px 0 6px">You're covered.</h1>
<p class="lead">Policy <b>{policy_no}</b> · {money(r['monthly'])} a month</p>
<p class="mut">Documents are on their way to {e(r['email'])}. Your 30-day free look runs to
<b>{free_look_ends}</b>.</p></div>

<div class="panel" style="margin-top:18px">
<h3>What just happened, in order</h3>
<table class="data" style="margin-top:10px">
<tr><td>Payment handed to the administrator</td><td><b>{e(tpa_note)}</b></td></tr>
<tr><td>Sale posted to the ping-post endpoint</td><td><b>{e(pp_note)}</b></td></tr>
<tr><td>Policy documents emailed</td><td><b>Sent to {e(r['email'])}</b></td></tr>
<tr><td>Free look</td><td><b>30 days, to {free_look_ends}</b></td></tr></table>
<p class="hint">Every one of these steps is logged. Admin → Activity shows the exact payloads.</p>
</div>

<div class="panel" style="margin-top:18px">
<h3>Create your account</h3>
<p class="mut">Manage billing, download documents, or cancel inside the free look — without
calling anyone.</p>
<form method="post" action="/signup" style="margin-top:12px">
<input type="hidden" name="policy_id" value="{pid}">
<input type="hidden" name="email" value="{e(r['email'])}">
<div class="fr two">
<div><label>Your email</label><input value="{e(r['email'])}" readonly
 style="background:#f3f7fb"></div>
<div><label>Choose a password</label><input type="password" name="pw" required minlength="8"
 autocomplete="new-password"></div></div>
<button class="btn block" type="submit">Create my account</button></form></div>

<div class="panel" style="margin-top:18px;background:var(--navy);color:#cfe4ff;border:0">
<h3 style="color:#fff">Anything else I can help you with?</h3>
<p style="color:#a9c8e8">The agent doesn't hang up. Travel cover for a trip you have coming up,
or accident medical for your spouse — it's the same conversation.</p>
<p style="margin-top:12px"><a class="btn" href="/quote?restart=1">Ask about something else</a>
<a class="btn onnavy" href="tel:{e(C.PHONE)}">Talk to a person</a></p></div>
</div></section>""", me(request), title=f"Covered — {policy_no}"))


# ================================================================ account ====
@app.post("/signup")
def signup(request: Request, email: str = Form(...), pw: str = Form(...),
           policy_id: int = Form(0)):
    email = email.strip().lower()
    if len(pw) < 8:
        return RedirectResponse("/login?err=Use+at+least+8+characters", status_code=303)
    with closing(db()) as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return RedirectResponse("/login?err=That+email+already+has+an+account", status_code=303)
        q = c.execute("SELECT * FROM quotes WHERE email=? ORDER BY id DESC LIMIT 1",
                      (email,)).fetchone()
        uid = c.execute("""INSERT INTO users(email,pw,role,first,last,phone,state,created)
                           VALUES(?,?,'customer',?,?,?,?,?)""",
                        (email, hash_pw(pw), q["first"] if q else "", q["last"] if q else "",
                         q["phone"] if q else "", q["state"] if q else "",
                         time.time())).lastrowid
        if policy_id:
            c.execute("UPDATE policies SET user_id=? WHERE id=?", (uid, policy_id))
        c.execute("UPDATE quotes SET user_id=? WHERE email=?", (uid, email))
        c.commit()
    request.session["uid"] = uid
    return RedirectResponse("/account", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request, next: str = "/account", err: str = ""):
    return HTMLResponse(shell(f"""<section class="wrap pad"><div style="max-width:430px;
margin:0 auto"><div class="panel"><h1 style="font-size:28px;margin-bottom:16px">Log in</h1>
{f'<div class="err">{e(err)}</div>' if err else ''}
<form method="post" action="/login"><input type="hidden" name="next" value="{e(next)}">
<div class="fr"><div><label>Email</label><input type="email" name="email" required autofocus
 autocomplete="username"></div></div>
<div class="fr"><div><label>Password</label><input type="password" name="pw" required
 autocomplete="current-password"></div></div>
<button class="btn block lg" type="submit">Log in</button></form>
<p class="small mut center" style="margin-top:14px">Just bought a policy? Your account is
created from the confirmation page.</p></div></div></section>""",
        me(request), title="Log in — Policy Store"))


@app.post("/login")
def login_post(request: Request, email: str = Form(...), pw: str = Form(...),
               next: str = Form("/account")):
    with closing(db()) as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not u or not check_pw(pw, u["pw"]):
        return RedirectResponse("/login?err=That+email+and+password+don%27t+match", status_code=303)
    request.session["uid"] = u["id"]
    if u["must_change"]:
        return RedirectResponse("/change-password", status_code=303)
    return RedirectResponse(next or "/account", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/change-password", response_class=HTMLResponse)
def chpw_get(request: Request, err: str = ""):
    u = me(request)
    if not u:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(shell(f"""<section class="wrap pad"><div style="max-width:430px;
margin:0 auto"><div class="panel"><h1 style="font-size:26px;margin-bottom:8px">Set your
password</h1>{f'<div class="err">{e(err)}</div>' if err else ''}
{'<div class="warn">This account is on a temporary password. Choose your own to continue.</div>' if u['must_change'] else ''}
<form method="post" action="/change-password">
<div class="fr"><div><label>Current password</label><input type="password" name="old"
 required></div></div>
<div class="fr"><div><label>New password</label><input type="password" name="pw" required
 minlength="8"></div></div>
<button class="btn block lg" type="submit">Save</button></form></div></div></section>""",
        u, title="Change password"))


@app.post("/change-password")
def chpw_post(request: Request, old: str = Form(...), pw: str = Form(...)):
    u = me(request)
    if not u:
        return RedirectResponse("/login", status_code=303)
    if not check_pw(old, u["pw"]):
        return RedirectResponse("/change-password?err=Current+password+is+wrong", status_code=303)
    if len(pw) < 8:
        return RedirectResponse("/change-password?err=Use+at+least+8+characters", status_code=303)
    with closing(db()) as c:
        c.execute("UPDATE users SET pw=?,must_change=0 WHERE id=?", (hash_pw(pw), u["id"]))
        c.commit()
    return RedirectResponse("/admin" if u["role"] == "admin" else "/account", status_code=303)


@app.get("/account", response_class=HTMLResponse)
def account(request: Request, u=Depends(require_user), ok: str = ""):
    with closing(db()) as c:
        pols = [dict(r) for r in c.execute(
            """SELECT p.*, q.product, q.benefit, q.monthly, q.state, q.token
               FROM policies p LEFT JOIN quotes q ON q.id=p.quote_id
               WHERE p.user_id=? ORDER BY p.created DESC""", (u["id"],))]
        qs = [dict(r) for r in c.execute(
            "SELECT * FROM quotes WHERE user_id=? ORDER BY created DESC LIMIT 10", (u["id"],))]
    cards = ""
    for p in pols:
        prods = " and ".join(P.PRODUCTS[x]["short"] for x in (p["product"] or "").split("+")
                             if x in P.PRODUCTS) or "Travel 365"
        in_look = p["free_look_ends"] and p["free_look_ends"] >= date.today().isoformat()
        cards += f"""<div class="panel" style="margin-bottom:16px">
<div style="display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap">
<div><div class="kicker">Policy {e(p['policy_no'])}</div>
<h3 style="margin:5px 0">{e(prods)}</h3>
<p class="mut small">{money(p['benefit'], False) if p['benefit'] else ''} ·
{e(P.STATE_NAMES.get(p['state'], p['state'] or ''))} ·
<span class="tag {'ok' if p['status'] == 'active' else 'warn'}">{e(p['status'])}</span></p></div>
<div style="text-align:right"><div style="font-size:24px;font-weight:850;color:var(--navy)">
{money(p['monthly'])}</div><div class="small mut">per month</div></div></div>
<hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
{'<span class="tag ok">Free look until ' + e(p['free_look_ends']) + '</span>' if in_look else
 '<span class="tag off">Free look ended ' + e(p['free_look_ends'] or '') + '</span>'}
{'<form method="post" action="/account/cancel" style="display:inline"><input type="hidden" name="policy_id" value="' + str(p['id']) + '"><button class="btn ghost sm" type="submit">Cancel within free look</button></form>' if in_look and p['status'] == 'active' else ''}
<a class="btn ghost sm" href="/account/billing">Billing</a></div></div>"""
    qrows = "".join(f"""<tr><td>{e(q['product'])}</td><td>{money(q['monthly'])}</td>
<td>{e(q['status'])}</td><td class="small mut">
{datetime.fromtimestamp(q['created']).strftime('%d %b %Y')}</td>
<td><a href="/checkout/{e(q['token'])}">Open</a></td></tr>""" for q in qs)
    return HTMLResponse(shell(f"""<section class="wrap pad">
<h1>Your account</h1>
<p class="lead" style="margin-bottom:22px">{e(u['email'])}</p>
{f'<div class="okmsg">{e(ok)}</div>' if ok else ''}
{cards or '<div class="panel"><p class="mut">No policies yet. <a href="/quote">Get a quote</a>.</p></div>'}
{f'<div class="panel" style="margin-top:16px"><h3 style="margin-bottom:10px">Recent quotes</h3><div class="tablewrap"><table class="data"><tr><th>Product</th><th>Monthly</th><th>Status</th><th>When</th><th></th></tr>{qrows}</table></div></div>' if qs else ''}
<p style="margin-top:20px"><a class="btn ghost" href="/change-password">Change password</a>
<a class="btn ghost" href="/quote?restart=1">Get another quote</a></p>
</section>""", u, title="My account — Policy Store", canon="/account"))


@app.post("/account/cancel")
def account_cancel(request: Request, policy_id: int = Form(...), u=Depends(require_user)):
    with closing(db()) as c:
        p = c.execute("SELECT * FROM policies WHERE id=? AND user_id=?",
                      (policy_id, u["id"])).fetchone()
        if not p:
            raise HTTPException(404, "Not your policy")
        if p["free_look_ends"] and p["free_look_ends"] < date.today().isoformat():
            return RedirectResponse("/account?ok=That+policy+is+past+its+free+look+period.",
                                    status_code=303)
        c.execute("UPDATE policies SET status='cancelled_free_look' WHERE id=?", (policy_id,))
        c.commit()
    log("free_look_cancel", f"policy {p['policy_no']}", p["quote_id"])
    send_email(OWNER_EMAIL, f"[Policy Store] Free-look cancellation — {p['policy_no']}",
               f"<p>{e(u['email'])} cancelled {e(p['policy_no'])} inside the 30-day free look.</p>")
    return RedirectResponse("/account?ok=Cancelled+within+the+free+look.+Premium+will+be+"
                            "refunded+in+full.", status_code=303)


@app.get("/account/billing", response_class=HTMLResponse)
def billing(request: Request, u=Depends(require_user)):
    cfg = setting("tpa", {}) or {}
    portal = cfg.get("billing_url")
    return HTMLResponse(shell(f"""<section class="wrap pad"><div class="narrow">
<h1>Billing</h1>
<p class="lead">Premium is collected by the third-party administrator, not by Policy Store — so
your card and bank details live with them, never here.</p>
<div class="panel" style="margin-top:18px">
{'<p>Manage your payment method, change the billing date or view receipts in the administrator portal.</p><p style="margin-top:14px"><a class="btn" href="' + e(portal) + '" target="_blank" rel="noopener">Open the billing portal →</a></p>' if portal else '<div class="warn">The administrator billing portal is not connected yet. Once the TPA endpoints are loaded in Admin → Integrations, this button opens their portal directly.</div><p class="mut">In the meantime, call ' + e(C.PHONE) + ' and we will handle any billing change for you.</p>'}
</div>
<div class="panel" style="margin-top:16px"><h3>Cancelling</h3>
<p class="mut">Inside the first thirty days, cancel from <a href="/account">your account</a> for a
full refund of premium, provided no claim has been filed. After that, cancellation follows the
terms in your policy documents.</p></div>
</div></section>""", u, title="Billing — Policy Store", canon="/account/billing"))


# ================================================================== admin ====
def admin_shell(u, active, inner, title):
    items = [("/admin", "📊 Overview", "home"), ("/admin/quotes", "📇 Quotes & policies", "quotes"),
             ("/admin/integrations", "🔌 Integrations", "int"),
             ("/admin/moneywords", "📞 Money words", "mw"),
             ("/admin/rates", "💵 Rates", "rates"),
             ("/admin/activity", "🧾 Activity log", "act"),
             ("/admin/gate", "🔒 Demo gate", "gate")]
    nav = "".join(f'<a class="{"on" if k == active else ""}" href="{h}">{t}</a>'
                  for h, t, k in items)
    return shell(f"""<section class="wrap pad-s"><div class="dash">
<div class="side"><div style="padding:6px 10px 12px;border-bottom:1px solid var(--line);
margin-bottom:8px"><b style="color:var(--navy)">{e(u['email'])}</b>
<div class="small mut">Administrator</div></div>{nav}
<a href="/logout" style="color:var(--soft)">↩︎ Sign out</a></div>
<div>{inner}</div></div></section>""", u, title=f"{title} — Admin")


@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, u=Depends(require_admin)):
    with closing(db()) as c:
        n = lambda s, *a: c.execute(s, a).fetchone()[0]
        stats = [("Quotes", n("SELECT COUNT(*) FROM quotes")),
                 ("Texted", n("SELECT COUNT(*) FROM quotes WHERE status IN ('texted','enrolling','enrolled')")),
                 ("Enrolled", n("SELECT COUNT(*) FROM quotes WHERE status='enrolled'")),
                 ("Policies", n("SELECT COUNT(*) FROM policies")),
                 ("Link clicks", n("SELECT COALESCE(SUM(hits),0) FROM links")),
                 ("Calls tracked", n("SELECT COUNT(*) FROM calls")),
                 ("Accounts", n("SELECT COUNT(*) FROM users")),
                 ("Events", n("SELECT COUNT(*) FROM events"))]
        recent = [dict(r) for r in c.execute(
            "SELECT * FROM quotes ORDER BY created DESC LIMIT 8")]
    tiles = "".join(f'<div class="stat"><div class="n">{v}</div><div class="l">{e(k)}</div></div>'
                    for k, v in stats)
    pp = setting("pingpost", {}) or {}
    sms = setting("sms", {}) or {}
    tpa = setting("tpa", {}) or {}
    def badge(ok, label):
        return (f'<span class="tag ok">{label} connected</span>' if ok
                else f'<span class="tag warn">{label} simulated</span>')
    rows = "".join(f"""<tr><td><b>{e((q['first'] or '') + ' ' + (q['last'] or ''))}</b><br>
<span class="small mut">{e(q['email'] or '')}</span></td>
<td>{e(q['product'])}</td><td>{money(q['monthly'])}</td><td>{e(q['state'])}</td>
<td><span class="tag {'ok' if q['status'] == 'enrolled' else 'off'}">{e(q['status'])}</span></td>
<td class="small mut">{datetime.fromtimestamp(q['created']).strftime('%d %b %H:%M')}</td></tr>"""
                   for q in recent)
    return HTMLResponse(admin_shell(u, "home", f"""
<h1>Overview</h1>
<p class="lead" style="margin-bottom:18px">The whole agency, from here.</p>
<div class="grid g4" style="margin-bottom:20px">{tiles}</div>
<div class="panel" style="margin-bottom:18px"><h3 style="margin-bottom:10px">Connections</h3>
<p>{badge(pp.get('post_url'), 'Ping-post')} {badge(sms.get('provider'), 'SMS')}
{badge(tpa.get('enroll_url'), 'Administrator')}
{'<span class="tag warn">Demo rates</span>' if rates_are_demo() else '<span class="tag ok">Carrier rates loaded</span>'}
{'<span class="tag red">Demo gate ON</span>' if setting('gate_enabled', True) else '<span class="tag ok">Site public</span>'}</p>
<p class="hint">Anything marked <i>simulated</i> still runs the full flow and records the exact
payload it would have sent — nothing silently no-ops.</p></div>
<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center">
<h3>Latest quotes</h3><a class="btn ghost sm" href="/admin/quotes">See all</a></div>
<div class="tablewrap" style="margin-top:10px"><table class="data">
<tr><th>Who</th><th>Product</th><th>Monthly</th><th>State</th><th>Status</th><th>When</th></tr>
{rows or '<tr><td colspan=6 class="mut">Nothing yet.</td></tr>'}</table></div></div>
""", "Overview"))


@app.get("/admin/integrations", response_class=HTMLResponse)
def admin_int(request: Request, u=Depends(require_admin), ok: str = ""):
    pp = setting("pingpost", {}) or {}
    sms = setting("sms", {}) or {}
    tpa = setting("tpa", {}) or {}
    mapping = json.dumps(pp.get("mapping") or {}, indent=1)
    static = json.dumps(pp.get("static") or {}, indent=1)
    sample = json.dumps({
        "lead_id": "Xk29fQ", "type": "post", "first_name": "Jane", "last_name": "Doe",
        "email": "jane@example.com", "phone": "5125550143", "state": "TX", "age": 42,
        "product": "add+ame", "benefit": 100000, "deductible": 100, "tier": "spouse",
        "monthly_premium": 38.42, "annual_premium": 461.04, "target_premium": 45.0,
        "rates_are_demo": True, "source": "policystore.com"}, indent=1)
    return HTMLResponse(admin_shell(u, "int", f"""
<h1>Integrations</h1>
<p class="lead">Drop the ping-post and administrator details in here. Nothing else has to
change — the flow already calls all of it.</p>
{f'<div class="okmsg">{e(ok)}</div>' if ok else ''}

<form method="post" action="/admin/integrations">
<div class="panel" style="margin-top:18px"><h3>Ping-post</h3>
<p class="mut small">A <b>ping</b> fires when a quote is texted; a <b>post</b> fires when the
customer enrols. Leave a URL blank and that step is simulated and logged instead.</p>
<div class="fr two" style="margin-top:14px">
<div><label>Ping URL</label><input type="url" name="ping_url" value="{e(pp.get('ping_url',''))}"
 placeholder="https://buyer.example.com/ping"></div>
<div><label>Post URL</label><input type="url" name="post_url" value="{e(pp.get('post_url',''))}"
 placeholder="https://buyer.example.com/post"></div></div>
<div class="fr"><div><label>Headers (JSON)</label>
<textarea name="pp_headers" placeholder='{{"Authorization":"Bearer …"}}'>{e(pp.get('headers',''))}</textarea></div></div>
<div class="fr two">
<div><label>Field mapping (JSON) — ours → theirs</label>
<textarea name="pp_mapping">{e(mapping)}</textarea>
<p class="hint">e.g. <code>{{"first_name":"fname","monthly_premium":"premium"}}</code></p></div>
<div><label>Static fields (JSON) — always sent</label>
<textarea name="pp_static">{e(static)}</textarea>
<p class="hint">e.g. <code>{{"vendor_id":"1234","campaign":"ps-add"}}</code></p></div></div>
<details><summary class="small mut" style="cursor:pointer">What we send by default</summary>
<pre style="margin-top:10px">{e(sample)}</pre></details>
</div>

<div class="panel" style="margin-top:16px"><h3>SMS delivery</h3>
<p class="mut small">How the enrolment link reaches the customer's phone.</p>
<div class="fr two" style="margin-top:14px">
<div><label>Provider</label><select name="sms_provider">
<option value="">— simulated (log only) —</option>
<option value="core" {'selected' if sms.get('provider') == 'core' else ''}>CORE / Zapmail</option>
<option value="webhook" {'selected' if sms.get('provider') == 'webhook' else ''}>Generic webhook</option>
</select></div>
<div><label>Webhook URL</label><input type="url" name="sms_url" value="{e(sms.get('url',''))}"
 placeholder="https://sms.example.com/send"></div></div>
<div class="fr"><div><label>Headers (JSON)</label>
<textarea name="sms_headers">{e(sms.get('headers',''))}</textarea></div></div></div>

<div class="panel" style="margin-top:16px"><h3>Third-party administrator</h3>
<p class="mut small">Where enrolments go and where the customer manages billing.</p>
<div class="fr two" style="margin-top:14px">
<div><label>Enrolment / payment URL</label><input type="url" name="tpa_enroll"
 value="{e(tpa.get('enroll_url',''))}" placeholder="https://tpa.example.com/api/enroll"></div>
<div><label>Customer billing portal</label><input type="url" name="tpa_billing"
 value="{e(tpa.get('billing_url',''))}" placeholder="https://tpa.example.com/portal"></div></div>
<div class="fr two">
<div><label>Acceptance post-back URL (theirs → us)</label>
<input value="{SITE}/api/tpa/postback" readonly style="background:#f3f7fb"></div>
<div><label>Post-back shared secret</label><input name="tpa_secret"
 value="{e(tpa.get('secret',''))}" placeholder="generated if left blank"></div></div>
<div class="fr"><div><label>Headers (JSON)</label>
<textarea name="tpa_headers">{e(tpa.get('headers',''))}</textarea></div></div></div>

<p style="margin-top:18px"><button class="btn lg" type="submit">Save integrations</button></p>
</form>

<div class="panel" style="margin-top:16px"><h3>Test it</h3>
<p class="mut small">Fires a real request against whatever is configured, using a dummy record,
and writes the result to the activity log.</p>
<p style="margin-top:12px">
<a class="btn ghost" href="/admin/test/ping">Test ping</a>
<a class="btn ghost" href="/admin/test/post">Test post</a>
<a class="btn ghost" href="/admin/test/sms">Test SMS</a>
<a class="btn ghost" href="/admin/test/tpa">Test administrator</a></p></div>
""", "Integrations"))


@app.post("/admin/integrations")
async def admin_int_save(request: Request, u=Depends(require_admin)):
    f = await request.form()
    g = lambda k: (f.get(k) or "").strip()
    def js(k):
        try:
            return json.loads(g(k)) if g(k) else {}
        except Exception:
            return {}
    set_setting("pingpost", {"ping_url": g("ping_url"), "post_url": g("post_url"),
                             "headers": g("pp_headers"), "mapping": js("pp_mapping"),
                             "static": js("pp_static")})
    set_setting("sms", {"provider": g("sms_provider"), "url": g("sms_url"),
                        "headers": g("sms_headers")})
    set_setting("tpa", {"enroll_url": g("tpa_enroll"), "billing_url": g("tpa_billing"),
                        "secret": g("tpa_secret") or secrets.token_urlsafe(24),
                        "headers": g("tpa_headers")})
    log("settings", "integrations updated")
    return RedirectResponse("/admin/integrations?ok=Saved.+The+flow+uses+these+immediately.",
                            status_code=303)


def _dummy_quote():
    return {"id": 0, "token": "TESTQUOTE", "first": "Test", "last": "Record",
            "email": "test@policystore.com", "phone": "5555550100", "state": "TX", "age": 42,
            "product": "add+ame", "benefit": 100000, "deductible": 100, "tier": "single",
            "monthly": 38.42, "annual": 461.04, "target_premium": 45.0, "demo_rates": 1,
            "created": time.time()}


@app.get("/admin/test/{what}")
def admin_test(request: Request, what: str, u=Depends(require_admin)):
    d = _dummy_quote()
    if what in ("ping", "post"):
        ok, _ = ping_post(d, what)
    elif what == "sms":
        ok = send_sms("5555550100", "Policy Store test message — ignore.", None)
    elif what == "tpa":
        ok = tpa_submit(d, "PS-TEST")
    else:
        raise HTTPException(404, "Unknown test")
    msg = {True: "succeeded", False: "failed — see the activity log",
           None: "ran in simulation (nothing configured yet)"}[ok]
    return RedirectResponse(f"/admin/integrations?ok=Test+{what}+{msg.replace(' ', '+')}",
                            status_code=303)


@app.post("/api/tpa/postback")
async def tpa_postback(request: Request):
    """Where the administrator confirms acceptance. Kept deliberately forgiving
    about field names — every TPA spells these differently."""
    try:
        body = await request.json()
    except Exception:
        body = dict(await request.form())
    secret = (setting("tpa", {}) or {}).get("secret")
    given = request.headers.get("x-ps-secret") or body.get("secret")
    if secret and given != secret:
        log("tpa_postback", "rejected — bad secret", None, body, False)
        raise HTTPException(401, "Bad secret")
    ref = body.get("quote_ref") or body.get("reference") or body.get("lead_id")
    status = (body.get("status") or "accepted").lower()
    policy_no = body.get("policy_number") or body.get("policy_no")
    with closing(db()) as c:
        q = c.execute("SELECT * FROM quotes WHERE token=?", (ref,)).fetchone()
        if q:
            c.execute("UPDATE policies SET status=?, tpa_ref=? WHERE quote_id=?",
                      ("active" if status in ("accepted", "active", "issued") else status,
                       policy_no or "", q["id"]))
            c.commit()
    log("tpa_postback", f"{ref} → {status}", q["id"] if q else None, body, True)
    return {"ok": True, "received": ref, "status": status}


@app.get("/admin/rates", response_class=HTMLResponse)
def admin_rates(request: Request, u=Depends(require_admin), ok: str = ""):
    current = json.dumps(rates(), indent=1)
    return HTMLResponse(admin_shell(u, "rates", f"""
<h1>Rates</h1>
<p class="lead">Travel 365 pricing is real and comes straight from the carrier sheet. The three
accident products are quoted from the table below.</p>
{f'<div class="okmsg">{e(ok)}</div>' if ok else ''}
{'<div class="warn"><b>Demo rates are loaded.</b> The workbook we were given contained benefit amounts, tiers and age bands but no premium rates for AD&amp;D, Accident Medical or Critical Illness. Everything below is placeholder pricing so the flow can be demonstrated. Every quote built from it is stamped <code>rates_are_demo: true</code> — on screen, in the quote record, and in the ping-post payload.</div>' if rates_are_demo() else '<div class="okmsg"><b>Carrier rates loaded.</b> Quotes are no longer flagged as demo.</div>'}
<div class="panel" style="margin-top:16px"><h3>How the table works</h3>
<ul class="mut" style="margin:10px 0 0 20px;font-size:14.5px">
<li style="margin-bottom:6px"><code>add</code>, <code>ame</code>, <code>ci</code> — monthly
premium per <b>$1,000</b> of benefit, keyed by the product's own age band.</li>
<li style="margin-bottom:6px"><code>ame_deductible_factor</code> — multiplier applied to the AME
rate for each filed deductible.</li>
<li style="margin-bottom:6px"><code>child_load</code> — proportion of the base rate added for
1–4+ children.</li>
<li style="margin-bottom:6px"><code>_demo</code> — set to <code>false</code> when these are the
carrier's real numbers, and the warnings disappear everywhere.</li></ul></div>
<form method="post" action="/admin/rates" style="margin-top:16px">
<div class="panel"><label>rates.json</label>
<textarea name="rates" style="min-height:420px;font-family:ui-monospace,Menlo,monospace;
font-size:12.5px">{e(current)}</textarea>
<p class="hint">Paste the carrier table over this and save. Malformed JSON is rejected rather
than half-applied.</p>
<button class="btn lg" style="margin-top:12px" type="submit">Save rates</button></div></form>
""", "Rates"))


@app.post("/admin/rates")
def admin_rates_save(request: Request, rates: str = Form(...), u=Depends(require_admin)):
    try:
        parsed = json.loads(rates)
        assert isinstance(parsed, dict)
    except Exception as ex:
        return RedirectResponse(f"/admin/rates?ok=Rejected+—+that+is+not+valid+JSON",
                                status_code=303)
    with open(RATES_FILE, "w") as f:
        json.dump(parsed, f, indent=1)
    log("settings", f"rates updated (demo={parsed.get('_demo', True)})")
    return RedirectResponse("/admin/rates?ok=Rates+saved.", status_code=303)


@app.get("/admin/moneywords", response_class=HTMLResponse)
def admin_mw(request: Request, u=Depends(require_admin), ok: str = ""):
    cfg = setting("moneywords", {}) or {}
    with closing(db()) as c:
        calls = [dict(r) for r in c.execute("SELECT * FROM calls ORDER BY ts DESC LIMIT 60")]
        counts = {r["moneyword"]: r["n"] for r in c.execute(
            "SELECT moneyword, COUNT(*) n FROM calls GROUP BY moneyword")}
    rows = ""
    for word, prod in P.MONEYWORDS:
        num = (cfg.get("numbers") or {}).get(word, "")
        rows += f"""<tr><td><b>{e(word)}</b></td>
<td><span class="tag ok">{e(P.PRODUCTS[prod]['short'] if prod in P.PRODUCTS else 'Travel 365')}</span></td>
<td><input name="num__{e(word)}" value="{e(num)}" placeholder="tracking number"
 style="padding:7px 10px;font-size:13.5px"></td>
<td class="center">{counts.get(word, 0)}</td></tr>"""
    clog = "".join(f"""<tr><td class="small">{datetime.fromtimestamp(c_['ts']).strftime('%d %b %H:%M')}</td>
<td>{e(c_['caller'] or '')}</td><td><b>{e(c_['moneyword'] or '')}</b></td>
<td>{e(c_['product'] or '')}</td><td>{e(c_['state'] or '')}</td>
<td>{e(c_['disposition'] or '')}</td></tr>""" for c_ in calls)
    return HTMLResponse(admin_shell(u, "mw", f"""
<h1>Money words</h1>
<p class="lead">Phrases that identify what an inbound caller actually wants. Give each one a
tracking number and the phone system attributes the call to the right product before the agent
says a word.</p>
{f'<div class="okmsg">{e(ok)}</div>' if ok else ''}
<div class="panel" style="margin-top:16px">
<h3>Feed from your phone system</h3>
<p class="mut small">Have the platform POST here when a money word triggers. It records the
call, maps it to a product, and returns what the agent should open with.</p>
<pre style="margin-top:10px">POST {SITE}/api/call
{{"caller":"+15125550143","moneyword":"critical illness","state":"TX","source":"keywordcalls"}}</pre>
</div>
<form method="post" action="/admin/moneywords">
<div class="panel" style="margin-top:16px"><h3>Words and routing</h3>
<div class="tablewrap" style="margin-top:10px"><table class="data">
<tr><th>Money word</th><th>Routes to</th><th>Tracking number</th><th>Calls</th></tr>
{rows}</table></div>
<button class="btn" style="margin-top:14px" type="submit">Save numbers</button></div></form>
<div class="panel" style="margin-top:16px"><h3>Call log</h3>
<div class="tablewrap" style="margin-top:10px"><table class="data">
<tr><th>When</th><th>Caller</th><th>Money word</th><th>Product</th><th>State</th>
<th>Disposition</th></tr>
{clog or '<tr><td colspan=6 class="mut">No calls tracked yet.</td></tr>'}</table></div>
<form method="post" action="/api/call" style="margin-top:14px;display:flex;gap:9px;flex-wrap:wrap">
<input name="caller" placeholder="+1 512 555 0143" style="max-width:190px">
<select name="moneyword" style="max-width:230px">
{"".join(f'<option value="{e(w)}">{e(w)}</option>' for w, _ in P.MONEYWORDS)}</select>
<input name="state" placeholder="TX" style="max-width:90px">
<button class="btn ghost sm" type="submit">Simulate a call</button></form></div>
""", "Money words"))


@app.post("/admin/moneywords")
async def admin_mw_save(request: Request, u=Depends(require_admin)):
    f = await request.form()
    nums = {k[5:]: v.strip() for k, v in f.items() if k.startswith("num__") and v.strip()}
    set_setting("moneywords", {"numbers": nums})
    return RedirectResponse("/admin/moneywords?ok=Saved.", status_code=303)


@app.post("/api/call")
async def api_call(request: Request):
    """Inbound call tracking. Accepts JSON or a form post so the phone platform,
    a webhook, or the admin's own simulate button can all use it."""
    try:
        body = await request.json()
    except Exception:
        body = dict(await request.form())
    word = (body.get("moneyword") or body.get("keyword") or "").lower().strip()
    product = next((p for w, p in P.MONEYWORDS if w == word), None)
    if not product:
        product = next((p for w, p in P.MONEYWORDS if w in word or word in w), None)
    with closing(db()) as c:
        c.execute("""INSERT INTO calls(caller,moneyword,product,source,state,disposition,ts)
                     VALUES(?,?,?,?,?,?,?)""",
                  (body.get("caller"), word, product, body.get("source", "api"),
                   (body.get("state") or "").upper(), "routed", time.time()))
        c.commit()
    log("call", f"{word} → {product}", None, body, True)
    opener = {"add": "AD&D — I can quote that in about a minute.",
              "ame": "Accident Medical — let's see what your deductible looks like.",
              "ci": "Critical Illness — I'll need your age and state.",
              "t365": "Travel 365 — annual cover, real published rates."}.get(product, "")
    if request.headers.get("accept", "").startswith("application/json") or \
            "application/json" in request.headers.get("content-type", ""):
        return {"ok": True, "moneyword": word, "product": product, "open_with": opener,
                "quote_url": f"{SITE}/quote?want={product or ''}"}
    return RedirectResponse("/admin/moneywords?ok=Call+recorded.", status_code=303)


@app.get("/admin/quotes", response_class=HTMLResponse)
def admin_quotes(request: Request, u=Depends(require_admin)):
    with closing(db()) as c:
        qs = [dict(r) for r in c.execute("SELECT * FROM quotes ORDER BY created DESC LIMIT 300")]
        pols = {r["quote_id"]: dict(r) for r in c.execute("SELECT * FROM policies")}
    rows = "".join(f"""<tr>
<td><b>{e((q['first'] or '') + ' ' + (q['last'] or '')) or '—'}</b><br>
<span class="small mut">{e(q['email'] or '')} {('· ' + e(q['phone'])) if q['phone'] else ''}</span></td>
<td>{e(q['product'])}<br><span class="small mut">{money(q['benefit'], False) if q['benefit'] else ''}</span></td>
<td>{money(q['monthly'])}<br><span class="small mut">{e(q['state'])} · age {q['age']}</span></td>
<td><span class="tag {'ok' if q['status'] == 'enrolled' else 'off'}">{e(q['status'])}</span>
{'<br><span class="small mut">' + e(pols[q['id']]['policy_no']) + '</span>' if q['id'] in pols else ''}</td>
<td>{'<span class="tag warn">demo</span>' if q['demo_rates'] else '<span class="tag ok">real</span>'}</td>
<td class="small mut">{datetime.fromtimestamp(q['created']).strftime('%d %b %H:%M')}</td>
<td><a href="/checkout/{e(q['token'])}">open</a></td></tr>""" for q in qs)
    return HTMLResponse(admin_shell(u, "quotes", f"""
<h1>Quotes &amp; policies</h1>
<p class="lead">{len(qs)} quote{'s' if len(qs) != 1 else ''} · {len(pols)} polic{'ies' if len(pols) != 1 else 'y'}</p>
<div class="panel" style="margin-top:16px"><div class="tablewrap"><table class="data">
<tr><th>Customer</th><th>Product</th><th>Premium</th><th>Status</th><th>Rates</th><th>When</th>
<th></th></tr>{rows or '<tr><td colspan=7 class="mut">Nothing yet.</td></tr>'}</table></div>
</div>""", "Quotes"))


@app.get("/admin/activity", response_class=HTMLResponse)
def admin_activity(request: Request, u=Depends(require_admin), kind: str = ""):
    sql = "SELECT * FROM events" + (" WHERE kind=?" if kind else "") + " ORDER BY ts DESC LIMIT 200"
    with closing(db()) as c:
        evs = [dict(r) for r in c.execute(sql, (kind,) if kind else ())]
        kinds = [r[0] for r in c.execute("SELECT DISTINCT kind FROM events ORDER BY kind")]
    pills = '<a class="pill" href="/admin/activity">All</a>' + "".join(
        f'<a class="pill" href="/admin/activity?kind={k}">{e(k)}</a>' for k in kinds)
    rows = "".join(f"""<tr><td class="small mut">
{datetime.fromtimestamp(ev['ts']).strftime('%d %b %H:%M:%S')}</td>
<td><b>{e(ev['kind'])}</b></td><td>{e(ev['detail'] or '')}</td>
<td>{'<span class="tag ok">ok</span>' if ev['ok'] else ('<span class="tag warn">simulated</span>' if ev['ok'] is None else '<span class="tag red">failed</span>')}</td>
<td>{'<details><summary class="small">payload</summary><pre style="max-width:520px">' + e(json.dumps(json.loads(ev['payload']), indent=1)[:2500]) + '</pre></details>' if ev['payload'] else ''}</td>
</tr>""" for ev in evs)
    return HTMLResponse(admin_shell(u, "act", f"""
<h1>Activity log</h1>
<p class="lead">Every outbound call the system makes, with the exact payload — including the ones
that ran in simulation.</p>
<div style="margin:14px 0">{pills}</div>
<div class="panel"><div class="tablewrap"><table class="data">
<tr><th>When</th><th>Event</th><th>Detail</th><th>Result</th><th>Payload</th></tr>
{rows or '<tr><td colspan=5 class="mut">Nothing logged yet.</td></tr>'}</table></div></div>
""", "Activity"))


@app.get("/admin/gate", response_class=HTMLResponse)
def admin_gate(request: Request, u=Depends(require_admin), ok: str = ""):
    on = setting("gate_enabled", True)
    pw = setting("gate_password", DEFAULT_GATE_PASSWORD)
    return HTMLResponse(admin_shell(u, "gate", f"""
<h1>Demo gate</h1>
<p class="lead">One password in front of the whole site. Turn it off and policystore.com becomes
a public landing page immediately.</p>
{f'<div class="okmsg">{e(ok)}</div>' if ok else ''}
<div class="panel" style="margin-top:16px">
<p>Status: {'<span class="tag red">ON — the site is password protected</span>' if on else '<span class="tag ok">OFF — the site is public</span>'}</p>
<form method="post" action="/admin/gate" style="margin-top:16px">
<div class="fr two">
<div><label>Demo password</label><input name="pw" value="{e(pw)}"></div>
<div><label>Protection</label><select name="enabled">
<option value="1" {'selected' if on else ''}>On — require the password</option>
<option value="0" {'selected' if not on else ''}>Off — site is public</option>
</select></div></div>
<button class="btn" type="submit">Save</button></form></div>
<div class="panel" style="margin-top:16px"><h3>One thing worth knowing</h3>
<p class="mut">You mentioned turning the protection off in the GoDaddy account. GoDaddy holds
the domain registration and points <code>policystore.com</code> at this server, but it cannot
see or control this application — so a switch there would not reach the gate. The toggle above
is the one that works, and it takes effect on the next page load with no deploy.</p>
<p class="mut" style="margin-top:10px">If you would rather it lived somewhere else entirely
— a GoDaddy-hosted holding page in front, or an nginx password — say the word and I'll move
it.</p></div>
""", "Demo gate"))


@app.post("/admin/gate")
def admin_gate_save(request: Request, pw: str = Form(...), enabled: str = Form("1"),
                    u=Depends(require_admin)):
    set_setting("gate_password", pw.strip() or DEFAULT_GATE_PASSWORD)
    set_setting("gate_enabled", enabled == "1")
    log("settings", f"demo gate {'enabled' if enabled == '1' else 'disabled'}")
    return RedirectResponse("/admin/gate?ok=Saved.", status_code=303)


@app.get("/healthz")
def healthz():
    with closing(db()) as c:
        n = c.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
    return {"ok": True, "quotes": n, "gate": bool(setting("gate_enabled", True)),
            "demo_rates": rates_are_demo(), "states_live": len(P.LIVE)}


# ================================================================== boot =====
def bootstrap():
    init_db()
    with closing(db()) as c:
        if not c.execute("SELECT 1 FROM users WHERE email=?", (GOD_EMAIL,)).fetchone():
            c.execute("""INSERT INTO users(email,pw,role,first,last,must_change,created)
                         VALUES(?,?,'admin','Jeff','Cline',1,?)""",
                      (GOD_EMAIL, hash_pw(TEMP_PASSWORD), time.time()))
            c.commit()
    if setting("gate_enabled") is None:
        set_setting("gate_enabled", True)
    if setting("gate_password") is None:
        set_setting("gate_password", DEFAULT_GATE_PASSWORD)
    if not os.path.exists(RATES_FILE):
        with open(RATES_FILE, "w") as f:
            json.dump(DEMO_RATES, f, indent=1)


bootstrap()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8400")))
