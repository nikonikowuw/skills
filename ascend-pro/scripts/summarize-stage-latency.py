#!/usr/bin/env python3
import argparse
import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path


LEGACY_PATTERN = re.compile(
    r"(?P<stage>[A-Za-z0-9_.-]+)\s*[:=]\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>us|ms)\b"
)


def load_csv_samples(text):
    rows = list(csv.DictReader(text.splitlines()))
    if not rows or not {"stage", "elapsed_us"}.issubset(rows[0]):
        return None

    samples = defaultdict(list)
    for line_number, row in enumerate(rows, start=2):
        stage = (row.get("stage") or "").strip()
        value = (row.get("elapsed_us") or "").strip()
        if not stage or not value:
            continue
        try:
            samples[stage].append(float(value) / 1000.0)
        except ValueError as error:
            raise ValueError(f"invalid elapsed_us at CSV line {line_number}: {value}") from error
    return samples


def load_legacy_samples(text):
    samples = defaultdict(list)
    for line in text.splitlines():
        match = LEGACY_PATTERN.search(line)
        if not match:
            continue
        value = float(match.group("value"))
        if match.group("unit") == "us":
            value /= 1000.0
        samples[match.group("stage")].append(value)
    return samples


def load_samples(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    csv_samples = load_csv_samples(text)
    return csv_samples if csv_samples is not None else load_legacy_samples(text)


def percentile(values, pct):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def main():
    parser = argparse.ArgumentParser(
        description="Summarize stage,elapsed_us CSV or legacy stage=5.2ms timing logs."
    )
    parser.add_argument("timing_log")
    args = parser.parse_args()

    try:
        samples = load_samples(args.timing_log)
    except (OSError, ValueError) as error:
        print(f"error: {error}")
        return 1
    if not samples:
        print("No timing samples found. Expected CSV stage,elapsed_us,... or infer=5.2ms.")
        return 1

    print("stage,count,avg_ms,p50_ms,p95_ms,max_ms")
    for stage in sorted(samples):
        values = samples[stage]
        print(
            f"{stage},{len(values)},{statistics.fmean(values):.3f},"
            f"{percentile(values, 50):.3f},{percentile(values, 95):.3f},{max(values):.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
