#!/bin/bash
# Builds EtherDream-Sitter-FI.app for Apple Silicon (M1/M2/M3/M4). Run on a Mac:
#   bash build_mac.sh
# Needs Python 3.12+ from python.org (ships Tk 8.6). Apple's python3 (Tk 8.5) will not work;
# Homebrew Python needs `brew install python-tk`.
set -euo pipefail
cd "$(dirname "$0")"
D="$PWD"
PY="${PY:-python3}"

"$PY" -c "import tkinter, sys; assert tkinter.TkVersion >= 8.6, 'Tk %s: use the python.org Python' % tkinter.TkVersion"
"$PY" -m venv build-mac/venv
. build-mac/venv/bin/activate
pip install --quiet pyinstaller pillow

pyinstaller --noconfirm --windowed --name "EtherDream-Sitter-FI" --icon "$D/assets/fi.ico" \
  --osx-bundle-identifier br.com.feiticaria.etherdreamsitter --target-arch arm64 \
  --distpath "$D/dist-mac" --workpath "$D/build-mac/work" --specpath "$D/build-mac" "$D/sitter_fi.py"

APP="$D/dist-mac/EtherDream-Sitter-FI.app"
PLIST="$APP/Contents/Info.plist"
# macOS 15+: Local Network permission prompt (Ether Dream UDP 7654 broadcast and TCP 7765)
/usr/libexec/PlistBuddy -c "Add :NSLocalNetworkUsageDescription string 'Monitors Ether Dream laser DACs on the local network.'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSLocalNetworkUsageDescription 'Monitors Ether Dream laser DACs on the local network.'" "$PLIST"
codesign --force --deep -s - "$APP"  # ad-hoc signature: required on Apple Silicon

ZIP="$D/dist-mac/EtherDream-Sitter-FI-mac-arm64.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
echo "ok: $ZIP"
