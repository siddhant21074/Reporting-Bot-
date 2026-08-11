#!/usr/bin/env bash
# ===========================================================================
#  Put Caddy in front of the app so the webhooks are reachable over HTTPS.
#  Meta and Telegram both refuse plain HTTP webhook URLs.
#
#      sudo bash deploy/setup-tls.sh reports.yourdomain.com
#
#  Caddy obtains and renews the Let's Encrypt certificate on its own; there is
#  no cron job to remember.
#
#  Point an A record at this Droplet's IP BEFORE running this - the
#  certificate request fails if the domain does not resolve here yet.
# ===========================================================================

set -euo pipefail

DOMAIN="${1:-}"
APP_PORT="${2:-8000}"

RED=$'\e[31m'; GREEN=$'\e[32m'; BOLD=$'\e[1m'; OFF=$'\e[0m'
die() { echo -e "\n${RED}error:${OFF} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root:  sudo bash deploy/setup-tls.sh yourdomain.com"
[[ -n "$DOMAIN" ]] || die "Give the domain:  sudo bash deploy/setup-tls.sh reports.yourdomain.com"

echo -e "\n${BOLD}==> Checking DNS${OFF}"
RESOLVED="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)"
PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org || echo '')"

if [[ -z "$RESOLVED" ]]; then
    die "$DOMAIN does not resolve. Add an A record pointing at ${PUBLIC_IP:-this droplet} and wait for it to propagate."
fi
if [[ -n "$PUBLIC_IP" && "$RESOLVED" != "$PUBLIC_IP" ]]; then
    die "$DOMAIN resolves to $RESOLVED but this droplet is $PUBLIC_IP. Fix the A record first."
fi
echo "    ok  $DOMAIN -> $RESOLVED"

echo -e "\n${BOLD}==> Installing Caddy${OFF}"
if ! command -v caddy >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y -qq --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https curl gnupg
    curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    apt-get update -qq
    apt-get install -y -qq caddy
fi
echo "    ok  caddy $(caddy version | head -1)"

echo -e "\n${BOLD}==> Writing the Caddyfile${OFF}"
cat >/etc/caddy/Caddyfile <<EOF
$DOMAIN {
    reverse_proxy 127.0.0.1:$APP_PORT

    # Meta may send a large media webhook; keep the body limit generous.
    request_body {
        max_size 32MB
    }

    log {
        output file /var/log/caddy/access.log
        format json
    }
}
EOF
mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy

systemctl enable caddy >/dev/null 2>&1 || true
systemctl restart caddy
sleep 3

echo -e "\n${BOLD}==> Verifying${OFF}"
if curl -fsS --max-time 20 "https://$DOMAIN/health" >/dev/null 2>&1; then
    echo -e "    ${GREEN}ok${OFF}  https://$DOMAIN/health is answering"
else
    echo "    Certificate issuance can take up to a minute. Check with:"
    echo "      journalctl -u caddy -n 50 --no-pager"
    echo "      curl https://$DOMAIN/health"
fi

cat <<EOF

Set this in $PWD/.env, then restart the service:

    BASE_URL="https://$DOMAIN"

    sudo systemctl restart reportbot

Webhook URLs to register:
    WhatsApp   https://$DOMAIN/webhook/whatsapp
    Telegram   https://$DOMAIN/webhook/telegram

EOF
