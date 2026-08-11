# The portal

A server-rendered dashboard on the same service as the webhook — no separate
frontend build, no CDN, no second deployment. Sign in at `/login`.

## Roles

| | Administrator | Viewer | User |
|---|---|---|---|
| Dashboard | all contacts | all contacts | own number only |
| Reports | all, download any | all, download any | own only |
| Contacts list | yes | yes | **no** |
| Contact detail | any | any | own number only |
| Settings | **yes** | no | no |
| Manage logins | **yes** | no | no |

**Create user accounts only when someone should see just their own reports.**
Anyone who needs the whole picture is a viewer. Most deployments need one
administrator and nothing else.

### How the user role is scoped

A `user` login is tied to one WhatsApp number — the number they send voice notes
from. The account then sees exactly the reports generated from those voice
notes, and nothing else.

The restriction is applied inside the SQL query, not in the template. A user who
guesses another report's URL gets a 403, not a document:

```
GET /reports/17/download   →  403  You can only download your own reports.
GET /contacts/9188888…     →  403  You can only view your own messages.
GET /contacts              →  403  Your account can only see its own reports.
```

### Creating a login

Settings → Logins, or straight from a contact: open the contact and click
**Create a login for this number** — the number is filled in for you.

The first administrator is created on the server, because there is no way to
sign in before one exists:

```bash
python scripts/make_admin.py --create
```

`setup.bat` does this for you on Windows.

**At the password prompt nothing appears as you type** — no characters, no
dots. That is the prompt hiding your input, not a frozen terminal. Type it and
press Enter.

If the prompt will not accept input at all, you are almost certainly in **Git
Bash**: Python's hidden-password prompt needs a real Windows console, and Git
Bash is a pipe, so the key presses never arrive. The script detects this and
switches to a visible prompt. To avoid it entirely, either run the command from
Command Prompt or PowerShell, or skip the prompt:

```bash
python scripts/make_admin.py --create --password "your password"
python scripts/make_admin.py --create --random      # generates and prints one
```

## Pages

**Dashboard** — reports today and over the retention window, contacts active,
delivery rate, failures, average build time. A 7-day bar chart of reports
(delivered vs failed), the conversations in progress right now, and a system
status panel covering both channels, both AI providers, ffmpeg, LibreOffice and
the PDF fonts.

**Contacts** — everyone who has messaged, searchable, with live workflow state.

**Contact detail** — the full conversation as a transcript, with voice-note
transcriptions inline, beside every report that number generated.

**Reports** — every document, filterable by status and searchable by reference
or project. Reports built without the AI model are tagged `No AI`, so a silent
degradation is visible rather than buried in the logs.

**Settings** (administrators) — WhatsApp and Telegram credentials, the chat and
speech-to-text provider and model, retention window, public URL. Changes apply
immediately; no restart. Every change is recorded in an audit trail shown at the
bottom of the page.

**Logins** (administrators) — create, disable and delete accounts.

## Settings and configuration layering

Configuration resolves in three layers, highest first:

1. Values saved on the Settings page (stored in the database)
2. `.env` on the server
3. Field defaults

So a key set in `.env` at deploy time can be replaced from the UI later, and
clearing the UI value falls back to `.env` again.

Secrets are never sent back to the browser. A stored secret renders as `********`
with a **Replace** button; leaving it alone keeps the current value.

Only the keys in `EDITABLE_KEYS` (`app/repositories/settings_store.py`) can be
written from the UI. `DATABASE_URL`, `SECRET_KEY` and the storage paths stay in
`.env` where a web request cannot reach them.

## Retention

`RETENTION_DAYS` (default 7) governs messages, reports and downloaded media.
An hourly task deletes expired rows and the files they point at, plus any
orphaned files whose rows never got written.

Per-contact totals are **not** decremented, so "42 reports" stays true after the
individual rows are gone.

## Voice-to-text without an API key

Transcription never depends on configuration alone. If the chosen provider has
no API key, or its library is not installed, the bot falls back to a built-in
Python engine rather than returning an empty transcript that looks like a bad
recording.

Resolution order (`app/ai/registry.py:LOCAL_STT_CHAIN`):

| Order | Engine | Key | Internet | Notes |
|---|---|---|---|---|
| 1 | faster-whisper | no | no | Best accuracy. `pip install faster-whisper` |
| 2 | PocketSphinx | no | no | Tiny, English only. `pip install pocketsphinx` |
| 3 | Google Web Speech | no | **yes** | Always available via SpeechRecognition |

Only the third is installed by default, so out of the box voice notes
transcribe with no configuration at all — as long as the server has internet.

Accuracy is the trade-off. Transcribing *"completed the slab casting on level
three and fixed two bugs"* through the free engine returns *"completed the slab
casting on level 3 and 62 bugs"*. That is why the dashboard reports a fallback
as a **warning**, not a pass:

