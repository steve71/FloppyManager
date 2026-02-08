# FAT12 Floppy Manager

## Python PyQt GUI for managing FAT12 floppy disk images

A modern GUI tool designed for managing FAT12 formatted floppy disk images (.img) used in Yamaha keyboards like the **DGX-500**, **PSR series**, and **Clavinova** or other vintage keyboards. Currently verified to work with Yamaha DGX-500.

<img width="945" height="657" alt="image" src="https://github.com/user-attachments/assets/2e93b091-ba9a-48fe-8784-29705a360fbc" />

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
- **Modern UI** - Native OS styling with Toolbar and Light/Dark themes
- **Persistent Settings** - Remembers last opened image and settings between sessions

### File Management
- **Create new blank floppy images** - standard 1.44MB FAT12 floppy images
- **Sector-Level Precision**: Writes directly to the image file without needing to mount it as a drive
- **Smart Truncation**: Automatically converts long filenames (e.g., `My_Favorite_Song.mid`) to the hardware-compliant 8.3 format (`MY_FAV~1.MID`) (Windows or no numeric tail option).
- **VFAT Filename Displayed in Table** - Displays both long filenames and 8.3 short names as well as size and type
- **Save floppy images** - save copies of floppy images
- **File Attributes** - View and edit file attributes (Read-only, Hidden, System, Archive)
- **Add files** - Drag any files or add file(s) with "Add Files" button
- **Rename files** - Windows-style inline editing (F2)
- **Delete files** - Delete selected files or all files (Del/Backspace key)
- **Extract files** - Extract selected files, all files, drag to extract, or export all to a ZIP archive
- **Format disk** - Erase all files and reset the disk to empty state
- **Sort columns** - Click any column header
- **Search/Filter** - Filter files by filename
- **Disk space** - Real-time monitoring

### Viewers & Tools
- **Boot Sector info** - View boot sector information
- **Root Directory info** - View complete root directory information with timestamps
- **FAT Viewer** - View File Allocation Table as a grid with cluster chains

### Settings
- **Confirmations** - Toggle on/off for delete/replace
- **Numeric Tails** - Toggle on/off for numeric tails (Windows-style vs. Linux truncation option)

### Keyboard Shortcuts
- **Delete/Backspace** - Delete selected files
- **Double-click** - Extract file
- **Ctrl+A** - Select all
- **Ctrl+N** - Create new image
- **Ctrl+O** - Open different image
- **Ctrl+Shift+S** - Save image as
- **Ctrl+Shift+F** - Format disk

---

## What's Included

**Essential Files:**
- `fat12_floppy_manager.py` - Main application (PyQt6)
- `fat12_handler.py` - FAT12 filesystem handler
- `gui_components.py` - GUI dialogs and viewers
- `vfat_utils.py` - VFAT/LFN utilities
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
- Or **Drag and Drop** files from the list to a folder
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

## Development & Testing

The project includes a comprehensive suite of unit tests ensuring reliability for file operations and filesystem integrity.

- **Backend Coverage:** ~99% (Core FAT12 logic, VFAT utilities)
- **Test Framework:** `pytest`

---

## License

Copyright 2026 Stephen P Smith
MIT License 
