#!/usr/bin/env bash
set -euo pipefail

# Creates a virtualenv at ./venv and installs requirements
# Usage: ./scripts/setup_venv.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_ROOT/venv"
REQ_FILE="$REPO_ROOT/app/lambda/py/requirements.txt"

# Allow overriding python with env var PYTHON (e.g. PYTHON=python3.11)
PYTHON_CMD="${PYTHON:-}"
if [ -z "$PYTHON_CMD" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD=python
  else
    echo "No python executable found in PATH. Install Python 3 and retry." >&2
    exit 1
  fi
fi

if [ -d "$VENV_DIR" ]; then
  echo "Virtualenv already exists at $VENV_DIR"
else
  echo "Creating virtualenv at $VENV_DIR using $PYTHON_CMD"
  "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

echo "Upgrading pip and setuptools in the virtualenv..."
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel

if [ -f "$REQ_FILE" ]; then
  echo "Installing requirements from $REQ_FILE"
  "$VENV_DIR/bin/pip" install -r "$REQ_FILE"
else
  echo "Requirements file not found at $REQ_FILE; skipping install"
fi

# Apply a small local patch to oscrypto's libcrypto version regex if needed.
# This fixes detection for OpenSSL 3.x version strings like "3.0.13".
echo "Checking for oscrypto regex fix..."
"$VENV_DIR/bin/python" - <<'PY'
import sysconfig, os, sys, re
try:
    site = sysconfig.get_paths()['purelib']
except Exception:
    print('Could not determine site-packages path; skipping patch')
    sys.exit(0)

path = os.path.join(site, 'oscrypto', '_openssl', '_libcrypto_cffi.py')
if not os.path.exists(path):
    print('oscrypto file not found at', path, '; skipping patch')
    sys.exit(0)

with open(path, 'r', encoding='utf-8') as f:
    orig_src = f.read()

    # Try multiple literal patterns then fall back to regex replace.
    old1 = "version_match = re.search('\\b(\\d\\.\\d\\.\\d[a-z]*)\\b', version_string)"
    old1_alt = 'version_match = re.search("\\b(\\d\\.\\d\\.\\d[a-z]*)\\b", version_string)'
    new1 = "version_match = re.search(r\"\\b(\\d+\\.\\d+\\.\\d+[a-z]*)\\b\", version_string)"

    old2 = "version_match = re.search('(?<=LibreSSL )(\\d\\.\\d(\\.\\d)?)\\b', version_string)"
    old2_alt = 'version_match = re.search("(?<=LibreSSL )(\\d\\.\\d(\\.\\d)?)\\b", version_string)'
    new2 = "version_match = re.search(r'(?<=LibreSSL )(\\d+\\.\\d+(?:\\.\\d+)?)\\b', version_string)"

mod_src = orig_src.replace(old1, new1).replace(old1_alt, new1).replace(old2, new2).replace(old2_alt, new2)
if mod_src == orig_src:
    # Fallback: regex-based substitutions to capture variations
      # Replace occurrences of 'version_match = re.search(...)'.
      # Use a function-based replacement: first non-LibreSSL occurrence -> new1,
      # any LibreSSL occurrence -> new2, other occurrences left unchanged.
      def _repl(m):
        s = m.group(0)
        if 'LibreSSL' in s:
          return new2
        if not hasattr(_repl, 'count'):
          _repl.count = 0
        if _repl.count == 0:
          _repl.count += 1
          return new1
        return s

      mod_src = re.sub(r"version_match\s*=\s*re\.search\([^\n]*\)", _repl, orig_src)
backup = path + '.orig'
try:
  if not os.path.exists(backup):
    with open(backup, 'w', encoding='utf-8') as b:
      b.write(orig_src)
  with open(path, 'w', encoding='utf-8') as f:
    f.write(mod_src)
  print('Patched', path, '(backup at', backup + ')')
except Exception as e:
  print('Failed to write patch:', e)
PY

echo
echo "Done. Activate the environment with:"
echo "  source $VENV_DIR/bin/activate"
