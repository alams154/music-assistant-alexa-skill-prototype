#!/usr/bin/env python3
"""Sync addons/music-assistant-skill/config.json version with the top-level VERSION file.

Usage: ./scripts/sync_version.py
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / 'VERSION'
CONFIG = ROOT / 'addons' / 'music-assistant-skill' / 'config.json'


def read_version():
    if not VERSION_FILE.exists():
        raise SystemExit(f"VERSION file not found at {VERSION_FILE}")
    text = VERSION_FILE.read_text(encoding='utf-8').strip()
    # Accept the file being wrapped in code fences (some repos do)
    if text.startswith('```'):
        # take the inner lines
        lines = [l for l in text.splitlines() if not l.strip().startswith('```')]
        text = '\n'.join(lines).strip()
    return text


def sync():
    ver = read_version()
    if not CONFIG.exists():
        raise SystemExit(f"config.json not found at {CONFIG}")

    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    old = data.get('version')
    if old == ver:
        print(f"config.json already at version {ver}")
        return 0

    data['version'] = ver
    CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding='utf-8')
    print(f"Updated config.json version: {old} -> {ver}")
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(sync())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise
