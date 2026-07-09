#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path


DEFAULT_OUTPUT_CANDIDATES = (
    ".agents/ascend-context.md",
    ".agent-context/ascend-baseline.md",
    "docs/ascend-baseline.md",
)

LIB_PATTERNS = {
    "libascendcl": re.compile(r"(?P<path>/[^\s]*libascendcl\.so[^\s]*)"),
    "libacl_dvpp": re.compile(r"(?P<path>/[^\s]*libacl_dvpp\.so[^\s]*)"),
    "libacl_op_compiler": re.compile(r"(?P<path>/[^\s]*libacl_op_compiler\.so[^\s]*)"),
    "libge_runner": re.compile(r"(?P<path>/[^\s]*libge_runner\.so[^\s]*)"),
}

SYMBOL_GROUPS = {
    "runtime": ("aclInit", "aclFinalize", "aclrtSetDevice", "aclrtCreateContext", "aclrtCreateStream"),
    "memory": ("aclrtMalloc", "aclrtFree", "aclrtMemcpy", "aclrtMemcpyAsync"),
    "model": ("aclmdlLoadFromFile", "aclmdlExecute", "aclmdlExecuteAsync", "aclmdlCreateDataset"),
    "dvpp": ("acldvppCreateChannel", "acldvppJpegDecodeAsync", "acldvppVpcResizeAsync", "acldvppVpcCropAndPasteAsync"),
}

