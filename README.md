# FAT12 Floppy Manager

## Python PyQt GUI for managing FAT12 floppy disk images

A modern GUI tool designed for managing FAT12 formatted floppy disk images (.img) used in Yamaha keyboards like the **DGX-500**, **PSR series**, and **Clavinova** or other vintage keyboards. Currently verified to work with Yamaha DGX-500.

<img width="747" height="563" alt="image" src="https://github.com/user-attachments/assets/0cf5c649-a6c9-44ee-84a0-a316d86565ad" />

---

## Why this exists
Could not find a tool like this anywhere for vintage keyboards where I could just simply create an image formatted to FAT12, drag and drop files to it and copy the image to a usb drive.  No longer need a tool like imdisk or winimage to create images, mount them in order to copy files to them and format them specifically on the Yamaha DGX-500.  This tool ensures your virtual disks are compatible with GOTEK EFI (Extensible Firmware Interface) emulators and original hardware.

---

## Yamaha DGX-500 Specific Gotek FlashFloppy Configuration

If using Gotek Flashfloppy ensure there is FF.CFG file
with the following contents:

```
display-type = oled-128x64-rotate
pin34 = nrdy
```
On the Gotek just need a jumper on S0 or S1.  A second jumper is not needed.
Verified to work on my Yamaha DGX-500 keyboard and Gotek SFR1M44-U100LQD 3.5inch USB 1.44M.  The Gotek replaced the existing floppy drive.

![Gotek in Yamaha DGX-500](https://github.com/user-attachments/assets/99f2c216-4d4d-4052-a2e7-d26f1c57cbdc)

---

## Quick Start

### 1 Check Python
```
Make sure Python is installed
```
- If not installed, install from python.org
- Install pip, Pyinstaller and PyQt6

### 2️ Build Application  
```
Double-click: BUILD.bat
```
- Builds executable

### 3️ Run Your App
```
dist\FAT12 Floppy Manager.exe
```
- Copy to Desktop
- Double-click to run

---

## Features

### General
- **FAT12 Support** - Standard FAT12 format verified to work with Yamaha DGX-500

### File Management
- **Create new blank floppy images** - standard 1.44MB FAT12 floppy images
- **Sector-Level Precision**: Writes directly to the image file without needing to mount it as a drive
- **Smart Truncation**: Automatically converts long filenames (e.g., `My_Favorite_Song.mid`) to the hardware-compliant 8.3 format (`MY_FAVOR.MID`).
- **Save floppy images** - save copies of floppy images
- **Add files** - Drag any files or add file(s) with "Add Files" button
- **Delete files** - Press Delete, Backspace key or use "Delete Selected" button
- **Extract files** - Double-click or extract with "Extract Selected" button
- **Sort columns** - Click any column header
- **Disk space** - Real-time monitoring

### Settings
- **Confirmations** - Toggle on/off for delete/replace
- **Persistent** - Settings saved between sessions
- **Modern UI** - Native OS styling with PyQt

### Keyboard Shortcuts
- **Delete/Backspace** - Delete selected files
- **Double-click** - Extract file
- **Ctrl+A** - Select all
- **Ctrl+O** - Open different image

---

## What's Included

**Essential Files:**
- `floppy_manager_pyqt.py` - Main application (PyQt6)
- `fat12_handler.py` - FAT12 filesystem handler
- `floppy_icon.ico` - Application icon
- `BUILD.bat` - Build script

---

## System Requirements

### For Building:
- Windows 10+
- Python 3.9+
- Internet connection
- 500 MB free space

### For Running:
- Windows 10+

---

## Using the Application

### Creating a Floppy Image
1. Run `FAT12 Floppy Manager.exe`
2. Select File / New Image...
3. Give it a filename and hit save

### Opening a Floppy Image
1. Run `FAT12 Floppy Manager.exe`
2. Browse to your `.img` file
3. Start managing files.

### Adding Files
- Click **Add Files** or drag and drop files
- Select any files
- Files automatically copied to floppy

### Deleting Files  
- Select files in table
- Press **Delete** or **Backspace** key
- Or click **Delete Selected** button

### Extracting Files
- **Double-click** any file
- Or select and click **Extract Selected**
- Choose destination folder

### Settings Menu
Turn off confirmations for faster workflow:
- Confirm before deleting checkbox
- Confirm before replacing checkbox

---

## Technical Details

**Format:** FAT12 filesystem  
**Capacity:** 1.44 MB (1,474,560 bytes)  
**Max Files:** 224 entries  
**Filenames:** 8.3 format (auto-converted)

**Compatible With:**
- Yamaha DGX-500
- Other Yamaha or other vintage keyboards using FAT12 floppies
- Any FAT12 1.44 MB floppy images

---

## License

Copyright 2026 Stephen P Smith
MIT License 
