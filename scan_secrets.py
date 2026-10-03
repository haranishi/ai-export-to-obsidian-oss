#!/usr/bin/env python3
import os
import re
import sys


RULES = [
    ("google_api_key", re.compile(rb"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("supabase_access_token", re.compile(rb"\bsbp_[0-9a-fA-F]{32,}\b")),
    ("supabase_key", re.compile(rb"\bsb_(?:secret|publishable)_[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(rb"(?<![A-Za-z0-9_])sk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("github_token", re.compile(rb"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z_]{20,}\b|\bgithub_pat_[0-9A-Za-z_]{30,}\b")),
    ("aws_access_key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("stripe_secret_key", re.compile(rb"\bsk_(?:live|test)_[0-9A-Za-z]{16,}\b")),
    ("private_key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(rb"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b")),
    ("bearer_token", re.compile(rb"(?:Authorization:\s*Bearer\s+|\bBearer\s+)[A-Za-z0-9._-]{50,}\b")),
]


SKIP_DIRS = {".git", "__pycache__", ".trash", ".obsidian"}


def is_binary(path):
    try:
        with open(path, "rb") as f:
            return b"\0" in f.read(4096)
    except OSError:
        return True


def scan_file(root, path):
    if is_binary(path):
        return []
    hits = []
    try:
        with open(path, "rb") as f:
            for line_no, line in enumerate(f, 1):
                for name, regex in RULES:
                    if regex.search(line):
                        rel = os.path.relpath(path, root)
                        hits.append((rel, line_no, name))
    except OSError:
        pass
    return hits


def scan(root):
    hits = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            hits.extend(scan_file(root, os.path.join(current, name)))
    return hits


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    root = os.path.abspath(root)
    hits = scan(root)
    if hits:
        print("SECRET SCAN FAILED: commit/push skipped")
        for rel, line_no, name in hits[:200]:
            print(f"{rel}:{line_no}: {name}")
        if len(hits) > 200:
            print(f"... {len(hits) - 200} more hits")
        return 2
    print("SECRET SCAN OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
