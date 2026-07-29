#!/usr/bin/env python3
"""Run rknn-pro routing and behavior evaluations against model commands.

Each model command receives one prompt on standard input and must print its
answer on standard output. Commands are parsed with shlex and never run through
a shell, which keeps the runner suitable for local CI adapters.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ModelCommand:
    name: str
    argv: tuple[str, ...]


def parse_model(value: str) -> ModelCommand:
    if "=" not in value:
        raise argparse.ArgumentTypeError("model must use NAME=COMMAND syntax")
    name, command = value.split("=", 1)
    argv = tuple(shlex.split(command))
    if not name.strip() or not argv:
        raise argparse.ArgumentTypeError("model name and command must be non-empty")
    return ModelCommand(name.strip(), argv)


def parse_command(value: str) -> tuple[str, ...]:
    argv = tuple(shlex.split(value))
    if not argv:
        raise argparse.ArgumentTypeError("command must be non-empty")
    return argv


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load {path}: {error}") from error


def extract_frontmatter(skill_text: str) -> str:
    if not skill_text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end = skill_text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md frontmatter is not terminated")
    return skill_text[4:end].strip()


def run_command(
    argv: tuple[str, ...], prompt: str, timeout: float, cwd: Path
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        process = subprocess.run(
            argv,
            cwd=cwd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "ok": False,
            "error": str(error),
            "stdout": getattr(error, "stdout", "") or "",
            "stderr": getattr(error, "stderr", "") or "",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def extract_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("response does not contain a JSON object")


def bounded_file_text(skill_root: Path, relative_path: str) -> str:
    root = skill_root.resolve()
    path = (root / relative_path).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"eval file escapes skill root: {relative_path}")
    if not path.is_file():
        raise ValueError(f"eval file does not exist: {relative_path}")
    return path.read_text(encoding="utf-8")


def routing_prompt(frontmatter: str, query: str) -> str:
    return f"""Decide whether the skill should be loaded for the user query.
Use only the skill metadata below; its body is unavailable during routing.
Return exactly one JSON object with keys should_trigger (boolean) and reason
(a short string). Do not solve the user task.

SKILL METADATA
{frontmatter}

USER QUERY
{query}
"""


def behavior_prompt(
    skill_root: Path, skill_text: str, item: dict[str, Any], with_skill: bool
) -> str:
    attachments = []
    for relative_path in item.get("files", []):
        attachments.append(
            f"\n--- FILE: {relative_path} ---\n"
            f"{bounded_file_text(skill_root, relative_path)}"
        )
    attachment_text = "".join(attachments) or "\n(none)"
    skill_section = (
        f"\n--- AVAILABLE SKILL: rknn-pro ---\n{skill_text}"
        if with_skill
        else "\nThe rknn-pro skill is intentionally unavailable for this control run."
    )
    return f"""Complete the user task below. Treat attached files as read-only.
Give a concrete technical answer and state uncertainty rather than inventing
version-specific contracts. Do not discuss this evaluation harness.

USER TASK
{item['prompt']}
{skill_section}

ATTACHED FILES
{attachment_text}
"""


def normalized_terms(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(term, str) for term in value):
        raise ValueError("required_terms and forbidden_terms must be arrays of strings")
    return [term.casefold() for term in value if term]


def term_checks(item: dict[str, Any], answer: str) -> dict[str, Any]:
    folded = answer.casefold()
    required = normalized_terms(item.get("required_terms"))
    forbidden = normalized_terms(item.get("forbidden_terms"))
    missing = [term for term in required if term not in folded]
    present_forbidden = [term for term in forbidden if term in folded]
    checked = bool(required or forbidden)
    return {
        "checked": checked,
        "passed": not missing and not present_forbidden if checked else None,
        "missing_required_terms": missing,
        "present_forbidden_terms": present_forbidden,
    }


def judge_prompt(item: dict[str, Any], answer: str) -> str:
    expectations = "\n".join(f"- {value}" for value in item["expectations"])
    return f"""Judge the candidate answer against every expectation below.
Return exactly one JSON object with keys passed (boolean), reason (string), and
expectation_results (an array of booleans in the same order). A technically
incorrect assertion fails even when matching keywords are present.

USER TASK
{item['prompt']}

EXPECTED OUTCOME
{item['expected_output']}

EXPECTATIONS
{expectations}

