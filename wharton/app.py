#!/usr/bin/env python3
"""
whartonjelly.com — provider acquisition funnel, patient referral routing, CRM.

Two audiences, two gates, one database. Almost all content sits behind an
account so intent is captured before anything is given away. Consumers are
routed by ZIP to a network provider; providers can hold a ZIP exclusively.

The manufacturer is never named anywhere in output. IORE is cited as the
education hub, which is how the supplied material describes it.
"""
import hashlib, hmac, html, json, os, re, secrets, sqlite3, sys, time
from contextlib import closing
from http import HTTPStatus

from fastapi import FastAPI, Form, Query, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import content as C
import product as P

DB = os.path.join(BASE, "wharton.db")
SECRET_FILE = os.path.join(BASE, ".session_secret")
e = html.escape

OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "jeff.cline@me.com")
CORE = "https://medigap.plus"
CORE_KEY = os.environ.get("CORE_KEY", "")
CORE_SECRET = os.environ.get("CORE_SECRET", "")
EXCLUSIVE_PRICE = 1500


# ---------- storage ----------
def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init_db():
    with closing(db()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS accounts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL, pw_hash TEXT, salt TEXT,
            role TEXT NOT NULL DEFAULT 'consumer',
            first TEXT, last TEXT, phone TEXT,
            must_change INTEGER NOT NULL DEFAULT 0,
            invite_token TEXT, created REAL NOT NULL, last_login REAL);
        CREATE TABLE IF NOT EXISTS providers(
            account_id INTEGER PRIMARY KEY, clinic TEXT, npi TEXT,
            city TEXT, state TEXT, zip TEXT, business_address TEXT,
            accepts_referrals INTEGER NOT NULL DEFAULT 1,
            exclusive INTEGER NOT NULL DEFAULT 0,
            verified_purchaser INTEGER NOT NULL DEFAULT 0,
            stripe_sub TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS consumers(
            account_id INTEGER PRIMARY KEY, city TEXT, state TEXT, zip TEXT,
            interest TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS leads(
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            account_id INTEGER, created REAL NOT NULL, zip TEXT,
            source TEXT, status TEXT NOT NULL DEFAULT 'new',
            assigned_provider INTEGER, assigned_at REAL, monday_item TEXT);
        CREATE TABLE IF NOT EXISTS lead_notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER NOT NULL,
            author_id INTEGER, ts REAL NOT NULL, note TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'crm');
        CREATE TABLE IF NOT EXISTS settings(
            k TEXT PRIMARY KEY, v TEXT, updated REAL);
        CREATE TABLE IF NOT EXISTS images(
            slot TEXT PRIMARY KEY, path TEXT, caption TEXT, updated REAL);
        CREATE TABLE IF NOT EXISTS zip_claims(
            zip TEXT PRIMARY KEY, provider_id INTEGER, since REAL, stripe_sub TEXT);
        CREATE INDEX IF NOT EXISTS idx_leads_zip ON leads(zip);
        CREATE INDEX IF NOT EXISTS idx_leads_prov ON leads(assigned_provider);
        """)
        c.commit()


def hash_pw(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=32).hex()


def setting(k, default=""):
    with closing(db()) as c:
        r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return (r["v"] if r else "") or default


def set_setting(k, v):
    with closing(db()) as c:
        c.execute("""INSERT INTO settings(k,v,updated) VALUES(?,?,?)
                     ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated=excluded.updated""",
                  (k, v, time.time()))
        c.commit()


def email_out(to, subject, body_html):
    if not (CORE_KEY and CORE_SECRET):
        return False
    import subprocess
    payload = json.dumps({"to": to, "subject": subject, "html": body_html})
    # CORE rotates outbound mail across sender accounts and the pool has degraded
    # to roughly a 50% failure rate. Eight attempts with growing backoff makes a
    # missed notification vanishingly unlikely; each retry draws a fresh sender.
    for i in range(8):
        try:
            p = subprocess.run(["curl", "-sS", "--max-time", "25", "-X", "POST",
                                "-H", f"x-core-key: {CORE_KEY}",
                                "-H", f"x-core-secret: {CORE_SECRET}",
                                "-H", "content-type: application/json", "-d", payload,
                                CORE + "/api/core/email"],
                               capture_output=True, text=True, timeout=40)
            if json.loads(p.stdout).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(min(1.0 * (i + 1), 5.0))
    return False


# ---------- referral routing ----------
def route_consumer(lead_id, zip_code):
    """Assign a consumer enquiry to a provider in that ZIP.

    Exclusive holder wins outright. Otherwise round-robin by who was assigned
    least recently, so a busy ZIP shares evenly. A provider must be a verified
    purchaser and have referrals switched on."""
    if not zip_code:
        return None
    with closing(db()) as c:
        claim = c.execute("SELECT provider_id FROM zip_claims WHERE zip=?", (zip_code,)).fetchone()
        if claim:
            p = c.execute("""SELECT account_id FROM providers WHERE account_id=?
                             AND accepts_referrals=1 AND verified_purchaser=1""",
                          (claim["provider_id"],)).fetchone()
            if p:
                c.execute("UPDATE leads SET assigned_provider=?, assigned_at=? WHERE id=?",
                          (p["account_id"], time.time(), lead_id))
                c.commit()
                return p["account_id"]
        rows = c.execute("""SELECT p.account_id,
                              (SELECT MAX(assigned_at) FROM leads l
                               WHERE l.assigned_provider=p.account_id) last_at
                            FROM providers p
                            WHERE p.zip=? AND p.accepts_referrals=1 AND p.verified_purchaser=1
                            ORDER BY COALESCE(last_at, 0) ASC""", (zip_code,)).fetchall()
        if not rows:
            return None
        pid = rows[0]["account_id"]
        c.execute("UPDATE leads SET assigned_provider=?, assigned_at=? WHERE id=?",
                  (pid, time.time(), lead_id))
        c.commit()
        return pid


def backfill_for_provider(provider_id, zip_code):
    """A provider joining a ZIP inherits the unassigned enquiries already sitting
    in it. Without this, every enquiry received before they signed up is wasted."""
    if not zip_code:
        return 0
    with closing(db()) as c:
        rows = c.execute("""SELECT id FROM leads WHERE kind='consumer' AND zip=?
                            AND assigned_provider IS NULL""", (zip_code,)).fetchall()
        for r in rows:
            c.execute("UPDATE leads SET assigned_provider=?, assigned_at=? WHERE id=?",
                      (provider_id, time.time(), r["id"]))
            c.execute("""INSERT INTO lead_notes(lead_id,author_id,ts,note,source)
                         VALUES(?,?,?,?,'system')""",
                      (r["id"], None, time.time(),
                       "Back-filled to provider on joining this ZIP."))
        c.commit()
        return len(rows)


# ---------- app ----------
if os.path.exists(SECRET_FILE):
    SECRET = open(SECRET_FILE).read().strip()
else:
    SECRET = secrets.token_hex(32)
    open(SECRET_FILE, "w").write(SECRET)
    os.chmod(SECRET_FILE, 0o600)

app = FastAPI(title="Wharton Jelly")
app.add_middleware(SessionMiddleware, secret_key=SECRET, https_only=True,
                   max_age=60 * 60 * 24 * 14)
os.makedirs(os.path.join(BASE, "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


def current(request: Request):
    return request.session.get("uid")


ALLOW_WHILE_TEMP = {"/change-password", "/logout"}


def require(request: Request):
    u = current(request)
    if not u:
        raise HTTPException(status_code=HTTPStatus.SEE_OTHER, headers={"Location": "/login"})
    # A temporary password must be replaced before ANY authenticated page opens.
    # Guarding only the landing page let /admin be reached by typing the URL.
    if request.url.path not in ALLOW_WHILE_TEMP:
        a = acct(u)
        if a and a["must_change"]:
            raise HTTPException(status_code=HTTPStatus.SEE_OTHER,
                                headers={"Location": "/change-password"})
    return u


def acct(uid):
    with closing(db()) as c:
        return c.execute("SELECT * FROM accounts WHERE id=?", (uid,)).fetchone()


def require_role(*roles):
    def dep(request: Request):
        uid = require(request)
        a = acct(uid)
        if not a or a["role"] not in roles:
            raise HTTPException(status_code=HTTPStatus.SEE_OTHER, headers={"Location": "/portal"})
        return uid
    return dep


init_db()
with closing(db()) as _c:
    if not _c.execute("SELECT 1 FROM accounts WHERE role='owner'").fetchone():
        _s = secrets.token_hex(16)
        _pw = os.environ.get("OWNER_TEMP_PW", "TEMP!234")
        _c.execute("""INSERT INTO accounts(email,pw_hash,salt,role,first,last,must_change,created)
                      VALUES(?,?,?,'owner','Jeff','Cline',1,?)""",
                   (OWNER_EMAIL, hash_pw(_pw, _s), _s, time.time()))
        _c.commit()



# ---------- structured data ----------
ORG_LD = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "Organization", "@id": "https://whartonjelly.com/#org",
         "name": "Wharton Jelly", "url": "https://whartonjelly.com/",
         "description": C.TAGLINE,
         "logo": "https://whartonjelly.com/static/img/wj-ss-vial.png"},
        {"@type": "WebSite", "@id": "https://whartonjelly.com/#site",
         "url": "https://whartonjelly.com/", "name": "Wharton Jelly",
         "publisher": {"@id": "https://whartonjelly.com/#org"},
         "inLanguage": "en-US"},
    ],
}


def faq_ld(pairs):
    """FAQPage markup is what answer engines lift directly, so every Q&A on the
    site is emitted as structured data as well as prose."""
    return json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a}}
                       for q, a in pairs]})


def product_ld():
    return json.dumps({
        "@context": "https://schema.org", "@type": "Product",
        "name": P.PRODUCT["name"], "alternateName": P.PRODUCT["h2"],
        "image": "https://whartonjelly.com" + P.PRODUCT["image"],
        "description": P.PRODUCT["sections"][0][1],
        "brand": {"@type": "Brand", "name": "Wharton Jelly"},
        "audience": {"@type": "MedicalAudience", "audienceType": "Clinician"},
        "disclaimer": P.LEGAL})


def article_ld(headline, body, url):
    return json.dumps({
        "@context": "https://schema.org", "@type": "MedicalWebPage",
        "headline": headline, "url": "https://whartonjelly.com" + url,
        "description": body[:200],
        "publisher": {"@id": "https://whartonjelly.com/#org"},
        "inLanguage": "en-US",
        "reviewedBy": {"@type": "Organization", "name": C.IORE_NAME}})


# ---------- chrome ----------
CSS = """
:root{--bg:#04141a;--panel:#0c2129;--line:#17323d;--tx:#e9f4f6;--mut:#8fadb6;
--teal:#19c2c9;--teal-d:#0e8f96;--orange:#ff7a1a;--orange-d:#e05f00;--ok:#2ea043;--bad:#e5484d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,sans-serif}
a{color:var(--teal)}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
header.nav{position:sticky;top:0;z-index:40;background:rgba(4,20,26,.92);
backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
header.nav .in{display:flex;align-items:center;gap:20px;padding:14px 0}
.brand{font-weight:800;letter-spacing:-.02em;text-decoration:none;font-size:18px;color:var(--tx)}
.brand .t{color:var(--teal)}.brand .o{color:var(--orange)}
nav.links{flex:1;display:flex;gap:20px}
nav.links a{color:var(--mut);text-decoration:none;font-size:14.5px;font-weight:600}
nav.links a:hover{color:var(--tx)}
.btn{display:inline-block;background:var(--orange);color:#fff;text-decoration:none;font-weight:800;
padding:13px 26px;border-radius:10px;font-size:15.5px;border:0;cursor:pointer;letter-spacing:-.01em}
.btn:hover{background:var(--orange-d)}
.btn.teal{background:var(--teal);color:#04141a}
.btn.teal:hover{background:var(--teal-d);color:#fff}
.btn.ghost{background:transparent;border:1px solid var(--line);color:var(--tx);font-weight:700}
.btn.sm{padding:8px 15px;font-size:13.5px}
.btn.lg{padding:17px 34px;font-size:17px}
/* hero */
.hero{position:relative;min-height:min(78vh,660px);display:flex;align-items:center;overflow:hidden}
.hero video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.hero .scrim{position:absolute;inset:0;
background:linear-gradient(100deg,rgba(4,20,26,.94) 0%,rgba(4,20,26,.78) 45%,rgba(4,20,26,.45) 100%)}
.hero .in{position:relative;max-width:1180px;margin:0 auto;padding:70px 24px;width:100%}
h1.hero-h1{margin:0 0 14px;font-size:clamp(44px,8.5vw,92px);line-height:.95;letter-spacing:-.045em;
font-weight:900}
h1.hero-h1 .t{color:var(--teal)}
h1.hero-h1 .o{color:var(--orange)}
.hero p.lead{font-size:clamp(17px,2.4vw,23px);color:#dbeef1;max-width:44ch;margin:0 0 10px;font-weight:600}
.hero p.sub{font-size:clamp(15px,1.9vw,18px);color:var(--mut);max-width:52ch;margin:0 0 30px}
.hero .cta{display:flex;gap:14px;flex-wrap:wrap}
/* sections */
section{padding:64px 0;border-top:1px solid var(--line)}
h2{font-size:clamp(26px,3.8vw,40px);letter-spacing:-.03em;margin:0 0 12px;font-weight:800}
h2 .t{color:var(--teal)}
p.lede{color:var(--mut);max-width:64ch;font-size:17px;margin:0 0 32px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:24px;
position:relative;overflow:hidden}
.card h3{margin:0 0 8px;font-size:18px;letter-spacing:-.015em}
.card p{color:var(--mut);margin:0;font-size:14.5px}
.card .kicker{font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--teal);
font-weight:800;margin-bottom:8px}
/* lock gate */
.locked{position:relative}
.locked .veil{position:absolute;inset:0;background:linear-gradient(180deg,
rgba(12,33,41,.15) 0%,rgba(4,20,26,.9) 62%,var(--bg) 100%);display:flex;align-items:flex-end;
justify-content:center;padding-bottom:26px}
.locked .veil .inner{text-align:center}
.locked .veil .lk{font-size:26px;margin-bottom:6px}
.locked .veil p{color:var(--tx);font-weight:700;margin:0 0 12px;font-size:15px}
.blurred{filter:blur(4px);pointer-events:none;user-select:none;max-height:230px;overflow:hidden}
/* forms */
.card.form{max-width:640px;margin:0 auto}
label{display:block;font-size:13px;color:var(--mut);margin:13px 0 5px;font-weight:700}
input,select,textarea{width:100%;padding:11px 13px;border:1px solid var(--line);border-radius:9px;
background:#061a21;color:var(--tx);font:inherit}
input:focus,select:focus,textarea:focus{outline:2px solid var(--teal);outline-offset:-1px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.three{display:grid;grid-template-columns:1.2fr .8fr .8fr;gap:12px}
@media(max-width:600px){.two,.three{grid-template-columns:1fr}}
.err{background:rgba(229,72,77,.12);border:1px solid var(--bad);color:#ffb4b6;padding:10px 13px;
border-radius:9px;font-size:14px;margin-bottom:12px}
.note{background:rgba(25,194,201,.09);border:1px solid var(--teal);padding:11px 14px;
border-radius:9px;font-size:14px;margin-bottom:16px}
/* tables */
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);
border-radius:13px;overflow:hidden}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);
padding:11px 13px;border-bottom:1px solid var(--line)}
td{padding:11px 13px;border-bottom:1px solid var(--line);vertical-align:top;font-size:14.5px}
tr:last-child td{border-bottom:0}
.pill{display:inline-block;font-size:11px;padding:2px 9px;border-radius:999px;
border:1px solid currentColor;font-weight:800}
.mut{color:var(--mut)}.bad{color:var(--bad)}.ok{color:var(--ok)}.teal{color:var(--teal)}
.compliance{border-top:1px solid var(--line);background:#061a21}
.compliance .in{max-width:1180px;margin:0 auto;padding:22px 24px;color:var(--mut);font-size:12.5px;
line-height:1.65}
footer{border-top:1px solid var(--line);background:var(--panel)}
footer .in{max-width:1180px;margin:0 auto;padding:44px 24px}
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:26px}
footer h4{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:0 0 11px}
footer a{display:block;color:var(--tx);text-decoration:none;padding:3px 0;font-size:14.5px}
footer a:hover{color:var(--teal)}
.joinstrip{background:linear-gradient(90deg,var(--teal-d),var(--teal));padding:34px 0}
.joinstrip .in{max-width:1180px;margin:0 auto;padding:0 24px;display:flex;gap:20px;
align-items:center;flex-wrap:wrap}
.joinstrip h3{margin:0;font-size:26px;color:#04141a;letter-spacing:-.02em;font-weight:900;flex:1}
.machine{border-top:1px solid var(--line);margin-top:14px;padding-top:14px;display:flex;
gap:14px;flex-wrap:wrap;align-items:center}
.machine span{color:var(--mut);font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;
font-weight:800}
.machine a{display:inline;color:var(--mut);font-size:11.5px;padding:0;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;text-decoration:none;
border-bottom:1px dotted var(--line)}
.machine a:hover{color:var(--teal);border-bottom-color:var(--teal)}
.rocket{position:fixed;right:19px;bottom:19px;z-index:70;width:52px;height:52px;border-radius:50%;
background:var(--orange);display:flex;align-items:center;justify-content:center;font-size:25px;
text-decoration:none;box-shadow:0 5px 20px rgba(0,0,0,.35);transition:transform .15s}
.rocket:hover{transform:translateY(-2px);background:var(--orange-d)}
"""


def shell(body, user=None, title="Wharton Jelly", nav=True, desc=None,
          canon="/", ld=None):
    desc = desc or f"{C.TAGLINE} {C.SUBLINE}"
    ld = ld or json.dumps(ORG_LD)
    connect_links = "".join(f'<a href="/connect/{sl}">{e(t)}</a>' for sl, t, _, _ in C.CONNECT)
    links = ""
    right = ('<a class="btn ghost sm" href="/login">Log in</a>'
             '<a class="btn sm" href="/providers">Provider access</a>')
    if user:
        links = ('<a href="/portal">Portal</a>'
                 + ('<a href="/crm">CRM</a>' if user["role"] in ("owner", "sales") else "")
                 + ('<a href="/admin">Admin</a>' if user["role"] == "owner" else ""))
        right = (f'<span class="mut" style="font-size:13px">{e(user["email"])}</span>'
                 f'<a class="btn ghost sm" href="/logout">Sign out</a>')
    header = f"""<header class="nav"><div class="wrap in">
<a class="brand" href="/"><span class="t">Wharton</span> <span class="o">Jelly</span></a>
<nav class="links">{links}</nav>{right}</div></header>""" if nav else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="https://whartonjelly.com{e(canon)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Wharton Jelly">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="https://whartonjelly.com{e(canon)}">
<meta property="og:image" content="https://whartonjelly.com{P.PRODUCT['image']}">
<meta name="twitter:card" content="summary_large_image">
<meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large">
<script type="application/ld+json">{ld}</script>
<style>{CSS}</style></head><body>{header}{body}
<div class="compliance"><div class="in">
<p style="margin:0 0 10px"><b>Important:</b> {e(C.COMPLIANCE)}</p>
<p style="margin:0">{e(P.LEGAL)}</p></div></div>
<footer><div class="in"><div class="fgrid">
<div><h4>Wharton Jelly</h4>
<a href="/providers">For doctors &amp; providers</a>
<a href="/patients">For consumers &amp; patients</a>
<a href="/science">The science</a>
<a href="/sourcing">Sourcing &amp; quality</a>
<a href="/research">Research</a>
<a href="/education">Education &amp; support</a></div>
<div><h4>Providers</h4>
<a href="/providers/apply">Join the provider program</a>
<a href="/providers#referrals">Referral network</a>
<a href="/login">Provider log in</a></div>
<div><h4>Education</h4>
<a href="/videos">Video library</a>
<a href="/modules">Education library</a>
<a href="/faq">Common questions</a>
<a href="/go/iore">{e(C.IORE_NAME)}</a>
<a href="/education">Clinical resources</a></div>
<div><h4>Connect</h4>{connect_links}</div>
</div>
<div style="border-top:1px solid var(--line);margin-top:30px;padding-top:20px;
color:var(--mut);font-size:12.5px">
Education, protocols and validation are provided through the {e(C.IORE_NAME)}, an independent
third party. &copy; {time.strftime('%Y')} Wharton Jelly.
</div>
<div class="machine">
<span>Machine-readable</span>
<a href="/sitemap.xml">sitemap.xml</a>
<a href="/answers.xml">answers.xml</a>
<a href="/llms.txt">llms.txt</a>
<a href="/robots.txt">robots.txt</a>
<a href="/schema.json">schema.json</a>
</div></div></footer>
<a class="rocket" href="https://r0cketship.com" target="_blank" rel="noopener"
 aria-label="Built by R0cketShip" title="Built by R0cketShip">&#128640;</a>
</body></html>"""


def img(slot, alt, cls=""):
    """Image slots are replaceable from the back office; until one is set we draw
    a branded placeholder rather than a broken image."""
    with closing(db()) as c:
        r = c.execute("SELECT path FROM images WHERE slot=?", (slot,)).fetchone()
    if r and r["path"]:
        return f'<img class="{cls}" src="{e(r["path"])}" alt="{e(alt)}" loading="lazy">'
    return (f'<div class="{cls} ph" role="img" aria-label="{e(alt)}"></div>')


def gate(inner_html, why, audience="provider"):
    """Show a taste, then stop. Everything of value sits behind an account so
    intent is captured before it is given away."""
    return f"""<div class="locked">
<div class="blurred">{inner_html}</div>
<div class="veil"><div class="inner">
<div class="lk">🔒</div><p>{e(why)}</p>
<a class="btn" href="/signup?as={audience}">Create your free account</a>
</div></div></div>"""


# ---------- public pages ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    u = acct(current(request)) if current(request) else None
    fv = C.FEATURED_VIDEO
    ft, fs, fslug, fq = fv["title"], fv["speaker"], fv["slug"], e(fv["quote"])
    prodsecs = "".join(f'<h4 class="ph">{e(t)}</h4><p class="pp">{e(b)}</p>'
                       for t, b in P.PRODUCT["sections"])
    whyparas = "".join(f'<p class="pp">{e(x)}</p>' for x in P.WHY["paras"])
    connparas = "".join(f'<div><p class="pp">{e(x)}</p></div>' for x in P.CONNECTIVE["paras"])
    home_ld = json.dumps({"@context": "https://schema.org", "@graph": [
        ORG_LD["@graph"][0], ORG_LD["@graph"][1],
        json.loads(product_ld()),
        json.loads(faq_ld([(q, a) for q, a in C.FAQ]))]})
    mods = "".join(f"""<div class="card"><div class="kicker">Clinical education</div>
<h3>{m['title']}</h3><p>{e(m['body'][:150])}…</p></div>""" for m in C.MODULES[:3])
    iore = "".join(f"<li>{e(b)}</li>" for b in C.IORE_BULLETS)
    return HTMLResponse(shell(f"""
<div class="hero">
<video autoplay muted loop playsinline preload="metadata"
 poster="/static/img/wj-ss-vial.png"><source src="/static/video/hero-v2.mp4" type="video/mp4"></video>
<div class="scrim"></div>
<div class="in">
<h1 class="hero-h1"><span class="t">Wharton</span> <span class="o">Jelly</span></h1>
<p class="lead">{e(C.TAGLINE)}</p>
<p class="sub">{e(C.SUBLINE)}</p>
<div class="cta">
<a class="btn lg" href="/providers">For doctors &amp; providers</a>
<a class="btn lg" href="/patients">For consumers &amp; patients</a>
</div></div></div>


<section id="product"><div class="wrap">
<div class="prod">
<div class="prodimg"><img src="{P.PRODUCT['image']}?v=3" alt="{e(P.PRODUCT['image_alt'])}"
 width="572" height="1600" loading="eager" decoding="async" fetchpriority="high"></div>
<div>
<div class="kicker" style="color:var(--orange);font-weight:800;letter-spacing:.09em;
font-size:12px;text-transform:uppercase">The formulation</div>
<h2 style="margin:8px 0 4px">{e(P.PRODUCT['h2'])}</h2>
<h3 style="margin:0 0 22px;font-size:21px;color:var(--teal);font-weight:800">
{e(P.PRODUCT['h3'])}</h3>
{prodsecs}
<div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:24px">
<a class="btn" href="/providers/apply">Provider access</a>
<a class="btn ghost" href="/sourcing">How it is sourced</a>
</div></div></div></div></section>

<section id="why"><div class="wrap">
<div class="two-col">
<div><h2>{e(P.WHY['title'])}</h2>{whyparas}</div>
<div class="factbox">
<h3 style="margin-top:0;font-size:17px">At a glance</h3>
<ul class="facts">
<li>Highest concentration of mesenchymal stem cells per millilitre of the extracellular-matrix-rich tissues</li>
<li>Collagen types I, III and V, elastin and fibronectin</li>
<li>A natural source of long-chain hyaluronic acid</li>
<li>Considered “immune privileged”</li>
</ul></div></div></div></section>

<section id="connective"><div class="wrap">
<div class="kicker" style="color:var(--orange);font-weight:800;letter-spacing:.09em;
font-size:12px;text-transform:uppercase">For clinicians</div>
<h2 style="margin:8px 0 14px">{e(P.CONNECTIVE['title'])}</h2>
<div class="two-col">{connparas}</div>
<p style="margin-top:20px"><a class="btn ghost" href="/science">The science in depth →</a></p>
</div></section>
<section><div class="wrap">
<h2>Two paths. <span class="t">Pick yours.</span></h2>
<p class="lede">Clinicians integrating biologics into practice need protocols, training and
supply. Patients need to understand their options and find a provider near them.</p>
<div class="grid">
<div class="card"><div class="kicker">Clinicians</div>
<h3>Provider program</h3>
<p>Advanced support, documentation, protocols and product access — plus our central education
and clinical support hub.</p>
<p style="margin-top:14px"><a class="btn sm" href="/providers">Provider access →</a></p></div>
<div class="card"><div class="kicker">Patients</div>
<h3>Understand your options</h3>
<p>What these products are, what they are not, and the questions worth asking before you decide.</p>
<p style="margin-top:14px"><a class="btn sm teal" href="/patients">Patient information →</a></p></div>
<div class="card"><div class="kicker">Education</div>
<h3>{e(C.IORE_NAME)}</h3>
<p>{e(C.IORE_HEADLINE)}</p>
<p style="margin-top:14px"><a class="btn sm ghost" href="/education">Explore →</a></p></div>
</div></div></section>

<section><div class="wrap">
<h2>Clinical education, <span class="t">not marketing hype</span></h2>
<p class="lede">Our education partner is the {e(C.IORE_NAME)}. {e(C.IORE_SUB)}.</p>
<ul class="lede" style="line-height:2">{iore}</ul>
{gate(f'<div class="grid">{mods}</div>',
      "Clinical modules, protocols and documentation are available to registered providers.",
      "provider")}
</div></section>


<section id="featured"><div class="wrap">
<div class="kicker" style="color:var(--orange);font-weight:800;letter-spacing:.09em;
font-size:12px;text-transform:uppercase">Featured</div>
<h2 style="margin:8px 0 26px">{ft} <span class="t">with {fs}</span></h2>
<div class="feature">
<a class="fthumb" href="/videos/{fslug}" aria-label="Play: {ft}">
<div class="vplay">▶</div>
<div class="vlock">🔒</div></a>
<div>
<p class="fq">{fq}</p>
<p class="mut" style="font-size:14px;margin:0 0 18px">
Watch the full video free — tell us whether you are a doctor or a patient and it opens
full screen.</p>
<div style="display:flex;gap:12px;flex-wrap:wrap">
<a class="btn" href="/videos/{fslug}">▶ Play the video</a>
<a class="btn ghost" href="/videos">Browse the library</a>
</div></div></div></div></section>
<div class="joinstrip"><div class="in">
<h3>Doctors — join the referral network</h3>
<a class="btn" style="background:#04141a" href="/providers/apply">Doctors Join Now</a>
</div></div>
<style>{VIDEO_CSS}</style>
""", user=u, title=f"{C.BRAND} — {C.TAGLINE}",
        desc=f"{C.TAGLINE} {C.SUBLINE} {P.PRODUCT['h2']}, {P.PRODUCT['h3']}.",
        canon="/", ld=home_ld))


@app.get("/providers", response_class=HTMLResponse)
def providers_page(request: Request):
    u = acct(current(request)) if current(request) else None
    items = "".join(f"<li>{e(x)}</li>" for x in C.HUB_ITEMS)
    mods = "".join(f"""<div class="card"><div class="kicker">Module</div>
<h3>{m['title']}</h3><p>{e(m['body'])}</p></div>"""
                   for m in C.MODULES if m["audience"] == "provider")
    return HTMLResponse(shell(f"""
<section style="border-top:0"><div class="wrap">
<div class="kicker" style="color:var(--orange);font-weight:800;letter-spacing:.09em;
font-size:12px;text-transform:uppercase">For doctors &amp; providers</div>
<h2 style="margin-top:8px">Advanced support, documentation,<br><span class="t">protocols and product access.</span></h2>
<p class="lede">{e(C.HUB_INTRO)}</p>
<ul class="lede" style="line-height:2">{items}</ul>
<p class="lede">{e(C.HUB_CLOSE)}</p>
<a class="btn lg" href="/providers/apply">Apply for provider access</a>
</div></section>

<section id="referrals"><div class="wrap">
<h2>Patient <span class="t">referral network</span></h2>
<p class="lede">Patients who request information through this site are routed to a participating
provider by ZIP code. Providers control whether they receive referrals, and a single provider may
hold a ZIP exclusively.</p>
<div class="grid">
<div class="card"><div class="kicker">Routing</div><h3>By ZIP code</h3>
<p>Enquiries are matched to the provider covering that ZIP. Two providers in the same ZIP share
them evenly, round-robin.</p></div>
<div class="card"><div class="kicker">Exclusivity</div><h3>${EXCLUSIVE_PRICE:,}/month</h3>
<p>Hold a ZIP outright and take every enquiry from it. Available on request from your provider
portal.</p></div>
<div class="card"><div class="kicker">On joining</div><h3>Nothing is wasted</h3>
<p>Enquiries already received for your ZIP before you joined are attached to your account when
you activate referrals.</p></div>
</div></div></section>

<section><div class="wrap">
<h2>Clinical modules</h2>
<p class="lede">Descriptions below are reproduced from our clinical education material.</p>
{gate(f'<div class="grid">{mods}</div>',
      "Full modules, protocols and documentation are available to registered providers.",
      "provider")}
</div></section>
""", user=u, title="For doctors & providers — Wharton Jelly"))


@app.get("/patients", response_class=HTMLResponse)
def patients_page(request: Request):
    u = acct(current(request)) if current(request) else None
    cons = [m for m in C.MODULES if m["audience"] == "consumer"]
    body = "".join(f"""<div class="card"><div class="kicker">Patient education</div>
<h3>{m['title']}</h3><p>{e(m['body'])}</p></div>""" for m in cons)
    return HTMLResponse(shell(f"""
<section style="border-top:0"><div class="wrap">
<div class="kicker" style="color:var(--orange);font-weight:800;letter-spacing:.09em;
font-size:12px;text-transform:uppercase">For consumers &amp; patients</div>
<h2 style="margin-top:8px">Understand your options<br><span class="t">before you decide.</span></h2>
<p class="lede">These products are not drugs and do not treat diseases. What follows explains
what they are, how providers use them, and what to ask.</p>
{gate(f'<div class="grid">{body}</div>',
      "Patient education and provider matching are available once you create a free account.",
      "consumer")}
<p style="margin-top:26px"><a class="btn lg" href="/signup?as=consumer">Find a provider near me</a></p>
</div></section>

<section><div class="wrap">
<h2>How matching <span class="t">works</span></h2>
<div class="grid">
<div class="card"><h3>1. Tell us your ZIP</h3><p>We match you to a participating provider
covering your area.</p></div>
<div class="card"><h3>2. A provider is notified</h3><p>Your enquiry goes to their portal with
your contact details and what you asked about.</p></div>
<div class="card"><h3>3. They reach out</h3><p>Any treatment decision is between you and your
licensed provider.</p></div>
</div></div></section>
""", user=u, title="For consumers & patients — Wharton Jelly"))


@app.get("/science", response_class=HTMLResponse)
def science_page(request: Request):
    u = acct(current(request)) if current(request) else None
    m = next(x for x in C.MODULES if x["slug"] == "allogeneic-science")
    return HTMLResponse(shell(f"""
<section style="border-top:0"><div class="wrap">
<h2>The <span class="t">science</span></h2>
<p class="lede">Reproduced from our clinical education material.</p>
<div class="card" style="max-width:820px"><h3>{m['title']}</h3><p>{e(m['body'])}</p></div>
{gate('<div class="grid"><div class="card"><h3>Protocols</h3><p>Recommended protocols and '
      'evolving best practices.</p></div><div class="card"><h3>Documentation</h3>'
      '<p>Clinical resources designed to support confidence, compliance, and growth.</p></div></div>',
      "Protocols and documentation are available to registered providers.", "provider")}
</div></section>""", user=u, title="The science — Wharton Jelly"))


@app.get("/education", response_class=HTMLResponse)
def education_page(request: Request):
    u = acct(current(request)) if current(request) else None
    feats = "".join(f'<div class="card"><h3>{e(f)}</h3></div>' for f in C.IORE_FEATURES)
    bl = "".join(f"<li>{e(b)}</li>" for b in C.IORE_BULLETS)
    return HTMLResponse(shell(f"""
<section style="border-top:0"><div class="wrap">
<h2>{e(C.IORE_NAME)}</h2>
<p class="lede">{e(C.IORE_HEADLINE)} — {e(C.IORE_SUB)}.</p>
<ul class="lede" style="line-height:2">{bl}</ul>
<div class="grid">{feats}</div>
<p class="lede" style="margin-top:26px">{e(C.HUB_CLOSE)}</p>
{gate('<div class="card"><h3>Private clinical community</h3><p>' + e(C.FB_NOTE).capitalize()
      + '.</p><p style="margin-top:12px"><a class="btn sm ghost" href="/go/community">'
      'Request access →</a></p></div>',
      "Community access is available to registered providers.", "provider")}
<p style="margin-top:22px"><a class="btn ghost" href="/go/iore">
Visit {e(C.IORE_NAME)} →</a></p>
</div></section>""", user=u, title=f"{C.IORE_NAME} — Wharton Jelly"))


# ---------- auth & signup ----------
STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY",
          "LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND",
          "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"]


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request,
                as_: str = Query("consumer", alias="as"),
                err: str = ""):
    # "as" is a Python keyword, so the query parameter is aliased.
    as_ = (as_ or "consumer").lower()
    if as_ not in ("provider", "consumer"):
        as_ = "consumer"
    if current(request):
        return RedirectResponse("/portal", 303)
    ee = f'<div class="err">{e(err)}</div>' if err else ""
    opts = "".join(f'<option value="{s}">{s}</option>' for s in STATES)
    if as_ == "provider":
        fields = f"""
<div class="two"><div><label>First name</label><input name="first" required></div>
<div><label>Last name</label><input name="last" required></div></div>
<label>Clinic or practice</label><input name="clinic" required>
<label>NPI</label><input name="npi" required inputmode="numeric" placeholder="10-digit NPI">
<label>Business address</label><input name="business_address" required>
<div class="three"><div><label>City</label><input name="city" required></div>
<div><label>State</label><select name="state" required>{opts}</select></div>
<div><label>ZIP</label><input name="zip" required inputmode="numeric" maxlength="10"></div></div>
<div class="two"><div><label>Phone</label><input name="phone" type="tel" required></div>
<div><label>Email</label><input name="email" type="email" required></div></div>
<label>Password <span class="mut">(9+ characters)</span></label>
<input name="password" type="password" required autocomplete="new-password">"""
        head = "Provider access"
        sub = ("Advanced support, documentation, protocols and product access. "
               "Your details are reviewed before referral routing is switched on.")
    else:
        fields = f"""
<div class="two"><div><label>First name</label><input name="first" required></div>
<div><label>Last name</label><input name="last" required></div></div>
<div class="two"><div><label>Email</label><input name="email" type="email" required></div>
<div><label>Phone</label><input name="phone" type="tel" required></div></div>
<div class="three"><div><label>City</label><input name="city"></div>
<div><label>State</label><select name="state">{opts}</select></div>
<div><label>ZIP</label><input name="zip" required inputmode="numeric" maxlength="10"></div></div>
<label>What are you looking for? <span class="mut">(optional)</span></label>
<textarea name="interest" rows="3"></textarea>
<label>Password <span class="mut">(9+ characters)</span></label>
<input name="password" type="password" required autocomplete="new-password">"""
        head = "Create your account"
        sub = "We match you to a participating provider covering your ZIP code."
    other = "consumer" if as_ == "provider" else "provider"
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="card form"><h2 style="font-size:26px">{head}</h2>
<p class="mut" style="margin:0 0 6px">{sub}</p>{ee}
<form method="post" action="/signup?as={as_}">{fields}
<button class="btn" type="submit" style="width:100%;margin-top:20px">Create account</button>
</form>
<p class="mut" style="margin-top:14px;font-size:13.5px">
Already registered? <a href="/login">Log in</a> ·
<a href="/signup?as={other}">I'm a {other}</a></p>
</div></div></section>""", title=head))


@app.post("/signup")
async def signup(request: Request):
    form = await request.form()
    as_ = (request.query_params.get("as") or "consumer").lower()
    as_ = "provider" if as_ == "provider" else "consumer"
    g = lambda k: (form.get(k) or "").strip()
    email, pw = g("email").lower(), form.get("password") or ""
    zip_ = re.sub(r"[^0-9]", "", g("zip"))[:5]

    def back(msg):
        from urllib.parse import quote_plus
        return RedirectResponse(f"/signup?as={as_}&err={quote_plus(msg)}", 303)

    if "@" not in email or "." not in email.split("@")[-1]:
        return back("Please give a valid email address")
    if len(pw) < 9:
        return back("Password must be at least 9 characters")
    if not zip_ or len(zip_) < 5:
        return back("A 5-digit ZIP code is required")
    if as_ == "provider" and not re.fullmatch(r"\d{10}", re.sub(r"\D", "", g("npi"))):
        return back("NPI must be 10 digits")

    salt = secrets.token_hex(16)
    with closing(db()) as c:
        if c.execute("SELECT 1 FROM accounts WHERE email=?", (email,)).fetchone():
            return back("That email already has an account")
        uid = c.execute("""INSERT INTO accounts(email,pw_hash,salt,role,first,last,phone,created)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (email, hash_pw(pw, salt), salt, as_, g("first"), g("last"),
                         g("phone"), time.time())).lastrowid
        if as_ == "provider":
            c.execute("""INSERT INTO providers(account_id,clinic,npi,city,state,zip,
                         business_address,accepts_referrals,created)
                         VALUES(?,?,?,?,?,?,?,1,?)""",
                      (uid, g("clinic"), re.sub(r"\D", "", g("npi")), g("city"), g("state"),
                       zip_, g("business_address"), time.time()))
        else:
            c.execute("""INSERT INTO consumers(account_id,city,state,zip,interest,created)
                         VALUES(?,?,?,?,?,?)""",
                      (uid, g("city"), g("state"), zip_, g("interest"), time.time()))
        lead_id = c.execute("""INSERT INTO leads(kind,account_id,created,zip,source,status)
                               VALUES(?,?,?,?,?,'new')""",
                            (as_, uid, time.time(), zip_, "website")).lastrowid
        c.commit()

    request.session["uid"] = uid
    if as_ == "consumer":
        route_consumer(lead_id, zip_)
    _notify_new(as_, email, g, zip_, lead_id)
    return RedirectResponse("/portal", 303)


def _notify_new(kind, email, g, zip_, lead_id):
    rows = [("Name", f"{g('first')} {g('last')}".strip()), ("Email", email),
            ("Phone", g("phone")), ("ZIP", zip_)]
    if kind == "provider":
        rows += [("Clinic", g("clinic")), ("NPI", re.sub(r"\D", "", g("npi"))),
                 ("Address", g("business_address")),
                 ("City/State", f"{g('city')}, {g('state')}")]
    else:
        rows += [("City/State", f"{g('city')}, {g('state')}"), ("Interest", g("interest"))]
    tr = "".join(f'<tr><td style="padding:6px 16px 6px 0;color:#697084;font-size:13px">{e(k)}</td>'
                 f'<td style="padding:6px 0;font-size:14.5px"><b>{e(v) or "—"}</b></td></tr>'
                 for k, v in rows)
    body = f"""<div style="background:#f6f7f9;padding:26px">
<table style="max-width:620px;margin:0 auto;background:#fff;border:1px solid #e2e5ea;
border-radius:12px;width:100%;font:14px/1.6 -apple-system,sans-serif;border-collapse:collapse">
<tr><td style="padding:22px 24px;border-bottom:1px solid #e2e5ea">
<div style="font:800 12px sans-serif;color:#ff7a1a;letter-spacing:.08em">
NEW {kind.upper()} LEAD</div>
<h2 style="margin:6px 0 0;font-size:21px">{e(g('first'))} {e(g('last'))}</h2></td></tr>
<tr><td style="padding:16px 24px"><table style="border-collapse:collapse">{tr}</table></td></tr>
<tr><td style="padding:14px 24px;border-top:1px solid #e2e5ea">
<a href="https://whartonjelly.com/crm/lead/{lead_id}" style="display:inline-block;
background:#ff7a1a;color:#fff;text-decoration:none;font-weight:700;padding:10px 18px;
border-radius:8px">Open in CRM</a></td></tr></table></div>"""
    subject = f"🧬 New {kind} lead — {g('first')} {g('last')}".strip()
    email_out(OWNER_EMAIL, subject, body)
    with closing(db()) as c:
        sales = [r["email"] for r in c.execute("SELECT email FROM accounts WHERE role='sales'")]
    if kind == "provider":
        for s in sales:
            email_out(s, subject, body)
    push_to_monday(lead_id)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, err: str = ""):
    if current(request):
        return RedirectResponse("/portal", 303)
    ee = f'<div class="err">{e(err)}</div>' if err else ""
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="card form" style="max-width:420px"><h2 style="font-size:25px">Log in</h2>{ee}
<form method="post" action="/login">
<label>Email</label><input name="email" type="email" required autofocus>
<label>Password</label><input name="password" type="password" required>
<button class="btn" type="submit" style="width:100%;margin-top:18px">Log in</button></form>
<p class="mut" style="margin-top:14px;font-size:13.5px">No account?
<a href="/signup?as=provider">Provider</a> · <a href="/signup?as=consumer">Patient</a></p>
</div></div></section>""", title="Log in"))


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    with closing(db()) as c:
        a = c.execute("SELECT * FROM accounts WHERE email=?", (email.strip().lower(),)).fetchone()
    if not a or not a["pw_hash"] or not hmac.compare_digest(hash_pw(password, a["salt"]),
                                                           a["pw_hash"]):
        return RedirectResponse("/login?err=Incorrect+email+or+password", 303)
    request.session["uid"] = a["id"]
    with closing(db()) as c:
        c.execute("UPDATE accounts SET last_login=? WHERE id=?", (time.time(), a["id"]))
        c.commit()
    if a["must_change"]:
        return RedirectResponse("/change-password", 303)
    return RedirectResponse("/portal", 303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)


@app.get("/change-password", response_class=HTMLResponse)
def cp_form(request: Request, err: str = "", uid=Depends(require)):
    a = acct(uid)
    ee = f'<div class="err">{e(err)}</div>' if err else ""
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="card form" style="max-width:420px"><h2 style="font-size:24px">Set your password</h2>
<p class="mut">Your temporary password must be replaced before you continue.</p>{ee}
<form method="post" action="/change-password">
<label>New password <span class="mut">(9+ characters)</span></label>
<input type="password" name="p1" required autofocus>
<label>Confirm</label><input type="password" name="p2" required>
<button class="btn" type="submit" style="width:100%;margin-top:18px">Set password</button>
</form></div></div></section>""", user=a, title="Set password"))


