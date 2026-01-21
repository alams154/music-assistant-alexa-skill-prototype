#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import shutil

# Simple domain regex (covers typical domains like example.com, sub.example.co.uk)
DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b", re.I)

# Default allowlist (lowercase). You may add entries via the SENSITIVE_ALLOWLIST env var
DEFAULT_ALLOWLIST = {"localhost", "127.0.0.1"}

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}

def repo_root():
    # Find repository root by walking up until we find .git or stop at filesystem root
    cur = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.getcwd()
        cur = parent

def get_git_executable():
    return shutil.which("git")

def get_staged_files():
    git = get_git_executable()
    if git:
        try:
            out = subprocess.check_output([
                git, "diff", "--cached", "--name-only", "--diff-filter=ACM"
            ], text=True)
            return [f for f in out.splitlines() if f]
        except subprocess.CalledProcessError:
            pass

    # Fallback: walk repository and return likely text files
    root = repo_root()
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune ignored directories
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for fn in filenames:
            # skip binary-like or large files by extension
            if fn.endswith(('.png', '.jpg', '.jpeg', '.gif', '.pb', '.so', '.dll')):
                continue
            path = os.path.relpath(os.path.join(dirpath, fn), start=os.getcwd())
            files.append(path)
    return files

def get_staged_content(path):
    git = get_git_executable()
    if git:
        try:
            return subprocess.check_output([git, "show", f":{path}"], text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            pass

    # Fallback: read file from working tree
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""

def scan_files(paths, allowlist):
    findings = []
    for p in paths:
        content = get_staged_content(p)
        if not content:
            continue
        for m in DOMAIN_RE.finditer(content):
            domain = m.group(0)
            if domain.lower() in allowlist:
                continue
            findings.append((p, domain))
    return findings

def build_allowlist():
    allow = set(DEFAULT_ALLOWLIST)
    env = os.environ.get("SENSITIVE_ALLOWLIST")
    if env:
        for part in env.split(','):
            p = part.strip().lower()
            if p:
                allow.add(p)
    return allow

def main(args):
    paths = args if args else get_staged_files()
    if not paths:
        return 0
    allowlist = build_allowlist()
    bad = scan_files(paths, allowlist)
    if bad:
        print("Error: sensitive domain names detected:")
        reported = set()
        for path, domain in bad:
            key = (path, domain)
            if key in reported:
                continue
            reported.add(key)
            print(f" - {path}: {domain}")
        print("\nIf these are expected, add them to the allowlist via the SENSITIVE_ALLOWLIST env var or commit with --no-verify.")
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
