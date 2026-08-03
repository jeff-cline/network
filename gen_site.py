#!/usr/bin/env python3
"""Generate the network.r0cketship.com inventory landing page from crawl results."""
import json, sys, html
from collections import Counter

results = json.load(open(sys.argv[1]))
OUT = sys.argv[2]

LIVE = [r for r in results if r["status"] in ("LIVE_MULTIPAGE", "LIVE_SINGLE")]
LIVE.sort(key=lambda r: (r["status"] != "LIVE_MULTIPAGE", r["domain"]))
BUILD = [r for r in results if r["status"] not in ("LIVE_MULTIPAGE", "LIVE_SINGLE")]
BUILD.sort(key=lambda r: (r["status"], r["domain"]))

c = Counter(r["status"] for r in results)
e = html.escape

LABEL = {
    "LIVE_MULTIPAGE": ("Multi-page", "ok"),
    "LIVE_SINGLE": ("Single page", "warn"),
    "PARKED": ("Parked", "warn"),
    "EMPTY": ("Empty (200, no content)", "bad"),
    "ERROR": ("Server error", "bad"),
    "NO_RESPONSE": ("No response", "bad"),
}


def fav(d):
    return f'<img class="fav" loading="lazy" alt="" src="https://www.google.com/s2/favicons?domain={e(d)}&sz=64">'


def live_rows():
    out = []
    for r in LIVE:
        lbl, cls = LABEL[r["status"]]
        title = e(r["title"]) or f'<span class="muted">— no title —</span>'
        desc = e(r["desc"]) or '<span class="muted">— no meta description —</span>'
        out.append(f"""<tr>
<td>{fav(r['domain'])}</td>
<td class="dom"><a href="{e(r['final_url'] or 'http://' + r['domain'])}" target="_blank" rel="noopener">{e(r['domain'])}</a>
<div class="sub"><span class="pill {cls}">{lbl}</span> <span class="muted">{r['internal_links']} links</span></div></td>
<td class="ttl">{title}</td>
<td class="dsc">{desc}</td>
<td class="exp muted">{e(r['expires'])}</td>
</tr>""")
    return "\n".join(out)


def build_rows():
    out = []
    for r in BUILD:
        lbl, cls = LABEL[r["status"]]
        note = e(r["error"]) or (f"HTTP {r['http']}" if r["http"] else "")
        out.append(f"""<tr>
<td>{fav(r['domain'])}</td>
<td class="dom">{e(r['domain'])}</td>
<td><span class="pill {cls}">{lbl}</span></td>
<td class="muted">{note}</td>
<td class="ttl needs" data-domain="{e(r['domain'])}"><span class="muted">needs title</span></td>
<td class="dsc needs"><span class="muted">needs description</span></td>
<td class="exp muted">{e(r['expires'])}</td>
</tr>""")
    return "\n".join(out)


