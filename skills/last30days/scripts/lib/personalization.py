"""Optional personal-interest relevance signals for research ranking.

This module is intentionally stateless. Callers supply a small set of interest
terms for the current research session; no user profile is persisted here.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import relevance, schema

_CURATOR_GENERIC_TOPIC_TOKENS = frozenset({
    "ai", "artificial", "intelligence", "agent", "agents", "mcp",
    "automation", "automated", "workflow", "workflows", "system", "systems",
    "platform", "platforms", "tool", "tools",
})


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



def _item_text(item: schema.SourceItem) -> str:
    return "\n".join(
        part for part in (
            item.title, item.body, item.snippet, item.why_relevant, item.container or "",
        ) if part
    )

def _anchor_text(item: schema.SourceItem) -> str:
    """High-salience text for topic anchors; avoids incidental late-transcript mentions."""
    representative = item.snippet or (item.body[:1200] if item.body else "")
    return "\n".join(part for part in (item.title, representative) if part)

def topic_anchor_coverage(item: schema.SourceItem, ranking_query: "str | relevance.PreparedQuery") -> float:
    prepared = ranking_query if isinstance(ranking_query, relevance.PreparedQuery) else relevance.PreparedQuery(ranking_query)
    anchors = set(prepared.informative_q_tokens) - _CURATOR_GENERIC_TOPIC_TOKENS
    if not anchors:
        anchors = set(prepared.informative_q_tokens)
    if not anchors:
        return 1.0
    text_tokens = relevance.tokenize(_anchor_text(item))
    return round(len(anchors & text_tokens) / len(anchors), 4)


def interest_term_coverage(item: schema.SourceItem, interest_terms: Iterable[str] | None) -> float:
    terms = normalize_interest_terms(interest_terms)
    if not terms:
        return 0.0
    text = _anchor_text(item)
    hashtags = item.metadata.get("hashtags") if isinstance(item.metadata, dict) else None
    matched = sum(
        relevance.token_overlap_relevance(term, text, hashtags=hashtags) >= 0.45
        for term in terms
    )
    return round(matched / len(terms), 4)

def curator_score(*, topic_relevance: float, topic_anchor_score: float,
                  personal_relevance_score: float, interest_coverage_score: float,
                  freshness_score: float, source_quality_score: float) -> float:
    personal_alignment = (0.65 * personal_relevance_score) + (0.35 * interest_coverage_score)
    topic_gate = 0.20 + (0.80 * topic_anchor_score)
    score = (
        0.40 * topic_relevance
        + 0.30 * topic_anchor_score
        + 0.15 * (personal_alignment * topic_gate)
        + 0.08 * freshness_score
        + 0.07 * source_quality_score
    )
    return round(max(0.0, min(1.0, score)), 4)

def personal_relevance(item: schema.SourceItem, interest_terms: Iterable[str] | None) -> float:
    """Score how closely one evidence item matches the caller's current interests."""
    terms = normalize_interest_terms(interest_terms)
    if not terms:
        return 0.0

    query = relevance.PreparedQuery(" ".join(terms))
    text = _item_text(item)
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
