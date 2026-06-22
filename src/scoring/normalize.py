"""Normalize bird common names for comparison at evaluation time.

The benchmark stores names in their official CBRO/eBird/AviList casing (e.g.
"Creamy-bellied Thrush", "Swainson's Thrush"). The *scorer* must compare a
model's output against the target without being tripped up by surface
differences that are not real disagreements -- casing, hyphen vs space,
apostrophes, surrounding punctuation, doubled whitespace.

:func:`normalize_for_match` produces that comparison key. It is applied to BOTH
sides at scoring time (model output and target) and never written back to the
dataset -- "dataset = truth, scorer = normalization".

Design boundaries (intentional):

- It standardizes *form*, not *lexicon*. "Gray" and "Grey", or "Grey-headed"
  and "Gray-hooded", stay distinct -- those are genuine name differences and
  belong to a separate "acceptable variants" layer, not here.
- It does NOT strip diacritics. English common names rarely carry them, and
  folding accents could conflate distinct names; revisit only if real data
  needs it.
"""

from __future__ import annotations

import re
import unicodedata

# Anything that is not a word character (letters/digits, Unicode-aware) or
# whitespace is dropped: apostrophes, parentheses, commas, periods, etc.
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_match(name: str | None) -> str:
    """Return a case- and hyphen-insensitive comparison key for ``name``.

    Lowercases (Unicode-aware), turns hyphens and slashes into spaces, removes
    remaining punctuation, and collapses runs of whitespace. Empty/None input
    yields ``""``.

    >>> normalize_for_match("Creamy-bellied Thrush")
    'creamy bellied thrush'
    >>> normalize_for_match("creamy bellied  THRUSH")
    'creamy bellied thrush'
    >>> normalize_for_match("Swainson's Thrush")
    'swainsons thrush'
    >>> normalize_for_match("Black-fronted Piping-Guan") == \\
    ...     normalize_for_match("Black-fronted Piping Guan")
    True
    >>> normalize_for_match("Gray Tinamou") == normalize_for_match("Grey Tinamou")
    False
    >>> normalize_for_match(None)
    ''
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFC", str(name)).casefold()
    # Hyphens and slashes are word separators, not punctuation to delete.
    text = text.replace("-", " ").replace("/", " ")
    text = _PUNCT_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()
