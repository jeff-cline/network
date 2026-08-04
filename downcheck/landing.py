#!/usr/bin/env python3
"""Landing page for websitedowncheckers.com — rendered server-side, static output."""
import html
e = html.escape

# Every figure below is publicly documented and attributed. No invented
# testimonials, no fake logos: this product is sold on trust.
INCIDENTS = [
    ("Delta Air Lines", "2016", "$150M",
     "A power control failure grounded ~2,000 flights over three days. Delta reported the "
     "pre-tax cost in its own filings.", "failure"),
    ("British Airways", "2017", "£80M",
     "An IT failure over a bank holiday weekend stranded 75,000 passengers. Parent company "
     "IAG put the cost at £80 million.", "failure"),
    ("Amazon", "2016", "$3.75M",
     "A 20-minute outage on Amazon.com. At their revenue run-rate that is roughly $3.75M "
     "of sales, gone, in under half an hour.", "server"),
    ("Facebook", "2021", "~6 hours",
     "A BGP misconfiguration took Facebook, Instagram and WhatsApp off the internet. Their "
     "own DNS became unreachable — staff could not even badge into buildings.", "dns"),
]

CAUSES = [
    ("💳", "An unpaid invoice",
     "The most common cause, and the most embarrassing. A card expires, a renewal notice "
     "lands in a spam folder, and the host suspends the account. The site is fine. The "
     "server is fine. Nobody told you.",
     "We watch the site itself, not your billing portal — so a suspension shows up the "
     "moment it takes effect."),
    ("🖥️", "The server stopped",
     "A host reboots, a disk fills, a service fails to restart after maintenance. The box "
     "answers pings but the web server never came back up.",
     "We check the port, not just the ping. A machine that is 'up' but serving nothing "
     "still counts as down."),
    ("🌐", "DNS or the IP moved",
     "A record gets edited, a nameserver change propagates, a domain transfer completes. "
     "Your site is running perfectly — at an address nobody is being sent to any more.",
     "We resolve your domain from outside your network every check, so a DNS change that "
     "points customers nowhere is caught in minutes."),
    ("🛡️", "You are under attack",
     "A flood of traffic, a compromised plugin, a defacement. Sometimes the first sign is "
     "a customer asking why your homepage looks strange.",
     "We compare what your page actually returns, not just whether it responds — so a "
     "200 OK serving the wrong content is still an alert."),
]

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from tiers import PLANS, ORDER
PLAN_PRICE = "9"


