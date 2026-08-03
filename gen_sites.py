#!/usr/bin/env python3
"""
Generate five-page static sites for every domain in the Q (state='queued').

Per site: money-keyword landing page, three supporting keyword pages, a contact
page. Unique title/description/alt text throughout, JSON-LD, sitemap, robots.
Forms POST to the lead proxy. 🚀 fixed bottom-right links to r0cketship.com.

Content is template-driven for now; swap `copy_for()` for a Claude call when an
Anthropic key is available. Nothing else needs to change.
"""
import html, json, os, random, re, sqlite3, sys, time

DB = sys.argv[1] if len(sys.argv) > 1 else "/opt/network-app/network.db"
OUTROOT = sys.argv[2] if len(sys.argv) > 2 else "/var/www/sites"
LEAD_API = "https://network.r0cketship.com/api/lead"
ADDRESS = {"street": "5 Cowboy Way", "city": "Frisco", "state": "TX", "zip": "75034"}
e = html.escape

PALETTES = [
    ("#ff6b1a", "#ffb545", "#1a1d24"), ("#2563eb", "#60a5fa", "#0f172a"),
    ("#059669", "#34d399", "#052e2b"), ("#7c3aed", "#a78bfa", "#1e1b31"),
    ("#dc2626", "#f87171", "#291313"), ("#0891b2", "#22d3ee", "#082f36"),
]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "page"


def titlecase(s):
    small = {"a", "an", "and", "the", "for", "in", "of", "on", "to", "with", "near"}
    w = s.split()
    return " ".join(x.capitalize() if i == 0 or x.lower() not in small else x.lower()
                    for i, x in enumerate(w))


# ---------- art (royalty-free by construction) ----------
def hero_svg(seed, pal, alt):
    rnd = random.Random(seed)
    a, b, dark = pal
    shapes = "".join(
        f'<circle cx="{rnd.randint(0,1200)}" cy="{rnd.randint(0,420)}" '
        f'r="{rnd.randint(40,190)}" fill="{a if i%2 else b}" opacity="{rnd.uniform(.06,.17):.2f}"/>'
        for i in range(9))
    return (f'<svg class="hero-art" viewBox="0 0 1200 420" role="img" aria-label="{e(alt)}" '
            f'xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">'
            f'<defs><linearGradient id="g{seed}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{dark}"/><stop offset="1" stop-color="{a}" stop-opacity=".55"/>'
            f'</linearGradient></defs><rect width="1200" height="420" fill="url(#g{seed})"/>{shapes}</svg>')


def card_svg(seed, pal, alt):
    rnd = random.Random(seed)
    a, b, dark = pal
    bars = "".join(
        f'<rect x="{20+i*52}" y="{200-rnd.randint(40,165)}" width="34" '
        f'height="{rnd.randint(40,165)}" rx="6" fill="{a if i%2 else b}" opacity=".8"/>'
        for i in range(6))
    return (f'<svg class="card-art" viewBox="0 0 340 200" role="img" aria-label="{e(alt)}" '
            f'xmlns="http://www.w3.org/2000/svg"><rect width="340" height="200" fill="{dark}" rx="10"/>{bars}</svg>')


# ---------- copy ----------
def copy_for(kw, domain, kind="support"):
    """Template copy. Replace with a Claude call for genuinely unique content."""
    k = titlecase(kw)
    if kind == "main":
        return {
            "h1": k,
            "lede": f"Straight answers about {kw} — what it costs, how it works, "
                    f"and how to tell a good option from a bad one.",
            "sections": [
                (f"What {k} Actually Involves",
                 f"Most people researching {kw} run into the same problem: every source is "
                 f"selling something. This page lays out how {kw} works in practice, what "
                 f"varies between providers, and which details change the outcome."),
                (f"What It Costs",
                 f"Pricing for {kw} moves with scope, timing, and who you work with. Knowing "
                 f"which factors drive the number lets you compare quotes on equal footing "
                 f"instead of guessing."),
                (f"How to Choose",
                 f"The gap between a good and bad decision on {kw} usually comes down to a "
                 f"few questions asked early. Ask them before you commit, not after."),
            ],
        }
    return {
        "h1": k,
        "lede": f"A focused look at {kw} — the part most overviews skip.",
        "sections": [
            (f"Understanding {k}",
             f"{k} comes up constantly once you start looking seriously. Here's what it "
             f"means, when it matters, and when it safely doesn't."),
            (f"What to Watch For",
             f"A few recurring mistakes cost people real money on {kw}. Each is avoidable "
             f"once you know it exists."),
        ],
    }


