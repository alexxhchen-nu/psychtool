"""Reversible identifier redaction (de-identification) for source text.

Implements the HIPAA Safe Harbor 18-identifier categories (45 CFR 164.514(b))
as a data-driven, extensible detector. The engine is a standalone tool: it has
no network access, no persistence, and no dependency on the rest of the code
base, so it can be reused by the draft prompt builder, the eval hard gates, and
any future import/export surface.

Two operations are exposed:

* ``redact_text`` -> ``(redacted, token_map)``: replace identifiers with
  semantic tokens such as ``[[TELEPHONE_1]]``. The ``token_map`` maps tokens
  back to the original values and must never leave the machine (it is what lets
  a downstream human reconstruct the final report without ever sending the
  identifiers to a model).
* ``restore_text``: substitute the tokens back using a token map.
* ``find_identifiers`` / ``gate_pii``: report identifiers in text (used as an
  output-side re-identification scan).

Detection is regex-based and therefore covers only machine-detectable
categories. The following Safe Harbor categories are NOT auto-detectable from
plain text and are documented as such (they need named-entity recognition,
image/audio analysis, or caller-supplied values):

* ``name`` -- detected only from the caller-supplied ``known_names`` list.
* ``biometric_identifier``, ``full_face_photo`` -- binary media, not text.
* ``other_unique_identifier`` -- context-dependent; supplied via ``known_names``
  or a future extension.

The pattern table is the extension point: append a ``(kind, regex)`` tuple to
``_PATTERNS`` to teach the engine a new category without touching call sites.
"""

from __future__ import annotations

import re

# Canonical Safe Harbor 18 categories (A through R) and their plain labels.
SAFE_HARBOR_18: tuple[tuple[str, str], ...] = (
    ("name", "Names"),
    ("geographic_subdivision", "Geographic subdivisions smaller than a state"),
    ("date", "Dates (other than year) and ages over 89"),
    ("telephone", "Telephone numbers"),
    ("fax", "Fax numbers"),
    ("email", "Electronic mail addresses"),
    ("ssn", "Social security numbers"),
    ("medical_record_number", "Medical record numbers"),
    ("health_plan_beneficiary_number", "Health plan beneficiary numbers"),
    ("account_number", "Account numbers"),
    ("certificate_license_number", "Certificate/license numbers"),
    ("vehicle_identifier", "Vehicle identifiers and serial numbers"),
    ("device_identifier", "Device identifiers and serial numbers"),
    ("url", "Web URLs"),
    ("ip_address", "Internet Protocol addresses"),
    ("biometric_identifier", "Biometric identifiers"),
    ("full_face_photo", "Full-face photographs and comparable images"),
    ("other_unique_identifier", "Other unique identifying characteristics"),
)

IDENTIFIER_KINDS: dict[str, str] = dict(SAFE_HARBOR_18)

# ``age_over_89`` is folded into the Safe Harbor "date" category but is kept as
# its own detection kind so callers can reason about it separately.
IDENTIFIER_KINDS["age_over_89"] = "Ages over 89"
IDENTIFIER_KINDS["vin"] = "Vehicle identification numbers"
IDENTIFIER_KINDS["zip"] = "ZIP codes"

