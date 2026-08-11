# Deploying to DigitalOcean

No Docker. A plain Ubuntu Droplet running the app under systemd, with Caddy in
front for HTTPS and PostgreSQL on the same box.

> **App Platform is not an option without Docker.** Its Python buildpack gives
> you no way to install system packages, and this app needs three of them:
> `ffmpeg` (voice notes), `libreoffice-writer` (template-accurate PDFs) and the
> Noto/DejaVu fonts (non-Latin text in PDFs). On a buildpack those features
> fail silently rather than loudly. Use a Droplet.

---

## Droplet sizing

| | Minimum | Comfortable |
|---|---|---|
| RAM | 2 GB | 4 GB |
| Disk | 50 GB | 50 GB |
| Cost | ~$12/mo | ~$24/mo |

2 GB is the floor because LibreOffice needs room to convert. Go to 4 GB if you
plan to run local models (`ollama` or `faster-whisper`).

Region `BLR1` (Bangalore) if your users are in India. Ubuntu 24.04 LTS.

---

## Install

SSH in and run one script:

```bash
ssh root@YOUR_DROPLET_IP

git clone https://github.com/your-org/Whatsapp-Reporting-Bot.git /opt/reportbot
cd /opt/reportbot
sudo bash deploy/install.sh
```

It installs the system packages, creates an unprivileged `reportbot` user,
builds the virtualenv, creates the PostgreSQL database with a generated
password, writes a `.env` with a generated `SECRET_KEY`, installs the systemd
unit and closes the firewall down to SSH, 80 and 443.

It is safe to re-run — every step checks before acting.

### Then finish the configuration

```bash
sudo nano /opt/reportbot/.env
```

Fill in at minimum:

```ini
BASE_URL="https://reports.yourdomain.com"

WHATSAPP_ACCESS_TOKEN="..."
WHATSAPP_APP_SECRET="..."
WHATSAPP_VERIFY_TOKEN="<any string you choose>"
WHATSAPP_PHONE_NUMBER_ID="..."

LLM_PROVIDER="openai"
LLM_MODEL="gpt-4o-mini"
LLM_API_KEY="sk-..."
```

`ENVIRONMENT="production"` is set for you, and it is load-bearing: it makes
`SECRET_KEY` and `WHATSAPP_APP_SECRET` mandatory and stops the app processing
unsigned webhooks.

Create the dashboard login and paste the output into `.env`:

```bash
cd /opt/reportbot
sudo -u reportbot .venv/bin/python scripts/make_admin.py
```

### Start it

```bash
sudo systemctl start reportbot
sudo systemctl status reportbot
curl http://127.0.0.1:8000/health
```

### Add HTTPS

Point an A record at the Droplet's IP first, then:

```bash
sudo bash /opt/reportbot/deploy/setup-tls.sh reports.yourdomain.com
```

Caddy obtains and renews the certificate itself — no cron job to remember. The
script refuses to run if DNS does not yet point at this Droplet, which is the
usual cause of a failed certificate request.

---

## Day-to-day

```bash
sudo systemctl start reportbot        # start
sudo systemctl stop reportbot         # stop
sudo systemctl restart reportbot      # restart, e.g. after editing .env
sudo systemctl status reportbot       # is it running
sudo journalctl -u reportbot -f       # live logs
sudo journalctl -u reportbot -n 200   # last 200 lines
```

The service starts on boot and restarts on crash.

### Updating

```bash
sudo bash /opt/reportbot/deploy/update.sh
```

Pulls `main`, reinstalls dependencies, restarts, and health-checks. If the new
commit does not come up, it rolls back to the previous one rather than leaving
you with a dead bot. `.env` is never touched.

---

## Connecting the channels

Both URLs are built from `BASE_URL`.

### WhatsApp (Meta Cloud API)

1. Meta App Dashboard → WhatsApp → Configuration → Edit webhook.
2. Callback URL: `https://reports.yourdomain.com/webhook/whatsapp`
3. Verify token: exactly the value of `WHATSAPP_VERIFY_TOKEN`.
4. Subscribe to the `messages` field.

