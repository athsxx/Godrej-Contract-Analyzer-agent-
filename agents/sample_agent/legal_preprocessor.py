"""Legal preprocessing helpers.

Builds lightweight legal context for contracts before agent analysis:
- defined terms
- cross references
- jurisdiction entities

The module works without a spaCy model; when `en_core_web_lg` is installed it adds
NER-derived jurisdiction hints.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List


@lru_cache(maxsize=1)
def _load_spacy_model():
    try:
        import spacy  # type: ignore

        return spacy.load("en_core_web_lg")
    except Exception:
        return None


def extract_defined_terms(text: str) -> Dict[str, str]:
    """Extract common definition patterns from contract text."""
    out: Dict[str, str] = {}
    if not text:
        return out
    patterns = [
        r'(?P<term>[A-Z][A-Za-z0-9 /&().-]{2,80})"\s*(?:means|shall mean)\s*(?P<definition>[^.;\n]{20,600})',
        r'"(?P<term>[A-Z][A-Za-z0-9 /&().-]{2,80})"\s*(?:means|shall mean)\s*(?P<definition>[^.;\n]{20,600})',
        r"\b(?P<term>[A-Z][A-Za-z0-9 /&().-]{2,80})\s+(?:means|shall mean)\s+(?P<definition>[^.;\n]{20,600})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            term = " ".join(match.group("term").strip(" \"'“”").split())
            definition = " ".join(match.group("definition").strip().split())
            if 2 <= len(term.split()) <= 8 or term[:1].isupper():
                out.setdefault(term, definition)
    return out


def extract_cross_references(text: str) -> List[Dict[str, str]]:
    """Extract clause/appendix/chapter cross references with surrounding context."""
    refs: List[Dict[str, str]] = []
    patterns = [
        r"\b(?:chapter|section|clause|article)\s+([0-9]+(?:\.[0-9]+)*)\b",
        r"\bappendix\s+([0-9]+(?:bis|ter|[A-Za-z])?)\b",
        r"\btitle\s+([0-9]+(?:\.[0-9]+)*)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 100)
            refs.append(
                {
                    "reference": match.group(0),
                    "target": match.group(1),
                    "context": " ".join((text[start:end] or "").split()),
                }
            )
    return refs


def extract_jurisdiction_entities(text: str) -> List[str]:
    """Extract jurisdiction/legal-procedure entities using rules + optional spaCy NER."""
    found = set()
    rules = [
        "Commercial Court of Paris",
        "Tribunal de Commerce de Paris",
        "Arbitration and Conciliation Act, 1996",
        "Arbitration and Conciliation Act",
        "Mumbai",
        "Paris",
        "France",
        "French law",
        "English law",
        "laws of India",
        "India",
    ]
    lower = (text or "").lower()
    for rule in rules:
        if rule.lower() in lower:
            found.add(rule)

    nlp = _load_spacy_model()
    if nlp is not None and text:
        sample = text[:120000]
        try:
            doc = nlp(sample)
            for ent in doc.ents:
                if ent.label_ in {"GPE", "ORG", "LAW"}:
                    value = " ".join(ent.text.split())
                    if any(k in value.lower() for k in ["court", "law", "arbitr", "paris", "mumbai", "india", "france"]):
                        found.add(value)
        except Exception:
            pass
    return sorted(found)


def build_legal_context(text: str) -> Dict[str, Any]:
    """Return structured legal context for downstream agents."""
    return {
        "defined_terms": extract_defined_terms(text),
        "cross_references": extract_cross_references(text),
        "jurisdiction_entities": extract_jurisdiction_entities(text),
    }

