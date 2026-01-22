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
# Common non-domain file extensions to ignore when matched (e.g., openapi.json)
IGNORE_EXTS = {"yml", "yaml", "json", "md", "txt", "py", "sh", "cfg", "ini", "toml", "po", "mo", "ico", "css", "js", "html", "svg", "yml"}

# Small whitelist of common TLDs to avoid matching identifiers like `sys.exit`.
TLD_WHITELIST = {"com","net","org","io","app","de","uk","co","edu","gov","info","tv","me","xyz","us","ca","biz","online","site","tech","dev","ai"}

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
            # Get raw bytes from git to avoid UnicodeDecodeError when blobs contain binary
            out = subprocess.check_output([git, "show", f":{path}"], stderr=subprocess.DEVNULL)
            if isinstance(out, bytes):
                return out.decode('utf-8', errors='ignore')
            return str(out)
        except subprocess.CalledProcessError:
            pass
        except UnicodeDecodeError:
            # fall back to reading from working tree
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
        _, ext = os.path.splitext(p)
        # skip common image files entirely
        if ext.lower().lstrip('.') in IMAGE_EXTS:
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
        # For shell scripts, only scan quoted strings to avoid matching function names
        elif ext == '.sh':
            try:
                strings = []
                # capture heredoc blocks: <<'DELIM' ... DELIM
                heredocs = re.findall(r"<<['\"]?([A-Za-z0-9_]+)['\"]?\n(.*?)\n\1", content, re.S)
                for delim, body in heredocs:
                    # attempt to parse heredoc body as Python and extract string literals
                    try:
                        import ast
                        tree = ast.parse(body)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                                strings.append(node.value)
                            elif isinstance(node, ast.JoinedStr):
                                for val in getattr(node, 'values', []):
                                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                                        strings.append(val.value)
                        continue
                    except Exception:
                        # fallback: extract quoted strings from the heredoc body
                        found = re.findall(r"'([^']*)'|\"([^\"]*)\"", body)
                        strings.extend([a or b for a, b in found])

                # also capture top-level quoted strings in the shell script
                found_top = re.findall(r"'([^']*)'|\"([^\"]*)\"", content)
                strings.extend([a or b for a, b in found_top])

                scan_text = '\n'.join(strings) if strings else ''
            except Exception:
                scan_text = ''

        for m in DOMAIN_RE.finditer(scan_text):
            domain = m.group(0)
            # compute surrounding line for contextual checks
            line_start = scan_text.rfind('\n', 0, m.start())
            if line_start == -1:
                line_start = 0
            else:
                line_start = line_start + 1
            line_end = scan_text.find('\n', m.end())
            if line_end == -1:
                line = scan_text[line_start:]
            else:
                line = scan_text[line_start:line_end]
            # ignore matches that are image filenames (e.g. background-rose.png)
            parts = domain.rsplit('.', 1)
            if len(parts) == 2:
                ext = parts[1].lower()
                # ignore image/file extensions and other ignored file-like endings
                if ext in IMAGE_EXTS or ext in IGNORE_EXTS:
                    continue
                # require last label look like a real TLD to avoid matching code identifiers
                if ext not in TLD_WHITELIST:
                    continue

            # skip GitHub Actions expression tokens like ${{ github.actor }}
            if '${{' in line or '}}' in line:
                continue

            # for workflow files, be conservative: only flag if the line contains a URL
            if p.startswith('.github/workflows') and ('http' not in line and '://' not in line):
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
    # Repo-level allowlist file (.sensitive_allowlist)
    try:
        root = repo_root()
        allowfile = os.path.join(root, '.sensitive_allowlist')
        if os.path.exists(allowfile):
            with open(allowfile, 'r', encoding='utf-8', errors='ignore') as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    allow.add(line.lower())
    except Exception:
        pass

    # Environment variable (comma-separated) overrides/additions
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
