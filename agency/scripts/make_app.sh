#!/usr/bin/env bash
# Build "Agency.app": a Dock icon that starts the agency (panel + scheduler) and opens the dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
APP="$ROOT/Agency.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Agency</string>
<key>CFBundleDisplayName</key><string>Agency</string>
<key>CFBundleIdentifier</key><string>com.aitoolsprimer.agency</string>
<key>CFBundleVersion</key><string>1.0</string>
<key>CFBundleExecutable</key><string>agency-launcher</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><false/>
</dict></plist>
PLIST
cat > "$APP/Contents/MacOS/agency-launcher" <<LAUNCH
#!/usr/bin/env bash
cd "$ROOT"
export PATH="\$HOME/.lmstudio/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"
if ! curl -s http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
  nohup "$ROOT/.venv/bin/agency" run >> "$ROOT/state/agency.log" 2>&1 &
  for i in \$(seq 1 30); do curl -s http://127.0.0.1:8765/api/status >/dev/null 2>&1 && break; sleep 1; done
fi
open "http://127.0.0.1:8765"
LAUNCH
chmod +x "$APP/Contents/MacOS/agency-launcher"
echo "Built $APP. Drag it to the Dock. It starts the agency if needed and opens the dashboard."