NODE_PATTERN = re.compile(r"/dev/(?:davinci\d+|davinci_manager|devmm_svm|hisi_hdc)")
HEADER_PATTERN = re.compile(r"(?:(?:-I)|include_directories\(|target_include_directories\()[^)\\\n]*", re.IGNORECASE)
LIBROOT_PATTERN = re.compile(r"(?:(?:-L)|link_directories\(|target_link_directories\()[^)\\\n]*", re.IGNORECASE)
SDK_PATH_PATTERN = re.compile(r"(/[^\s'\"()]*?(?:Ascend|ascend|CANN|cann|acl|ACL)[^\s'\"()]*)")
DL_PATTERN = re.compile(r"\bdlopen\b|RTLD_", re.IGNORECASE)
OS_RELEASE_PATTERN = re.compile(r'PRETTY_NAME="?([^"\n]+)"?')
KERNEL_PATTERN = re.compile(r"^Linux\s+.+", re.MULTILINE)
DEVICE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(Ascend\s*\d+[A-Za-z0-9]*|Atlas\s*200I(?:\s|-)?A2|Atlas\s*(?:300|500|800|900|A\d+)[A-Za-z0-9_-]*)(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
ATC_PATTERN = re.compile(r"(?:ATC|atc)[^\n]*(?:version|Version)[^\n]*", re.IGNORECASE)
CANN_ROOT_PATTERN = re.compile(r"(?:ASCEND_HOME_PATH|ASCEND_TOOLKIT_HOME)=([^\n]*)")
CHIP_SN_PATTERN = re.compile(r"Chip\s*Sn[\s:]*(\w+)", re.IGNORECASE)
SERIAL_PATTERN = re.compile(r"Serial\s*(?:Number|No\.?)[\s:]*(\w+)", re.IGNORECASE)
OM_PATTERN = re.compile(r"(?P<path>[^\s'\"()]+\.om)\b")
AIPP_PATTERN = re.compile(r"(?P<path>[^\s'\"()]*aipp[^\s'\"()]*\.(?:cfg|conf|ini))\b", re.IGNORECASE)
CONTEXT_HEADER_PATTERN = re.compile(r"^==\s*Device Context:\s*(?P<label>.+?)\s*==\s*$", re.IGNORECASE | re.MULTILINE)


def load_text(path_arg):
    if path_arg:
        return Path(path_arg).read_text(encoding="utf-8", errors="replace")
    return sys.stdin.read()


def choose_default_output_path():
    cwd = Path.cwd()
    for candidate in DEFAULT_OUTPUT_CANDIDATES:
        path = cwd / candidate
        parent = path.parent
        if parent.exists() and parent.is_dir():
            return path
    return cwd / DEFAULT_OUTPUT_CANDIDATES[0]


def first_match(pattern, text, group=1, default="unknown"):
    match = pattern.search(text)
    if not match:
        return default
    if isinstance(group, int) and match.lastindex is None and group != 0:
        return match.group(0).strip()
    if isinstance(group, str):
        return match.group(group).strip()
    return match.group(group).strip()


def collect_unique(pattern, text, group=0):
    seen = []
    for match in pattern.finditer(text):
        value = match.group(group).strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def split_device_contexts(text):
    matches = list(CONTEXT_HEADER_PATTERN.finditer(text))
    contexts = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = re.sub(r"\s+", " ", match.group("label")).strip()
        block = text[start:end].strip()
        if label and block:
            contexts.append((label, block))
    return contexts


def detect_devices(text):
    values = collect_unique(DEVICE_PATTERN, text, 1)
    normalized = []
    for value in values:
        compact = re.sub(r"\s+", " ", value).strip()
        if compact.lower() not in [item.lower() for item in normalized]:
            normalized.append(compact)
    return normalized


def detect_libraries(text):
    result = {}
    for name, pattern in LIB_PATTERNS.items():
        matches = collect_unique(pattern, text, "path")
        result[name] = matches or ["not found in pasted evidence"]
    return result


def detect_symbols(text):
    found = {}
    for group, names in SYMBOL_GROUPS.items():
        present = [name for name in names if re.search(rf"\b{re.escape(name)}\b", text)]
        found[group] = present
    return found


def detect_runtime_loading(text):
    return "uses dlopen or RTLD patterns" if DL_PATTERN.search(text) else "no dynamic loading clues found"


def detect_library_roots(text):
    roots = collect_unique(LIBROOT_PATTERN, text)
    roots.extend(path for path in collect_unique(SDK_PATH_PATTERN, text) if "/lib" in path.lower())
    return roots[:8]


def detect_header_roots(text):
    roots = collect_unique(HEADER_PATTERN, text)
    roots.extend(path for path in collect_unique(SDK_PATH_PATTERN, text) if "/include" in path.lower())
    return roots[:8]


def summarize_list(values):
    return ", ".join(values) if values else "unknown"


def summarize_context(label, text):
    libraries = detect_libraries(text)
    symbols = detect_symbols(text)
    devices = detect_devices(text)
    nodes = collect_unique(NODE_PATTERN, text)
    cann_roots = collect_unique(CANN_ROOT_PATTERN, text, 1)
    om_files = collect_unique(OM_PATTERN, text, "path")[:10]
    aipp_files = collect_unique(AIPP_PATTERN, text, "path")[:10]

    return [
        f"### {label}",
        f"- Device model candidates: {summarize_list(devices)}",
        f"- Device nodes: {summarize_list(nodes)}",
        f"- CANN roots: {summarize_list(cann_roots)}",
        f"- libascendcl: {summarize_list(libraries['libascendcl'])}",
        f"- libacl_dvpp: {summarize_list(libraries['libacl_dvpp'])}",
        f"- Header roots: {summarize_list(detect_header_roots(text))}",
        f"- Library roots: {summarize_list(detect_library_roots(text))}",
        f"- Runtime loading behavior: {detect_runtime_loading(text)}",
        f"- ACL runtime symbols present: {summarize_list(symbols['runtime'])}",
        f"- ACL model symbols present: {summarize_list(symbols['model'])}",
        f"- DVPP symbols present: {summarize_list(symbols['dvpp'])}",
        f"- OM files: {summarize_list(om_files)}",
        f"- AIPP config files: {summarize_list(aipp_files)}",
    ]


def build_baseline(text):
    libraries = detect_libraries(text)
    symbols = detect_symbols(text)
    devices = detect_devices(text)
    nodes = collect_unique(NODE_PATTERN, text)
    sdk_paths = collect_unique(SDK_PATH_PATTERN, text)[:10]
    cann_roots = collect_unique(CANN_ROOT_PATTERN, text, 1)
    om_files = collect_unique(OM_PATTERN, text, "path")[:10]
    aipp_files = collect_unique(AIPP_PATTERN, text, "path")[:10]
    context_blocks = split_device_contexts(text)

    kernel = first_match(KERNEL_PATTERN, text)
    os_release = first_match(OS_RELEASE_PATTERN, text)
    atc_version = first_match(ATC_PATTERN, text, 0)
    chip_sn = first_match(CHIP_SN_PATTERN, text)
    if chip_sn == "unknown":
        chip_sn = first_match(SERIAL_PATTERN, text)

    open_risks = []
    if chip_sn == "unknown":
        open_risks.append("Chip serial number not found. Run 'npu-smi info -t board' to get chip_sn.")
    if not devices:
        open_risks.append("Device model not identified from pasted evidence.")
    if kernel == "unknown":
        open_risks.append("Kernel version not identified.")
    if not nodes:
        open_risks.append("Ascend device nodes were not observed.")
    if not cann_roots:
        open_risks.append("CANN root environment variables were not observed.")
    if any("not found" in item for item in libraries["libascendcl"]):
        open_risks.append("No libascendcl path found in pasted evidence.")
    if not symbols["runtime"]:
        open_risks.append("Required ACL runtime symbols were not observed in pasted symbol dumps.")
    if not symbols["model"]:
        open_risks.append("Required ACL model symbols were not observed in pasted symbol dumps.")
    if not om_files:
        open_risks.append("No OM model artifact was observed; conversion provenance remains unknown.")
    if len(devices) > 1 and not context_blocks:
        open_risks.append("Multiple device models were observed without labeled Device Context blocks; do not merge their .so, header, symbol, or OM facts.")

    lines = [
        "Project baseline",
        "",
        "Active device context",
        "- Active context ID: not selected",
        "- Rule: select one device-scoped context before implementation unless the task is explicitly multi-device support.",
        "- Aggregated discovery sections below are not implementation context when multiple devices or CANN roots exist; use the device-scoped runtime context section.",
        "",
        "Device baseline",
        f"- Chip serial number: {chip_sn}  (unique hardware identifier; context key)",
        f"- Device model candidates: {summarize_list(devices)}",
        f"- Device nodes: {summarize_list(nodes)}",
        "",
        "Kernel and OS baseline",
        f"- Kernel: {kernel}",
        f"- OS release: {os_release}",
        "- Driver and firmware: unknown unless explicitly shown by npu-smi output",
        "",
        "CANN and tool baseline",
        f"- CANN roots: {summarize_list(cann_roots)}",
        f"- ATC version: {atc_version}",
        "- CANN package provenance: unknown from pasted evidence",
        "",
        "Userspace library sightings",
        f"- libascendcl: {summarize_list(libraries['libascendcl'])}",
        f"- libacl_dvpp: {summarize_list(libraries['libacl_dvpp'])}",
        f"- libacl_op_compiler: {summarize_list(libraries['libacl_op_compiler'])}",
        f"- libge_runner: {summarize_list(libraries['libge_runner'])}",
        "- Which copy the project actually uses: unknown from pasted evidence",
        "- Rule: treat these as discovery sightings only until tied to one device-scoped context.",
        "",
        "ABI and symbol baseline",
        f"- ACL runtime symbols present: {summarize_list(symbols['runtime'])}",
        f"- ACL memory symbols present: {summarize_list(symbols['memory'])}",
        f"- ACL model symbols present: {summarize_list(symbols['model'])}",
        f"- DVPP symbols present: {summarize_list(symbols['dvpp'])}",
        "- Any symbol mismatches: unknown; inspect absent symbols against intended integration",
        "",
        "Project link and include baseline",
        f"- Header roots: {summarize_list(detect_header_roots(text))}",
        f"- Library roots: {summarize_list(detect_library_roots(text))}",
        f"- Bundled or mounted Ascend SDK paths: {summarize_list(sdk_paths)}",
        f"- Runtime loading behavior: {detect_runtime_loading(text)}",
        "",
        "Model artifact baseline",
        f"- OM files: {summarize_list(om_files)}",
        f"- AIPP config files: {summarize_list(aipp_files)}",
        "- Conversion command and logs: unknown unless explicitly included",
        "",
        "Device-scoped runtime contexts",
    ]

    if context_blocks:
        for label, block in context_blocks:
            lines.extend(summarize_context(label, block))
            lines.append("")
        lines.extend([
            "Context passing rule",
            "- Pass only the selected device context block to future agents or turns by default.",
            "- Mention other context IDs separately; do not merge their `.so`, headers, symbols, or OM artifacts.",
            "",
        ])
    else:
        lines.extend([
            "- No labeled `== Device Context: ... ==` blocks found.",
            "- If this evidence covers more than one device model, ask the user to relabel the paste before using library or model facts.",
            "",
        ])

    lines.extend([
        "Open risks",
    ])

    if open_risks:
        lines.extend(f"- {risk}" for risk in open_risks)
    else:
        lines.append("- No obvious gaps detected in pasted evidence; still verify project-specific API usage.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Render an Ascend project baseline from pasted device evidence.")
    parser.add_argument("input", nargs="?", help="Optional text file containing pasted device evidence. Reads stdin if omitted.")
    parser.add_argument("-o", "--output", help="Optional markdown output file path.")
    parser.add_argument("--write-default", action="store_true", help="Write to the recommended project path. Prefers .agent-context/ascend-baseline.md, then docs/ascend-baseline.md.")
    args = parser.parse_args()

    text = load_text(args.input)
    if not text.strip():
        print("No input provided. Pass a file path or pipe pasted device evidence on stdin.", file=sys.stderr)
        return 1

    baseline = build_baseline(text)
    if args.output and args.write_default:
        print("Use either --output or --write-default, not both.", file=sys.stderr)
        return 1

    output_path = None
    if args.output:
        output_path = Path(args.output)
    elif args.write_default:
        output_path = choose_default_output_path()

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(baseline + "\n", encoding="utf-8")
        print(f"Wrote baseline to {output_path}")
        return 0

    print(baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
