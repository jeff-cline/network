# medigap.plus/888 — TV attribution

Live at **https://medigap.plus/888/**

Tracks 1-888-887-7595, the QR-code number on the national TV ad, against the main
1-800-633-4427 line, and matches both to an uploaded TV post log.

Runs as its own service (`medigap888.service`, port 8500) behind an nginx
`location /888` block. It reads the medigap Postgres **read-only** and never
touches the live Next.js site.

| Column | What it means |
|---|---|
| DIRECT 888 | Calls to the QR number, charted by day |
| ALL CALLS | Calls to 1-800-633-4427 within ±5 min of that 888 call |
| SAME STATE | Calls from the caller's state within ±10 min either side |

Post logs upload as .xlsx or .csv. Column names are matched loosely, times are
converted from the log's timezone to UTC, and each call is attributed to the
nearest spot inside the response window — never counted twice.

    rsync -aq app.py r0cketship:/opt/medigap888/
    ssh r0cketship 'systemctl restart medigap888'
