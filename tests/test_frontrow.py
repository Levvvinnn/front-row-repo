"""Tests for front-row/scripts/frontrow.py. Run from the repo root: python3 -m unittest discover tests"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "front-row" / "scripts" / "frontrow.py"
spec = importlib.util.spec_from_file_location("frontrow", SCRIPT)
frontrow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontrow)


def run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = frontrow.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


class ScanTest(unittest.TestCase):
    def test_sample_finds_each_kind_of_hint(self):
        result = frontrow.scan(frontrow.SAMPLE_TRANSCRIPT.read_text())
        ranks = {(c["rank"], c["minute"]) for c in result["candidates"]}
        self.assertIn(("direct", 12), ranks)  # "This will be on the midterm"
        self.assertIn(("strong", 31), ranks)  # "People always get this wrong"
        self.assertIn(("skip", 38), ranks)  # "won't be on the exam"
        self.assertEqual(result["timestamps"], "from transcript")
        self.assertIn("krebs cycle", {r["phrase"] for r in result["repeated"]})

    def test_negation_is_a_skip_not_a_hint(self):
        for line in ("That won't be on the exam.", "This is not going to be on the final.",
                     "You don't need to memorize these."):
            self.assertEqual(frontrow.classify(line)[0], "skip", line)

    def test_direct_and_strong_phrases(self):
        self.assertEqual(frontrow.classify("This will definitely be on the midterm.")[0], "direct")
        self.assertEqual(frontrow.classify("I'd study this one.")[0], "direct")
        self.assertEqual(frontrow.classify("Write this down.")[0], "strong")
        self.assertEqual(frontrow.classify("Students always mix these up.")[0], "strong")
        self.assertIsNone(frontrow.classify("The mitochondria has two membranes."))

    def test_minutes_estimated_without_timestamps(self):
        text = ("word " * 1300) + "This will be on the exam."
        result = frontrow.scan(text)
        self.assertEqual(result["candidates"][0]["minute"], 10)
        self.assertIn("estimated", result["timestamps"])


class MatchTest(unittest.TestCase):
    def test_sample_statuses(self):
        result = frontrow.match(json.loads(frontrow.SAMPLE_HINTS.read_text()), frontrow.SAMPLE_MATERIALS)
        status = {h["concept"]: h.get("status") for h in result["hints"]}
        self.assertEqual(status["Krebs cycle products per glucose"], "slides")
        self.assertEqual(status["Fermentation regenerates NAD+"], "only_lecture")
        # The slides never say 30 to 32, so this must not be called "in the slides".
        self.assertNotEqual(status["Total ATP yield per glucose is 30 to 32"], "slides")
        self.assertIsNone(status["Detailed steps of fermentation"])  # skips aren't matched
        self.assertEqual(result["searched"], ["lecture-14-cellular-respiration.md"])

    def test_unreadable_material_blocks_only_lecture(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "slides.md").write_text("Glycolysis happens in the cytoplasm.")
            Path(folder, "deck.key").write_bytes(b"\x00binary")
            result = frontrow.match([{"concept": "Photosystem II", "rank": "direct"}], Path(folder))
        self.assertEqual(result["hints"][0]["status"], "not_checked")
        self.assertTrue(result["unreadable"])

    def test_empty_folder_blocks_only_lecture(self):
        with tempfile.TemporaryDirectory() as folder:
            result = frontrow.match([{"concept": "Photosystem II", "rank": "direct"}], Path(folder))
        self.assertEqual(result["hints"][0]["status"], "not_checked")

    def test_too_many_unclear_drops_the_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "slides.md").write_text("Krebs cycle in the matrix. Glycolysis in the cytoplasm.")
            hints = [{"concept": "Krebs cycle regulation", "rank": "strong"},  # 2 of 3 words: unclear
                     {"concept": "Glycolysis cytoplasm enzymes", "rank": "strong"},  # unclear
                     {"concept": "Photosystem II", "rank": "direct"}]  # nowhere
            result = frontrow.match(hints, Path(folder))
        self.assertTrue(result["only_lecture_dropped"])
        self.assertNotIn("only_lecture", {h["status"] for h in result["hints"]})


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("SKILL_DATA_DIR")
        os.environ["SKILL_DATA_DIR"] = self.tmp.name
        self.hints = Path(self.tmp.name, "hints.json")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("SKILL_DATA_DIR", None)
        else:
            os.environ["SKILL_DATA_DIR"] = self.old
        self.tmp.cleanup()

    def write(self, hints):
        self.hints.write_text(json.dumps(hints))
        return str(self.hints)

    def test_save_list_and_merge_across_lectures(self):
        path = self.write([{"concept": "Krebs cycle", "rank": "strong", "quote": "remember this"},
                           {"concept": "Fermentation steps", "rank": "skip"}])
        self.assertEqual(run("save", "--course", "BIO 181", "--date", "2026-10-14", "--hints", path)[0], 0)
        path = self.write([{"concept": "krebs cycle", "rank": "direct", "status": "slides", "link": "https://x"}])
        self.assertEqual(run("save", "--course", "BIO 181", "--date", "2026-10-21", "--hints", path)[0], 0)

        code, out = run("list", "--course", "BIO 181")
        self.assertEqual(code, 0)
        self.assertIn("[DIRECT] Krebs cycle", out)  # best rank wins
        self.assertIn("said in 2 lectures", out)
        self.assertIn("https://x", out)
        self.assertIn("Said NOT on the exam", out)

        code, out = run("list", "--course", "BIO 181", "--short")
        self.assertNotIn("NOT on the exam", out)

    def test_resaving_a_lecture_replaces_not_duplicates(self):
        path = self.write([{"concept": "ATP yield", "rank": "strong"}])
        run("save", "--course", "CHEM 113", "--date", "2026-10-21", "--hints", path)
        _, out = run("save", "--course", "CHEM 113", "--date", "2026-10-21", "--hints", path)
        self.assertIn("0 new and 1 updated", out)

    def test_bad_input(self):
        self.assertEqual(run("save", "--course", "X", "--date", "Oct 21", "--hints", self.write([]))[0], 2)
        self.assertEqual(run("save", "--course", "X", "--date", "2026-10-21",
                             "--hints", self.write([{"concept": "A", "rank": "maybe"}]))[0], 2)
        self.assertEqual(run("list", "--course", "Nothing Saved")[0], 3)

    def test_sample_save_writes_nothing(self):
        code, out = run("save", "--sample")
        self.assertEqual(code, 0)
        self.assertIn("nothing saved", out)
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])


class CallTest(unittest.TestCase):
    def test_sample_call_reads_direct_hints_and_skip(self):
        code, out = run("call", "--sample", "--exam", "midterm", "--time", "10 AM")
        self.assertEqual(code, 0)
        self.assertIn("Your midterm is at 10 AM.", out)
        self.assertIn("Krebs cycle products per glucose", out)
        self.assertIn("not on the exam", out)
        self.assertNotRegex(out, r"https?://|[()\[\]*#]")

    def test_speakable(self):
        self.assertEqual(frontrow.speakable("Build heap is O(n)"), "Build heap is O of n")
        self.assertEqual(frontrow.speakable("NAD+ see https://canvas.x/1"), "NAD plus see")
        self.assertEqual(frontrow.spoken_list(["a", "b"]), "a and b")
        self.assertEqual(frontrow.spoken_list(["a", "b", "c"]), "a, b, and c")

    def test_no_direct_hints(self):
        store = {"course": "X", "hints": [{"concept": "Y", "rank": "strong", "status": "slides", "date": "2026-10-21"}]}
        self.assertIn("No direct hints", frontrow.call_script(store, "final", None))


@unittest.skipUnless(importlib.util.find_spec("reportlab"), "reportlab not installed")
class PdfTest(unittest.TestCase):
    def test_sample_pdf_is_one_page(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder, "list.pdf")
            checks = Path(folder, "checks.json")
            checks.write_text(json.dumps({"Krebs cycle products per glucose": "How many NADH per glucose?"}))
            code, _ = run("pdf", "--sample", "--exam", "Midterm", "--checks", str(checks), "--out", str(out))
            self.assertEqual(code, 0)
            data = out.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(data.count(b"/Type /Page\n") + data.count(b"/Type /Page "), 1)


if __name__ == "__main__":
    unittest.main()
