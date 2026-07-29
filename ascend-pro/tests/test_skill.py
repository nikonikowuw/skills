import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REFERENCES = ROOT / "references"


def load_script(name):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RENDERER = load_script("render-project-baseline.py")
SANITIZER = load_script("sanitize-ascend-evidence.py")
SUMMARIZER = load_script("summarize-stage-latency.py")


class SkillStructureTests(unittest.TestCase):
    def test_frontmatter_is_narrow_and_has_anti_triggers(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = match.group(1)
        self.assertIn("name: ascend-pro", frontmatter)
        self.assertIn("Load when", frontmatter)
        self.assertIn("Do not use", frontmatter)
        self.assertIn("Huawei Ascend", frontmatter)
        self.assertIn("Rockchip/RKNN", frontmatter)
        self.assertNotIn("whenever the user mentions", frontmatter.lower())

    def test_skill_is_a_compact_router(self):
        lines = (ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(lines), 180)

    def test_local_markdown_links_exist(self):
        sources = [ROOT / "SKILL.md", *REFERENCES.glob("*.md")]
        pattern = re.compile(r"\[[^]]+\]\(([^)]+)\)")
        missing = []
        for source in sources:
            for target in pattern.findall(source.read_text(encoding="utf-8")):
                path = target.split("#", 1)[0]
                if not path or re.match(r"^[a-z]+://", path):
                    continue
                if not (source.parent / path).exists():
                    missing.append(f"{source.relative_to(ROOT)} -> {path}")
        self.assertEqual(missing, [])

    def test_obsolete_hazardous_rules_are_gone(self):
        corpus = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [ROOT / "SKILL.md", *REFERENCES.glob("*.md")]
        )
        banned = (
            "stdout_color_mt_st",
            "aclGetRecentErrDesc",
            "within 4 minor versions",
            ".agent/ascend-pro/context/{machine_id}.md",
            "--write-default",
            "aclError aclError",
            "32 bytes (guaranteed)",
            "64-byte alignment",
        )
        for value in banned:
            self.assertNotIn(value, corpus)

    def test_trigger_eval_has_positive_negative_and_edges(self):
        text = (REFERENCES / "skill-evals.md").read_text(encoding="utf-8")
        sections = {}
        for heading in ("Should Trigger", "Should Not Trigger", "Edge Cases"):
            match = re.search(rf"## {heading}\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
            self.assertIsNotNone(match)
            sections[heading] = match.group(1)
        self.assertGreaterEqual(sections["Should Trigger"].count("| `"), 3)
        self.assertGreaterEqual(sections["Should Not Trigger"].count("| `"), 3)
        self.assertGreaterEqual(sections["Edge Cases"].count("| `"), 2)


class SanitizerTests(unittest.TestCase):
    def test_redacts_identifiers_and_is_stable(self):
        raw = (
            "0123456789abcdef0123456789abcdef\n"
            "Machine ID: fedcba9876543210fedcba9876543210\n"
            "Chip Serial: ABCD-1234\n"
            "path=/Users/alice/project ip=192.168.1.20 mac=aa:bb:cc:dd:ee:ff\n"
        )
        first = SANITIZER.sanitize(raw)
        second = SANITIZER.sanitize(raw)
        self.assertEqual(first, second)
        self.assertRegex(first, r"h-[0-9a-f]{12}")
        self.assertRegex(first, r"s-[0-9a-f]{12}")
        self.assertNotIn("0123456789abcdef0123456789abcdef", first)
        self.assertNotIn("fedcba9876543210fedcba9876543210", first)
        self.assertNotIn("ABCD-1234", first)
        self.assertIn("/Users/<user>/project", first)
        self.assertIn("<ip-redacted>", first)
        self.assertIn("<mac-redacted>", first)


class RendererTests(unittest.TestCase):
    def run_renderer(self, *args, cwd=None, input_text=None):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "render-project-baseline.py"), *map(str, args)],
            cwd=cwd or ROOT,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_sample_parsing_uses_evidence_not_source_mentions(self):
        text = (REFERENCES / "sample-device-evidence.txt").read_text(encoding="utf-8")
        draft, contexts = RENDERER.build_draft(text)
        self.assertEqual(len(contexts), 1)
        fields = contexts[0]
        self.assertEqual(fields["atc_version"], "ATC version 8.0.0")
        self.assertEqual(fields["devices"], ["Ascend310P"])
        self.assertIn("aclrtMalloc", fields["symbols"])
        self.assertNotIn("src/infer.cpp: aclrtMalloc", fields["symbols"])
        self.assertNotIn("--soc_version", fields["atc_version"])
        self.assertIn("# Generated Ascend Runtime Context Draft", draft)

    def test_multi_context_does_not_treat_soc_flag_as_observed_device(self):
        text = (REFERENCES / "sample-multi-device-evidence.txt").read_text(encoding="utf-8")
        _, contexts = RENDERER.build_draft(text)
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[0]["devices"], ["Ascend310P"])
        self.assertEqual(contexts[1]["devices"], ["Atlas 200I A2"])
        self.assertEqual(contexts[0]["atc_version"], "ATC version 7.0.RC1")
        self.assertEqual(contexts[1]["atc_version"], "ATC version 6.3.RC2")

    def test_context_label_alone_is_not_runtime_device_evidence(self):
        text = (
            "== Device Context: Ascend310P host ==\n"
            "Host Token: h-111111111111\nDeployment: host\nDevice Index: 0\n"
        )
        _, contexts = RENDERER.build_draft(text)
        self.assertEqual(contexts[0]["devices"], [])

    def test_readelf_needed_line_is_linkage_evidence(self):
        text = "0x0000000000000001 (NEEDED) Shared library: [libascendcl.so]\n"
        fields = RENDERER.context_fields("test", text)
        self.assertEqual(len(fields["linkage"]), 1)

    def test_refuses_raw_machine_id(self):
        for raw in (
            "0123456789abcdef0123456789abcdef\n",
            "Machine ID: 0123456789abcdef0123456789abcdef\n",
        ):
            with self.subTest(raw=raw):
                result = self.run_renderer(input_text=raw)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Raw machine ID detected", result.stderr)

    def test_draft_write_does_not_overwrite_without_force(self):
        sample = REFERENCES / "sample-device-evidence.txt"
        with tempfile.TemporaryDirectory() as tmp:
            first = self.run_renderer(sample, "--write-draft", cwd=tmp)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self.run_renderer(sample, "--write-draft", cwd=tmp)
            self.assertNotEqual(second.returncode, 0)
            forced = self.run_renderer(sample, "--write-draft", "--force", cwd=tmp)
            self.assertEqual(forced.returncode, 0, forced.stderr)
            drafts = list((Path(tmp) / ".agent/ascend-pro/drafts").glob("*.generated.md"))
            self.assertEqual(len(drafts), 1)

    def test_refuses_reviewed_context_directory(self):
        sample = REFERENCES / "sample-device-evidence.txt"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / ".agent/ascend-pro/context/unsafe.md"
            result = self.run_renderer(sample, "-o", output, cwd=tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewed context directory", result.stderr)
            self.assertFalse(output.exists())

    def test_explicit_output_must_be_generated_markdown(self):
        sample = REFERENCES / "sample-device-evidence.txt"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "notes.md"
            result = self.run_renderer(sample, "-o", output, cwd=tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must end with .generated.md", result.stderr)
            self.assertFalse(output.exists())

    def test_write_draft_requires_one_context(self):
        sample = REFERENCES / "sample-multi-device-evidence.txt"
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_renderer(sample, "--write-draft", cwd=tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one labeled context", result.stderr)


class LatencySummaryTests(unittest.TestCase):
    def test_csv_and_legacy_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "timing.csv"
            csv_path.write_text(
                "stage,elapsed_us,frame,extra\ninfer,5000,1,-\ninfer,7000,2,-\n",
                encoding="utf-8",
            )
            legacy_path = Path(tmp) / "timing.log"
            legacy_path.write_text("dvpp=800us\ndvpp: 1.2ms\n", encoding="utf-8")
            self.assertEqual(SUMMARIZER.load_samples(csv_path)["infer"], [5.0, 7.0])
            self.assertEqual(SUMMARIZER.load_samples(legacy_path)["dvpp"], [0.8, 1.2])


class CollectorCliTests(unittest.TestCase):
    def test_requires_explicit_output_and_refuses_existing_path(self):
        script = SCRIPTS / "collect-ascend-debug.sh"
        missing = subprocess.run(["bash", str(script)], text=True, capture_output=True, check=False)
        self.assertEqual(missing.returncode, 2)
        with tempfile.TemporaryDirectory() as tmp:
            existing = subprocess.run(
                ["bash", str(script), "--output", tmp], text=True, capture_output=True, check=False
            )
            self.assertEqual(existing.returncode, 2)
            self.assertIn("Output already exists", existing.stderr)

    def test_collector_creates_sanitized_combined_evidence(self):
        script = SCRIPTS / "collect-ascend-debug.sh"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    "--output",
                    str(output),
                    "--deployment",
                    "host",
                    "--device-index",
                    "0",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            combined = (output / "ascend-evidence.txt").read_text(encoding="utf-8")
            self.assertIn("== Device Context: host device-0 ==", combined)
            self.assertIn("Host Token:", combined)
            self.assertNotRegex(combined, r"(?m)^[0-9a-fA-F]{32}$")

    def test_scripts_are_executable(self):
        for path in SCRIPTS.iterdir():
            if path.suffix in {".py", ".sh"}:
                self.assertTrue(os.access(path, os.X_OK), path.name)


if __name__ == "__main__":
    unittest.main()
