#!/usr/bin/env python3
"""
websitedowncheckers.com — uptime monitoring as a service.

Accounts, multiple sites per account, unlimited alert recipients per site,
and an owner-side admin console. Stripe is wired but inert until keys exist:
signups land as 'trial' rather than being blocked, so the product is usable
and testable before billing is switched on.
"""
import hashlib, hmac, html, json, os, re, secrets, sqlite3, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tiers import PLANS, ORDER, COUPONS, plan as tier_plan
from contextlib import closing
from http import HTTPStatus

from fastapi import FastAPI, Form, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "downcheck.db")
SECRET_FILE = os.path.join(BASE, ".session_secret")
e = html.escape

OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "jeff.cline@me.com")
CORE = "https://medigap.plus"
CORE_KEY = os.environ.get("CORE_KEY", "")
CORE_SECRET = os.environ.get("CORE_SECRET", "")
STRIPE_PK = os.environ.get("STRIPE_PK", "")
STRIPE_SK = os.environ.get("STRIPE_SK", "")
PRICE = "9"


# ---------- storage ----------
def db():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with closing(db()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS accounts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL, company TEXT, pw_hash TEXT NOT NULL,
            salt TEXT NOT NULL, created REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'trial',
            plan TEXT NOT NULL DEFAULT 'starter',
            coupon TEXT,
            stripe_customer TEXT, stripe_sub TEXT, is_owner INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sites(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL, url TEXT NOT NULL, label TEXT,
            active INTEGER DEFAULT 1, created REAL NOT NULL,
            last_up INTEGER, last_detail TEXT, last_checked REAL, since REAL);
        CREATE TABLE IF NOT EXISTS recipients(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL, email TEXT NOT NULL, created REAL NOT NULL,
            UNIQUE(site_id, email));
        CREATE TABLE IF NOT EXISTS incidents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL, started REAL NOT NULL, ended REAL,
            detail TEXT);
        CREATE INDEX IF NOT EXISTS idx_sites_acct ON sites(account_id);
        CREATE INDEX IF NOT EXISTS idx_rec_site ON recipients(site_id);
        """)
        for col, ddl in (("plan", "TEXT NOT NULL DEFAULT 'starter'"), ("coupon", "TEXT")):
            try:
                c.execute(f"ALTER TABLE accounts ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass          # already present
        c.commit()


def hash_pw(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=32).hex()


def core_email(to, subject, html_body):
    """Send via CORE. Its sender pool drops roughly 1 in 5, so retry."""
    if not (CORE_KEY and CORE_SECRET):
        return False
    import subprocess
    payload = json.dumps({"to": to, "subject": subject, "html": html_body})
    for i in range(4):
        try:
            p = subprocess.run(
                ["curl", "-sS", "--max-time", "25", "-X", "POST",
                 "-H", f"x-core-key: {CORE_KEY}", "-H", f"x-core-secret: {CORE_SECRET}",
                 "-H", "content-type: application/json", "-d", payload,
                 CORE + "/api/core/email"], capture_output=True, text=True, timeout=40)
            if json.loads(p.stdout).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(1.2 * (i + 1))
    return False


# ---------- app ----------
if os.path.exists(SECRET_FILE):
    SECRET = open(SECRET_FILE).read().strip()
else:
    SECRET = secrets.token_hex(32)
    open(SECRET_FILE, "w").write(SECRET)
    os.chmod(SECRET_FILE, 0o600)

app = FastAPI(title="Website Down Checkers")
app.add_middleware(SessionMiddleware, secret_key=SECRET, https_only=True, max_age=60 * 60 * 24 * 14)


def current(request: Request):
    return request.session.get("acct")


def require(request: Request):
    a = current(request)
    if not a:
        raise HTTPException(status_code=HTTPStatus.SEE_OTHER, headers={"Location": "/login"})
    return a


def require_owner(request: Request):
    a = require(request)
    with closing(db()) as c:
        r = c.execute("SELECT is_owner FROM accounts WHERE id=?", (a,)).fetchone()
    if not r or not r["is_owner"]:
        raise HTTPException(status_code=HTTPStatus.SEE_OTHER, headers={"Location": "/app"})
    return a


CSS = """
:root{--bg:#0b0d12;--panel:#141821;--line:#232936;--tx:#eef1f6;--mut:#98a1b3;
--acc:#ff5a1f;--ok:#2ea043;--bad:#e5484d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font:15.5px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
a{color:var(--acc)}
.top{border-bottom:1px solid var(--line);background:var(--panel)}
.top .in{max-width:1180px;margin:0 auto;padding:14px 24px;display:flex;align-items:center;gap:18px}
.brand{font-weight:800;text-decoration:none;color:var(--tx);font-size:16px}
.brand .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ok);
margin-right:7px}
nav{flex:1;display:flex;gap:18px}
nav a{color:var(--mut);text-decoration:none;font-size:14px;font-weight:600}
nav a.on,nav a:hover{color:var(--tx)}
.who{color:var(--mut);font-size:13px}
.wrap{max-width:1180px;margin:0 auto;padding:26px 24px 70px}
.btn{display:inline-block;background:var(--acc);color:#fff;text-decoration:none;font-weight:700;
padding:10px 18px;border-radius:9px;font-size:14.5px;border:0;cursor:pointer}
.btn.ghost{background:transparent;border:1px solid var(--line);color:var(--tx)}
.btn.sm{padding:6px 12px;font-size:13px}
h1{font-size:26px;letter-spacing:-.02em;margin:0 0 4px}
h2{font-size:19px;margin:26px 0 10px}
p.mut{color:var(--mut);margin:0 0 18px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);
border-radius:12px;overflow:hidden}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);
padding:11px 13px;border-bottom:1px solid var(--line)}
td{padding:11px 13px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
.lamp{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.lamp.green{background:var(--ok);box-shadow:0 0 0 3px rgba(46,160,67,.18)}
.lamp.red{background:var(--bad);box-shadow:0 0 0 3px rgba(229,72,77,.18)}
.lamp.grey{background:var(--mut);opacity:.5}
.mut{color:var(--mut)}.bad{color:var(--bad)}.ok{color:var(--ok)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:22px;
max-width:430px;margin:56px auto}
.card.wide{max-width:720px}
label{display:block;font-size:13px;color:var(--mut);margin:13px 0 5px;font-weight:600}
input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:9px;
background:var(--bg);color:var(--tx);font:inherit}
form.inline{display:flex;gap:9px;align-items:flex-end;flex-wrap:wrap}
form.inline label{margin-top:0}
form.inline>div{flex:1;min-width:190px}
.err{background:rgba(229,72,77,.12);border:1px solid var(--bad);color:var(--bad);
padding:9px 12px;border-radius:9px;font-size:13.5px;margin-bottom:10px}
.note{background:rgba(255,90,31,.09);border:1px solid var(--acc);padding:10px 13px;
border-radius:9px;font-size:13.5px;margin-bottom:16px}
.pill{display:inline-block;font-size:11px;padding:2px 8px;border-radius:999px;
border:1px solid currentColor;font-weight:700}
.tag{background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:3px 9px;
font-size:12.5px;display:inline-flex;align-items:center;gap:7px;margin:0 5px 5px 0}
.tag a{color:var(--mut);text-decoration:none;font-weight:700}
"""


def shell(body, acct=None, title="Website Down Checkers", owner=False, cur=""):
    nav = ""
    if acct:
        items = [("/app", "app", "Dashboard")]
        if owner:
            items.append(("/admin", "admin", "Customers"))
        nav = "".join(f'<a class="{"on" if k == cur else ""}" href="{h}">{l}</a>'
                      for h, k, l in items)
        right = f'<span class="who">{e(acct)}</span> <a class="btn ghost btn-sm" href="/logout">Sign out</a>'
    else:
        right = '<a class="btn ghost" href="/login">Log in</a> <a class="btn" href="/signup">Start</a>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>{CSS}</style></head><body>
<div class="top"><div class="in">
<a class="brand" href="/"><span class="dot"></span>Website Down Checkers</a>
<nav>{nav}</nav>{right}</div></div>
{body}</body></html>"""


# ---------- public ----------
@app.get("/", response_class=HTMLResponse)
def home():
    p = os.path.join(BASE, "index.html")
    if os.path.exists(p):
        return HTMLResponse(open(p).read())
    return HTMLResponse(shell('<div class="wrap"><h1>Website Down Checkers</h1></div>'))


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, err: str = ""):
    if current(request):
        return RedirectResponse("/app", 303)
    ee = f'<div class="err">{e(err)}</div>' if err else ""
    return HTMLResponse(shell(f"""<div class="card">
<h1>Start monitoring</h1>
<p class="mut">${PRICE}/month · unlimited recipients · cancel any time</p>{ee}
<form method="post" action="/signup">
<label>Work email</label><input type="email" name="email" required autofocus autocomplete="email">
<label>Company <span class="mut">(optional)</span></label><input name="company" autocomplete="organization">
<label>Password <span class="mut">(9+ characters)</span></label>
<input type="password" name="password" required autocomplete="new-password">
<label>Website to monitor</label><input name="site" placeholder="example.com" required>
<button class="btn" type="submit" style="width:100%;margin-top:18px">Create account</button>
</form>
<p class="mut" style="margin-top:16px;font-size:13px">Already have an account?
<a href="/login">Log in</a></p></div>""", title="Start monitoring"))


