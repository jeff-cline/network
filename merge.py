#!/usr/bin/env python3
"""Merge both accounts and re-probe ambiguous domains for a precise status."""
import json, ssl, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

a1 = json.load(open('crawl_results.json'))
a2 = json.load(open('crawl_results2.json'))
for r in a1: r['account'] = 1
for r in a2: r['account'] = 2
allr = a1 + a2

AMBIG = {'EMPTY', 'ERROR', 'PARKED'}
targets = [r for r in allr if r['status'] in AMBIG]


def refine(d):
    for s in ("https://", "http://"):
        try:
            req = urllib.request.Request(s + d, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=12, context=CTX) as resp:
                final = resp.geturl(); body = resp.read(60000).decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            final = s + d
            try: body = e.read(60000).decode('utf-8', 'replace')
            except Exception: body = ""
            if 'suspend' in body.lower(): return d, 'SUSPENDED'
            if e.code in (500, 502, 503): return d, 'BROKEN'
            continue
        except Exception:
            continue
        low = (final + " " + body).lower()
        if 'suspendedpage.cgi' in low or 'account has been suspended' in low: return d, 'SUSPENDED'
        if '/lander' in low or 'parkingcrew' in low or 'sedo' in low or 'afternic' in low: return d, 'PARKED'
        if 'godaddy' in low and ('forsale' in low or 'coming soon' in low): return d, 'PARKED'
        if len(body.strip()) < 400: return d, 'PARKED'
        return d, 'BROKEN'
    return d, 'UNREACHABLE'


print(f"re-probing {len(targets)} ambiguous domains...", flush=True)
with ThreadPoolExecutor(max_workers=24) as ex:
    refined = dict(ex.map(refine, [r['domain'] for r in targets]))

for r in allr:
    if r['domain'] in refined:
        r['status'] = refined[r['domain']]
    elif r['status'] == 'NO_RESPONSE':
        r['status'] = 'UNREACHABLE'

json.dump(allr, open('merged.json', 'w'), indent=1)
c = Counter(r['status'] for r in allr)
print(f"\n=== MERGED: {len(allr)} domains across 2 accounts ===")
for k, v in c.most_common(): print(f"  {k:16} {v}")
print(f"\naccount 1: {sum(1 for r in allr if r['account']==1)}   account 2: {sum(1 for r in allr if r['account']==2)}")
