#!/usr/bin/env python3
"""Generate a project-wide candidate inventory for Rockchip crash-risk review.

This is a triage tool, not a vulnerability oracle. Findings require manual call-path,
layout, ownership, and runtime-version verification.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".cmake", ".go", ".rs", ".sh",
}
SOURCE_NAMES = {"CMakeLists.txt", "Makefile"}
DEFAULT_EXCLUDED_PARTS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules",
    "__pycache__", ".cache", "dist", "coverage", "target",
}
GENERATED_PARTS = {
    "build", "builds", "out", "output", "_deps", "generated",
    "cmake-build-debug", "cmake-build-release",
}
THIRD_PARTY_PARTS = {
    "third_party", "third-party", "3rdparty", "vendor", "vendors",
    "external", "extern", "deps",
}
NON_PRODUCTION_PARTS = {
    "test", "tests", "testing", "example", "examples", "sample", "samples",
    "demo", "demos", "benchmark", "benchmarks", "tool", "tools", "fuzz", "fuzzers",
}
KNOWN_VENDOR_FILE_NAMES = {
    "stb_image.h", "stb_image_write.h", "json.hpp", "httplib.h",
}

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

SENSITIVE_APIS = (
    "rknn_init", "rknn_query", "rknn_create_mem", "rknn_create_mem_from_fd",
    "rknn_set_io_mem", "rknn_mem_sync", "rknn_run", "rknn_destroy_mem",
    "rknn_destroy", "importbuffer_fd", "importbuffer_virtualaddr",
    "wrapbuffer_fd", "wrapbuffer_handle", "wrapbuffer_virtualaddr",
    "releasebuffer_handle", "imcheck", "imresize", "imcrop", "imcvtcolor",
    "improcess", "imfill", "imsync", "imbeginJob", "imendJob",
    "mpp_buffer_get", "mpp_buffer_put",
    "mpp_buffer_import", "mpp_buffer_commit", "mpp_buffer_group_get_internal",
    "mpp_buffer_group_get_external", "mpp_buffer_group_limit_config",
    "mpp_buffer_group_put", "mpp_frame_deinit", "mpp_packet_deinit",
    "mmap", "munmap", "memcpy", "memmove", "malloc", "calloc", "realloc",
    "memset", "free", "open", "close", "dup", "dup2",
)

CHECKED_RETURN_APIS = {
    "rknn_init", "rknn_query", "rknn_set_io_mem", "rknn_mem_sync", "rknn_run",
    "imcheck", "imresize", "imcrop", "imcvtcolor", "improcess", "imfill",
    "mpp_buffer_get", "mpp_buffer_import", "mpp_buffer_commit",
    "mpp_buffer_group_limit_config",
}
CLEANUP_RETURN_APIS = {
    "rknn_destroy_mem", "rknn_destroy", "releasebuffer_handle",
    "mpp_buffer_put", "mpp_buffer_group_put",
}

CALL_NAMES = sorted(set(SENSITIVE_APIS) | {
    "read", "pread", "fread", "recv", "recvfrom", "strcpy", "strcat",
    "sprintf", "vsprintf", "gets", "scanf", "sscanf", "fscanf",
})

UNSAFE_STRING_APIS = {"strcpy", "strcat", "sprintf", "vsprintf", "gets"}
COPY_APIS = {"memcpy", "memmove", "memset", "read", "pread", "fread", "recv", "recvfrom"}
ALLOCATION_APIS = {"malloc", "calloc", "realloc", "rknn_create_mem", "rknn_create_mem_from_fd",
                   "importbuffer_fd", "importbuffer_virtualaddr", "mpp_buffer_get"}
RGA_OP_APIS = {"imresize", "imcrop", "imcvtcolor", "improcess", "imfill"}


@dataclass
class Finding:
    rule_id: str
    priority: str
    category: str
    title: str
    path: str
    line: int
    evidence: str
    reason: str
    review: str
    confidence: str = "candidate"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="project root")
    parser.add_argument("--output", "-o", help="write report to this path")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--include-third-party", action="store_true")
    parser.add_argument("--include-generated", action="store_true")
    parser.add_argument("--include-tests-examples", action="store_true")
    parser.add_argument("--exclude", action="append", default=[], help="extra path component to exclude")
    parser.add_argument(
        "--preprocess", "-E", action="store_true",
        help="expand macros with GCC before scanning (improves detection in macro-heavy code)",
    )
    parser.add_argument(
        "--preprocess-include", "-I", action="append", default=[], metavar="DIR",
        help="include directory passed to GCC as -I during --preprocess (repeatable); "
             "without the project's include paths most real sources fail to preprocess "
             "and fall back to raw scanning",
    )
    parser.add_argument(
        "--cross-prefix", default="",
        help="cross-compiler prefix (e.g., 'aarch64-linux-gnu-') for --preprocess",
    )
    return parser.parse_args()


# Suffixes eligible for GCC macro preprocessing.
_PREPROCESS_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
LINE_MARKER_RE = re.compile(r'^\s*#\s+(?P<line>\d+)\s+"(?P<path>[^"]+)"(?:\s+.*)?$')


def is_source(path):
    return path.name in SOURCE_NAMES or path.suffix.lower() in SOURCE_SUFFIXES


def extract_primary_source(preprocessed, filepath):
    """Keep expanded lines owned by filepath and preserve their original line numbers."""
    target = filepath.resolve()
    current_path = None
    current_line = 1
    kept_lines = []
    line_map = []

    for line in preprocessed.splitlines():
        marker = LINE_MARKER_RE.match(line)
        if marker:
            marker_path = marker.group("path")
            current_line = int(marker.group("line"))
            if marker_path.startswith("<"):
                current_path = None
            else:
                try:
                    current_path = Path(marker_path).resolve()
                except OSError:
                    current_path = None
            continue

        if current_path == target:
            kept_lines.append(line)
            line_map.append(current_line)
        current_line += 1

    if not kept_lines:
        return None
    return "\n".join(kept_lines), line_map


def preprocess_file(filepath, cross_prefix="", include_dirs=()):
    """Expand macros while excluding included-header bodies and retaining source line mapping."""
    gcc = f"{cross_prefix}gcc"
    if not shutil.which(gcc):
        return None
    try:
        cmd = [gcc, "-E"]
        cmd.extend(f"-I{directory}" for directory in include_dirs)
        cmd.append(str(filepath))
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return extract_primary_source(result.stdout, filepath)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def exclusion_reason(path, include_third_party, include_generated, include_tests_examples, extra):
    parts = set(path.parts)
    if parts & (DEFAULT_EXCLUDED_PARTS | set(extra)):
        return "excluded_path"
    if not include_generated:
        if parts & GENERATED_PARTS or any(part.startswith("cmake-build-") for part in path.parts):
            return "generated_path"
        if any(part.startswith("build-") for part in path.parts):
            return "generated_path"
    if not include_third_party and (parts & THIRD_PARTY_PARTS or path.name in KNOWN_VENDOR_FILE_NAMES):
        return "third_party_path"
    if not include_tests_examples and parts & NON_PRODUCTION_PARTS:
        return "non_production_path"
    return None


def discover_files(root, include_third_party, include_generated, include_tests_examples, extra):
    selected = []
    skipped = Counter()
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        rel_current = current.relative_to(root)
        kept_dirs = []
        for dirname in dirnames:
            rel_dir = rel_current / dirname
            reason = exclusion_reason(
                rel_dir, include_third_party, include_generated, include_tests_examples, extra
            )
            if reason:
                skipped[f"{reason}_directories"] += 1
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in filenames:
            rel = rel_current / filename
            reason = exclusion_reason(
                rel, include_third_party, include_generated, include_tests_examples, extra
            )
            if reason:
                skipped[f"{reason}_files"] += 1
            elif not is_source(rel):
                skipped["unsupported_extension_files"] += 1
            else:
                selected.append(rel)
    return sorted(set(selected)), skipped


def mask_c_like(text):
    chars = list(text)
    i = 0
    state = "code"
    quote = ""
    while i < len(chars):
        ch = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "line_comment"
                continue
            if ch == "/" and nxt == "*":
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "block_comment"
                continue
            if ch in ('"', "'"):
                quote = ch
                chars[i] = " "
                i += 1
                state = "string"
                continue
        elif state == "line_comment":
            if ch == "\n":
                state = "code"
            else:
                chars[i] = " "
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "code"
                continue
            if ch != "\n":
                chars[i] = " "
        elif state == "string":
            if ch == "\\":
                chars[i] = " "
                if i + 1 < len(chars) and chars[i + 1] != "\n":
                    chars[i + 1] = " "
                    i += 2
                    continue
            elif ch == quote:
                chars[i] = " "
                state = "code"
            elif ch != "\n":
                chars[i] = " "
        i += 1
    return "".join(chars)


CALL_RE = re.compile(r"\b(" + "|".join(map(re.escape, CALL_NAMES)) + r")\s*\(")


def iter_calls(text, masked):
    for match in CALL_RE.finditer(masked):
        open_pos = masked.find("(", match.start())
        depth = 0
        end = None
        for pos in range(open_pos, len(masked)):
            if masked[pos] == "(":
                depth += 1
            elif masked[pos] == ")":
                depth -= 1
                if depth == 0:
                    end = pos
                    break
        if end is None:
            continue
        yield match.group(1), match.start(), end + 1, text[open_pos + 1:end], masked[open_pos + 1:end]


def looks_like_template_open(masked, index):
    if index == 0 or masked[index - 1].isspace():
        return False
    previous = masked[index - 1]
    if not (previous.isalnum() or previous in "_>:])"):
        return False

    depth = 1
    nested_depth = 0
    for pos in range(index + 1, len(masked)):
        ch = masked[pos]
        if ch in "([{":
            nested_depth += 1
        elif ch in ")]}":
            nested_depth = max(0, nested_depth - 1)
        elif nested_depth == 0:
            if ch == "<" and pos > 0 and not masked[pos - 1].isspace():
                depth += 1
            elif ch == ">":
                depth -= 1
                if depth == 0:
                    return True
            elif ch in "?;":
                return False
    return False


def split_args(raw, masked):
    args = []
    start = 0
    stack = []
    for i, ch in enumerate(masked):
        if ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if stack and (stack[-1], ch) in {("(", ")"), ("[", "]"), ("{", "}")}:
                stack.pop()
        elif ch == "<" and looks_like_template_open(masked, i):
            stack.append("<")
        elif ch == ">" and stack and stack[-1] == "<":
            stack.pop()
        elif ch == "," and not stack:
            args.append(raw[start:i].strip())
            start = i + 1
    tail = raw[start:].strip()
    if tail or raw.strip():
        args.append(tail)
    return args


def line_number(text, pos):
    return text.count("\n", 0, pos) + 1


def source_line_number(text, pos, line_map=None):
    generated_line = line_number(text, pos)
    if line_map and generated_line <= len(line_map):
        return line_map[generated_line - 1]
    return generated_line


def compact(value, limit=240):
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit - 3] + "..."


def has_unchecked_arithmetic(expr):
    return bool(re.search(r"\w\s*[+*]\s*\w", expr)) and not re.search(
        r"Checked|checked_|safe_|overflow|numeric_limits|__builtin_(?:mul|add)_overflow", expr, re.I
    )


def call_is_unchecked(text, start, end):
    statement_start = max(
        text.rfind("\n", 0, start),
        text.rfind(";", 0, start),
        text.rfind("{", 0, start),
        text.rfind("}", 0, start),
    ) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    prefix = text[statement_start:start].strip()
    suffix = text[end:line_end].strip()
    checked_prefix = re.search(
        r"(?:\b(?:return|if|while|for|switch|assert)\b|(?<![=!<>])=(?!=))", prefix
    )
    if checked_prefix:
        return False
    return (not prefix or prefix in {"(void)"}) and suffix.startswith(";")


def add(findings, rule_id, priority, category, title, rel, line, evidence, reason, review):
    findings.append(Finding(
        rule_id, priority, category, title, str(rel), line, compact(evidence), reason, review
    ))


def scan_file(rel, text, inventory, findings, line_map=None):
    masked = mask_c_like(text)
    calls = list(iter_calls(text, masked))
    call_counts = Counter(name for name, *_ in calls)
    inventory.update(call_counts)

    for name, start, end, raw_args, masked_args in calls:
        args = split_args(raw_args, masked_args)
        line = source_line_number(text, start, line_map)
        evidence = text[start:end]

        if name in UNSAFE_STRING_APIS:
            add(findings, "MEM001", "high", "generic-memory", "Unbounded C string API", rel, line,
                evidence, "The API does not carry destination capacity and can corrupt memory.",
                "Replace with a bounded, checked construction and prove destination capacity.")

        if name in COPY_APIS:
            size_arg = ""
            if name in {"memcpy", "memmove", "memset"} and len(args) >= 3:
                size_arg = args[2]
            elif name in {"read", "pread", "recv", "recvfrom"} and len(args) >= 3:
                size_arg = args[2]
            elif name == "fread" and len(args) >= 3:
                size_arg = f"({args[1]}) * ({args[2]})"
            priority = "high" if has_unchecked_arithmetic(size_arg) else "low"
            add(findings, "MEM002", priority, "copy-bounds", "Raw copy/read requires capacity proof", rel,
                line, evidence, "Source/destination bounds and size arithmetic are not provable by syntax alone.",
                "Trace source bytes, destination capacity, overlap, signedness, and short-read behavior.")

        if name in ALLOCATION_APIS:
            size_expr = ""
            if name in {"malloc", "realloc"} and args:
                size_expr = args[-1]
            elif name == "calloc" and len(args) >= 2:
                size_expr = f"({args[0]}) * ({args[1]})"
            elif name == "rknn_create_mem" and len(args) >= 2:
                size_expr = args[1]
            elif name == "rknn_create_mem_from_fd" and len(args) >= 4:
                size_expr = args[3]
            elif name.startswith("importbuffer_") and len(args) >= 2:
                size_expr = args[1]
            elif name == "mpp_buffer_get" and len(args) >= 3:
                size_expr = args[2]

            if has_unchecked_arithmetic(size_expr):
                add(findings, "MEM003", "high", "integer-overflow", "Allocation/import size uses unchecked arithmetic",
                    rel, line, evidence, "Multiplication or addition can wrap before allocation/import.",
                    "Use checked size_t multiply/add/align helpers and validate dimensions before conversion.")

            if name == "rknn_create_mem" and re.search(r"(?:\.|->)size\b", size_expr) and \
                    "size_with_stride" not in size_expr and "max" not in size_expr.lower():
                add(findings, "RKNN001", "high", "rknn-allocation", "RKNN allocation directly uses logical size",
                    rel, line, evidence, "Stride-aware tensor bytes or RGA target layout may exceed the logical size.",
                    "Trace the selected header fields and allocate the maximum applicable size plus checked alignment.")

            if name == "rknn_create_mem" and "RKNN_TENSOR_SIZE_FIELD" in size_expr and not re.search(
                    r"alloc|safe|checked|max|align|GetTensorAllocSize", size_expr, re.I):
                add(findings, "RKNN002", "high", "rknn-allocation",
                    "RKNN allocation uses one selected field without a defensive size helper",
                    rel, line, evidence,
                    "A selected field may not cover comparison with other available fields, RGA-derived bytes, overflow checks, or page alignment.",
                    "Trace the producer. Route allocation through one checked helper that compares all applicable minima and alignment.")

        if name in {"wrapbuffer_fd", "wrapbuffer_handle", "wrapbuffer_virtualaddr"} and len(args) == 4:
            add(findings, "RGA001", "high", "rga-layout", "RGA wrapper relies on implicit tight strides", rel,
                line, evidence, "The public four-argument form defaults strides to width/height.",
                "Pass the actual source or destination w_stride/h_stride and prove allocation size from them.")

        if name in {"wrapbuffer_virtualaddr", "importbuffer_virtualaddr"}:
            add(findings, "RGA002", "medium", "rga-virtual-memory", "RGA virtual-address path needs mapping/lifetime audit",
                rel, line, evidence, "RGA page-table conversion is sensitive to mapping length, allocator, kmap, cache, and lifetime.",
                "Verify mapped bytes, allocator compatibility, cache sync, in-flight lifetime, and prefer a valid fd path.")

        if name in CHECKED_RETURN_APIS and call_is_unchecked(text, start, end):
            add(findings, "API001", "medium", "error-handling", "Vendor API return value appears unchecked", rel,
                line, evidence, "Continuing after a failed hardware/runtime call can reuse invalid state or memory.",
                "Check the exact return code and unwind only acquired resources before continuing or retrying.")

        if name in CLEANUP_RETURN_APIS and call_is_unchecked(text, start, end):
            add(findings, "API002", "low", "cleanup-observability", "Cleanup API return value appears unchecked", rel,
                line, evidence, "A cleanup failure can hide leaked driver/runtime state or make later diagnosis ambiguous.",
                "Log or aggregate cleanup failures where the API contract makes them actionable; keep cleanup idempotent.")

    if any(call_counts[name] for name in RGA_OP_APIS) and call_counts["imcheck"] == 0:
        first = min(source_line_number(text, start, line_map) for name, start, *_ in calls if name in RGA_OP_APIS)
        add(findings, "RGA003", "high", "rga-validation", "RGA operations in file have no imcheck call", rel,
            first, "RGA operation(s) without imcheck in the same translation unit",
            "Invalid rectangles, formats, strides, and hardware restrictions may reach the driver.",
            "Trace whether validation occurs in a caller; otherwise validate the real buffers and rectangles before submit.")

    # RGA004: Detect per-frame wrapbuffer_fd without importbuffer_fd — the cascade failure pattern.
    if call_counts["wrapbuffer_fd"] > 0 and call_counts["importbuffer_fd"] == 0 and call_counts["wrapbuffer_handle"] == 0:
        first = min(source_line_number(text, start, line_map) for name, start, *_ in calls if name == "wrapbuffer_fd")
        add(findings, "RGA004", "high", "rga-lifecycle", "wrapbuffer_fd without importbuffer_fd — cascade failure risk", rel,
            first, f"wrapbuffer_fd={call_counts['wrapbuffer_fd']}, importbuffer_fd=0, wrapbuffer_handle=0",
            "Per-frame wrapbuffer_fd uses librga's internal fd-cache, which returns stale handles when fds are recycled. "
            "This is the #1 cause of RGA cascade failures (Cannot get dst channel buffer → job timeout → soft reset → pipeline stall).",
            "Import each buffer once with importbuffer_fd, use wrapbuffer_handle per frame, and releasebuffer_handle at shutdown. "
            "All buffers must use handle-based API — mixing handles and fd-wrap is rejected by librga.")

    # RGA005: Detect mixing of handle-based and fd-based buffer APIs in the same file.
    if call_counts["wrapbuffer_handle"] > 0 and call_counts["wrapbuffer_fd"] > 0:
        add(findings, "RGA005", "high", "rga-lifecycle", "Mixed handle and fd buffer wrapping in same file", rel,
            1, f"wrapbuffer_handle={call_counts['wrapbuffer_handle']}, wrapbuffer_fd={call_counts['wrapbuffer_fd']}",
            "librga requires uniform handle usage: all buffers via importbuffer+wrapbuffer_handle, or all via wrapbuffer_fd. "
            "Mixing causes 'librga only supports the use of handles only or no handles' warning and can abort or corrupt.",
            "Convert all buffer wrapping to the handle-based path: importbuffer_fd once, wrapbuffer_handle per frame.")

    # RGA006: RGA operations in file with no sync fence and RKNN run — missing synchronization.
    if any(call_counts[name] for name in RGA_OP_APIS) and call_counts["rknn_run"] > 0:
        if "imsync" not in text and "release_fence" not in text and "IM_SYNC" not in text and "sync" not in text:
            add(findings, "RGA006", "medium", "rga-sync", "RGA-to-RKNN handoff has no visible synchronization", rel,
                1, "RGA operation(s) and rknn_run in same file without sync/fence",
                "If RGA runs asynchronously and RKNN reads the destination buffer before RGA finishes, the NPU reads stale or partial data.",
                "Use IM_SYNC (sync=1) for RGA operations, or use fence-based synchronization with imendJob/release_fence_fd.")

    pair_rules = (
        (("importbuffer_fd", "importbuffer_virtualaddr"), "releasebuffer_handle", "LIFE001", "RGA imported handle"),
        (("rknn_create_mem", "rknn_create_mem_from_fd"), "rknn_destroy_mem", "LIFE002", "RKNN tensor memory"),
        (("mmap",), "munmap", "LIFE003", "Memory mapping"),
        (("mpp_buffer_get", "mpp_buffer_import"), "mpp_buffer_put", "LIFE004", "MPP buffer reference"),
    )
    for creators, releaser, rule_id, label in pair_rules:
        acquired = sum(call_counts[name] for name in creators)
        released = call_counts[releaser]
        if acquired and released == 0:
            add(findings, rule_id, "medium", "resource-lifetime", f"{label} has no matching release in file",
                rel, 1, f"acquire/import calls={acquired}, {releaser}=0",
                "The release may be cross-file, but leaks and shutdown use-after-free require explicit ownership tracing.",
                "Follow every returned object through success, partial failure, reload, and shutdown paths.")

    # Check for DMA-BUF file descriptor opening without close
    # (matches open("/dev/dma_heap/system", ...) and similar heap-node paths)
    if re.search(r'open\s*\(\s*"/dev/(?:dma_heap|ion)', text):
        if call_counts["close"] == 0:
            add(findings, "LIFE005", "high", "resource-leak", "DMA-BUF heap opened without explicit close in file",
                rel, 1, "open('/dev/dma_heap...') present but close=0",
                "Unclosed DMA heap file descriptors can cause kernel FD table exhaustion during long service runs.",
                "Ensure every open dma_heap or ion file descriptor is closed after buffer allocation or during cleanup.")

    # Same-file threads plus rknn_run need context-ownership tracing; syntax cannot prove sharing.
    if call_counts["rknn_run"] >= 1 and ("std::thread" in text or "pthread_create" in text):
        if not re.search(r"std::mutex|pthread_mutex_t|std::lock_guard|std::unique_lock", text):
            add(findings, "RKNN003", "medium", "concurrency-hazard", "Threaded RKNN execution needs per-context ownership proof",
                rel, 1, "pthread_create/std::thread and rknn_run present without mutex",
                "If threads share one context without a version-supported contract, calls can race; separate contexts in the same file are not a defect.",
                "Trace the context passed to each worker. Use one owned context per worker/pool lease or serialize access according to the deployed Runtime contract.")


    if "RKNN_FLAG_DISABLE_FLUSH_INPUT_MEM_CACHE" in text or "RKNN_FLAG_DISABLE_FLUSH_OUTPUT_MEM_CACHE" in text:
        if call_counts["rknn_mem_sync"] == 0:
            line = source_line_number(text, text.find("RKNN_FLAG_DISABLE_FLUSH"), line_map)
            add(findings, "SYNC001", "high", "cache-coherency", "RKNN automatic cache maintenance disabled without local mem sync",
                rel, line, "RKNN_FLAG_DISABLE_FLUSH_*_MEM_CACHE",
                "CPU/device access can observe stale data or overwrite unsynchronized cache lines.",
                "Trace synchronization across callers and add the required rknn_mem_sync direction before access.")

    if "mpp_frame_get_info_change" in text and "MPP_DEC_SET_INFO_CHANGE_READY" not in text:
        line = source_line_number(text, text.find("mpp_frame_get_info_change"), line_map)
        add(findings, "MPP001", "high", "mpp-reconfigure", "MPP info-change handling may be incomplete", rel,
            line, "mpp_frame_get_info_change without MPP_DEC_SET_INFO_CHANGE_READY in file",
            "Continuing with old strides or buffers after resolution change can overrun or stall the decoder.",
            "Trace the caller; rebuild the buffer group from returned strides before acknowledging info-change.")

    if "mpp_buffer_group_get_internal" in text and "mpp_buffer_group_limit_config" not in text:
        line = source_line_number(text, text.find("mpp_buffer_group_get_internal"), line_map)
        add(findings, "MPP002", "medium", "resource-exhaustion", "MPP internal buffer group has no visible limit",
            rel, line, "mpp_buffer_group_get_internal without mpp_buffer_group_limit_config in file",
            "Decoder memory can grow beyond service limits depending on mode and retained frames.",
            "Trace group configuration and frame retention; set size/count limits or document bounded ownership.")

    if call_counts["mmap"] and "MAP_FAILED" not in text:
        first = min(source_line_number(text, start, line_map) for name, start, *_ in calls if name == "mmap")
        add(findings, "LIFE006", "high", "mapping-lifetime", "mmap result has no visible MAP_FAILED check",
            rel, first, "mmap call(s) without MAP_FAILED in the same file",
            "Using `(void*)-1` as a valid mapping can crash the process or pass an invalid address to a driver.",
            "Trace wrapper/caller validation; reject MAP_FAILED before storing, copying, or hardware submission.")

    align_match = re.search(
        r"(?:ALIGN(?:_UP)?\s*\([^\n;]+|\([^\n;]*\+\s*(?:align|alignment|4095|8191|16383)[^\n;]*\)\s*&)",
        masked, re.I,
    )
    if align_match:
        nearby = masked[max(0, align_match.start() - 300):align_match.end() + 300]
        if not re.search(r"overflow|numeric_limits|__builtin_add_overflow|AlignUpChecked|checked", nearby, re.I):
            add(findings, "MEM004", "medium", "integer-overflow", "Alignment expression needs overflow proof",
                rel, source_line_number(text, align_match.start(), line_map), compact(text[align_match.start():align_match.end()]),
                "Adding alignment minus one can wrap before rounding, producing an undersized allocation.",
                "Use a checked align-up helper and reject zero/non-power-of-two alignment when required.")

    if re.search(r"\.detach\s*\(|pthread_detach\s*\(", masked):
        pos = re.search(r"\.detach\s*\(|pthread_detach\s*\(", masked).start()
        add(findings, "CONC001", "high", "concurrency-lifetime", "Detached worker needs hardware-object lifetime proof",
            rel, source_line_number(text, pos, line_map), compact(text[pos:pos + 160]),
            "A detached worker can outlive RKNN contexts, RGA/MPP buffers, callbacks, or plugin code.",
            "Use an owned worker with cancellation and join, or prove captured resources outlive the process.")

    if rel.name == "CMakeLists.txt" or rel.suffix == ".cmake":
        if re.search(r"rknn", text, re.I) and "check_struct_has_member" in text and "size_with_stride" not in text:
            add(findings, "BUILD001", "high", "build-abi", "RKNN field probing does not prefer size_with_stride",
                rel, 1, "RKNN CMake feature detection without size_with_stride",
                "A target may compile with an older logical-size field and under-allocate stride-aware tensors.",
                "Probe size_with_stride first against the same target header and export guarded feature macros.")
        if re.search(r"/(?:Users|home|usr/local)/[^\s\"')]+(?:rknn|rga|mpp)", text, re.I):
            pos = re.search(r"/(?:Users|home|usr/local)/[^\s\"')]+(?:rknn|rga|mpp)", text, re.I).start()
            add(findings, "BUILD002", "medium", "build-abi", "Hard-coded Rockchip SDK path can select the wrong ABI",
                rel, source_line_number(text, pos, line_map), compact(text[pos:pos + 180]),
                "Machine-specific include/library paths can silently mix headers, sysroots, and runtime libraries.",
                "Resolve SDK roots from the selected toolchain/target and verify the final compile/link commands.")


def render_markdown(root, files, skipped, inventory, findings, unreadable, args):
    counts = Counter(item.priority for item in findings)
    categories = Counter(item.category for item in findings)
    lines = [
        "# Rockchip Crash-Risk Candidate Report", "",
        "> Automated candidates are not confirmed defects. Manually trace layout, ownership, call paths,",
        "> error handling, synchronization, and deployed versions before assigning severity.", "",
        "## Coverage", "",
        f"- Root: `{root}`",
        f"- Source/build files scanned: {len(files)}",
        f"- Unreadable files: {unreadable}",
        f"- Include third-party: {args.include_third_party}",
        f"- Include generated/build trees: {args.include_generated}",
        f"- Include tests/examples: {args.include_tests_examples}",
        f"- Pruned excluded directories: {skipped['excluded_path_directories']}",
        f"- Pruned generated/build directories: {skipped['generated_path_directories']}",
        f"- Pruned third-party directories: {skipped['third_party_path_directories']}",
        f"- Pruned test/example directories: {skipped['non_production_path_directories']}",
        f"- Skipped unsupported-extension files: {skipped['unsupported_extension_files']}", "",
        "## Summary", "",
        f"- High-priority candidates: {counts['high']}",
        f"- Medium-priority candidates: {counts['medium']}",
        f"- Low-priority manual-review sites: {counts['low']}", "",
        "### Categories", "",
    ]
    for name, count in sorted(categories.items()):
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Sensitive API Inventory", ""])
    for name in sorted(inventory):
        lines.append(f"- `{name}`: {inventory[name]}")
    lines.extend(["", "## Findings", ""])
    ordered = sorted(findings, key=lambda item: (PRIORITY_ORDER[item.priority], item.path, item.line, item.rule_id))
    for index, item in enumerate(ordered, 1):
        lines.extend([
            f"### {index}. [{item.priority.upper()}] {item.rule_id}: {item.title}", "",
            f"- Location: `{item.path}:{item.line}`",
            f"- Confidence: `{item.confidence}`",
            f"- Category: `{item.category}`",
            f"- Evidence: `{item.evidence.replace('`', ' ') }`",
            f"- Why review: {item.reason}",
            f"- Required review: {item.review}", "",
        ])
    lines.extend([
        "## Required Manual Follow-up", "",
        "1. Limit CodeGraph/source tracing to production roots and connect each candidate to callers and cleanup.",
        "2. Build a per-buffer size/layout/owner/lifetime ledger across RKNN, RGA, MPP, DMA-BUF, and CPU code.",
        "3. Run project builds and available analyzers/tests for every algorithm and SoC variant.",
        "4. Correlate target-board logs and versions before promoting environment-dependent findings.",
        "5. Report exclusions and residual risk; this candidate report alone is not a comprehensive audit.", "",
    ])
    return "\n".join(lines)


def main():
    args = parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    files, skipped = discover_files(
        root, args.include_third_party, args.include_generated,
        args.include_tests_examples, args.exclude
    )
    inventory = Counter()
    findings = []
    unreadable = 0
    preprocess_ok = 0
    preprocess_fail = 0
    preprocess_skip = 0
    for rel in files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            unreadable += 1
            continue

        scan_text = text
        line_map = None
        if args.preprocess and rel.suffix.lower() in _PREPROCESS_SUFFIXES:
            expanded = preprocess_file(root / rel, args.cross_prefix, args.preprocess_include)
            if expanded is not None:
                scan_text, line_map = expanded
                preprocess_ok += 1
            else:
                preprocess_fail += 1
                print(f"warning: preprocessing failed for {rel}, scanning raw source", file=sys.stderr)
        elif args.preprocess:
            preprocess_skip += 1

        scan_file(rel, scan_text, inventory, findings, line_map=line_map)

    if args.preprocess:
        total = preprocess_ok + preprocess_fail + preprocess_skip
        print(
            f"Preprocessed {preprocess_ok}/{total} files successfully "
            f"({preprocess_fail} failed, used raw source; {preprocess_skip} skipped, not C/C++)",
            file=sys.stderr,
        )

    deduped = []
    seen = set()
    for finding in findings:
        key = (finding.rule_id, finding.path, finding.line, finding.evidence)
        if key not in seen:
            seen.add(key)
            deduped.append(finding)

    if args.format == "json":
        report = json.dumps({
            "root": str(root),
            "coverage": {
                "files_scanned": len(files),
                "unreadable": unreadable,
                "preprocessed": preprocess_ok if args.preprocess else None,
                "preprocess_failed": preprocess_fail if args.preprocess else None,
                "skipped": dict(skipped),
                "include_third_party": args.include_third_party,
                "include_generated": args.include_generated,
                "include_tests_examples": args.include_tests_examples,
            },
            "inventory": dict(sorted(inventory.items())),
            "findings": [asdict(item) for item in deduped],
        }, indent=2)
    else:
        report = render_markdown(root, files, skipped, inventory, deduped, unreadable, args)

    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