# Ordered (kind, regex). Order matters: the most distinctive patterns run first
# so that, for example, a social security number is not re-labelled a phone.
_PATTERNS: tuple[tuple[str, str], ...] = (
    ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ("url", r"\b(?:https?://|www\.)[^\s<>()\"']+"),
    ("ip_address", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("telephone", r"(?<!\w)(?:\+?\d{1,2}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)"),
    ("fax", r"(?i)\bfax\s*(?:number|no\.?|#)?\s*:?\s*(\+?\d[\d\s.-]{6,}\d)\b"),
    ("vin", r"\b[A-HJ-NPR-Z0-9]{17}\b"),
    (
        "date",
        r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}"
        r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
        r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4})\b",
    ),
    ("age_over_89", r"\b(?:9[0-9]|1[0-4][0-9])\s*(?:years?|yrs?\.?|y\.?o\.?)\b"),
    ("zip", r"\b\d{5}(?:-\d{4})?\b"),
    ("medical_record_number", r"(?i)\b(?:MRN|medical\s+record)\s*(?:#|number|no\.?)?\s*:?\s*[A-Z0-9-]{4,}\b"),
    ("health_plan_beneficiary_number", r"(?i)\b(?:member|beneficiary|subscriber)\s*(?:id|#|number|no\.?)?\s*:?\s*\d[\d-]{3,}\b"),
    ("account_number", r"(?i)\baccount\s*(?:#|number|no\.?)?\s*:?\s*\d[\d-]{3,}\b"),
    ("certificate_license_number", r"(?i)\b(?:license|lic\.|certificate|cert\.)\s*(?:#|number|no\.?)?\s*:?\s*[A-Z0-9-]{4,}\b"),
    ("device_identifier", r"(?i)\b(?:device|serial|IMEI|MAC)\s*(?:#|id|no\.?)?\s*:?\s*[A-Z0-9:-]{4,}\b"),
    ("geographic_subdivision", r"\b[A-Z][a-z]+(?:[\s.]+[A-Z][a-z]+)*,\s*[A-Z]{2}\b"),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(regex)) for kind, regex in _PATTERNS
)

_TOKEN_RE = re.compile(r"\[\[([A-Z_]+)_(\d+)\]\]")


def _name_regex(known_names: tuple[str, ...]) -> re.Pattern[str] | None:
    names = "|".join(re.escape(n) for n in known_names if n and n.strip())
    if not names:
        return None
    return re.compile(rf"\b(?:{names})\b", re.IGNORECASE)


def redact_text(text: str, *, known_names: tuple[str, ...] = ()) -> tuple[str, dict[str, str]]:
    """Replace identifiers with ``[[KIND_n]]`` tokens; return (text, token_map)."""
    token_map: dict[str, str] = {}
    counter = {"n": 0}
    redacted = text

    name_re = _name_regex(known_names)
    if name_re is not None:
        def _name_repl(match: re.Match[str]) -> str:
            token = f"[[NAME_{counter['n']}]]"
            counter["n"] += 1
            token_map[token] = match.group(0)
            return token
        redacted = name_re.sub(_name_repl, redacted)

    for kind, pattern in _COMPILED:
        def _repl(match: re.Match[str], kind: str = kind) -> str:
            token = f"[[{kind.upper()}_{counter['n']}]]"
            counter["n"] += 1
            token_map[token] = match.group(0)
            return token
        redacted = pattern.sub(_repl, redacted)

    return redacted, token_map


def restore_text(text: str, token_map: dict[str, str]) -> str:
    """Substitute ``[[KIND_n]]`` tokens back to their original values."""
    def _repl(match: re.Match[str]) -> str:
        return token_map.get(match.group(0), match.group(0))
    return _TOKEN_RE.sub(_repl, text)


def find_identifiers(text: str, *, known_names: tuple[str, ...] = ()) -> list[dict]:
    """Report identifiers found in ``text`` (empty list means none detected)."""
    findings: list[dict] = []
    name_re = _name_regex(known_names)
    if name_re is not None:
        for match in name_re.finditer(text):
            findings.append(_finding("name", match.group(0)))
    for kind, pattern in _COMPILED:
        for match in pattern.finditer(text):
            findings.append(_finding(kind, match.group(0)))
    return findings


def _finding(kind: str, value: str) -> dict:
    return {"category": kind, "label": IDENTIFIER_KINDS.get(kind, kind), "value": value}


def gate_pii(text: str, *, known_names: tuple[str, ...] = ()) -> list[dict]:
    """Output-side re-identification scan; returns findings (empty = pass)."""
    return find_identifiers(text, known_names=known_names)
