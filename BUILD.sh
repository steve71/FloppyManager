#!/bin/bash

# FAT12 Floppy Manager Build Script for Linux

# Ensure we are in the script's directory
cd "$(dirname "$0")"

echo ""
echo "============================="
echo "  FAT12 Floppy Manager"
echo "============================="
echo ""

# 1. Check Python
echo "[1/3] Checking for Python..."
if ! command -v python3 &> /dev/null; then
    echo "  [X] Python 3 is NOT installed"
    echo ""
    echo "  Please install Python 3 using your package manager."
    echo "  Example: sudo apt install python3 python3-pip"
    echo ""
    exit 1
else
    python3 --version
    echo "  [OK] Python 3 is installed"
fi

# 2. Check/Install Dependencies
echo ""
echo "[2/3] Checking required packages..."
# Check if modules can be imported
if ! python3 -c "import PySide6; import PyInstaller" &> /dev/null; then
    echo "  Packages missing. Installing..."
    
    # Try installing to user site
    python3 -m pip install PySide6 pyinstaller --user
    
    if [ $? -ne 0 ]; then
        echo ""
        echo "  [!] Standard installation failed."
        echo "  Attempting with --break-system-packages (for managed environments)..."
        echo ""
        python3 -m pip install PySide6 pyinstaller --break-system-packages --user
        
        if [ $? -ne 0 ]; then
             echo ""
             echo "  [!] Installation failed."
             echo "  Please install PySide6 and PyInstaller manually."
             echo "  Or use a virtual environment (recommended)."
             exit 1
        fi
    fi
    echo "  [OK] Package check complete"
else
    echo "  [OK] Packages already installed."
fi

# 3. Build
echo ""
echo "[3/3] Building executable..."
echo "Please wait..."
echo ""

# Clean previous build artifacts
rm -rf build dist *.spec

# Run PyInstaller
# Note: Using ':' as separator for --add-data on Linux
python3 -m PyInstaller --clean --noconfirm \
    --name "FAT12_Floppy_Manager" \
    --onefile \
    --windowed \
    --icon=floppy_icon.ico \
    --add-data "floppy_icon.ico:." \
    fat12_floppy_manager.py

echo ""
# Check if build succeeded
if [ -f "dist/FAT12_Floppy_Manager" ]; then
    echo "================================================================"
    echo "  SUCCESS - Build Complete!"
    echo "================================================================"
    echo ""
    echo "  Your executable is ready!"
    echo "  Location: dist/FAT12_Floppy_Manager"
    echo ""
    echo "  To run:"
    echo "  ./dist/FAT12_Floppy_Manager"
    echo ""
else
    echo "================================================================"
    echo "  BUILD FAILED"
    echo "================================================================"
    echo "  Please check error messages above."
fi