@app.post("/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...),
           site: str = Form(...), company: str = Form("")):
    email = email.strip().lower()
    if len(password) < 9:
        return RedirectResponse("/signup?err=Password+must+be+at+least+9+characters", 303)
    host = re.sub(r"^https?://", "", site.strip().lower()).strip("/").split("/")[0]
    if not host or "." not in host:
        return RedirectResponse("/signup?err=Enter+a+valid+website", 303)
    salt = secrets.token_hex(16)
    with closing(db()) as c:
        if c.execute("SELECT 1 FROM accounts WHERE email=?", (email,)).fetchone():
            return RedirectResponse("/signup?err=That+email+already+has+an+account", 303)
        cur = c.execute("""INSERT INTO accounts(email,company,pw_hash,salt,created,status)
                           VALUES(?,?,?,?,?,'trial')""",
                        (email, company.strip(), hash_pw(password, salt), salt, time.time()))
        aid = cur.lastrowid
        sid = c.execute("INSERT INTO sites(account_id,url,label,created) VALUES(?,?,?,?)",
                        (aid, host, host, time.time())).lastrowid
        c.execute("INSERT OR IGNORE INTO recipients(site_id,email,created) VALUES(?,?,?)",
                  (sid, email, time.time()))
        c.commit()
    request.session["acct"] = aid
    core_email(OWNER_EMAIL, f"New signup — {email}",
               f"""<div style="font:14px -apple-system,sans-serif;padding:22px">
<h2 style="margin:0 0 10px">New Website Down Checkers signup</h2>
<table style="border-collapse:collapse">
<tr><td style="padding:5px 12px 5px 0;color:#697084">Email</td><td><b>{e(email)}</b></td></tr>
<tr><td style="padding:5px 12px 5px 0;color:#697084">Company</td><td>{e(company) or "—"}</td></tr>
<tr><td style="padding:5px 12px 5px 0;color:#697084">First site</td><td>{e(host)}</td></tr>
<tr><td style="padding:5px 12px 5px 0;color:#697084">Status</td><td>trial</td></tr>
</table></div>""")
    return RedirectResponse("/app", 303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, err: str = ""):
    if current(request):
        return RedirectResponse("/app", 303)
    ee = f'<div class="err">{e(err)}</div>' if err else ""
    return HTMLResponse(shell(f"""<div class="card"><h1>Log in</h1>
<p class="mut">Manage your monitored sites and alert recipients.</p>{ee}
<form method="post" action="/login">
<label>Email</label><input type="email" name="email" required autofocus>
<label>Password</label><input type="password" name="password" required>
<button class="btn" type="submit" style="width:100%;margin-top:18px">Log in</button>
</form>
<p class="mut" style="margin-top:16px;font-size:13px">No account?
<a href="/signup">Start monitoring</a></p></div>""", title="Log in"))


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    with closing(db()) as c:
        a = c.execute("SELECT * FROM accounts WHERE email=?", (email.strip().lower(),)).fetchone()
    if not a or not hmac.compare_digest(hash_pw(password, a["salt"]), a["pw_hash"]):
        return RedirectResponse("/login?err=Incorrect+email+or+password", 303)
    request.session["acct"] = a["id"]
    return RedirectResponse("/app", 303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)


