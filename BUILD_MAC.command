#!/bin/bash

# Floppy Manager Build Script for macOS
# This is a .command file which can be double-clicked in Finder

# Ensure we are in the script's directory
cd "$(dirname "$0")"

echo ""
echo "============================="
echo "  Floppy Manager (Mac)"
echo "============================="
echo ""

# 1. Check Python
echo "[1/3] Checking for Python..."
if ! command -v python3 &> /dev/null; then
    echo "  [X] Python 3 is NOT installed"
    echo ""
    echo "  Please install Python 3."
    echo "  Recommended: Install Homebrew (https://brew.sh) then run:"
    echo "  brew install python"
    echo ""
    read -p "Press Enter to exit..."
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
    python3 -m pip install -r requirements.txt --user
    
    if [ $? -ne 0 ]; then
        echo ""
        echo "  [!] Standard installation failed."
        echo "  Attempting with --break-system-packages (for managed environments)..."
        echo ""
        python3 -m pip install -r requirements.txt --break-system-packages --user
        
        if [ $? -ne 0 ]; then
             echo ""
             echo "  [!] Installation failed."
             echo "  Please install PySide6 and PyInstaller manually."
             echo ""
             read -p "Press Enter to exit..."
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
python3 -m PyInstaller --clean --noconfirm Floppy_Manager.spec

echo ""
# Check if build succeeded
if [ -f "dist/Floppy_Manager" ]; then
    echo "SUCCESS! Executable is in the 'dist' folder."
else
    echo "BUILD FAILED. Check messages above."
fi

echo ""
read -p "Press Enter to close..."