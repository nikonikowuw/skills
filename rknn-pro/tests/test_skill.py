import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = SKILL_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkillIntegrityTests(unittest.TestCase):
    def test_documented_helpers_are_directly_executable(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"scripts/([A-Za-z0-9_-]+\.(?:py|sh))", skill))
        self.assertIn("run-skill-evals.py", documented)
        for name in documented:
            helper = SKILL_ROOT / "scripts" / name
            self.assertTrue(helper.is_file(), helper)
            self.assertTrue(os.access(helper, os.X_OK), f"documented helper is not executable: {helper}")

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
            self.assertIsInstance(item.get("route"), str)
            self.assertTrue(item["route"])
            for field in ("required_terms", "forbidden_terms"):
                if field in item:
                    self.assertTrue(all(isinstance(value, str) for value in item[field]))
        self.assertGreaterEqual(len({item["route"] for item in data["evals"]}), 5)

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
        reordered = "\n".join(reversed(evidence.strip().splitlines())) + "\n"
        self.assertEqual(first, baseline.environment_fingerprint(reordered))
        self.assertNotEqual(first, baseline.environment_fingerprint(evidence.replace("2.3.2", "2.3.3")))
        rendered = baseline.build_baseline(evidence)
        self.assertIn("Device identifier: abcdef1234567890", rendered)
        self.assertIn(f"Environment fingerprint: {first}", rendered)

    def test_missing_serial_does_not_prevent_baseline(self):
        baseline = load_script("render-project-baseline.py")
        rendered = baseline.build_baseline("rockchip,rk3568\nLinux board 6.1.0 #1\n")
        self.assertIn("Device identifier: unknown", rendered)
        self.assertIn("Environment fingerprint:", rendered)

    def test_machine_id_extraction_and_default_output_path(self):
        baseline = load_script("render-project-baseline.py")
        evidence_with_serial = "Serial : RK3588_SERIAL_12345\nrockchip,rk3588\n"
        self.assertEqual(baseline.extract_machine_id(evidence_with_serial), "rk3588_serial_12345")
        path_serial = baseline.choose_default_output_path(evidence_with_serial)
        self.assertTrue(str(path_serial).endswith(".agents/context/rknn-context/rk3588_serial_12345.md"))

        evidence_no_serial = "rockchip,rk3568\nLinux board 6.1.0 #1\n"
        fingerprint = baseline.environment_fingerprint(evidence_no_serial)
        self.assertEqual(baseline.extract_machine_id(evidence_no_serial), fingerprint)
        path_no_serial = baseline.choose_default_output_path(evidence_no_serial)
        self.assertTrue(str(path_no_serial).endswith(f".agents/context/rknn-context/{fingerprint}.md"))

        path_override = baseline.choose_default_output_path(evidence_with_serial, context_id_override="custom-board-01")
        self.assertTrue(str(path_override).endswith(".agents/context/rknn-context/custom-board-01.md"))

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

    def test_auditor_parses_comparisons_and_checks_each_call_statement(self):
        audit = load_script("audit-rockchip-memory-safety.py")
        source = (
            "void run(void *ctx, unsigned n, unsigned cap, unsigned width, unsigned height) {\n"
            "  calloc(n < cap ? n : cap, width * height);\n"
            "  int prior_status = 0; rknn_run(ctx, 0);\n"
            "  int checked = rknn_run(ctx, 0);\n"
            "}\n"
        )
        inventory = Counter()
        findings = []
        audit.scan_file(Path("sample.c"), source, inventory, findings)

        self.assertTrue(any(item.rule_id == "MEM003" and item.line == 2 for item in findings))
        unchecked = [item for item in findings if item.rule_id == "API001"]
        self.assertEqual([(item.line, item.evidence) for item in unchecked], [(3, "rknn_run(ctx, 0)")])

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

    def test_onnx_inspector_decodes_only_constants_reached_from_input_prefix(self):
        try:
            import onnx
            from onnx import TensorProto, helper, numpy_helper
        except ImportError:
            self.skipTest("onnx is not installed")

        inspector = load_script("inspect-onnx-model.py")
        input_info = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1])
        output_info = helper.make_tensor_value_info("normalized", TensorProto.FLOAT, [1])
        scale = helper.make_tensor("scale", TensorProto.FLOAT, [1], [255.0])
        unused = helper.make_tensor("unused_weights", TensorProto.FLOAT, [1024], [0.0] * 1024)
        divide = helper.make_node("Div", ["images", "scale"], ["normalized"])
        graph = helper.make_graph(
            [divide], "lazy-constant-test", [input_info], [output_info], [scale, unused]
        )
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        decoded = []
        original_to_array = numpy_helper.to_array

        def record_decode(tensor, *args, **kwargs):
            decoded.append(tensor.name)
            return original_to_array(tensor, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "model.onnx"
            onnx.save(model, str(model_path))
            with mock.patch.object(numpy_helper, "to_array", side_effect=record_decode):
                report = inspector.inspect_model(model_path)

        self.assertIn("scale", decoded)
        self.assertNotIn("unused_weights", decoded)
        candidate = report["preprocessing_candidates"][0]
        self.assertEqual(candidate["constant_inputs"][0]["name"], "scale")

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

        stdin_run = subprocess.run(
            [str(script)],
            input="infer=5.0ms\nrga: 800us\ninfer=7.0ms\n",
            capture_output=True,
            text=True,
        )
        self.assertEqual(stdin_run.returncode, 0, stdin_run.stderr)
        self.assertIn("infer,2,6.000", stdin_run.stdout)

    def test_read_only_diagnostic_uses_static_elf_inspection(self):
        script = (SKILL_ROOT / "scripts" / "rknn-diag.sh").read_text(encoding="utf-8")
        self.assertNotRegex(script, r"\bcapture\s+ldd\b")
        self.assertRegex(script, r"\b(?:readelf|objdump)\b")

    def test_reference_contract_regressions_are_absent(self):
        skill_and_references = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [SKILL_ROOT / "SKILL.md", *sorted((SKILL_ROOT / "references").glob("*.md"))]
        )
        for invalid in (
            "IM_HAL_CORE_RGA2",
            "IM_HAL_CORE_RGA3",
            '"hw:core_id"',
            "perf.layer_detail",
            "uint8_t zp",
            "hor_stride * ver_stride * 2",
            "Read only first N bytes",
            "MPP external buffer mode unavailable on old BSP",
            "decoder is stuck in internal or half-internal",
            "running on CPU` — ops that fall back",
        ):
            self.assertNotIn(invalid, skill_and_references)
        self.assertNotRegex(skill_and_references, r"MANDATORY[^\n]*rknn_dup_context")
        self.assertRegex(
            skill_and_references,
            r"rknn_dup_context\(rknn_context\s*\*\s*context_in",
        )
        self.assertIn("w_stride` is read-only", skill_and_references)
        self.assertIn("h_stride` is write-only", skill_and_references)
        self.assertIn("IM_SCHEDULER_RGA3_CORE0", skill_and_references)

        rknn_refs = "\n".join(
            (SKILL_ROOT / "references" / name).read_text(encoding="utf-8")
            for name in ("api-quick-reference.md", "rknn-api-reference.md")
        )
        self.assertNotIn("void *model, size_t size", rknn_refs)
        self.assertNotIn("void *info, size_t info_size", rknn_refs)

        rga = (SKILL_ROOT / "references" / "rga-api-reference.md").read_text(
            encoding="utf-8"
        )
        for capability in ("color fill", "ROP", "mosaic", "OSD", "Gaussian"):
            self.assertIn(capability, rga)

        scheduling = (SKILL_ROOT / "references" / "multi-model-scheduling.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("actual backing allocation's `h_stride`", scheduling)

    def test_eval_runner_executes_a_model_adapter_and_records_raw_output(self):
        runner = SKILL_ROOT / "scripts" / "run-skill-evals.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            stub = Path(temp_dir) / "model.py"
            stub.write_text(
                "import json, sys\n"
                "prompt = sys.stdin.read()\n"
                "if 'Complete the user task below' in prompt:\n"
                "    print('RKNN_TENSOR_FLOAT32 is valid; inspect pass_through and measure conversion.')\n"
                "else:\n"
                "    print(json.dumps({'should_trigger': True, 'reason': 'RKNN task'}))\n",
                encoding="utf-8",
            )
            model_arg = "stub={} {}".format(
                shlex.quote(sys.executable), shlex.quote(str(stub))
            )
            run = subprocess.run(
                [
                    str(runner),
                    "--mode",
                    "triggers",
                    "--limit",
                    "1",
                    "--model",
                    model_arg,
                    "--model",
                    model_arg.replace("stub=", "second=", 1),
                ],
                capture_output=True,
                text=True,
            )
            behavior_run = subprocess.run(
                [
                    str(runner),
                    "--mode",
                    "behavior",
                    "--limit",
                    "1",
                    "--compare-without",
                    "--model",
                    model_arg,
                ],
                capture_output=True,
                text=True,
            )

        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        result = report["models"]["stub"]["triggers"]["results"][0]
        self.assertTrue(result["passed"])
        self.assertIn('"should_trigger": true', result["execution"]["stdout"])
        self.assertTrue(report["models"]["second"]["triggers"]["results"][0]["passed"])

        self.assertEqual(behavior_run.returncode, 0, behavior_run.stderr)
        comparison = json.loads(behavior_run.stdout)["models"]["stub"]["behavior"][
            "comparison"
        ]
        self.assertEqual(comparison["with_skill"]["automated"], 1)
        self.assertEqual(comparison["without_skill"]["automated"], 1)
        self.assertEqual(comparison["pass_rate_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