@app.post("/change-password")
def cp(request: Request, p1: str = Form(...), p2: str = Form(...), uid=Depends(require)):
    if p1 != p2:
        return RedirectResponse("/change-password?err=Passwords+do+not+match", 303)
    if len(p1) < 9:
        return RedirectResponse("/change-password?err=Use+at+least+9+characters", 303)
    salt = secrets.token_hex(16)
    with closing(db()) as c:
        c.execute("UPDATE accounts SET pw_hash=?, salt=?, must_change=0, invite_token=NULL "
                  "WHERE id=?", (hash_pw(p1, salt), salt, uid))
        c.commit()
    return RedirectResponse("/portal", 303)


@app.get("/invite/{token}", response_class=HTMLResponse)
def invite(token: str, request: Request):
    with closing(db()) as c:
        a = c.execute("SELECT * FROM accounts WHERE invite_token=?", (token,)).fetchone()
    if not a:
        return HTMLResponse(shell('<section style="border-top:0"><div class="wrap">'
                                  '<div class="card form"><h2>This invitation has expired</h2>'
                                  '<p class="mut">Ask for a new one, or '
                                  '<a href="/login">log in</a>.</p></div></div></section>',
                                  title="Invitation"), status_code=404)
    request.session["uid"] = a["id"]
    return RedirectResponse("/change-password", 303)


