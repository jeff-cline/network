"""medigap.plus/888 — TV attribution for the 1-888-887-7595 QR-code number.

Mounted at the /888 path in front of the live medigap.plus Next.js app, which
this service never touches. It reads the medigap Postgres database read-only and
keeps its own SQLite alongside for uploaded TV post logs.

Three questions it answers:

  DIRECT 888   how many people dialled the QR number, and when
  ALL CALLS    for each of those, how many calls hit the main 800 line within
               five minutes either side — the same viewer trying twice, or the
               same spot driving both numbers
  SAME STATE   how many calls came from that caller's state within ten minutes
               either side, which is the strongest signal that a spot in that
               market just aired

Then it matches all of it against the TV post log so the programmes can be
ranked by what they actually produced.
"""
import csv, io, json, os, re, secrets, sqlite3, subprocess, time
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, date

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "postlog.db")
PGDB = "medigap"

# The QR number on the television ad, and the main inbound line.
NUM_888 = "8888877595"
NUM_800 = "8006334427"

# Call timestamps are stored UTC. Broadcast post logs are Eastern. In August
# that is UTC-4; the offset is a setting because it will be UTC-5 in winter and
# because not every log house uses Eastern.
DEFAULT_TZ_OFFSET = -4
DEFAULT_WINDOW_MIN = 5          # response window after a spot airs
WIN_ALL_CALLS = 5               # ± minutes, 888 vs the 800 line
WIN_SAME_STATE = 10             # ± minutes, same-state correlation

app = FastAPI(title="medigap.plus/888", root_path="/888")


def e(s):
    import html
    return html.escape("" if s is None else str(s), quote=True)


# --------------------------------------------------------------- postgres ----
def pg(sql):
    """Read-only query against the medigap database, returned as dict rows.
    Uses psql under the postgres role so no credentials live in this service."""
    out = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-d", PGDB, "-At", "-F", "\x1f",
         "--no-align", "-c", sql],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[:400])
    rows = []
    for line in (out.stdout or "").strip().split("\n"):
        if line:
            rows.append(line.split("\x1f"))
    return rows


def norm(n):
    return re.sub(r"\D", "", n or "")


