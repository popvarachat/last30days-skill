import unittest

import last30days as cli
from lib import pipeline
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

    def test_curator_topic_anchors_demote_cross_domain_mcp_false_positive(self):
        github = self._item(
            "github",
            "GitHub pull request agent with MCP, CI checks, and human approval before merge.",
        )
        docusign = self._item(
            "docusign",
            "Docusign renewal risk agent uses MCP and human approval for contract cancellation.",
        )
        ranked = signals.annotate_stream(
            [docusign, github],
            ranking_query="GitHub AI agents pull request human approval MCP",
            freshness_mode="balanced_recent",
            reference_date="2026-09-17",
            personal_interest_terms=[
                "GitHub Actions", "MCP", "pull request governance", "human approval", "CI automation"
            ],
        )
        self.assertEqual("github", ranked[0].item_id)
        self.assertGreater(github.metadata["topic_anchor_score"], docusign.metadata["topic_anchor_score"])
        self.assertGreater(github.metadata["curator_score"], docusign.metadata["curator_score"])

    def test_curator_score_is_bounded_and_records_interest_coverage(self):
        item = self._item("bounded", "GitHub pull request with human approval and MCP automation")
        signals.annotate_stream(
            [item],
            ranking_query="GitHub pull request governance",
            freshness_mode="balanced_recent",
            reference_date="2026-09-17",
            personal_interest_terms=["GitHub", "human approval", "MCP"],
        )
        self.assertGreaterEqual(item.metadata["curator_score"], 0.0)
        self.assertLessEqual(item.metadata["curator_score"], 1.0)
        self.assertGreater(item.metadata["interest_coverage_score"], 0.5)

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

    def test_cli_accepts_repeatable_interest_context(self):
        args = cli.build_parser().parse_args([
            "test topic",
            "--interest-context", "GitHub",
            "--interest-context", "MCP human gate",
        ])
        self.assertEqual(["GitHub", "MCP human gate"], args.interest_context)

    def test_mock_pipeline_applies_session_interest_metadata(self):
        report = pipeline.run(
            topic="test topic",
            config={
                "LAST30DAYS_REASONING_PROVIDER": "gemini",
                "_PERSONAL_INTEREST_TERMS": ["GitHub", "MCP", "human gate"],
            },
            depth="quick",
            requested_sources=["reddit", "x", "grounding"],
            mock=True,
        )
        items = [item for values in report.items_by_source.values() for item in values]
        self.assertTrue(items)
        self.assertTrue(all("personal_relevance" in item.metadata for item in items))


if __name__ == "__main__":
    unittest.main()
