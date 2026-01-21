#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import shutil

# Simple domain regex (covers typical domains like example.com, sub.example.co.uk)
DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b")

# Default allowlist (lowercase). You may add entries via the SENSITIVE_ALLOWLIST env var
# Common registry hostnames and local hosts are allowlisted by default.
DEFAULT_ALLOWLIST = {"localhost", "127.0.0.1", "ghcr.io", "streams.80s80s.de", "*.cloudfront.net"}

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".githooks"}
# Files to never scan (relative paths)
IGNORED_FILES = {"scripts/check_sensitive.py"}

# File extensions that are usually code. For these, only flag domains inside string
# literals to avoid matching code tokens like `os.path.join` or `re.compile`.
CODE_EXTS = {'.py', '.js', '.ts', '.go', '.java', '.c', '.cpp', '.rs'}
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "svg", "webp"}

def _is_within_quotes(line, start_idx, end_idx):
    # Find nearest quote char before start_idx
    left_single = line.rfind("'", 0, start_idx)
    left_double = line.rfind('"', 0, start_idx)
    # choose the nearest (max)
    left = max(left_single, left_double)
    if left == -1:
        return False
    quote_char = line[left]
    # find matching closing quote after end_idx
    right = line.find(quote_char, end_idx)
    return right != -1

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
        # skip repository-local hooks and other ignored paths
        if p.split(os.sep)[0] in IGNORED_DIRS:
            continue
        if os.path.normpath(p) in IGNORED_FILES:
            continue
        content = get_staged_content(p)
        if not content:
            continue
        _, ext = os.path.splitext(p)
        scan_text = content
        # For Python files, extract string literals using the AST to avoid matching code tokens
        if ext == '.py':
            try:
                import ast
                tree = ast.parse(content)
                strings = []
                for node in ast.walk(tree):
                    # new-style string nodes
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        strings.append(node.value)
                    # f-strings: JoinedStr contains Constant parts
                    elif isinstance(node, ast.JoinedStr):
                        for val in getattr(node, 'values', []):
                            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                                strings.append(val.value)
                if strings:
                    scan_text = '\n'.join(strings)
                else:
                    # no string literals, nothing to scan
                    scan_text = ''
            except Exception:
                # fallback to scanning content with quote heuristic
                scan_text = content

        for m in DOMAIN_RE.finditer(scan_text):
            domain = m.group(0)
            # ignore matches that are image filenames (e.g. background-rose.png)
            parts = domain.rsplit('.', 1)
            if len(parts) == 2 and parts[1].lower() in IMAGE_EXTS:
                continue
            if is_allowed(domain, allowlist):
                continue
            findings.append((p, domain))
    return findings

def is_allowed(domain, allowlist):
    d = domain.lower()
    for a in allowlist:
        a = a.lower()
        if a.startswith('*.'):
            # wildcard subdomain match
            if d == a[2:] or d.endswith(a[1:]):
                return True
        else:
            if d == a:
                return True
    return False

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
