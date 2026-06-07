"""Decompose the CBRO ``Status`` field into structured columns.

The spreadsheet's ``Status`` field is a composite, comma-separated string that
encodes several dimensions at once. Real examples:

    "BR"            -> breeding resident
    "BR, En"        -> breeding resident + endemic to Brazil
    "BR, En, Ex"    -> resident + endemic + extinct
    "VI (S)"        -> seasonal visitor from the South
    "VA (N?, E?)"   -> vagrant from the North/East (uncertain direction)
    "BR#"           -> resident with assumed, unconfirmed status

Official legend (the spreadsheet's "Legenda Status" tab):
    BR  Breeding resident or breeding migrant
    VI  Regular non-breeding (seasonal) visitor
    VA  Vagrant
    En  Species endemic to Brazil
    Ex  Species extinct in the country
    In  Introduced species
    #   Status assumed but not confirmed

Directions in parentheses (S/N/E/W) indicate the origin for VI and VA.

We decompose this into discrete, boolean fields that are easy to filter in
pandas without re-parsing strings -- and, as a bonus, we eliminate the internal
comma that broke fragile CSV viewers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# Base tokens recognized. A token may carry a "#" suffix (unconfirmed) and/or
# directions in parentheses, e.g. "VI# (S, N?)".
_OCCURRENCE_TOKENS = {"BR", "VI", "VA"}
_FLAG_TOKENS = {"En", "Ex", "In"}

# Captures: base (letters), optional "#", optional "(...)".
_TOKEN_RE = re.compile(r"^([A-Za-z]+)(#?)\s*(?:\(([^)]*)\))?$")


@dataclass(frozen=True)
class StatusFields:
    """Decomposed representation of a CBRO Status field."""

    status_raw: str          # original string, kept for reference
    occurrence: str          # "BR" | "VI" | "VA" | "" (occurrence category)
    endemic_brazil: bool     # "En" token present
    extinct: bool            # "Ex" token present
    introduced: bool         # "In" token present
    status_uncertain: bool   # any token marked with "#"
    origin_directions: str   # compiled directions, e.g. "S" or "N;E" (no comma)


def _split_tokens(status_raw: str) -> list[str]:
    """Split the composite status into tokens, respecting parentheses.

    We cannot simply split on commas: "VA (N?, E?)" contains a comma *inside*
    the parentheses that does not separate tokens. So we track parenthesis
    depth.
    """
    tokens: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in status_raw:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            tokens.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf).strip())
    return [t for t in tokens if t]


def parse_status(status_raw: str | None) -> StatusFields:
    """Decompose a CBRO Status string into :class:`StatusFields`.

    Tolerant of empty/None input and of unexpected tokens (which are silently
    ignored, but preserved in ``status_raw``).
    """
    raw = (status_raw or "").strip()
    if not raw:
        return StatusFields(
            status_raw="",
            occurrence="",
            endemic_brazil=False,
            extinct=False,
            introduced=False,
            status_uncertain=False,
            origin_directions="",
        )

    occurrence = ""
    endemic = extinct = introduced = uncertain = False
    directions: list[str] = []

    for token in _split_tokens(raw):
        m = _TOKEN_RE.match(token)
        if not m:
            # Token outside the expected pattern: preserved in raw, skip it.
            continue
        base, hash_flag, dirs = m.group(1), m.group(2), m.group(3)

        if hash_flag == "#":
            uncertain = True

        if base in _OCCURRENCE_TOKENS:
            # The first occurrence defines the main category. Cases with two
            # (rare, e.g. "VI (S), BR") privilege BR as the main occurrence
            # when present, since it indicates breeding in the country.
            if base == "BR" or not occurrence:
                occurrence = base
            if dirs:
                directions.extend(_clean_directions(dirs))
        elif base == "En":
            endemic = True
        elif base == "Ex":
            extinct = True
        elif base == "In":
            introduced = True

    return StatusFields(
        status_raw=raw,
        occurrence=occurrence,
        endemic_brazil=endemic,
        extinct=extinct,
        introduced=introduced,
        status_uncertain=uncertain,
        # Use ';' as separator so we never reintroduce a comma into the CSV.
        origin_directions=";".join(directions),
    )


def _clean_directions(dirs: str) -> list[str]:
    """Extract S/N/E/W directions from a string like 'N?, E?' -> ['N', 'E']."""
    found = re.findall(r"[SNEW]", dirs.upper())
    # Drop duplicates while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for d in found:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def status_to_dict(status_raw: str | None) -> dict[str, object]:
    """Convenience: return the decomposed status as a dict (for CSV writing)."""
    return asdict(parse_status(status_raw))
