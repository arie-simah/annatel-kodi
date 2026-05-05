#!/usr/bin/env bash
# Installs the service.annatel addon into the local Kodi addons directory.
# Usage: bash install.sh [KODI_ADDONS_DIR]
# Default target: ~/.kodi/addons/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON_SRC="${SCRIPT_DIR}/addon/service.annatel"
TARGET_DIR="${1:-${HOME}/.kodi/addons}"
DEST="${TARGET_DIR}/service.annatel"

if [[ ! -f "${ADDON_SRC}/addon.xml" ]]; then
    echo "ERROR: Cannot find addon source at ${ADDON_SRC}" >&2
    exit 1
fi

mkdir -p "${TARGET_DIR}"

if [[ -d "${DEST}" ]]; then
    echo "Removing existing installation at ${DEST}"
    rm -rf "${DEST}"
fi

cp -r "${ADDON_SRC}" "${DEST}"
echo "Installed to ${DEST}"
echo ""
echo "Next steps in Kodi:"
echo "  1. Go to Add-ons > My add-ons > Services > Annatel IPTV"
echo "     (if not listed: Add-ons > Install from zip / Enable Unknown Sources first)"
echo "  2. Enable the addon and open its Settings"
echo "  3. Enter your Annatel username and password"
echo "  4. The TV menu will populate automatically within a few seconds"
