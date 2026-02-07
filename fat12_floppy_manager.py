#!/usr/bin/env python3

# Copyright (c) 2026 Stephen P Smith
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
FAT12 Floppy Disk Image Manager
A modern GUI tool for managing files on FAT12 floppy disk images with VFAT LFN support
"""

import sys
import os
import shutil
from pathlib import Path
from typing import Optional

from vfat_utils import generate_83_name


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QLabel, QStatusBar, QMenuBar, QMenu, QHeaderView,
    QDialog, QTabWidget
)
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import QIcon, QAction, QKeySequence, QActionGroup, QPalette, QColor

# Import the FAT12 handler
from fat12_handler import FAT12Image
from gui_components import BootSectorViewer, RootDirectoryViewer, FATViewer

class FloppyManagerWindow(QMainWindow):
    """Main window for the floppy manager"""

    def __init__(self, image_path: Optional[str] = None):
        super().__init__()

        # Settings
        self.settings = QSettings('FAT12FloppyManager', 'Settings')
        self.confirm_delete = self.settings.value('confirm_delete', True, type=bool)
        self.confirm_replace = self.settings.value('confirm_replace', True, type=bool)
        self.use_numeric_tail = self.settings.value('use_numeric_tail', False, type=bool)
        self.theme_mode = self.settings.value('theme_mode', 'light', type=str)

        # Restore window geometry if available
        geometry = self.settings.value('window_geometry')
        if geometry:
            self.restoreGeometry(geometry)

        self.image_path = image_path
        self.image = None

        self.setup_ui()
        
        # Apply theme after UI is set up
        self.apply_theme(self.theme_mode)

        # Load image if provided or restore last image
        if image_path:
            self.load_image(image_path)
        else:
            # Try to restore last opened image
            last_image = self.settings.value('last_image_path', '')
            if last_image and Path(last_image).exists():
                self.load_image(last_image)
            else:
                # No image loaded, show empty state
                self.status_bar.showMessage("No image loaded. Create new or open existing image.")

    def setup_ui(self):
        """Create the user interface"""
        self.setWindowTitle("FAT12 Floppy Manager")
        self.setGeometry(400, 200, 620, 500)

        # Enable drag and drop
        self.setAcceptDrops(True)

        # Set window icon if available
        icon_path = Path(__file__).parent / 'floppy_icon.ico'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Create menu bar
        self.create_menus()

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        layout = QVBoxLayout(central_widget)

        # Top toolbar
        toolbar = QHBoxLayout()

        # Buttons
        self.add_btn = QPushButton("📁 Add Files")
        self.add_btn.setToolTip("Add files to the floppy image")
        self.add_btn.clicked.connect(self.add_files)

        self.extract_btn = QPushButton("💾 Extract Selected")
        self.extract_btn.setToolTip("Extract selected files to your computer")
        self.extract_btn.clicked.connect(self.extract_selected)

        self.delete_btn = QPushButton("🗑️ Delete Selected")
        self.delete_btn.setToolTip("Delete selected files (or press Delete key)")
        self.delete_btn.clicked.connect(self.delete_selected)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setToolTip("Reload the file list")
        self.refresh_btn.clicked.connect(self.refresh_file_list)

        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.extract_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addStretch()

        # Info label
        self.info_label = QLabel()
        self.info_label.setStyleSheet("QLabel { color: #555; font-weight: bold; }")
        toolbar.addWidget(self.info_label)

        layout.addLayout(toolbar)

        # File table - now with 5 columns
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Filename', 'Short Name (8.3)', 'Size', 'Type', 'Index'])

        # Hide the index column (used internally)
        self.table.setColumnHidden(4, True)

        # Configure table
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Set column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Filename
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Short name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Size
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Type

        # Double-click to extract
        self.table.doubleClicked.connect(self.extract_selected)

        # Context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.table)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready | Tip: Drag and drop files to add them to the floppy")

        # Keyboard shortcuts
        self.table.keyPressEvent = self.table_key_press

    def show_context_menu(self, position):
        """Show context menu for table"""
        if not self.image:
            return

        selected_rows = set(item.row() for item in self.table.selectedItems())
        if not selected_rows:
            return

        menu = QMenu()
        
        extract_action = QAction("Extract", self)
        extract_action.triggered.connect(self.extract_selected)
        menu.addAction(extract_action)
                
        menu.addSeparator()
        
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self.delete_selected)
        menu.addAction(delete_action)
        
        menu.exec(self.table.viewport().mapToGlobal(position))

    def create_menus(self):
        """Create menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        new_action = QAction("&New Image...", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.setToolTip("Create a new blank floppy disk image")
        new_action.triggered.connect(self.create_new_image)
        file_menu.addAction(new_action)

        open_action = QAction("&Open Image...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_image)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        save_as_action = QAction("Save Image &As...", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.setToolTip("Save a copy of the current image")
        save_as_action.triggered.connect(self.save_image_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        format_action = QAction("&Format Disk...", self)
        format_action.setToolTip("Erase all files and reset the disk to empty state")
        format_action.triggered.connect(self.format_disk)
        file_menu.addAction(format_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        boot_sector_action = QAction("&Boot Sector Information...", self)
        boot_sector_action.setToolTip("View complete boot sector details")
        boot_sector_action.triggered.connect(self.show_boot_sector_info)
        view_menu.addAction(boot_sector_action)

        root_dir_action = QAction("&Root Directory Information...", self)
        root_dir_action.setToolTip("View complete root directory details")
        root_dir_action.triggered.connect(self.show_root_directory_info)
        view_menu.addAction(root_dir_action)

        fat_viewer_action = QAction("&File Allocation Table...", self)
        fat_viewer_action.setToolTip("View File Allocation Table as a grid")
        fat_viewer_action.triggered.connect(self.show_fat_viewer)
        view_menu.addAction(fat_viewer_action)

        # Settings menu
        settings_menu = menubar.addMenu("&Settings")

        self.confirm_delete_action = QAction("Confirm before deleting", self)
        self.confirm_delete_action.setCheckable(True)
        self.confirm_delete_action.setChecked(self.confirm_delete)
        self.confirm_delete_action.triggered.connect(self.toggle_confirm_delete)
        settings_menu.addAction(self.confirm_delete_action)

        self.confirm_replace_action = QAction("Confirm before replacing files", self)
        self.confirm_replace_action.setCheckable(True)
        self.confirm_replace_action.setChecked(self.confirm_replace)
        self.confirm_replace_action.triggered.connect(self.toggle_confirm_replace)
        settings_menu.addAction(self.confirm_replace_action)

        settings_menu.addSeparator()

        self.use_numeric_tail_action = QAction("Use numeric tails for 8.3 names (~1, ~2, etc.)", self)
        self.use_numeric_tail_action.setCheckable(True)
        self.use_numeric_tail_action.setChecked(self.use_numeric_tail)
        self.use_numeric_tail_action.setToolTip("When enabled, uses Windows-style numeric tails (e.g., LONGFI~1.TXT). When disabled, simply truncates names (like Linux nonumtail option).")
        self.use_numeric_tail_action.triggered.connect(self.toggle_numeric_tail)
        settings_menu.addAction(self.use_numeric_tail_action)

        settings_menu.addSeparator()

        # Theme submenu
        theme_menu = settings_menu.addMenu("Theme")
        
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        
        self.theme_light_action = QAction("Light", self)
        self.theme_light_action.setCheckable(True)
        self.theme_light_action.setActionGroup(self.theme_group)
        self.theme_light_action.triggered.connect(lambda: self.change_theme('light'))
        theme_menu.addAction(self.theme_light_action)
        
        self.theme_dark_action = QAction("Dark", self)
        self.theme_dark_action.setCheckable(True)
        self.theme_dark_action.setActionGroup(self.theme_group)
        self.theme_dark_action.triggered.connect(lambda: self.change_theme('dark'))
        theme_menu.addAction(self.theme_dark_action)
        
        # Set initial theme selection
        if self.theme_mode == 'dark':
            self.theme_dark_action.setChecked(True)
        else:
            self.theme_light_action.setChecked(True)

        settings_menu.addSeparator()

        reset_settings_action = QAction("Reset Settings to Default...", self)
        reset_settings_action.setToolTip("Reset all settings to their default values")
        reset_settings_action.triggered.connect(self.reset_settings)
        settings_menu.addAction(reset_settings_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def toggle_confirm_delete(self):
        """Toggle delete confirmation"""
        self.confirm_delete = self.confirm_delete_action.isChecked()
        self.settings.setValue('confirm_delete', self.confirm_delete)

    def toggle_confirm_replace(self):
        """Toggle replace confirmation"""
        self.confirm_replace = self.confirm_replace_action.isChecked()
        self.settings.setValue('confirm_replace', self.confirm_replace)

    def toggle_numeric_tail(self):
        """Toggle numeric tail usage for 8.3 name generation"""
        self.use_numeric_tail = self.use_numeric_tail_action.isChecked()
        self.settings.setValue('use_numeric_tail', self.use_numeric_tail)
        
        # Show info message
        if self.use_numeric_tail:
            mode_desc = "Windows-style numeric tails enabled (e.g., LONGFI~1.TXT)"
        else:
            mode_desc = "Simple truncation mode enabled (like Linux nonumtail)"
        
        self.status_bar.showMessage(f"8.3 name generation: {mode_desc}")

    def change_theme(self, theme_mode):
        """Change the application theme"""
        self.theme_mode = theme_mode
        self.settings.setValue('theme_mode', theme_mode)
        self.apply_theme(theme_mode)
    
    def apply_theme(self, theme_mode):
        """Apply the specified theme to the application"""
        app = QApplication.instance()
        
        if theme_mode == 'dark':
            # Dark theme
            app.setStyleSheet("")
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
            palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(127, 127, 127))
            app.setPalette(palette)
            
        else:  # light (default)
            # Light theme
            app.setStyleSheet("")
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
            palette.setColor(QPalette.ColorRole.Link, QColor(0, 0, 255))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            app.setPalette(palette)

    def reset_settings(self):
        """Reset all settings to their default values"""
        response = QMessageBox.question(
            self,
            "Reset Settings",
            "Reset all settings to their default values?\n\n"
            "This will reset:\n"
            "• Confirmation dialogs (enabled)\n"
            "• Numeric tail mode (disabled)\n"
            "• Theme (Light)\n"
            "• Clusters per row (32)\n"
            "• Window size and position\n\n"
            "The application will need to restart for all changes to take effect.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if response == QMessageBox.StandardButton.No:
            return
        
        # Clear all settings
        self.settings.clear()
        
        # Set defaults
        self.confirm_delete = True
        self.confirm_replace = True
        self.use_numeric_tail = False
        self.theme_mode = 'light'
        
        # Update UI to reflect defaults
        self.confirm_delete_action.setChecked(True)
        self.confirm_replace_action.setChecked(True)
        self.use_numeric_tail_action.setChecked(False)
        self.theme_light_action.setChecked(True)
        
        # Apply light theme
        self.apply_theme('light')
        
        # Save the default settings
        self.settings.setValue('confirm_delete', True)
        self.settings.setValue('confirm_replace', True)
        self.settings.setValue('use_numeric_tail', False)
        self.settings.setValue('theme_mode', 'light')
        self.settings.setValue('clusters_per_row', 32)
        
        QMessageBox.information(
            self,
            "Settings Reset",
            "Settings have been reset to default values.\n\n"
            "Note: Window size and position will be reset when you restart the application."
        )
        
        self.status_bar.showMessage("Settings reset to defaults")

    def table_key_press(self, event):
        """Handle keyboard events in the table"""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        elif event.key() == Qt.Key.Key_Escape:
            # Cancel editing if in progress
            if self.currently_editing and self.original_name_before_edit:
                current_item = self.table.currentItem()
                if current_item and current_item.column() == 0:
                    current_item.setText(self.original_name_before_edit)
                    self.currently_editing = False
                    self.original_name_before_edit = None
                    self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            # Call the original keyPressEvent
            QTableWidget.keyPressEvent(self.table, event)
        else:
            # Call the original keyPressEvent
            QTableWidget.keyPressEvent(self.table, event)

    def load_image(self, filepath: str):
        """Load a floppy disk image"""
        try:
            self.image = FAT12Image(filepath)
            self.image_path = filepath
            self.setWindowTitle(f"FAT12 Floppy Manager - {Path(filepath).name}")

            # Save as last opened image
            self.settings.setValue('last_image_path', filepath)

            self.refresh_file_list()
            self.status_bar.showMessage(f"Loaded: {Path(filepath).name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load image: {e}")
            self.image = None
            self.image_path = None
            self.setWindowTitle("FAT12 Floppy Manager")

    def refresh_file_list(self):
        """Refresh the file list from the image"""
        self.table.setRowCount(0)

        if not self.image:
            self.info_label.setText("No image loaded")
            return

        try:
            entries = self.image.read_root_directory()

            for entry in entries:
                if not entry['is_dir']:
                    row = self.table.rowCount()
                    self.table.insertRow(row)

                    # Filename (long name) - EDITABLE
                    filename_item = QTableWidgetItem(entry['name'])
                    filename_item.setFlags(filename_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 0, filename_item)

                    # Short name (8.3) - READ ONLY
                    short_name_item = QTableWidgetItem(entry['short_name'])
                    short_name_item.setFlags(short_name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 1, short_name_item)

                    # Size - READ ONLY
                    size_str = f"{entry['size']:,} bytes"
                    size_item = QTableWidgetItem(size_str)
                    size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 2, size_item)

                    # Type - READ ONLY
                    file_type = Path(entry['name']).suffix.upper().lstrip('.')
                    type_item = QTableWidgetItem(file_type)
                    type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 3, type_item)

                    # Index (hidden) - READ ONLY
                    index_item = QTableWidgetItem(str(entry['index']))
                    index_item.setFlags(index_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 4, index_item)

            # Update info
            free_clusters = len(self.image.find_free_clusters())
            free_space = free_clusters * self.image.bytes_per_cluster
            self.info_label.setText(f"{len(entries)} files | {free_space:,} bytes free")
            self.status_bar.showMessage(f"Loaded {len(entries)} files")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read directory: {e}")

    def show_boot_sector_info(self):
        """Show boot sector information"""
        if not self.image:
            QMessageBox.information(
                self, 
                "No Image Loaded", 
                "Please load or create a floppy image first."
            )
            return
        
        viewer = BootSectorViewer(self.image, self)
        viewer.exec()

    def show_root_directory_info(self):
        """Show complete root directory information"""
        if not self.image:
            QMessageBox.information(
                self, 
                "No Image Loaded", 
                "Please load or create a floppy image first."
            )
            return
        
        viewer = RootDirectoryViewer(self.image, self)
        viewer.exec()

    def show_fat_viewer(self):
        """Show File Allocation Table viewer"""
        if not self.image:
            QMessageBox.information(
                self, 
                "No Image Loaded", 
                "Please load or create a floppy image first."
            )
            return
        
        viewer = FATViewer(self.image, self)
        viewer.exec()

    def add_files(self):
        """Add files to the image via file dialog"""
        if not self.image:
            QMessageBox.information(
                self,
                "No Image Loaded",
                "Please create a new image or open an existing one first."
            )
            return

        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files to add",
            "",
            "All files (*.*)"
        )

        if not filenames:
            return

        self.add_files_from_list(filenames)

    def add_files_from_list(self, filenames: list):
        """Add files from a list of file paths (used by both dialog and drag-drop)"""
        if not self.image:
            return

        success_count = 0
        fail_count = 0

        for filepath in filenames:
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()

                path_obj = Path(filepath)
                original_name = path_obj.name

                # Get existing 8.3 names
                existing_83_names = self.image.get_existing_83_names()
                
                # Generate the 8.3 name that will be used
                short_name_83 = generate_83_name(
                    original_name, 
                    existing_83_names, 
                    self.use_numeric_tail
                )
                
                # Format 8.3 name for display (add dot back)
                short_display = short_name_83[:8].strip() + '.' + short_name_83[8:11].strip()
                short_display = short_display.rstrip('.')

                # Check if file already exists
                existing_entries = self.image.read_root_directory()
                collision_entry = None
                
                # Check both long name and short name
                for e in existing_entries:
                    e_short_83 = e['short_name'].replace('.', '').ljust(11).upper()
                    if e_short_83 == short_name_83:
                        collision_entry = e
                        break

                if collision_entry:
                    if self.confirm_replace:
                        msg = f"The file '{original_name}' will be saved with 8.3 name '{short_display}', which already exists"
                        if collision_entry['name'] != collision_entry['short_name']:
                            msg += f" (long name: '{collision_entry['name']}')"
                        msg += ".\n\nDo you want to replace it?"
                        
                        response = QMessageBox.question(
                            self,
                            "File Exists",
                            msg,
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if response == QMessageBox.StandardButton.No:
                            continue

                    # Delete the existing file
                    self.image.delete_file(collision_entry)

                # Write the new file
                if self.image.write_file_to_image(original_name, data, self.use_numeric_tail):
                    success_count += 1
                else:
                    fail_count += 1
                    QMessageBox.warning(
                        self,
                        "Error",
                        f"Failed to write {original_name} - disk may be full"
                    )

            except Exception as e:
                fail_count += 1
                QMessageBox.critical(self, "Error", f"Failed to add {Path(filepath).name}: {e}")

        self.refresh_file_list()

        if success_count > 0:
            self.status_bar.showMessage(f"Added {success_count} file(s)")
        if fail_count > 0:
            QMessageBox.warning(self, "Warning", f"Failed to add {fail_count} file(s)")

    def extract_selected(self):
        """Extract selected files"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return

        selected_rows = set(item.row() for item in self.table.selectedItems())

        if not selected_rows:
            QMessageBox.information(self, "Info", "Please select files to extract")
            return

        save_dir = QFileDialog.getExistingDirectory(self, "Select folder to save files")
        if not save_dir:
            return

        entries = self.image.read_root_directory()
        success_count = 0

        for row in selected_rows:
            entry_index = int(self.table.item(row, 4).text())
            entry = next((e for e in entries if e['index'] == entry_index), None)

            if entry:
                try:
                    data = self.image.extract_file(entry)
                    # Use the long filename (original name) when extracting
                    output_path = os.path.join(save_dir, entry['name'])

                    with open(output_path, 'wb') as f:
                        f.write(data)

                    success_count += 1
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to extract {entry['name']}: {e}")

        if success_count > 0:
            self.status_bar.showMessage(f"Extracted {success_count} file(s) to {save_dir}")
            QMessageBox.information(self, "Success", f"Extracted {success_count} file(s)")

    def delete_selected(self):
        """Delete selected files"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return

        selected_rows = set(item.row() for item in self.table.selectedItems())

        if not selected_rows:
            QMessageBox.information(self, "Info", "Please select files to delete")
            return

        if self.confirm_delete:
            response = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Delete {len(selected_rows)} file(s) from the disk image?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if response == QMessageBox.StandardButton.No:
                return

        entries = self.image.read_root_directory()
        success_count = 0

        for row in selected_rows:
            entry_index = int(self.table.item(row, 4).text())
            entry = next((e for e in entries if e['index'] == entry_index), None)

            if entry:
                if self.image.delete_file(entry):
                    success_count += 1
                else:
                    QMessageBox.critical(self, "Error", f"Failed to delete {entry['name']}")

        self.refresh_file_list()

        if success_count > 0:
            self.status_bar.showMessage(f"Deleted {success_count} file(s)")

    def create_new_image(self):
        """Create a new blank floppy disk image"""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Create New Floppy Image",
            "",
            "Floppy images (*.img);;All files (*.*)"
        )

        if not filename:
            return

        # Ensure .img extension
        if not filename.lower().endswith('.img'):
            filename += '.img'

        try:
            # Create a blank 1.44MB floppy image using the handler
            FAT12Image.create_empty_image(filename)

            # Load the new image
            self.load_image(filename)

            QMessageBox.information(
                self,
                "Success",
                f"Created new floppy image:\n{Path(filename).name}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create image: {e}")

    def save_image_as(self):
        """Save a copy of the current floppy image"""
        if not self.image:
            QMessageBox.information(self, "Info", "No image loaded to save")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Image As",
            Path(self.image_path).name if self.image_path else "floppy.img",
            "Floppy images (*.img);;All files (*.*)"
        )

        if not filename:
            return

        # Ensure .img extension
        if not filename.lower().endswith('.img'):
            filename += '.img'

        try:
            # Copy the current image file
            shutil.copy2(self.image_path, filename)

            QMessageBox.information(
                self,
                "Success",
                f"Image saved as:\n{Path(filename).name}"
            )

            self.status_bar.showMessage(f"Saved as: {Path(filename).name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save image: {e}")

    def format_disk(self):
        """Format the disk - erase all files and reset to empty state"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded to format.")
            return
        
        # Show warning dialog
        response = QMessageBox.warning(
            self,
            "Format Disk",
            "⚠️ WARNING: This will permanently erase ALL files on the disk!\n\n"
            f"Disk: {Path(self.image_path).name}\n\n"
            "Are you sure you want to format this disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No  # Default to No for safety
        )
        
        if response == QMessageBox.StandardButton.No:
            return
        
        try:
            # Format the disk
            self.image.format_disk()
            
            # Refresh the file list to show empty disk
            self.refresh_file_list()
            
            QMessageBox.information(
                self,
                "Format Complete",
                "Disk has been formatted successfully.\nAll files have been erased."
            )
            
            self.status_bar.showMessage("Disk formatted - all files erased")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to format disk: {e}")

    def open_image(self):
        """Open a different floppy image"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select FAT12 Floppy Image",
            "",
            "Floppy images (*.img *.ima);;All files (*.*)"
        )

        if filename:
            self.load_image(filename)

    def show_about(self):
        """Show about dialog"""
        about_text = """<h2>FAT12 Floppy Manager</h2>
        <p><b>Version 2.1</b></p>

        <p>A modern tool for managing files on FAT12 floppy disk images with VFAT long filename support.</p>

        <p><b>Features:</b></p>
        <ul>
        <li>FAT12 filesystem support with VFAT long filenames</li>
        <li>Windows-compatible 8.3 name generation with numeric tails</li>
        <li>Toggleable numeric tail mode (Windows-style vs. simple truncation)</li>
        <li>Create new blank floppy images</li>
        <li>Writes directly to the image file without needing to mount it as a drive</li>
        <li>Displays both long filenames and 8.3 short names</li>
        <li>Save copies of floppy images</li>
        <li>Drag and drop files to add them</li>
        <li>Delete files (press Del key)</li>
        <li>Extract files with original long names</li>
        <li>View boot sector information</li>
        <li>View complete root directory information with timestamps</li>
        <li>Remembers last opened image and settings</li>
        </ul>

        <p><b>Keyboard Shortcuts:</b></p>
        <ul>
        <li>Ctrl+N - Create new image</li>
        <li>Ctrl+O - Open image</li>
        <li>Ctrl+Shift+S - Save image as</li>
        <li>Del/Backspace - Delete selected files</li>
        <li>Double-click - Extract file</li>
        </ul>

        <p><small>© 2026 Stephen P Smith | MIT License</small></p>
        """
        QMessageBox.about(self, "About", about_text)

    def closeEvent(self, event):
        """Handle window close event - save state"""
        # Save window geometry
        self.settings.setValue('window_geometry', self.saveGeometry())
        event.accept()

    def dragEnterEvent(self, event):
        """Handle drag enter event"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Handle drop event - add files to floppy"""
        if not self.image:
            QMessageBox.information(
                self,
                "No Image Loaded",
                "Please create a new image or open an existing one first."
            )
            event.ignore()
            return

        # Get dropped files
        files = []
        for url in event.mimeData().urls():
            filepath = url.toLocalFile()
            if filepath and Path(filepath).is_file():
                files.append(filepath)

        if not files:
            event.ignore()
            return

        event.acceptProposedAction()

        # Add files using existing method
        self.add_files_from_list(files)


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("FAT12 Floppy Manager")
    app.setOrganizationName("FAT12FloppyManager")

    # Set application style
    app.setStyle('Fusion')

    # Create main window
    window = FloppyManagerWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