page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Network Inventory — {len(results)} domains | R0cketShip</title>
<meta name="description" content="Live inventory of the R0cketShip domain network: {len(LIVE)} active sites and {len(BUILD)} domains awaiting build.">
<style>
:root{{--bg:#0f1115;--panel:#171a21;--line:#262b36;--tx:#e7eaf0;--mut:#8b93a7;--acc:#ff6b1a;--ok:#2ea043;--warn:#d29922;--bad:#cf484d}}
@media(prefers-color-scheme:light){{:root{{--bg:#f6f7f9;--panel:#fff;--line:#e2e5ea;--tx:#12151b;--mut:#697084}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
header{{padding:28px 24px 0;max-width:1400px;margin:0 auto}}
h1{{margin:0 0 4px;font-size:26px;letter-spacing:-.02em}}
h1 .r{{color:var(--acc)}}
.lede{{color:var(--mut);margin:0 0 18px}}
.stats{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}}
.stat{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:104px}}
.stat b{{display:block;font-size:21px;line-height:1.2}}
.stat span{{color:var(--mut);font-size:12px}}
.tabs{{display:flex;gap:4px;border-bottom:1px solid var(--line);max-width:1400px;margin:0 auto;padding:0 24px}}
.tab{{appearance:none;background:none;border:0;border-bottom:2px solid transparent;color:var(--mut);font:inherit;font-weight:600;padding:11px 16px;cursor:pointer}}
.tab[aria-selected=true]{{color:var(--tx);border-bottom-color:var(--acc)}}
main{{max-width:1400px;margin:0 auto;padding:18px 24px 60px}}
.toolbar{{margin-bottom:12px}}
input[type=search]{{width:100%;max-width:380px;padding:9px 12px;border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--tx);font:inherit}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);padding:10px 12px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}}
td{{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top}}
tr:last-child td{{border-bottom:0}}
.fav{{width:20px;height:20px;border-radius:4px;display:block}}
.dom{{font-weight:600;white-space:nowrap}}
.dom a{{color:var(--tx);text-decoration:none}}
.dom a:hover{{color:var(--acc);text-decoration:underline}}
.sub{{margin-top:4px;font-weight:400}}
.ttl{{min-width:220px}}
.dsc{{color:var(--mut);font-size:13.5px;min-width:280px}}
.exp{{white-space:nowrap;font-size:13px}}
.muted{{color:var(--mut)}}
.pill{{display:inline-block;font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid currentColor;font-weight:600}}
.pill.ok{{color:var(--ok)}} .pill.warn{{color:var(--warn)}} .pill.bad{{color:var(--bad)}}
.panel[hidden]{{display:none}}
.wrap{{overflow-x:auto}}
footer{{max-width:1400px;margin:0 auto;padding:0 24px 50px;color:var(--mut);font-size:13px}}
footer a{{color:var(--acc)}}
</style></head><body>
<header>
<h1><span class="r">🚀</span> Network Inventory</h1>
<p class="lede">{len(results)} active domains · account 1 of 2 · crawled automatically</p>
<div class="stats">
<div class="stat"><b>{c['LIVE_MULTIPAGE']}</b><span>multi-page</span></div>
<div class="stat"><b>{c['LIVE_SINGLE']}</b><span>single page</span></div>
<div class="stat"><b>{c['EMPTY']}</b><span>empty</span></div>
<div class="stat"><b>{c['ERROR']}</b><span>server error</span></div>
<div class="stat"><b>{c['NO_RESPONSE']}</b><span>no response</span></div>
<div class="stat"><b>{c['PARKED']}</b><span>parked</span></div>
</div>
</header>
<div class="tabs" role="tablist">
<button class="tab" role="tab" aria-selected="true" aria-controls="p-live" id="t-live">Network Sites ({len(LIVE)})</button>
<button class="tab" role="tab" aria-selected="false" aria-controls="p-build" id="t-build">Need to Build ({len(BUILD)})</button>
</div>
<main>
<div class="toolbar"><input type="search" id="q" placeholder="Filter by domain, title, or description…" aria-label="Filter"></div>

<section class="panel" id="p-live" role="tabpanel" aria-labelledby="t-live">
<div class="wrap"><table>
<thead><tr><th></th><th>Domain</th><th>Title</th><th>Description</th><th>Expires</th></tr></thead>
<tbody>
{live_rows()}
</tbody></table></div>
</section>

<section class="panel" id="p-build" role="tabpanel" aria-labelledby="t-build" hidden>
<div class="wrap"><table>
<thead><tr><th></th><th>Domain</th><th>Status</th><th>Detail</th><th>Title</th><th>Description</th><th>Expires</th></tr></thead>
<tbody>
{build_rows()}
</tbody></table></div>
</section>
</main>
<footer>Generated from the GoDaddy API + a live crawl of every domain. Account 2 pending.
&nbsp;·&nbsp; <a href="https://r0cketship.com">R0cketShip</a> &nbsp;·&nbsp; <a href="https://jeff-cline.com">Jeff Cline</a></footer>
<script>
const tabs=[...document.querySelectorAll('.tab')];
tabs.forEach(t=>t.addEventListener('click',()=>{{
  tabs.forEach(x=>{{x.setAttribute('aria-selected',x===t);
    document.getElementById(x.getAttribute('aria-controls')).hidden = x!==t;}});
  document.getElementById('q').dispatchEvent(new Event('input'));
}}));
document.getElementById('q').addEventListener('input',e=>{{
  const v=e.target.value.toLowerCase();
  document.querySelectorAll('.panel:not([hidden]) tbody tr').forEach(r=>{{
    r.style.display = !v || r.textContent.toLowerCase().includes(v) ? '' : 'none';
  }});
}});
</script>
</body></html>"""

open(OUT, "w").write(page)
print(f"wrote {OUT}  ({len(page):,} bytes)")
print(f"  Network Sites : {len(LIVE)}")
print(f"  Need to Build : {len(BUILD)}")
