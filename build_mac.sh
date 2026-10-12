#!/bin/bash
# Gera EtherDream-Sitter-FI.app para Apple Silicon (M1/M2/M3/M4). Rodar num Mac:
#   bash build_mac.sh
# Precisa de Python 3.12+ do python.org (traz Tk 8.6). O python3 da Apple (Tk 8.5) não serve;
# o do Homebrew precisa de `brew install python-tk`.
set -euo pipefail
cd "$(dirname "$0")"
D="$PWD"
PY="${PY:-python3}"

"$PY" -c "import tkinter, sys; assert tkinter.TkVersion >= 8.6, 'Tk %s: use o Python do python.org' % tkinter.TkVersion"
"$PY" -m venv build-mac/venv
. build-mac/venv/bin/activate
pip install --quiet pyinstaller pillow

pyinstaller --noconfirm --windowed --name "EtherDream-Sitter-FI" --icon "$D/assets/fi.ico" \
  --osx-bundle-identifier br.com.feiticaria.etherdreamsitter --target-arch arm64 \
  --distpath "$D/dist-mac" --workpath "$D/build-mac/work" --specpath "$D/build-mac" "$D/sitter_fi.py"

APP="$D/dist-mac/EtherDream-Sitter-FI.app"
PLIST="$APP/Contents/Info.plist"
# macOS 15+: pedido de permissão de Rede Local (broadcast UDP 7654 e TCP 7765 da Ether Dream)
/usr/libexec/PlistBuddy -c "Add :NSLocalNetworkUsageDescription string 'Monitorar as Ether Dream da rede local.'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSLocalNetworkUsageDescription 'Monitorar as Ether Dream da rede local.'" "$PLIST"
codesign --force --deep -s - "$APP"  # assinatura ad-hoc: obrigatória no Apple Silicon

ZIP="$D/dist-mac/EtherDream-Sitter-FI-mac-arm64.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
echo "ok: $ZIP"
