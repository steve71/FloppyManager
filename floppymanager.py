#!/usr/bin/env python3

# Copyright (c) 2026 Stephen P Smith
# MIT License

"""
FAT12 FloppyManager
A modern GUI tool for managing files on FAT12 floppy disk images with VFAT LFN support
"""

import sys
import os
import shutil
import zipfile
import tempfile
import logging
import atexit
from pathlib import Path
from typing import Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QFileDialog, QMessageBox, QLabel, QStatusBar, QMenu,
    QDialog, QToolBar, QStyle, QHeaderView, QLineEdit
)
from PySide6.QtCore import Qt, QSettings, QTimer, QSize, QMimeData, QUrl
from PySide6.QtGui import QIcon, QAction, QKeySequence, QActionGroup, QPalette, QColor, QPainter, QPixmap 

from fat12_backend.handler import FAT12Image
from fat12_backend.directory import FAT12Error, FAT12CorruptionError
from fat12_backend.vfat_utils import format_83_name, decode_fat_datetime

from gui.components import (
    BootSectorViewer, DirectoryViewer, FATViewer, FileAttributesDialog,
    SortableTreeWidgetItem, FileTreeWidget, RenameDelegate, FormatDialog,
    NewImageDialog, LogViewer
)
from gui.file_icons import FileIconProvider
from gui.styles import (get_dark_palette, get_light_palette, 
                        dark_toolbar_stylesheet, light_toolbar_stylesheet,
                        dark_info_label_stylesheet, light_info_label_stylesheet)

from gui.about import about_html