CANDIDATE ANSWER
{answer}
"""


def run_trigger_eval(
    model: ModelCommand,
    frontmatter: str,
    item: dict[str, Any],
    timeout: float,
    cwd: Path,
) -> dict[str, Any]:
    execution = run_command(model.argv, routing_prompt(frontmatter, item["query"]), timeout, cwd)
    result: dict[str, Any] = {
        "query": item["query"],
        "expected": item["should_trigger"],
        "execution": execution,
        "passed": False,
    }
    if not execution["ok"]:
        return result
    try:
        decision = extract_json_object(execution["stdout"])
        actual = decision.get("should_trigger")
        if not isinstance(actual, bool):
            raise ValueError("should_trigger is not a boolean")
    except ValueError as error:
        result["parse_error"] = str(error)
        return result
    result.update(
        {
            "actual": actual,
            "reason": decision.get("reason"),
            "passed": actual == item["should_trigger"],
        }
    )
    return result


def run_behavior_eval(
    model: ModelCommand,
    judge_argv: tuple[str, ...] | None,
    skill_root: Path,
    skill_text: str,
    item: dict[str, Any],
    with_skill: bool,
    timeout: float,
) -> dict[str, Any]:
    execution = run_command(
        model.argv,
        behavior_prompt(skill_root, skill_text, item, with_skill),
        timeout,
        skill_root,
    )
    result: dict[str, Any] = {
        "id": item["id"],
        "route": item.get("route", "unspecified"),
        "with_skill": with_skill,
        "execution": execution,
        "passed": False if not execution["ok"] else None,
    }
    if not execution["ok"]:
        return result
    answer = execution["stdout"]
    result["term_checks"] = term_checks(item, answer)
    if result["term_checks"]["checked"]:
        result["passed"] = result["term_checks"]["passed"]
    if judge_argv is None:
        return result

    judge_execution = run_command(judge_argv, judge_prompt(item, answer), timeout, skill_root)
    result["judge_execution"] = judge_execution
    if not judge_execution["ok"]:
        result["passed"] = False
        return result
    try:
        judgment = extract_json_object(judge_execution["stdout"])
        judge_passed = judgment.get("passed")
        checks = judgment.get("expectation_results")
        if not isinstance(judge_passed, bool):
            raise ValueError("judge passed field is not a boolean")
        if not isinstance(checks, list) or len(checks) != len(item["expectations"]):
            raise ValueError("judge expectation_results has the wrong length")
        if not all(isinstance(value, bool) for value in checks):
            raise ValueError("judge expectation_results must contain booleans")
    except ValueError as error:
        result["judge_parse_error"] = str(error)
        result["passed"] = False
        return result
    result["judgment"] = judgment
    result["passed"] = bool(judge_passed and result["term_checks"]["passed"] is not False)
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    automated = [item for item in results if isinstance(item.get("passed"), bool)]
    passed = sum(item["passed"] for item in automated)
    return {
        "total": len(results),
        "automated": len(automated),
        "manual_review": len(results) - len(automated),
        "passed": passed,
        "failed": len(automated) - passed,
        "pass_rate": round(passed / len(automated), 4) if automated else None,
    }


def compare_variants(results: list[dict[str, Any]]) -> dict[str, Any]:
    with_skill = summarize([item for item in results if item["with_skill"]])
    without_skill = summarize([item for item in results if not item["with_skill"]])
    with_rate = with_skill["pass_rate"]
    without_rate = without_skill["pass_rate"]
    return {
        "with_skill": with_skill,
        "without_skill": without_skill,
        "pass_rate_delta": (
            round(with_rate - without_rate, 4)
            if with_rate is not None and without_rate is not None
            else None
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        type=parse_model,
        metavar="NAME=COMMAND",
        help="model adapter; it receives the prompt on stdin (repeatable)",
    )
    parser.add_argument(
        "--judge-command",
        type=parse_command,
        metavar="COMMAND",
        help="optional independent judge adapter receiving a rubric on stdin",
    )
    parser.add_argument("--mode", choices=("all", "triggers", "behavior"), default="all")
    parser.add_argument(
        "--compare-without",
        action="store_true",
        help="also run behavior cases without the skill as a control",
    )
    parser.add_argument("--limit", type=int, help="run at most this many cases per suite")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds per command")
    parser.add_argument("--skill-root", type=Path, default=SKILL_ROOT)
    parser.add_argument("--output", type=Path, help="write the JSON report to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if len({model.name for model in args.model}) != len(args.model):
        raise SystemExit("model names must be unique")

    skill_root = args.skill_root.resolve()
    try:
        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = extract_frontmatter(skill_text)
        trigger_items = load_json(skill_root / "evals" / "trigger-evals.json")
        behavior_data = load_json(skill_root / "evals" / "evals.json")
        if not isinstance(trigger_items, list):
            raise ValueError("trigger-evals.json must contain an array")
        if not isinstance(behavior_data, dict) or not isinstance(
            behavior_data.get("evals"), list
        ):
            raise ValueError("evals.json must contain an evals array")
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.limit is not None:
        trigger_items = trigger_items[: args.limit]
        behavior_items = behavior_data["evals"][: args.limit]
    else:
        behavior_items = behavior_data["evals"]

    report: dict[str, Any] = {
        "skill": behavior_data.get("skill_name"),
        "models": {},
    }
    any_failure = False
    for model in args.model:
        model_report: dict[str, Any] = {}
        if args.mode in ("all", "triggers"):
            trigger_results = [
                run_trigger_eval(model, frontmatter, item, args.timeout, skill_root)
                for item in trigger_items
            ]
            model_report["triggers"] = {
                "summary": summarize(trigger_results),
                "results": trigger_results,
            }
            any_failure |= model_report["triggers"]["summary"]["failed"] > 0

        if args.mode in ("all", "behavior"):
            variants = [True, False] if args.compare_without else [True]
            behavior_results = [
                run_behavior_eval(
                    model,
                    args.judge_command,
                    skill_root,
                    skill_text,
                    item,
                    with_skill,
                    args.timeout,
                )
                for item in behavior_items
                for with_skill in variants
            ]
            model_report["behavior"] = {
                "summary": summarize(behavior_results),
                "results": behavior_results,
            }
            if args.compare_without:
                model_report["behavior"]["comparison"] = compare_variants(behavior_results)
            any_failure |= model_report["behavior"]["summary"]["failed"] > 0
        report["models"][model.name] = model_report

    rendered = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as error:
            print(f"error: cannot write {args.output}: {error}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(rendered)
    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
