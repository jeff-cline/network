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
