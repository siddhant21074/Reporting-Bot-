#!/usr/bin/env bash
# ===========================================================================
#  SiteReport Bot - install on a fresh Ubuntu 24.04 DigitalOcean Droplet.
#  No Docker.
#
#  Run as root:
#      curl -fsSL https://raw.githubusercontent.com/YOUR-ORG/REPO/main/deploy/install.sh | bash
#  or, if you already cloned the repo:
#      sudo bash deploy/install.sh
#
#  Safe to re-run: every step checks before it acts.
# ===========================================================================

set -euo pipefail

APP_USER="reportbot"
APP_DIR="/opt/reportbot"
DB_NAME="reportbot"
DB_USER="reportbot"
REPO_URL="${REPO_URL:-https://github.com/your-org/Whatsapp-Reporting-Bot.git}"
BRANCH="${BRANCH:-main}"

RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BOLD=$'\e[1m'; OFF=$'\e[0m'
step()  { echo -e "\n${BOLD}==> $*${OFF}"; }
ok()    { echo -e "    ${GREEN}ok${OFF}  $*"; }
warn()  { echo -e "    ${YELLOW}!${OFF}   $*"; }
die()   { echo -e "\n${RED}error:${OFF} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this as root:  sudo bash deploy/install.sh"

# ---------------------------------------------------------------------------
step "Installing system packages"
# ---------------------------------------------------------------------------
# Why each of these matters:
#   ffmpeg              decodes WhatsApp OGG/Opus voice notes. Without it,
#                       transcription silently returns nothing.
#   libreoffice-writer  converts the populated .docx to a PDF that matches the
#                       Word template. Without it a close-but-not-identical
#                       renderer is used instead.
#   fonts-dejavu/noto   Unicode coverage in PDFs. Without them, Hindi, Marathi
#                       and the rupee sign are transliterated away.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-dev \
    build-essential libpq-dev \
    ffmpeg libsndfile1 \
    fonts-dejavu-core fonts-noto-core fonts-noto-ui-core \
    libreoffice-writer libreoffice-core \
    postgresql postgresql-contrib \
    git curl ca-certificates ufw
fc-cache -f >/dev/null 2>&1 || true
ok "python $(python3 --version 2>&1 | cut -d' ' -f2), ffmpeg, libreoffice, postgres"

# ---------------------------------------------------------------------------
step "Creating the service account"
# ---------------------------------------------------------------------------
if id "$APP_USER" &>/dev/null; then
    ok "user '$APP_USER' already exists"
else
    useradd --system --create-home --home-dir "/home/$APP_USER" --shell /usr/sbin/nologin "$APP_USER"
    ok "created user '$APP_USER'"
fi

# ---------------------------------------------------------------------------
step "Fetching the application"
# ---------------------------------------------------------------------------
if [[ -d "$APP_DIR/.git" ]]; then
    git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
    git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
    ok "updated $APP_DIR to origin/$BRANCH"
elif [[ -f "$(dirname "$0")/../app/main.py" ]]; then
    SRC="$(cd "$(dirname "$0")/.." && pwd)"
    if [[ "$SRC" != "$APP_DIR" ]]; then
        mkdir -p "$APP_DIR"
        cp -a "$SRC/." "$APP_DIR/"
        ok "copied from $SRC"
    else
        ok "already running from $APP_DIR"
    fi
else
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    ok "cloned $REPO_URL"
fi

mkdir -p "$APP_DIR"/storage/{logs,media,reports,temp,fonts,run}

# ---------------------------------------------------------------------------
step "Building the Python environment"
# ---------------------------------------------------------------------------
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "dependencies installed"

# ---------------------------------------------------------------------------
step "Setting up PostgreSQL"
# ---------------------------------------------------------------------------
systemctl enable --now postgresql >/dev/null 2>&1 || true

if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    ok "database role '$DB_USER' already exists"
    DB_PASS=""
else
    DB_PASS="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
    sudo -u postgres psql -qc "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"
    ok "created database role '$DB_USER'"
fi

if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
    ok "database '$DB_NAME' already exists"
else
    sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
    ok "created database '$DB_NAME'"
fi

# ---------------------------------------------------------------------------
step "Writing configuration"
# ---------------------------------------------------------------------------
if [[ -f "$APP_DIR/.env" ]]; then
    ok ".env already exists, leaving it untouched"
else
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    SECRET_KEY="$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=' | head -c 48)"

    sed -i "s|^ENVIRONMENT=.*|ENVIRONMENT=\"production\"|"  "$APP_DIR/.env"
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=\"$SECRET_KEY\"|"   "$APP_DIR/.env"
    if [[ -n "$DB_PASS" ]]; then
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=\"postgresql+asyncpg://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME\"|" "$APP_DIR/.env"
    fi
    ok "created .env with a generated SECRET_KEY and database URL"
    warn "you still need to fill in the WhatsApp and AI credentials"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

# ---------------------------------------------------------------------------
step "Installing the systemd service"
# ---------------------------------------------------------------------------
cp "$APP_DIR/deploy/reportbot.service" /etc/systemd/system/reportbot.service
systemctl daemon-reload
systemctl enable reportbot >/dev/null
ok "service 'reportbot' installed and enabled at boot"

# ---------------------------------------------------------------------------
step "Firewall"
# ---------------------------------------------------------------------------
ufw allow OpenSSH >/dev/null 2>&1 || true
ufw allow 80/tcp   >/dev/null 2>&1 || true
ufw allow 443/tcp  >/dev/null 2>&1 || true
yes | ufw enable   >/dev/null 2>&1 || true
ok "SSH, 80 and 443 open; everything else closed"
# The app binds to 127.0.0.1 only, so it is not reachable except through Caddy.

# ---------------------------------------------------------------------------
echo
echo "============================================================"
echo " Installed."
echo "============================================================"
cat <<EOF

Next, in order:

  1. Fill in your credentials
       sudo nano $APP_DIR/.env

     At minimum: WHATSAPP_ACCESS_TOKEN, WHATSAPP_APP_SECRET,
     WHATSAPP_VERIFY_TOKEN, WHATSAPP_PHONE_NUMBER_ID, LLM_API_KEY.
     Set BASE_URL to your public https:// address.

  2. Create the dashboard login
       cd $APP_DIR && sudo -u $APP_USER .venv/bin/python scripts/make_admin.py --create
     This is the administrator account you sign in to the portal with.

  3. Start it
       sudo systemctl start reportbot
       sudo systemctl status reportbot
       curl http://127.0.0.1:8000/health

  4. Add HTTPS (Meta and Telegram both refuse plain HTTP webhooks)
       sudo bash $APP_DIR/deploy/setup-tls.sh reports.yourdomain.com

  5. Register the webhook in the Meta dashboard
       https://reports.yourdomain.com/webhook/whatsapp

Logs:    sudo journalctl -u reportbot -f
Update:  sudo bash $APP_DIR/deploy/update.sh

EOF
