#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ADDON_DIR="${REPO_ROOT}/addons/music-assistant-skill"
ADDON_APP_DIR="${ADDON_DIR}/app"
ADDON_SCRIPTS_DIR="${ADDON_DIR}/scripts"
ADDON_ASSETS_DIR="${ADDON_DIR}/assets"
STAGED_MARKER="${ADDON_DIR}/.staged-build-context"
CREATED_APP_DIR=0
CREATED_SCRIPTS_DIR=0
CREATED_ASSETS_DIR=0

# Home Assistant builds local addons with the addon directory as Docker context.
# Stage runtime source files into that context before invoking supervisor_run.
sync_addon_build_context() {
    if [ ! -d "${ADDON_APP_DIR}" ]; then
        CREATED_APP_DIR=1
    fi
    if [ ! -d "${ADDON_SCRIPTS_DIR}" ]; then
        CREATED_SCRIPTS_DIR=1
    fi
    if [ ! -d "${ADDON_ASSETS_DIR}" ]; then
        CREATED_ASSETS_DIR=1
    fi

    mkdir -p "${ADDON_APP_DIR}" "${ADDON_SCRIPTS_DIR}" "${ADDON_ASSETS_DIR}"
    rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
        "${REPO_ROOT}/app/" "${ADDON_APP_DIR}/"

    install -m 0755 "${REPO_ROOT}/scripts/ask_create_skill.sh" "${ADDON_SCRIPTS_DIR}/ask_create_skill.sh"
    install -m 0755 "${REPO_ROOT}/scripts/find_skills_to_delete.py" "${ADDON_SCRIPTS_DIR}/find_skills_to_delete.py"
    install -m 0644 "${REPO_ROOT}/scripts/build_skill_manifest.py" "${ADDON_SCRIPTS_DIR}/build_skill_manifest.py"

    rsync -a --delete "${REPO_ROOT}/assets/" "${ADDON_ASSETS_DIR}/"

    printf 'staged\n' > "${STAGED_MARKER}"
}

cleanup_addon_build_context() {
    [ -f "${STAGED_MARKER}" ] || return 0

    rm -f "${STAGED_MARKER}"
    if [ "${CREATED_APP_DIR}" -eq 1 ]; then
        rm -rf "${ADDON_APP_DIR}"
    fi
    if [ "${CREATED_SCRIPTS_DIR}" -eq 1 ]; then
        rm -rf "${ADDON_SCRIPTS_DIR}"
    fi
    if [ "${CREATED_ASSETS_DIR}" -eq 1 ]; then
        rm -rf "${ADDON_ASSETS_DIR}"
    fi
}

clear_stale_staging() {
    [ -f "${STAGED_MARKER}" ] || return 0
    rm -rf "${ADDON_APP_DIR}" "${ADDON_SCRIPTS_DIR}" "${ADDON_ASSETS_DIR}" "${STAGED_MARKER}"
}

sudo() {
    "$@"
}

clear_stale_staging
sync_addon_build_context
trap cleanup_addon_build_context EXIT

source /usr/bin/supervisor_run