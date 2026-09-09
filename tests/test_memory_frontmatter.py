#!/usr/bin/env python3
"""The supported frontmatter subset is explicit and independent of its writer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import memory_frontmatter


class MemoryFrontmatterTests(unittest.TestCase):
    def test_parses_scalar_quotes_comments_and_lists_from_a_handwritten_fixture(self) -> None:
        text = '''---
# This comment is not metadata.
name: 'Writer''s note'
description: "A comma, a # hash and an escaped \\"quote\\"" # outside comment
custom: [AGENTS.md, "docs/a,b.md", 'it''s here', "back\\\\slash"]
optional:
metadata: # mapping comment
  type: workflow
  review_after: null
  superseded_by: ~
  scope: []
  evidence_refs:
    - AGENTS.md # file
    - "docs/a,b.md"
  unknown_items:
    - 'quoted # value'
    - plain#fragment
---

Body is ordinary Markdown: ---\n'''

        data, body = memory_frontmatter.parse_frontmatter(text)

        self.assertEqual(
            data,
            {
                "name": "Writer's note",
                "description": 'A comma, a # hash and an escaped "quote"',
                "custom": ["AGENTS.md", "docs/a,b.md", "it's here", "back\\slash"],
                "optional": None,
                "metadata": {
                    "type": "workflow",
                    "review_after": None,
                    "superseded_by": None,
                    "scope": [],
                    "evidence_refs": ["AGENTS.md", "docs/a,b.md"],
                    "unknown_items": ["quoted # value", "plain#fragment"],
                },
            },
        )
        self.assertEqual(body, "Body is ordinary Markdown: ---\n")
        self.assertEqual(memory_frontmatter.parse_document(text).data, data)

    def test_lf_and_crlf_parse_to_the_same_values(self) -> None:
        text = "---\nname: 中文\nmetadata:\n  evidence_refs:\n    - AGENTS.md\n---\n\nBody\n"

        lf_data, lf_body = memory_frontmatter.parse_frontmatter(text)
        crlf_data, crlf_body = memory_frontmatter.parse_frontmatter(text.replace("\n", "\r\n"))

        self.assertEqual(crlf_data, lf_data)
        self.assertEqual(crlf_body, lf_body.replace("\n", "\r\n"))

    def test_indentless_lists_and_empty_metadata_are_supported(self) -> None:
        text = "---\nscope:\n- one\n- two\nmetadata:\n  entities:\n  - three\n---\n"

        data, _ = memory_frontmatter.parse_frontmatter(text)

        self.assertEqual(data, {"scope": ["one", "two"], "metadata": {"entities": ["three"]}})
        self.assertEqual(memory_frontmatter.parse_frontmatter("---\nmetadata:\n---\n")[0], {"metadata": {}})

    def test_scalar_types_are_preserved_for_governance_diagnostics(self) -> None:
        data, _ = memory_frontmatter.parse_frontmatter(
            "---\na: true\nb: false\nc: 42\nd: -1.25\ne: 1e3\nf: 'null'\ng: none\n---\n"
        )

        self.assertEqual(data, {"a": True, "b": False, "c": 42, "d": -1.25, "e": 1000.0, "f": "null", "g": None})

    def test_plain_keywords_preserve_unicode_names_and_case_sensitive_text(self) -> None:
        cases = {
            "project": "project",
            "工作流": "工作流",
            "domain_1": "domain_1",
            "None": None,
            "NULL": None,
            "TRUE": True,
            "FALSE": False,
            "TrueRule": "TrueRule",
            "true值": "true值",
            "ＮＵＬＬ": "ＮＵＬＬ",
            "NAÏVE": "NAÏVE",
            "_domain": "_domain",
            "nan": "nan",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                data, _ = memory_frontmatter.parse_frontmatter(f"---\nvalue: {value}\n---\n")
                self.assertEqual(data, {"value": expected})

    def test_legacy_text_is_unchanged_and_delimiters_must_occupy_a_line(self) -> None:
        for text in ("Plain legacy note\n", "--- not a delimiter\nBody\n", "\n---\nname: body\n"):
            with self.subTest(text=text):
                self.assertEqual(memory_frontmatter.parse_frontmatter(text), ({}, text))
        with self.assertRaisesRegex(ValueError, r"line 1.*not terminated"):
            memory_frontmatter.parse_frontmatter("---\nname: a\n--- trailing text\n")

    def test_unsupported_yaml_and_duplicate_keys_have_line_diagnostics(self) -> None:
        cases = [
            ("name: a\nname: b", 3, "duplicate"),
            ("metadata:\n  type: project\n  type: workflow", 4, "duplicate"),
            ("metadata:\n\ttype: project", 3, "tab"),
            ("description: |\n  multiline", 2, "block scalar"),
            ("description: >-\n  multiline", 2, "block scalar"),
            ("name: &anchor text", 2, "anchor"),
            ("name: *anchor", 2, "alias"),
            ("name: !custom text", 2, "tag"),
            ("custom:\n  nested: object", 3, "mapping"),
            ("metadata:\n  custom:\n    nested: object", 4, "mapping"),
            ("metadata:\n  custom:\n    - key: value", 4, "mapping"),
            ("custom: [{key: value}]", 2, "collection"),
            ("custom: [[nested]]", 2, "collection"),
            ("custom: [prefix{nested}]", 2, "collection"),
            ('name: "unterminated', 2, "quoted"),
            ('name: "quoted" junk', 2, "trailing"),
        ]
        for header, line, reason in cases:
            with self.subTest(header=header):
                for parser in (memory_frontmatter.parse_frontmatter, memory_frontmatter.parse_document):
                    with self.assertRaisesRegex(ValueError, rf"line {line}.*{reason}"):
                        parser(f"---\n{header}\n---\nBody\n")

    def test_a_closing_delimiter_at_end_of_file_is_supported(self) -> None:
        self.assertEqual(memory_frontmatter.parse_frontmatter("---\nname: a\n---"), ({"name": "a"}, ""))


if __name__ == "__main__":
    unittest.main()
