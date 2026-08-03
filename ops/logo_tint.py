#!/usr/bin/env python3
"""Work out whether each brand logo is light or dark, so the card can give it a
tile that contrasts. White-on-transparent logos vanish on a white tile."""
import glob, json, os
from PIL import Image

OUT = "/var/www/network/brandicons"
# Anything above this reads as a light/white logo that needs a dark tile.
# Measured: vrtcls 168.8 and keywordcalls 166.8 are white marks, so 170 was too high.
LIGHT_THRESHOLD = 150
res = {}
for f in sorted(glob.glob(OUT + "/*")):
    base = os.path.basename(f)
    if base == "tint.json" or base.endswith(".norm.png"):
        continue
    dom = base.rsplit(".", 1)[0]
    try:
        im = Image.open(f)
        # Multi-image .ico files and SVG-adjacent formats render unreliably in the
        # browser at small sizes; normalise everything to a plain 64px PNG.
        if getattr(im, "n_frames", 1) > 1 or im.format == "ICO":
            im.size = max(im.ico.sizes()) if hasattr(im, "ico") else im.size
        im = im.convert("RGBA")
        im.thumbnail((64, 64))
        norm = os.path.join(OUT, dom + ".norm.png")
        im.save(norm, "PNG")
        tot = n = near_white = transparent = total_px = 0
        for r, g, b, a in im.getdata():
            total_px += 1
            if a < 40:                      # ignore transparent pixels entirely
                transparent += 1
                continue
            l = 0.2126 * r + 0.7152 * g + 0.0722 * b
            mx, mn = max(r, g, b), min(r, g, b)
            sat = 0 if mx == 0 else (mx - mn) / mx
            if l > 215 and sat < 0.15:      # this pixel would vanish on white
                near_white += 1
            tot += l
            n += 1
        lum = (tot / n) if n else 128
        white_frac = (near_white / n) if n else 0
        trans_frac = (transparent / total_px) if total_px else 0
        # A logo drawn on its own opaque background is fine on any tile - it
        # brings its own. Only a mark floating on transparency can vanish, so
        # require real transparency before judging it a white mark.
        is_white_mark = trans_frac > 0.25 and white_frac > 0.40
        res[dom] = {"file": dom + ".norm.png", "lum": round(lum, 1),
                    "white_frac": round(white_frac, 3),
                    "trans_frac": round(trans_frac, 3), "light": is_white_mark}
    except Exception:
        res[dom] = {"file": base, "lum": None, "light": False}

json.dump(res, open(os.path.join(OUT, "tint.json"), "w"), indent=1)
for d, v in sorted(res.items()):
    verdict = "white mark -> DARK tile" if v["light"] else "light tile"
    print("  %-34s white=%5s trans=%5s  %s"
          % (d, v.get("white_frac"), v.get("trans_frac"), verdict))
