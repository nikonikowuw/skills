import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
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
        self.assertEqual(data["skill_name"], "rknn-pro")
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

    def test_environment_fingerprint_is_stable_and_version_sensitive(self):
        baseline = load_script("render-project-baseline.py")
        evidence = """Serial : abcdef1234567890
rockchip,rk3588
Linux board 6.1.0 #1
PRETTY_NAME=\"Test OS\"
librknnrt.so /usr/lib/librknnrt.so
API version: 2.3.2
"""
        first = baseline.environment_fingerprint(evidence)
        self.assertEqual(first, baseline.environment_fingerprint(evidence))
        self.assertNotEqual(first, baseline.environment_fingerprint(evidence.replace("2.3.2", "2.3.3")))
        rendered = baseline.build_baseline(evidence)
        self.assertIn("Device identifier: abcdef1234567890", rendered)
        self.assertIn(f"Environment fingerprint: {first}", rendered)

    def test_missing_serial_does_not_prevent_baseline(self):
        baseline = load_script("render-project-baseline.py")
        rendered = baseline.build_baseline("rockchip,rk3568\nLinux board 6.1.0 #1\n")
        self.assertIn("Device identifier: unknown", rendered)
        self.assertIn("Environment fingerprint:", rendered)

    def test_baseline_parses_driver_device_fallback_and_library_directories(self):
        baseline = load_script("render-project-baseline.py")
        evidence = """$ board serial candidates
board-lab-7
rga_api version 1.10.1_[2]
RGA driver version: 1.2.10
/usr/lib/librga.so
/usr/lib/librknnrt.so.2
target_link_libraries(app PRIVATE /opt/rk/lib/libmpp.so)
"""
        self.assertEqual(baseline.detect_device_id(evidence), "board-lab-7")
        self.assertEqual(baseline.first_match(baseline.RGA_DRIVER_PATTERN, evidence), "1.2.10")
        self.assertEqual(baseline.detect_library_roots(evidence), ["/usr/lib", "/opt/rk/lib"])
        rendered = baseline.build_baseline(evidence)
        self.assertIn("RGA driver: 1.2.10", rendered)
        self.assertNotIn("Library roots: /usr/lib/librga.so", rendered)

    @unittest.skipUnless(shutil.which("gcc"), "gcc is required for preprocessing regression coverage")
    def test_preprocess_maps_macro_findings_to_source_and_excludes_headers(self):
        audit = load_script("audit-rockchip-memory-safety.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "vendor.h").write_text(
                "static void vendor_copy(void *d, void *s, int n) { memcpy(d, s, n); }\n",
                encoding="utf-8",
            )
            source = root / "sample.c"
            source.write_text(
                '#include "vendor.h"\n'
                '#define COPY(d, s, n) memcpy((d), (s), (n))\n'
                'void run(void *dst, void *src, int rows, int cols)\n'
                '{\n'
                '    COPY(dst, src, rows * cols);\n'
                '}\n',
                encoding="utf-8",
            )

            result = audit.preprocess_file(source, include_dirs=[root])
            self.assertIsNotNone(result)
            expanded, line_map = result
            inventory = Counter()
            findings = []
            audit.scan_file(Path("sample.c"), expanded, inventory, findings, line_map=line_map)

        self.assertEqual(inventory["memcpy"], 1, "included header bodies must not be attributed to sample.c")
        copy_finding = next(item for item in findings if item.rule_id == "MEM002")
        self.assertEqual(copy_finding.line, 5)
        self.assertEqual(copy_finding.priority, "high")

    def test_sensitive_evidence_collector_refuses_existing_directory(self):
        script = SKILL_ROOT / "scripts" / "collect-rockchip-crash-evidence.sh"
        with tempfile.TemporaryDirectory() as existing:
            run = subprocess.run(["bash", str(script), "", existing], capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertIn("refusing to overwrite", run.stderr)

    def test_skill_routes_without_forcing_board_access_and_documents_async_semantics(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        description = skill.split("---", 2)[1].lower()
        for term in ("rknn", "rga", "mpp", "dma-buf", "stride", "crashes"):
            self.assertIn(term, description)
        self.assertIn("Source-only review", skill)
        self.assertIn("previous-frame output semantics", skill)

        scheduling = (SKILL_ROOT / "references" / "multi-model-scheduling.md").read_text(encoding="utf-8")
        self.assertIn("previous frame rather than the current frame", scheduling)
        self.assertNotIn("Below is a complete example", scheduling)

    def test_model_conversion_evidence_gate_rejects_inference_from_runtime_io(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        conversion = (SKILL_ROOT / "references" / "model-conversion.md").read_text(
            encoding="utf-8"
        )
        manifest = (SKILL_ROOT / "references" / "model-conversion-manifest.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Model Conversion Evidence Gate", skill)
        self.assertIn("all three possible normalization locations", skill)
        self.assertIn("do_quantization=True` proves only what was requested", skill)
        self.assertIn("If only a `.rknn` file", skill)
        self.assertIn("Missing ONNX identity and contract fields by name", skill)
        self.assertIn("Work that may continue now", skill)
        self.assertIn("ONNX graph", conversion)
        self.assertIn("Toolkit2 conversion", conversion)
        self.assertIn("Application/RGA side", conversion)
        self.assertIn("An unknown is not an absence", conversion)
        self.assertIn("confirmed-present", manifest)
        self.assertIn("Actual graph/layer precision", manifest)

    def test_onnx_inspector_missing_dependency_is_actionable(self):
        dependency_probe = subprocess.run(
            [sys.executable, "-S", "-c", "import onnx"], capture_output=True, text=True
        )
        if dependency_probe.returncode == 0:
            self.skipTest("onnx remains importable with site initialization disabled")

        script = SKILL_ROOT / "scripts" / "inspect-onnx-model.py"
        with tempfile.NamedTemporaryFile(suffix=".onnx") as handle:
            run = subprocess.run(
                [sys.executable, "-S", str(script), handle.name],
                capture_output=True,
                text=True,
            )
        self.assertEqual(run.returncode, 2)
        self.assertIn("optional dependency 'onnx'", run.stderr)
        self.assertIn("python3 -m pip install onnx", run.stderr)

    def test_onnx_inspector_reports_contract_metadata_and_candidates(self):
        try:
            import onnx
            from onnx import TensorProto, helper
        except ImportError:
            self.skipTest("onnx is not installed")

        script = SKILL_ROOT / "scripts" / "inspect-onnx-model.py"
        input_info = helper.make_tensor_value_info(
            "images", TensorProto.FLOAT, [1, 3, "height", "width"]
        )
        output_info = helper.make_tensor_value_info(
            "normalized", TensorProto.FLOAT, [1, 3, "height", "width"]
        )
        scale = helper.make_tensor("scale", TensorProto.FLOAT, [1], [255.0])
        divide = helper.make_node("Div", ["images", "scale"], ["normalized"], name="scale_input")
        graph = helper.make_graph([divide], "normalization-test", [input_info], [output_info], [scale])
        model = helper.make_model(
            graph,
            producer_name="rknn-pro-test",
            opset_imports=[helper.make_opsetid("", 13)],
        )
        metadata = model.metadata_props.add()
        metadata.key = "training_input"
        metadata.value = "RGB [0,255]"

        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "model.onnx"
            onnx.save(model, str(model_path))
            run = subprocess.run(
                [sys.executable, str(script), str(model_path), "--format", "json"],
                capture_output=True,
                text=True,
            )

        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(len(report["artifact"]["sha256"]), 64)
        self.assertEqual(report["model"]["opsets"], [{"domain": "ai.onnx", "version": 13}])
        self.assertEqual(report["model"]["metadata"]["training_input"], "RGB [0,255]")
        self.assertEqual(report["graph"]["inputs"][0]["shape"], [1, 3, "height", "width"])
        self.assertEqual(
            report["graph"]["initializers"][0],
            {"name": "scale", "dtype": "FLOAT", "shape": [1], "external_data": {}},
        )
        candidate = report["preprocessing_candidates"][0]
        self.assertEqual(candidate["op_type"], "Div")
        self.assertEqual(candidate["constant_inputs"][0]["sample"], [255.0])
        self.assertIn("cannot confirm", " ".join(report["limitations"]))

    def test_latency_cli_supports_help_and_samples(self):
        script = SKILL_ROOT / "scripts" / "summarize-stage-latency.py"
        help_run = subprocess.run(["python3", str(script), "--help"], capture_output=True, text=True)
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write("infer=5.0ms\nrga: 800us\ninfer=7.0ms\n")
            handle.flush()
            run = subprocess.run(["python3", str(script), handle.name], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("infer,2,6.000", run.stdout)
        self.assertIn("rga,1,0.800", run.stdout)


if __name__ == "__main__":
    unittest.main()