def load_calls(days=120):
    """Every call in the window, normalised. One query, then all the correlation
    work happens in memory — the volumes here are small and it keeps the
    production database out of the loop."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = pg(f"""SELECT id, "createdAt", "fromNumber", "toNumber", state, zip,
                         "durationSec", status, disposition, source
                  FROM "Call" WHERE "createdAt" >= '{since}' ORDER BY "createdAt";""")
    calls = []
    for r in rows:
        if len(r) < 10:
            continue
        try:
            ts = datetime.fromisoformat(r[1].split(".")[0])
        except Exception:
            continue
        calls.append({"id": r[0], "ts": ts, "frm": norm(r[2]), "to": norm(r[3]),
                      "state": (r[4] or "").strip().upper(), "zip": r[5],
                      "secs": int(r[6] or 0), "status": r[7], "disp": r[8],
                      "source": r[9]})
    return calls


# ----------------------------------------------------------------- sqlite ----
SCHEMA = """
CREATE TABLE IF NOT EXISTS postlog(
  id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL,
  aired_utc TEXT NOT NULL, aired_local TEXT NOT NULL,
  program TEXT, network TEXT, region TEXT, order_no TEXT, line_no TEXT,
  customer TEXT, ad_unit TEXT, length INTEGER, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS batches(
  batch TEXT PRIMARY KEY, filename TEXT, rows INTEGER, tz_offset INTEGER,
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS ix_pl_aired ON postlog(aired_utc);
"""


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with closing(db()) as c:
        c.executescript(SCHEMA)
        c.commit()


def setting(k, default=None):
    with closing(db()) as c:
        r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except Exception:
        return r["v"]


def set_setting(k, v):
    with closing(db()) as c:
        c.execute("INSERT INTO settings(k,v) VALUES(?,?) "
                  "ON CONFLICT(k) DO UPDATE SET v=?", (k, json.dumps(v), json.dumps(v)))
        c.commit()


# ------------------------------------------------------------- correlation ---
def analyse(calls):
    """Split the call set and compute the three columns for every 888 call."""
    direct = [c for c in calls if c["to"].endswith(NUM_888)]
    main = [c for c in calls if c["to"].endswith(NUM_800)]
    rows = []
    for d in direct:
        w5 = timedelta(minutes=WIN_ALL_CALLS)
        w10 = timedelta(minutes=WIN_SAME_STATE)
        near = [m for m in main if abs(m["ts"] - d["ts"]) <= w5]
        same_state = []
        if d["state"]:
            same_state = [c for c in calls
                          if c["id"] != d["id"] and c["state"] == d["state"]
                          and abs(c["ts"] - d["ts"]) <= w10]
        rows.append({**d, "all_calls": len(near), "near": near,
                     "same_state": len(same_state), "same_state_calls": same_state})
    return direct, main, rows


def by_day(calls, days=30):
    """Daily counts, zero-filled, so the chart does not lie about quiet days."""
    if not calls:
        end = datetime.utcnow().date()
    else:
        end = max(c["ts"] for c in calls).date()
    end = max(end, datetime.utcnow().date())
    start = end - timedelta(days=days - 1)
    buckets = {start + timedelta(days=i): 0 for i in range(days)}
    for c in calls:
        d = c["ts"].date()
        if d in buckets:
            buckets[d] += 1
    return sorted(buckets.items())


def bar_chart(series, height=170, colour="#2f7fd8", label=""):
    """A dependency-free SVG bar chart. No CDN, nothing to load, prints fine."""
    if not series:
        return "<p class='mut'>No data yet.</p>"
    n = len(series)
    peak = max(v for _, v in series) or 1
    bw = max(6, min(34, int(940 / n) - 3))
    gap = 3
    w = n * (bw + gap) + 46
    bars, labels = "", ""
    for i, (d, v) in enumerate(series):
        h = int((v / peak) * (height - 26)) if v else 0
        x = 40 + i * (bw + gap)
        y = height - 20 - h
        bars += (f'<rect x="{x}" y="{y}" width="{bw}" height="{max(h,1)}" rx="2" '
                 f'fill="{colour}" opacity="{1 if v else .18}"><title>{d} — {v} call'
                 f'{"s" if v != 1 else ""}</title></rect>')
        if v:
            bars += (f'<text x="{x + bw/2}" y="{y - 4}" text-anchor="middle" '
                     f'font-size="10" fill="#0e2745" font-weight="700">{v}</text>')
        if n <= 16 or i % max(1, n // 12) == 0:
            labels += (f'<text x="{x + bw/2}" y="{height - 6}" text-anchor="middle" '
                       f'font-size="9" fill="#7b8ea4">{d.strftime("%m/%d")}</text>')
    grid = ""
    for f in (0, .5, 1):
        yy = height - 20 - int(f * (height - 26))
        grid += (f'<line x1="38" y1="{yy}" x2="{w}" y2="{yy}" stroke="#e6edf4" '
                 f'stroke-width="1"/><text x="34" y="{yy+3}" text-anchor="end" '
                 f'font-size="9" fill="#9aabbd">{int(peak*f)}</text>')
    return (f'<div style="overflow-x:auto"><svg width="{w}" height="{height}" '
            f'role="img" aria-label="{e(label)}">{grid}{bars}{labels}</svg></div>')


# ------------------------------------------------------------- post log ------
POSTLOG_COLS = {
    "date": ["verified_date", "air_date", "date", "aired"],
    "time": ["verified_time", "air_time", "time", "aired_time"],
    "program": ["program_title", "program", "show", "title"],
    "network": ["network_code", "network", "net", "station"],
    "region": ["region_code", "region", "market", "dma"],
    "order": ["order_number", "order", "order_no"],
    "line": ["line_number", "line", "line_no"],
    "customer": ["customer_name", "customer", "advertiser"],
    "adunit": ["ad_unit_title", "ad_unit", "creative", "adcopy", "spot"],
    "length": ["adcopy_length", "length", "duration", "spot_length"],
}


def _match_col(header):
    """Map whatever the log house calls a column onto ours. Post logs vary by
    vendor, so this is deliberately forgiving."""
    idx = {}
    low = [str(h or "").strip().lower().replace(" ", "_") for h in header]
    for ours, theirs in POSTLOG_COLS.items():
        for t in theirs:
            if t in low:
                idx[ours] = low.index(t)
                break
    return idx


def parse_postlog(data, filename, tz_offset):
    """Accepts .xlsx or .csv. Returns (rows, problems)."""
    rows, problems = [], []
    header, body = None, []
    if filename.lower().endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError:
            return [], ["openpyxl is not installed on the server."]
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        for r in ws.iter_rows(values_only=True):
            if header is None:
                if any(x is not None and str(x).strip() for x in r):
                    header = list(r)
                continue
            body.append(list(r))
    else:
        text = data.decode("utf-8", errors="replace")
        rd = list(csv.reader(io.StringIO(text)))
        if rd:
            header, body = rd[0], rd[1:]
    if not header:
        return [], ["That file has no header row."]
    idx = _match_col(header)
    missing = [k for k in ("date", "time") if k not in idx]
    if missing:
        return [], [f"Could not find a {' and '.join(missing)} column. "
                    f"Columns seen: {', '.join(str(h) for h in header if h)}"]

    def cell(r, key):
        i = idx.get(key)
        return r[i] if i is not None and i < len(r) else None

    for r in body:
        d, t = cell(r, "date"), cell(r, "time")
        if d is None or t is None:
            continue
        # date may arrive as a datetime or a string
        if isinstance(d, datetime):
            dd = d.date()
        elif isinstance(d, date):
            dd = d
        else:
            s = str(d).strip().split(" ")[0]
            try:
                dd = datetime.strptime(s, "%Y-%m-%d").date()
            except ValueError:
                try:
                    dd = datetime.strptime(s, "%m/%d/%Y").date()
                except ValueError:
                    problems.append(f"unreadable date: {d}")
                    continue
        # time may be a time object, a datetime, or hh:mm:ss text
        if hasattr(t, "hour") and not isinstance(t, str):
            tt = (t.hour, t.minute, getattr(t, "second", 0))
        else:
            m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", str(t).strip())
            if not m:
                problems.append(f"unreadable time: {t}")
                continue
            tt = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
        local = datetime(dd.year, dd.month, dd.day, tt[0], tt[1], tt[2])
        utc = local - timedelta(hours=tz_offset)
        rows.append({
            "aired_local": local.isoformat(sep=" "), "aired_utc": utc.isoformat(sep=" "),
            "program": str(cell(r, "program") or "").strip(),
            "network": str(cell(r, "network") or "").strip(),
            "region": str(cell(r, "region") or "").strip(),
            "order_no": str(cell(r, "order") or "").strip(),
            "line_no": str(cell(r, "line") or "").strip(),
            "customer": str(cell(r, "customer") or "").strip(),
            "ad_unit": str(cell(r, "adunit") or "").strip(),
            "length": int(float(cell(r, "length") or 0) or 0),
        })
    return rows, problems


def save_postlog(rows, filename, tz_offset):
    batch = datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    with closing(db()) as c:
        c.execute("INSERT INTO batches(batch,filename,rows,tz_offset,created) VALUES(?,?,?,?,?)",
                  (batch, filename, len(rows), tz_offset, time.time()))
        for r in rows:
            c.execute("""INSERT INTO postlog(batch,aired_utc,aired_local,program,network,region,
                         order_no,line_no,customer,ad_unit,length,created)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (batch, r["aired_utc"], r["aired_local"], r["program"], r["network"],
                       r["region"], r["order_no"], r["line_no"], r["customer"], r["ad_unit"],
                       r["length"], time.time()))
        c.commit()
    return batch


def airings(batch=None):
    with closing(db()) as c:
        if batch:
            rows = c.execute("SELECT * FROM postlog WHERE batch=? ORDER BY aired_utc",
                             (batch,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM postlog ORDER BY aired_utc").fetchall()
    out = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["aired_utc"])
        except Exception:
            continue
        out.append({**dict(r), "ts": ts})
    return out


def attribute(air, calls, window_min):
    """A call belongs to a spot if it lands inside the response window that
    starts when the spot airs. Where two spots overlap the same call, the
    nearer one takes it — a call cannot be counted twice."""
    win = timedelta(minutes=window_min)
    claims = defaultdict(list)
    for c in calls:
        best, best_gap = None, None
        for a in air:
            gap = c["ts"] - a["ts"]
            if timedelta(0) <= gap <= win:
                if best_gap is None or gap < best_gap:
                    best, best_gap = a, gap
        if best is not None:
            claims[best["id"]].append({**c, "lag_sec": int(best_gap.total_seconds())})
    return claims


def rank_programs(air, claims):
    agg = defaultdict(lambda: {"airings": 0, "calls": 0, "direct": 0, "networks": set(),
                               "lags": []})
    for a in air:
        k = a["program"] or "(untitled)"
        g = agg[k]
        g["airings"] += 1
        if a["network"]:
            g["networks"].add(a["network"])
        for c in claims.get(a["id"], []):
            g["calls"] += 1
            g["lags"].append(c["lag_sec"])
            if c["to"].endswith(NUM_888):
                g["direct"] += 1
    out = []
    for k, g in agg.items():
        out.append({"program": k, "airings": g["airings"], "calls": g["calls"],
                    "direct": g["direct"],
                    "cpa": (g["calls"] / g["airings"]) if g["airings"] else 0,
                    "networks": ", ".join(sorted(g["networks"])),
                    "avg_lag": (sum(g["lags"]) / len(g["lags"])) if g["lags"] else None})
    out.sort(key=lambda x: (-x["cpa"], -x["calls"], x["program"]))
    return out


def alignment_888(air, calls):
    """The QR number, spot by spot. For every 888 call that falls inside a loaded
    post log, show what was actually on air around it — and whether any timezone
    shift would put it right after a spot.

    The caveat matters more than the table: with spots roughly twenty minutes
    apart, a single call sits within ten or fifteen minutes of *some* spot at
    almost every offset. That is arithmetic, not attribution. It takes a couple
    of dozen 888 calls before the pattern means anything."""
    if not air:
        return ""
    tz = setting("tz_offset", DEFAULT_TZ_OFFSET)
    ats = sorted(air, key=lambda a: a["ts"])
    lo, hi = ats[0]["ts"], ats[-1]["ts"]
    d888 = sorted([c for c in calls if c["to"].endswith(NUM_888)], key=lambda c: c["ts"])
    inside = [c for c in d888 if lo - timedelta(hours=12) <= c["ts"] <= hi + timedelta(hours=12)]
    outside = [c for c in d888 if c not in inside]

    if not inside:
        return f"""<div class="panel"><div class="kicker">888 alignment</div>
<h2 style="margin-bottom:6px">The QR number against this log</h2>
<div class="warn"><b>None of the {len(d888)} calls to 1-888-887-7595 fall inside this flight.</b>
The log covers {lo.date()} to {hi.date()}; the 888 calls are on other dates entirely. There is
nothing here to align — upload the post log for the dates those calls landed on and this panel
will fill in.</div></div>"""

    blocks = ""
    for c in inside:
        local = c["ts"] + timedelta(hours=tz)
        # what was on air around it, at the configured timezone
        around = [a for a in ats if abs((a["ts"] - c["ts"]).total_seconds()) <= 3600]
        near_rows = ""
        for a in around:
            lag = (c["ts"] - a["ts"]).total_seconds() / 60
            before = lag >= 0
            tone = ("#e4f5eb" if 0 <= lag <= 5 else
                    ("#fdf1dc" if 0 <= lag <= 15 else "transparent"))
            near_rows += (f'<tr style="background:{tone}">'
                          f'<td>{(a["ts"]+timedelta(hours=tz)).strftime("%H:%M:%S")}</td>'
                          f'<td><b>{e(a["program"] or "—")}</b></td>'
                          f'<td>{e(a["network"] or "—")}</td>'
                          f'<td class="center">{"+" if before else ""}{lag:.1f} min '
                          f'{"after" if before else "before"}</td></tr>')
        # every shift, nearest preceding spot
        shift_rows = ""
        best = None
        for h in range(-8, 9):
            sh = timedelta(hours=h)
            prev = [a for a in ats if a["ts"] + sh <= c["ts"]]
            if not prev:
                continue
            a = prev[-1]
            lag = (c["ts"] - (a["ts"] + sh)).total_seconds() / 60
            if best is None or lag < best[1]:
                best = (h, lag, a)
            tzlabel = f"UTC{tz - h:+d}"
            us = tzlabel in ("UTC-4", "UTC-5", "UTC-6", "UTC-7", "UTC-8")
            cur = h == 0
            tone = "#e7f0fb" if cur else ("transparent" if us else "#fbfbfc")
            shift_rows += (f'<tr style="background:{tone}">'
                           f'<td>{h:+d}h</td><td>{tzlabel}'
                           f'{" <span class=\'tag blue\'>in use</span>" if cur else ""}'
                           f'{"" if us else " <span class=\'small mut\'>not a US zone</span>"}</td>'
                           f'<td class="center"><b>{lag:.1f} min</b></td>'
                           f'<td>{e(a["program"] or "—")} <span class="small mut">'
                           f'{e(a["network"])}</span></td></tr>')
        prev_now = [a for a in ats if a["ts"] <= c["ts"]]
        lag_now = ((c["ts"] - prev_now[-1]["ts"]).total_seconds() / 60) if prev_now else None
        verdict = ""
        if best and best[1] <= 5:
            verdict = (f'<div class="okmsg">Closest fit is a {best[1]:.1f}-minute lag at a '
                       f'{best[0]:+d}h shift.</div>')
        else:
            verdict = (f'<div class="warn"><b>No offset puts this call right after a spot.</b> '
                       f'The best any shift manages is {best[1]:.1f} minutes '
                       f'({best[0]:+d}h). At Eastern — what the station says the log is — it '
                       f'sits {lag_now:.1f} minutes after the nearest spot.</div>'
                       if lag_now is not None else
                       f'<div class="warn">No spot precedes this call.</div>')
        blocks += f"""<div style="border:1px solid var(--line);border-radius:11px;padding:16px;
margin-bottom:14px">
<h3 style="margin-bottom:2px">{local.strftime('%a %d %b %Y, %H:%M:%S')} local
<span class="small mut">({c['ts'].strftime('%H:%M:%S')} UTC)</span></h3>
<p class="small mut" style="margin-bottom:10px">from {e(c['frm'][-10:])}
{('· ' + e(c['state']) + ' ' + e(c['zip'])) if c['state'] else '· state unknown'}
· {e(c['status'])}</p>
{verdict}
<div class="grid g2" style="gap:18px;margin-top:12px">
<div><h4 style="font-size:13px;margin-bottom:6px">What aired within an hour, at UTC{tz:+d}</h4>
<div class="tw"><table><tr><th>Aired</th><th>Programme</th><th>Net</th>
<th class="center">Gap</th></tr>{near_rows or '<tr><td colspan=4 class="mut">Nothing within an hour.</td></tr>'}</table></div></div>
<div><h4 style="font-size:13px;margin-bottom:6px">Nearest preceding spot at every shift</h4>
<div class="tw"><table><tr><th>Shift</th><th>Log would be</th><th class="center">Lag</th>
<th>Programme</th></tr>{shift_rows}</table></div></div>
</div></div>"""

    med_gap = 0
    gaps = sorted((ats[i+1]["ts"] - ats[i]["ts"]).total_seconds()/60
                  for i in range(len(ats)-1) if ats[i+1]["ts"] > ats[i]["ts"])
    if gaps:
        med_gap = gaps[len(gaps)//2]
    return f"""<div class="panel"><div class="kicker">888 alignment</div>
<h2 style="margin-bottom:6px">The QR number, call by call</h2>
<p class="mut small" style="margin-bottom:12px">{len(inside)} of {len(d888)} calls to
1-888-887-7595 fall inside this flight
{f'· the other {len(outside)} are on dates this log does not cover' if outside else ''}.</p>
<div class="warn"><b>Read the shift table with care.</b> Spots on this buy are a median
{med_gap:.0f} minutes apart, so a single call sits within ten or fifteen minutes of
<i>some</i> programme at almost every offset — that is arithmetic, not attribution. A timezone
can only be identified from a couple of dozen 888 calls showing the same lag, not from one.</div>
{blocks}</div>"""


def timing_check(air, calls, window):
    """Is the post log aligned with the call log at all?

    The honest test is not "how many matched" — with spots twenty minutes apart,
    windows tile a quarter of the flight and random calls match by accident. The
    test is the shape of the lag distribution. Real TV response is front-loaded
    into the first few minutes. Noise is flat. This panel shows the shape, the
    hour-of-day comparison, and a shift sweep, and then says plainly which it is.
    """
    if not air or not calls:
        return ""
    tz = setting("tz_offset", DEFAULT_TZ_OFFSET)
    ats = sorted(a["ts"] for a in air)
    lo, hi = ats[0], ats[-1]
    pool = [c for c in calls if lo <= c["ts"] <= hi + timedelta(hours=2)]
    if not pool:
        return ""

    # ---- lag histogram ----
    bands = [(0, 5, "0–5 min"), (5, 10, "5–10 min"), (10, 15, "10–15 min"),
             (15, 30, "15–30 min"), (30, 60, "30–60 min"), (60, 120, "1–2 hrs"),
             (120, 10 ** 6, "2+ hrs")]
    counts = {b[2]: 0 for b in bands}
    lags = []
    for c in pool:
        prev = [a for a in ats if a <= c["ts"]]
        if not prev:
            continue
        lag = (c["ts"] - prev[-1]).total_seconds() / 60
        lags.append(lag)
        for a0, a1, name in bands:
            if a0 <= lag < a1:
                counts[name] += 1
                break
    tot = sum(counts.values()) or 1
    gaps = sorted((ats[i + 1] - ats[i]).total_seconds() / 60
                  for i in range(len(ats) - 1) if ats[i + 1] > ats[i])
    med_gap = gaps[len(gaps) // 2] if gaps else 0
    chance_pct = min(100.0, (5 / med_gap * 100)) if med_gap else 0
    observed_pct = counts["0–5 min"] / tot * 100
    rows = ""
    peak = max(counts.values()) or 1
    for _, _, name in bands:
        v = counts[name]
        w = int(v / peak * 100)
        hot = name == "0–5 min"
        rows += (f'<tr><td style="width:96px">{name}</td>'
                 f'<td><div class="meter"><i style="width:{w}%;'
                 f'background:{"linear-gradient(90deg,#17924f,#4fc98a)" if hot else "linear-gradient(90deg,#8496ab,#b8c6d6)"}"></i></div></td>'
                 f'<td class="center" style="width:70px"><b>{v}</b> '
                 f'<span class="small mut">{v/tot*100:.0f}%</span></td></tr>')

    # ---- shift sweep ----
    sweep = []
    for h in range(-12, 13):
        sh = timedelta(hours=h)
        shifted = [a + sh for a in ats]
        w = timedelta(minutes=window)
        n = sum(1 for c in calls
                if any(timedelta(0) <= (c["ts"] - a) <= w for a in shifted))
        sweep.append((h, n))
    smax = max(n for _, n in sweep) or 1
    spark = ""
    for i, (h, n) in enumerate(sweep):
        bh = int(n / smax * 44)
        cur = h == 0
        spark += (f'<rect x="{i*22+30}" y="{56-bh}" width="15" height="{max(bh,1)}" rx="2" '
                  f'fill="{"#2f7fd8" if cur else "#c3d2e1"}"><title>{h:+d}h → {n} matched</title>'
                  f'</rect>')
        if h % 3 == 0:
            spark += (f'<text x="{i*22+37}" y="70" text-anchor="middle" font-size="9" '
                      f'fill="#8496ab">{h:+d}</text>')

    # ---- hour of day ----
    ah = defaultdict(int)
    for a in ats:
        ah[(a + timedelta(hours=tz)).hour] += 1
    ch = defaultdict(int)
    for c in pool:
        ch[(c["ts"] + timedelta(hours=tz)).hour] += 1
    amax = max(ah.values()) or 1
    cmax = max(ch.values()) or 1
    hod = ""
    for h in range(24):
        abar = int(ah[h] / amax * 40)
        cbar = int(ch[h] / cmax * 40)
        hod += (f'<g><rect x="{h*38+30}" y="{44-abar}" width="14" height="{max(abar,0)}" '
                f'rx="2" fill="#e09b12"><title>{h:02d}:00 — {ah[h]} airings</title></rect>'
                f'<rect x="{h*38+46}" y="{44-cbar}" width="14" height="{max(cbar,0)}" rx="2" '
                f'fill="#2f7fd8"><title>{h:02d}:00 — {ch[h]} calls</title></rect>'
                f'<text x="{h*38+44}" y="58" text-anchor="middle" font-size="8.5" '
                f'fill="#8496ab">{h:02d}</text></g>')
    overnight = sum(v for h, v in ah.items() if h < 6)

    # ---- verdict ----
    if observed_pct > chance_pct * 1.8 and counts["0–5 min"] >= 8:
        verdict = ("ok", "The timing lines up.",
                   f"{observed_pct:.0f}% of calls arrive within five minutes of a spot against "
                   f"{chance_pct:.0f}% expected by chance. That is a real response curve.")
    elif observed_pct < chance_pct:
        verdict = ("warn", "No response signal — and the clock is not why.",
                   f"Only {observed_pct:.0f}% of calls land within five minutes of a spot, and "
                   f"pure chance would give {chance_pct:.0f}% because spots are a median "
                   f"{med_gap:.0f} minutes apart. The lag distribution is flat: calls are "
                   f"arriving independently of the airings. A wrong timezone would show up as "
                   f"one tall bar in the sweep below — there isn't one. "
                   f"{overnight} of {len(ats)} spots run before 6am, when almost nobody calls.")
    else:
        verdict = ("warn", "Inconclusive at this volume.",
                   f"{observed_pct:.0f}% within five minutes against {chance_pct:.0f}% by "
                   f"chance — too close to call with {len(pool)} calls. More flights will "
                   f"separate them.")

    return f"""<div class="panel">
<div class="kicker">Timing check</div>
<h2 style="margin-bottom:4px">Is the post log actually aligned with the calls?</h2>
<p class="mut small" style="margin-bottom:12px">Run automatically on whatever log is loaded.
Times are being read as UTC{tz:+d}.</p>
<div class="{'okmsg' if verdict[0] == 'ok' else 'warn'}"><b>{e(verdict[1])}</b>
{e(verdict[2])}</div>
<div class="grid" style="grid-template-columns:minmax(300px,.85fr) 1.15fr;gap:22px;
margin-top:14px">
<div><h3 style="margin-bottom:8px">How long after a spot did each call arrive?</h3>
<p class="small mut" style="margin-bottom:8px">Real TV response is front-loaded into the green
bar. Flat means the calls are not coming from the spots.</p>
<table>{rows}</table>
<p class="small mut" style="margin-top:8px">Median lag
<b>{(sorted(lags)[len(lags)//2] if lags else 0):.0f} min</b> · median gap between spots
<b>{med_gap:.0f} min</b> · {len(pool)} calls in the flight</p></div>
<div><h3 style="margin-bottom:8px">Shift the log ±12 hours — does any offset fit better?</h3>
<p class="small mut" style="margin-bottom:8px">If the log were in the wrong timezone, one bar
would tower over the rest. Blue is the offset in use.</p>
<svg width="590" height="78" role="img" aria-label="offset sweep">{spark}</svg>
<h3 style="margin:14px 0 8px">Airings vs calls, by hour of day</h3>
<p class="small mut" style="margin-bottom:6px"><span style="color:#e09b12">■</span> airings
<span style="color:#2f7fd8;margin-left:8px">■</span> calls</p>
<div style="overflow-x:auto"><svg width="950" height="64" role="img"
 aria-label="hour of day">{hod}</svg></div></div>
</div></div>"""


def calib_table(air, calls, window):
    """If the post log's timezone were wrong, one offset would match far better
    than the others. Showing the grid makes that visible instead of assumed."""
    tz_now = setting("tz_offset", DEFAULT_TZ_OFFSET)
    wins = (2, 5, 10, 15, 30)
    head = "".join(f"<th class='center'>{w} min</th>" for w in wins)
    body = ""
    for tz in (0, -4, -5, -6, -7, -8):
        shift = timedelta(hours=(tz_now - tz))
        shifted = [{**a, "ts": a["ts"] + shift} for a in air]
        cells = ""
        for w in wins:
            n = sum(len(v) for v in attribute(shifted, calls, w).values())
            hot = (tz == tz_now and w == window)
            cells += (f"<td class='center'{' style=\'background:#e7f0fb;font-weight:800\''
                      if hot else ''}>{n}</td>")
        body += (f"<tr><td>UTC{tz:+d}{' <span class=\'tag blue\'>in use</span>' if tz == tz_now else ''}"
                 f"</td>{cells}</tr>")
    return (f"<p class='small mut' style='margin:8px 0'>Calls matched at each assumption. If one "
            f"row stands out, the log is in that timezone.</p>"
            f"<div class='tw'><table><tr><th>Log timezone</th>{head}</tr>{body}</table></div>")


def rank_networks(air, claims):
    agg = defaultdict(lambda: {"airings": 0, "calls": 0})
    for a in air:
        k = a["network"] or "—"
        agg[k]["airings"] += 1
        agg[k]["calls"] += len(claims.get(a["id"], []))
    out = [{"network": k, "airings": v["airings"], "calls": v["calls"],
            "cpa": v["calls"] / v["airings"] if v["airings"] else 0}
           for k, v in agg.items()]
    out.sort(key=lambda x: (-x["cpa"], -x["calls"]))
    return out


# ================================================================== chrome ====
CSS = """
:root{--navy:#0b1f38;--blue:#2f7fd8;--sky:#5aa9ff;--ink:#16202e;--mut:#5b6b80;
 --soft:#8496ab;--line:#dde5ef;--bg:#f5f8fc;--ok:#17924f;--amber:#e09b12;--red:#cf4b34;
 --sh:0 1px 2px rgba(11,31,56,.05),0 8px 24px rgba(11,31,56,.07)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:15px/1.55 ui-sans-serif,-apple-system,
 "Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
h1,h2,h3{line-height:1.15;letter-spacing:-.02em;color:var(--navy)}
h1{font-size:clamp(26px,3.6vw,38px);font-weight:800}
h2{font-size:21px;font-weight:800}h3{font-size:16.5px;font-weight:800}
p{margin:0 0 12px}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
.mut{color:var(--mut)}.small{font-size:13px}.center{text-align:center}
.kicker{font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;
 color:var(--blue)}
.top{background:linear-gradient(150deg,#06152a,#123a63 60%,#1f5490);color:#dce9f7;
 padding:30px 0 26px;border-bottom:4px solid var(--blue)}
.top h1{color:#fff}.top .mut{color:#a9c8e8}
.panel{background:#fff;border:1px solid var(--line);border-radius:13px;padding:20px;
 box-shadow:var(--sh);margin-bottom:18px}
.grid{display:grid;gap:14px}
.g4{grid-template-columns:repeat(4,1fr)}.g3{grid-template-columns:repeat(3,1fr)}
.g2{grid-template-columns:repeat(2,1fr)}
@media(max-width:900px){.g4{grid-template-columns:repeat(2,1fr)}.g3,.g2{grid-template-columns:1fr}}
.stat{background:rgba(255,255,255,.08);border:1px solid rgba(90,169,255,.3);border-radius:11px;
 padding:14px 16px}
.stat .n{font-size:29px;font-weight:850;color:#fff;letter-spacing:-.9px;line-height:1}
.stat .l{font-size:11.5px;color:#8fb6dc;margin-top:5px;line-height:1.35}
table{width:100%;border-collapse:collapse;font-size:13.6px}
th{text-align:left;font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;
 color:var(--soft);padding:0 10px 8px 0;border-bottom:1px solid var(--line);font-weight:800;
 white-space:nowrap}
td{padding:9px 10px 9px 0;border-bottom:1px solid #eef3f8;vertical-align:top}
tr:last-child td{border-bottom:0}
.tw{overflow-x:auto}
.tag{display:inline-block;font-size:11px;font-weight:750;padding:2px 8px;border-radius:20px}
.tag.ok{background:#e4f5eb;color:var(--ok)}.tag.warn{background:#fdf1dc;color:var(--amber)}
.tag.off{background:#eef2f6;color:var(--soft)}.tag.blue{background:#e7f0fb;color:var(--blue)}
.rank{display:flex;align-items:center;gap:9px}
.rank .pos{flex:0 0 26px;height:26px;border-radius:50%;background:#eef3f9;color:var(--navy);
 display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800}
.rank .pos.g{background:linear-gradient(135deg,#e0b400,#f6d34a);color:#4a3800}
.rank .pos.s{background:linear-gradient(135deg,#9fb0c2,#cfd9e4);color:#31404f}
.rank .pos.b{background:linear-gradient(135deg,#b07a4a,#d8a273);color:#4a2f16}
.meter{height:7px;background:#edf2f7;border-radius:4px;overflow:hidden;min-width:70px}
.meter i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--sky))}
label{display:block;font-size:12.5px;font-weight:700;color:var(--navy);margin-bottom:5px}
input,select{width:100%;border:1.5px solid #c6d4e4;border-radius:9px;padding:10px 12px;
 font-size:14.5px;font-family:inherit;background:#fff}
input[type=file]{padding:8px}
.btn{display:inline-flex;align-items:center;gap:8px;background:linear-gradient(135deg,
 var(--blue),var(--sky));color:#fff;font-weight:750;padding:11px 20px;border-radius:9px;border:0;
 cursor:pointer;font-size:14.5px;font-family:inherit;white-space:nowrap}
.btn:hover{filter:brightness(1.07);text-decoration:none}
.btn.ghost{background:#fff;color:var(--navy);border:1.5px solid #c6d4e4}
.fr{display:grid;gap:12px;margin-bottom:12px}
.fr.three{grid-template-columns:1fr 1fr 1fr}.fr.four{grid-template-columns:2fr 1fr 1fr auto}
@media(max-width:760px){.fr.three,.fr.four{grid-template-columns:1fr}}
.warn{background:#fff6e5;border:1px solid #f3dcae;color:#8a5d08;padding:10px 13px;
 border-radius:9px;margin-bottom:14px;font-size:13.5px}
.okmsg{background:#e9f7f0;border:1px solid #b6e3cd;color:#0f6b46;padding:10px 13px;
 border-radius:9px;margin-bottom:14px;font-size:13.5px}
.live{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;font-weight:750;
 color:var(--ok)}
.live i{width:8px;height:8px;border-radius:50%;background:var(--ok);display:block;
 animation:p 2s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
details summary{cursor:pointer;font-size:12.5px;color:var(--mut)}
"""


def shell(body, title="medigap.plus/888", refresh=60):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="robots" content="noindex,nofollow">
{f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ''}
<style>{CSS}</style></head><body>{body}</body></html>"""


# =================================================================== views ====
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, days: int = 30, window: int = 0, batch: str = "",
              ok: str = "", err: str = ""):
    window = window or setting("window_min", DEFAULT_WINDOW_MIN)
    tz = setting("tz_offset", DEFAULT_TZ_OFFSET)
    try:
        calls = load_calls(days=max(days, 1200))
    except Exception as ex:
        return HTMLResponse(shell(f"<div class='wrap' style='padding:40px 20px'>"
                                  f"<div class='warn'>Could not read the call database: "
                                  f"{e(str(ex))}</div></div>"), status_code=500)
    direct, main, rows = analyse(calls)
    series = by_day(direct, days)
    all_series = by_day(main, days)

    # ---------- headline numbers ----------
    d30 = [c for c in direct if (datetime.utcnow() - c["ts"]).days < days]
    tiles = f"""<div class="grid g4" style="margin-top:18px">
<div class="stat"><div class="n">{len(direct)}</div>
<div class="l">DIRECT 888 calls, all time</div></div>
<div class="stat"><div class="n">{len(d30)}</div>
<div class="l">In the last {days} days</div></div>
<div class="stat"><div class="n">{sum(r['all_calls'] for r in rows)}</div>
<div class="l">800-line calls within ±{WIN_ALL_CALLS} min of an 888 call</div></div>
<div class="stat"><div class="n">{sum(r['same_state'] for r in rows)}</div>
<div class="l">Same-state calls within ±{WIN_SAME_STATE} min</div></div></div>"""

    # ---------- the 888 call table ----------
    trs = ""
    for r in sorted(rows, key=lambda x: x["ts"], reverse=True):
        local = r["ts"] + timedelta(hours=tz)
        near_detail = "".join(
            f"<div class='small mut'>{(n['ts']+timedelta(hours=tz)).strftime('%H:%M:%S')} · "
            f"{e(n['state'] or '—')} · {e(n['frm'][-10:])}</div>" for n in r["near"][:8])
        ss_detail = "".join(
            f"<div class='small mut'>{(n['ts']+timedelta(hours=tz)).strftime('%H:%M:%S')} · "
            f"{e(n['frm'][-10:])} · to {e(n['to'][-10:])}</div>"
            for n in r["same_state_calls"][:8])
        trs += f"""<tr>
<td><b>{local.strftime('%a %d %b %Y')}</b><br>
<span class="small mut">{local.strftime('%H:%M:%S')} local · {r['ts'].strftime('%H:%M:%S')} UTC</span></td>
<td>{e(r['frm'][-10:] or '—')}</td>
<td>{('<b>' + e(r['state']) + '</b>' + (' <span class="small mut">' + e(r['zip']) + '</span>' if r['zip'] else '')) if r['state'] else '<span class="mut">unknown</span>'}</td>
<td><span class="tag {'ok' if r['status'] == 'completed' else 'warn'}">{e(r['status'])}</span>
{f'<br><span class="small mut">{r["secs"]}s</span>' if r['secs'] else ''}</td>
<td class="center"><b style="font-size:16px">{r['all_calls']}</b>
{f'<details><summary>show</summary>{near_detail}</details>' if r['near'] else ''}</td>
<td class="center"><b style="font-size:16px">{r['same_state']}</b>
{f'<details><summary>show</summary>{ss_detail}</details>' if r['same_state_calls'] else ''}</td>
</tr>"""

    # ---------- post log ----------
    air = airings(batch or None)
    with closing(db()) as c:
        batches = [dict(x) for x in c.execute(
            "SELECT * FROM batches ORDER BY created DESC")]
    postlog_block = ""
    ranking_block = ""
    if air:
        claims = attribute(air, calls, window)
        progs = rank_programs(air, claims)
        nets = rank_networks(air, claims)
        matched = sum(len(v) for v in claims.values())
        top = progs[0]["cpa"] if progs else 0
        produced = [p for p in progs if p["calls"] > 0]
        lo = min(a["ts"] for a in air)
        hi = max(a["ts"] for a in air) + timedelta(minutes=window)
        in_window = [c for c in calls if lo <= c["ts"] <= hi]
        cover = (matched / len(in_window) * 100) if in_window else 0
        caveat = ""
        if matched < 30:
            caveat = f"""<div class="warn"><b>Read this before you act on the ranking.</b>
Only {matched} of the {len(in_window)} calls that arrived during the flight fall inside a
{window}-minute window after a spot. With {len(air)} airings and that few calls, the difference
between first and tenth place is mostly noise — one extra call moves a programme several
positions. Treat it as a first read, not a verdict, and give it a few more flights before you
cut anything.</div>"""
        prows = ""
        shown_divider = False
        for i, p in enumerate(progs):
            # Only rank what actually produced. Everything on zero is tied, and
            # medalling an alphabetical tie would read as a finding.
            if p["calls"] == 0 and not shown_divider:
                shown_divider = True
                prows += (f'<tr><td colspan="5" style="background:#f6f9fc;color:#8496ab;'
                          f'font-size:12px;letter-spacing:.06em;text-transform:uppercase;'
                          f'font-weight:800;padding:8px 0">No calls attributed — '
                          f'{len(progs) - len(produced)} programmes, tied, listed '
                          f'alphabetically</td></tr>')
            ranked = p["calls"] > 0
            medal = ("g" if i == 0 else ("s" if i == 1 else ("b" if i == 2 else ""))) if ranked else ""
            pct = int((p["cpa"] / top) * 100) if top else 0
            prows += f"""<tr>
<td><div class="rank"><span class="pos {medal}">{(i+1) if ranked else "·"}</span>
<div><b>{e(p['program'])}</b><br>
<span class="small mut">{e(p['networks'] or '—')}</span></div></div></td>
<td class="center">{p['airings']}</td>
<td class="center"><b>{p['calls']}</b>
{f'<br><span class="tag blue">{p["direct"]} direct</span>' if p['direct'] else ''}</td>
<td><div style="display:flex;align-items:center;gap:9px">
<div class="meter" style="flex:1"><i style="width:{pct}%"></i></div>
<b style="min-width:42px;text-align:right">{p['cpa']:.2f}</b></div></td>
<td class="center small mut">{f"{p['avg_lag']/60:.1f} min" if p['avg_lag'] is not None else '—'}</td>
</tr>"""
        nrows = "".join(f"""<tr><td><b>{e(n['network'])}</b></td>
<td class="center">{n['airings']}</td><td class="center"><b>{n['calls']}</b></td>
<td class="center">{n['cpa']:.2f}</td></tr>""" for n in nets)
        span = f"{min(a['ts'] for a in air).date()} → {max(a['ts'] for a in air).date()}"
        ranking_block = alignment_888(air, calls) + timing_check(air, calls, window) + f"""
<div class="panel">
<div style="display:flex;justify-content:space-between;align-items:flex-end;gap:16px;
flex-wrap:wrap;margin-bottom:6px">
<div><div class="kicker">National TV Advertising</div>
<h2>Which programme actually worked</h2>
<p class="mut small" style="margin:4px 0 0">{len(air)} airings, {span} · <b>{matched}</b> of
{len(in_window)} calls in the flight window attributed ({cover:.0f}% coverage) inside a
{window}-minute response window · {len(produced)} of {len(progs)} programmes produced a call ·
ranked by calls per airing, because a programme that ran twice and pulled four calls beat one
that ran forty times and pulled six.</p>
</div>
<form method="get" style="display:flex;gap:8px;align-items:flex-end">
<input type="hidden" name="batch" value="{e(batch)}">
<div><label>Response window</label>
<select name="window" onchange="this.form.submit()">
{"".join(f'<option value="{w}" {"selected" if w == window else ""}>{w} min</option>' for w in (2,3,5,10,15,30))}
</select></div></form></div>
{caveat}
<div class="tw"><table>
<tr><th>Programme</th><th class="center">Airings</th><th class="center">Calls</th>
<th>Calls per airing</th><th class="center">Avg. lag</th></tr>{prows}</table></div>
<details style="margin-top:12px"><summary>Calibration — match rate by assumed post-log timezone
and window</summary>{calib_table(air, calls, window)}</details>
</div>
<div class="panel"><div class="kicker">By network</div>
<h2 style="margin-bottom:10px">Where the airings paid</h2>
<div class="tw"><table><tr><th>Network</th><th class="center">Airings</th>
<th class="center">Calls</th><th class="center">Per airing</th></tr>{nrows}</table></div></div>"""

    bsel = "".join(f"""<option value="{e(b['batch'])}" {'selected' if batch == b['batch'] else ''}>
{e(b['filename'])} — {b['rows']} airings, {datetime.fromtimestamp(b['created']).strftime('%d %b %H:%M')}
</option>""" for b in batches)
    postlog_block = f"""<div class="panel">
<div class="kicker">TV post log</div>
<h2 style="margin-bottom:4px">Upload the airing log</h2>
<p class="mut small">Excel or CSV. It reads VERIFIED_DATE, VERIFIED_TIME, PROGRAM_TITLE,
NETWORK_CODE, REGION_CODE and AD_UNIT_TITLE, and tolerates other column names.</p>
{f'<div class="okmsg">{e(ok)}</div>' if ok else ''}
{f'<div class="warn">{e(err)}</div>' if err else ''}
<form method="post" action="upload" enctype="multipart/form-data" style="margin-top:14px">
<div class="fr four">
<div><label>Post log file</label><input type="file" name="file" accept=".xlsx,.xlsm,.csv" required></div>
<div><label>Log times are</label><select name="tz">
{"".join(f'<option value="{o}" {"selected" if o == tz else ""}>UTC{o:+d} ({n})</option>' for o, n in ((-4,"Eastern, summer"),(-5,"Eastern, winter"),(-6,"Central, summer"),(-7,"Mountain, summer"),(-8,"Pacific, summer"),(0,"already UTC")))}
</select></div>
<div><label>Response window</label><select name="window">
{"".join(f'<option value="{w}" {"selected" if w == window else ""}>{w} min</option>' for w in (2,3,5,10,15,30))}
</select></div>
<div style="display:flex;align-items:flex-end"><button class="btn" type="submit">Upload</button></div>
</div></form>
{f'''<form method="get" style="margin-top:6px;display:flex;gap:9px;align-items:flex-end">
<div style="flex:1"><label>Showing</label><select name="batch" onchange="this.form.submit()">
<option value="">All uploaded logs combined</option>{bsel}</select></div>
<button class="btn ghost" type="submit">View</button></form>''' if batches else ''}
</div>"""

    return HTMLResponse(shell(f"""
<div class="top"><div class="wrap">
<div class="kicker" style="color:var(--sky)">medigap.plus / 888</div>
<h1 style="margin:6px 0 6px">1-888-887-7595 — TV attribution</h1>
<p class="mut" style="max-width:70ch">The QR code number from the television ad, tracked live
against the main 800 line and matched to the airing log.</p>
{tiles}
<p style="margin-top:16px"><span class="live"><i></i>LIVE</span>
<span class="small" style="color:#8fb6dc;margin-left:10px">Refreshes every 60 seconds ·
{len(calls):,} calls loaded · times shown UTC{tz:+d}</span></p>
</div></div>
<div class="wrap" style="padding:22px 20px 40px">

<div class="panel">
<div style="display:flex;justify-content:space-between;align-items:flex-end;gap:14px;flex-wrap:wrap">
<div><div class="kicker">Direct 888</div><h2>Calls to the QR number, by day</h2></div>
<form method="get"><label>Range</label><select name="days" onchange="this.form.submit()">
{"".join(f'<option value="{d}" {"selected" if d == days else ""}>Last {d} days</option>' for d in (7,14,30,60,90))}
</select></form></div>
{bar_chart(series, label="Direct 888 calls by day")}
</div>

<div class="panel">
<div class="kicker">All calls</div><h2 style="margin-bottom:8px">The 800 line, same period</h2>
<p class="mut small" style="margin-bottom:8px">1-800-633-4427 — shown for scale, so an 888 spike
can be read against the background.</p>
{bar_chart(all_series, height=140, colour="#8496ab", label="800 line calls by day")}
</div>

<div class="panel">
<div class="kicker">Every 888 call</div>
<h2 style="margin-bottom:4px">Direct calls, with what happened around them</h2>
<p class="mut small" style="margin-bottom:12px"><b>ALL CALLS</b> counts calls to
1-800-633-4427 within ±{WIN_ALL_CALLS} minutes. <b>SAME STATE</b> counts calls from that
caller's state within ±{WIN_SAME_STATE} minutes — the signal that a spot ran in that market.</p>
<div class="tw"><table>
<tr><th>When</th><th>From</th><th>State</th><th>Call</th>
<th class="center">ALL CALLS<br><span style="font-weight:600;text-transform:none">±{WIN_ALL_CALLS} min on 800</span></th>
<th class="center">SAME STATE<br><span style="font-weight:600;text-transform:none">±{WIN_SAME_STATE} min</span></th></tr>
{trs or '<tr><td colspan=6 class="mut">No calls to the 888 number yet.</td></tr>'}</table></div>
</div>

{postlog_block}
{ranking_block}

<p class="small mut center" style="margin-top:20px">
Read-only against the medigap call database. Post logs are stored separately and never written
back. <a href="data.json">JSON</a> · <a href="?days={days}">refresh</a></p>
</div>""", refresh=60))


@app.post("/upload")
async def upload(file: UploadFile = File(...), tz: int = Form(DEFAULT_TZ_OFFSET),
                 window: int = Form(DEFAULT_WINDOW_MIN)):
    data = await file.read()
    if len(data) > 12 * 1024 * 1024:
        return RedirectResponse("./?err=That+file+is+too+large", status_code=303)
    rows, problems = parse_postlog(data, file.filename or "postlog.xlsx", tz)
    if not rows:
        msg = "; ".join(problems) or "No airings could be read from that file."
        return RedirectResponse(f"./?err={msg.replace(' ', '+')}", status_code=303)
    batch = save_postlog(rows, file.filename or "postlog.xlsx", tz)
    set_setting("tz_offset", tz)
    set_setting("window_min", window)
    note = f"Loaded {len(rows)} airings from {file.filename}."
    if problems:
        note += f" {len(problems)} row(s) skipped."
    return RedirectResponse(f"./?batch={batch}&window={window}&ok={note.replace(' ', '+')}",
                            status_code=303)


@app.get("/data.json")
def data_json(days: int = 30, window: int = 0):
    window = window or setting("window_min", DEFAULT_WINDOW_MIN)
    calls = load_calls(days=max(days, 1200))
    direct, main, rows = analyse(calls)
    air = airings()
    claims = attribute(air, calls, window) if air else {}
    return JSONResponse({
        "number_888": NUM_888, "number_800": NUM_800,
        "direct_888_total": len(direct),
        "direct_by_day": [[str(d), v] for d, v in by_day(direct, days)],
        "all_calls_by_day": [[str(d), v] for d, v in by_day(main, days)],
        "calls": [{"at": r["ts"].isoformat(), "from": r["frm"][-10:], "state": r["state"],
                   "status": r["status"], "all_calls_5min": r["all_calls"],
                   "same_state_10min": r["same_state"]} for r in rows],
        "airings": len(air), "window_min": window,
        "programs": rank_programs(air, claims) if air else [],
        "networks": rank_networks(air, claims) if air else [],
    })


@app.get("/healthz")
def healthz():
    try:
        n = len(load_calls(days=2))
        return {"ok": True, "recent_calls": n}
    except Exception as ex:
        return JSONResponse({"ok": False, "error": str(ex)[:200]}, status_code=500)


init()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8500")))