Meta immediately sends a `GET` carrying a challenge. A `200` echoing the
challenge means it worked; a `403` means the token does not match.

The legacy bare `/webhook` path still works, so an existing subscription keeps
running without reconfiguration.

### Telegram

Set `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN` (from @BotFather) and
`TELEGRAM_WEBHOOK_SECRET` (any string) in `.env`, restart, then register once:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://reports.yourdomain.com/webhook/telegram" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

---

## Choosing the AI models

Chat and speech-to-text are configured separately, and both can be changed from
the admin Settings page without a redeploy. Full provider list:
[`app/ai/registry.py`](../app/ai/registry.py).

**Paid, best quality**

```ini
LLM_PROVIDER="openai"   LLM_MODEL="gpt-4o-mini"   LLM_API_KEY="sk-..."
STT_PROVIDER="openai"   STT_MODEL="whisper-1"
```

**Free**

```ini
LLM_PROVIDER="groq"   LLM_MODEL="llama-3.3-70b-versatile"   LLM_API_KEY="gsk_..."
STT_PROVIDER="groq"   STT_MODEL="whisper-large-v3"
```

**Free and fully local** — no key, no per-request cost, needs a 4 GB Droplet:

```ini
LLM_PROVIDER="ollama"           LLM_MODEL="llama3.1"
STT_PROVIDER="faster-whisper"   STT_MODEL="small"
```

Uncomment `faster-whisper` in `requirements.txt` for the local STT option, and
install Ollama separately with `curl -fsSL https://ollama.com/install.sh | sh`.

**Anything through one key** — OpenRouter reaches Claude, Gemini, Llama,
Mistral, DeepSeek and Qwen; models ending in `:free` cost nothing:

```ini
LLM_PROVIDER="openrouter"   LLM_MODEL="meta-llama/llama-3.3-70b-instruct:free"
```

---

## What gets installed, and why

| Package | Without it |
|---|---|
| `ffmpeg` | WhatsApp OGG/Opus voice notes cannot be decoded — transcription silently returns nothing |
| `libreoffice-writer` | PDFs come from the native renderer rather than the Word template, so they do not match it exactly |
| `fonts-dejavu-core`, `fonts-noto-core` | Hindi, Marathi and the rupee sign are transliterated out of PDFs |
| `libsndfile1` | `soundfile`, the ffmpeg fallback, cannot load audio |
| `postgresql` | No message or report history |

---

## Security notes

- The app binds to `127.0.0.1` only. Nothing reaches it except through Caddy.
- PostgreSQL listens on localhost with a generated password.
- The service runs as an unprivileged user with `ProtectSystem=strict`; the only
  writable path is `/opt/reportbot/storage`.
- `.env` is `chmod 600`, owned by `reportbot`.
- `ufw` allows SSH, 80 and 443 only.

Consider also: disabling SSH password auth, and adding a DigitalOcean Cloud
Firewall in front of `ufw`.

---

## Troubleshooting

**Service will not start**

```bash
sudo journalctl -u reportbot -n 50 --no-pager
```

A `ConfigurationError` naming a variable means `.env` is incomplete — the app
refuses to start in production without `SECRET_KEY` and `WHATSAPP_APP_SECRET`.

**Meta webhook verification fails**

`WHATSAPP_VERIFY_TOKEN` must match the Meta form exactly. The token is
deliberately never logged, so compare by hand.

**Voice notes produce empty reports**

```bash
ffmpeg -version                                   # must be installed
sudo journalctl -u reportbot | grep stt_failed    # provider errors
```

**PDFs are missing Hindi text**

```bash
fc-list | grep -i -E 'deva|noto'
sudo apt install -y fonts-noto-core && sudo systemctl restart reportbot
```

Startup logs name every channel and provider that is enabled but incomplete:

```bash
sudo journalctl -u reportbot | grep startup_configuration_warning
```
