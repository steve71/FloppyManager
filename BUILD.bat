@echo off
cd /d "%~dp0"
REM FAT12 Floppy Manager

echo.
echo =============================
echo   FAT12 Floppy Manager
echo =============================
echo.

REM Check Python
echo [1/3] Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   [X] Python is NOT installed
    echo.
    echo   SOLUTION:
    echo   1. Go to: https://www.python.org/downloads/
    echo   2. Download Python 3.9 or later
    echo   3. Run installer
    echo   4. [CHECK] "Add Python to PATH"
    echo   5. Click "Install Now"
    echo   6. Restart this script
    echo.
    pause
    exit /b 1
) else (
    python --version
    echo   [OK] Python is installed
)

echo.
echo [2/3] Checking required packages...
python -c "import PySide6; import PyInstaller; import win32ctypes" >nul 2>&1
if errorlevel 1 (
    echo   Packages missing. Installing...
    echo   This may take a minute...
    python -m pip install PySide6 pyinstaller pywin32-ctypes --quiet --disable-pip-version-check
    if errorlevel 1 (
        echo.
        echo   Warning: Quick install failed, trying with verbose output...
        echo.
        python -m pip install PySide6 pyinstaller pywin32-ctypes
        if errorlevel 1 (
            echo.
            echo   [!] Standard installation failed.
            echo   Attempting with --break-system-packages ^(for managed environments^)...
            echo.
            python -m pip install PySide6 pyinstaller pywin32-ctypes --break-system-packages
            if errorlevel 1 (
                echo.
                echo   [!] Installation failed or restricted.
                echo.
                echo   Attempting to proceed with build anyway...
                echo   ^(If build fails, please install PySide6, PyInstaller, and pywin32-ctypes manually^)
                echo.
            )
        )
    )
    echo   [OK] Package check complete
) else (
    echo   [OK] Packages already installed.
)

echo.
echo [3/3] Building executable...
echo Please wait...
echo.

python -m PyInstaller --clean --noconfirm ^
    --name "FAT12 Floppy Manager" ^
    --onefile ^
    --windowed ^
    --icon=floppy_icon.ico ^
    --add-data "floppy_icon.ico;." ^
    fat12_floppy_manager.py

echo.
REM Check if build succeeded
if exist "dist\FAT12 Floppy Manager.exe" (
    echo ================================================================
    echo   SUCCESS - Build Complete!
    echo ================================================================
    echo.
    echo   Your executable is ready!
    echo   Location: dist\FAT12 Floppy Manager.exe
    echo.
    echo   File size: ~30 MB (includes PySide6 runtime^)
    echo.
    echo   NEXT STEPS:
    echo   1. Open the "dist" folder
    echo   2. Copy "FAT12 Floppy Manager.exe" to your Desktop
    echo   3. Double-click to run
    echo   4. Right-click exe and Create shortcut (optional^)
    echo.
    echo   The .exe is PORTABLE - copy it to any Windows PC!
    echo   No Python or installation needed to run it.
    echo.
    goto :build_success
)

echo ================================================================
echo   BUILD FAILED
echo ================================================================
echo.
echo   Please check error messages above.
echo.
echo   Common issues:
echo   - Missing files (fat12_floppy_manager.py, fat12_handler.py)
echo   - Antivirus blocking PyInstaller
echo   - Insufficient disk space (need ~500 MB)
echo.
echo   Try:
echo   - Run as administrator
echo   - Temporarily disable antivirus
echo   - Make sure all files are in same folder
echo.

:build_success
pause
