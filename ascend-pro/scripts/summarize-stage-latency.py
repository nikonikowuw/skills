#!/usr/bin/env python3
import re
import statistics
import sys
from collections import defaultdict


PATTERN = re.compile(r"(?P<stage>[A-Za-z0-9_-]+)\s*[:=]\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>us|ms)")


def load_samples(path):
    samples = defaultdict(list)
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            match = PATTERN.search(line)
            if not match:
                continue
            stage = match.group("stage")
            value = float(match.group("value"))
            unit = match.group("unit")
            if unit == "us":
                value /= 1000.0
            samples[stage].append(value)
    return samples


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def main():
    if len(sys.argv) != 2:
        print("Usage: summarize-stage-latency.py <timing-log>")
        return 1

    samples = load_samples(sys.argv[1])
    if not samples:
        print("No stage timing samples found. Expected lines like: infer=5.2ms or dvpp: 830us")
        return 1

    print("stage,count,avg_ms,p50_ms,p95_ms,max_ms")
    for stage in sorted(samples):
        values = samples[stage]
        print(
            f"{stage},{len(values)},{statistics.fmean(values):.3f},{percentile(values, 50):.3f},{percentile(values, 95):.3f},{max(values):.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
