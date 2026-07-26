#!/usr/bin/env python3
import argparse
import hashlib
import re
import sys
from pathlib import Path

DEFAULT_OUTPUT_CANDIDATES = (
    ".agents/rknn-context.md",
    ".agent-context/rockchip-baseline.md",
    "docs/rockchip-baseline.md",
)


LIB_PATTERNS = {
    "librga": re.compile(r"(?P<path>/[^\s'\"()]*librga\.so[^\s'\"()]*)"),
    "librknnrt": re.compile(r"(?P<path>/[^\s'\"()]*librknnrt\.so[^\s'\"()]*)"),
    "libmpp": re.compile(r"(?P<path>/[^\s'\"()]*(?:libmpp\.so|librockchip_mpp\.so)[^\s'\"()]*)"),
}

SYMBOL_GROUPS = {
    "rga": ("importbuffer_fd", "wrapbuffer_fd", "imcheck", "imresize", "imcrop"),
    "rknn": ("rknn_init", "rknn_run", "rknn_inputs_set", "rknn_query", "rknn_outputs_get"),
    "mpp": ("mpp_create", "mpp_init", "mpp_buffer_group_get_internal", "mpp_buffer_import"),
}

MODULE_PATTERN = re.compile(r"^(rockchip\S*|rga\S*|mpp\S*|vcodec\S*|rknpu\S*|iep\S*)\b", re.MULTILINE)
NODE_PATTERN = re.compile(r"/dev/(?:media\d+|video\d+|rga|dri/renderD\d+)")
HEADER_PATTERN = re.compile(r"(?:(?:-I)|include_directories\(|target_include_directories\()[^)\\\n]*", re.IGNORECASE)
LIBROOT_PATTERN = re.compile(r"(?:(?:-L)|link_directories\(|target_link_directories\()[^)\\\n]*", re.IGNORECASE)
SDK_PATH_PATTERN = re.compile(r"(/[^\s'\"()]*?(?:rknn|rockchip|rga|mpp|sdk)[^\s'\"()]*)", re.IGNORECASE)
ABS_PATH_PATTERN = re.compile(r"/[^\s'\"()]+")
VERSION_LINE_PATTERN = re.compile(
    r"^.*(?:api\s+version|driver\s+version|librknnrt|rknnrt\s+version|rga_api|mpp\s+version).*$",
    re.IGNORECASE | re.MULTILINE,
)
DL_PATTERN = re.compile(r"\bdlopen\b|RTLD_", re.IGNORECASE)
OS_RELEASE_PATTERN = re.compile(r'PRETTY_NAME="?([^"\n]+)"?')
COMPATIBLE_PATTERN = re.compile(r"(?:^|\n)(?:rockchip,[^\x00\n]+(?:\x00[^\x00\n]+)*)")
KERNEL_PATTERN = re.compile(r"^Linux\s+.+", re.MULTILINE)
SOC_PATTERN = re.compile(r"\b(rk(?:3576|3568|3566|3588|3588s|3562|3562j|3562g))\b", re.IGNORECASE)
RGA_DRIVER_PATTERN = re.compile(
    r"^(?:rga(?:\s+driver)?|rga\d*_driver)\s+version[ \t]*:[ \t]*([^\r\n]+)$",
    re.IGNORECASE | re.MULTILINE,
)
DEVICE_ID_PATTERN = re.compile(
    r"^(?:Board\s+Serial|Serial|Device\s+ID)\s*:\s*([^\s\x00]+)",
    re.IGNORECASE | re.MULTILINE,
)
DIAG_BARE_DEVICE_ID_PATTERN = re.compile(
    r"^\$\s+board serial candidates\s*$\n(?P<device_id>[^\s\x00]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
RKNN_MODEL_PATTERN = re.compile(r"(?P<path>[^\s'\"()]+\.rknn)\b", re.IGNORECASE)
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


def detect_soc(text):
    values = collect_unique(SOC_PATTERN, text, 1)
    deduped = []
    for value in values:
        upper = value.upper()
        if upper not in deduped:
            deduped.append(upper)
    return ", ".join(deduped) if deduped else "unknown"


def detect_board_model(text):
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if "device context" in lowered:
            continue
        if stripped.startswith("/") or stripped.startswith("Linux "):
            continue
        if "version" in lowered and "driver" in lowered:
            continue
        if "\x00" in stripped:
            continue
        if any(token in stripped.lower() for token in ("rockchip", "radxa", "firefly", "orangepi", "rk3568", "rk3576")):
            if not stripped.startswith("/") and len(stripped) < 200:
                return stripped
    return "unknown"


def detect_compatible(text):
    match = COMPATIBLE_PATTERN.search(text)
    if not match:
        return "unknown"
    return match.group(0).replace("\x00", ", ").strip()


def detect_device_id(text):
    labeled = first_match(DEVICE_ID_PATTERN, text)
    if labeled != "unknown":
        return labeled
    match = DIAG_BARE_DEVICE_ID_PATTERN.search(text)
    return match.group("device_id").strip() if match else "unknown"


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
    roots = []
    for directive in collect_unique(LIBROOT_PATTERN, text):
        roots.extend(collect_unique(ABS_PATH_PATTERN, directive))
    for path in collect_unique(SDK_PATH_PATTERN, text):
        if "/lib" not in path.lower():
            continue
        cleaned = path.rstrip(",;")
        if re.search(r"\.so(?:\.[^/]*)?$", cleaned, re.IGNORECASE):
            cleaned = str(Path(cleaned).parent)
        roots.append(cleaned)
    return list(dict.fromkeys(roots))[:6]


def detect_header_roots(text):
    roots = []
    for directive in collect_unique(HEADER_PATTERN, text):
        roots.extend(collect_unique(ABS_PATH_PATTERN, directive))
    roots.extend(path for path in collect_unique(SDK_PATH_PATTERN, text) if "/include" in path.lower())
    return list(dict.fromkeys(roots))[:6]


def summarize_list(values):
    return ", ".join(values) if values else "unknown"


def environment_fingerprint(text):
    fields = [
        detect_soc(text),
        first_match(KERNEL_PATTERN, text),
        first_match(OS_RELEASE_PATTERN, text),
        first_match(RGA_DRIVER_PATTERN, text),
        *detect_libraries(text)["librga"],
        *detect_libraries(text)["librknnrt"],
        *detect_libraries(text)["libmpp"],
        *detect_header_roots(text),
        *collect_unique(VERSION_LINE_PATTERN, text),
    ]
    normalized = "\n".join(re.sub(r"\s+", " ", field).strip() for field in fields)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]


