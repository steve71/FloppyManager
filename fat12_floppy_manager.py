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
import zipfile
import tempfile
from pathlib import Path
from typing import Optional
from datetime import datetime

from vfat_utils import format_83_name, split_filename_for_editing, decode_fat_datetime


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QLabel, QStatusBar, QMenuBar, QMenu, QHeaderView,
    QDialog, QTabWidget, QToolBar, QStyle, QSizePolicy, QInputDialog
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QSize, QMimeData, QUrl
from PyQt6.QtGui import QIcon, QAction, QKeySequence, QActionGroup, QPalette, QColor, QDrag

# Import the FAT12 handler
from fat12_handler import FAT12Image
from gui_components import BootSectorViewer, RootDirectoryViewer, FATViewer, FileAttributesDialog

from PyQt6.QtWidgets import QStyledItemDelegate, QLineEdit

class SortableTableWidgetItem(QTableWidgetItem):
    """Table item that sorts based on UserRole data if available, otherwise text"""
    def __lt__(self, other):
        # Get sort data
        my_data = self.data(Qt.ItemDataRole.UserRole)
        other_data = other.data(Qt.ItemDataRole.UserRole)
        
        if my_data is not None and other_data is not None:
            return my_data < other_data
            
        return super().__lt__(other)

class FileTableWidget(QTableWidget):
    """Custom TableWidget that supports dragging files out and dropping files in"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTableWidget.DragDropMode.DragDrop)
    
    def startDrag(self, supportedActions):
        # Get main window reference to access image
        main_window = self.window()
        if not hasattr(main_window, 'image') or not main_window.image:
            return

        selected_rows = set(item.row() for item in self.selectedItems())
        if not selected_rows:
            return

        # Create a temporary directory
        temp_dir = tempfile.mkdtemp(prefix="fat12_drag_")
        
        try:
            urls = []
            entries = main_window.image.read_root_directory()
            
            files_exported = False
            
            for row in selected_rows:
                # Get index from hidden column 5
                index_item = self.item(row, 6)
                if not index_item:
                    continue
                    
                entry_index = int(index_item.text())
                entry = next((e for e in entries if e['index'] == entry_index), None)
                
                if entry and not entry['is_dir']:
                    try:
                        data = main_window.image.extract_file(entry)
                        filename = entry['name']
                        filepath = os.path.join(temp_dir, filename)
                        
                        with open(filepath, 'wb') as f:
                            f.write(data)
                        
                        urls.append(QUrl.fromLocalFile(filepath))
                        files_exported = True
                    except Exception as e:
                        print(f"Error extracting {entry['name']} for drag: {e}")
            
            if not files_exported:
                return

            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setUrls(urls)
            drag.setMimeData(mime_data)
            
            # Execute drag - blocks until drop is finished
            drag.exec(Qt.DropAction.CopyAction)
            
        finally:
            # Cleanup temp dir after drag is done
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            main_window = self.window()
            
            if not hasattr(main_window, 'image') or not main_window.image:
                QMessageBox.information(
                    self,
                    "No Image Loaded",
                    "Please create a new image or open an existing one first."
                )
                event.ignore()
                return

            files = []
            for url in event.mimeData().urls():
                filepath = url.toLocalFile()
                if filepath and Path(filepath).is_file():
                    files.append(filepath)
            
            if files:
                event.acceptProposedAction()
                main_window.add_files_from_list(files)
        else:
            super().dropEvent(event)

class RenameDelegate(QStyledItemDelegate):
    """Custom delegate that selects only filename (not extension) when editing starts"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.should_customize_selection = False
    
    def createEditor(self, parent, option, index):
        """Create editor and customize selection if requested"""
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit) and self.should_customize_selection:
            # Only customize if we explicitly requested it
            QTimer.singleShot(0, lambda: self.customize_selection(editor, index))
            self.should_customize_selection = False  # Reset flag
        return editor
    
    def customize_selection(self, editor, index):
        """Customize the text selection to exclude extension"""
        if editor and editor.isVisible():
            text = index.data()
            if text:
                full_name, start, end = split_filename_for_editing(text)
                editor.setFocus()
                editor.setSelection(start, end - start)

