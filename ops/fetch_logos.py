#!/usr/bin/env python3
"""
Fetch each brand's real logo and store it locally.

Google's favicon service 301s and renders nothing, and the sites keep their
icons at varying paths (/icon.png, /icon.svg?hash, /favicon.ico?hash), so the
only reliable route is to read each homepage and follow its declared icon.
"""
import os, re, subprocess, sys

OUT = "/var/www/network/brandicons"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def sh(args, timeout=25):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 1, b""


def fetch(domain):
    rc, body = sh(["curl", "-skL", "--max-time", "20", "-A", UA, f"https://{domain}/"])
    html = body.decode("utf-8", "replace") if rc == 0 else ""
    cands = []
    for m in re.finditer(r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]*>', html, re.I):
        tag = m.group(0)
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if href:
            cands.append(href.group(1))
    cands += ["/favicon.ico", "/icon.png", "/apple-touch-icon.png"]

    for href in cands:
        url = href if href.startswith("http") else f"https://{domain}" + (
            href if href.startswith("/") else "/" + href)
        ext = ".png"
        for e2 in (".svg", ".ico", ".png", ".jpg", ".webp"):
            if e2 in url.lower():
                ext = e2
                break
        path = os.path.join(OUT, domain + ext)
        rc, data = sh(["curl", "-skL", "--max-time", "20", "-A", UA, url])
        if rc == 0 and len(data) > 200 and not data.lstrip()[:15].lower().startswith(b"<!doctype"):
            open(path, "wb").write(data)
            return domain + ext, len(data)
    return None, 0


def main():
    os.makedirs(OUT, exist_ok=True)
    domains = sys.argv[1:]
    got = 0
    for d in domains:
        name, size = fetch(d)
        if name:
            got += 1
            print(f"  OK   {d:34} {name.split('.')[-1]:5} {size:>7}b")
        else:
            print(f"  none {d}")
    print(f"\n  {got}/{len(domains)} logos fetched")


if __name__ == "__main__":
    main()
