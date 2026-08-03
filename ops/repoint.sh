#!/bin/bash
# Repoint a domain's @ A record to the network IP.
# GoDaddy quirks learned the hard way:
#   - PUT /records/A body must NOT contain a "type" field  -> 422 INVALID_BODY
#   - Sending @ and www together 422s when a www CNAME exists -> send @ only
#   - Cloudflare-hosted domains ignore GoDaddy changes entirely -> check NS first
NEW_IP="${NEW_IP:-207.148.0.22}"
NEVER="attorney.plus r0cketship.com jeff-cline.com medigap.plus medigap.ai"
acct=$1; d=$2
for p in $NEVER; do [ "$d" = "$p" ] && { echo "BLOCKED (protected): $d"; exit 1; }; done
case "$(dig +short "$d" NS | head -1)" in
  *cloudflare*) echo "SKIP $d — Cloudflare DNS, GoDaddy change has no effect"; exit 1;;
esac
TOK=$(sed -n "${acct}p" ~/.godaddy_keys)
curl -s -o /dev/null -w "%{http_code}\n" -X PUT \
  -H "Authorization: Bearer $TOK" -H "content-type: application/json" \
  -d "[{\"name\":\"@\",\"data\":\"$NEW_IP\",\"ttl\":600}]" \
  "https://api.godaddy.com/v1/domains/$d/records/A"