# ---------- customer app ----------
def _acct(aid):
    with closing(db()) as c:
        return c.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()


def _dur(ts):
    if not ts:
        return ""
    m = int((time.time() - ts) / 60)
    if m < 60:
        return f"{m}m"
    if m < 1440:
        return f"{m // 60}h {m % 60}m"
    return f"{m // 1440}d {(m % 1440) // 60}h"


@app.get("/app", response_class=HTMLResponse)
def dashboard(request: Request, aid=Depends(require)):
    a = _acct(aid)
    with closing(db()) as c:
        sites = c.execute("SELECT * FROM sites WHERE account_id=? ORDER BY id", (aid,)).fetchall()
        recs = {}
        for s in sites:
            recs[s["id"]] = [r["email"] for r in
                             c.execute("SELECT email FROM recipients WHERE site_id=? ORDER BY email",
                                       (s["id"],))]
    rows = ""
    for s in sites:
        if s["last_up"] is None:
            lamp, word = "grey", "checking…"
        elif s["last_up"]:
            lamp, word = "green", "up"
        else:
            lamp, word = "red", "DOWN"
        rows += (f'<tr><td><span class="lamp {lamp}"></span>'
                 f'<b class="{"bad" if lamp == "red" else ""}">{word}</b>'
                 f'<div class="mut" style="font-size:12px">{e(s["last_detail"] or "")}</div></td>'
                 f'<td><a href="https://{e(s["url"])}" target="_blank" rel="noopener">{e(s["url"])}</a></td>'
                 f'<td class="mut">{len(recs[s["id"]])} recipient'
                 f'{"s" if len(recs[s["id"]]) != 1 else ""}</td>'
                 f'<td class="mut">{_dur(s["since"])}</td>'
                 f'<td><a class="btn ghost sm" href="/app/site/{s["id"]}">Manage</a></td></tr>')
    table = (f'<table><thead><tr><th>Status</th><th>Website</th><th>Alerts to</th>'
             f'<th>For</th><th></th></tr></thead><tbody>{rows}</tbody></table>'
             if sites else '<p class="mut">No sites yet — add one below.</p>')
    pl = tier_plan(a["plan"])
    planbar = (f'<div class="note" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">'
               f'<b>{e(pl["name"])} plan</b>'
               f'<span class="mut">checks {e(pl["human"])} · '
               f'{pl["confirmations"]} confirmations before any alert</span>'
               f'<span style="flex:1"></span>'
               f'<a class="btn sm" href="/plans">Change plan</a></div>')
    banner = planbar
    if a["status"] == "trial":
        banner += ('<div class="note"><b>Trial.</b> Monitoring is live. '
                   + ("Billing is not yet switched on for this instance."
                      if not STRIPE_SK else '<a href="/plans">Choose a plan</a> to continue.')
                   + "</div>")
    return HTMLResponse(shell(f"""<div class="wrap">
<h1>Your websites</h1><p class="mut">Checked every 60 seconds from outside your network.</p>
{banner}{table}
<h2>Add a website</h2>
<form class="inline" method="post" action="/app/site/add">
<div><label>Website</label><input name="site" placeholder="example.com" required></div>
<div><label>Label <span class="mut">(optional)</span></label><input name="label"></div>
<button class="btn" type="submit">Add site</button>
</form></div>""", acct=a["email"], owner=bool(a["is_owner"]), cur="app", title="Dashboard"))


