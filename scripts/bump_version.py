#!/usr/bin/env python3
"""Bump the patch version in the top-level VERSION file, sync add-on config, and stage changes.

Behavior:
- Parse VERSION as MAJOR.MINOR.PATCH plus optional suffix (e.g. -beta) and increment PATCH.
- Preserve any suffix when bumping (e.g. 0.0.2-beta -> 0.0.3-beta).
- Run `scripts/sync_version.py` to keep `addons/.../config.json` in sync.
- Stage updated files (`git add`) so the commit includes the change.

This script is intended to be run from a repo-local pre-commit hook so version
increments happen locally before push.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / 'VERSION'
SYNC_SCRIPT = ROOT / 'scripts' / 'sync_version.py'


def read_version():
    text = VERSION_FILE.read_text(encoding='utf-8').strip()
    if text.startswith('```'):
        lines = [l for l in text.splitlines() if not l.strip().startswith('```')]
        text = '\n'.join(lines).strip()
    return text


def write_version(v: str):
    VERSION_FILE.write_text(v + '\n', encoding='utf-8')


def bump_version_string(v: str) -> str:
    # Match numeric semver start: major.minor.patch and optional suffix
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)$", v)
    if not m:
        raise SystemExit(f"Unrecognized VERSION format: '{v}'")
    major, minor, patch, suffix = m.groups()
    new_patch = int(patch) + 1
    return f"{major}.{minor}.{new_patch}{suffix}"


def run_sync():
    if SYNC_SCRIPT.exists():
        try:
            # prefer python3
            py = 'python3'
            subprocess.run([py, str(SYNC_SCRIPT)], check=True)
        except Exception:
            try:
                subprocess.run(['python', str(SYNC_SCRIPT)], check=True)
            except Exception:
                # best effort; don't block commit on failure
                print('Warning: failed to run sync_version.py', file=sys.stderr)


# Intentionally do not stage files: version bumps should remain local only.


def main():
    if not VERSION_FILE.exists():
        raise SystemExit(f"VERSION file not found at {VERSION_FILE}")
    cur = read_version()
    new = bump_version_string(cur)
    if new == cur:
        print(f'Version unchanged: {cur}')
        return 0
    write_version(new)
    print(f'Bumped VERSION: {cur} -> {new}')

    # Run sync to update addon config
    run_sync()

    # Do NOT stage files — keep version bump and config changes local only.
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print('Error:', e, file=sys.stderr)
        raise
