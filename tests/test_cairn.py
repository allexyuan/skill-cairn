from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import cairn  # noqa: E402


class CairnTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name) / "vault"
        cairn.initialize_vault(self.vault)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_card(
        self,
        filename: str,
        *,
        title: str,
        topic: str,
        source: str,
        status: str = "verified",
        reusable: bool = True,
        tags: list[str] | None = None,
    ) -> Path:
        card_tags = tags or ["operations", "troubleshooting", status]
        source_lines = "\n".join(f'  - "{item}"' for item in source.split("|"))
        content = f"""---
title: "{title}"
date: "2026-10-25"
topic: "{topic}"
project: "sample-project"
source:
{source_lines}
tags:
{chr(10).join(f'  - "{item}"' for item in card_tags)}
reusable: {str(reusable).lower()}
---

# {title}

## Context

The behavior was observed in a sample project.

## Reusable knowledge

Apply the documented check before changing the routing configuration.

## Evidence

- The command output was captured.

## When not to use

Do not use this when the service is managed by another operator.

## Verification

Run the connectivity check twice after applying the change.
"""
        path = self.vault / "10-Knowledge" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_initialize_creates_vault_and_refuses_existing_config(self) -> None:
        self.assertTrue(
            (self.vault / "_config" / "skill-cairn.json").is_file()
        )
        self.assertTrue((self.vault / "_templates" / "knowledge-card.md").is_file())
        for relative in (
            "00-Inbox",
            "10-Knowledge",
            "20-SOP",
            "30-Skill-Candidates",
            "90-Map",
        ):
            self.assertTrue((self.vault / relative).is_dir())

        with self.assertRaises(cairn.CairnError):
            cairn.initialize_vault(self.vault)

    def test_valid_card_passes_validation(self) -> None:
        path = self.write_card(
            "routing-check.md",
            title="Routing check",
            topic="routing-check",
            source="Codex session 2026-10-25",
        )
        result = cairn.validate_vault(self.vault)
        self.assertTrue(result["ok"])
        self.assertEqual(result["card_count"], 1)
        self.assertEqual(result["cards"][0].path, path)

    def test_unregistered_tag_fails_validation(self) -> None:
        self.write_card(
            "bad-tag.md",
            title="Bad tag",
            topic="bad-tag",
            source="Codex session 2026-10-25",
            tags=["operations", "troubleshooting", "verified", "invented-tag"],
        )
        result = cairn.validate_vault(self.vault)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("unregistered tags" in error for error in result["errors"])
        )

    def test_slug_topic_is_required(self) -> None:
        self.write_card(
            "bad-topic.md",
            title="Bad topic",
            topic="Bad Topic With Spaces",
            source="Codex session 2026-10-25",
        )
        result = cairn.validate_vault(self.vault)
        self.assertFalse(result["ok"])
        self.assertTrue(any("lowercase ASCII slug" in e for e in result["errors"]))

    def test_promotion_gate_requires_repetition_and_evidence(self) -> None:
        self.write_card(
            "routing-a.md",
            title="Routing evidence A",
            topic="docker-routing",
            source="session-a",
        )
        self.write_card(
            "routing-b.md",
            title="Routing evidence B",
            topic="docker-routing",
            source="session-b",
        )

        validation = cairn.validate_vault(self.vault)
        config = cairn.load_config(self.vault)
        before = cairn.promotion_candidates(validation["cards"], config)
        self.assertFalse(before[0]["eligible"])

        self.write_card(
            "routing-c.md",
            title="Routing evidence C",
            topic="docker-routing",
            source="session-b",
            status="unverified",
        )
        validation = cairn.validate_vault(self.vault)
        after = cairn.promotion_candidates(validation["cards"], config)
        self.assertTrue(after[0]["eligible"])
        self.assertEqual(after[0]["card_count"], 3)
        self.assertEqual(after[0]["verified_cards"], 2)
        self.assertEqual(after[0]["unique_sources"], 2)

    def test_export_skill_draft_and_refuse_overwrite(self) -> None:
        self.write_card(
            "routing-a.md",
            title="Routing evidence A",
            topic="docker-routing",
            source="session-a",
        )
        self.write_card(
            "routing-b.md",
            title="Routing evidence B",
            topic="docker-routing",
            source="session-b",
        )
        self.write_card(
            "routing-c.md",
            title="Routing evidence C",
            topic="docker-routing",
            source="session-b",
        )
        output = self.vault / "30-Skill-Candidates" / "docker-routing.SKILL.md"
        result = cairn.export_skill_draft(self.vault, "docker-routing", output)
        self.assertEqual(result["card_count"], 3)
        content = output.read_text(encoding="utf-8")
        self.assertIn('name: "docker-routing"', content)
        self.assertIn("## Evidence sources", content)
        self.assertIn("- session-a", content)
        self.assertIn("- session-b", content)

        with self.assertRaises(cairn.CairnError):
            cairn.export_skill_draft(self.vault, "docker-routing", output)

    def test_report_write_is_deterministic_aside_from_date(self) -> None:
        self.write_card(
            "routing-a.md",
            title="Routing evidence A",
            topic="docker-routing",
            source="session-a",
        )
        validation = cairn.validate_vault(self.vault)
        config = cairn.load_config(self.vault)
        candidates = cairn.promotion_candidates(validation["cards"], config)
        rendered = cairn.render_candidate_report(candidates)
        self.assertIn("| docker-routing | 1 | 1 | 1 | no |", rendered)
        self.assertIn("needs 3 cards", rendered)

    def test_config_is_valid_json(self) -> None:
        config_path = self.vault / "_config" / "skill-cairn.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["schema_version"], 1)
        self.assertEqual(config["tags"]["verified_status"], "verified")


if __name__ == "__main__":
    unittest.main()