@app.post("/app/site/add")
def add_site(request: Request, site: str = Form(...), label: str = Form(""), aid=Depends(require)):
    host = re.sub(r"^https?://", "", site.strip().lower()).strip("/").split("/")[0]
    if host and "." in host:
        a = _acct(aid)
        with closing(db()) as c:
            sid = c.execute("INSERT INTO sites(account_id,url,label,created) VALUES(?,?,?,?)",
                            (aid, host, label.strip() or host, time.time())).lastrowid
            c.execute("INSERT OR IGNORE INTO recipients(site_id,email,created) VALUES(?,?,?)",
                      (sid, a["email"], time.time()))
            c.commit()
    return RedirectResponse("/app", 303)


@app.get("/app/site/{sid}", response_class=HTMLResponse)
def site_detail(sid: int, request: Request, aid=Depends(require)):
    a = _acct(aid)
    with closing(db()) as c:
        s = c.execute("SELECT * FROM sites WHERE id=? AND account_id=?", (sid, aid)).fetchone()
        if not s:
            raise HTTPException(404)
        recs = c.execute("SELECT * FROM recipients WHERE site_id=? ORDER BY email", (sid,)).fetchall()
        inc = c.execute("SELECT * FROM incidents WHERE site_id=? ORDER BY started DESC LIMIT 20",
                        (sid,)).fetchall()
    tags = "".join(f'<span class="tag">{e(r["email"])}'
                   f'<a href="/app/site/{sid}/recipient/{r["id"]}/delete" title="Remove">×</a></span>'
                   for r in recs)
    hist = "".join(
        f'<tr><td class="mut">{time.strftime("%b %d %H:%M", time.localtime(i["started"]))}</td>'
        f'<td>{e(i["detail"] or "")}</td>'
        f'<td class="mut">{_dur(i["started"]) if not i["ended"] else str(int((i["ended"]-i["started"])/60)) + "m"}</td>'
        f'<td>{"<span class=bad>ongoing</span>" if not i["ended"] else "<span class=ok>resolved</span>"}</td></tr>'
        for i in inc)
    hist_t = (f'<table><thead><tr><th>Started</th><th>Detail</th><th>Duration</th>'
              f'<th></th></tr></thead><tbody>{hist}</tbody></table>' if inc else
              '<p class="mut">No incidents recorded. That is the goal.</p>')
    lamp = "grey" if s["last_up"] is None else ("green" if s["last_up"] else "red")
    return HTMLResponse(shell(f"""<div class="wrap">
<p class="mut"><a href="/app">← All sites</a></p>
<h1><span class="lamp {lamp}"></span>{e(s["url"])}</h1>
<p class="mut">{e(s["last_detail"] or "waiting for first check")} · {_dur(s["since"])}</p>

<h2>Alert recipients</h2>
<p class="mut">Everyone here is emailed when this site goes down, and again when it recovers.
No per-seat charge.</p>
<div style="margin-bottom:14px">{tags or '<span class="mut">None yet.</span>'}</div>
<form class="inline" method="post" action="/app/site/{sid}/recipient">
<div><label>Add recipient</label><input type="email" name="email" placeholder="teammate@company.com" required></div>
<button class="btn" type="submit">Add</button></form>

<h2>Incident history</h2>{hist_t}
</div>""", acct=a["email"], owner=bool(a["is_owner"]), cur="app", title=s["url"]))


