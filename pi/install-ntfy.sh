#!/usr/bin/env bash
# Install or update ntfy on the Pi (armv7) and set it up for Mission Control. Run ON the Pi:
#   sudo NTFY_BASE_URL=https://<your ntfy hostname> bash install-ntfy.sh
# Re-running updates the package and keeps users, tokens and the config.
#   - listens on :2586, deny-all by default, no Firebase, no message cache needed beyond 12 h
#   - user mc-pi  : write to up* and mc-alerts   (token goes into mc-pi.env)
#   - user phone  : read-write up*, read mc-alerts (token goes into the ntfy app on the phone)
set -euo pipefail
VER="${NTFY_VERSION:-2.37.2}"
BASE_URL="${NTFY_BASE_URL:?set NTFY_BASE_URL, e.g. https://ntfy.example.com}"
MC_ENV=/home/filip/mission-control/mc-pi.env
OUT=/home/filip/mission-control/secrets
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

if ! dpkg -s ntfy 2>/dev/null | grep -q "^Version: $VER"; then
  echo "== install ntfy $VER (armv7 .deb from GitHub)"
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/ntfy.deb" "https://github.com/binwiederhier/ntfy/releases/download/v$VER/ntfy_${VER}_linux_armv7.deb"
  dpkg -i "$tmp/ntfy.deb"
  rm -rf "$tmp"
fi

mkdir -p /var/lib/ntfy /var/cache/ntfy
cat > /etc/ntfy/server.yml <<EOF
# Written by mission-control/pi/install-ntfy.sh
base-url: "$BASE_URL"
listen-http: ":2586"
behind-proxy: true
cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "12h"
auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"
enable-signup: false
enable-login: true
web-root: "disable"
EOF
chown -R ntfy:ntfy /var/lib/ntfy /var/cache/ntfy
systemctl enable -q ntfy
systemctl restart ntfy
sleep 2

as_ntfy() { sudo -u ntfy ntfy "$@"; }
user_exists() { as_ntfy user list 2>/dev/null | grep -q "^user $1 "; }
for u in mc-pi phone; do
  # Random password nobody uses: the phone and mc-pi log in with tokens.
  user_exists "$u" || sudo -u ntfy env NTFY_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')" \
    ntfy user add "$u" >/dev/null
done
as_ntfy access mc-pi 'up*' write-only >/dev/null
as_ntfy access mc-pi mc-alerts write-only >/dev/null
as_ntfy access phone 'up*' read-write >/dev/null
as_ntfy access phone mc-alerts read-only >/dev/null

mkdir -p "$OUT"; chown filip:filip "$OUT"; chmod 700 "$OUT"
if ! grep -q '^NTFY_TOKEN=tk_' "$MC_ENV" 2>/dev/null; then
  tok=$(as_ntfy token add --label=mc-pi mc-pi | grep -o 'tk_[A-Za-z0-9]*' | head -1)
  sed -i '/^NTFY_TOKEN=/d' "$MC_ENV"; echo "NTFY_TOKEN=$tok" >> "$MC_ENV"
  chown filip:filip "$MC_ENV"; chmod 600 "$MC_ENV"
  echo "== mc-pi token written to $MC_ENV"
fi
if [ ! -s "$OUT/ntfy-phone-token.txt" ]; then
  as_ntfy token add --label=phone phone | grep -o 'tk_[A-Za-z0-9]*' | head -1 > "$OUT/ntfy-phone-token.txt"
  chown filip:filip "$OUT/ntfy-phone-token.txt"; chmod 600 "$OUT/ntfy-phone-token.txt"
  echo "== phone token saved to $OUT/ntfy-phone-token.txt (put it in the ntfy app, then delete the file)"
fi
systemctl is-active ntfy
curl -fsS http://127.0.0.1:2586/v1/health; echo
