#!/usr/bin/env bash

set -euo pipefail

# Mirror the task wrapper behavior for all child processes by shimming sudo.
if [ ! -r /usr/bin/devcontainer_bootstrap ]; then
  echo "ERROR: /usr/bin/devcontainer_bootstrap not found in this devcontainer image." >&2
  exit 1
fi

shim_dir="$(mktemp -d)"
trap 'rm -rf "$shim_dir"' EXIT

cat >"$shim_dir/sudo" <<'EOF'
#!/usr/bin/env bash
exec "$@"
EOF
chmod +x "$shim_dir/sudo"

PATH="$shim_dir:$PATH" bash /usr/bin/devcontainer_bootstrap
