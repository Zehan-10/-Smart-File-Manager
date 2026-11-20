#!/bin/bash

set -e

INSTALL_DIR="$HOME/.local/opt/smart-file-manager"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
NAUTILUS_SCRIPTS="$HOME/.local/share/nautilus/scripts"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Find application files
if [ -f "$SCRIPT_DIR/../main" ] && [ -f "$SCRIPT_DIR/../arrange.py" ]; then
    SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "$SCRIPT_DIR/main" ] && [ -f "$SCRIPT_DIR/arrange.py" ]; then
    SOURCE_DIR="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../dist/main" ] && [ -f "$SCRIPT_DIR/../arrange.py" ]; then
    SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    echo "Error: Required application files were not found."
    exit 1
fi

if [ ! -f "$SOURCE_DIR/main" ] && [ ! -f "$SOURCE_DIR/dist/main" ]; then
    echo "Error: Application executable not found."
    exit 1
fi

if [ ! -f "$SOURCE_DIR/arrange.py" ]; then
    echo "Error: arrange.py not found."
    exit 1
fi

echo "======================================"
echo "     Smart File Manager Installer"
echo "======================================"

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$NAUTILUS_SCRIPTS"

echo "[1/5] Installing application..."

if [ -f "$SOURCE_DIR/main" ]; then
    cp "$SOURCE_DIR/main" "$INSTALL_DIR/main"
else
    cp "$SOURCE_DIR/dist/main" "$INSTALL_DIR/main"
fi

chmod +x "$INSTALL_DIR/main"
cp "$SOURCE_DIR/arrange.py" "$INSTALL_DIR/arrange.py"

if [ -f "$SOURCE_DIR/arrange_report.py" ]; then
    cp "$SOURCE_DIR/arrange_report.py" "$INSTALL_DIR/arrange_report.py"
fi

echo "[2/5] Creating application launcher..."

cat > "$BIN_DIR/smart-file-manager" <<LAUNCHER
#!/bin/bash
exec "$INSTALL_DIR/main" "\$@"
LAUNCHER

chmod +x "$BIN_DIR/smart-file-manager"

echo "[3/5] Creating desktop shortcut..."

cat > "$DESKTOP_DIR/smart-file-manager.desktop" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Smart File Manager
Comment=Smart file organization for Ubuntu
Exec=$INSTALL_DIR/main
Terminal=false
Categories=Utility;FileManager;
DESKTOP

chmod +x "$DESKTOP_DIR/smart-file-manager.desktop"

echo "[4/5] Adding Nautilus Arrange Files option..."

cat > "$NAUTILUS_SCRIPTS/Arrange Files" <<NAUTILUS
#!/bin/bash

if [ "\$#" -eq 0 ]; then
    notify-send "Smart File Manager" "Please select one or more files first."
    exit 0
fi

/usr/bin/python3 "$INSTALL_DIR/arrange.py" "\$@"
NAUTILUS

chmod +x "$NAUTILUS_SCRIPTS/Arrange Files"

echo "[5/5] Checking installation..."

if [ ! -x "$INSTALL_DIR/main" ]; then
    echo "Error: Application installation failed."
    exit 1
fi

echo
echo "======================================"
echo "Installation completed!"
echo "======================================"
echo "Application: Smart File Manager"
echo "Launcher: $BIN_DIR/smart-file-manager"
echo "Nautilus: Right-click > Scripts > Arrange Files"
echo
echo "You may need to restart Nautilus or log out and back in."
