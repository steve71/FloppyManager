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
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from vfat_utils import format_83_name, decode_fat_datetime


from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QFileDialog, QMessageBox, QLabel, QStatusBar, QMenu,
    QDialog, QToolBar, QStyle, QInputDialog, QHeaderView, QLineEdit
)
from PySide6.QtCore import Qt, QSettings, QTimer, QSize
from PySide6.QtGui import QIcon, QAction, QKeySequence, QActionGroup, QPalette, QColor

# Import the FAT12 handler
from fat12_handler import FAT12Image
from fat12_directory import FAT12Error, FAT12CorruptionError
from gui_components import (
    BootSectorViewer, DirectoryViewer, FATViewer, FileAttributesDialog,
    SortableTreeWidgetItem, FileTreeWidget, RenameDelegate, FormatDialog,
    NewImageDialog, LogViewer
)
from file_icons import FileIconProvider

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
        self.table.setHeaderLabels(['Filename', 'Short Name (8.3)', 'Date Modified', 'Type', 'Size', 'Attr'])

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

        selected_items = self.table.selectedItems()

        menu = QMenu()
        
        new_folder_action = QAction("New Folder", self)
        new_folder_action.triggered.connect(self.create_new_folder)
        menu.addAction(new_folder_action)
        
        menu.addSeparator()
        
        if not selected_items:
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
            
            copy_action = QAction("Copy", self)
            copy_action.triggered.connect(self.copy_selected)
            menu.addAction(copy_action)
        
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
        defrag_action.setToolTip("Optimize disk by making all files contiguous")
        defrag_action.triggered.connect(self.defragment_disk)
        file_menu.addAction(defrag_action)

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

        root_dir_action = QAction("&Directory Information...", self)
        root_dir_action.setToolTip("View complete directory details")
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

        log_action = QAction("View &Log...", self)
        log_action.triggered.connect(self.view_log)
        help_menu.addAction(log_action)

        help_menu.addSeparator()

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
        else:
            # Call the original keyPressEvent
            QTreeWidget.keyPressEvent(self.table, event)

    def load_image(self, filepath: str):
        """Load a floppy disk image"""
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
                        
                        if entry['is_dir']:
                            stack.append((item, entry['cluster']))
                        else:
                            file_count += 1

                self.info_label.setText(f"{file_count} files | {self.image.get_free_space():,} bytes free")
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

        # Determine parent cluster from selection
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

        self.add_files_from_list(filenames, parent_cluster)

    def add_files_from_list(self, filenames: list, parent_cluster: int = None):
        """Add files from a list of file paths (used by both dialog and drag-drop)"""
        if not self.image:
            return 0

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
        
        # Ask for folder name
        name, ok = QInputDialog.getText(self, "New Folder", "Folder Name:")
        if ok:
            name = name.strip()
            if not name:
                QMessageBox.warning(self, "Invalid Name", "Folder name cannot be empty.")
                return

            invalid_chars = '<>:"/\\|?*'
            if any(c in name for c in invalid_chars):
                QMessageBox.warning(self, "Invalid Name", f"Folder name cannot contain characters: {invalid_chars}")
                return

        if ok:
            name = name.strip()
            if not name:
                QMessageBox.warning(self, "Invalid Name", "Folder name cannot be empty.")
                return

            invalid_chars = '<>:"/\\|?*'
            if any(c in name for c in invalid_chars):
                QMessageBox.warning(self, "Invalid Name", f"Folder name cannot contain characters: {invalid_chars}")
                return

            try:
                self.image.create_directory(name, parent_cluster, self.use_numeric_tail)
                self.refresh_file_list()
                self.status_bar.showMessage(f"Created folder: {name}")
                self.logger.info(f"Created directory: {name}")
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

    def copy_selected(self):
        """Copy the selected file"""
        if not self.image:
            return
            
        selected_items = self.table.selectedItems()
        if len(selected_items) != 1:
            return
            
        entry = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if not entry or entry['is_dir']:
            return
            
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
            self.refresh_file_list()
            self.status_bar.showMessage(f"Copied: {new_name}")
            self.logger.info(f"Copied file '{entry['name']}' to '{new_name}'")
        except FAT12CorruptionError as e:
            self.logger.error(f"Corruption copying file {entry['name']}: {e}")
            QMessageBox.critical(self, "Filesystem Corruption", f"Cannot copy file:\n{e}")
        except FAT12Error as e:
            self.logger.warning(f"Failed to copy file {entry['name']}: {e}")
            QMessageBox.warning(self, "Error", f"Failed to copy file: {e}")
                
        except Exception as e:
            self.logger.error(f"Unexpected error copying file {entry['name']}: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to copy file: {e}")

    def delete_all(self):
        """Delete all files"""
        if not self.image:
            QMessageBox.information(self, "No Image Loaded", "No image loaded.")
            return

        entries = self.image.read_root_directory()
        items_to_delete = entries

        if not items_to_delete:
            QMessageBox.information(self, "Info", "Disk is already empty")
            return

        if self.confirm_delete:
            response = QMessageBox.question(
                self,
                "Confirm Delete All",
                f"Delete ALL {len(items_to_delete)} item(s) from the disk image?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if response == QMessageBox.StandardButton.No:
                return

        self.logger.info(f"User requested delete ALL ({len(items_to_delete)} items)")
        # Check for read-only items
        read_only_items = [e for e in items_to_delete if e['is_read_only']]
        if read_only_items:
            msg = f"{len(read_only_items)} of the items are Read-Only.\n\nDo you want to delete them anyway?"
            response = QMessageBox.warning(
                self,
                "Read-Only Items",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if response == QMessageBox.StandardButton.No:
                return

        success_count = 0
        for entry in items_to_delete:
            try:
                if entry['is_dir']:
                    self.image.delete_directory(entry, recursive=True)
                else:
                    self.image.delete_file(entry)
                success_count += 1
            except FAT12CorruptionError as e:
                self.logger.error(f"Corruption deleting {entry['name']}: {e}")
                QMessageBox.critical(self, "Filesystem Corruption", f"Cannot delete {entry['name']}:\n{e}")
            except FAT12Error as e:
                self.logger.warning(f"Failed to delete {entry['name']}: {e}")
                pass # Skip failed deletions in bulk op

        self.refresh_file_list()
        if success_count > 0:
            self.status_bar.showMessage(f"Deleted {success_count} item(s)")
            self.logger.info(f"Successfully deleted {success_count} item(s)")

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
        about_text = """<h2>FloppyManager</h2>

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
        <li>Open existing floppy images</li>
        <li>Close image</li>
        <li>Writes directly to image (no mounting)</li>
        <li>Displays long filenames and 8.3 short names</li>
        <li>Save copies of floppy images</li>
        <li>Directory support (Create/Delete/Navigate)</li>
        </ul>
        </td>

        <td valign="top" width="50%">
        <ul>
        <li>Drag and drop support (Hold Ctrl to copy)</li>
        <li>View and edit file attributes</li>
        <li>Rename files (Windows-style inline)</li>
        <li>Delete files (selected or all)</li>
        <li>Extract files (selected, all, or to ZIP)</li>
        <li>Format disk</li>
        <li>Defragment disk</li>
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
        <li>Ctrl+A - Select all</li>
        <li>Ctrl+N - Create new image</li>
        <li>Ctrl+O - Open image</li>
        <li>Ctrl+W - Close image</li>
        <li>Ctrl+Shift+S - Save image as</li>
        <li>Ctrl+Shift+F - Format disk</li>
        <li>Del/Backspace - Delete selected files</li>
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