def page() -> str:
    inc = "".join(f"""<div class="inc">
<div class="inc-h"><b>{e(n)}</b><span class="yr">{e(y)}</span></div>
<div class="cost">{e(c)}</div><p>{e(d)}</p></div>""" for n, y, c, d, _ in INCIDENTS)

    causes = "".join(f"""<div class="cause">
<div class="ic">{ic}</div>
<div><h3>{e(t)}</h3><p>{e(body)}</p>
<p class="fix"><b>What we do:</b> {e(fix)}</p></div></div>""" for ic, t, body, fix in CAUSES)

    def _tier(k):
        p = PLANS[k]
        if p.get("request"):
            feats = "".join(f"<li>{e(x)}</li>" for x in p["features"])
            return (f'<div class="tier corp"><div class="tname">{e(p["name"])}</div>'
                    f'<div class="tamt req">Let&rsquo;s talk</div>'
                    f'<div class="tfreq">{e(p["human"])}</div>'
                    f'<p>{e(p["blurb"])}</p><ul class="plist">{feats}</ul>'
                    f'<div class="tfor">{e(p["for"])}</div>'
                    f'<a class="btn" style="width:100%;text-align:center" href="/corporate">'
                    f'Request pricing</a></div>')
        per = 86400 // p["interval"]
        return (f'<div class="tier{" feat" if k == "pro" else ""}">'
                f'<div class="tname">{e(p["name"])}</div>'
                f'<div class="tamt">${p["price"]:,}<span>/mo</span></div>'
                f'<div class="tfreq">checks {e(p["human"])}</div>'
                f'<p>{e(p["blurb"])}</p><ul class="plist">'
                f'<li>{per:,} check{"s" if per != 1 else ""} per site, per day</li>'
                f'<li>{p["confirmations"]} confirmations before any alert</li>'
                f'<li>Unlimited sites and recipients</li>'
                f'<li>Down and recovery alerts</li></ul>'
                f'<div class="tfor">{e(p["for"])}</div>'
                f'<a class="btn" style="width:100%;text-align:center" href="/signup">Start</a></div>')

    tiers = "".join(_tier(k) for k in ORDER)

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Website Down Checkers — Know the moment your site goes down</title>
<meta name="description" content="Independent uptime monitoring that alerts your whole team the
moment your website goes down. Daily checks from $9/month, or every 3 seconds on Real-time.
Confirmed alerts, no false positives.">
<link rel="canonical" href="https://websitedowncheckers.com/">
<meta property="og:title" content="Know the moment your website goes down">
<meta property="og:description" content="Most businesses find out their site is down from a
customer. Independent monitoring, unlimited team alerts, ${PLAN_PRICE}/month.">
<meta name="theme-color" content="#0b0d12">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"SoftwareApplication",
"name":"Website Down Checkers","applicationCategory":"BusinessApplication",
"offers":{{"@type":"Offer","price":"{PLAN_PRICE}","priceCurrency":"USD"}}}}</script>
<style>
:root{{--bg:#0b0d12;--panel:#141821;--line:#232936;--tx:#eef1f6;--mut:#98a1b3;
--acc:#ff5a1f;--ok:#2ea043;--bad:#e5484d}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,sans-serif}}
a{{color:var(--acc)}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 24px}}
header{{position:sticky;top:0;z-index:30;background:rgba(11,13,18,.9);
backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}}
header .in{{display:flex;align-items:center;gap:20px;padding:15px 0}}
.brand{{font-weight:800;letter-spacing:-.02em;text-decoration:none;color:var(--tx);font-size:17px}}
.brand .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--ok);
margin-right:8px;box-shadow:0 0 0 3px rgba(46,160,67,.2)}}
nav{{flex:1;display:flex;gap:22px}}
nav a{{color:var(--mut);text-decoration:none;font-size:14.5px;font-weight:500}}
nav a:hover{{color:var(--tx)}}
.btn{{display:inline-block;background:var(--acc);color:#fff;text-decoration:none;font-weight:700;
padding:11px 22px;border-radius:9px;font-size:15px;border:0;cursor:pointer}}
.btn.ghost{{background:transparent;border:1px solid var(--line);color:var(--tx)}}
.hero{{padding:78px 0 54px;text-align:center}}
.kicker{{display:inline-block;border:1px solid var(--line);border-radius:999px;
padding:6px 15px;color:var(--mut);font-size:13px;margin-bottom:22px}}
h1{{font-size:clamp(33px,6vw,60px);line-height:1.04;letter-spacing:-.035em;margin:0 0 20px}}
h1 .hl{{color:var(--acc)}}
.sub{{color:var(--mut);font-size:clamp(16px,2.3vw,20px);max-width:58ch;margin:0 auto 30px}}
.cta-row{{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}}
.trust{{color:var(--mut);font-size:13.5px;margin-top:16px}}
section{{padding:62px 0;border-top:1px solid var(--line)}}
h2{{font-size:clamp(25px,3.6vw,36px);letter-spacing:-.025em;margin:0 0 12px}}
.lede{{color:var(--mut);max-width:62ch;margin:0 0 34px;font-size:17px}}
.incs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(238px,1fr));gap:16px}}
.inc{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}}
.inc-h{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}}
.yr{{color:var(--mut);font-size:13px}}
.cost{{font-size:29px;font-weight:800;color:var(--bad);letter-spacing:-.02em;margin-bottom:8px}}
.inc p{{color:var(--mut);font-size:14px;margin:0;line-height:1.55}}
.cause{{display:flex;gap:18px;padding:24px 0;border-bottom:1px solid var(--line)}}
.cause:last-child{{border-bottom:0}}
.cause .ic{{font-size:27px;flex:0 0 52px;height:52px;background:var(--panel);
border:1px solid var(--line);border-radius:13px;display:flex;align-items:center;justify-content:center}}
.cause h3{{margin:2px 0 7px;font-size:19px;letter-spacing:-.015em}}
.cause p{{color:var(--mut);margin:0 0 9px;max-width:68ch}}
.fix{{color:var(--tx)!important;font-size:14.5px;background:rgba(255,90,31,.07);
border-left:2px solid var(--acc);padding:9px 13px;border-radius:0 8px 8px 0}}
.grid3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px}}
.card h3{{margin:0 0 7px;font-size:17px}}
.card p{{color:var(--mut);margin:0;font-size:14.5px}}
.tiers{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}}
.tier.corp{{border-color:var(--acc);background:linear-gradient(180deg,rgba(255,90,31,.07),transparent)}}
.tamt.req{{font-size:31px}}
.tier{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:26px;
display:flex;flex-direction:column}}
.tier.feat{{border-color:var(--acc);box-shadow:0 0 0 1px rgba(255,90,31,.25)}}
.tname{{font-size:12.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);font-weight:700}}
.tamt{{font-size:44px;font-weight:800;letter-spacing:-.035em;margin:6px 0 2px}}
.tamt span{{font-size:15px;color:var(--mut);font-weight:600}}
.tfreq{{color:var(--acc);font-weight:700;margin-bottom:13px}}
.tier p{{color:var(--mut);font-size:14.5px;margin:0 0 14px}}
.tfor{{font-size:13px;color:var(--mut);border-top:1px solid var(--line);padding-top:13px;
margin:6px 0 18px;flex:1}}
.price{{background:var(--panel);border:1px solid var(--acc);border-radius:18px;
padding:34px;max-width:440px;margin:0 auto;text-align:center}}
.amt{{font-size:58px;font-weight:800;letter-spacing:-.04em;line-height:1}}
.amt span{{font-size:17px;color:var(--mut);font-weight:600}}
.plist{{list-style:none;padding:0;margin:22px 0 26px;text-align:left}}
.plist li{{padding:7px 0 7px 27px;position:relative;color:var(--mut);font-size:15px}}
.plist li:before{{content:"✓";position:absolute;left:0;color:var(--ok);font-weight:800}}
footer{{border-top:1px solid var(--line);padding:44px 0 60px;color:var(--mut);font-size:14px}}
.fgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:28px;margin-bottom:30px}}
footer h4{{color:var(--tx);font-size:13px;text-transform:uppercase;letter-spacing:.07em;margin:0 0 11px}}
footer a{{display:block;color:var(--mut);text-decoration:none;padding:3px 0}}
footer a:hover{{color:var(--acc)}}
.legal{{border-top:1px solid var(--line);padding-top:20px;font-size:13px}}
</style></head><body>