@app.post("/app/site/{sid}/recipient")
def add_recipient(sid: int, request: Request, email: str = Form(...), aid=Depends(require)):
    with closing(db()) as c:
        if c.execute("SELECT 1 FROM sites WHERE id=? AND account_id=?", (sid, aid)).fetchone():
            c.execute("INSERT OR IGNORE INTO recipients(site_id,email,created) VALUES(?,?,?)",
                      (sid, email.strip().lower(), time.time()))
            c.commit()
    return RedirectResponse(f"/app/site/{sid}", 303)


@app.get("/app/site/{sid}/recipient/{rid}/delete")
def del_recipient(sid: int, rid: int, request: Request, aid=Depends(require)):
    with closing(db()) as c:
        if c.execute("SELECT 1 FROM sites WHERE id=? AND account_id=?", (sid, aid)).fetchone():
            c.execute("DELETE FROM recipients WHERE id=? AND site_id=?", (rid, sid))
            c.commit()
    return RedirectResponse(f"/app/site/{sid}", 303)


# ---------- owner admin ----------
@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, aid=Depends(require_owner)):
    a = _acct(aid)
    with closing(db()) as c:
        rows = c.execute("""SELECT a.*,
            (SELECT COUNT(*) FROM sites s WHERE s.account_id=a.id) nsites,
            (SELECT COUNT(*) FROM recipients r JOIN sites s ON s.id=r.site_id
             WHERE s.account_id=a.id) nrec
            FROM accounts a WHERE a.is_owner=0 ORDER BY a.created DESC""").fetchall()
    tr = "".join(
        f'<tr><td class="mut">{time.strftime("%b %d", time.localtime(r["created"]))}</td>'
        f'<td><b>{e(r["email"])}</b><div class="mut" style="font-size:12.5px">{e(r["company"] or "")}</div></td>'
        f'<td><span class="pill">{e(r["status"])}</span></td>'
        f'<td class="mut">{r["nsites"]}</td><td class="mut">{r["nrec"]}</td>'
        f'<td><a class="btn ghost sm" href="/admin/customer/{r["id"]}">Open</a></td></tr>'
        for r in rows)
    body = (f'<table><thead><tr><th>Joined</th><th>Customer</th><th>Status</th><th>Sites</th>'
            f'<th>Recipients</th><th></th></tr></thead><tbody>{tr}</tbody></table>'
            if rows else '<p class="mut">No customers yet.</p>')
    return HTMLResponse(shell(f"""<div class="wrap">
<h1>Customers</h1><p class="mut">{len(rows)} account{"s" if len(rows) != 1 else ""}.
Stripe {"connected" if STRIPE_SK else "not configured — signups land as trial"}.</p>
{body}</div>""", acct=a["email"], owner=True, cur="admin", title="Customers"))


