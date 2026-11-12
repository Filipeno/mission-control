#!/usr/bin/env bash
# Deploy mc-pi to the Pi. Run from the PC (Git Bash) in this folder:  ./deploy.sh
# Safe to re-run (also after reinstalling the Pi). Needs `ssh pi` to work and sudo on the Pi.
# It never touches pc-waker; it only reads pc-waker.env on the Pi at run time.
set -euo pipefail
HOST="${MC_PI_HOST:-pi}"
DEST=/home/filip/mission-control
cd "$(dirname "$0")"

echo "== copy files to $HOST:$DEST"
tar -cf - mcpi.py claude_hub.py sessions_hub.py docs_hub.py system_hub.py p256.py requirements.txt mission-control.service mc-pi.env.example \
  | ssh "$HOST" "mkdir -p $DEST && tar -xf - -C $DEST"

echo "== venv + packages, env file, systemd unit"
ssh "$HOST" bash -s <<EOF
set -euo pipefail
cd $DEST
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q --only-binary=:all: -r requirements.txt
.venv/bin/python mcpi.py setup
sudo install -m 644 mission-control.service /etc/systemd/system/mission-control.service
sudo systemctl daemon-reload
sudo systemctl enable -q mission-control
sudo systemctl restart mission-control
for i in \$(seq 1 20); do
  curl -fsS http://127.0.0.1:8780/api/health && echo && break
  sleep 1
done
systemctl is-active mission-control
EOF
