import unittest

from skills.last30days.scripts.lib import personalization, schema, signals


class PersonalizationV3Tests(unittest.TestCase):
    def _item(self, item_id: str, body: str) -> schema.SourceItem:
        return schema.SourceItem(
            item_id=item_id,
            source="youtube",
            title="AI agent workflow tutorial",
            body=body,
            url=f"https://youtube.com/watch?v={item_id}",
            published_at="2026-09-10",
            engagement={"views": 5000, "likes": 200, "comments": 20},
        )

    def test_normalize_interest_terms_trims_deduplicates_and_preserves_order(self):
        terms = personalization.normalize_interest_terms(
            [" GitHub ", "MCP", "github", "", "Human Gate"]
        )
        self.assertEqual(("GitHub", "MCP", "Human Gate"), terms)

    def test_personal_relevance_uses_transcript_snippet(self):
        item = self._item("yt-1", "General automation overview")
        item.snippet = "Use GitHub pull requests with MCP and a human approval gate."
        score = personalization.personal_relevance(
            item,
            ["GitHub pull request", "MCP", "human approval"],
        )
        self.assertGreater(score, 0.5)

    def test_annotate_stream_personal_context_can_break_generic_tie(self):
        preferred = self._item(
            "preferred",
            "GitHub pull request automation with MCP, CI checks, and human gate approval.",
        )
        generic = self._item(
            "generic",
            "AI agent automation patterns for general productivity workflows.",
        )
        ranked = signals.annotate_stream(
            [generic, preferred],
            ranking_query="AI agent workflow tutorial",
            freshness_mode="balanced_recent",
            reference_date="2026-09-17",
            personal_interest_terms=["GitHub", "pull request", "MCP", "human gate"],
        )
        self.assertEqual("preferred", ranked[0].item_id)
        self.assertGreater(
            preferred.metadata["personal_relevance"],
            generic.metadata["personal_relevance"],
        )

    def test_annotate_stream_without_context_keeps_legacy_formula(self):
        item = self._item("legacy", "AI agent workflow tutorial")
        ranked = signals.annotate_stream(
            [item],
            ranking_query="AI agent workflow tutorial",
            freshness_mode="balanced_recent",
            reference_date="2026-09-17",
        )
        expected = (
            0.65 * item.local_relevance
            + 0.25 * (item.freshness / 100.0)
            + 0.10 * ((item.engagement_score or 0) / 100.0)
        )
        self.assertAlmostEqual(expected, ranked[0].local_rank_score)
        self.assertNotIn("personal_relevance", ranked[0].metadata)


if __name__ == "__main__":
    unittest.main()
