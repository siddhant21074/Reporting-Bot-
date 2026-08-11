#!/usr/bin/env bash
# ===========================================================================
#  Pull the latest code and restart the service.
#
#      sudo bash /opt/reportbot/deploy/update.sh
#
#  .env is never touched. If the service fails to come back up, this rolls
#  back to the previous commit rather than leaving you with a dead bot.
# ===========================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/reportbot}"
APP_USER="${APP_USER:-reportbot}"
BRANCH="${BRANCH:-main}"

RED=$'\e[31m'; GREEN=$'\e[32m'; BOLD=$'\e[1m'; OFF=$'\e[0m'
step() { echo -e "\n${BOLD}==> $*${OFF}"; }
die()  { echo -e "\n${RED}error:${OFF} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root:  sudo bash $APP_DIR/deploy/update.sh"
[[ -d "$APP_DIR/.git" ]] || die "$APP_DIR is not a git checkout; update it by hand."

PREVIOUS="$(git -C "$APP_DIR" rev-parse HEAD)"
echo "Current commit: ${PREVIOUS:0:8}"

step "Fetching origin/$BRANCH"
git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
TARGET="$(git -C "$APP_DIR" rev-parse "origin/$BRANCH")"

if [[ "$PREVIOUS" == "$TARGET" ]]; then
    echo "    Already up to date."
    exit 0
fi

git -C "$APP_DIR" reset --hard --quiet "$TARGET"
echo "    Now at ${TARGET:0:8}"

step "Updating dependencies"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

step "Refreshing the systemd unit"
cp "$APP_DIR/deploy/reportbot.service" /etc/systemd/system/reportbot.service
systemctl daemon-reload

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

step "Restarting"
systemctl restart reportbot
sleep 5

if curl -fsS --max-time 15 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo -e "    ${GREEN}ok${OFF}  service is healthy at ${TARGET:0:8}"
    exit 0
fi

echo -e "\n${RED}The service did not come back up. Rolling back to ${PREVIOUS:0:8}.${OFF}\n"
journalctl -u reportbot -n 30 --no-pager || true

git -C "$APP_DIR" reset --hard --quiet "$PREVIOUS"
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
systemctl restart reportbot
sleep 5

if curl -fsS --max-time 15 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    die "Rolled back to ${PREVIOUS:0:8}, which is healthy. The new commit needs a fix."
fi
die "Rollback did not restore health either. Investigate with: journalctl -u reportbot -n 100"
