#!/usr/bin/env python3
"""
Derive title / description / keywords from a domain name.

These are money-word domains: the phrase lives in the name, between the dots.
Segmentation is imperfect on brand names and misspellings, so a quality gate
rejects bad splits and falls back to the raw label rather than emitting
nonsense like "a ler gies".
"""
import re

try:
    import wordninja
    _WC = wordninja.DEFAULT_LANGUAGE_MODEL._wordcost
    _MAXCOST = max(_WC.values()) + 2
except Exception:
    wordninja = None
    _WC, _MAXCOST = {}, 99

# A good segmentation spreads its cost over many characters; a junk one crams
# rare fragments into few. Measured across the real portfolio, genuine splits
# sit at 0.9-2.3 and nonsense ("a ler gies", "am nigra ft") at 3.2-4.2.
MAX_COST_PER_CHAR = 2.5

# TLDs that carry no meaning and should be dropped from the phrase.
GENERIC_TLDS = {
    "com", "net", "org", "io", "co", "ai", "us", "ws", "tv", "me", "info",
    "biz", "app", "dev", "xyz", "site", "online", "link", "click", "live",
    # country codes carry no keyword value either
    "mx", "uk", "ca", "de", "fr", "es", "it", "nl", "au", "nz", "in", "jp",
    "cn", "br", "ru", "ch", "se", "no", "dk", "fi", "pl", "pt", "be", "at",
    "ie", "za", "cc", "gg", "sh", "st", "to", "am", "fm", "la", "vc",
}
# Short tokens that are legitimate on their own.
OK_SHORT = {"a", "i", "my", "we", "us", "go", "2a", "ai", "it", "up", "on", "at", "tv", "rv", "iv"}

DESCRIPTOR = "Costs, Options & How to Choose"


def _segment(label: str):
    """Split a concatenated label into words, or return None if unconvincing."""
    if not wordninja:
        return None
    parts = [p for p in wordninja.split(label) if p]
    if not parts or len(parts) > 5:
        return None
    # Two-character fragments are the signature of a forced split.
    for p in parts:
        if len(p) <= 2 and p.lower() not in OK_SHORT and not p.isdigit():
            return None
    cost = sum(0 if p.isdigit() else _WC.get(p.lower(), _MAXCOST) for p in parts)
    if cost / max(len(label), 1) > MAX_COST_PER_CHAR:
        return None
    return parts


def phrase_for(domain: str):
    """Return (phrase, words) for a domain, e.g. 'accident sickness pay'."""
    d = domain.lower().strip()
    bits = d.split(".")
    sld, tld = bits[0], (bits[-1] if len(bits) > 1 else "")

    words = []
    for chunk in re.split(r"[-_]+", sld):
        if not chunk:
            continue
        if chunk.isdigit() or len(chunk) <= 3:
            words.append(chunk)
            continue
        seg = _segment(chunk)
        words.extend(seg if seg else [chunk])

    if tld and tld not in GENERIC_TLDS:
        seg = _segment(tld) or [tld]
        words.extend(seg)

    words = [w for w in words if w and w != "the"]
    return " ".join(words), words


def titlecase(s: str) -> str:
    small = {"a", "an", "and", "the", "for", "in", "of", "on", "to", "with", "near", "or"}
    out = []
    for i, w in enumerate(s.split()):
        if re.fullmatch(r"\d+[a-z]?", w):          # 2a, 770
            out.append(w.upper())
        elif len(w) <= 3 and w.lower() not in small and w.isalpha() and i == 0:
            out.append(w.upper() if len(w) <= 2 else w.capitalize())
        elif i == 0 or w.lower() not in small:
            out.append(w.capitalize())
        else:
            out.append(w.lower())
    return " ".join(out)


def suggest(domain: str) -> dict:
    phrase, words = phrase_for(domain)
    if not phrase:
        phrase = domain.split(".")[0]
    pretty = titlecase(phrase)

    title = pretty if len(pretty) >= 22 else f"{pretty} — {DESCRIPTOR}"
    title = title[:70]

    desc = (f"Straight answers about {phrase}: what it involves, what it costs, "
            f"and how to choose. No sales pitch.")
    if len(desc) > 160:
        desc = f"What {phrase} involves, what it costs, and how to choose the right option."[:160]

    return {
        "title": title,
        "description": desc,
        "money_keyword": phrase,
        "kw1": f"{phrase} near me",
        "kw2": f"{phrase} cost",
        "kw3": f"best {phrase}",
    }


if __name__ == "__main__":
    import sys
    for d in sys.argv[1:]:
        s = suggest(d)
        print(f"\n{d}")
        for k, v in s.items():
            print(f"  {k:14} {v}")