<header><div class="wrap in">
<a class="brand" href="/"><span class="dot"></span>Website Down Checkers</a>
<nav>
<a href="#why">Why it matters</a>
<a href="#causes">What we catch</a>
<a href="#pricing">Pricing</a>
</nav>
<a class="btn ghost" href="/login">Log in</a>
<a class="btn" href="/signup">Start monitoring</a>
</div></header>

<div class="wrap hero">
<div class="kicker">Checked every 60 seconds · alerts your whole team</div>
<h1>Most businesses find out their site is down<br><span class="hl">from a customer.</span></h1>
<p class="sub">By then you have lost the sale, the trust, and the search ranking. We watch your
site from outside your network and tell everyone who needs to know — within a minute.</p>
<div class="cta-row">
<a class="btn" href="/signup">Start monitoring — from ${PLAN_PRICE}/month</a>
<a class="btn ghost" href="#causes">See what we catch</a>
</div>
<p class="trust">No contract. Cancel any time. Unlimited team recipients.</p>
</div>

<section id="why"><div class="wrap">
<h2>Downtime is not a technical problem. It is a revenue problem.</h2>
<p class="lede">These are documented, publicly reported incidents. The pattern is always the
same: the outage was short, the cost was not.</p>
<div class="incs">{inc}</div>
<p class="lede" style="margin-top:26px;font-size:15px">Sources: company filings and public
statements from Delta Air Lines, IAG, Amazon and Meta. Figures as reported at the time.</p>
</div></section>

<section id="causes"><div class="wrap">
<h2>Four ways your site goes down. We watch for all of them.</h2>
<p class="lede">Most monitoring tools ping a server and call it a day. That misses the two
causes that actually take small businesses offline.</p>
{causes}
</div></section>

<section><div class="wrap">
<h2>Built for teams, not just the person who set it up</h2>
<p class="lede">The person who notices is rarely the person who can fix it. Everyone who needs
to know gets told at the same time.</p>
<div class="grid3">
<div class="card"><h3>Unlimited recipients</h3><p>Add your developer, your agency, your
operations lead and yourself. No per-seat pricing.</p></div>
<div class="card"><h3>Multiple sites, one account</h3><p>Monitor every property you own or
manage from a single dashboard.</p></div>
<div class="card"><h3>Manage clients separately</h3><p>Agencies can group sites by client and
route alerts to different teams.</p></div>
<div class="card"><h3>Alerts on recovery too</h3><p>You are told when it comes back, and how
long it was gone — so you can measure the damage.</p></div>
<div class="card"><h3>Checked from outside</h3><p>Monitoring that runs on your own server
cannot tell you your server is down. Ours runs independently.</p></div>
<div class="card"><h3>Content verification</h3><p>A page that returns 200 while serving the
wrong site is still broken. We check what is actually served.</p></div>
</div>
</div></section>

<section id="pricing"><div class="wrap">
<h2 style="text-align:center">Choose how fast you find out</h2>
<p class="lede" style="margin:0 auto 34px;text-align:center">Every plan includes unlimited
websites and unlimited alert recipients. The only difference is speed.</p>
<div class="tiers">{tiers}</div>
<p class="lede" style="margin:30px auto 0;text-align:center;font-size:15px">
Every alert is confirmed by multiple independent checks before it is sent.
A single network blip never emails your team.</p>
</div></section>

<footer><div class="wrap">
<div class="fgrid">
<div><h4>Website Down Checkers</h4>
<a href="#why">Why it matters</a><a href="#causes">What we catch</a>
<a href="#pricing">Pricing</a><a href="/login">Log in</a></div>
<div><h4>From the same team</h4>
<a href="https://r0cketship.com" target="_blank" rel="noopener">R0cketShip — predictive data networks</a>
<a href="https://jeff-cline.com" target="_blank" rel="noopener">Jeff Cline — profit at scale</a>
<a href="https://jeff-cline.com" target="_blank" rel="noopener">Exit optimization</a></div>
<div><h4>Contact</h4>
<a href="/contact">Contact us</a><a href="mailto:jeff.cline@me.com">jeff.cline@me.com</a></div>
</div>
<div class="legal">&copy; 2026 Website Down Checkers · Incident figures are drawn from public
company statements and filings and are cited for illustration.</div>
</div></footer>
</body></html>"""


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    open(out, "w").write(page())
    print(f"wrote {out} ({len(page()):,} bytes)")
