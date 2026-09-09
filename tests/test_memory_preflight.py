"""Behavior cases for the deliberately heuristic preflight gate."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import memory_index


class PreflightBehaviorTests(unittest.TestCase):
    def test_fixed_positive_and_negative_cases_and_acknowledgement(self):
        cases = json.loads((ROOT / "evals/preflight-cases.json").read_text())["cases"]
        self.assertGreaterEqual(len(cases), 6)
        for case in cases:
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                memory = root / "memory"
                memory.mkdir()
                for i, text in enumerate(case["existing"]):
                    (memory / f"{chr(97+i)}.md").write_text(text)
                candidate = memory / "a.md" if case.get("self") else root / "candidate.md"
                candidate.write_text(case["candidate"])
                args = ["preflight", "--memory-dir", str(memory), "--candidate", str(candidate),
                        "--limit", str(case.get("limit", 5))]
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    rc = memory_index.main(args)
                result = json.loads(out.getvalue())
                self.assertEqual(result["assessment_scope"], "heuristic")
                self.assertEqual(result["review_required_files"], case["required"])
                self.assertEqual(rc, 2 if case["required"] else 0)
                self.assertLessEqual(len(result["similar_candidates"]), case.get("limit", 5))
                if "reason" in case:
                    self.assertIn(case["reason"], result["review_reasons"][case["required"][-1]])
                receipt = root / "receipt.json"
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(memory_index.main(args + ["--acknowledge", "--receipt", str(receipt)]), 0)
                acknowledged = json.loads(receipt.read_text())
                self.assertTrue(acknowledged["acknowledged"])
                for key in ("review_reasons", "candidate_hash", "corpus_hash", "blocking"):
                    self.assertEqual(acknowledged[key], result[key])


if __name__ == "__main__":
    unittest.main()