# ---------- Monday.com integration ----------
def monday_cfg():
    return setting("monday_token"), setting("monday_board")


def push_to_monday(lead_id):
    """Create the lead as an item on the configured board. Inert without a token,
    so the funnel works before the integration is connected."""
    token, board = monday_cfg()
    if not (token and board):
        return False
    with closing(db()) as c:
        l = c.execute("""SELECT l.*, a.email, a.first, a.last, a.phone
                         FROM leads l LEFT JOIN accounts a ON a.id=l.account_id
                         WHERE l.id=?""", (lead_id,)).fetchone()
        p = c.execute("SELECT * FROM providers WHERE account_id=?", (l["account_id"],)).fetchone() \
            if l else None
    if not l:
        return False
    name = f"{l['first'] or ''} {l['last'] or ''}".strip() or l["email"] or f"Lead {lead_id}"
    notes = [f"kind: {l['kind']}", f"email: {l['email']}", f"phone: {l['phone']}",
             f"zip: {l['zip']}"]
    if p:
        notes += [f"clinic: {p['clinic']}", f"npi: {p['npi']}",
                  f"address: {p['business_address']}"]
    col = json.dumps({"text": " | ".join(x for x in notes if x)})
    q = ("mutation ($b:ID!,$n:String!,$c:JSON!){create_item(board_id:$b,item_name:$n,"
         "column_values:$c){id}}")
    payload = json.dumps({"query": q, "variables": {"b": board, "n": name, "c": col}})
    import subprocess
    try:
        r = subprocess.run(["curl", "-sS", "--max-time", "25", "-X", "POST",
                            "-H", f"Authorization: {token}",
                            "-H", "Content-Type: application/json",
                            "-H", "API-Version: 2024-01",
                            "-d", payload, "https://api.monday.com/v2"],
                           capture_output=True, text=True, timeout=35)
        d = json.loads(r.stdout)
        item = (((d.get("data") or {}).get("create_item") or {}).get("id"))
        if item:
            with closing(db()) as c:
                c.execute("UPDATE leads SET monday_item=? WHERE id=?", (str(item), lead_id))
                c.commit()
            return True
    except Exception:
        pass
    return False


