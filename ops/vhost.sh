#!/bin/bash
# Create + enable an nginx vhost for a generated static site. Run on the server.
d=$1
cat > /etc/nginx/sites-available/site-$d <<CONF
server {
    listen 80;
    listen [::]:80;
    server_name $d www.$d;
    root /var/www/sites/$d;
    index index.html;
    location / { try_files \$uri \$uri/ =404; }
    gzip on;
    gzip_types text/html text/css application/javascript application/xml;
}
CONF
ln -sf /etc/nginx/sites-available/site-$d /etc/nginx/sites-enabled/
nginx -t >/dev/null 2>&1 && systemctl reload nginx && echo "vhost live: $d"
