import importlib.util
import os
import re
import subprocess
import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = SKILL_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkillIntegrityTests(unittest.TestCase):
    def test_markdown_links_are_portable_and_resolve(self):
        for markdown in SKILL_ROOT.rglob("*.md"):
            text = markdown.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", text, markdown)
            for target in __import__("re").findall(r"\[[^]]*\]\(([^)#]+)", text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                self.assertTrue((markdown.parent / target).resolve().exists(), (markdown, target))

    def test_eval_schema_and_ids(self):
        data = json.loads((SKILL_ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(data["skill_name"], "ascend-pro")
        ids = [item["id"] for item in data["evals"]]
        self.assertEqual(len(ids), len(set(ids)))
        for item in data["evals"]:
            self.assertTrue(item["prompt"])
            self.assertTrue(item["expected_output"])
            self.assertGreaterEqual(len(item["expectations"]), 3)

        triggers = json.loads((SKILL_ROOT / "evals" / "trigger-evals.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(triggers), 20)
        self.assertTrue(all(isinstance(item.get("query"), str) and item["query"] for item in triggers))
        self.assertTrue(all(isinstance(item.get("should_trigger"), bool) for item in triggers))
        self.assertGreaterEqual(sum(item["should_trigger"] for item in triggers), 8)
        self.assertGreaterEqual(sum(not item["should_trigger"] for item in triggers), 8)

    def test_script_syntax_for_bash_scripts(self):
        for name in ("detect-ascend-env.sh", "collect-ascend-debug.sh"):
            script_path = SKILL_ROOT / "scripts" / name
            run = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, f"{name} syntax error: {run.stderr}")

    def test_machine_id_extraction(self):
        baseline = load_script("render-project-baseline.py")
        text_with_hex_id = "abc123def4567890abc123def4567890\nAscend310P\n"
        self.assertEqual(baseline.extract_machine_id(text_with_hex_id), "abc123def4567890abc123def4567890")

        text_with_chip_sn = "Chip Sn: NPU_SERIAL_1234\nAscend310P\n"
        self.assertEqual(baseline.extract_machine_id(text_with_chip_sn), "NPU_SERIAL_1234")

        text_unknown = "No device identifier present in this log text\n"
        self.assertEqual(baseline.extract_machine_id(text_unknown), "unknown")

    def test_default_output_path(self):
        baseline = load_script("render-project-baseline.py")
        text = "abc123def4567890abc123def4567890\nAscend310P\n"
        path = baseline.choose_default_output_path(text)
        self.assertTrue(str(path).endswith(".agent/ascend-pro/context/abc123def4567890abc123def4567890.md"))

    def test_baseline_deterministic_and_version_sensitive(self):
        baseline = load_script("render-project-baseline.py")
        evidence = """abc123def4567890abc123def4567890
Ascend310P
Linux host 5.10.0 #1
PRETTY_NAME="Ubuntu 22.04"
ATC version: 7.0.0
ASCEND_HOME_PATH=/usr/local/Ascend/ascend-toolkit/latest
libascendcl.so /usr/lib/libascendcl.so
"""
        rendered1 = baseline.build_baseline(evidence)
        rendered2 = baseline.build_baseline(evidence)
        self.assertEqual(rendered1, rendered2)

        different_evidence = evidence.replace("abc123def4567890abc123def4567890", "fff123def4567890abc123def4567890")
        rendered_diff = baseline.build_baseline(different_evidence)
        self.assertNotEqual(rendered1, rendered_diff)

    def test_missing_machine_id_does_not_prevent_baseline(self):
        baseline = load_script("render-project-baseline.py")
        rendered = baseline.build_baseline("Ascend310P\nLinux host 5.10.0\n")
        self.assertIn("Machine ID: unknown", rendered)
        self.assertIn("Open risks", rendered)

    def test_baseline_parses_sample_device_evidence(self):
        baseline = load_script("render-project-baseline.py")
        sample_path = SKILL_ROOT / "references" / "sample-device-evidence.txt"
        evidence = sample_path.read_text(encoding="utf-8")
        rendered = baseline.build_baseline(evidence)
        self.assertIn("Ascend310P", rendered)
        self.assertIn("libascendcl", rendered)

    def test_baseline_handles_multi_device_context_blocks(self):
        baseline = load_script("render-project-baseline.py")
        multi_evidence = """== Device Context: Ascend310P Host ==
Ascend310P
abc123def4567890abc123def4567890

== Device Context: Atlas 200I A2 Container ==
Atlas 200I A2
fedcba0987654321fedcba0987654321
"""
        contexts = baseline.split_device_contexts(multi_evidence)
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[0][0], "Ascend310P Host")
        self.assertEqual(contexts[1][0], "Atlas 200I A2 Container")

    def test_latency_cli_supports_help_and_samples(self):
        script = SKILL_ROOT / "scripts" / "summarize-stage-latency.py"
        help_run = subprocess.run(["python3", str(script), "--help"], capture_output=True, text=True)
        self.assertEqual(help_run.returncode, 0, help_run.stderr)

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write("infer=5.0ms\ndvpp: 800us\ninfer=7.0ms\n")
            handle.flush()
            run = subprocess.run(["python3", str(script), handle.name], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("infer,2,6.000", run.stdout)
        self.assertIn("dvpp,1,0.800", run.stdout)

    def test_baseline_parses_cann8_libraries_and_symbols(self):
        baseline = load_script("render-project-baseline.py")
        evidence = """abc123def4567890abc123def4567890
Ascend310B4
/usr/local/Ascend/ascend-toolkit/latest/lib64/libascend_hal.so
/usr/local/Ascend/ascend-toolkit/latest/lib64/libhi_mpi_vpc.so
hi_mpi_vpc_resize
aclrtMallocAlign32
aclnnMatMul
"""
        rendered = baseline.build_baseline(evidence)
        self.assertIn("libascend_hal", rendered)
        self.assertIn("libhi_mpi_vpc", rendered)
        self.assertIn("aclrtMallocAlign32", rendered)
        self.assertIn("aclnnMatMul", rendered)

    def test_skill_contains_expected_sections(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        description = skill.split("---", 2)[1].lower()
        for term in ("ascend", "dvpp", "aipp", "atc", "ascendcl", "npu", "zero-copy"):
            self.assertIn(term, description)
        self.assertIn("Session Start: Device Identity Verification", skill)
        self.assertIn("context.md Document Format", skill)
        self.assertIn("Debugging and Logging", skill)


if __name__ == "__main__":
    unittest.main()