@app.post("/api/monday/webhook")
async def monday_webhook(request: Request):
    """Inbound half of the bi-directional link. Monday posts a challenge on setup,
    then updates; each update lands as a timestamped CRM note."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False}, 400)
    if "challenge" in body:
        return JSONResponse({"challenge": body["challenge"]})
    ev = body.get("event") or {}
    item = str(ev.get("pulseId") or ev.get("itemId") or "")
    text = (ev.get("value") or {}).get("label", {}).get("text") if isinstance(
        ev.get("value"), dict) else None
    text = text or json.dumps(ev.get("value"))[:300]
    if item:
        with closing(db()) as c:
            l = c.execute("SELECT id FROM leads WHERE monday_item=?", (item,)).fetchone()
            if l:
                c.execute("""INSERT INTO lead_notes(lead_id,author_id,ts,note,source)
                             VALUES(?,?,?,?,'monday')""",
                          (l["id"], None, time.time(),
                           f"Monday update — {ev.get('columnTitle') or ev.get('type') or 'change'}"
                           f": {text}"))
                c.commit()
    return JSONResponse({"ok": True})


# ---------- portals ----------
@app.get("/portal", response_class=HTMLResponse)
def portal(request: Request, uid=Depends(require)):
    a = acct(uid)
    if a["must_change"]:
        return RedirectResponse("/change-password", 303)
    if a["role"] in ("owner", "sales"):
        return RedirectResponse("/crm", 303)
    if a["role"] == "provider":
        with closing(db()) as c:
            p = c.execute("SELECT * FROM providers WHERE account_id=?", (uid,)).fetchone()
            refs = c.execute("""SELECT l.*, ac.first, ac.last, ac.email, ac.phone, co.interest
                                FROM leads l LEFT JOIN accounts ac ON ac.id=l.account_id
                                LEFT JOIN consumers co ON co.account_id=l.account_id
                                WHERE l.assigned_provider=? ORDER BY l.created DESC""",
                             (uid,)).fetchall()
        tr = "".join(
            f'<tr><td class="mut">{time.strftime("%b %d", time.localtime(r["created"]))}</td>'
            f'<td><b>{e((r["first"] or "") + " " + (r["last"] or ""))}</b></td>'
            f'<td><a href="mailto:{e(r["email"] or "")}">{e(r["email"] or "")}</a>'
            f'<div class="mut" style="font-size:12.5px">{e(r["phone"] or "")}</div></td>'
            f'<td class="mut">{e(r["zip"] or "")}</td>'
            f'<td class="mut">{e((r["interest"] or "")[:60])}</td></tr>' for r in refs)
        on = p and p["accepts_referrals"]
        verified = p and p["verified_purchaser"]
        excl = p and p["exclusive"]
        gate_note = "" if verified else (
            '<div class="note"><b>Referrals are not yet active.</b> Participation in the referral '
            'network requires an active product account. We will confirm and switch this on.</div>')
        return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<h2>Provider portal</h2>
<p class="lede">{e(p["clinic"] or "")} · NPI {e(p["npi"] or "")} ·
{e(p["city"] or "")}, {e(p["state"] or "")} {e(p["zip"] or "")}</p>
{gate_note}
<div class="grid" style="margin-bottom:26px">
<div class="card"><div class="kicker">Referrals</div>
<h3>{"On" if on else "Off"}</h3>
<p>Patient enquiries in your ZIP are {"routed to you" if on else "not routed to you"}.</p>
<form method="post" action="/portal/referrals" style="margin-top:12px">
<input type="hidden" name="on" value="{0 if on else 1}">
<button class="btn sm {'ghost' if on else ''}" type="submit">
{"Turn off referrals" if on else "Turn on referrals"}</button></form></div>
<div class="card"><div class="kicker">ZIP {e(p["zip"] or "")}</div>
<h3>{"Exclusive" if excl else "Shared"}</h3>
<p>{"You receive every enquiry from this ZIP." if excl else
    f"Enquiries are shared round-robin. Exclusivity is ${EXCLUSIVE_PRICE:,}/month."}</p>
{"" if excl else f'<form method="post" action="/portal/exclusive" style="margin-top:12px">'
 f'<button class="btn sm" type="submit">Request exclusive ZIP</button></form>'}</div>
<div class="card"><div class="kicker">Education</div><h3>{e(C.IORE_NAME)}</h3>
<p>{e(C.IORE_HEADLINE)}</p>
<p style="margin-top:12px"><a class="btn sm ghost" href="/go/iore">Open →</a></p></div>
</div>
<h2 style="font-size:22px">Your referrals</h2>
{f'<table><thead><tr><th>When</th><th>Patient</th><th>Contact</th><th>ZIP</th><th>Interest</th>'
 f'</tr></thead><tbody>{tr}</tbody></table>' if refs else
 '<p class="mut">No referrals yet. They appear here as patients in your ZIP register.</p>'}
</div></section>""", user=a, title="Provider portal"))

    with closing(db()) as c:
        co = c.execute("SELECT * FROM consumers WHERE account_id=?", (uid,)).fetchone()
        l = c.execute("""SELECT l.*, p.clinic, ac.first pf, ac.last pl, ac.phone pp, ac.email pe
                         FROM leads l LEFT JOIN providers p ON p.account_id=l.assigned_provider
                         LEFT JOIN accounts ac ON ac.id=l.assigned_provider
                         WHERE l.account_id=? ORDER BY l.created DESC LIMIT 1""",
                      (uid,)).fetchone()
    mods = "".join(f'<div class="card"><div class="kicker">Patient education</div>'
                   f'<h3>{m["title"]}</h3><p>{e(m["body"])}</p></div>'
                   for m in C.MODULES if m["audience"] == "consumer")
    if l and l["assigned_provider"]:
        match = (f'<div class="card"><div class="kicker">Your provider</div>'
                 f'<h3>{e(l["clinic"] or "")}</h3>'
                 f'<p>{e((l["pf"] or "") + " " + (l["pl"] or ""))}<br>'
                 f'{e(l["pp"] or "")}<br>{e(l["pe"] or "")}</p></div>')
    else:
        match = ('<div class="card"><div class="kicker">Your provider</div>'
                 '<h3>Matching in progress</h3><p>We are identifying a participating provider '
                 'for your ZIP. You will hear from us.</p></div>')
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<h2>Welcome{", " + e(a["first"]) if a["first"] else ""}</h2>
<p class="lede">Your patient education library and provider match.</p>
<div class="grid">{match}{mods}</div>
</div></section>""", user=a, title="Your account"))


@app.post("/portal/referrals")
def toggle_ref(request: Request, on: int = Form(...), uid=Depends(require_role("provider"))):
    with closing(db()) as c:
        c.execute("UPDATE providers SET accepts_referrals=? WHERE account_id=?", (int(on), uid))
        c.commit()
        p = c.execute("SELECT zip, verified_purchaser FROM providers WHERE account_id=?",
                      (uid,)).fetchone()
    if int(on) and p and p["verified_purchaser"]:
        backfill_for_provider(uid, p["zip"])
    return RedirectResponse("/portal", 303)


@app.post("/portal/exclusive")
def request_exclusive(request: Request, uid=Depends(require_role("provider"))):
    a = acct(uid)
    with closing(db()) as c:
        p = c.execute("SELECT * FROM providers WHERE account_id=?", (uid,)).fetchone()
    email_out(OWNER_EMAIL, f"💳 Exclusive ZIP request — {p['zip']} — {a['email']}",
              f"""<div style="font:14px/1.6 -apple-system,sans-serif;padding:22px">
