#!/bin/bash
# Build everything in the Q, publish a vhost for each new site, then repoint DNS
# so the site actually serves at its own domain. Runs on a timer so the operator
# can keep entering details uninterrupted.
set -u
APP=/opt/network-app
PY=$APP/venv/bin/python
SITES=/var/www/sites
LOG=/var/log/network-build.log

exec >>"$LOG" 2>&1
echo "=== $(date -Is) build run ==="

# Promote anything the operator has finished into the Q automatically. The
# manual gate meant completed entries sat in Ready indefinitely, unbuilt.
PROMOTED=$($PY - <<'PYEOF'
import sqlite3
c = sqlite3.connect("/opt/network-app/network.db")
n = c.execute("UPDATE build_queue SET state='queued' WHERE state='ready'").rowcount
c.commit()
print(n)
PYEOF
)
[ "${PROMOTED:-0}" -gt 0 ] && echo "  promoted $PROMOTED ready -> Q"

$PY $APP/gen_sites.py $APP/network.db $SITES || exit 1

NEW=0
for dir in "$SITES"/*/; do
  d=$(basename "$dir")
  [ -f "/etc/nginx/sites-available/site-$d" ] && continue
  cat > "/etc/nginx/sites-available/site-$d" <<CONF
server {
    listen 80;
    listen [::]:80;
    server_name $d www.$d;
    root $SITES/$d;
    index index.html;
    location / { try_files \$uri \$uri/ =404; }
    gzip on;
    gzip_types text/html text/css application/javascript application/xml image/svg+xml;
}
CONF
  ln -sf "/etc/nginx/sites-available/site-$d" /etc/nginx/sites-enabled/
  echo "  vhost created: $d"
  NEW=$((NEW+1))
done

if [ "$NEW" -gt 0 ]; then
  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx && echo "  nginx reloaded ($NEW new vhosts)"
  else
    echo "  !! nginx config test FAILED - not reloading"; nginx -t
  fi
fi

echo "--- DNS repoint for built sites ---"
$PY $APP/repoint_built.py

echo "--- health check ---"
$PY $APP/check_sites.py

echo "done"
