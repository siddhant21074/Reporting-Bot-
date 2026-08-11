"""Creates or repairs .env, and reports what still needs filling in.

Called by setup.bat and usable by hand. Safe to re-run: it only ever adds
missing values, never overwrites one you have set.

    python scripts/ensure_env.py

Exit codes:
    0  .env is ready to run
    2  .env exists but required credentials are still blank
"""

import os
import re
import secrets
import shutil
import sys
from pathlib import Path

# Windows consoles still default to a legacy codepage (cp1252), which cannot
# encode characters outside Latin-1. Setup output is kept ASCII for that
# reason; this is belt and braces in case that slips.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"

# Without these the service cannot do its job.
REQUIRED = [
    ("WHATSAPP_ACCESS_TOKEN", "Meta dashboard > WhatsApp > API Setup"),
    ("WHATSAPP_APP_SECRET", "Meta dashboard > App Settings > Basic"),
    ("WHATSAPP_VERIFY_TOKEN", "any string you choose (paste the same one into Meta)"),
    ("WHATSAPP_PHONE_NUMBER_ID", "Meta dashboard > WhatsApp > API Setup"),
    ("LLM_API_KEY", "your OpenAI / Groq / OpenRouter key"),
]

# Generated automatically when blank.
GENERATED = {
    "SECRET_KEY": lambda: secrets.token_urlsafe(48),
}


def read_value(text: str, key: str) -> str:
    """Returns the value of a key in .env text, stripped of quotes."""
    match = re.search(rf"^{re.escape(key)}=(.*)$", text, flags=re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def set_value(text: str, key: str, value: str) -> str:
    """Sets a key in .env text, appending it if the key is absent."""
    line = f'{key}="{value}"'
    pattern = rf"^{re.escape(key)}=.*$"
    if re.search(pattern, text, flags=re.MULTILINE):
        return re.sub(pattern, line, text, count=1, flags=re.MULTILINE)
    return text.rstrip("\n") + f"\n{line}\n"


def main() -> int:
    created = False

    if not ENV_PATH.exists():
        if not EXAMPLE_PATH.exists():
            print("  .env.example is missing; cannot create .env.", file=sys.stderr)
            return 1
        shutil.copyfile(EXAMPLE_PATH, ENV_PATH)
        created = True

    text = ENV_PATH.read_text(encoding="utf-8")

    # Fill in anything we can generate ourselves. This also repairs a .env
    # created before SECRET_KEY existed.
    filled = []
    for key, generator in GENERATED.items():
        if not read_value(text, key):
            text = set_value(text, key, generator())
            filled.append(key)

    if filled or created:
        ENV_PATH.write_text(text, encoding="utf-8")

    if created:
        print("      Created .env from .env.example")
    if filled:
        print(f"      Generated {', '.join(filled)}")
    if not created and not filled:
        print("      .env already present and complete")

    # Restrict the file where the platform allows it.
    try:
        if os.name != "nt":
            os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass

    missing = [(key, where) for key, where in REQUIRED if not read_value(text, key)]
    if not missing:
        print("      All required credentials are set")
        return 0

    print()
    print("      Still to fill in (open .env in a text editor):")
    for key, where in missing:
        print(f"        {key:<26} {where}")
    print()
    print("      For a free AI setup, set these in .env instead of an OpenAI key:")
    print('        LLM_PROVIDER="groq"   LLM_MODEL="llama-3.3-70b-versatile"')
    print('        STT_PROVIDER="groq"   STT_MODEL="whisper-large-v3"')
    print("        LLM_API_KEY from https://console.groq.com/keys")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