<h2 style="margin:0 0 8px">Exclusive ZIP requested</h2>
<p><b>{e(a['first'] or '')} {e(a['last'] or '')}</b> — {e(p['clinic'] or '')}<br>
{e(a['email'])} · {e(a['phone'] or '')}</p>
<p>ZIP <b>{e(p['zip'] or '')}</b> at ${EXCLUSIVE_PRICE:,}/month.</p>
<p style="color:#697084">Stripe is {"connected" if setting("stripe_sk") else
"NOT configured on this instance — take payment manually"}.</p></div>""")
    return RedirectResponse("/portal?requested=1", 303)


# ---------- CRM (owner + sales) ----------
@app.get("/crm", response_class=HTMLResponse)
def crm(request: Request, kind: str = "", uid=Depends(require_role("owner", "sales"))):
    a = acct(uid)
    where, args = "", []
    if kind in ("provider", "consumer"):
        where, args = "WHERE l.kind=?", [kind]
    with closing(db()) as c:
        rows = c.execute(f"""SELECT l.*, ac.first, ac.last, ac.email, ac.phone,
                               p.clinic, p.npi, p.city, p.state,
                               (SELECT COUNT(*) FROM lead_notes n WHERE n.lead_id=l.id) notes
                             FROM leads l
                             LEFT JOIN accounts ac ON ac.id=l.account_id
                             LEFT JOIN providers p ON p.account_id=l.account_id
                             {where} ORDER BY l.created DESC LIMIT 400""", args).fetchall()
        tot = c.execute("SELECT kind, COUNT(*) n FROM leads GROUP BY kind").fetchall()
    counts = {r["kind"]: r["n"] for r in tot}
    tr = "".join(
        f'<tr><td class="mut">{time.strftime("%b %d %H:%M", time.localtime(r["created"]))}</td>'
        f'<td><span class="pill {"teal" if r["kind"]=="provider" else "mut"}">{e(r["kind"])}</span></td>'
        f'<td><b>{e((r["first"] or "") + " " + (r["last"] or ""))}</b>'
        f'{f"<div class=mut style=font-size:12.5px>{e(r[chr(99)+chr(108)+chr(105)+chr(110)+chr(105)+chr(99)] or chr(34)+chr(34))}</div>" if r["clinic"] else ""}</td>'
        f'<td><a href="mailto:{e(r["email"] or "")}">{e(r["email"] or "")}</a>'
        f'<div class="mut" style="font-size:12.5px">{e(r["phone"] or "")}</div></td>'
        f'<td class="mut">{e(r["zip"] or "")}</td>'
        f'<td><span class="pill">{e(r["status"])}</span></td>'
        f'<td class="mut">{r["notes"]}</td>'
        f'<td><a class="btn ghost sm" href="/crm/lead/{r["id"]}">Open</a></td></tr>' for r in rows)
    tabs = "".join(
        f'<a class="btn {"" if kind==k else "ghost"} sm" href="/crm{"?kind="+k if k else ""}">'
        f'{lbl}{" " + str(counts.get(k, 0)) if k else " " + str(sum(counts.values()))}</a>'
        for k, lbl in (("", "All"), ("provider", "Providers"), ("consumer", "Patients")))
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<h2>CRM</h2><p class="lede">Every enquiry, timestamped, with notes.</p>
<div style="display:flex;gap:9px;margin-bottom:16px">{tabs}</div>
{f'<table><thead><tr><th>When</th><th>Type</th><th>Name</th><th>Contact</th><th>ZIP</th>'
 f'<th>Status</th><th>Notes</th><th></th></tr></thead><tbody>{tr}</tbody></table>'
 if rows else '<p class="mut">No leads yet.</p>'}
</div></section>""", user=a, title="CRM"))


@app.get("/crm/lead/{lid}", response_class=HTMLResponse)
def crm_lead(lid: int, request: Request, uid=Depends(require_role("owner", "sales"))):
    a = acct(uid)
    with closing(db()) as c:
        l = c.execute("""SELECT l.*, ac.first, ac.last, ac.email, ac.phone, ac.created acct_created
                         FROM leads l LEFT JOIN accounts ac ON ac.id=l.account_id
                         WHERE l.id=?""", (lid,)).fetchone()
        if not l:
            raise HTTPException(404)
        p = c.execute("SELECT * FROM providers WHERE account_id=?", (l["account_id"],)).fetchone()
        co = c.execute("SELECT * FROM consumers WHERE account_id=?", (l["account_id"],)).fetchone()
        notes = c.execute("""SELECT n.*, ac.email author FROM lead_notes n
                             LEFT JOIN accounts ac ON ac.id=n.author_id
                             WHERE n.lead_id=? ORDER BY n.ts DESC""", (lid,)).fetchall()
        assigned = c.execute("""SELECT ac.email, p.clinic FROM providers p
                                JOIN accounts ac ON ac.id=p.account_id
                                WHERE p.account_id=?""", (l["assigned_provider"],)).fetchone() \
            if l["assigned_provider"] else None
    def row(k, v):
        return f'<tr><td class="mut" style="white-space:nowrap">{e(k)}</td><td>{e(str(v or "—"))}</td></tr>'
    detail = row("Type", l["kind"]) + row("Received",
              time.strftime("%d %b %Y %H:%M", time.localtime(l["created"]))) \
        + row("Name", f"{l['first'] or ''} {l['last'] or ''}".strip()) \
        + row("Email", l["email"]) + row("Phone", l["phone"]) + row("ZIP", l["zip"]) \
        + row("Source", l["source"]) + row("Monday item", l["monday_item"])
    if p:
        detail += (row("Clinic", p["clinic"]) + row("NPI", p["npi"])
                   + row("Business address", p["business_address"])
                   + row("City / State", f"{p['city']}, {p['state']}")
                   + row("Accepts referrals", "yes" if p["accepts_referrals"] else "no")
                   + row("Verified purchaser", "yes" if p["verified_purchaser"] else "no"))
    if co:
        detail += row("Interest", co["interest"])
    if assigned:
        detail += row("Routed to", f"{assigned['clinic']} ({assigned['email']})")
    nl = "".join(
        f'<div class="card" style="margin-bottom:10px"><div class="mut" style="font-size:12.5px">'
        f'{time.strftime("%d %b %H:%M", time.localtime(n["ts"]))} · '
        f'{e(n["author"] or n["source"])}</div><div>{e(n["note"])}</div></div>' for n in notes)
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<p class="mut"><a href="/crm">← CRM</a></p>
<h2>{e((l["first"] or "") + " " + (l["last"] or "")) or e(l["email"] or "Lead")}</h2>
<div class="grid" style="grid-template-columns:1.1fr .9fr">
<div><table>{detail}</table></div>
<div><h3 style="margin-top:0">Notes</h3>
<form method="post" action="/crm/lead/{lid}/note" style="margin-bottom:16px">
<textarea name="note" rows="3" placeholder="What happened on this lead?" required></textarea>
<button class="btn sm" type="submit" style="margin-top:9px">Add note</button></form>
{nl or '<p class="mut">No notes yet.</p>'}</div>
</div></div></section>""", user=a, title="Lead"))


@app.post("/crm/lead/{lid}/note")
def crm_note(lid: int, request: Request, note: str = Form(...),
             uid=Depends(require_role("owner", "sales"))):
    if note.strip():
        with closing(db()) as c:
            c.execute("""INSERT INTO lead_notes(lead_id,author_id,ts,note,source)
                         VALUES(?,?,?,?,'crm')""", (lid, uid, time.time(), note.strip()))
            c.commit()
    return RedirectResponse(f"/crm/lead/{lid}", 303)


# ---------- owner admin ----------
@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, saved: str = "", uid=Depends(require_role("owner"))):
    a = acct(uid)
    with closing(db()) as c:
        team = c.execute("SELECT * FROM accounts WHERE role IN ('sales','owner') ORDER BY id").fetchall()
        provs = c.execute("""SELECT ac.email, ac.first, ac.last, p.* FROM providers p
                             JOIN accounts ac ON ac.id=p.account_id ORDER BY p.created DESC""").fetchall()
    tm = "".join(f'<tr><td>{e(r["email"])}</td><td>{e((r["first"] or "")+" "+(r["last"] or ""))}</td>'
                 f'<td><span class="pill">{e(r["role"])}</span></td>'
                 f'<td class="mut">{"invited — not yet set up" if r["invite_token"] else ("never logged in" if not r["last_login"] else time.strftime("%d %b %H:%M", time.localtime(r["last_login"])))}</td></tr>'
                 for r in team)
    pv = "".join(
        f'<tr><td><b>{e(r["clinic"] or "")}</b><div class="mut" style="font-size:12.5px">'
        f'{e((r["first"] or "")+" "+(r["last"] or ""))} · {e(r["email"])}</div></td>'
        f'<td class="mut">{e(r["zip"] or "")}</td>'
        f'<td>{"<span class=ok>on</span>" if r["accepts_referrals"] else "<span class=mut>off</span>"}</td>'
        f'<td>{"<span class=ok>yes</span>" if r["verified_purchaser"] else "<span class=bad>no</span>"}</td>'
        f'<td><form method="post" action="/admin/provider/{r["account_id"]}/verify">'
        f'<input type="hidden" name="v" value="{0 if r["verified_purchaser"] else 1}">'
        f'<button class="btn sm {"ghost" if r["verified_purchaser"] else ""}" type="submit">'
        f'{"Revoke" if r["verified_purchaser"] else "Verify"}</button></form></td></tr>'
        for r in provs)
    slots = "".join(
        f'<tr><td class="mut">{e(lbl)}</td><td><code>{e(slot)}</code></td>'
        f'<td><form method="post" action="/admin/image" class="two" style="gap:8px">'
        f'<input type="hidden" name="slot" value="{slot}">'
        f'<input name="path" placeholder="/static/img/…" value="{e(setting("img_" + slot))}">'
        f'<button class="btn sm" type="submit">Save</button></form></td></tr>'
        for slot, lbl in C.IMAGE_SLOTS)
    note = '<div class="note">Saved.</div>' if saved else ""
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<h2>Admin</h2>{note}

<h3>Integrations</h3>
<p class="mut">Monday receives every new lead. The webhook posts updates back as CRM notes.</p>
<form method="post" action="/admin/settings" class="card" style="max-width:720px">
<div class="two">
<div><label>Monday API token</label>
<input name="monday_token" type="password" value="{e(setting('monday_token'))}"
 placeholder="eyJhbGci…"></div>
<div><label>Monday board ID</label>
<input name="monday_board" value="{e(setting('monday_board'))}" placeholder="1234567890"></div>
</div>
<div class="two">
<div><label>Stripe publishable key</label>
<input name="stripe_pk" value="{e(setting('stripe_pk'))}" placeholder="pk_live_…"></div>
<div><label>Stripe secret key</label>
<input name="stripe_sk" type="password" value="{e(setting('stripe_sk'))}"
 placeholder="sk_live_…"></div>
</div>
<label>Exclusive ZIP price (USD / month)</label>
<input name="exclusive_price" value="{e(setting('exclusive_price', str(EXCLUSIVE_PRICE)))}">
<button class="btn" type="submit" style="margin-top:16px">Save integrations</button>
</form>
<p class="mut" style="font-size:13.5px">Monday webhook URL —
<code>https://whartonjelly.com/api/monday/webhook</code></p>

<h3 style="margin-top:34px">Team</h3>
<table><thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Last login</th></tr></thead>
<tbody>{tm}</tbody></table>
<form method="post" action="/admin/invite" class="card" style="max-width:640px;margin-top:14px">
<div class="three"><div><label>First name</label><input name="first" required></div>
<div><label>Last name</label><input name="last" required></div>
<div><label>Role</label><select name="role"><option value="sales">Sales manager</option></select></div></div>
<label>Email</label><input name="email" type="email" required>
<button class="btn" type="submit" style="margin-top:14px">Send invitation</button></form>

<h3 style="margin-top:34px">Providers</h3>
<p class="mut">Referral participation requires an active product account — verify here.</p>
<table><thead><tr><th>Provider</th><th>ZIP</th><th>Referrals</th><th>Verified</th><th></th></tr>
</thead><tbody>{pv or '<tr><td colspan=5 class=mut>None yet</td></tr>'}</tbody></table>

<h3 style="margin-top:34px">Images</h3>
<p class="mut">Replace any image on the site by pointing its slot at a new file.</p>
<table><thead><tr><th>Slot</th><th>Key</th><th>Path</th></tr></thead><tbody>{slots}</tbody></table>
</div></section>""", user=a, title="Admin"))


