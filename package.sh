#!/usr/bin/env bash
# Creates a Kodi-installable zip for the service.annatel addon.
# Usage: bash package.sh
# Output: dist/service.annatel-<version>.zip

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON_SRC="${SCRIPT_DIR}/addon/service.annatel"
DIST_DIR="${SCRIPT_DIR}/dist"

# Read version from addon.xml (the <addon> element's version attribute,
# not the XML declaration's version="1.0" on the first line)
VERSION="$(python3 -c "import xml.etree.ElementTree as ET; print(ET.parse('${ADDON_SRC}/addon.xml').getroot().get('version'))")"

ZIP_NAME="service.annatel-${VERSION}.zip"
ZIP_PATH="${DIST_DIR}/${ZIP_NAME}"

mkdir -p "${DIST_DIR}"

# Remove previous build
rm -f "${ZIP_PATH}"

# Kodi requires the zip to contain a top-level folder named after the addon id
cd "${SCRIPT_DIR}/addon"
zip -r "${ZIP_PATH}" service.annatel/

echo ""
echo "Created: ${ZIP_PATH}"
echo ""
echo "Install on Android TV:"
echo "  1. Copy ${ZIP_NAME} to a USB stick or serve it on your network"
echo "  2. In Kodi: Settings > System > Add-ons > Unknown sources = ON"
echo "  3. Add-ons > Install from zip > navigate to ${ZIP_NAME}"
echo "  4. Add-ons > My add-ons > Services > Annatel IPTV > Enable"
echo "  5. Configure with your Annatel username and password"
