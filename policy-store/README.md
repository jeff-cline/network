# Policy Store — fully autonomous insurance agency

Live at **https://policystore.com** (behind a demo password until switched off in
Admin → Demo gate). Runs on the Vultr box at 207.148.0.22, port 8400.

## Files
| File | What it is |
|---|---|
| `app.py` | The application — demo gate, conversational quoter, checkout, shortener, account, admin |
| `plans.py` | Product data transcribed from the carrier workbook: state availability, benefit amounts, tiers, age bands, Travel 365 rates, money words |
| `content.py` | Marketing and educational copy per product |
| `rates.json` | Rate table for AD&D / AME / CI. **Demo values** until the carrier sheet is loaded |
| `data/` | The two T365 tabs (they were images, not cells) and the Chubb availability PDF |
| `briefing.html`, `infographic.html` | The executive one-sheet and flow poster |

## What is real vs demo
- **Travel 365 rates are real** — transcribed from the carrier's pricing image.
- **AD&D / AME / CI rates are demo.** The workbook had benefit amounts, tiers and
  age bands but no premiums. Quotes built from them carry `rates_are_demo: true`
  on screen, in the record, and in the ping-post payload.
- Ping-post, SMS and the administrator are **simulated until configured** in
  Admin → Integrations. Simulated calls still log the exact payload.

## Deploy
    rsync -aq app.py plans.py content.py vultr:/opt/policystore/
    ssh vultr 'systemctl restart policystore'