@app.post("/admin/settings")
async def admin_settings(request: Request, uid=Depends(require_role("owner"))):
    form = await request.form()
    for k in ("monday_token", "monday_board", "stripe_pk", "stripe_sk", "exclusive_price"):
        if k in form:
            set_setting(k, (form.get(k) or "").strip())
    return RedirectResponse("/admin?saved=1", 303)


@app.post("/admin/image")
def admin_image(request: Request, slot: str = Form(...), path: str = Form(""),
                uid=Depends(require_role("owner"))):
    set_setting("img_" + slot, path.strip())
    with closing(db()) as c:
        c.execute("""INSERT INTO images(slot,path,updated) VALUES(?,?,?)
                     ON CONFLICT(slot) DO UPDATE SET path=excluded.path, updated=excluded.updated""",
                  (slot, path.strip(), time.time()))
        c.commit()
    return RedirectResponse("/admin?saved=1", 303)


@app.post("/admin/provider/{pid}/verify")
def admin_verify(pid: int, request: Request, v: int = Form(...),
                 uid=Depends(require_role("owner"))):
    with closing(db()) as c:
        c.execute("UPDATE providers SET verified_purchaser=? WHERE account_id=?", (int(v), pid))
        c.commit()
        p = c.execute("SELECT zip, accepts_referrals FROM providers WHERE account_id=?",
                      (pid,)).fetchone()
    if int(v) and p and p["accepts_referrals"]:
        n = backfill_for_provider(pid, p["zip"])
        if n:
            a = acct(pid)
            email_out(a["email"], f"{n} patient enquiries are waiting for you",
                      f"""<div style="font:14px/1.6 -apple-system,sans-serif;padding:22px">
<h2>You have {n} waiting enquir{'y' if n == 1 else 'ies'}</h2>
<p>Enquiries received for ZIP {e(p['zip'])} before you joined have been attached to your
account.</p><a href="https://whartonjelly.com/portal" style="display:inline-block;
background:#ff7a1a;color:#fff;text-decoration:none;font-weight:700;padding:10px 18px;
border-radius:8px">Open your portal</a></div>""")
    return RedirectResponse("/admin?saved=1", 303)


@app.post("/admin/invite")
def admin_invite(request: Request, email: str = Form(...), first: str = Form(""),
                 last: str = Form(""), role: str = Form("sales"),
                 uid=Depends(require_role("owner"))):
    email = email.strip().lower()
    role = role if role in ("sales",) else "sales"
    token = secrets.token_urlsafe(24)
    with closing(db()) as c:
        ex = c.execute("SELECT id FROM accounts WHERE email=?", (email,)).fetchone()
        if ex:
            c.execute("UPDATE accounts SET role=?, invite_token=?, must_change=1 WHERE id=?",
                      (role, token, ex["id"]))
        else:
            c.execute("""INSERT INTO accounts(email,role,first,last,must_change,invite_token,created)
                         VALUES(?,?,?,?,1,?,?)""",
                      (email, role, first.strip(), last.strip(), token, time.time()))
        c.commit()
    email_out(email, "You have been invited to the Wharton Jelly CRM",
              f"""<div style="background:#f6f7f9;padding:26px">
<table style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e5ea;
border-radius:12px;width:100%;font:14px/1.6 -apple-system,sans-serif">
<tr><td style="padding:24px 26px">
<h2 style="margin:0 0 8px;font-size:21px">Hello {e(first)},</h2>
<p>You have been given a sales manager account for the Wharton Jelly provider CRM. You will see
every provider enquiry as it arrives, with full contact details, and can add notes.</p>
<p>Set your own password using the link below — it is single-use.</p>
<a href="https://whartonjelly.com/invite/{token}" style="display:inline-block;background:#ff7a1a;
color:#fff;text-decoration:none;font-weight:800;padding:12px 22px;border-radius:8px;
margin:10px 0">Set my password</a>
<p style="color:#697084;font-size:12.5px">If the button does not work, paste this into your
browser:<br>https://whartonjelly.com/invite/{token}</p>
</td></tr></table></div>""")
    return RedirectResponse("/admin?saved=1", 303)


@app.get("/healthz")
def healthz():
    with closing(db()) as c:
        return {"ok": True,
                "accounts": c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"],
                "leads": c.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"],
                "monday": bool(setting("monday_token")),
                "stripe": bool(setting("stripe_sk"))}


# ---------- provider application ----------
@app.get("/providers/apply", response_class=HTMLResponse)
def providers_apply(request: Request):
    """Was linked from three places before it existed. It is the provider signup,
    given its own URL and framing so the funnel reads as an application."""
    if current(request):
        return RedirectResponse("/portal", 303)
    return RedirectResponse("/signup?as=provider", 303)


# ---------- module pages ----------
@app.get("/modules", response_class=HTMLResponse)
def modules_index(request: Request):
    u = acct(current(request)) if current(request) else None
    cards = "".join(f"""<a class="card" style="text-decoration:none;color:inherit;display:block"
href="/modules/{m['slug']}"><div class="kicker">
{'Clinical education' if m['audience']=='provider' else 'Patient education'}</div>
<h3>{m['title']}</h3><p>{e(m['body'][:130])}…</p>
<p style="margin-top:12px;color:var(--teal);font-weight:700;font-size:14px">Read →</p></a>"""
                    for m in C.MODULES)
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<h2>Education <span class="t">library</span></h2>
<p class="lede">Clinical and patient modules, reproduced from our education material.
Validation and protocols are provided through the {e(C.IORE_NAME)}, an independent third
party.</p>
<div class="grid">{cards}</div></div></section>""", user=u, title="Education library"))


@app.get("/modules/{slug}", response_class=HTMLResponse)
def module_page(slug: str, request: Request):
    u = acct(current(request)) if current(request) else None
    m = next((x for x in C.MODULES if x["slug"] == slug), None)
    if not m:
        raise HTTPException(404)
    signed_in = bool(u)
    audience = m["audience"]
    others = "".join(f'<a class="card" style="text-decoration:none;color:inherit;display:block" '
                     f'href="/modules/{o["slug"]}"><h3 style="font-size:16px">{o["title"]}</h3></a>'
                     for o in C.MODULES if o["slug"] != slug)
    full = f'<div class="card" style="max-width:820px"><p>{e(m["body"])}</p></div>'
    body = full if signed_in else gate(full,
        "Full modules are available to registered members.", audience)
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<p class="mut"><a href="/modules">← Education library</a></p>
<div class="kicker" style="color:var(--orange);font-weight:800;letter-spacing:.09em;
font-size:12px;text-transform:uppercase">
{'For providers' if audience == 'provider' else 'For patients'}</div>
<h2 style="margin-top:8px">{m['title']}</h2>
{body}
<h3 style="margin-top:34px">More from the library</h3>
<div class="grid">{others}</div>
</div></section>""", user=u, title=m["title"]))


@app.get("/faq", response_class=HTMLResponse)
def faq_page(request: Request):
    u = acct(current(request)) if current(request) else None
    pairs = list(C.FAQ) + list(P.SOURCING)
    items = "".join(f'<div class="card" style="margin-bottom:12px">'
                    f'<h3 itemprop="name">{e(q)}</h3>'
                    f'<p itemprop="text">{e(a)}</p></div>' for q, a in pairs)
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<h2>Common <span class="t">questions</span></h2>
<p class="lede">Answers drawn from our clinical, patient and sourcing material.</p>
<div style="max-width:860px" itemscope itemtype="https://schema.org/FAQPage">{items}</div>
<p style="margin-top:26px"><a class="btn ghost" href="/sourcing">Full sourcing process →</a></p>
</div></section>""", user=u, title="Common questions — Wharton Jelly",
        desc="Answers on Wharton's Jelly: what it is, how it is screened, processed, tested and "
             "distributed, and how providers should describe it to patients.",
        canon="/faq", ld=faq_ld(pairs)))


# ---------- footer enquiry desks ----------
@app.get("/connect/{slug}", response_class=HTMLResponse)
def connect_form(slug: str, request: Request, err: str = "", sent: str = ""):
    u = acct(current(request)) if current(request) else None
    d = next((x for x in C.CONNECT if x[0] == slug), None)
    if not d:
        raise HTTPException(404)
    _, title, sub, hint = d
    if sent:
        return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="card form" style="text-align:center;max-width:560px">
<div style="font-size:44px;line-height:1;margin-bottom:8px">✅</div>
<h2 style="font-size:25px">Thank you</h2>
<p class="mut">Your enquiry about <b>{e(title)}</b> has reached us. We read every one and will
come back to you.</p>
<a class="btn" href="/">Back to the site</a></div></div></section>""",
            user=u, title=f"{title} — sent"))
    ee = f'<div class="err">{e(err)}</div>' if err else ""
    opts = "".join(f'<option value="{s}">{s}</option>' for s in STATES)
    others = "".join(f'<a href="/connect/{s}">{e(t)}</a>'
                     for s, t, _, _ in C.CONNECT if s != slug)
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div style="display:grid;grid-template-columns:.85fr 1.15fr;gap:34px;align-items:start;
max-width:1020px;margin:0 auto" class="cwrap">
<div>
<div class="kicker" style="color:var(--orange);font-weight:800;letter-spacing:.09em;
font-size:12px;text-transform:uppercase">Get in touch</div>
<h2 style="margin:8px 0 10px;font-size:32px">{e(title)}</h2>
<p class="lede" style="margin-bottom:20px">{e(sub)}</p>
<p class="mut" style="font-size:14px;border-top:1px solid var(--line);padding-top:16px">
Other desks</p>
<div style="display:flex;flex-direction:column;gap:6px">{others}</div>
</div>
<div class="card form" style="margin:0;max-width:none">
<h3 style="margin:0 0 4px;font-size:19px">Send us your details</h3>
<p class="mut" style="font-size:14px;margin:0 0 4px">{e(hint)}</p>{ee}
<form method="post" action="/connect/{slug}">
<div class="two"><div><label>First name</label><input name="first" required></div>
<div><label>Last name</label><input name="last" required></div></div>
<div class="two"><div><label>Email</label><input name="email" type="email" required></div>
<div><label>Phone</label><input name="phone" type="tel" required></div></div>
<div class="three"><div><label>City</label><input name="city"></div>
<div><label>State</label><select name="state"><option value=""></option>{opts}</select></div>
<div><label>ZIP</label><input name="zip" inputmode="numeric" maxlength="10"></div></div>
<label>Website</label><input name="website" placeholder="https://">
<label>Anything you would like to share</label>
<textarea name="message" rows="4" placeholder="{e(hint)}"></textarea>
<button class="btn" type="submit" style="width:100%;margin-top:18px">Submit</button>
</form></div></div></div></section>
<style>@media(max-width:860px){{.cwrap{{grid-template-columns:1fr!important}}}}</style>""",
        user=u, title=f"{title} — Wharton Jelly"))


@app.post("/connect/{slug}")
async def connect_submit(slug: str, request: Request):
    d = next((x for x in C.CONNECT if x[0] == slug), None)
    if not d:
        raise HTTPException(404)
    _, title, _, _ = d
    form = await request.form()
    g = lambda k: (form.get(k) or "").strip()
    first, last, email, phone = g("first"), g("last"), g("email").lower(), g("phone")
    from urllib.parse import quote_plus
    if not first or not last:
        return RedirectResponse(f"/connect/{slug}?err={quote_plus('Please give your name')}", 303)
    if "@" not in email or "." not in email.split("@")[-1]:
        return RedirectResponse(
            f"/connect/{slug}?err={quote_plus('Please give a valid email address')}", 303)
    if not phone:
        return RedirectResponse(
            f"/connect/{slug}?err={quote_plus('A phone number is required')}", 303)

    zip_ = re.sub(r"[^0-9]", "", g("zip"))[:5]
    detail = " | ".join(x for x in [
        f"desk: {title}", f"city: {g('city')}", f"state: {g('state')}", f"zip: {zip_}",
        f"website: {g('website')}", f"message: {g('message')}"] if not x.endswith(": "))

    with closing(db()) as c:
        lid = c.execute("""INSERT INTO leads(kind,account_id,created,zip,source,status)
                           VALUES('partner',NULL,?,?,?,'new')""",
                        (time.time(), zip_, f"connect:{slug}")).lastrowid
        c.execute("""INSERT INTO lead_notes(lead_id,author_id,ts,note,source)
                     VALUES(?,NULL,?,?,'form')""",
                  (lid, time.time(),
                   f"{first} {last} · {email} · {phone}\n{detail}"))
        c.commit()

    # Into the JV pipeline at CORE, then a notification.
    core_jv(f"{first} {last}".strip(), email, phone, f"[JV/{title}] {detail}")
    rows = [("Desk", title), ("Name", f"{first} {last}"), ("Email", email), ("Phone", phone),
            ("City", g("city")), ("State", g("state")), ("ZIP", zip_),
            ("Website", g("website")), ("Message", g("message"))]
    tr = "".join(f'<tr><td style="padding:6px 16px 6px 0;color:#697084;font-size:13px;'
                 f'white-space:nowrap">{e(k)}</td>'
                 f'<td style="padding:6px 0;font-size:14.5px"><b>{e(v) or "—"}</b></td></tr>'
                 for k, v in rows)
    email_out(OWNER_EMAIL, f"🤝 {title} — {first} {last}",
              f"""<div style="background:#f6f7f9;padding:26px">
