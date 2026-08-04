#!/bin/bash
# Cross-monitor. Runs on the OTHER server so that when the primary dies, there is
# still something alive to send the alert. A monitor on the box it watches cannot
# report that box being down - which is exactly how the last outage went unnoticed.
STATE=/var/lib/network-watchdog.state
LOG=/var/log/network-watchdog.log
WATCH_IP="${WATCH_IP:-207.148.0.22}"
WATCH_URL="${WATCH_URL:-https://network.r0cketship.com/healthz}"
CORE_KEY="${CORE_KEY:-}"
CORE_SECRET="${CORE_SECRET:-}"
NOTIFY="${NOTIFY_TO:-jeff.cline@me.com}"

up=0
if curl -sk --max-time 15 -o /dev/null "$WATCH_URL"; then up=1
elif nc -z -w 5 "$WATCH_IP" 443 2>/dev/null; then up=1; fi

prev=$(cat "$STATE" 2>/dev/null || echo "1")
if [ "$up" != "$prev" ]; then
  echo "$up" > "$STATE"
  ts=$(date -Is)
  echo "$ts state=$up" >> "$LOG"
  if [ "$up" = "0" ]; then
    subj="🔴 NETWORK server unreachable ($WATCH_IP)"
    body="<div style=\"font:14px -apple-system,sans-serif;padding:20px\"><h2 style=\"color:#cf484d\">NETWORK server is down</h2><p>$WATCH_IP stopped responding at $ts.</p><p>All network sites, the back office and lead capture are affected. Check the Vultr console for instance state and billing.</p></div>"
  else
    subj="🟢 NETWORK server recovered ($WATCH_IP)"
    body="<div style=\"font:14px -apple-system,sans-serif;padding:20px\"><h2 style=\"color:#2ea043\">NETWORK server is back</h2><p>$WATCH_IP responded again at $ts.</p></div>"
  fi
  for i in 1 2 3 4; do
    r=$(curl -sS --max-time 25 -X POST \
      -H "x-core-key: $CORE_KEY" -H "x-core-secret: $CORE_SECRET" \
      -H "content-type: application/json" \
      -d "$(python3 -c 'import json,sys;print(json.dumps({"to":sys.argv[1],"subject":sys.argv[2],"html":sys.argv[3]}))' "$NOTIFY" "$subj" "$body")" \
      https://medigap.plus/api/core/email)
    echo "$r" | grep -q '"ok":true' && { echo "  alert sent" >> "$LOG"; break; }
    sleep 2
  done
fi
