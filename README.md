# SiteReport Bot

Turns a voice note or a typed update sent over WhatsApp (and, shortly, Telegram)
into a formatted Daily Progress Report — as a Word document or a PDF — and sends
it straight back in the chat.

Comes with a web portal for tracking who messaged, browsing their conversation
history and downloading every report they generated, with three access levels.

Built on FastAPI. The portal is server-rendered by the same service, so there is
one thing to deploy. Speech-to-text and report structuring are configured
independently and can use any OpenAI-compatible provider, free or paid.

---

## Quick start (Windows)

```
setup.bat      once — creates the venv, installs everything, writes .env
start.bat      start the server
stop.bat       stop it
```

`setup.bat` tells you which credentials still need filling in. Edit `.env`,
then `start.bat`.

| Command | What it does |
|---|---|
| `start.bat` | Starts in the background and opens the portal |
| `start.bat 9000` | …on a different port |
| `start.bat quiet` | Starts without opening the browser |
| `start.bat console` | Runs in the current window, Ctrl+C to stop |
| `stop.bat` | Stops the background server |
| `stop.bat 8000` | Also frees anything else holding that port |

`setup.bat` is safe to re-run — it never overwrites configuration you have
already set, and it repairs a `.env` that predates a newer setting.

`start.bat` waits for the server to actually answer before reporting success,
and prints the error log if it does not. Background logs go to
`storage\logs\app.log` and `storage\logs\app.err.log`.

Open **http://127.0.0.1:8000** and sign in with the administrator account
`setup.bat` asked you to create. `/health` confirms the service is up, and
`/docs` has the interactive API reference (development only).

Requires Python 3.11–3.13; `setup.bat` finds a supported one and tells you if
there isn't one. 3.14 does not yet have a prebuilt `pydantic-core` wheel.

> Type `start.bat`, not `start` — `start` is a built-in Windows command.
> Double-clicking the file works too.

### Try it without WhatsApp

```powershell
python scripts/cli_test.py --text "Set up the Docker container and fixed two payment bugs."
python scripts/cli_test.py --audio "path\to\voice_note.m4a" --format both
```

---

## The portal

Full guide: [`docs/portal.md`](docs/portal.md).

| Page | What it shows |
|---|---|
| Dashboard | Volume, delivery rate, failures, a 7-day chart, live conversations, system status |
| Contacts | Everyone who has messaged, searchable, with live workflow state |
| Contact detail | The whole conversation plus every report that number generated |
| Reports | All documents, filterable, downloadable |
| Settings | Channel credentials, AI provider and model, retention — administrators only |
| Logins | Create and manage accounts — administrators only |

Three roles:

- **Administrator** — everything, including settings and logins.
- **Viewer** — sees every contact and report, changes nothing.
- **User** — tied to one WhatsApp number, sees only the reports generated from
  that number's voice notes. Create these only when someone should see just
  their own work.

The user restriction is applied inside the SQL query, so guessing another
report's URL returns 403 rather than the document.

## Configuration

Everything lives in `.env` — see [`.env.example`](.env.example), which matches
the field list in [`app/core/config.py`](app/core/config.py).

Configuration resolves in three layers: values saved from the Settings page,
then the environment, then defaults. A credential or model changed in the UI
takes effect immediately, with no restart, and survives one.

### Choosing AI models

Chat (structuring) and speech-to-text are separate settings.

| Goal | Chat | Speech-to-text |
|---|---|---|
| Best quality | `openai` / `gpt-4o-mini` | `openai` / `whisper-1` |
| Free | `groq` / `llama-3.3-70b-versatile` | `groq` / `whisper-large-v3` |
| Fully local, no key | `ollama` / `llama3.1` | `faster-whisper` / `small` |
| Everything via one key | `openrouter` / `…:free` | — |

`app/ai/registry.py` holds the full provider list. Model dropdowns are populated
live from each provider's `/models` endpoint, so a newly released model is
selectable without a code change.

---

## Deployment

A DigitalOcean Ubuntu Droplet, running under systemd. No Docker. Full guide:
[`docs/deployment-digitalocean.md`](docs/deployment-digitalocean.md).

```bash
git clone https://github.com/your-org/Whatsapp-Reporting-Bot.git /opt/reportbot
cd /opt/reportbot
sudo bash deploy/install.sh                              # packages, db, service
sudo nano .env                                           # credentials
sudo bash deploy/setup-tls.sh reports.yourdomain.com     # HTTPS via Caddy
sudo systemctl start reportbot
```

| | |
|---|---|
| `sudo systemctl {start,stop,restart,status} reportbot` | control the service |
| `sudo journalctl -u reportbot -f` | live logs |
| `sudo bash deploy/update.sh` | pull, restart, roll back if unhealthy |

Webhook URLs are `{BASE_URL}/webhook/whatsapp` and `{BASE_URL}/webhook/telegram`.
The legacy bare `/webhook` path still works.

DigitalOcean App Platform is not usable here: its Python buildpack cannot
install `ffmpeg`, LibreOffice or the Unicode fonts this app needs, and those
features fail silently rather than loudly.

---

## Layout

```
app/
  ai/            provider registry, transcription, report structuring
  api/           webhook routes and dependencies
  auth/          session cookies, roles, per-user scoping
  clients/       Meta Graph API client
  core/          config, logging, security, lifespan
  db/            SQLAlchemy engine and models
  repositories/  all database access
  reports/       DOCX and PDF generation, font resolution
  services/      webhook parsing, event dispatch, workflow state machine, history recording
  sessions/      in-flight conversation state
  templates/     outbound WhatsApp message copy
  web/           the portal — routes, Jinja templates, CSS and JS
deploy/          Droplet install, TLS, update scripts, systemd unit
docs/            deployment and portal guides
scripts/         CLI tester, admin creation
storage/         report template, generated reports, media, fonts, database
```

---

## Status

Working: the WhatsApp bot end to end, the portal with all three roles, message
and report history with automatic 7-day retention, and a settings page that
reconfigures channels and AI models without a redeploy.

Not yet built: the **Telegram channel**. Its credentials, settings UI and
webhook URL are in place, but no adapter processes updates, so enabling it does
nothing today.