@app.get("/admin/customer/{cid}", response_class=HTMLResponse)
def admin_customer(cid: int, request: Request, aid=Depends(require_owner)):
    a = _acct(aid)
    with closing(db()) as c:
        cust = c.execute("SELECT * FROM accounts WHERE id=?", (cid,)).fetchone()
        if not cust:
            raise HTTPException(404)
        sites = c.execute("SELECT * FROM sites WHERE account_id=? ORDER BY id", (cid,)).fetchall()
        recs = {s["id"]: [r["email"] for r in
                          c.execute("SELECT email FROM recipients WHERE site_id=?", (s["id"],))]
                for s in sites}
        inc = c.execute("""SELECT i.*, s.url FROM incidents i JOIN sites s ON s.id=i.site_id
                           WHERE s.account_id=? ORDER BY i.started DESC LIMIT 25""", (cid,)).fetchall()
    st = "".join(
        f'<tr><td><span class="lamp {"grey" if s["last_up"] is None else ("green" if s["last_up"] else "red")}"></span></td>'
        f'<td>{e(s["url"])}</td><td class="mut">{e(s["last_detail"] or "")}</td>'
        f'<td class="mut">{", ".join(e(x) for x in recs[s["id"]])}</td></tr>' for s in sites)
    ih = "".join(
        f'<tr><td class="mut">{time.strftime("%b %d %H:%M", time.localtime(i["started"]))}</td>'
        f'<td>{e(i["url"])}</td><td class="mut">{e(i["detail"] or "")}</td>'
        f'<td>{"ongoing" if not i["ended"] else str(int((i["ended"]-i["started"])/60)) + "m"}</td></tr>'
        for i in inc)
    return HTMLResponse(shell(f"""<div class="wrap">
<p class="mut"><a href="/admin">← Customers</a></p>
<h1>{e(cust["email"])}</h1>
<p class="mut">{e(cust["company"] or "—")} · joined
{time.strftime("%d %b %Y", time.localtime(cust["created"]))} ·
<span class="pill">{e(cust["status"])}</span>
{" · stripe " + e(cust["stripe_customer"]) if cust["stripe_customer"] else ""}</p>
<h2>Sites</h2>
<table><thead><tr><th></th><th>Website</th><th>Last check</th><th>Alerts to</th></tr></thead>
<tbody>{st or '<tr><td colspan=4 class=mut>None</td></tr>'}</tbody></table>
<h2>Incidents</h2>
<table><thead><tr><th>Started</th><th>Site</th><th>Detail</th><th>Duration</th></tr></thead>
<tbody>{ih or '<tr><td colspan=4 class=mut>None recorded</td></tr>'}</tbody></table>
</div>""", acct=a["email"], owner=True, cur="admin", title=cust["email"]))