# ---------- page chrome ----------
def head(title, desc, domain, path, pal, extra_ld=""):
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="https://{domain}{path}">
<meta property="og:type" content="website"><meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}"><meta property="og:url" content="https://{domain}{path}">
<meta name="twitter:card" content="summary_large_object"><meta name="twitter:title" content="{e(title)}">
<meta name="theme-color" content="{pal[0]}">
<style>{css(pal)}</style>{extra_ld}</head><body>"""


def css(pal):
    a, b, dark = pal
    return f""":root{{--a:{a};--b:{b};--dark:{dark};--bg:#fff;--tx:#14171d;--mut:#5b6472;--line:#e4e7ec;--panel:#f7f8fa}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0f1115;--tx:#e8ebf0;--mut:#98a0b0;--line:#242832;--panel:#161920}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,sans-serif}}
a{{color:var(--a)}}img,svg{{max-width:100%}}
.top{{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line)}}
.top .in{{max-width:1120px;margin:0 auto;padding:13px 22px;display:flex;align-items:center;gap:20px}}
.brand{{font-weight:800;letter-spacing:-.02em;text-decoration:none;color:var(--tx);font-size:17px}}
nav{{display:flex;gap:17px;flex:1;flex-wrap:wrap}}
nav a{{color:var(--mut);text-decoration:none;font-size:14.5px;font-weight:500}}
nav a:hover{{color:var(--a)}}
.login{{border:1px solid var(--line);padding:7px 15px;border-radius:8px;text-decoration:none;
color:var(--tx);font-size:14px;font-weight:600;white-space:nowrap}}
.login:hover{{border-color:var(--a);color:var(--a)}}
.hero{{position:relative;overflow:hidden}}
.hero-art{{width:100%;height:340px;display:block;object-fit:cover}}
.hero .txt{{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;
max-width:1120px;margin:0 auto;padding:0 22px}}
.hero h1{{margin:0 0 10px;font-size:clamp(28px,5vw,46px);line-height:1.1;letter-spacing:-.03em;color:#fff;max-width:15ch}}
.hero p{{margin:0;color:rgba(255,255,255,.9);font-size:clamp(15px,2vw,19px);max-width:52ch}}
main{{max-width:1120px;margin:0 auto;padding:52px 22px 70px}}
section{{margin-bottom:46px}}
h2{{font-size:clamp(21px,3vw,29px);letter-spacing:-.02em;margin:0 0 12px}}
h3{{font-size:18px;margin:0 0 7px}}
p{{color:var(--mut);max-width:70ch}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:22px;margin-top:26px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:13px;overflow:hidden}}
.card-art{{width:100%;height:150px;display:block;object-fit:cover}}
.card .body{{padding:17px}}
.cta{{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:34px;text-align:center}}
.btn{{display:inline-block;background:var(--a);color:#fff;text-decoration:none;font-weight:700;
padding:13px 27px;border-radius:10px;border:0;font-size:15.5px;cursor:pointer}}
form{{display:grid;gap:12px;max-width:460px}}
label{{font-size:13.5px;color:var(--mut);font-weight:600}}
input,textarea{{width:100%;padding:11px 13px;border:1px solid var(--line);border-radius:9px;
background:var(--bg);color:var(--tx);font:inherit}}
textarea{{min-height:110px;resize:vertical}}
footer{{border-top:1px solid var(--line);background:var(--panel)}}
footer .in{{max-width:1120px;margin:0 auto;padding:40px 22px}}
.fgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:30px}}
footer h4{{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);margin:0 0 11px}}
footer a{{display:block;color:var(--tx);text-decoration:none;font-size:14.5px;padding:3px 0}}
footer a:hover{{color:var(--a)}}
.legal{{border-top:1px solid var(--line);padding:19px 22px;text-align:center;color:var(--mut);font-size:13px}}
.rocket{{position:fixed;right:19px;bottom:19px;z-index:60;width:52px;height:52px;border-radius:50%;
background:var(--a);display:flex;align-items:center;justify-content:center;font-size:25px;
text-decoration:none;box-shadow:0 5px 20px rgba(0,0,0,.28)}}
.rocket:hover{{transform:translateY(-2px)}}
.ok{{background:#e7f7ec;border:1px solid #2ea043;color:#136c2e;padding:11px 14px;border-radius:9px;display:none}}
@media(prefers-color-scheme:dark){{.ok{{background:rgba(46,160,67,.14);color:#5dd67f}}}}
"""


def nav_html(domain, pages, brand):
    links = "".join(f'<a href="{p["path"]}">{e(p["nav"])}</a>' for p in pages)
    return f"""<header class="top"><div class="in">
<a class="brand" href="/">{e(brand)}</a>
<nav>{links}</nav>
<a class="login" href="https://network.r0cketship.com/login">Login</a>
</div></header>"""


def form_html(kind, label, domain):
    extra = ('<label for="m">Message</label><textarea id="m" name="message" '
             'placeholder="How can we help?"></textarea>') if kind == "contact" else \
            f'<label for="m">Tell us about your interest</label><textarea id="m" name="message"></textarea>'
    return f"""<form class="lead" data-form="{kind}">
<div class="ok" role="status">Thank you — we received your message and will be in touch.</div>
<label for="n-{kind}">Name</label><input id="n-{kind}" name="name" required autocomplete="name">
<label for="e-{kind}">Email</label><input id="e-{kind}" type="email" name="email" required autocomplete="email">
<label for="p-{kind}">Phone</label><input id="p-{kind}" type="tel" name="phone" required autocomplete="tel">
{extra}
<button class="btn" type="submit">{e(label)}</button>
</form>"""


def footer_html(domain, brand):
    forms = [("contact", "Contact Us"), ("investor", "Investor Relations"),
             ("advertise", "Advertise With Us"), ("join", "Join Our Network")]
    links = "".join(f'<a href="/{k}.html">{v}</a>' for k, v in forms)
    return f"""<footer><div class="in"><div class="fgrid">
<div><h4>{e(brand)}</h4><p style="font-size:14px">{ADDRESS['street']}<br>
{ADDRESS['city']}, {ADDRESS['state']} {ADDRESS['zip']}</p></div>
<div><h4>Company</h4>{links}</div>
<div><h4>Network</h4>
<a href="https://r0cketship.com">R0cketShip</a>
<a href="https://jeff-cline.com">Jeff Cline</a></div>
</div></div>
<div class="legal">&copy; {time.strftime('%Y')} {e(brand)} · {e(domain)}</div></footer>
<a class="rocket" href="https://r0cketship.com" aria-label="Powered by R0cketShip" title="R0cketShip">🚀</a>
<script>
document.querySelectorAll('form.lead').forEach(f=>f.addEventListener('submit',async ev=>{{
  ev.preventDefault();
  const b=f.querySelector('button');b.disabled=true;b.textContent='Sending…';
  const d=Object.fromEntries(new FormData(f));
  d.form=f.dataset.form; d.site=location.hostname;
  try{{
    const r=await fetch('{LEAD_API}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
    if(!r.ok) throw 0;
    f.querySelector('.ok').style.display='block';
    f.querySelectorAll('input,textarea').forEach(i=>i.value='');
    b.textContent='Sent';
  }}catch(_){{b.disabled=false;b.textContent='Try again';}}
}}));
</script></body></html>"""


def ld_local(domain, brand, desc):
    return ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "LocalBusiness", "name": brand,
        "url": f"https://{domain}", "description": desc,
        "address": {"@type": "PostalAddress", "streetAddress": ADDRESS["street"],
                    "addressLocality": ADDRESS["city"], "addressRegion": ADDRESS["state"],
                    "postalCode": ADDRESS["zip"], "addressCountry": "US"},
    }) + "</script>")


# ---------- build one site ----------
def build_site(row, outroot):
    domain = row["domain"]
    # Prefer the brand the operator typed into the title ("Ads Eyewear — ...") over a
    # guess derived from the domain, which cannot find word boundaries ("Adseyewear").
    brand = ""
    if row["title"]:
        brand = re.split(r"\s+[—–|:]\s+", row["title"])[0].strip()
    if not brand or len(brand) > 42:
        brand = titlecase(re.sub(r"\.[a-z]{2,12}$", "", domain).replace("-", " "))
    pal = PALETTES[hash(domain) % len(PALETTES)]
    money = row["money_keyword"] or brand
    supports = [k for k in (row["kw1"], row["kw2"], row["kw3"]) if k]
    while len(supports) < 3:
        supports.append(f"{money} {['guide','costs','options'][len(supports)]}")

    pages = [{"path": "/", "file": "index.html", "nav": "Home", "kw": money, "kind": "main"}]
    for kw in supports[:3]:
        pages.append({"path": f"/{slug(kw)}.html", "file": f"{slug(kw)}.html",
                      "nav": titlecase(kw)[:26], "kw": kw, "kind": "support"})
    pages.append({"path": "/contact.html", "file": "contact.html", "nav": "Contact", "kw": "contact", "kind": "contact"})

    d = os.path.join(outroot, domain)
    os.makedirs(d, exist_ok=True)
    nav = nav_html(domain, pages, brand)
    foot = footer_html(domain, brand)

    for i, p in enumerate(pages):
        if p["kind"] == "contact":
            title = f"Contact {brand} — {ADDRESS['city']}, {ADDRESS['state']}"
            desc = f"Get in touch with {brand} in {ADDRESS['city']}, {ADDRESS['state']}. Call or send a message and we'll respond promptly."
            body = f"""<section><h2>Contact {e(brand)}</h2>
<p>Questions about {e(money)}? Send a message and we'll get back to you.</p>
<div class="grid"><div>{form_html('contact','Send Message',domain)}</div>
<div class="card"><div class="body"><h3>Visit</h3>
<p>{ADDRESS['street']}<br>{ADDRESS['city']}, {ADDRESS['state']} {ADDRESS['zip']}</p></div></div></div></section>"""
            art = ""
        else:
            c = copy_for(p["kw"], domain, p["kind"])
            title = (row["title"] if i == 0 else f'{titlecase(p["kw"])} — {brand}')[:70]
            desc = (row["description"] if i == 0 else c["lede"])[:160]
            secs = "".join(f"<section><h2>{e(h)}</h2><p>{e(t)}</p></section>" for h, t in c["sections"])
            kw = p["kw"]
            cards = "".join(
                f'<div class="card">'
                + card_svg(hash(kw + s) % 9999, pal, f"Chart illustrating {s} in relation to {kw}")
                + f'<div class="body"><h3>{e(titlecase(s))}</h3>'
                  f'<p>How {e(s)} affects your decision on {e(kw)}.</p></div></div>'
                for s in supports[:3] if s != kw)
            art = ('<div class="hero">'
                   + hero_svg(hash(domain + kw) % 9999, pal, f"Abstract header graphic representing {kw}")
                   + f'<div class="txt"><h1>{e(c["h1"])}</h1><p>{e(c["lede"])}</p></div></div>')
            body = f'{secs}<div class="grid">{cards}</div>' \
                   f'<section class="cta"><h2>Talk to someone about {e(p["kw"])}</h2>' \
                   f'<p style="margin:0 auto 18px">Tell us what you need and we\'ll point you the right way.</p>' \
                   f'<a class="btn" href="/contact.html">Get in touch</a></section>'

        ld = ld_local(domain, brand, desc) if i == 0 else ""
        open(os.path.join(d, p["file"]), "w").write(
            head(title, desc, domain, p["path"], pal, ld) + nav + art + "<main>" + body + "</main>" + foot)

    # standalone form pages
    for k, lbl in [("investor", "Investor Relations"), ("advertise", "Advertise With Us"),
                   ("join", "Join Our Network")]:
        t = f"{lbl} — {brand}"
        ds = f"{lbl} enquiries for {brand}. Send your details and we'll respond."
        open(os.path.join(d, f"{k}.html"), "w").write(
            head(t, ds, domain, f"/{k}.html", pal) + nav +
            f'<main><section><h2>{e(lbl)}</h2><p>{e(ds)}</p>{form_html(k, "Submit", domain)}</section></main>' + foot)

    urls = "".join(f"<url><loc>https://{domain}{p['path']}</loc></url>" for p in pages) + \
           "".join(f"<url><loc>https://{domain}/{k}.html</loc></url>" for k in ("investor", "advertise", "join"))
    open(os.path.join(d, "sitemap.xml"), "w").write(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    open(os.path.join(d, "robots.txt"), "w").write(
        f"User-agent: *\nAllow: /\nSitemap: https://{domain}/sitemap.xml\n")
    return len(pages) + 3


def main():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM build_queue WHERE state='queued' ORDER BY domain").fetchall()
    if not rows:
        print("Q is empty — nothing to build."); return
    print(f"building {len(rows)} sites -> {OUTROOT}")
    built = 0
    for r in rows:
        try:
            n = build_site(r, OUTROOT)
            con.execute("UPDATE build_queue SET state='built', built_at=? WHERE domain=?",
                        (time.time(), r["domain"]))
            con.commit(); built += 1
            print(f"  ✓ {r['domain']:38} {n} files")
        except Exception as ex:
            print(f"  ✗ {r['domain']:38} {type(ex).__name__}: {ex}")
    print(f"\nbuilt {built}/{len(rows)}")


if __name__ == "__main__":
    main()
