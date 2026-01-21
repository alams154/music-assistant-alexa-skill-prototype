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
from typing import List

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




def get_staged_files() -> List[str]:
    try:
        out = subprocess.check_output(['git', 'diff', '--name-only', '--cached'], stderr=subprocess.DEVNULL)
        files = out.decode('utf-8').splitlines()
        return [f for f in files if f]
    except Exception:
        # Not a git repo or no staged files
        return []


def git_add(paths):
    try:
        subprocess.run(['git', 'add'] + [str(p) for p in paths], check=True)
    except Exception:
        print('Warning: git add failed (not a git repo or git missing)', file=sys.stderr)


def main():
    # Only bump if there are staged changes that require a new image.
    staged = get_staged_files()

    # If VERSION is already staged, assume bump already happened.
    if 'VERSION' in staged:
        print('VERSION is already staged; skipping bump')
        return 0

    # Determine if any staged file should trigger an image bump
    need_bump = False
    for f in staged:
        if f == 'Dockerfile' or f.startswith('app/') or f.startswith('addons/') or f.startswith('.github/workflows/'):
            need_bump = True
            break

    if not need_bump:
        print('No image-related staged changes; skipping version bump')
        return 0

    if not VERSION_FILE.exists():
        raise SystemExit(f"VERSION file not found at {VERSION_FILE}")

    cur = read_version()
    new = bump_version_string(cur)
    if new == cur:
        print(f'Version unchanged: {cur}')
        return 0

    # Update VERSION and sync config.json
    write_version(new)
    print(f'Bumped VERSION: {cur} -> {new}')
    run_sync()

    # Stage the updated files so the user's commit includes them automatically
    addon_cfg = ROOT / 'addons' / 'music-assistant-skill' / 'config.json'
    to_stage = [VERSION_FILE]
    if addon_cfg.exists():
        to_stage.append(addon_cfg)
    git_add(to_stage)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print('Error:', e, file=sys.stderr)
        raise