# ---------- plans, upgrades and coupons ----------
@app.get("/plans", response_class=HTMLResponse)
def plans_page(request: Request, err: str = "", ok: str = "", aid=Depends(require)):
    a = _acct(aid)
    cur = a["plan"]
    cards = ""
    for k in ORDER:
        p = PLANS[k]
        is_cur = (k == cur)
        per_day = 86400 // p["interval"]
        cards += f"""<div class="plan {'cur' if is_cur else ''}">
<div class="pname">{e(p['name'])}</div>
<div class="pamt">${p['price']:,}<span>/mo</span></div>
<div class="pfreq">checks {e(p['human'])}</div>
<p>{e(p['blurb'])}</p>
<ul>
<li>{per_day:,} check{'s' if per_day != 1 else ''} per site per day</li>
<li>{p['confirmations']} independent confirmations before any alert</li>
<li>Unlimited recipients &amp; unlimited sites</li>
<li>Down and recovery alerts with duration</li>
</ul>
<div class="pfor">{e(p['for'])}</div>
{'<div class="curbadge">Your current plan</div>' if is_cur else
 f'<form method="post" action="/plans/select"><input type="hidden" name="plan" value="{k}">'
 f'<button class="btn" type="submit" style="width:100%">Choose {e(p["name"])}</button></form>'}
</div>"""
    ee = f'<div class="err">{e(err)}</div>' if err else ""
    okk = f'<div class="note">{e(ok)}</div>' if ok else ""
    return HTMLResponse(shell(f"""<div class="wrap">
<p class="mut"><a href="/app">← Dashboard</a></p>
<h1>Choose your monitoring speed</h1>
<p class="mut">Every plan includes unlimited sites and unlimited alert recipients.
The difference is how quickly you find out.</p>
{ee}{okk}
<div class="plans">{cards}</div>

<h2>Have a coupon?</h2>
<p class="mut">Applies a plan directly, without going through checkout.</p>
<form class="inline" method="post" action="/plans/coupon">
<div><label>Coupon code</label><input name="code" placeholder="code" required></div>
<button class="btn ghost" type="submit">Apply</button></form>
</div>
<style>
.plans{{display:grid;grid-template-columns:repeat(auto-fit,minmax(268px,1fr));gap:18px;margin-bottom:30px}}
.plan{{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:24px;
display:flex;flex-direction:column}}
.plan.cur{{border-color:var(--acc)}}
.pname{{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);font-weight:700}}
.pamt{{font-size:42px;font-weight:800;letter-spacing:-.03em;margin:6px 0 2px}}
.pamt span{{font-size:15px;color:var(--mut);font-weight:600}}
.pfreq{{color:var(--acc);font-weight:700;font-size:14.5px;margin-bottom:12px}}
.plan p{{color:var(--mut);font-size:14px;margin:0 0 14px}}
.plan ul{{list-style:none;padding:0;margin:0 0 16px}}
.plan li{{padding:5px 0 5px 22px;position:relative;font-size:13.5px;color:var(--mut)}}
.plan li:before{{content:"✓";position:absolute;left:0;color:var(--ok);font-weight:800}}
.pfor{{font-size:13px;color:var(--mut);border-top:1px solid var(--line);padding-top:12px;
margin-bottom:16px;flex:1}}
.curbadge{{text-align:center;padding:10px;border:1px dashed var(--acc);border-radius:9px;
color:var(--acc);font-weight:700;font-size:14px}}
</style>""", acct=a["email"], owner=bool(a["is_owner"]), cur="app", title="Plans"))


@app.post("/plans/select")
def plans_select(request: Request, plan: str = Form(...), aid=Depends(require)):
    if plan not in PLANS:
        return RedirectResponse("/plans?err=Unknown+plan", 303)
    if not STRIPE_SK:
        # Billing not configured on this instance: record the intent rather than
        # pretending a payment happened.
        return RedirectResponse(
            "/plans?err=Checkout+is+not+enabled+yet.+Use+a+coupon+to+test,+or+add+Stripe+keys.", 303)
    return RedirectResponse(f"/subscribe?plan={plan}", 303)


@app.post("/plans/coupon")
def plans_coupon(request: Request, code: str = Form(...), aid=Depends(require)):
    c_ = COUPONS.get(code.strip().lower())
    if not c_:
        return RedirectResponse("/plans?err=That+coupon+code+is+not+recognised", 303)
    with closing(db()) as c:
        c.execute("UPDATE accounts SET plan=?, status=?, coupon=? WHERE id=?",
                  (c_["plan"], "comped" if c_.get("free") else "active",
                   code.strip().lower(), aid))
        c.commit()
    p = PLANS[c_["plan"]]
    return RedirectResponse(
        f"/plans?ok=Coupon+applied.+You+are+on+{p['name']}+—+checks+{p['human'].replace(' ', '+')}.", 303)

@app.get("/healthz")
def healthz():
    with closing(db()) as c:
        n = c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"]
        s = c.execute("SELECT COUNT(*) n FROM sites WHERE active=1").fetchone()["n"]
    return {"ok": True, "accounts": n, "sites": s, "stripe": bool(STRIPE_SK)}


init_db()
# Seed the owner account so the admin console is reachable immediately.
with closing(db()) as _c:
    if not _c.execute("SELECT 1 FROM accounts WHERE is_owner=1").fetchone():
        _s = secrets.token_hex(16)
        _pw = os.environ.get("OWNER_TEMP_PW") or secrets.token_urlsafe(12)
        _c.execute("""INSERT OR IGNORE INTO accounts(email,company,pw_hash,salt,created,status,is_owner)
                      VALUES(?,?,?,?,?,'owner',1)""",
                   (OWNER_EMAIL, "Website Down Checkers", hash_pw(_pw, _s), _s, time.time()))
        _c.commit()