class FloppyManagerWindow(QMainWindow):
    """Main window for the floppy manager"""
    
    def setup_logging(self):
        """Configure application-wide logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("floppymanager.log", mode='w'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("FloppyManager")

    def __init__(self, image_path: Optional[str] = None):
        super().__init__()

        # Settings
        self.settings = QSettings('FloppyManager', 'Settings')
        self.confirm_delete = self.settings.value('confirm_delete', True, type=bool)
        self.confirm_replace = self.settings.value('confirm_replace', True, type=bool)
        self.show_hidden_files = self.settings.value('show_hidden_files', True, type=bool)
        self.use_numeric_tail = self.settings.value('use_numeric_tail', False, type=bool)
        self.theme_mode = self.settings.value('theme_mode', 'light', type=str)

        self.setup_logging()
        self.logger.info("Application started")

        self.setup_ui()

        self.restore_settings()

        # Set a default sort order on startup, overriding any restored state.
        # This ensures a consistent, predictable initial view (A-Z).
        self.table.header().setSortIndicator(0, Qt.SortOrder.AscendingOrder)

        self.image_path = image_path
        self.image = None
        self.log_viewer = None
        self._last_copy_temp_dir = None
        self._cut_entries = []
        self._clipboard_source_cluster = None
        
        # Register cleanup on exit
        atexit.register(self._cleanup_temp_dir)
        
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
        self.setWindowTitle("FloppyManager")
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

        # File Tree
        self.table = FileTreeWidget()
        self.table.setColumnCount(6)
        self.table.setHeaderLabels(['Filename', '8.3 Name', 'Date Modified', 'Type', 'Size', 'Attr'])

        # Configure tree
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        # Disable all automatic edit triggers - we'll handle this manually
        self.table.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)

        # Track editing state
        self._editing_in_progress = False
        self.table.itemChanged.connect(self.on_item_changed)
        
        # Set custom delegate for filename column to handle selection
        self.rename_delegate = RenameDelegate(self.table)
        self.table.setItemDelegateForColumn(0, self.rename_delegate)
        
        # Reset click tracking when selection changes
        self.table.itemSelectionChanged.connect(self.on_selection_changed)

        # Set column resizing behavior
        header = self.table.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 6):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        # Handle clicks for rename
        self.table.clicked.connect(self.on_table_clicked)

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
        
        # New Folder
        new_folder_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), "New Folder", self)
        new_folder_action.setStatusTip("Create a new folder")
        new_folder_action.triggered.connect(self.create_new_folder)
        toolbar.addAction(new_folder_action)
        
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
        delete_action.setStatusTip("Delete selected items (Del key)")
        delete_action.triggered.connect(self.delete_selected)
        toolbar.addAction(delete_action)

    def show_context_menu(self, position):
        """Show context menu for table"""
        if not self.image:
            return

        selected_items = self.table.selectedItems()

        menu = QMenu()
        
        new_folder_action = QAction("New Folder", self)
        new_folder_action.triggered.connect(self.create_new_folder)
        menu.addAction(new_folder_action)
        
        menu.addSeparator()
        
        # Check clipboard status
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        has_files = False
        if mime_data and mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    if os.path.isfile(url.toLocalFile()):
                        has_files = True
                        break
        
        if not selected_items:
            paste_action = QAction("Paste", self)
            paste_action.setShortcut(QKeySequence.StandardKey.Paste)
            paste_action.triggered.connect(self.paste_from_clipboard)
            paste_action.setEnabled(has_files)
            menu.addAction(paste_action)
            
            menu.exec(self.table.viewport().mapToGlobal(position))
            return
        
        # Only show rename and properties if exactly one file is selected
        if len(selected_items) == 1:
            rename_action = QAction("Rename", self)
            rename_action.setShortcut(Qt.Key.Key_F2)
            rename_action.triggered.connect(self.start_rename)
            menu.addAction(rename_action)
            
            properties_action = QAction("Properties...", self)
            properties_action.setShortcut("Alt+Return")
            properties_action.triggered.connect(self.edit_file_attributes)
            menu.addAction(properties_action)
            menu.addSeparator()

        cut_action = QAction("Cut", self)
        cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        cut_action.triggered.connect(self.cut_selected)
        menu.addAction(cut_action)

        copy_action = QAction("Copy", self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(self.copy_to_clipboard)
        menu.addAction(copy_action)

        paste_action = QAction("Paste", self)
        paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        paste_action.triggered.connect(self.paste_from_clipboard)
        paste_action.setEnabled(has_files)
        menu.addAction(paste_action)

        menu.addSeparator()

        duplicate_action = QAction("Duplicate", self)
        duplicate_action.setShortcut("Ctrl+D")
        duplicate_action.triggered.connect(self.duplicate_selected)
        menu.addAction(duplicate_action)

        extract_action = QAction("Extract", self)
        extract_action.triggered.connect(self.extract_selected)
        menu.addAction(extract_action)
                
        menu.addSeparator()
        
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self.delete_selected)
        menu.addAction(delete_action)
        
        menu.exec(self.table.viewport().mapToGlobal(position))

    def update_edit_menu(self):
        """Update enabled state of edit menu items"""
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        has_files = False
        if mime_data and mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    if os.path.isfile(url.toLocalFile()):
                        has_files = True
                        break
        if hasattr(self, 'paste_action'):
            self.paste_action.setEnabled(has_files)

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

        new_folder_action = QAction("New &Folder", self)
        new_folder_action.setShortcut("Ctrl+Shift+N")
        new_folder_action.setToolTip("Create a new folder")
        new_folder_action.triggered.connect(self.create_new_folder)
        file_menu.addAction(new_folder_action)

        open_action = QAction("&Open Image...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_image)
        file_menu.addAction(open_action)

        close_action = QAction("&Close Image", self)
        close_action.setShortcut(QKeySequence.StandardKey.Close)
        close_action.setToolTip("Close the current floppy image")
        close_action.triggered.connect(self.close_image)
        file_menu.addAction(close_action)

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

        defrag_action = QAction("&Defragment Disk", self)
        defrag_action.setShortcut("Ctrl+Shift+D")
        defrag_action.setToolTip("Optimize disk by making all files contiguous (Ctrl+Shift+D)")
        defrag_action.triggered.connect(self.defragment_disk)
        file_menu.addAction(defrag_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.setToolTip("Exit FloppyManager (Ctrl+Q)")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.aboutToShow.connect(self.update_edit_menu)

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

        edit_menu.addSeparator()

        cut_action = QAction("Cu&t", self)
        cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        cut_action.triggered.connect(self.cut_selected)
        edit_menu.addAction(cut_action)

        copy_action = QAction("&Copy", self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(self.copy_to_clipboard)
        edit_menu.addAction(copy_action)

        self.paste_action = QAction("&Paste", self)
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(self.paste_from_clipboard)
        edit_menu.addAction(self.paste_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        boot_sector_action = QAction("&Boot Sector Information...", self)
        boot_sector_action.setToolTip("View complete boot sector details")
        boot_sector_action.triggered.connect(self.show_boot_sector_info)
        view_menu.addAction(boot_sector_action)

        root_dir_action = QAction("&Directory Information...", self)
        root_dir_action.setToolTip("View complete directory details")
        root_dir_action.triggered.connect(self.show_root_directory_info)
        view_menu.addAction(root_dir_action)

        fat_viewer_action = QAction("&File Allocation Table...", self)
        fat_viewer_action.setToolTip("View File Allocation Table as a grid")
        fat_viewer_action.triggered.connect(self.show_fat_viewer)
        view_menu.addAction(fat_viewer_action)

        view_menu.addSeparator()

        log_action = QAction("View &Log...", self)
        log_action.setToolTip("View application log")
        log_action.triggered.connect(self.view_log)
        view_menu.addAction(log_action)

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
        self.logger.info(f"Settings: Confirm delete set to {self.confirm_delete}")

    def toggle_confirm_replace(self):
        """Toggle replace confirmation"""
        self.confirm_replace = self.confirm_replace_action.isChecked()
        self.settings.setValue('confirm_replace', self.confirm_replace)
        self.logger.info(f"Settings: Confirm replace set to {self.confirm_replace}")

    def toggle_show_hidden(self):
        """Toggle visibility of hidden files"""
        self.show_hidden_files = self.show_hidden_action.isChecked()
        self.settings.setValue('show_hidden_files', self.show_hidden_files)
        self.logger.info(f"Settings: Show hidden files set to {self.show_hidden_files}")
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
        self.logger.info(f"Settings: Numeric tail set to {self.use_numeric_tail}")

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
            
            palette = get_dark_palette()
            app.setPalette(palette)
            
            # Update toolbar for dark mode
            self.update_toolbar_style('dark')
            
        else:  # light (default)
            # Light theme
            app.setStyleSheet("")
            
            palette = get_light_palette()
            app.setPalette(palette)
            
            # Update toolbar for light mode
            self.update_toolbar_style('light')
            
        # Update icon provider with current style
        self.icon_provider = FileIconProvider(self.style())
        
        # Refresh file list to update icons if image is loaded
        if hasattr(self, 'image') and self.image:
             self.refresh_file_list()
    
    def update_toolbar_style(self, theme_mode):
        """Update toolbar styling based on theme"""
        # Find the toolbar
        toolbars = self.findChildren(QToolBar)
        if not toolbars:
            return
        
        toolbar = toolbars[0]
        
        if theme_mode == 'dark':
            toolbar.setStyleSheet(dark_toolbar_stylesheet)
            
            # Update info label for dark mode
            self.info_label.setStyleSheet(dark_info_label_stylesheet)
        else:  # light
            toolbar.setStyleSheet(light_toolbar_stylesheet)
            
            # Update info label for light mode
            self.info_label.setStyleSheet(light_info_label_stylesheet)

    def reset_settings(self):
        """Reset all settings to their default values"""
        response = QMessageBox.question(
            self,
            "Reset Settings",
            "Reset all settings to their default values?\n\n"
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
        
        self.logger.info("Settings reset to defaults")
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
        elif event.key() == Qt.Key.Key_Escape:
            # Cancel cut operation
            if self._cut_entries:
                self._cut_entries = []
                self.refresh_file_list()
                self.status_bar.showMessage("Cut operation cancelled")
            self.table.clearSelection()
        else:
            # Call the original keyPressEvent
            QTreeWidget.keyPressEvent(self.table, event)

    def load_image(self, filepath: str):
        """Load a floppy disk image"""
        # Clear any pending cut operation from previous image
        if self._cut_entries:
            self._cut_entries = []
            if self._last_copy_temp_dir and os.path.exists(self._last_copy_temp_dir):
                try:
                    shutil.rmtree(self._last_copy_temp_dir)
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup temp dir: {e}")
            self._last_copy_temp_dir = None
            self._clipboard_source_cluster = None
            QApplication.clipboard().clear()
        
        try:
            self.image = FAT12Image(filepath)
            self.image_path = filepath
            self.setWindowTitle(f"FloppyManager - {Path(filepath).name}")

            # Save as last opened image
            self.settings.setValue('last_image_path', filepath)

            self.refresh_file_list()
            self.status_bar.showMessage(f"Loaded: {Path(filepath).name}")
            self.logger.info(f"Loaded image: {filepath}")
        except Exception as e:
            self.logger.error(f"Failed to load image {filepath}: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to load image: {e}")
            self.image = None
            self.image_path = None
            self.setWindowTitle("FloppyManager")

    def on_search_text_changed(self, text):
        """Handle search text changes"""
        self.refresh_file_list()

    def _is_entry_cut(self, entry):
        """Check if an entry is in the cut list"""
        for cut_entry in self._cut_entries:
            # Compare parent cluster and name
            p1 = cut_entry.get('parent_cluster')
            if p1 == 0: p1 = None
            p2 = entry.get('parent_cluster')
            if p2 == 0: p2 = None
            
            if p1 == p2 and cut_entry.get('name') == entry.get('name'):
                return True
        return False
    
    def _normalize_parent_cluster(self, parent_cluster):
        """Normalize parent cluster: convert 0 or None to None for consistency"""
        if parent_cluster is None or parent_cluster == 0:
            return None
        return parent_cluster
    
    def _cleanup_temp_dir(self):
        """Cleanup temporary directory used for clipboard operations"""
        if self._last_copy_temp_dir and os.path.exists(self._last_copy_temp_dir):
            try:
                shutil.rmtree(self._last_copy_temp_dir)
                if hasattr(self, 'logger'):
                    self.logger.info(f"Cleaned up temp directory: {self._last_copy_temp_dir}")
            except Exception as e:
                if hasattr(self, 'logger'):
                    self.logger.warning(f"Failed to cleanup temp dir: {e}")
            finally:
                self._last_copy_temp_dir = None

    def _dim_item(self, item, dim):
        """Visually dim or undim an item"""
        if dim:
            # Dim text
            color = QColor(self.palette().text().color())
            color.setAlpha(128) # 50% opacity
            
            # Dim icon
            icon = item.icon(0)
            if not icon.isNull():
                pixmap = icon.pixmap(16, 16)
                transparent = QPixmap(pixmap.size())
                transparent.fill(Qt.GlobalColor.transparent)
                painter = QPainter(transparent)
                painter.setOpacity(0.5)
                painter.drawPixmap(0, 0, pixmap)
                painter.end()
                item.setIcon(0, QIcon(transparent))
        
            for col in range(item.columnCount()):
                item.setForeground(col, color)

    def _undim_all_items(self):
        """Undim all items in the tree"""
        # Helper to recursively undim
        def undim_recursive(item):
            # Restore text color
            color = QColor(self.palette().text().color())
            for col in range(item.columnCount()):
                item.setForeground(col, color)
            # Restore icon (refresh from entry data)
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry:
                item.setIcon(0, self.icon_provider.get_icon(entry))
            
            for i in range(item.childCount()):
                undim_recursive(item.child(i))

        for i in range(self.table.topLevelItemCount()):
            undim_recursive(self.table.topLevelItem(i))

    def refresh_file_list(self):
        """Refresh the file list from the image"""
        # Block signals to prevent itemChanged from firing during population
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clear()

            if not self.image:
                self.info_label.setText("")
                return

            try:
                # Get search text
                search_text = self.search_input.text().lower().strip() if hasattr(self, 'search_input') else ""
                
                # Get current sort settings to pre-sort entries
                header = self.table.header()
                sort_col = header.sortIndicatorSection()
                ascending = (header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder)

                # Iterative approach to prevent stack overflow and segfaults
                # Stack contains tuples: (parent_item, cluster_id)
                # Start with Root (cluster None)
                stack = [(None, None)] 
                visited_dirs = set()
                file_count = 0
                
                while stack:
                    parent_item, cluster = stack.pop()
                    
                    # Prevent infinite recursion / loops
                    # Use a unique key for visited check. Root is None.
                    cluster_key = cluster if cluster is not None else -1
                    if cluster_key in visited_dirs:
                        continue
                    visited_dirs.add(cluster_key)

                    entries = self.image.read_directory(cluster)
                    
                    # Pre-sort entries to match current table sort state
                    # This prevents visual jumping/flickering when sorting is re-enabled
                    def get_sort_key(e):
                        # Primary: Directories first (0) vs Files (1)
                        type_group = 0 if e['is_dir'] else 1
                        
                        # Secondary: Column data
                        val = ""
                        if sort_col == 0: val = e['name'].lower()
                        elif sort_col == 1: val = e['short_name'].lower()
                        elif sort_col == 2: val = (e['last_modified_date'] << 16) + e['last_modified_time']
                        elif sort_col == 3: val = e['file_type'].lower()
                        elif sort_col == 4: val = e['size']
                        elif sort_col == 5: val = e['attributes']
                        else: val = e['name'].lower()
                        
                        return (type_group, val)

                    entries.sort(key=get_sort_key)
                    if not ascending:
                        entries.reverse()
                    
                    for entry in entries:
                        if entry['name'] in ('.', '..'): continue
                        
                        if not self.show_hidden_files and entry['is_hidden']:
                            continue

                        # Apply search filter (files only)
                        if not entry['is_dir'] and search_text:
                            if (search_text not in entry['name'].lower() and 
                                search_text not in entry['short_name'].lower()):
                                continue
                        
                        # Add parent_cluster to entry for later use in cut/copy/paste operations
                        entry['parent_cluster'] = cluster

                        # Create item
                        if parent_item:
                            item = SortableTreeWidgetItem(parent_item)
                        else:
                            item = SortableTreeWidgetItem(self.table)
                        
                        # Store entry data
                        item.setData(0, Qt.ItemDataRole.UserRole, entry)

                        # Filename (0)
                        item.setText(0, entry['name'])
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        
                        # Short Name (1)
                        item.setText(1, entry['short_name'])

                        # Date Modified (2)
                        date_int = entry['last_modified_date']
                        time_int = entry['last_modified_time']
                        dt = decode_fat_datetime(date_int, time_int)
                        if dt:
                            date_str = dt.strftime("%m/%d/%Y %I:%M %p")
                            sort_key = int(dt.timestamp())
                        else:
                            date_str = ""
                            sort_key = -1
                            
                        item.setText(2, date_str)
                        item.setData(2, Qt.ItemDataRole.UserRole, sort_key)

                        # Type (3)
                        item.setText(3, entry['file_type'])
                        item.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)

                        # Size (4)
                        if entry['is_dir']:
                            item.setText(4, "")
                            item.setData(4, Qt.ItemDataRole.UserRole, -1)
                        else:
                            item.setText(4, f"{entry['size']:,} bytes")
                            item.setData(4, Qt.ItemDataRole.UserRole, entry['size'])

                        # Attr (5)
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
                        
                        item.setText(5, attr_str)
                        if tooltip_parts:
                            item.setToolTip(5, ", ".join(tooltip_parts))
                        item.setTextAlignment(5, Qt.AlignmentFlag.AlignCenter)

                        # Icon & Recursion
                        item.setIcon(0, self.icon_provider.get_icon(entry))
                        
                        # Check if cut
                        if self._is_entry_cut(entry):
                            self._dim_item(item, True)
                        
                        if entry['is_dir']:
                            stack.append((item, entry['cluster']))
                        else:
                            file_count += 1

                fmt_name = self.image.get_format_name()
                self.info_label.setText(f"{fmt_name} | {file_count} files | {self.image.get_free_space():,} bytes free")
                self.status_bar.showMessage(f"Loaded {file_count} files")
            
            except FAT12CorruptionError as e:
                QMessageBox.critical(self, "Filesystem Corruption Detected", f"Error reading directory structure:\n{e}\n\nThe disk image may be corrupted.")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to read directory: {e}")
        finally:
            # Re-enable sorting immediately (no timer) to prevent flicker
            self.table.setSortingEnabled(True)
            self.table.setUpdatesEnabled(True)
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
        
        viewer = DirectoryViewer(self.image, self)
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
        
        try:
            viewer = FATViewer(self.image, self)
            viewer.exec()
        except FAT12CorruptionError as e:
            QMessageBox.critical(self, "Filesystem Corruption", f"Cannot open FAT Viewer due to filesystem corruption:\n{e}")

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

    def add_files_from_list(self, filenames: list, parent_cluster: int = -1, rename_on_collision: bool = False, refresh: bool = True):
        """Add files from a list of file paths (used by dialog, drag-drop, and paste)"""
        if not self.image:
            return 0

        # Determine parent cluster from selection if not specified
        if parent_cluster == -1:
            parent_cluster = None
            selected_items = self.table.selectedItems()
            if selected_items:
                item = selected_items[0]
                entry = item.data(0, Qt.ItemDataRole.UserRole)
                if entry:
                    if entry['is_dir']:
                        parent_cluster = entry['cluster']
                    else:
                        parent_cluster = entry.get('parent_cluster')
                        if parent_cluster == 0: parent_cluster = None

        # Sort files by name (case-insensitive) to ensure deterministic order
        filenames.sort(key=lambda x: Path(x).name.lower())

        success_count = 0
        fail_count = 0

        for filepath in filenames:
            path_obj = Path(filepath)
            original_name = path_obj.name
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()

                # Get modification time
                try:
                    stat = path_obj.stat()
                    modification_dt = datetime.fromtimestamp(stat.st_mtime)
                except Exception:
                    modification_dt = None

                # Predict the 8.3 name that will be used
                short_name_83 = self.image.predict_short_name(original_name, self.use_numeric_tail, parent_cluster)
                
                # Format 8.3 name for display (add dot back)
                short_display = format_83_name(short_name_83)

                # Check if file already exists
                # Check in the specific directory
                entries = self.image.read_directory(parent_cluster)
                
                # Check for LFN collision (case-insensitive) first
                collision_entry = next((e for e in entries if e['name'].lower() == original_name.lower()), None)

                if not collision_entry:
                    # Check for Short Name collision if no LFN collision found
                    collision_entry = next((e for e in entries if e['short_name'].upper() == short_name_83), None)

                if collision_entry:
                    if rename_on_collision:
                        # Generate new name to avoid collision (e.g. "File - Copy.txt")
                        name_parts = os.path.splitext(original_name)
                        base_name = f"{name_parts[0]} - Copy"
                        extension = name_parts[1]
                        
                        new_name = f"{base_name}{extension}"
                        
                        # Check for collisions with new name
                        existing_names_lfn = {e['name'].lower() for e in entries}
                        
                        counter = 2
                        while new_name.lower() in existing_names_lfn:
                            new_name = f"{base_name} ({counter}){extension}"
                            counter += 1
                        
                        original_name = new_name
                        # Do not delete existing file, we are creating a copy
                    else:
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
                self.image.write_file_to_image(original_name, data, self.use_numeric_tail, modification_dt, parent_cluster)
                success_count += 1

            except FAT12CorruptionError as e:
                fail_count += 1
                self.logger.error(f"Corruption error writing {original_name}: {e}")
                QMessageBox.critical(self, "Filesystem Corruption", f"Cannot write {Path(filepath).name}:\n{e}")

            except FAT12Error as e:
                fail_count += 1
                self.logger.warning(f"FAT12 error writing {original_name}: {e}")
                QMessageBox.warning(self, "Error", f"Failed to write {Path(filepath).name}: {e}")

            except Exception as e:
                fail_count += 1
                self.logger.error(f"Unexpected error writing {original_name}: {e}", exc_info=True)
                QMessageBox.critical(self, "Error", f"Failed to add {Path(filepath).name}: {e}")

        if refresh:
            self.refresh_file_list()

        if success_count > 0:
            self.status_bar.showMessage(f"Added {success_count} file(s)")
            self.logger.info(f"Successfully added {success_count} file(s)")
        if fail_count > 0:
            QMessageBox.warning(self, "Warning", f"Failed to add {fail_count} file(s)")
            
        return success_count

    def create_new_folder(self):
        """Create a new directory"""
        if not self.image:
            QMessageBox.information(self, "No Image", "Please create a new image or open an existing one first.")
            return

        # Determine parent cluster based on selection
        parent_cluster = None
        selected_items = self.table.selectedItems()
        
        if selected_items:
            item = selected_items[0]
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry:
                if entry['is_dir']:
                    parent_cluster = entry['cluster']
                else:
                    parent_cluster = entry.get('parent_cluster')
                    # Convert 0 to None for root if necessary
                    if parent_cluster == 0:
                        parent_cluster = None
        
        name = "New Folder"
        try:
            # Generate unique default name
            entries = self.image.read_directory(parent_cluster)
            existing_names = {e['name'].lower() for e in entries}
            
            base_name = "New Folder"
            name = base_name
            counter = 2
            while name.lower() in existing_names:
                name = f"{base_name} ({counter})"
                counter += 1

            self.image.create_directory(name, parent_cluster, self.use_numeric_tail)
            self.refresh_file_list()
            self.status_bar.showMessage(f"Created folder: {name}")
            self.logger.info(f"Created directory: {name}")
            
            # Find and select the new folder to start renaming
            items = self.table.findItems(name, Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchExactly, 0)
            
            target_item = None
            for item in items:
                entry = item.data(0, Qt.ItemDataRole.UserRole)
                if entry:
                    item_parent = entry.get('parent_cluster')
                    if item_parent == 0: item_parent = None
                    
                    if item_parent == parent_cluster:
                        target_item = item
                        break
            
            if target_item:
                # Ensure parent is expanded so the new item is visible
                parent_item = target_item.parent()
                while parent_item:
                    parent_item.setExpanded(True)
                    parent_item = parent_item.parent()

                self.table.clearSelection()
                target_item.setSelected(True)
                self.table.setCurrentItem(target_item)
                self.table.scrollToItem(target_item)
                # Start rename
                self.start_rename()

        except FAT12CorruptionError as e:
            self.logger.error(f"Corruption detected creating directory {name}: {e}")
            QMessageBox.critical(self, "Filesystem Corruption", f"Cannot create directory:\n{e}")
        except FAT12Error as e:
            self.logger.warning(f"Failed to create directory {name}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to create directory: {e}")

    def extract_selected(self):
        """Extract selected files"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return

        selected_items = self.table.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Info", "Please select files to extract")
            return

        save_dir = QFileDialog.getExistingDirectory(self, "Select folder to save files")
        if not save_dir:
            return

        success_count = 0

        for item in selected_items:
            entry = item.data(0, Qt.ItemDataRole.UserRole)

            if entry:
                try:
                    data = self.image.extract_file(entry)
                    # Use the long filename (original name) when extracting
                    output_path = os.path.join(save_dir, entry['name'])

                    with open(output_path, 'wb') as f:
                        f.write(data)

                    success_count += 1
                except FAT12CorruptionError as e:
                    self.logger.error(f"Corruption extracting {entry['name']}: {e}")
                    QMessageBox.critical(self, "Filesystem Corruption", f"Cannot extract '{entry['name']}':\n{e}")
                except Exception as e:
                    self.logger.error(f"Failed to extract {entry['name']}: {e}", exc_info=True)
                    QMessageBox.critical(self, "Error", f"Failed to extract {entry['name']}: {e}")

        if success_count > 0:
            self.logger.info(f"Extracted {success_count} file(s) to {save_dir}")
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
        fail_count = 0
        corruption_errors = []

        for entry in files_to_extract:
            try:
                data = self.image.extract_file(entry)
                output_path = os.path.join(save_dir, entry['name'])
                with open(output_path, 'wb') as f:
                    f.write(data)
                success_count += 1
            except FAT12CorruptionError as e:
                self.logger.error(f"Corruption extracting {entry['name']}: {e}")
                fail_count += 1
                corruption_errors.append(f"{entry['name']}: {e}")
            except Exception as e:
                self.logger.error(f"Failed to extract {entry['name']}: {e}", exc_info=True)
                fail_count += 1

        if success_count > 0:
            self.logger.info(f"Extracted {success_count} file(s) to {save_dir}")
            self.status_bar.showMessage(f"Extracted {success_count} file(s) to {save_dir}")
            
        if corruption_errors:
            QMessageBox.critical(self, "Filesystem Corruption", 
                               f"Corruption detected during extraction:\n\n" + "\n".join(corruption_errors[:5]) + 
                               (f"\n...and {len(corruption_errors)-5} more." if len(corruption_errors) > 5 else ""))
        elif fail_count > 0:
            QMessageBox.warning(self, "Extraction Incomplete", f"Successfully extracted {success_count} files.\nFailed to extract {fail_count} files.")
        elif success_count > 0:
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
        fail_count = 0
        corruption_errors = []

        try:
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for entry in files_to_extract:
                    try:
                        data = self.image.extract_file(entry)
                        # Use the long filename
                        zipf.writestr(entry['name'], data)
                        success_count += 1
                    except FAT12CorruptionError as e:
                        self.logger.error(f"Corruption archiving {entry['name']}: {e}")
                        fail_count += 1
                        corruption_errors.append(f"{entry['name']}: {e}")
                    except Exception as e:
                        self.logger.error(f"Failed to archive {entry['name']}: {e}", exc_info=True)
                        fail_count += 1
            
            if success_count > 0:
                self.logger.info(f"Archived {success_count} file(s) to {zip_filename}")
                self.status_bar.showMessage(f"Archived {success_count} file(s) to {Path(zip_filename).name}")
                
            if corruption_errors:
                QMessageBox.critical(self, "Filesystem Corruption", 
                                   f"Corruption detected during archiving:\n\n" + "\n".join(corruption_errors[:5]))
            elif fail_count > 0:
                QMessageBox.warning(self, "Archive Incomplete", f"Archived {success_count} files.\nFailed to add {fail_count} files to archive.")
            elif success_count > 0:
                QMessageBox.information(self, "Success", f"Archived {success_count} file(s) to ZIP file")
                
        except Exception as e:
             self.logger.error(f"Failed to create ZIP file: {e}", exc_info=True)
             QMessageBox.critical(self, "Error", f"Failed to create ZIP file: {e}")

    def delete_selected(self):
        """Delete selected items"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return

        selected_items = self.table.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Info", "Please select items to delete")
            return

        if self.confirm_delete:
            response = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Delete {len(selected_items)} item(s) from the disk image?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if response == QMessageBox.StandardButton.No:
                return

        self.logger.info(f"User requested delete of {len(selected_items)} items")
        success_count = 0
        items_to_delete = []
        read_only_items = []

        for item in selected_items:
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry:
                items_to_delete.append(entry)
                if entry['is_read_only']:
                    read_only_items.append(entry)

        # Warn about read-only items
        if read_only_items:
            msg = f"{len(read_only_items)} of the selected items are Read-Only.\n\nDo you want to delete them anyway?"
            response = QMessageBox.warning(
                self,
                "Read-Only Items",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if response == QMessageBox.StandardButton.No:
                return

        # Proceed with deletion
        for entry in items_to_delete:
            if entry.get('is_dir'):
                try:
                    self.image.delete_directory(entry, recursive=True)
                    success_count += 1
                except FAT12CorruptionError as e:
                    self.logger.error(f"Corruption deleting directory {entry['name']}: {e}")
                    QMessageBox.critical(self, "Filesystem Corruption", f"Cannot delete directory {entry['name']}:\n{e}")
                except FAT12Error as e:
                    self.logger.warning(f"Failed to delete directory {entry['name']}: {e}")
                    QMessageBox.critical(self, "Error", f"Failed to delete directory {entry['name']}: {e}")
            else:
                try:
                    self.image.delete_file(entry)
                    success_count += 1
                except FAT12Error as e:
                    self.logger.warning(f"Failed to delete file {entry['name']}: {e}")
                    QMessageBox.critical(self, "Error", f"Failed to delete {entry['name']}: {e}")

        self.refresh_file_list()

        if success_count > 0:
            self.status_bar.showMessage(f"Deleted {success_count} item(s)")
            self.logger.info(f"Successfully deleted {success_count} item(s)")
            
            # Clear cut selection if any cut files were deleted
            if self._cut_entries:
                # Check if any deleted items were in the cut list
                deleted_set = {(e['cluster'], e['name'].lower()) for e in items_to_delete}
                cut_set = {(e['cluster'], e['name'].lower()) for e in self._cut_entries}
                
                if deleted_set & cut_set:  # If there's any overlap
                    self.logger.info("Clearing cut selection due to file deletion")
                    self._cut_entries = []
                    if self._last_copy_temp_dir and os.path.exists(self._last_copy_temp_dir):
                        try:
                            shutil.rmtree(self._last_copy_temp_dir)
                        except Exception as e:
                            self.logger.warning(f"Failed to cleanup temp dir: {e}")
                        finally:
                            self._last_copy_temp_dir = None
                    QApplication.clipboard().clear()

    def duplicate_selected(self):
        """Duplicate the selected file(s) inside the image"""
        if not self.image:
            return
            
        selected_items = self.table.selectedItems()
        if not selected_items:
            return

        success_count = 0

        for item in selected_items:
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if not entry or entry['is_dir']:
                continue

            try:
                # Extract file data
                data = self.image.extract_file(entry)
                
                # Determine parent cluster
                parent_cluster = entry.get('parent_cluster')
                if parent_cluster == 0: parent_cluster = None

                # Get existing files to check for collisions
                entries = self.image.read_directory(parent_cluster)
                existing_names = {e['name'].lower() for e in entries}
                
                # Create new name (e.g. "File.txt" -> "File - Copy.txt")
                name_parts = os.path.splitext(entry['name'])
                base_name = f"{name_parts[0]} - Copy"
                extension = name_parts[1]
                
                new_name = f"{base_name}{extension}"
                
                # Check for collisions and increment if necessary
                counter = 2
                while new_name.lower() in existing_names:
                    new_name = f"{base_name} ({counter}){extension}"
                    counter += 1
                
                # Write the new file
                self.image.write_file_to_image(new_name, data, self.use_numeric_tail, None, parent_cluster)
                success_count += 1
                self.logger.info(f"Duplicated file '{entry['name']}' to '{new_name}'")
            except FAT12CorruptionError as e:
                self.logger.error(f"Corruption duplicating file {entry['name']}: {e}")
                QMessageBox.critical(self, "Filesystem Corruption", f"Cannot duplicate file:\n{e}")
            except FAT12Error as e:
                self.logger.warning(f"Failed to duplicate file {entry['name']}: {e}")
                QMessageBox.warning(self, "Error", f"Failed to duplicate file: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error copying file {entry['name']}: {e}", exc_info=True)
                QMessageBox.critical(self, "Error", f"Failed to copy file: {e}")

        if success_count > 0:
            self.refresh_file_list()
            self.status_bar.showMessage(f"Copied {success_count} file(s)")

    def cut_selected(self):
        """Cut selected files (copy to clipboard and mark for deletion on paste)"""
        if not self.image:
            return
        
        selected_items = self.table.selectedItems()
        if not selected_items:
            return
        
        # Count files vs directories
        file_count = 0
        dir_count = 0
        for item in selected_items:
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry:
                if entry['is_dir']:
                    dir_count += 1
                else:
                    file_count += 1
        
        # Warn if directories were selected
        if dir_count > 0:
            QMessageBox.information(
                self,
                "Directories Not Supported",
                f"Cut/Copy operations currently support files only.\n\n"
                f"{dir_count} director{'y' if dir_count == 1 else 'ies'} will be excluded."
            )
        
        if file_count == 0:
            self.status_bar.showMessage("No files selected to cut")
            return
            
        # Perform copy to clipboard first
        self.copy_to_clipboard()
        
        # Store selected entries for later deletion upon paste
        self._cut_entries = []
        for item in selected_items:
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            # Only cut files, as we don't support folder copy/paste yet
            if entry and not entry['is_dir']:
                self._cut_entries.append(entry)
                self._dim_item(item, True)
        
        self.status_bar.showMessage(f"Cut {len(self._cut_entries)} file(s) to clipboard")

    def copy_to_clipboard(self):
        """Copy selected files to system clipboard"""
        if not self.image:
            return

        selected_items = self.table.selectedItems()
        if not selected_items:
            return
        
        # Count files vs directories
        file_count = 0
        dir_count = 0
        for item in selected_items:
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry:
                if entry['is_dir']:
                    dir_count += 1
                else:
                    file_count += 1

        # Store source cluster to determine if we are pasting into the same folder later
        if selected_items:
            first_entry = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if first_entry:
                # parent_cluster is now always present in entries (set in refresh_file_list)
                self._clipboard_source_cluster = self._normalize_parent_cluster(first_entry.get('parent_cluster'))
            else:
                self._clipboard_source_cluster = None
        else:
            self._clipboard_source_cluster = None

        # If we had a pending cut, undim those items visually since this copy cancels the cut
        if self._cut_entries:
            self._undim_all_items()

        # Clear any pending cut operation since we are doing a new copy
        self._cut_entries = []

        # Cleanup previous temp dir
        if self._last_copy_temp_dir and os.path.exists(self._last_copy_temp_dir):
            try:
                shutil.rmtree(self._last_copy_temp_dir)
            except Exception as e:
                self.logger.warning(f"Failed to cleanup old temp dir: {e}")
        
        self._last_copy_temp_dir = tempfile.mkdtemp(prefix="fat12_copy_")
        
        urls = []
        for item in selected_items:
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry and not entry['is_dir']:
                try:
                    data = self.image.extract_file(entry)
                    filename = entry['name']
                    filepath = os.path.join(self._last_copy_temp_dir, filename)
                    with open(filepath, 'wb') as f:
                        f.write(data)
                    urls.append(QUrl.fromLocalFile(filepath))
                except Exception as e:
                    self.logger.warning(f"Failed to extract {entry['name']} for copy: {e}")
        
        # Warn if directories were excluded.
        if dir_count > 0:
            QMessageBox.information(
                self,
                "Directories Not Supported",
                f"Copy operations currently support files only.\n\n"
                f"{dir_count} director{'y' if dir_count == 1 else 'ies'} will be excluded."
            )

        if urls:
            mime_data = QMimeData()
            mime_data.setUrls(urls)
            QApplication.clipboard().setMimeData(mime_data)
            self.status_bar.showMessage(f"Copied {len(urls)} file(s) to clipboard")
        elif file_count == 0:
            self.status_bar.showMessage("No files selected to copy")

    def paste_from_clipboard(self):
        """Paste files from system clipboard"""
        if not self.image:
            return

        mime_data = QApplication.clipboard().mimeData()
        if not mime_data or not mime_data.hasUrls():
            self.status_bar.showMessage("Clipboard is empty or contains no files")
            return

        files = []
        for url in mime_data.urls():
            if url.isLocalFile():
                fpath = url.toLocalFile()
                if os.path.isfile(fpath):
                    files.append(fpath)

        # Check if these files match our pending cut operation
        is_internal_cut = False
        is_internal_copy = False
        if self._cut_entries and self._last_copy_temp_dir and files:
            # Check if ALL files are inside our temp dir (this is a cut operation)
            try:
                temp_parent = Path(self._last_copy_temp_dir).resolve()
                is_internal_cut = all(
                    Path(f).parent.resolve() == temp_parent 
                    for f in files
                )
            except Exception as e:
                self.logger.warning(f"Failed to verify internal cut: {e}")
                is_internal_cut = False
        elif self._last_copy_temp_dir and files:
            # Check if this is an internal copy (not cut)
            try:
                temp_parent = Path(self._last_copy_temp_dir).resolve()
                is_internal_copy = all(
                    Path(f).parent.resolve() == temp_parent 
                    for f in files
                )
            except Exception as e:
                self.logger.warning(f"Failed to verify internal copy: {e}")
                is_internal_copy = False
        
        # If we have cut entries but the clipboard files are NOT from our temp dir,
        # it means the user copied something else externally.
        # We should cancel the cut operation to prevent deleting the original files.
        if self._cut_entries and not is_internal_cut:
            self._cut_entries = []
            self._undim_all_items()
            self.status_bar.showMessage("External clipboard content detected. Cut operation cancelled.")

        if files:
            # Determine target parent cluster from selection (same logic as add_files_from_list)
            parent_cluster = None
            selected_items = self.table.selectedItems()
            if selected_items:
                item = selected_items[0]
                entry = item.data(0, Qt.ItemDataRole.UserRole)
                if entry:
                    if entry['is_dir']:
                        parent_cluster = entry['cluster']
                    else:
                        parent_cluster = entry.get('parent_cluster')
            
            # Normalize for consistent comparison
            parent_cluster = self._normalize_parent_cluster(parent_cluster)

            # If this is a paste from a cut operation, check if source == destination
            if self._cut_entries:
                # Check if we are pasting into the same directory as the source
                # We assume all cut items are from the same directory (current view)
                first_cut = self._cut_entries[0]
                src_parent = self._normalize_parent_cluster(first_cut.get('parent_cluster'))
                
                if src_parent == parent_cluster:
                    self._cut_entries = []
                    QApplication.clipboard().clear()
                    self.refresh_file_list()
                    # Set message after refresh so it doesn't get overwritten
                    self.status_bar.showMessage("Source and destination are the same. Move cancelled.")
                    return

            # Check if this is an internal paste (source is our temp dir)
            # If so, enable rename_on_collision to support "Copy/Paste to same folder -> Duplicate"
            rename_on_collision = False
            if self._last_copy_temp_dir and files and is_internal_copy:
                try:
                    # Only auto-rename if pasting back to the exact same source folder
                    if self._clipboard_source_cluster == parent_cluster:
                        rename_on_collision = True
                except Exception:
                    pass

            # If this is a CUT operation, disable rename_on_collision to force prompt/overwrite behavior
            if self._cut_entries:
                rename_on_collision = False

            # Add files (Copy)
            success_count = self.add_files_from_list(files, parent_cluster, rename_on_collision)
            
            # If this was a cut operation, handle deletion of originals
            if self._cut_entries:
                if success_count == len(files):
                    # All files pasted successfully - delete originals
                    deleted_count = 0
                    
                    # Group entries by parent cluster to minimize directory reads during verification
                    entries_by_parent = {}
                    for entry in self._cut_entries:
                        pc = self._normalize_parent_cluster(entry.get('parent_cluster'))
                        if pc not in entries_by_parent:
                            entries_by_parent[pc] = []
                        entries_by_parent[pc].append(entry)

                    for pc, entries in entries_by_parent.items():
                        try:
                            # Verify files still exist and match before deleting
                            current_dir_entries = self.image.read_directory(pc)
                            
                            # Build map using cluster+name as key for robustness
                            current_map = {}
                            for e in current_dir_entries:
                                key = (e['cluster'], e['name'].lower())
                                current_map[key] = e

                            for entry in entries:
                                # Use cluster+name for matching instead of index
                                key = (entry['cluster'], entry['name'].lower())
                                match = current_map.get(key)
                                
                                if match and match['index'] == entry['index']:
                                    # Extra safety: verify index still matches
                                    self.image.delete_file(entry)
                                    deleted_count += 1
                                else:
                                    self.logger.warning(
                                        f"Skipping delete of cut file {entry['name']}: "
                                        f"File changed or no longer exists at source."
                                    )
                        except Exception as e:
                            self.logger.warning(f"Error processing cut deletion for parent {pc}: {e}")
                    
                    self._cut_entries = []
                    QApplication.clipboard().clear()
                    self.refresh_file_list()
                    self.status_bar.showMessage(f"Moved {deleted_count} file(s)")
                    
                elif success_count > 0:
                    # Partial success - ask user what to do
                    response = QMessageBox.question(
                        self,
                        "Partial Paste Failure",
                        f"Only {success_count} of {len(files)} files were pasted successfully.\n\n"
                        f"The original files have NOT been deleted.\n"
                        f"Do you want to clear the cut operation?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    
                    if response == QMessageBox.StandardButton.Yes:
                        self._cut_entries = []
                        QApplication.clipboard().clear()
                        self.refresh_file_list()
                    else:
                        self.status_bar.showMessage(
                            f"Partial paste completed. Cut files remain at source for retry."
                        )
                else:
                    # Complete failure - keep cut state for retry
                    self.status_bar.showMessage(
                        "Paste failed. Cut files remain at source. You can retry pasting."
                    )
        else:
            self.status_bar.showMessage("Clipboard contains no valid files")

    def create_new_image(self):
        """Create a new blank floppy disk image"""
        # Ask for format and OEM Name
        formats = list(FAT12Image.FORMATS.keys())
        display_names = [FAT12Image.FORMATS[k]['name'] for k in formats]
        
        dialog = NewImageDialog(formats, display_names, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        selected_key = dialog.selected_format
        oem_name = dialog.oem_name

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
            FAT12Image.create_empty_image(filename, selected_key, oem_name)

            # Load the new image
            self.load_image(filename)

            QMessageBox.information(
                self,
                "Success",
                f"Created new image:\n{Path(filename).name}"
            )
            self.logger.info(f"Created new image: {filename}")
        except Exception as e:
            self.logger.error(f"Failed to create image: {e}", exc_info=True)
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
            self.logger.info(f"Image saved as: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save image: {e}")

    def format_disk(self):
        """Format the disk - erase all files and reset to empty state"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded to format.")
            return
        
        # Ask for format type
        dialog = FormatDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        full_format = dialog.full_format
        format_type_desc = "FULL" if full_format else "QUICK"
        
        response = QMessageBox.warning(
            self,
            "Format Disk",
            "⚠️ WARNING: This will permanently erase ALL files on the disk!\n\n"
            f"Disk: {Path(self.image_path).name}\n\n"
            f"Type: {format_type_desc} FORMAT\n\n"
            "Are you sure you want to format this disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No  # Default to No for safety
        )
        
        if response == QMessageBox.StandardButton.No:
            return
        
        try:
            # Format the disk
            self.image.format_disk(full_format=full_format)
            
            # Refresh the file list to show empty disk
            self.refresh_file_list()
            
            QMessageBox.information(
                self,
                "Format Complete",
                f"Disk has been formatted successfully ({format_type_desc}).\nAll files have been erased."
            )
            
            self.status_bar.showMessage(f"Disk formatted ({format_type_desc}) - all files erased")
            self.logger.info(f"Disk formatted ({format_type_desc})")
        except Exception as e:
            self.logger.error(f"Failed to format disk: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to format disk: {e}")

    def defragment_disk(self):
        """Defragment the disk"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return
            
        response = QMessageBox.question(
            self,
            "Defragment Disk",
            "This will reorganize all files to be contiguous and sorted.\n"
            "This operation rewrites the entire disk image.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if response == QMessageBox.StandardButton.Yes:
            try:
                self.image.defragment_filesystem()
                self.refresh_file_list()
                self.status_bar.showMessage("Disk defragmented successfully")
                QMessageBox.information(self, "Success", "Disk defragmentation complete.")
                self.logger.info("Disk defragmented successfully")
            except FAT12CorruptionError as e:
                QMessageBox.critical(self, "Filesystem Corruption", f"Defragmentation aborted due to corruption:\n{e}")
            except Exception as e:
                self.logger.error(f"Defragmentation failed: {e}", exc_info=True)
                QMessageBox.critical(self, "Error", f"Defragmentation failed: {e}")

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

    def close_image(self):
        """Close the currently open image"""
        if self.image:
            self.image = None
            self.image_path = None
            self.setWindowTitle("FloppyManager")
            
            # Clear any pending cut/copy state to prevent cross-image operations
            if self._cut_entries:
                self._cut_entries = []
                QApplication.clipboard().clear()
            self._clipboard_source_cluster = None
            if self._last_copy_temp_dir and os.path.exists(self._last_copy_temp_dir):
                try:
                    shutil.rmtree(self._last_copy_temp_dir)
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup temp dir: {e}")
                finally:
                    self._last_copy_temp_dir = None
            
            self.refresh_file_list()
            self.logger.info("Image closed")
            self.status_bar.showMessage("Image closed")

    def view_log(self):
        """Show the application log"""
        if self.log_viewer is None:
            self.log_viewer = LogViewer("floppymanager.log", self)
            self.log_viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.log_viewer.finished.connect(self._on_log_viewer_closed)
            self.log_viewer.show()
        else:
            self.log_viewer.raise_()
            self.log_viewer.activateWindow()

    def _on_log_viewer_closed(self):
        self.log_viewer = None

    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(self, "About", about_html)

    def closeEvent(self, event):
        """Handle window close event - save state"""
        # Save window geometry and State
        self.settings.setValue('window_geometry', self.saveGeometry())
        self.settings.setValue('window_state', self.saveState())
        
        # Cleanup temp dir
        self._cleanup_temp_dir()

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

    def start_rename(self):
        """Start inline renaming of the selected file (Windows-style)"""
        if not self.image:
            return
        
        # Reset click tracking
        self._last_click_time = 0
        self._last_click_row = -1
        self._last_click_col = -1
        
        # Get selected row
        selected_items = self.table.selectedItems()
        if len(selected_items) != 1:
            QMessageBox.information(
                self,
                "Select One File",
                "Please select exactly one file to rename."
            )
            return
        
        item = selected_items[0]
        
        # Make sure we're on the filename column
        self.table.setCurrentItem(item, 0)
        
        # Tell the delegate to customize selection
        self.rename_delegate.should_customize_selection = True
        
        # Temporarily enable editing, start edit, then disable again
        self.table.setEditTriggers(QTreeWidget.EditTrigger.AllEditTriggers)
        self.table.editItem(item, 0)
        
        # Disable editing triggers after a moment (after editor is created)
        QTimer.singleShot(100, lambda: self.table.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers))
    
    def edit_file_attributes(self):
        """Open the file attributes editor dialog"""
        if not self.image:
            return
        
        # Get selected row
        selected_items = self.table.selectedItems()
        if len(selected_items) != 1:
            QMessageBox.information(
                self,
                "Select One Item",
                "Please select exactly one item to edit attributes."
            )
            return
        
        item = selected_items[0]
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        
        if not entry:
            QMessageBox.warning(self, "Error", "Could not find entry.")
            return
        
        # Show the attributes dialog
        dialog = FileAttributesDialog(entry, self.image, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the new attributes
            attrs = dialog.get_attributes()
            
            # Update the attributes
            try:
                self.image.set_entry_attributes(
                    entry,
                    is_read_only=attrs['is_read_only'],
                    is_hidden=attrs['is_hidden'],
                    is_system=attrs['is_system'],
                    is_archive=attrs['is_archive']
                )
                self.status_bar.showMessage(f"Attributes updated for {entry['name']}", 3000)
                self.refresh_file_list()
            except FAT12Error as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to update attributes for {entry['name']}: {e}"
                )
    
    def on_item_changed(self, item, column):
        """Handle item changes (when rename is completed)"""
        if self._editing_in_progress:
            return
        
        # Only process changes to the filename column (column 0)
        if column != 0:
            return
        
        self._editing_in_progress = True
        
        # Defer the actual processing to avoid interfering with Qt's editing lifecycle
        QTimer.singleShot(0, lambda: self.process_rename(item))
    
    def process_rename(self, item):
        """Process the rename after Qt's editing lifecycle completes"""
        try:
            # Edit triggers are already NoEditTriggers - no need to set again
            
            new_name = item.text(0).strip()
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            
            if not entry:
                self._editing_in_progress = False
                return
            
            old_name = entry['name']
            
            # Check if name actually changed
            if new_name == old_name or not new_name:
                # User cancelled or didn't change anything
                # Silently restore original name
                self.table.itemChanged.disconnect(self.on_item_changed)
                item.setText(0, old_name)
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
                item.setText(0, old_name)
                self.table.itemChanged.connect(self.on_item_changed)
                self._editing_in_progress = False
                return
            
            # Attempt the rename
            try:
                self.image.rename_entry(entry, new_name, self.use_numeric_tail)
                self.status_bar.showMessage(f"Renamed '{old_name}' to '{new_name}'")
                # Refresh the file list to show the new name and short name
                self.refresh_file_list()
            except FAT12CorruptionError as e:
                self.logger.error(f"Corruption renaming {old_name}: {e}")
                QMessageBox.critical(self, "Filesystem Corruption", f"Cannot rename file:\n{e}")
            except FAT12Error as e:
                self.logger.warning(f"Failed to rename {old_name} to {new_name}: {e}")
                QMessageBox.critical(
                    self,
                    "Rename Failed",
                    f"Could not rename '{old_name}' to '{new_name}'.\n\n{e}"
                )
                # Temporarily disconnect to avoid recursion
                self.table.itemChanged.disconnect(self.on_item_changed)
                item.setText(0, old_name)
                self.table.itemChanged.connect(self.on_item_changed)
        
        finally:
            self._editing_in_progress = False

def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("FloppyManager")
    app.setOrganizationName("FloppyManager")
    # Set application style
    app.setStyle('Fusion')

    # Create main window
    window = FloppyManagerWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