def summarize_context(label, text):
    libraries = detect_libraries(text)
    symbols = detect_symbols(text)
    modules = [
        value for value in collect_unique(MODULE_PATTERN, text, 1)
        if "," not in value and not value.startswith("rga_api")
    ]
    nodes = collect_unique(NODE_PATTERN, text)
    media_nodes = [node for node in nodes if "/dev/media" in node or "/dev/video" in node]
    drm_nodes = [node for node in nodes if "/dev/dri/" in node]
    rknn_models = collect_unique(RKNN_MODEL_PATTERN, text, "path")[:10]

    return [
        f"### {label}",
        f"- Device identifier: {detect_device_id(text)}",
        f"- Environment fingerprint: {environment_fingerprint(text)}",
        f"- SoC: {detect_soc(text)}",
        f"- Board model: {detect_board_model(text)}",
        f"- Compatible string: {detect_compatible(text)}",
        f"- RGA driver: {first_match(RGA_DRIVER_PATTERN, text)}",
        f"- V4L2 or media nodes: {summarize_list(media_nodes)}",
        f"- DRM or display nodes: {summarize_list(drm_nodes)}",
        f"- Other relevant modules: {summarize_list(modules)}",
        f"- librga: {summarize_list(libraries['librga'])}",
        f"- librknnrt: {summarize_list(libraries['librknnrt'])}",
        f"- libmpp or librockchip_mpp: {summarize_list(libraries['libmpp'])}",
        f"- Header roots: {summarize_list(detect_header_roots(text))}",
        f"- Library roots: {summarize_list(detect_library_roots(text))}",
        f"- Runtime loading behavior: {detect_runtime_loading(text)}",
        f"- Required RGA symbols present: {summarize_list(symbols['rga'])}",
        f"- Required RKNN symbols present: {summarize_list(symbols['rknn'])}",
        f"- Required MPP symbols present: {summarize_list(symbols['mpp'])}",
        f"- RKNN model artifacts: {summarize_list(rknn_models)}",
    ]


