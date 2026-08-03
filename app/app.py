#!/usr/bin/env python3
"""
network.r0cketship.com — management back office.

Auth (single admin), bucket tabs over the domain inventory, selection state,
and a build queue. Site generation is a separate stage that reads the queue.
"""
import hashlib, hmac, json, os, secrets, sqlite3, time
from contextlib import closing
from http import HTTPStatus

from fastapi import FastAPI, Form, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "network.db")
DATA = os.path.join(BASE, "data-merged.json")
SECRET_FILE = os.path.join(BASE, ".session_secret")

BUCKETS = [
    ("live",        "Live Sites",   ["LIVE_MULTIPAGE", "LIVE_SINGLE"]),
    ("parked",      "Parked",       ["PARKED"]),
    ("unreachable", "Unreachable",  ["UNREACHABLE"]),
    ("suspended",   "Suspended",    ["SUSPENDED"]),
    ("broken",      "Broken 5xx",   ["BROKEN"]),
]
BUILDABLE = {"PARKED", "UNREACHABLE", "SUSPENDED", "BROKEN"}


# ---------- storage ----------
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with closing(db()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            email TEXT PRIMARY KEY,
            pw_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            must_change INTEGER NOT NULL DEFAULT 1,
            created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS selections(
            domain TEXT PRIMARY KEY,
            selected_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS build_queue(
            domain TEXT PRIMARY KEY,
            title TEXT, description TEXT,
            money_keyword TEXT, kw1 TEXT, kw2 TEXT, kw3 TEXT,
            state TEXT NOT NULL DEFAULT 'queued',
            queued_at REAL NOT NULL,
            built_at REAL
        );
        """)
        c.commit()


def hash_pw(pw: str, salt: str) -> str:
    return hashlib.scrypt(pw.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=32).hex()


def seed_admin(email: str, temp_pw: str):
    with closing(db()) as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return
        salt = secrets.token_hex(16)
        c.execute("INSERT INTO users(email,pw_hash,salt,must_change,created) VALUES(?,?,?,1,?)",
                  (email, hash_pw(temp_pw, salt), salt, time.time()))
        c.commit()


def load_inventory():
    with open(DATA) as f:
        rows = json.load(f)
    for r in rows:
        r["buildable"] = r["status"] in BUILDABLE
    return rows


INVENTORY = load_inventory()

# ---------- app ----------
if os.path.exists(SECRET_FILE):
    SECRET = open(SECRET_FILE).read().strip()
else:
    SECRET = secrets.token_hex(32)
    with open(SECRET_FILE, "w") as f:
        f.write(SECRET)
    os.chmod(SECRET_FILE, 0o600)

app = FastAPI(title="Network Back Office")
app.add_middleware(SessionMiddleware, secret_key=SECRET, https_only=True, max_age=60 * 60 * 12)


def current_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    u = current_user(request)
    if not u:
        raise HTTPException(status_code=HTTPStatus.SEE_OTHER, headers={"Location": "/login"})
    return u


# ---------- shared chrome ----------
CSS = """
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--tx:#e7eaf0;--mut:#8b93a7;--acc:#ff6b1a;--ok:#2ea043;--warn:#d29922;--bad:#cf484d}
@media(prefers-color-scheme:light){:root{--bg:#f6f7f9;--panel:#fff;--line:#e2e5ea;--tx:#12151b;--mut:#697084}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
a{color:var(--acc)}
.topbar{display:flex;align-items:center;gap:16px;padding:14px 24px;border-bottom:1px solid var(--line);background:var(--panel)}
.topbar h1{margin:0;font-size:17px;letter-spacing:-.01em;flex:1}
.topbar .who{color:var(--mut);font-size:13px}
.btn{appearance:none;border:1px solid var(--line);background:var(--panel);color:var(--tx);font:inherit;font-weight:600;padding:8px 14px;border-radius:9px;cursor:pointer;text-decoration:none;display:inline-block}
.btn.primary{background:var(--acc);border-color:var(--acc);color:#fff}
.btn:disabled{opacity:.45;cursor:not-allowed}
.wrap{max-width:1500px;margin:0 auto;padding:20px 24px 70px}
.tabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin-bottom:16px}
.tab{padding:10px 15px;border-bottom:2px solid transparent;color:var(--mut);font-weight:600;text-decoration:none;font-size:14px}
.tab.on{color:var(--tx);border-bottom-color:var(--acc)}
.tab .n{color:var(--mut);font-weight:500}
.bar{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
input[type=search],input[type=password],input[type=email]{padding:9px 12px;border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--tx);font:inherit}
input[type=search]{width:320px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);padding:10px 12px;border-bottom:1px solid var(--line)}
td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
.fav{width:20px;height:20px;border-radius:4px;display:block}
.dom{font-weight:600;white-space:nowrap}
.dom a{color:var(--tx);text-decoration:none}
.dom a:hover{color:var(--acc);text-decoration:underline}
.dsc{color:var(--mut);font-size:13.5px}
.muted{color:var(--mut)}
.pill{display:inline-block;font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid currentColor;font-weight:600}
.pill.ok{color:var(--ok)}.pill.warn{color:var(--warn)}.pill.bad{color:var(--bad)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:26px;max-width:420px;margin:70px auto}
.card h2{margin:0 0 6px;font-size:20px}
.card p{color:var(--mut);margin:0 0 18px;font-size:14px}
.card label{display:block;font-size:13px;color:var(--mut);margin:12px 0 5px}
.card input{width:100%}
.card .btn{width:100%;margin-top:18px;text-align:center}
.err{background:rgba(207,72,77,.12);border:1px solid var(--bad);color:var(--bad);padding:9px 12px;border-radius:9px;font-size:13.5px;margin-bottom:8px}
.note{background:rgba(255,107,26,.1);border:1px solid var(--acc);padding:10px 13px;border-radius:9px;font-size:13.5px;margin-bottom:14px}
.selbar{position:sticky;bottom:0;background:var(--panel);border:1px solid var(--acc);border-radius:12px;padding:12px 16px;display:flex;gap:12px;align-items:center;margin-top:14px}
</style>
"""


def shell(body: str, user=None, title="Network Back Office") -> str:
    who = f'<span class="who">{user}</span> <a class="btn" href="/logout">Sign out</a>' if user else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>{CSS}</head><body>
<div class="topbar"><h1>🚀 Network Back Office</h1>{who}</div>
{body}
</body></html>"""


# ---------- auth ----------
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, err: str = ""):
    if current_user(request):
        return RedirectResponse("/", 303)
    e = f'<div class="err">{err}</div>' if err else ""
    return shell(f"""<div class="card"><h2>Sign in</h2>
<p>Management access for the R0cketShip domain network.</p>{e}
<form method="post" action="/login">
<label>Email</label><input type="email" name="email" value="jeff.cline@me.com" required autofocus>
<label>Password</label><input type="password" name="password" required>
<button class="btn primary" type="submit">Sign in</button>
</form></div>""", title="Sign in — Network")


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    with closing(db()) as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not u or not hmac.compare_digest(hash_pw(password, u["salt"]), u["pw_hash"]):
        return RedirectResponse("/login?err=Incorrect+email+or+password", 303)
    request.session["user"] = u["email"]
    if u["must_change"]:
        return RedirectResponse("/change-password", 303)
    return RedirectResponse("/", 303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


@app.get("/change-password", response_class=HTMLResponse)
def change_form(request: Request, user=Depends(require_login), err: str = ""):
    e = f'<div class="err">{err}</div>' if err else ""
    return shell(f"""<div class="card"><h2>Set your password</h2>
<p>The temporary password must be replaced before you can manage the network.</p>{e}
<form method="post" action="/change-password">
<label>New password (9+ characters)</label><input type="password" name="p1" required autofocus>
<label>Confirm</label><input type="password" name="p2" required>
<button class="btn primary" type="submit">Set password</button>
</form></div>""", user=user, title="Set password")


@app.post("/change-password")
def change_pw(request: Request, p1: str = Form(...), p2: str = Form(...), user=Depends(require_login)):
    if p1 != p2:
        return RedirectResponse("/change-password?err=Passwords+do+not+match", 303)
    if len(p1) < 9:
        return RedirectResponse("/change-password?err=Use+at+least+9+characters", 303)
    salt = secrets.token_hex(16)
    with closing(db()) as c:
        c.execute("UPDATE users SET pw_hash=?,salt=?,must_change=0 WHERE email=?", (hash_pw(p1, salt), salt, user))
        c.commit()
    return RedirectResponse("/", 303)


def guard_password_change(request: Request, user):
    with closing(db()) as c:
        u = c.execute("SELECT must_change FROM users WHERE email=?", (user,)).fetchone()
    return bool(u and u["must_change"])


# ---------- inventory ----------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, bucket: str = "parked", q: str = "", user=Depends(require_login)):
    if guard_password_change(request, user):
        return RedirectResponse("/change-password", 303)

    counts = {k: sum(1 for r in INVENTORY if r["status"] in st) for k, _, st in BUCKETS}
    cur = next((b for b in BUCKETS if b[0] == bucket), BUCKETS[1])
    rows = [r for r in INVENTORY if r["status"] in cur[2]]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["domain"].lower() or ql in (r["title"] or "").lower()]
    rows.sort(key=lambda r: r["domain"])

    with closing(db()) as c:
        sel = {r["domain"] for r in c.execute("SELECT domain FROM selections")}

    tabs = "".join(
        f'<a class="tab {"on" if k == cur[0] else ""}" href="/?bucket={k}">{lbl} <span class="n">{counts[k]}</span></a>'
        for k, lbl, _ in BUCKETS)

    LBL = {"LIVE_MULTIPAGE": ("Multi-page", "ok"), "LIVE_SINGLE": ("Single page", "warn"),
           "PARKED": ("Parked", "warn"), "SUSPENDED": ("Suspended", "bad"),
           "BROKEN": ("5xx", "bad"), "UNREACHABLE": ("No host", "bad")}

    buildable = cur[0] != "live"
    tr = []
    for r in rows:
        lbl, cls = LBL[r["status"]]
        checked = "checked" if r["domain"] in sel else ""
        box = (f'<input type="checkbox" class="sel" value="{r["domain"]}" {checked}>'
               if buildable else '<span class="muted" title="Live sites cannot be queued">—</span>')
        url = r["final_url"] or "http://" + r["domain"]
        tr.append(f"""<tr>
<td>{box}</td>
<td><img class="fav" loading="lazy" alt="" src="https://www.google.com/s2/favicons?domain={r['domain']}&sz=64"></td>
<td class="dom"><a href="{url}" target="_blank" rel="noopener">{r['domain']}</a></td>
<td><span class="pill {cls}">{lbl}</span></td>
<td>{(r['title'] or '')[:90] or '<span class="muted">—</span>'}</td>
<td class="dsc">{(r['desc'] or '')[:130] or '<span class="muted">—</span>'}</td>
<td class="muted">{r['expires']}</td>
<td class="muted">{r['account']}</td>
</tr>""")

    warn = ('<div class="note"><b>Live sites are read-only here.</b> They cannot be selected or '
            'repointed — this is the guard against taking a working site offline.</div>'
            if cur[0] == "live" else "")

    selbar = "" if not buildable else f"""
<div class="selbar">
<label><input type="checkbox" id="all"> Select all {len(rows)} in this tab</label>
<span class="muted" id="cnt">{len(sel)} selected overall</span>
<span style="flex:1"></span>
<a class="btn primary" href="/queue">Review build queue →</a>
</div>"""

    return shell(f"""<div class="wrap">
<div class="tabs">{tabs}</div>
{warn}
<div class="bar">
<form method="get"><input type="hidden" name="bucket" value="{cur[0]}">
<input type="search" name="q" value="{q}" placeholder="Filter {cur[1].lower()}…"></form>
<span class="muted">{len(rows)} domains</span>
</div>
<table><thead><tr><th></th><th></th><th>Domain</th><th>Status</th><th>Title</th><th>Description</th><th>Expires</th><th>Acct</th></tr></thead>
<tbody>{"".join(tr)}</tbody></table>
{selbar}
</div>
<script>
const cnt=document.getElementById('cnt');
async function post(u,b){{const r=await fetch(u,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(b)}});return r.json();}}
document.querySelectorAll('.sel').forEach(cb=>cb.addEventListener('change',async()=>{{
  const j=await post('/api/select',{{domain:cb.value,on:cb.checked}});
  cnt.textContent=j.total+' selected overall';
}}));
const all=document.getElementById('all');
if(all) all.addEventListener('change',async()=>{{
  const ds=[...document.querySelectorAll('.sel')].map(c=>c.value);
  document.querySelectorAll('.sel').forEach(c=>c.checked=all.checked);
  const j=await post('/api/select-bulk',{{domains:ds,on:all.checked}});
  cnt.textContent=j.total+' selected overall';
}});
</script>""", user=user, title=f"{cur[1]} — Network")


@app.post("/api/select")
async def api_select(request: Request, user=Depends(require_login)):
    b = await request.json()
    d, on = b["domain"], bool(b["on"])
    rec = next((r for r in INVENTORY if r["domain"] == d), None)
    if not rec or not rec["buildable"]:
        raise HTTPException(400, "not selectable")
    with closing(db()) as c:
        if on:
            c.execute("INSERT OR IGNORE INTO selections VALUES(?,?)", (d, time.time()))
        else:
            c.execute("DELETE FROM selections WHERE domain=?", (d,))
        c.commit()
        n = c.execute("SELECT COUNT(*) n FROM selections").fetchone()["n"]
    return {"ok": True, "total": n}


@app.post("/api/select-bulk")
async def api_select_bulk(request: Request, user=Depends(require_login)):
    b = await request.json()
    ok = {r["domain"] for r in INVENTORY if r["buildable"]}
    ds = [d for d in b["domains"] if d in ok]
    with closing(db()) as c:
        if b["on"]:
            c.executemany("INSERT OR IGNORE INTO selections VALUES(?,?)", [(d, time.time()) for d in ds])
        else:
            c.executemany("DELETE FROM selections WHERE domain=?", [(d,) for d in ds])
        c.commit()
        n = c.execute("SELECT COUNT(*) n FROM selections").fetchone()["n"]
    return {"ok": True, "total": n}


@app.get("/queue", response_class=HTMLResponse)
def queue(request: Request, user=Depends(require_login)):
    with closing(db()) as c:
        sel = [r["domain"] for r in c.execute("SELECT domain FROM selections ORDER BY domain")]
    by = {r["domain"]: r for r in INVENTORY}
    rows = "".join(
        f'<tr><td class="dom">{d}</td><td><span class="pill warn">{by[d]["status"]}</span></td>'
        f'<td class="muted">{by[d]["expires"]}</td><td class="muted">acct {by[d]["account"]}</td></tr>'
        for d in sel if d in by)
    body = (f'<p class="muted">{len(sel)} domains selected. Nothing has been changed yet — '
            f'DNS repointing and site generation require explicit approval of this exact list.</p>'
            f'<table><thead><tr><th>Domain</th><th>Current status</th><th>Expires</th><th>Account</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>') if sel else '<p class="muted">Nothing selected yet.</p>'
    return shell(f"""<div class="wrap">
<div class="bar"><a class="btn" href="/">← Back to inventory</a></div>
<h2 style="margin:0 0 4px">Build queue</h2>
{body}
</div>""", user=user, title="Build queue — Network")


@app.get("/healthz")
def healthz():
    return {"ok": True, "domains": len(INVENTORY)}


init_db()
seed_admin(os.environ.get("ADMIN_EMAIL", "jeff.cline@me.com"),
           os.environ.get("ADMIN_TEMP_PW", secrets.token_urlsafe(12)))
