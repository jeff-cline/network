#!/bin/bash
# Build everything sitting in the Q, then publish a vhost for each new site.
# Runs on a timer so the operator can keep entering details uninterrupted.
set -u
APP=/opt/network-app
PY=$APP/venv/bin/python
SITES=/var/www/sites
LOG=/var/log/network-build.log

exec >>"$LOG" 2>&1
echo "=== $(date -Is) build run ==="

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
echo "done"
