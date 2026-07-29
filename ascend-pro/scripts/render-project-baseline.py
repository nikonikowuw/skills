#!/usr/bin/env python3
"""Render a reviewable Ascend runtime-context draft from sanitized evidence."""

import argparse
import hashlib
import re
import sys
from pathlib import Path


RAW_MACHINE_ID_PATTERN = re.compile(
    r"(?im)(?:^[0-9a-f]{32}$|^\s*machine[\s_-]*id\s*[:=]\s*[0-9a-f]{32}\s*$)"
)
HOST_TOKEN_PATTERN = re.compile(r"(?im)^Host Token:\s*(h-[0-9a-f]{8,64})\s*$")
SERIAL_TOKEN_PATTERN = re.compile(
    r"(?im)^(?:NPU )?(?:Serial|Chip Sn|Chip Serial|Board Sn|Board Serial|Device Serial) Token:"
    r"\s*(s-[0-9a-f]{8,64})\s*$"
)
DEVICE_INDEX_PATTERN = re.compile(r"(?im)^Device Index:\s*([0-9]+)\s*$")
DEPLOYMENT_PATTERN = re.compile(r"(?im)^Deployment:\s*([A-Za-z0-9._-]+)\s*$")
COLLECTED_PATTERN = re.compile(r"(?im)^Collected UTC:\s*([^\n]+)")
CONTEXT_HEADER_PATTERN = re.compile(
    r"^==\s*Device Context:\s*(?P<label>.+?)\s*==\s*$", re.IGNORECASE | re.MULTILINE
)
DEVICE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(Ascend\s*\d+[A-Za-z0-9]*|Atlas\s*200I(?:\s|-)?A2|"
    r"Atlas\s*(?:300|500|800|900|A\d+)[A-Za-z0-9_-]*)(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
NODE_PATTERN = re.compile(r"/dev/(?:davinci\d+|davinci_manager|devmm_svm|hisi_hdc)")
OS_RELEASE_PATTERN = re.compile(r'^PRETTY_NAME="?([^"\n]+)"?', re.MULTILINE)
KERNEL_PATTERN = re.compile(r"^Linux\s+.+", re.MULTILINE)
ATC_VERSION_PATTERN = re.compile(
    r"(?im)^(?P<value>(?:ATC|atc)[^\n]*(?:\s|:)(?:version|Version)\b[^\n]*)$"
)
DRIVER_VERSION_PATTERN = re.compile(r"(?im)^\s*Driver(?:\s+Version|_Version)\s*[:=]\s*([^\n]+)")
FIRMWARE_VERSION_PATTERN = re.compile(r"(?im)^\s*Firmware(?:\s+Version|_Version)\s*[:=]\s*([^\n]+)")
CANN_ROOT_PATTERN = re.compile(
    r"(?m)^(?:ASCEND_HOME_PATH|ASCEND_HOME_REALPATH|ASCEND_TOOLKIT_HOME|ASCEND_TOOLKIT_REALPATH)=([^\n]*)"
)
LIB_PATTERN = re.compile(
    r"(?P<path>/[^\s]*?(?:libascendcl|libacl_dvpp|libacl_op_compiler|libge_runner)\.so[^\s]*)"
)
HEADER_PATH_PATTERN = re.compile(r"(?P<path>/[^\s]*(?:acl|acl_rt|acl_mdl|acl_dvpp)\.h)\b")
OM_PATTERN = re.compile(r"(?P<path>[^\s'\"()]+\.om)\b")
AIPP_PATTERN = re.compile(
    r"(?P<path>[^\s'\"()]*aipp[^\s'\"()]*\.(?:cfg|conf|ini))\b", re.IGNORECASE
)
ATC_COMMAND_PATTERN = re.compile(r"(?im)^\s*atc\s+[^\n]*--model(?:=|\s)[^\n]*$")
LINKAGE_LINE_PATTERN = re.compile(
    r"(?m)^(?=[^\n]*(?:libascendcl|libacl_dvpp)\.so)(?=[^\n]*(?:=>|NEEDED|RUNPATH|RPATH))[^\n]*$"
)
SYMBOL_LINE_PATTERN = re.compile(
    r"(?m)^(?:\s*\d+:)?[^\n]*(?:\bFUNC\b|\bGLOBAL\b|\bWEAK\b|\b[ABCDGIRSTVW]\b)[^\n]*\b"
    r"(?P<name>acl(?:Init|Finalize|rt[A-Za-z0-9_]+|mdl[A-Za-z0-9_]+|dvpp[A-Za-z0-9_]+))\b[^\n]*$"
)
SAFE_FILENAME_PATTERN = re.compile(r"^[a-z0-9._-]+$")


def load_text(path_arg):
    if path_arg:
        return Path(path_arg).read_text(encoding="utf-8", errors="replace")
    return sys.stdin.read()


def unique(values):
    result = []
    for value in values:
        normalized = value.strip().rstrip(",;")
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def matches(pattern, text, group=0):
    return unique(match.group(group) for match in pattern.finditer(text))


def first(pattern, text, group=1, default="unknown"):
    match = pattern.search(text)
    return match.group(group).strip() if match else default


def split_contexts(text):
    headers = list(CONTEXT_HEADER_PATTERN.finditer(text))
    if not headers:
        return [("unlabeled evidence", text)]

    contexts = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[header.start():end].strip()
        contexts.append((re.sub(r"\s+", " ", header.group("label")).strip(), block))
    return contexts


def observed_devices(text):
    evidence_lines = []
    for line in text.splitlines():
        if re.match(r"^==\s*Device Context:", line, re.IGNORECASE):
            continue
        if re.match(r"^\s*atc\s", line, re.IGNORECASE):
            continue
        if ".om" in line or "--soc_version" in line:
            continue
        evidence_lines.append(line)
    normalized = []
    for match in DEVICE_PATTERN.finditer("\n".join(evidence_lines)):
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        compact = re.sub(r"[\s_-]+", "", value).lower()
        if compact == "atlas200ia2":
            value = "Atlas 200I A2"
        elif compact.startswith("ascend"):
            suffix = re.sub(r"(?i)^ascend\s*", "", value)
            value = "Ascend" + re.sub(r"[\s_-]+", "", suffix)
        if value not in normalized:
            normalized.append(value)
    return normalized


def detect_symbols(text):
    return unique(match.group("name") for match in SYMBOL_LINE_PATTERN.finditer(text))


def context_fields(label, text):
    cann_roots = matches(CANN_ROOT_PATTERN, text, 1)
    libraries = matches(LIB_PATTERN, text, "path")
    library_roots = unique(str(Path(path).parent) for path in libraries)
    atc_version = first(ATC_VERSION_PATTERN, text, "value")
    host_token = first(HOST_TOKEN_PATTERN, text)
    serial_token = first(SERIAL_TOKEN_PATTERN, text)
    device_index = first(DEVICE_INDEX_PATTERN, text)
    deployment = first(DEPLOYMENT_PATTERN, text)
    cann_material = "|".join(sorted([*cann_roots, *library_roots, atc_version]))
    cann_fingerprint = "c-" + hashlib.sha256(cann_material.encode()).hexdigest()[:8]
    identity_component = serial_token if serial_token != "unknown" else f"d-{device_index}"
    context_id = f"{host_token}-{identity_component}-{deployment}-{cann_fingerprint}".lower()

    return {
        "label": label,
        "host_token": host_token,
        "serial_token": serial_token,
        "device_index": device_index,
        "deployment": deployment,
        "context_id": context_id,
        "collected": first(COLLECTED_PATTERN, text),
        "devices": observed_devices(text),
        "nodes": matches(NODE_PATTERN, text),
        "kernel": first(KERNEL_PATTERN, text, 0),
        "os_release": first(OS_RELEASE_PATTERN, text),
        "driver_version": first(DRIVER_VERSION_PATTERN, text),
        "firmware_version": first(FIRMWARE_VERSION_PATTERN, text),
        "cann_roots": cann_roots,
        "atc_version": atc_version,
        "libraries": libraries,
        "library_roots": library_roots,
        "headers": matches(HEADER_PATH_PATTERN, text, "path"),
        "symbols": detect_symbols(text),
        "linkage": matches(LINKAGE_LINE_PATTERN, text),
        "om_files": matches(OM_PATTERN, text, "path"),
        "aipp_files": matches(AIPP_PATTERN, text, "path"),
        "atc_commands": matches(ATC_COMMAND_PATTERN, text),
    }


def summary(values):
    return ", ".join(values) if values else "unknown"


def risks_for(fields):
    risks = []
    if fields["host_token"] == "unknown":
        risks.append("Safe host token is missing; collect sanitized identity evidence.")
    if fields["device_index"] == "unknown":
        risks.append("Selected device index is missing.")
    if fields["deployment"] == "unknown":
        risks.append("Host/container deployment boundary is missing.")
    if not fields["devices"]:
        risks.append("Device model was not observed in runtime evidence.")
    if not fields["nodes"]:
        risks.append("Ascend device nodes were not observed.")
    if fields["driver_version"] == "unknown":
        risks.append("Driver version was not observed.")
    if fields["firmware_version"] == "unknown":
        risks.append("Firmware version was not observed.")
    if not fields["cann_roots"]:
        risks.append("CANN root was not observed.")
    if fields["atc_version"] == "unknown":
        risks.append("ATC version was not observed; required only for conversion work.")
    if not fields["libraries"]:
        risks.append("No Ascend runtime library path was observed.")
    if not fields["linkage"]:
        risks.append("Actual target linkage or dlopen resolution was not proved.")
    if not fields["symbols"]:
        risks.append("No exported Ascend symbols were observed from deployed libraries.")
    if not fields["om_files"]:
        risks.append("OM artifact provenance is unknown; required only for model/runtime work.")
    return risks


def render_context(fields):
    lines = [
        f"## Candidate Context: {fields['label']}",
        "",
        "### Identity",
        f"- Candidate context ID: `{fields['context_id']}`",
        f"- Safe host token: `{fields['host_token']}`",
        f"- NPU serial token: `{fields['serial_token']}`",
        f"- Selected device index: `{fields['device_index']}`",
        f"- Deployment: `{fields['deployment']}`",
        f"- Collected: {fields['collected']}",
        f"- Observed device candidates: {summary(fields['devices'])}",
        f"- Device nodes: {summary(fields['nodes'])}",
        "",
        "### System And Runtime",
        f"- Kernel: {fields['kernel']}",
        f"- OS: {fields['os_release']}",
        f"- Driver version: {fields['driver_version']}",
        f"- Firmware version: {fields['firmware_version']}",
        f"- CANN roots: {summary(fields['cann_roots'])}",
        f"- ATC version: {fields['atc_version']}",
        f"- Runtime libraries discovered: {summary(fields['libraries'])}",
        f"- Library roots: {summary(fields['library_roots'])}",
        f"- Header paths: {summary(fields['headers'])}",
        f"- Linkage evidence: {summary(fields['linkage'])}",
        f"- Exported Ascend symbols observed: {summary(fields['symbols'])}",
        "",
        "### Model Artifacts",
        f"- OM files: {summary(fields['om_files'])}",
        f"- AIPP files: {summary(fields['aipp_files'])}",
        f"- ATC commands: {summary(fields['atc_commands'])}",
        "",
        "### Open Risks",
    ]
    risks = risks_for(fields)
    lines.extend(f"- [ ] {risk}" for risk in risks)
    if not risks:
        lines.append("- [ ] No parser-detected gaps; manual review is still required.")
    return lines


def build_draft(text):
    contexts = [context_fields(label, block) for label, block in split_contexts(text)]
    lines = [
        "# Generated Ascend Runtime Context Draft",
        "",
        "> Generated from sanitized evidence. This is not an authoritative context and must not be",
        "> copied over a reviewed file without manual verification.",
        "",
    ]
    for fields in contexts:
        lines.extend(render_context(fields))
        lines.append("")
    lines.extend([
        "## Review Gate",
        "",
        "- [ ] Parser false positives removed.",
        "- [ ] One active runtime context selected.",
        "- [ ] Driver, firmware, loaded libraries, headers, linkage, and OM provenance verified as needed.",
        "- [ ] Device/CANN-specific rules cite their source and verification date.",
        "- [ ] Verified facts transferred deliberately into a reviewed context file.",
    ])
    return "\n".join(lines) + "\n", contexts


def validate_sanitized_input(text):
    if RAW_MACHINE_ID_PATTERN.search(text):
        raise ValueError("Raw machine ID detected. Run sanitize-ascend-evidence.py before rendering.")


def default_draft_path(context):
    context_id = context["context_id"]
    if "unknown" in context_id or not SAFE_FILENAME_PATTERN.fullmatch(context_id):
        raise ValueError("Cannot derive a safe context ID; host token, device index, and deployment are required.")
    return Path.cwd() / ".agent" / "ascend-pro" / "drafts" / f"{context_id}.generated.md"


def write_output(path, draft, force):
    resolved_path = path.resolve(strict=False)
    parts = resolved_path.parts
    reviewed_path = (".agent", "ascend-pro", "context")
    if any(tuple(parts[index:index + 3]) == reviewed_path for index in range(len(parts) - 2)):
        raise ValueError("Refusing to write generated output into the reviewed context directory.")

    if path.is_symlink():
        raise ValueError(f"Refusing to write through a symbolic link: {path}")
    if not resolved_path.name.endswith(".generated.md"):
        raise ValueError("Generated output filename must end with .generated.md.")

    if path.exists() and not force:
        raise ValueError(f"Output exists: {path}. Pass --force only to replace a generated draft.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(draft, encoding="utf-8")
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="Sanitized evidence file; reads stdin when omitted.")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("-o", "--output", help="Explicit path ending in .generated.md.")
    output_group.add_argument("--write-draft", action="store_true", help="Write under .agent/ascend-pro/drafts/.")
    parser.add_argument("--force", action="store_true", help="Replace an existing generated draft.")
    args = parser.parse_args()

    try:
        text = load_text(args.input)
        if not text.strip():
            raise ValueError("No input provided.")
        if args.force and not (args.output or args.write_draft):
            raise ValueError("--force requires --output or --write-draft.")
        validate_sanitized_input(text)
        draft, contexts = build_draft(text)

        output_path = None
        if args.output:
            output_path = Path(args.output)
        elif args.write_draft:
            if len(contexts) != 1:
                raise ValueError("--write-draft requires exactly one labeled context per input file.")
            output_path = default_draft_path(contexts[0])

        if output_path:
            write_output(output_path, draft, args.force)
            print(f"Wrote generated draft to {output_path}")
        else:
            sys.stdout.write(draft)
        return 0
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