```
Voice to text    [warn] Built-in · Google Web Speech (legacy)
                 Fell back to the built-in engine because 'groq' has no
                 API key. Add an API key for better accuracy.
```

Set `STT_PROVIDER="auto"` to use the built-in chain deliberately. For accurate
offline transcription with no key and no internet, uncomment `faster-whisper`
in `requirements.txt` and set `STT_PROVIDER="auto"` — it will be picked up
automatically.

## Theme

The portal uses the **Navy brand** theme from the HR Hiring Portal
(`design-system/talentsphere` / `docs/THEME_GUIDE.md` in that repository), so
the two read as one product:

| Token | Value | Used for |
|---|---|---|
| `--sidebar` | `#1e3a8a` | Navy nav panel |
| `--sidebar-active` | `#2c50b3` | Active nav item |
| `--primary` | `#f47c25` | Buttons, focus, active marker |
| `--canvas` | `#f5f6f9` | Page background |
| `--surface` | `#ffffff` | Cards |
| `--ink` | `#222b42` | Text |
| `--line` | `#e4e7ee` | Borders |
| `--chart-2` | `#4390c3` | Steel accent, chart bars |
| `--radius` | `12px` | Corner rounding |

Type is Poppins for headings and Open Sans for body, matching that project.
The fonts load from Google Fonts with a Segoe UI / system-ui fallback, so a
machine with no internet gets the same layout in system type. Removing the
three `<link>` tags in `base.html`, `login.html` and `error.html` makes the
portal fully self-contained.

**Light is the default.** Every page stamps `data-theme="light"` on `<html>`,
and the operating system's dark preference is deliberately not followed — so
everyone sees the same portal unless they choose otherwise. Dark is opt-in
through the sidebar toggle and remembered per browser; it mirrors that
project's `.dark` palette (oklch, violet primary).

### Sign-in page

The sign-in screen is copied from that project's login (`frontend/src/app/login`)
rather than the in-app theme, because it has its own composition and brand
palette there:

- Deep navy mesh canvas — the same layered radial gradients and vignette
- White card with a blue-to-green gradient header band carrying the Techknomatic
  wordmark, the portal name, and three brand chips (**Listen · Draft · Deliver**)
- Icon-prefixed username and password fields on a tinted `#fbfdff` ground
- A hero panel on the right that drops away below 1024px

### The pipeline graphic

Five stages — Voice note, Transcribe, Structure, Report, Delivered — each with
its own colour, drawn from the Techknomatic palette:

| Stage | Colour |
|---|---|
| Voice note | `#4FA3D9` steel blue |
| Transcribe | `#20C5CB` teal |
| Structure | `#3AA655` green |
| Report | `#F47C25` brand orange |
| Delivered | `#B0D058` lime |

The colour **flows**: when a stage lights, the connector to the next one fills
left-to-right with a `linear-gradient(90deg, var(--c), var(--next))`, carrying
that stage's colour into the following one. It is one 8-second CSS loop with
each node and connector phase-shifted by `animation-delay`, so there is no
JavaScript involved. Under `prefers-reduced-motion` the whole chain simply
rests fully lit.

The page never follows the OS dark setting — the navy artwork is the design.

### Deviations, and why

Four values differ from the source tokens. Each one failed the 4.5:1 text
contrast the same design system's own pre-delivery checklist requires:

| Token | Source | Here | Measured |
|---|---|---|---|
| `--primary-ink` | `#ffffff` | `#222b42` | white on `#f47c25` was 2.71:1 → 5.20:1 |
| `--primary-soft-ink` | `#c95e10` | `#a34a08` | 3.56:1 → 5.11:1 |
| `--secondary-ink` | `#1778af` | `#146395` | 4.11:1 → 5.50:1 |
| `--focus` | `#f47c25` | `#c95e10` | 2.51:1 on canvas → 3.82:1 |

The brand orange itself is untouched — only the text drawn on it changed, which
keeps the buttons recognisably the same colour. Darkening the orange enough to
carry white text would have meant `#b45309`, a visibly different hue.

For pixel parity with the HR portal instead, set `--primary-ink: #ffffff` in
`app/web/static/app.css`.

## Security

- Session cookies are signed with `SECRET_KEY`; the cookie carries only a user
  id, so a role change or a disabled account takes effect on the next request
  rather than when the cookie expires.
- Passwords are bcrypt, SHA-256 pre-hashed so long passphrases are not truncated.
- Failed logins take the same time whether or not the username exists.
- The last administrator cannot be deleted, disabled, or demoted.
- Download authorisation is checked on the download route itself, not only on
  the page that rendered the link.
- `/docs` is disabled outside development.

Put the portal behind HTTPS — `deploy/setup-tls.sh` does this with Caddy. The
session cookie is marked `secure` outside development, so it will not be sent
over plain HTTP.
