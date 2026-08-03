#!/usr/bin/env python3
"""Crawl each domain: is it live, is it a real multi-page site, what's its title/description."""
import json, re, ssl, sys, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

IN, OUT = sys.argv[1], sys.argv[2]
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

PARK_MARKERS = [
    "godaddy.com/forsale", "afternic", "dan.com", "sedoparking", "parkingcrew",
    "this domain is for sale", "buy this domain", "domain for sale",
    "future home of something quite cool", "coming soon", "under construction",
    "cashparking", "hugedomains", "domain is parked", "parked free",
]

class Extract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self._in_title = None, False
        self.desc = None
        self.links = set()
        self.imgs = 0
        self.h = {"h1": 0, "h2": 0}
        self._tag = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self._tag = tag
        if tag == "title" and self.title is None:
            self._in_title = True
        elif tag == "meta":
            n = (a.get("name") or a.get("property") or "").lower()
            if n in ("description", "og:description") and not self.desc:
                self.desc = (a.get("content") or "").strip()
        elif tag == "a" and a.get("href"):
            self.links.add(a["href"])
        elif tag == "img":
            self.imgs += 1
        elif tag in self.h:
            self.h[tag] += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, d):
        if self._in_title:
            self.title = ((self.title or "") + d).strip()


def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        raw = r.read(400_000)
        enc = r.headers.get_content_charset() or "utf-8"
        return r.geturl(), r.status, raw.decode(enc, "replace")


def probe(rec):
    d = rec["domain"]
    out = {
        "domain": d, "expires": rec.get("expires", "")[:10], "status": "",
        "final_url": "", "http": None, "title": "", "desc": "",
        "internal_links": 0, "images": 0, "h1": 0, "parked": False, "error": "",
    }
    for scheme in ("https://", "http://"):
        try:
            final, code, body = fetch(scheme + d)
            out["final_url"], out["http"] = final, code
            p = Extract()
            try:
                p.feed(body)
            except Exception:
                pass
            out["title"] = re.sub(r"\s+", " ", (p.title or "")).strip()[:200]
            out["desc"] = re.sub(r"\s+", " ", (p.desc or "")).strip()[:300]
            out["images"], out["h1"] = p.imgs, p.h["h1"]

            host = urllib.parse.urlparse(final).netloc.lower().replace("www.", "")
            internal = set()
            for href in p.links:
                if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                u = urllib.parse.urljoin(final, href)
                pu = urllib.parse.urlparse(u)
                if pu.netloc.lower().replace("www.", "") == host:
                    path = pu.path.rstrip("/")
                    if path and path != "/":
                        internal.add(path)
            out["internal_links"] = len(internal)

            low = (body[:200_000] + " " + out["title"] + " " + out["desc"]).lower()
            out["parked"] = any(m in low for m in PARK_MARKERS)

            if out["parked"]:
                out["status"] = "PARKED"
            elif code >= 400:
                out["status"] = "ERROR"
            elif out["internal_links"] >= 3 and out["title"]:
                out["status"] = "LIVE_MULTIPAGE"
            elif out["title"] or out["images"] > 1:
                out["status"] = "LIVE_SINGLE"
            else:
                out["status"] = "EMPTY"
            return out
        except urllib.error.HTTPError as e:
            out["http"] = e.code
            out["error"] = f"HTTP {e.code}"
            if scheme == "http://":
                out["status"] = "ERROR"
        except Exception as e:
            out["error"] = type(e).__name__
            if scheme == "http://":
                out["status"] = "NO_RESPONSE"
    return out


domains = json.load(open(IN))
print(f"crawling {len(domains)} domains...", flush=True)
results = []
with ThreadPoolExecutor(max_workers=24) as ex:
    for i, r in enumerate(ex.map(probe, domains), 1):
        results.append(r)
        if i % 25 == 0:
            print(f"  {i}/{len(domains)}", flush=True)

json.dump(results, open(OUT, "w"), indent=1)
from collections import Counter
c = Counter(r["status"] for r in results)
print("\n=== CRAWL COMPLETE ===")
for k, v in c.most_common():
    print(f"{k:16} {v}")