def build_baseline(text):
    libraries = detect_libraries(text)
    symbols = detect_symbols(text)
    device_id = detect_device_id(text)
    fingerprint = environment_fingerprint(text)
    modules = [
        value for value in collect_unique(MODULE_PATTERN, text, 1)
        if "," not in value and not value.startswith("rga_api")
    ]
    nodes = collect_unique(NODE_PATTERN, text)
    media_nodes = [node for node in nodes if "/dev/media" in node or "/dev/video" in node]
    drm_nodes = [node for node in nodes if "/dev/dri/" in node]
    sdk_paths = [
        path for path in collect_unique(SDK_PATH_PATTERN, text)
        if not path.lower().endswith(".rknn") and not path.startswith("/dev/")
    ][:8]
    rknn_models = collect_unique(RKNN_MODEL_PATTERN, text, "path")[:10]
    context_blocks = split_device_contexts(text)

    board_model = detect_board_model(text)
    soc = detect_soc(text)
    compatible = detect_compatible(text)
    kernel = first_match(KERNEL_PATTERN, text)
    os_release = first_match(OS_RELEASE_PATTERN, text)
    rga_driver = first_match(RGA_DRIVER_PATTERN, text)

    open_risks = []
    if device_id == "unknown":
        open_risks.append("No device identifier found. Record a board serial, asset tag, or stable user-provided label when hardware identity matters.")
    if board_model == "unknown":
        open_risks.append("Board model not identified from pasted evidence.")
    if kernel == "unknown":
        open_risks.append("Kernel version not identified.")
    if rga_driver == "unknown":
        open_risks.append("RGA driver version not found; driver and librga compatibility remains unverified.")
    if any("not found" in item for item in libraries["librga"]):
        open_risks.append("No librga path found in pasted evidence.")
    if any("not found" in item for item in libraries["librknnrt"]):
        open_risks.append("No librknnrt path found in pasted evidence.")
    if not symbols["rga"]:
        open_risks.append("Required RGA symbols were not observed in pasted symbol dumps.")
    if not symbols["rknn"]:
        open_risks.append("Required RKNN symbols were not observed in pasted symbol dumps.")
    if len([soc for soc in detect_soc(text).split(", ") if soc != "unknown"]) > 1 and not context_blocks:
        open_risks.append("Multiple Rockchip SoCs were observed without labeled Device Context blocks; do not merge their .so, driver, symbol, or RKNN artifact facts.")

    lines = [
        "Project baseline",
        "",
        "Active device context",
        "- Active context ID: not selected",
        "- Rule: select one device-scoped context before implementation unless the task is explicitly multi-board support.",
        "- Aggregated discovery sections below are not implementation context when multiple boards, SoCs, BSPs, or library roots exist; use the device-scoped runtime context section.",
        "",
        "Board baseline",
        f"- Device identifier: {device_id}",
        f"- Environment fingerprint: {fingerprint}",
        f"- SoC: {soc}",
        f"- Board model: {board_model}",
        f"- Compatible string: {compatible}",
        "",
        "Kernel and BSP baseline",
        f"- Kernel: {kernel}",
        f"- OS release: {os_release}",
        "- BSP or image source: unknown from pasted evidence",
        "",
        "Driver baseline",
        f"- RGA driver: {rga_driver}",
        f"- V4L2 or media nodes: {summarize_list(media_nodes)}",
        f"- DRM or display nodes: {summarize_list(drm_nodes)}",
        f"- Other relevant modules: {summarize_list(modules)}",
        "",
        "Userspace library sightings",
        f"- librga: {summarize_list(libraries['librga'])}",
        f"- librknnrt: {summarize_list(libraries['librknnrt'])}",
        f"- libmpp or librockchip_mpp: {summarize_list(libraries['libmpp'])}",
        "- Which copy the project actually uses: unknown from pasted evidence",
        "- Rule: treat these as discovery sightings only until tied to one device-scoped context.",
        "",
        "ABI and symbol baseline",
        f"- Required RGA symbols present: {summarize_list(symbols['rga'])}",
        f"- Required RKNN symbols present: {summarize_list(symbols['rknn'])}",
        f"- Required MPP symbols present: {summarize_list(symbols['mpp'])}",
        "- Any symbol mismatches: unknown; inspect absent symbols against intended integration",
        "",
        "Project link and include baseline",
        f"- Header roots: {summarize_list(detect_header_roots(text))}",
        f"- Library roots: {summarize_list(detect_library_roots(text))}",
        f"- Bundled vendor SDK paths: {summarize_list(sdk_paths)}",
        f"- Runtime loading behavior: {detect_runtime_loading(text)}",
        "",
        "Model artifact baseline",
        f"- RKNN model artifacts: {summarize_list(rknn_models)}",
        "- Conversion command and toolkit version: unknown unless explicitly included",
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
            "- Mention other context IDs separately; do not merge their `.so`, drivers, headers, symbols, or RKNN artifacts.",
            "",
        ])
    else:
        lines.extend([
            "- No labeled `== Device Context: ... ==` blocks found.",
            "- If this evidence covers more than one board, SoC, BSP, rootfs, or container, ask the user to relabel the paste before using library or model facts.",
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
    parser = argparse.ArgumentParser(description="Render a Rockchip project baseline from pasted device evidence.")
    parser.add_argument("input", nargs="?", help="Optional text file containing pasted device evidence. Reads stdin if omitted.")
    parser.add_argument("-o", "--output", help="Optional markdown output file path.")
    parser.add_argument("--write-default", action="store_true", help="Write to the recommended project path. Prefers .agents/rknn-context.md, then .agent-context/rockchip-baseline.md, then docs/rockchip-baseline.md.")
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
