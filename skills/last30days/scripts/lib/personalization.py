"""Optional personal-interest relevance signals for research ranking.

This module is intentionally stateless. Callers supply a small set of interest
terms for the current research session; no user profile is persisted here.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import relevance, schema


def normalize_interest_terms(interest_terms: Iterable[str] | None) -> tuple[str, ...]:
    """Return trimmed, de-duplicated interest terms while preserving order."""
    if not interest_terms:
        return ()
    seen: set[str] = set()
    normalized: list[str] = []
    for value in interest_terms:
        term = str(value).strip()
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        normalized.append(term)
    return tuple(normalized)


def personal_relevance(item: schema.SourceItem, interest_terms: Iterable[str] | None) -> float:
    """Score how closely one evidence item matches the caller's current interests."""
    terms = normalize_interest_terms(interest_terms)
    if not terms:
        return 0.0

    query = relevance.PreparedQuery(" ".join(terms))
    text = "\n".join(
        part
        for part in (
            item.title,
            item.body,
            item.snippet,
            item.why_relevant,
            item.container or "",
        )
        if part
    )
    hashtags = item.metadata.get("hashtags") if isinstance(item.metadata, dict) else None
    return relevance.token_overlap_relevance(query, text, hashtags=hashtags)


def annotate_personal_relevance(
    item: schema.SourceItem,
    interest_terms: Iterable[str] | None,
) -> float:
    """Attach personal relevance to item metadata and return the score."""
    score = personal_relevance(item, interest_terms)
    if isinstance(item.metadata, dict):
        item.metadata["personal_relevance"] = score
    return score
