# FloppyManager

## Python PySide6 GUI for managing FAT12 floppy disk images

A modern, easy-to-use GUI application for creating and managing raw FAT12 floppy disk images (.img) used with Gotek/FlashFloppy drives in vintage piano keyboards. Eliminates the hassle of mounting virtual disks—simply create an image, drag and drop your files, and copy to USB. Verified working with Yamaha DGX-500 + Gotek SFR1M44-U100LQD (FlashFloppy firmware)

<img width="855" height="547" alt="image" src="https://github.com/user-attachments/assets/2bc9f850-47e6-4784-ae55-221e105c8077" />

---

## Why this exists
Couldn't find a simple way to create FAT12 images, add files, and copy to USB without juggling multiple mounting/formatting tools. This does it all in one place.

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

## Build Instructions

### Windows Build Instructions

1. **Install Python 3**
   - Download and install from [python.org](https://www.python.org/downloads/)
   - Ensure **"Add Python to PATH"** is checked during installation.

2. **Install Dependencies**
   ```bash
   pip install PySide6 pyinstaller
   ```

3. **Build Application**
   - Double-click `BUILD.bat`
   - Or run in Command Prompt:
     ```cmd
     python -m PyInstaller --clean --noconfirm floppymanager.spec
     ```

   *Note: The executable will be in the `dist` folder.*

### Linux Build Instructions

1. **Install Python 3 and pip**
   ```bash
   sudo apt install python3 python3-pip
   ```

2. **Install Dependencies**
   ```bash
   pip install PySide6 pyinstaller
   ```

3. **Build Application**
   ```bash
   python3 -m PyInstaller --clean --noconfirm floppymanager.spec
   ```

### macOS Build Instructions

1. **Install Python 3**
   - Recommended: Install via Homebrew:
     ```bash
     brew install python
     ```

2. **Build Application**
   - Double-click `BUILD_MAC.command`
   - Or run in terminal:
     ```bash
     chmod +x BUILD_MAC.command
     ./BUILD_MAC.command
     ```

   *Note: The executable will be in the `dist` folder.*


## Features

### General
- **FAT12 Support** - Standard FAT12 format verified to work with Yamaha DGX-500
- **Modern UI** - Native OS styling with Toolbar and Light/Dark themes
- **Persistent Settings** - Remembers last opened image and settings between sessions

### File Management
- **Create new blank floppy images** - Supports 1.44MB, 720KB, 1.68MB DMF, 2.88MB, 1.2MB, and 360KB formats
- **Open existing floppy images** - Open and manage files on existing .img files
- **Close image** - Close the current image to return to empty state
- **Sector-Level Precision**: Writes directly to the image file without needing to mount it as a drive
- **Smart Truncation**: Automatically converts long filenames (e.g., `My_Favorite_Song.mid`) to the hardware-compliant 8.3 format (`MY_FAV~1.MID`) (Windows or no numeric tail option).
- **VFAT Filename Displayed in Table** - Displays both long filenames and 8.3 short names as well as size and type
- **Save floppy images** - save copies of floppy images
- **Directory Support** - Create, rename, and delete folders; navigate subdirectories
- **File Attributes** - View and edit file attributes (Read-only, Hidden, System, Archive)
- **Add files** - Drag any files or add file(s) with "Add Files" button
- **Drag and Drop** - Move files between folders, or hold **Ctrl** to copy
- **Rename files** - Windows-style inline editing (F2)
- **Delete files** - Delete selected files (Del/Backspace key)
- **Extract files** - Extract selected files, all files, drag to extract, or export all to a ZIP archive
- **Format disk** - Erase all files and reset the disk to empty state
- **Defragment disk** - Optimize disk by making all files contiguous
- **Sort columns** - Click any column header
- **Search/Filter** - Filter files by filename
- **Disk space** - Real-time monitoring

### Viewers & Tools
- **Boot Sector info** - View boot sector information
- **Root Directory info** - View complete root directory information with timestamps
- **FAT Viewer** - View File Allocation Table as a grid with cluster chains
- **Log Viewer** - View application logs for debugging and tracking operations

### Settings
- **Confirmations** - Toggle on/off for delete/replace
- **Numeric Tails** - Toggle on/off for numeric tails (Windows-style vs. Linux truncation option)

### Keyboard Shortcuts
- **Delete/Backspace** - Delete selected files
- **Ctrl+A** - Select all
- **Ctrl+N** - Create new image
- **Ctrl+O** - Open image
- **Ctrl+W** - Close image
- **Ctrl+X** - Cut files 
- **Ctrl+C** - Copy files 
- **Ctrl+V** - Paste files 
- **Ctrl+D** - Duplicate files 
- **Ctrl+Q** - Exit FloppyManager 
- **Ctrl+Shift+S** - Save image as
- **Ctrl+Shift+F** - Format disk
- **Ctrl+Shift+D** - Defragment disk 
- **Del/Backspace** - Delete selected files 

---

## Development & Testing

The project includes a comprehensive suite of unit tests ensuring reliability for file operations and filesystem integrity.

- **Backend Coverage:** ~99% (Core FAT12 logic, VFAT utilities)
- **Test Framework:** `pytest`

---

## License

© 2026 Stephen P Smith | MIT License | [Support Development ☕](https://ko-fi.com/steve71887)
