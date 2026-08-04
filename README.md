# network

Domain network inventory + static site platform for the R0cketShip network.

Live: http://network.r0cketship.com  (server 207.148.0.22, Debian 13 + nginx)

## Layout
- `site/index.html` — generated inventory landing page (Network Sites / Need to Build)
- `crawl.py` — probes every domain: live? multi-page? title/description
- `gen_site.py` — renders crawl results into `site/index.html`
- `data-account1.json` — crawl results, GoDaddy account 1

## Regenerate
```
python3 crawl.py gd_domains.json data-account1.json
python3 gen_site.py data-account1.json site/index.html
scp site/index.html vultr:/var/www/network/index.html
```

## Notes
- GoDaddy API auth is `Authorization: Bearer <gd_pat_...>`; tokens live in `~/.godaddy_keys` (never committed)
- Token rotation deadline: 2027-07-29

## Back office
`app/app.py` — FastAPI, runs on the server at `/opt/network-app` under systemd
(`network-app.service`), proxied by nginx at https://network.r0cketship.com.

- Auth: single admin, scrypt-hashed password, forced change on first login
- Tabs: Live / Parked / Unreachable / Suspended / Broken
- Selection + select-all persisted in SQLite; live sites cannot be selected
- `/queue` shows the pending build list — no DNS or generation happens without approval

Deploy: `scp app/app.py vultr:/opt/network-app/app.py && ssh vultr systemctl restart network-app`

## CORE API
Base `https://medigap.plus`, headers `x-core-key` / `x-core-secret` (in the systemd unit, never committed).
Documented: `GET /api/core/ping`, `POST /api/core/lead`.
**Undocumented but live** (found via the ping scope list): `POST /api/core/email`
(`to`, `subject`, `html`|`text`) and `POST /api/core/sms`. Scopes granted:
`lead:create`, `lead:read`, `email:send`, `sms:send`. `lead:read` returns HTML, not JSON.

Static sites POST to `https://network.r0cketship.com/api/lead` — never directly to CORE,
because the secret cannot live in client-side HTML. The proxy forwards to CORE, sends the
notification email with the form name in the subject, and stores a local copy in `leads`.

## Cloudflare
Token in `~/.cloudflare` (mode 600), scope Zone:DNS:Edit on all zones.
`ops/cf_repoint.py` repoints zones to the network IP. It only touches a zone that is
BOTH in build_queue as 'built' AND currently serving nothing — zone membership alone is
not enough, since several Cloudflare zones are live sites.

Certbot validates www and IPv6 as well as the apex, so repointing must also delete
AAAA records and set a www A record, or validation fails against Cloudflare's IPv6.

## Uptime monitoring
`ops/monitor.py` (on NETWORK, systemd timer every 2 min) checks 5 servers by IP and 12
critical sites by hostname. Emails via CORE on STATE CHANGE only — one alert per outage,
plus a recovery notice. `/status` shows the live board.

`ops/watchdog.sh` (on R0cketShip, timer every 3 min) watches NETWORK from outside it.
A monitor on the box it watches cannot report that box being down — which is how the
2026-08-04 Vultr suspension went unnoticed. Both alert paths are tested end to end.

Known gap: both servers are on the same Vultr account, so an account-level suspension
silences both. An external check (or one on a machine outside Vultr) would close it.