class FloppyManagerWindow(QMainWindow):
    """Main window for the floppy manager"""

    def __init__(self, image_path: Optional[str] = None):
        super().__init__()

        # Settings
        self.settings = QSettings('FAT12FloppyManager', 'Settings')
        self.confirm_delete = self.settings.value('confirm_delete', True, type=bool)
        self.confirm_replace = self.settings.value('confirm_replace', True, type=bool)
        self.show_hidden_files = self.settings.value('show_hidden_files', True, type=bool)
        self.use_numeric_tail = self.settings.value('use_numeric_tail', False, type=bool)
        self.theme_mode = self.settings.value('theme_mode', 'light', type=str)

        self.setup_ui()

        self.restore_settings()

        self.image_path = image_path
        self.image = None
        
        # Track clicks for rename-on-slow-double-click
        self._last_click_time = 0
        self._last_click_row = -1
        self._last_click_col = -1
        
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

    def restore_settings(self):
        # Restore window geometry if available
        geometry = self.settings.value('window_geometry')
        if geometry:
            self.restoreGeometry(geometry)

        # Restore window state if available
        state = self.settings.value('window_state')
        if state:
            self.restoreState(state)

    def setup_ui(self):
        """Create the user interface"""
        self.setWindowTitle("FAT12 Floppy Manager")
        self.setGeometry(400, 200, 620, 500)

        # Set window icon if available
        icon_path = Path(__file__).parent / 'floppy_icon.ico'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon))

        # Create menu bar
        self.create_menus()

        # Create toolbar
        self.create_toolbar()

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        layout = QVBoxLayout(central_widget)

        # Search/Filter Bar
        search_layout = QHBoxLayout()
        search_label = QLabel("Filter:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by filename...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # File table - now with 7 columns
        self.table = FileTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(['Filename', 'Short Name (8.3)', 'Date Modified', 'Type', 'Size', 'Attr', 'Index'])

        # Hide the index column (used internally)
        self.table.setColumnHidden(6, True)

        # Configure table
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        # Disable all automatic edit triggers - we'll handle this manually
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Track editing state
        self._editing_in_progress = False
        self.table.itemChanged.connect(self.on_item_changed)
        
        # Set custom delegate for filename column to handle selection
        self.rename_delegate = RenameDelegate(self.table)
        self.table.setItemDelegateForColumn(0, self.rename_delegate)
        
        # Reset click tracking when selection changes
        self.table.itemSelectionChanged.connect(self.on_selection_changed)

        # Set column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Filename
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Short name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Date Modified
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Type
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Size
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)             # Attr
        self.table.setColumnWidth(5, 50)

        # Handle clicks for rename and extract
        self.table.clicked.connect(self.on_table_clicked)
        self.table.doubleClicked.connect(self.on_table_double_clicked)

        # Context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.table)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Info Label (Permanent widget on the right side of status bar)
        self.info_label = QLabel()
        self.status_bar.addPermanentWidget(self.info_label)
        
        self.status_bar.showMessage("Ready | Tip: Drag and drop files to add them to the floppy")

        # Keyboard shortcuts
        self.table.keyPressEvent = self.table_key_press

    def create_toolbar(self):
        """Create the main toolbar with professional styling"""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setObjectName("MainToolbar")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        
        # Professional styling with better spacing and appearance
        toolbar.setStyleSheet("""
            QToolBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f8f8, stop:1 #e8e8e8);
                border-bottom: 1px solid #c0c0c0;
                spacing: 4px;
                padding: 2px;
            }
            QToolButton {
                font-size: 10px;
                min-width: 40px;
                padding: 2px;
                margin: 1px;
                border-radius: 3px;
                background: transparent;
            }
            QToolButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #e0e0e0);
                border: 1px solid #b0b0b0;
            }
            QToolButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #d0d0d0, stop:1 #e8e8e8);
                border: 1px solid #909090;
            }
            QToolButton:disabled {
                color: #a0a0a0;
            }
        """)
        
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        # === FILE OPERATIONS GROUP ===
        
        # New Image
        new_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon), "New", self)
        new_action.setStatusTip("Create a new blank floppy disk image")
        new_action.triggered.connect(self.create_new_image)
        toolbar.addAction(new_action)
        
        # Open Image
        open_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), "Open", self)
        open_action.setStatusTip("Open an existing floppy disk image")
        open_action.triggered.connect(self.open_image)
        toolbar.addAction(open_action)
        
        # Format
        format_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon), "Format", self)
        format_action.setStatusTip("Format the disk (erase all files)")
        format_action.triggered.connect(self.format_disk)
        toolbar.addAction(format_action)
        
        toolbar.addSeparator()
        
        # === FILE MANAGEMENT GROUP ===
        
        # Add Files
        add_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "Add", self)
        add_action.setStatusTip("Add files to the floppy image")
        add_action.triggered.connect(self.add_files)
        toolbar.addAction(add_action)

        # Extract Selected
        extract_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "Extract", self)
        extract_action.setStatusTip("Extract selected files to your computer")
        extract_action.triggered.connect(self.extract_selected)
        toolbar.addAction(extract_action)

        # Extract All
        extract_all_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), "Ext. All", self)
        extract_all_action.setStatusTip("Extract all files to a folder")
        extract_all_action.triggered.connect(self.extract_all)
        toolbar.addAction(extract_all_action)

        toolbar.addSeparator()
        
        # === ARCHIVE OPERATIONS ===
        
        # Zip All
        zip_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveCDIcon), "Zip", self)
        zip_action.setStatusTip("Extract all files to a ZIP archive")
        zip_action.triggered.connect(self.extract_all_to_zip)
        toolbar.addAction(zip_action)

        toolbar.addSeparator()
        
        # === DELETE OPERATIONS ===
        
        # Delete Selected
        delete_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Delete", self)
        delete_action.setStatusTip("Delete selected files (Del key)")
        delete_action.triggered.connect(self.delete_selected)
        toolbar.addAction(delete_action)

        # Delete All
        delete_all_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogDiscardButton), "Del. All", self)
        delete_all_action.setStatusTip("Delete all files from the disk")
        delete_all_action.triggered.connect(self.delete_all)
        toolbar.addAction(delete_all_action)
        
        toolbar.addSeparator()
        
        # === VIEW/UTILITY GROUP ===

        # Refresh
        refresh_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "Refresh", self)
        refresh_action.setStatusTip("Reload the file list")
        refresh_action.triggered.connect(self.refresh_file_list)
        toolbar.addAction(refresh_action)

    def show_context_menu(self, position):
        """Show context menu for table"""
        if not self.image:
            return

        selected_rows = set(item.row() for item in self.table.selectedItems())
        if not selected_rows:
            return

        menu = QMenu()
        
        # Only show rename and properties if exactly one file is selected
        if len(selected_rows) == 1:
            rename_action = QAction("Rename", self)
            rename_action.setShortcut(Qt.Key.Key_F2)
            rename_action.triggered.connect(self.start_rename)
            menu.addAction(rename_action)
            
            properties_action = QAction("Properties...", self)
            properties_action.setShortcut("Alt+Return")
            properties_action.triggered.connect(self.edit_file_attributes)
            menu.addAction(properties_action)
            menu.addSeparator()
        
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
        format_action.setShortcut("Ctrl+Shift+F")
        format_action.setToolTip("Erase all files and reset the disk to empty state")
        format_action.triggered.connect(self.format_disk)
        file_menu.addAction(format_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        rename_action = QAction("&Rename", self)
        rename_action.setShortcut(Qt.Key.Key_F2)
        rename_action.setToolTip("Rename selected file (F2)")
        rename_action.triggered.connect(self.start_rename)
        edit_menu.addAction(rename_action)
        
        edit_menu.addSeparator()
        
        properties_action = QAction("&Properties...", self)
        properties_action.setShortcut("Alt+Return")
        properties_action.setToolTip("Edit file attributes (Alt+Enter)")
        properties_action.triggered.connect(self.edit_file_attributes)
        edit_menu.addAction(properties_action)

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

        self.show_hidden_action = QAction("Show &Hidden Files", self)
        self.show_hidden_action.setCheckable(True)
        self.show_hidden_action.setChecked(self.show_hidden_files)
        self.show_hidden_action.triggered.connect(self.toggle_show_hidden)
        settings_menu.addAction(self.show_hidden_action)

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

    def toggle_show_hidden(self):
        """Toggle visibility of hidden files"""
        self.show_hidden_files = self.show_hidden_action.isChecked()
        self.settings.setValue('show_hidden_files', self.show_hidden_files)
        self.refresh_file_list()

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
            
            # Update toolbar for dark mode
            self.update_toolbar_style('dark')
            
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
            
            # Update toolbar for light mode
            self.update_toolbar_style('light')
    
    def update_toolbar_style(self, theme_mode):
        """Update toolbar styling based on theme"""
        # Find the toolbar
        toolbars = self.findChildren(QToolBar)
        if not toolbars:
            return
        
        toolbar = toolbars[0]
        
        if theme_mode == 'dark':
            toolbar.setStyleSheet("""
                QToolBar {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #404040, stop:1 #353535);
                    border-bottom: 1px solid #202020;
                    spacing: 4px;
                    padding: 2px;
                }
                QToolButton {
                    font-size: 10px;
                    min-width: 40px;
                    padding: 2px;
                    margin: 1px;
                    border-radius: 3px;
                    background: transparent;
                    color: #ffffff;
                }
                QToolButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #505050, stop:1 #454545);
                    border: 1px solid #606060;
                }
                QToolButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #303030, stop:1 #404040);
                    border: 1px solid #505050;
                }
                QToolButton:disabled {
                    color: #808080;
                }
            """)
            
            # Update info label for dark mode
            self.info_label.setStyleSheet("""
                QLabel {
                    padding-right: 10px;
                    font-weight: bold;
                    font-size: 12px;
                    color: #ffffff;
                    background: transparent;
                }
            """)
        else:  # light
            toolbar.setStyleSheet("""
                QToolBar {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f8f8f8, stop:1 #e8e8e8);
                    border-bottom: 1px solid #c0c0c0;
                    spacing: 4px;
                    padding: 2px;
                }
                QToolButton {
                    font-size: 10px;
                    min-width: 40px;
                    padding: 2px;
                    margin: 1px;
                    border-radius: 3px;
                    background: transparent;
                }
                QToolButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ffffff, stop:1 #e0e0e0);
                    border: 1px solid #b0b0b0;
                }
                QToolButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #d0d0d0, stop:1 #e8e8e8);
                    border: 1px solid #909090;
                }
                QToolButton:disabled {
                    color: #a0a0a0;
                }
            """)
            
            # Update info label for light mode
            self.info_label.setStyleSheet("""
                QLabel {
                    padding-right: 10px;
                    font-weight: bold;
                    font-size: 12px;
                    color: #333333;
                    background: transparent;
                }
            """)

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
        self.show_hidden_files = True
        self.use_numeric_tail = False
        self.theme_mode = 'light'
        
        # Update UI to reflect defaults
        self.confirm_delete_action.setChecked(True)
        self.confirm_replace_action.setChecked(True)
        self.use_numeric_tail_action.setChecked(False)
        self.show_hidden_action.setChecked(True)
        self.theme_light_action.setChecked(True)
        
        # Apply light theme
        self.apply_theme('light')
        
        # Save the default settings
        self.settings.setValue('confirm_delete', True)
        self.settings.setValue('confirm_replace', True)
        self.settings.setValue('show_hidden_files', True)
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
        elif event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.AltModifier:
            # Alt+Return opens properties dialog
            self.edit_file_attributes()
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

    def on_search_text_changed(self, text):
        """Handle search text changes"""
        self.refresh_file_list()

    def refresh_file_list(self):
        """Refresh the file list from the image"""
        # Block signals to prevent itemChanged from firing during population
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)

            if not self.image:
                self.info_label.setText("")
                return

            try:
                entries = self.image.read_root_directory()

                # Get search text
                search_text = self.search_input.text().lower().strip() if hasattr(self, 'search_input') else ""
                
                total_files_count = 0

                for entry in entries:
                    # Filter hidden files if not enabled
                    if not self.show_hidden_files and entry['is_hidden']:
                        continue

                    if not entry['is_dir']:
                        total_files_count += 1
                        
                        # Apply search filter (filename only)
                        if search_text and (search_text not in entry['name'].lower() and 
                                          search_text not in entry['short_name'].lower()):
                            continue

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

                        # Date Modified - READ ONLY
                        date_int = entry['last_modified_date']
                        time_int = entry['last_modified_time']
                        
                        dt = decode_fat_datetime(date_int, time_int)
                        
                        if dt:
                            # Format: 10/25/2023 02:30 PM
                            date_str = dt.strftime("%m/%d/%Y %I:%M %p")
                            sort_key = int(dt.timestamp())
                        else:
                            date_str = ""
                            sort_key = -1
                            
                        date_item = SortableTableWidgetItem(date_str)
                        date_item.setData(Qt.ItemDataRole.UserRole, sort_key) # Sort by timestamp
                        date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(row, 2, date_item)

                        # Type - READ ONLY
                        type_item = QTableWidgetItem(entry['file_type'])
                        type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(row, 3, type_item)

                        # Size - READ ONLY
                        size_str = f"{entry['size']:,} bytes"
                        size_item = SortableTableWidgetItem(size_str)
                        size_item.setData(Qt.ItemDataRole.UserRole, entry['size']) # Sort by actual size
                        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(row, 4, size_item)

                        # Attr - READ ONLY
                        attr_str = ""
                        tooltip_parts = []

                        if entry['is_read_only']:
                            attr_str += "R"
                            tooltip_parts.append("Read-only")
                        if entry['is_hidden']:
                            attr_str += "H"
                            tooltip_parts.append("Hidden")
                        if entry['is_system']:
                            attr_str += "S"
                            tooltip_parts.append("System")
                        if entry['is_archive']:
                            attr_str += "A"
                            tooltip_parts.append("Archive")

                        attr_item = QTableWidgetItem(attr_str)
                        if tooltip_parts:
                            attr_item.setToolTip(", ".join(tooltip_parts))
                        attr_item.setFlags(attr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        attr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table.setItem(row, 5, attr_item)

                        # Index (hidden) - READ ONLY
                        index_item = QTableWidgetItem(str(entry['index']))
                        index_item.setFlags(index_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(row, 6, index_item)

                # Update info
                visible_count = self.table.rowCount()
                if search_text:
                    self.info_label.setText(f"Showing {visible_count} of {total_files_count} files | {self.image.get_free_space():,} bytes free")
                else:
                    self.info_label.setText(f"{visible_count} files | {self.image.get_free_space():,} bytes free")
                self.status_bar.showMessage(f"Loaded {visible_count} files")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to read directory: {e}")
        finally:
            self.table.blockSignals(False)

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

        # Sort files by name (case-insensitive) to ensure deterministic order
        filenames.sort(key=lambda x: Path(x).name.lower())

        success_count = 0
        fail_count = 0

        for filepath in filenames:
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()

                path_obj = Path(filepath)
                original_name = path_obj.name

                # Get modification time
                try:
                    stat = path_obj.stat()
                    modification_dt = datetime.fromtimestamp(stat.st_mtime)
                except Exception:
                    modification_dt = None

                # Predict the 8.3 name that will be used
                short_name_83 = self.image.predict_short_name(original_name, self.use_numeric_tail)
                
                # Format 8.3 name for display (add dot back)
                short_display = format_83_name(short_name_83)

                # Check if file already exists
                collision_entry = self.image.find_entry_by_83_name(short_name_83)

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
                if self.image.write_file_to_image(original_name, data, self.use_numeric_tail, modification_dt):
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
            entry_index = int(self.table.item(row, 6).text())
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

    def extract_all(self):
        """Extract all files"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return

        entries = self.image.read_root_directory()
        files_to_extract = [e for e in entries if not e['is_dir']]

        if not files_to_extract:
            QMessageBox.information(self, "Info", "No files to extract")
            return

        save_dir = QFileDialog.getExistingDirectory(self, "Select folder to save all files")
        if not save_dir:
            return

        success_count = 0
        for entry in files_to_extract:
            try:
                data = self.image.extract_file(entry)
                output_path = os.path.join(save_dir, entry['name'])
                with open(output_path, 'wb') as f:
                    f.write(data)
                success_count += 1
            except Exception as e:
                print(f"Failed to extract {entry['name']}: {e}")

        if success_count > 0:
            self.status_bar.showMessage(f"Extracted {success_count} file(s) to {save_dir}")
            QMessageBox.information(self, "Success", f"Extracted {success_count} file(s)")

    def extract_all_to_zip(self):
        """Extract all files to a ZIP archive"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return

        entries = self.image.read_root_directory()
        files_to_extract = [e for e in entries if not e['is_dir']]

        if not files_to_extract:
            QMessageBox.information(self, "Info", "No files to extract")
            return

        default_name = "floppy_content.zip"
        if self.image_path:
            default_name = Path(self.image_path).stem + ".zip"

        zip_filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save as ZIP",
            default_name,
            "ZIP files (*.zip)"
        )

        if not zip_filename:
            return
            
        if not zip_filename.lower().endswith('.zip'):
            zip_filename += '.zip'

        success_count = 0
        try:
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for entry in files_to_extract:
                    try:
                        data = self.image.extract_file(entry)
                        # Use the long filename
                        zipf.writestr(entry['name'], data)
                        success_count += 1
                    except Exception as e:
                        print(f"Failed to extract {entry['name']} to zip: {e}")
            
            if success_count > 0:
                self.status_bar.showMessage(f"Archived {success_count} file(s) to {Path(zip_filename).name}")
                QMessageBox.information(self, "Success", f"Archived {success_count} file(s) to ZIP file")
                
        except Exception as e:
             QMessageBox.critical(self, "Error", f"Failed to create ZIP file: {e}")

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
        files_to_delete = []
        read_only_files = []

        for row in selected_rows:
            entry_index = int(self.table.item(row, 6).text())
            entry = next((e for e in entries if e['index'] == entry_index), None)
            if entry:
                files_to_delete.append(entry)
                if entry['is_read_only']:
                    read_only_files.append(entry)

        # Warn about read-only files
        if read_only_files:
            msg = f"{len(read_only_files)} of the selected files are Read-Only.\n\nDo you want to delete them anyway?"
            response = QMessageBox.warning(
                self,
                "Read-Only Files",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if response == QMessageBox.StandardButton.No:
                return

        # Proceed with deletion
        for entry in files_to_delete:
                if self.image.delete_file(entry):
                    success_count += 1
                else:
                    QMessageBox.critical(self, "Error", f"Failed to delete {entry['name']}")

        self.refresh_file_list()

        if success_count > 0:
            self.status_bar.showMessage(f"Deleted {success_count} file(s)")

    def delete_all(self):
        """Delete all files"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return

        entries = self.image.read_root_directory()
        files_to_delete = [e for e in entries if not e['is_dir']]

        if not files_to_delete:
            QMessageBox.information(self, "Info", "No files to delete")
            return

        if self.confirm_delete:
            response = QMessageBox.question(
                self,
                "Confirm Delete All",
                f"Delete ALL {len(files_to_delete)} file(s) from the disk image?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if response == QMessageBox.StandardButton.No:
                return

        # Check for read-only files
        read_only_files = [e for e in files_to_delete if e['is_read_only']]
        if read_only_files:
            msg = f"{len(read_only_files)} of the files are Read-Only.\n\nDo you want to delete them anyway?"
            response = QMessageBox.warning(
                self,
                "Read-Only Files",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if response == QMessageBox.StandardButton.No:
                return

        success_count = 0
        for entry in files_to_delete:
            if self.image.delete_file(entry):
                success_count += 1

        self.refresh_file_list()
        if success_count > 0:
            self.status_bar.showMessage(f"Deleted {success_count} file(s)")

    def create_new_image(self):
        """Create a new blank floppy disk image"""
        # Ask for format
        formats = list(FAT12Image.FORMATS.keys())
        display_names = [FAT12Image.FORMATS[k]['name'] for k in formats]
        
        item, ok = QInputDialog.getItem(
            self, 
            "Select Disk Format", 
            "Choose floppy disk format:", 
            display_names, 
            0, # Default to first (1.44M)
            False # Not editable
        )
        
        if not ok or not item:
            return
            
        # Map back to key
        selected_key = formats[display_names.index(item)]

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
            FAT12Image.create_empty_image(filename, selected_key)
            FAT12Image.create_empty_image(filename)

            # Load the new image
            self.load_image(filename)

            QMessageBox.information(
                self,
                "Success",
                f"Created new {item} image:\n{Path(filename).name}"
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

        <p>A modern tool for managing files on FAT12 floppy disk images with VFAT long filename support.</p>

        <p><b>Features:</b></p>
        <table border="0" width="100%">
        <tr>
        <td valign="top" width="50%">
        <ul>
        <li>FAT12 filesystem support with VFAT long filenames</li>
        <li>Windows-compatible 8.3 name generation</li>
        <li>Toggleable numeric tail mode</li>
        <li>Create new blank floppy images</li>
        <li>Writes directly to image (no mounting)</li>
        <li>Displays long filenames and 8.3 short names</li>
        <li>Save copies of floppy images</li>
        <li>Drag and drop support</li>
        <li>View and edit file attributes</li>
        </ul>
        </td>

        <td valign="top" width="50%">
        <ul>
        <li>Rename files (Windows-style inline)</li>
        <li>Delete files (selected or all)</li>
        <li>Extract files (selected, all, or to ZIP)</li>
        <li>Format disk</li>
        <li>Search/Filter files by filename</li>
        <li>Boot Sector, Root Dir & FAT Viewers</li>
        <li>Modern UI with Toolbar and Light/Dark themes</li>
        <li>Remembers last opened image and settings</li>
        </ul>
        </td>
        </tr>
        </table>

        <p><b>Keyboard Shortcuts:</b></p>
        <ul>
        <li>Ctrl+N - Create new image</li>
        <li>Ctrl+O - Open image</li>
        <li>Ctrl+Shift+S - Save image as</li>
        <li>Ctrl+Shift+F - Format disk</li>
        <li>Del/Backspace - Delete selected files</li>
        <li>Double-click - Extract file</li>
        </ul>

        <p><small>© 2026 Stephen P Smith | MIT License</small></p>
        """
        QMessageBox.about(self, "About", about_text)

    def closeEvent(self, event):
        """Handle window close event - save state"""
        # Save window geometry and State
        self.settings.setValue('window_geometry', self.saveGeometry())
        self.settings.setValue('window_state', self.saveState())

        event.accept()

    def on_selection_changed(self):
        """Reset click tracking when selection changes"""
        # Don't reset if we're in the middle of editing
        if not self._editing_in_progress:
            self._last_click_time = 0
            self._last_click_row = -1
            self._last_click_col = -1
    
    def on_table_clicked(self, index):
        """Handle single clicks on table - detect slow double-click for rename"""
        import time
        
        if not self.image:
            return
        
        current_time = time.time()
        row = index.row()
        col = index.column()
        
        # Only process clicks on the filename column
        if col != 0:
            return
        
        # Check if this is a slow double-click (click on already selected item)
        # Windows uses ~500ms minimum between clicks for rename
        time_since_last_click = current_time - self._last_click_time
        
        # Conditions for rename:
        # 1. Same row as last click
        # 2. Between 0.5 and 5 seconds since last click (slow double-click window)
        # 3. Item is already selected (not a fresh selection)
        if (row == self._last_click_row and 
            col == self._last_click_col and
            0.5 <= time_since_last_click <= 5.0):
            
            # This is a slow double-click - start rename
            self.start_rename()
            # Reset tracking to prevent immediate re-trigger
            self._last_click_time = 0
            self._last_click_row = -1
            self._last_click_col = -1
        else:
            # Update tracking for next click
            self._last_click_time = current_time
            self._last_click_row = row
            self._last_click_col = col
    
    def on_table_double_clicked(self, index):
        """Handle double-clicks on table - extract file"""
        # Reset click tracking to prevent rename after double-click
        self._last_click_time = 0
        self._last_click_row = -1
        self._last_click_col = -1
        
        # Extract the file
        self.extract_selected()

    def start_rename(self):
        """Start inline renaming of the selected file (Windows-style)"""
        if not self.image:
            return
        
        # Reset click tracking
        self._last_click_time = 0
        self._last_click_row = -1
        self._last_click_col = -1
        
        # Get selected row
        selected_rows = set(item.row() for item in self.table.selectedItems())
        if len(selected_rows) != 1:
            QMessageBox.information(
                self,
                "Select One File",
                "Please select exactly one file to rename."
            )
            return
        
        row = list(selected_rows)[0]
        
        # Make sure we're on the filename column
        self.table.setCurrentCell(row, 0)
        
        # Tell the delegate to customize selection
        self.rename_delegate.should_customize_selection = True
        
        # Temporarily enable editing, start edit, then disable again
        self.table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        self.table.edit(self.table.currentIndex())
        
        # Disable editing triggers after a moment (after editor is created)
        QTimer.singleShot(100, lambda: self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers))
    
    def edit_file_attributes(self):
        """Open the file attributes editor dialog"""
        if not self.image:
            return
        
        # Get selected row
        selected_rows = set(item.row() for item in self.table.selectedItems())
        if len(selected_rows) != 1:
            QMessageBox.information(
                self,
                "Select One File",
                "Please select exactly one file to edit attributes."
            )
            return
        
        row = list(selected_rows)[0]
        
        # Get the file entry from the hidden index column
        index = int(self.table.item(row, 6).text())
        entries = self.image.read_root_directory()
        entry = next((e for e in entries if e['index'] == index), None)
        
        if not entry:
            QMessageBox.warning(self, "Error", "Could not find file entry.")
            return
        
        # Show the attributes dialog
        dialog = FileAttributesDialog(entry, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the new attributes
            attrs = dialog.get_attributes()
            
            # Update the attributes
            success = self.image.set_file_attributes(
                entry,
                is_read_only=attrs['is_read_only'],
                is_hidden=attrs['is_hidden'],
                is_system=attrs['is_system'],
                is_archive=attrs['is_archive']
            )
            
            if success:
                self.status_bar.showMessage(f"Attributes updated for {entry['name']}", 3000)
                self.refresh_file_list()
            else:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to update attributes for {entry['name']}"
                )
    
    def on_item_changed(self, item):
        """Handle item changes (when rename is completed)"""
        if self._editing_in_progress:
            return
        
        # Only process changes to the filename column (column 0)
        if item.column() != 0:
            return
        
        self._editing_in_progress = True
        
        # Defer the actual processing to avoid interfering with Qt's editing lifecycle
        QTimer.singleShot(0, lambda: self.process_rename(item))
    
    def process_rename(self, item):
        """Process the rename after Qt's editing lifecycle completes"""
        try:
            # Edit triggers are already NoEditTriggers - no need to set again
            
            new_name = item.text().strip()
            row = item.row()
            
            # Get the entry index from the hidden column
            index_item = self.table.item(row, 6)
            if not index_item:
                self._editing_in_progress = False
                return
            
            entry_index = int(index_item.text())
            
            # Get the entry from the image
            entries = self.image.read_root_directory()
            entry = None
            for e in entries:
                if e['index'] == entry_index:
                    entry = e
                    break
            
            if not entry:
                self._editing_in_progress = False
                return
            
            old_name = entry['name']
            
            # Check if name actually changed
            if new_name == old_name or not new_name:
                # User cancelled or didn't change anything
                # Silently restore original name
                self.table.itemChanged.disconnect(self.on_item_changed)
                item.setText(old_name)
                self.table.itemChanged.connect(self.on_item_changed)
                self._editing_in_progress = False
                return
            
            # Check for invalid characters in FAT12
            invalid_chars = '<>:"|?*\\/\x00'
            if any(c in new_name for c in invalid_chars):
                QMessageBox.warning(
                    self,
                    "Invalid Name",
                    f"Filename cannot contain these characters: {invalid_chars}"
                )
                # Temporarily disconnect to avoid recursion
                self.table.itemChanged.disconnect(self.on_item_changed)
                item.setText(old_name)
                self.table.itemChanged.connect(self.on_item_changed)
                self._editing_in_progress = False
                return
            
            # Attempt the rename
            success = self.image.rename_file(entry, new_name, self.use_numeric_tail)
            
            if success:
                self.status_bar.showMessage(f"Renamed '{old_name}' to '{new_name}'")
                # Refresh the file list to show the new name and short name
                self.refresh_file_list()
            else:
                QMessageBox.critical(
                    self,
                    "Rename Failed",
                    f"Could not rename '{old_name}' to '{new_name}'.\n\n"
                    "The root directory may be full or another error occurred."
                )
                # Temporarily disconnect to avoid recursion
                self.table.itemChanged.disconnect(self.on_item_changed)
                item.setText(old_name)
                self.table.itemChanged.connect(self.on_item_changed)
        
        finally:
            self._editing_in_progress = False

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