<table style="max-width:620px;margin:0 auto;background:#fff;border:1px solid #e2e5ea;
border-radius:12px;width:100%;font:14px/1.6 -apple-system,sans-serif;border-collapse:collapse">
<tr><td style="padding:22px 24px;border-bottom:1px solid #e2e5ea">
<div style="font:800 12px sans-serif;color:#ff7a1a;letter-spacing:.08em">
{e(title.upper())}</div>
<h2 style="margin:6px 0 0;font-size:21px">{e(first)} {e(last)}</h2></td></tr>
<tr><td style="padding:16px 24px"><table style="border-collapse:collapse">{tr}</table></td></tr>
<tr><td style="padding:14px 24px;border-top:1px solid #e2e5ea">
<a href="mailto:{e(email)}" style="display:inline-block;background:#ff7a1a;color:#fff;
text-decoration:none;font-weight:700;padding:10px 18px;border-radius:8px">
Reply to {e(first)}</a></td></tr></table></div>""")
    return RedirectResponse(f"/connect/{slug}?sent=1", 303)


def core_jv(name, email, phone, notes):
    """Push a partnership enquiry into the JV pipeline at CORE."""
    if not (CORE_KEY and CORE_SECRET):
        return False
    import subprocess
    payload = json.dumps({"name": name, "email": email, "phone": phone or "n/a",
                          "creatorRef": "whartonjelly.com", "notes": notes[:1000]})
    for i in range(3):
        try:
            p = subprocess.run(["curl", "-sS", "--max-time", "25", "-X", "POST",
                                "-H", f"x-core-key: {CORE_KEY}",
                                "-H", f"x-core-secret: {CORE_SECRET}",
                                "-H", "content-type: application/json", "-d", payload,
                                CORE + "/api/core/lead"], capture_output=True, text=True,
                               timeout=35)
            if json.loads(p.stdout).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(1.2 * (i + 1))
    return False


# ---------- outbound gate ----------
def ext(key, label=None, cls="", btn=False):
    """Render an outbound link as a gated hop. Nothing leaves this site without
    us knowing who is leaving."""
    dest = C.OUTBOUND.get(key)
    if not dest:
        return ""
    text = label or dest[1]
    c = f'class="{cls}"' if cls else ""
    return f'<a {c} href="/go/{key}">{e(text)}{" →" if btn else ""}</a>'


def _record_outbound(uid, key, request):
    with closing(db()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS outbound(
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, dest TEXT,
            ts REAL, ip TEXT)""")
        c.execute("INSERT INTO outbound(account_id,dest,ts,ip) VALUES(?,?,?,?)",
                  (uid, key, time.time(),
                   (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                    or (request.client.host if request.client else ""))))
        c.commit()


@app.get("/go/{key}", response_class=HTMLResponse)
def outbound(key: str, request: Request, step: str = "", err: str = ""):
    dest = C.OUTBOUND.get(key)
    if not dest:
        raise HTTPException(404)
    url, name, why = dest
    uid = current(request)

    # Known visitor: we already hold their details, so record and let them through.
    if uid:
        a = acct(uid)
        if not a["must_change"]:
            _record_outbound(uid, key, request)
            with closing(db()) as c:
                c.execute("""INSERT INTO lead_notes(lead_id,author_id,ts,note,source)
                             SELECT id, NULL, ?, ?, 'system' FROM leads
                             WHERE account_id=? ORDER BY id DESC LIMIT 1""",
                          (time.time(), f"Followed outbound link to {name}.", uid))
                c.commit()
            return HTMLResponse(f"""<!doctype html><meta charset="utf-8">
<meta http-equiv="refresh" content="0;url={e(url)}">
<title>Continuing…</title><body style="background:#04141a;color:#e9f4f6;
font:16px -apple-system,sans-serif;padding:60px;text-align:center">
Taking you to {e(name)}… <a style="color:#19c2c9" href="{e(url)}">continue</a></body>""")

    # Unknown visitor: choose audience, then give us your details.
    if step not in ("provider", "consumer"):
        return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="card form" style="max-width:620px;text-align:center">
<div style="font-size:34px;line-height:1;margin-bottom:6px">🔒</div>
<h2 style="font-size:26px;margin-bottom:6px">Before you continue</h2>
<p class="mut" style="margin:0 0 4px">You are about to visit <b>{e(name)}</b>.</p>
<p class="mut" style="margin:0 0 22px;font-size:14px">{e(why)}</p>
<p style="font-weight:700;margin:0 0 14px">First — which are you?</p>
<div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
<a class="btn" href="/go/{key}?step=provider">I'm a doctor or provider</a>
<a class="btn teal" href="/go/{key}?step=consumer">I'm a consumer or patient</a>
</div>
<p class="mut" style="margin-top:18px;font-size:13px">Already registered?
<a href="/login?next=/go/{key}">Log in</a> and you will go straight through.</p>
</div></div></section>""", title=f"Before you continue — {name}"))

    ee = f'<div class="err">{e(err)}</div>' if err else ""
    opts = "".join(f'<option value="{s}">{s}</option>' for s in STATES)
    if step == "provider":
        extra = f"""<label>Clinic or practice</label><input name="clinic" required>
<label>NPI</label><input name="npi" required inputmode="numeric" placeholder="10-digit NPI">
<label>Business address</label><input name="business_address" required>"""
        head = "Doctor & provider details"
    else:
        extra = """<label>What are you looking for? <span class="mut">(optional)</span></label>
<textarea name="interest" rows="3"></textarea>"""
        head = "Your details"
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="card form" style="max-width:620px">
<p class="mut" style="margin:0"><a href="/go/{key}">← Back</a></p>
<h2 style="font-size:24px;margin:6px 0 4px">{head}</h2>
<p class="mut" style="margin:0 0 6px;font-size:14px">
We will take you to <b>{e(name)}</b> as soon as this is complete.</p>{ee}
<form method="post" action="/go/{key}?step={step}">
<div class="two"><div><label>First name</label><input name="first" required autofocus></div>
<div><label>Last name</label><input name="last" required></div></div>
<div class="two"><div><label>Email</label><input name="email" type="email" required></div>
<div><label>Phone</label><input name="phone" type="tel" required></div></div>
<div class="three"><div><label>City</label><input name="city"></div>
<div><label>State</label><select name="state"><option value=""></option>{opts}</select></div>
<div><label>ZIP</label><input name="zip" required inputmode="numeric" maxlength="10"></div></div>
{extra}
<label>Create a password <span class="mut">(9+ characters)</span></label>
<input name="password" type="password" required autocomplete="new-password">
<button class="btn" type="submit" style="width:100%;margin-top:18px">
Continue to {e(name)}</button>
</form></div></div></section>""", title=f"{head} — {name}"))


@app.post("/go/{key}")
async def outbound_submit(key: str, request: Request, step: str = ""):
    dest = C.OUTBOUND.get(key)
    if not dest or step not in ("provider", "consumer"):
        raise HTTPException(404)
    url, name, _ = dest
    form = await request.form()
    g = lambda k: (form.get(k) or "").strip()
    from urllib.parse import quote_plus
    back = lambda m: RedirectResponse(f"/go/{key}?step={step}&err={quote_plus(m)}", 303)

    email, pw = g("email").lower(), form.get("password") or ""
    zip_ = re.sub(r"[^0-9]", "", g("zip"))[:5]
    if "@" not in email or "." not in email.split("@")[-1]:
        return back("Please give a valid email address")
    if len(pw) < 9:
        return back("Password must be at least 9 characters")
    if not zip_ or len(zip_) < 5:
        return back("A 5-digit ZIP code is required")
    if step == "provider" and not re.fullmatch(r"\d{10}", re.sub(r"\D", "", g("npi"))):
        return back("NPI must be 10 digits")

    salt = secrets.token_hex(16)
    with closing(db()) as c:
        ex = c.execute("SELECT id FROM accounts WHERE email=?", (email,)).fetchone()
        if ex:
            return back("That email already has an account — please log in")
        uid = c.execute("""INSERT INTO accounts(email,pw_hash,salt,role,first,last,phone,created)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (email, hash_pw(pw, salt), salt, step, g("first"), g("last"),
                         g("phone"), time.time())).lastrowid
        if step == "provider":
            c.execute("""INSERT INTO providers(account_id,clinic,npi,city,state,zip,
                         business_address,accepts_referrals,created)
                         VALUES(?,?,?,?,?,?,?,1,?)""",
                      (uid, g("clinic"), re.sub(r"\D", "", g("npi")), g("city"), g("state"),
                       zip_, g("business_address"), time.time()))
        else:
            c.execute("""INSERT INTO consumers(account_id,city,state,zip,interest,created)
                         VALUES(?,?,?,?,?,?)""",
                      (uid, g("city"), g("state"), zip_, g("interest"), time.time()))
        lead_id = c.execute("""INSERT INTO leads(kind,account_id,created,zip,source,status)
                               VALUES(?,?,?,?,?,'new')""",
                            (step, uid, time.time(), zip_, f"outbound:{key}")).lastrowid
        c.execute("""INSERT INTO lead_notes(lead_id,author_id,ts,note,source)
                     VALUES(?,NULL,?,?,'system')""",
                  (lead_id, time.time(),
                   f"Captured at the outbound gate on the way to {name}."))
        c.commit()

    request.session["uid"] = uid
    if step == "consumer":
        route_consumer(lead_id, zip_)
    _notify_new(step, email, g, zip_, lead_id)     # owner + sales email, and Monday
    _record_outbound(uid, key, request)
    return RedirectResponse(url, 303)


# ---------- video library ----------
def _videos_for(role):
    """Consumers see consumer videos. Providers see everything, because clinical
    material is written for them and the patient video is what they show patients."""
    if role == "provider":
        return list(C.VIDEOS)
    if role == "consumer":
        return [v for v in C.VIDEOS if v["audience"] == "consumer"]
    return []


def _tile(v, unlocked):
    playable = bool(v.get("embed"))
    badge = next((t for k, t, _, _ in C.VIDEO_CATEGORIES if k == v["category"]), "")
    lock = "" if unlocked else '<div class="vlock">🔒</div>'
    href = f'/videos/{v["slug"]}'
    state = "" if playable else '<div class="soon">Coming soon</div>'
    return f"""<a class="vtile{'' if playable else ' pending'}" href="{href}">
<div class="vthumb">{lock}<div class="vplay">▶</div>{state}</div>
<div class="vmeta"><div class="vcat">{e(badge)}</div>
<h3>{v['title']}</h3>
<p>{e(v['desc'][:110])}…</p>
<div class="vspk">{e(v['speaker'])}</div></div></a>"""


VIDEO_CSS = """
.vgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(288px,1fr));gap:18px}
.vtile{display:block;text-decoration:none;color:inherit;background:var(--panel);
border:1px solid var(--line);border-radius:14px;overflow:hidden;transition:border-color .15s,transform .15s}
.vtile:hover{border-color:var(--teal);transform:translateY(-2px)}
.vtile.pending{opacity:.62}
.vthumb{position:relative;aspect-ratio:16/9;
background:radial-gradient(120% 120% at 30% 20%,#123a44 0%,#08222a 60%,#061a21 100%);
display:flex;align-items:center;justify-content:center}
.vplay{width:56px;height:56px;border-radius:50%;background:var(--orange);color:#fff;
display:flex;align-items:center;justify-content:center;font-size:21px;padding-left:4px;
box-shadow:0 6px 22px rgba(255,122,26,.35)}
.vlock{position:absolute;top:11px;right:12px;font-size:15px;opacity:.85}
.soon{position:absolute;bottom:10px;left:12px;font-size:11px;letter-spacing:.06em;
text-transform:uppercase;color:var(--mut);font-weight:800}
.vmeta{padding:16px}
.vcat{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--teal);
font-weight:800;margin-bottom:6px}
.vtile h3{margin:0 0 6px;font-size:16px;letter-spacing:-.015em;line-height:1.3}
.vtile p{margin:0 0 8px;color:var(--mut);font-size:13.5px}
.vspk{color:var(--mut);font-size:12.5px;font-weight:700}
.feature{display:grid;grid-template-columns:1.05fr .95fr;gap:30px;align-items:center}
.prod{display:grid;grid-template-columns:.82fr 1.18fr;gap:40px;align-items:center}
@media(max-width:900px){.prod{grid-template-columns:1fr}}
.prodimg{background:radial-gradient(70% 70% at 50% 40%,#12333d 0%,#08222a 60%,#061a21 100%);
border:1px solid var(--line);border-radius:18px;padding:20px;display:flex;
align-items:center;justify-content:center;min-height:640px}
.prodimg img{max-width:100%;height:auto;max-height:690px;object-fit:contain;
background:#fff;border-radius:12px;padding:14px;
filter:drop-shadow(0 26px 52px rgba(0,0,0,.6))}
@media(max-width:900px){.prodimg{min-height:0}.prodimg img{max-height:520px}}
.ph{margin:18px 0 5px;font-size:17px;letter-spacing:-.01em;color:var(--teal)}
.pp{color:var(--mut);margin:0;font-size:15.5px;line-height:1.75;max-width:70ch}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:28px}
@media(max-width:820px){.two-col{grid-template-columns:1fr}}
.factbox{background:var(--panel);border:1px solid var(--teal);border-radius:15px;padding:22px;
align-self:start}
.facts{list-style:none;padding:0;margin:0}
.facts li{padding:8px 0 8px 24px;position:relative;color:var(--mut);font-size:14.5px;
border-bottom:1px solid var(--line)}
.facts li:last-child{border-bottom:0}
.facts li:before{content:"◆";position:absolute;left:0;color:var(--teal);font-size:11px;top:11px}
@media(max-width:900px){.feature{grid-template-columns:1fr}}
.fthumb{position:relative;aspect-ratio:16/9;border-radius:16px;overflow:hidden;
background:radial-gradient(120% 120% at 30% 20%,#134450 0%,#08222a 60%,#061a21 100%);
display:flex;align-items:center;justify-content:center;border:1px solid var(--line)}
.fthumb .vplay{width:78px;height:78px;font-size:28px}
.fq{border-left:3px solid var(--teal);padding:2px 0 2px 16px;color:var(--mut);font-size:15px;
line-height:1.7;margin:16px 0 22px}
.player{position:relative;aspect-ratio:16/9;border-radius:14px;overflow:hidden;
border:1px solid var(--line);background:#000}
.player iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
"""


@app.get("/videos", response_class=HTMLResponse)
def videos_index(request: Request):
    u = acct(current(request)) if current(request) else None
    role = u["role"] if u else ""
    role = "provider" if role in ("provider", "owner", "sales") else role
    unlocked = bool(u)
    vids = _videos_for(role) if unlocked else C.VIDEOS
    by_cat = {}
    for v in vids:
        by_cat.setdefault(v["category"], []).append(v)
    blocks = ""
    for key, title, aud, sub in C.VIDEO_CATEGORIES:
        items = by_cat.get(key, [])
        if not items:
            continue
        tiles = "".join(_tile(v, unlocked) for v in items)
        blocks += f"""<h3 style="margin:34px 0 4px;font-size:20px">{e(title)}</h3>
<p class="mut" style="margin:0 0 14px;font-size:14px">{e(sub)}
{'· for providers' if aud == 'provider' else '· for patients'}</p>
<div class="vgrid">{tiles}</div>"""
    intro = ("Everything below is available on your account."
             if unlocked else
             "Every video is behind a free account. Tell us whether you are a doctor or a "
             "patient and you will see the library written for you.")
    cta = "" if unlocked else """<div style="display:flex;gap:12px;flex-wrap:wrap;margin:22px 0 8px">
<a class="btn" href="/signup?as=provider">I'm a doctor or provider</a>
<a class="btn teal" href="/signup?as=consumer">I'm a consumer or patient</a></div>"""
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<h2>Video <span class="t">library</span></h2>
<p class="lede">{e(intro)}</p>{cta}
{blocks}
</div></section><style>{VIDEO_CSS}</style>""", user=u, title="Video library"))


@app.get("/videos/{slug}", response_class=HTMLResponse)
def video_page(slug: str, request: Request):
    u = acct(current(request)) if current(request) else None
    v = next((x for x in C.VIDEOS if x["slug"] == slug), None)
    if not v:
        raise HTTPException(404)
    role = u["role"] if u else ""
    role = "provider" if role in ("provider", "owner", "sales") else role
    allowed = bool(u) and v in _videos_for(role)

    if not u:
        return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="card form" style="max-width:640px;text-align:center">
<div style="font-size:34px;line-height:1;margin-bottom:6px">🔒</div>
<h2 style="font-size:25px;margin-bottom:6px">{v['title']}</h2>
<p class="mut" style="margin:0 0 4px">{e(v['speaker'])}</p>
<p class="mut" style="margin:0 0 22px;font-size:14.5px">{e(v['desc'][:190])}…</p>
<p style="font-weight:700;margin:0 0 14px">To watch, tell us which you are</p>
<div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
<a class="btn" href="/signup?as=provider">I'm a doctor or provider</a>
<a class="btn teal" href="/signup?as=consumer">I'm a consumer or patient</a></div>
<p class="mut" style="margin-top:18px;font-size:13px">Already registered?
<a href="/login">Log in</a></p></div></div></section>
<style>{VIDEO_CSS}</style>""", title=v["title"]))

    if not allowed:
        return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="card form" style="max-width:600px;text-align:center">
