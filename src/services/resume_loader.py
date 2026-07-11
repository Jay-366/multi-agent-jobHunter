"""Resume loader — read a resume file (.txt/.md/.pdf) into clean raw text (no LLM).

PDF text is extracted with pypdf and lightly normalized (odd bullet/dash glyphs, runaway
whitespace). Because a scanned/image PDF can yield almost nothing, `validate_resume_text`
gives a quality verdict callers can surface before spending an LLM call on junk.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

_SUPPORTED = {".txt", ".md", ".pdf"}

# Code points PDFs commonly use, normalized to plain ASCII for the LLM.
# Written as \u escapes so no empty/ambiguous key can slip in.
_GLYPHS = {
    "•": "- ",   # • bullet
    "": "- ",   # Wingdings bullet (private use area)
    "●": "- ",   # ● black circle
    "‣": "- ",   # ‣ triangular bullet
    "⁃": "- ",   # ⁃ hyphen bullet
    "’": "'", "‘": "'",   # ’ ‘
    "“": '"', "”": '"',   # “ ”
    "–": "-", "—": "-",   # – —
    " ": " ",                   # non-breaking space
}


def _clean(text: str) -> str:
    for bad, good in _GLYPHS.items():
        text = text.replace(bad, good)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF bytes and normalize it. Raises RuntimeError if pypdf is absent."""
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("PDF support needs pypdf — run: pip install pypdf") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = [(page.extract_text() or "") for page in reader.pages]
    except Exception as e:  # corrupt file, wrong type behind a .pdf name, encrypted, etc.
        raise ValueError(f"Could not read the PDF — it may be corrupt or not a real PDF: {e}") from e
    return _clean("\n".join(parts))


def extract_resume_bytes(filename: str, data: bytes) -> str:
    """Extract resume text from uploaded bytes (used by the UI — no temp file)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED:
        raise ValueError(f"Unsupported resume type {suffix!r}; supported: {sorted(_SUPPORTED)}")
    if suffix == ".pdf":
        text = extract_pdf_text(data)
    else:
        text = _clean(data.decode("utf-8", errors="replace"))
    if not text:
        raise ValueError("No text could be extracted from the resume.")
    return text


def load_resume(path: str | Path) -> str:
    """Return the raw text of a resume file (.txt/.md/.pdf). Raises on missing/unsupported/empty."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Resume not found: {p}")
    if p.suffix.lower() not in _SUPPORTED:
        raise ValueError(
            f"Unsupported resume type {p.suffix!r}; supported: {sorted(_SUPPORTED)}"
        )
    if p.suffix.lower() == ".pdf":
        text = extract_pdf_text(p.read_bytes())
    else:
        text = _clean(p.read_text(encoding="utf-8"))
    if not text:
        raise ValueError(f"Resume file is empty or unreadable: {p}")
    return text


def validate_resume_text(text: str) -> dict:
    """Quality gate for extracted resume text.

    Catches the 'too little / garbled' case (e.g. a scanned image PDF) so the UI can warn
    before onboarding. Returns: ok, chars, words, alpha_ratio, has_contact, reasons.
    """
    text = text or ""
    n_chars = len(text)
    n_words = len(re.findall(r"[A-Za-z]{2,}", text))
    n_alpha = sum(c.isalpha() for c in text)
    alpha_ratio = (n_alpha / n_chars) if n_chars else 0.0
    has_email = bool(re.search(r"[\w.+-]+@[\w-]+\.\w+", text))
    has_contact = has_email or bool(re.search(r"\d{3}", text))

    reasons: list[str] = []
    if n_chars < 300:
        reasons.append("very little text extracted (<300 chars) — the PDF may be scanned/"
                       "image-based. Try a .md or .txt export instead.")
    if n_words < 80:
        reasons.append("too few words (<80) to build a good profile.")
    if alpha_ratio < 0.5:
        reasons.append("text looks garbled (unusually few letters).")
    if not has_contact:
        reasons.append("no email or phone number found — extraction may be incomplete.")

    return {
        "ok": not reasons,
        "chars": n_chars,
        "words": n_words,
        "alpha_ratio": round(alpha_ratio, 2),
        "has_contact": has_contact,
        "reasons": reasons,
    }
