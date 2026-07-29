#!/usr/bin/env python3
"""Redact common identifiers from Ascend diagnostic evidence."""

import argparse
import hashlib
import hmac
import re
import sys


TOKEN_KEY = b"ascend-pro-context-v1:7b66474d5c9e427693cf291253ae9358"
MACHINE_ID_RE = re.compile(r"(?m)^[0-9a-fA-F]{32}$")
LABELED_MACHINE_ID_RE = re.compile(
    r"(?im)^\s*machine[\s_-]*id\s*[:=]\s*([0-9a-f]{32})\s*$"
)
SERIAL_RE = re.compile(
    r"(?im)(?P<label>\b(?:chip|board|device|npu)?\s*(?:sn|serial(?:\s+(?:number|no\.?))?))"
    r"(?P<sep>\s*[:=]\s*)(?P<value>[A-Za-z0-9._:-]{4,})"
)
MAC_RE = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")
IPV4_RE = re.compile(r"(?<![0-9.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![0-9.])")
HOME_RE = re.compile(r"(?P<prefix>/(?:home|Users)/)[^/\s]+")


def token(kind, value):
    normalized = value.strip().encode("utf-8", errors="replace")
    digest = hmac.new(TOKEN_KEY, normalized, hashlib.sha256).hexdigest()[:12]
    return f"{kind}-{digest}"


def sanitize(text):
    text = LABELED_MACHINE_ID_RE.sub(lambda match: f"Host Token: {token('h', match.group(1))}", text)
    text = MACHINE_ID_RE.sub(lambda match: token("h", match.group(0)), text)

    def replace_serial(match):
        label = re.sub(r"\s+", " ", match.group("label").strip()).title()
        return f"{label} Token{match.group('sep')}{token('s', match.group('value'))}"

    text = SERIAL_RE.sub(replace_serial, text)
    text = MAC_RE.sub("<mac-redacted>", text)
    text = IPV4_RE.sub("<ip-redacted>", text)
    text = HOME_RE.sub(lambda match: f"{match.group('prefix')}<user>", text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--derive-token", choices=("host", "serial"))
    args = parser.parse_args()
    value = sys.stdin.read()

    if args.derive_token:
        value = value.strip()
        if not value:
            print("Cannot derive a token from empty input.", file=sys.stderr)
            return 1
        print(token("h" if args.derive_token == "host" else "s", value))
        return 0

    sys.stdout.write(sanitize(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