<h2 style="font-size:23px">This one is written for clinicians</h2>
<p class="mut">Your account is registered as a patient. The patient library is
<a href="/videos">here</a>.</p></div></div></section>""", user=u, title="Not available"))

    player = (f'<div class="player"><iframe src="{e(v["embed"])}" allowfullscreen '
              f'allow="autoplay; fullscreen; picture-in-picture"></iframe></div>'
              if v.get("embed") else
              '<div class="fthumb"><div class="soon" style="position:static;font-size:13px">'
              'This recording is being added to the library.</div></div>')
    more = "".join(_tile(x, True) for x in _videos_for(role) if x["slug"] != slug)
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<p class="mut"><a href="/videos">← Video library</a></p>
<h2 style="margin-bottom:4px">{v['title']}</h2>
<p class="mut" style="margin:0 0 18px">{e(v['speaker'])}</p>
{player}
<p class="lede" style="margin-top:22px;max-width:78ch">{e(v['desc'])}</p>
<h3 style="margin-top:34px;font-size:19px">More in your library</h3>
<div class="vgrid">{more}</div>
</div></section><style>{VIDEO_CSS}</style>""", user=u, title=v["title"]))


# ---------- sourcing, research, richer FAQ ----------
@app.get("/sourcing", response_class=HTMLResponse)
def sourcing_page(request: Request):
    u = acct(current(request)) if current(request) else None
    cards = "".join(f'<div class="card"><div class="kicker">Step</div><h3>{e(t)}</h3>'
                    f'<p>{e(b)}</p></div>' for t, b in P.SOURCING)
    steps = "".join(f'<li>{e(x)}</li>' for x in P.SOURCING_STEPS)
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<div class="kicker" style="color:var(--orange);font-weight:800;letter-spacing:.09em;
font-size:12px;text-transform:uppercase">Sourcing &amp; quality</div>
<h2 style="margin:8px 0 14px">Product <span class="t">sourcing process</span></h2>
<p class="lede">{e(P.SOURCING_INTRO)}</p>
<div class="grid">{cards}</div>
<h3 style="margin:38px 0 12px;font-size:21px">From donation to delivery</h3>
<ol class="steps">{steps}</ol>
</div></section>
<style>.steps{{counter-reset:s;list-style:none;padding:0;margin:0;max-width:900px}}
.steps li{{counter-increment:s;position:relative;padding:14px 0 14px 52px;
border-bottom:1px solid var(--line);color:var(--mut);font-size:15px;line-height:1.7}}
.steps li:last-child{{border-bottom:0}}
.steps li:before{{content:counter(s);position:absolute;left:0;top:12px;width:32px;height:32px;
border-radius:50%;background:var(--panel);border:1px solid var(--teal);color:var(--teal);
display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px}}</style>""",
        user=u, title="Product sourcing process — Wharton Jelly",
        desc=("How Wharton's Jelly is donated, screened, processed in a cGMP facility and "
              "distributed. Prescreening, processing, distribution and lot testing explained."),
        canon="/sourcing",
        ld=faq_ld([(t, b) for t, b in P.SOURCING])))


@app.get("/research", response_class=HTMLResponse)
def research_page(request: Request):
    u = acct(current(request)) if current(request) else None
    paras = "".join(f'<p class="pp" style="margin-bottom:16px">{e(x)}</p>' for x in P.RESEARCH)
    return HTMLResponse(shell(f"""<section style="border-top:0"><div class="wrap">
<h2>Research</h2>
<div style="max-width:78ch">{paras}</div>
{gate('<div class="grid"><div class="card"><h3>Peer-reviewed collection</h3>'
      '<p>Curated publications from our scientific officers and medical board.</p></div>'
      '<div class="card"><h3>Protocols</h3><p>Recommended protocols and evolving best '
      'practices.</p></div></div>',
      "The publication library is available to registered providers.", "provider")}
</div></section>""", user=u, title="Research — Wharton Jelly",
        desc="A curated collection of published peer-reviewed studies in regenerative medicine.",
        canon="/research",
        ld=article_ld("Research", P.RESEARCH[0], "/research")))


# ---------- SEO / AEO surfaces ----------
PUBLIC_URLS = [
    ("/", "1.0", "weekly"), ("/providers", "0.9", "weekly"), ("/patients", "0.9", "weekly"),
    ("/science", "0.8", "monthly"), ("/sourcing", "0.8", "monthly"),
    ("/research", "0.7", "monthly"), ("/education", "0.7", "monthly"),
    ("/videos", "0.8", "weekly"), ("/modules", "0.7", "monthly"), ("/faq", "0.8", "monthly"),
]


@app.get("/sitemap.xml")
def sitemap():
    urls = list(PUBLIC_URLS)
    urls += [(f"/modules/{m['slug']}", "0.6", "monthly") for m in C.MODULES]
    urls += [(f"/videos/{v['slug']}", "0.6", "monthly") for v in C.VIDEOS]
    urls += [(f"/connect/{s}", "0.5", "yearly") for s, _, _, _ in C.CONNECT]
    body = "".join(
        f"<url><loc>https://whartonjelly.com{u}</loc>"
        f"<changefreq>{cf}</changefreq><priority>{pr}</priority></url>"
        for u, pr, cf in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                    media_type="application/xml")


@app.get("/robots.txt")
def robots():
    return Response(
        "User-agent: *\nAllow: /\n"
        "Disallow: /crm\nDisallow: /admin\nDisallow: /portal\nDisallow: /invite\n\n"
        "# Answer engines\nUser-agent: GPTBot\nAllow: /\n"
        "User-agent: PerplexityBot\nAllow: /\n"
        "User-agent: ClaudeBot\nAllow: /\n"
        "User-agent: Google-Extended\nAllow: /\n\n"
        "Sitemap: https://whartonjelly.com/sitemap.xml\n"
        "Sitemap: https://whartonjelly.com/answers.xml\n",
        media_type="text/plain")


@app.get("/answers.xml")
def answers_xml():
    """An answer-engine feed: every question the site answers, with its answer and
    the page it lives on, so a retrieval system can lift a citable passage."""
    qa = [(q, a, "/faq") for q, a in C.FAQ]
    qa += [(t, b, "/sourcing") for t, b in P.SOURCING]
    qa += [(P.WHY["title"], " ".join(P.WHY["paras"]), "/")]
    qa += [(P.CONNECTIVE["title"], " ".join(P.CONNECTIVE["paras"]), "/")]
    qa += [(t, b, "/") for t, b in P.PRODUCT["sections"]]
    qa += [(m["title"], m["body"], f"/modules/{m['slug']}") for m in C.MODULES]
    items = "".join(
        f"<answer><question>{e(q)}</question><text>{e(a)}</text>"
        f"<url>https://whartonjelly.com{u}</url></answer>" for q, a, u in qa)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><answers site="whartonjelly.com" '
                    f'count="{len(qa)}">{items}</answers>', media_type="application/xml")


@app.get("/llms.txt")
def llms_txt():
    """The emerging convention for telling a language model what a site is and
    which pages are worth citing."""
    lines = [f"# {C.BRAND}", "", f"> {C.TAGLINE} {C.SUBLINE}", "",
             f"{P.PRODUCT['h2']} — {P.PRODUCT['h3']}.", "",
             "## Compliance", P.COMPLIANCE if hasattr(P, "COMPLIANCE") else C.COMPLIANCE,
             "", P.LEGAL, "", "## Pages"]
    for u, _, _ in PUBLIC_URLS:
        lines.append(f"- https://whartonjelly.com{u}")
    lines += ["", "## Education partner",
              f"- {C.IORE_NAME} ({C.IORE_URL}) — independent third party",
              "", "## Answer feed", "- https://whartonjelly.com/answers.xml"]
    return Response("\n".join(lines), media_type="text/plain")


@app.get("/schema.json")
def schema_json():
    """One document containing every structured-data block the site publishes,
    so the markup can be inspected or validated without crawling each page."""
    return JSONResponse({
        "organization": ORG_LD,
        "product": json.loads(product_ld()),
        "faq": json.loads(faq_ld(list(C.FAQ) + list(P.SOURCING))),
        "sitemaps": ["https://whartonjelly.com/sitemap.xml",
                     "https://whartonjelly.com/answers.xml"],
        "llms": "https://whartonjelly.com/llms.txt",
    })
