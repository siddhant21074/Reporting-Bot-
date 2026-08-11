"""Unicode font resolution for PDF generation.

fpdf2's built-in fonts are Latin-1 only, so the report generator used to strip
every character outside that range -- silently deleting Devanagari, the rupee
sign and typographic punctuation from reports written in Hindi or Marathi.

This module finds a real TrueType font at runtime and registers it, plus an
Indic fallback face for scripts the main font does not cover. If nothing usable
is installed the caller falls back to Helvetica and Latin-1 transliteration, so
PDF generation degrades rather than failing.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger("app.reports.fonts")

# Directories searched for TrueType files, in order.
_SEARCH_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype",
    "/usr/local/share/fonts",
    "/Library/Fonts",
    "C:/Windows/Fonts",
)

# Preferred families, best first. Each entry maps an fpdf2 style to a filename.
_FAMILY_CANDIDATES = (
    ("DejaVuSans", {"": "DejaVuSans.ttf", "B": "DejaVuSans-Bold.ttf", "I": "DejaVuSans-Oblique.ttf"}),
    ("NotoSans", {"": "NotoSans-Regular.ttf", "B": "NotoSans-Bold.ttf", "I": "NotoSans-Italic.ttf"}),
    ("LiberationSans", {"": "LiberationSans-Regular.ttf", "B": "LiberationSans-Bold.ttf", "I": "LiberationSans-Italic.ttf"}),
    ("Arial", {"": "arial.ttf", "B": "arialbd.ttf", "I": "ariali.ttf"}),
)

# Registered after the main family so Devanagari renders instead of boxing out.
_FALLBACK_CANDIDATES = (
    ("NotoDevanagari", "NotoSansDevanagari-Regular.ttf"),
    ("NotoDevanagariUI", "NotoSansDevanagariUI-Regular.ttf"),
    ("Nirmala", "Nirmala.ttc"),      # Windows: Devanagari, Tamil, Telugu, Gujarati
    ("Mangal", "mangal.ttf"),
)


@dataclass
class FontSet:
    """The fonts a PDF should use."""

    family: str = "Helvetica"
    unicode: bool = False
    fallbacks: List[str] = field(default_factory=list)
    _files: Dict[str, str] = field(default_factory=dict)
    _fallback_files: Dict[str, str] = field(default_factory=dict)

    def register(self, pdf) -> None:
        """Registers every resolved face on an ``FPDF`` instance.

        Args:
            pdf: The ``FPDF`` document to register fonts on.
        """
        if not self.unicode:
            return

        for style, path in self._files.items():
            pdf.add_font(self.family, style, path)

        registered: List[str] = []
        for name, path in self._fallback_files.items():
            try:
                if path.lower().endswith(".ttc"):
                    # .ttc bundles several faces; the first is the one we want.
                    # collection_font_number only exists on newer fpdf2 builds.
                    try:
                        pdf.add_font(name, "", path, collection_font_number=0)
                    except TypeError:
                        pdf.add_font(name, "", path)
                else:
                    pdf.add_font(name, "", path)
                registered.append(name)
            except Exception as exc:
                logger.warning(f"Could not register fallback font '{name}' from '{path}': {exc}")

        if registered:
            # exact_match=False lets a regular-weight fallback stand in for bold,
            # which is what we want for a script the main family lacks entirely.
            pdf.set_fallback_fonts(registered, exact_match=False)


def _search_dirs() -> List[Path]:
    """Returns the directories to search, project fonts first."""
    dirs = [Path(settings.app.fonts_dir)] if settings.app.fonts_dir else []
    dirs.extend(Path(d) for d in _SEARCH_DIRS)
    return [d for d in dirs if d.is_dir()]


def _find(filename: str, dirs: List[Path]) -> Optional[str]:
    """Finds a font file by name, case-insensitively."""
    target = filename.lower()
    for directory in dirs:
        candidate = directory / filename
        if candidate.is_file():
            return str(candidate)
        try:
            for entry in os.listdir(directory):
                if entry.lower() == target:
                    return str(directory / entry)
        except OSError:
            continue
    return None


def resolve_fonts() -> FontSet:
    """Locates the best available Unicode font family.

    Returns:
        A ``FontSet``. When ``unicode`` is False no TrueType font was found and
        the caller must sanitise text to Latin-1.
    """
    dirs = _search_dirs()
    if not dirs:
        logger.warning("No font directories found; PDFs will use Latin-1 Helvetica.")
        return FontSet()

    for family, styles in _FAMILY_CANDIDATES:
        regular = _find(styles[""], dirs)
        if not regular:
            continue

        files = {"": regular}
        # A missing bold or italic file is not fatal: reuse the regular face so
        # set_font(..., "B") still resolves.
        for style in ("B", "I"):
            files[style] = _find(styles[style], dirs) or regular

        fallback_files: Dict[str, str] = {}
        for name, filename in _FALLBACK_CANDIDATES:
            path = _find(filename, dirs)
            if path:
                fallback_files[name] = path

        logger.info(
            f"PDF font family resolved to '{family}'"
            + (f" with fallbacks {list(fallback_files)}" if fallback_files else " (no Indic fallback found)"),
            extra={"event": "pdf_fonts_resolved", "family": family},
        )
        return FontSet(
            family=family,
            unicode=True,
            fallbacks=list(fallback_files),
            _files=files,
            _fallback_files=fallback_files,
        )

    logger.warning(
        "No Unicode TrueType font found. PDFs fall back to Helvetica and non-Latin "
        "characters will be transliterated. Install fonts-dejavu-core and "
        "fonts-noto-core, or drop a .ttf into the fonts directory.",
        extra={"event": "pdf_fonts_missing"},
    )
    return FontSet()


_cached: Optional[FontSet] = None


def get_fonts() -> FontSet:
    """Returns the resolved font set, computing it once per process."""
    global _cached
    if _cached is None:
        _cached = resolve_fonts()
    return _cached
