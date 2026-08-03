#!/bin/bash
# Poll the A2 suspended account. Logs a line only when the state changes, so the
# log stays readable and the moment of unsuspension is obvious.
LOG=/var/log/a2-watch.log
STATE=/opt/network-app/.a2_state
PROBES="vrtcls.com briecline.com keywordcalls.com offtakers.org randomincome.com"

live=0; total=0
for d in $PROBES; do
  total=$((total+1))
  url=$(curl -sk -L --max-time 12 -o /dev/null -w "%{url_effective}" "https://$d/" 2>/dev/null)
  case "$url" in *suspendedpage*) ;; *) live=$((live+1));; esac
done

now="$live/$total"
prev=$(cat "$STATE" 2>/dev/null || echo "")
if [ "$now" != "$prev" ]; then
  echo "$(date -Is)  restored: $now  (was ${prev:-unknown})" >> "$LOG"
  echo "$now" > "$STATE"
fi
