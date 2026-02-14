# Copyright (c) 2026 Stephen P Smith
# MIT License

import os
import shutil
import tempfile
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, 
    QTabWidget, QHeaderView, QPushButton, QLabel, QGridLayout,
    QWidget, QScrollArea, QSizePolicy, QSpinBox, QFrame, QApplication,
    QTreeWidget, QTreeWidgetItem, QStyledItemDelegate, QLineEdit, QComboBox,
    QRadioButton, QDialogButtonBox, QMessageBox, QTextEdit, QCheckBox
)
from PySide6.QtCore import Qt, QSize, QTimer, QMimeData, QUrl, QSettings
from PySide6.QtGui import QColor, QPalette, QDrag, QTextCursor

# Import the FAT12 handler
from fat12_handler import FAT12Image
from fat12_directory import FAT12CorruptionError, FAT12Error
from vfat_utils import parse_raw_lfn_entry, parse_raw_short_entry, get_raw_entry_chain, split_filename_for_editing

logger = logging.getLogger(__name__)

class BootSectorViewer(QDialog):
    """Dialog to view boot sector information"""
    
    def __init__(self, image: FAT12Image, parent=None):
        super().__init__(parent)
        self.image = image
        logger.debug("Opening Boot Sector Viewer")
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the viewer UI"""
        self.setWindowTitle("Boot Sector Information")
        
        layout = QVBoxLayout(self)
        
        # Create tab widget for different sections
        tabs = QTabWidget()
        
        # Boot Sector / BPB Table
        bpb_table = QTableWidget()
        bpb_table.setColumnCount(2)
        bpb_table.setHorizontalHeaderLabels(['Field', 'Value'])
        bpb_table.horizontalHeader().setStretchLastSection(True)
        bpb_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        bpb_table.setAlternatingRowColors(True)
        
        # BPB data
        bpb_data = [
            ('OEM Name', self.image.oem_name),
            ('Bytes per Sector', str(self.image.bytes_per_sector)),
            ('Sectors per Cluster', str(self.image.sectors_per_cluster)),
            ('Reserved Sectors', str(self.image.reserved_sectors)),
            ('Number of FATs', str(self.image.num_fats)),
            ('Root Directory Entries', str(self.image.root_entries)),
            ('Total Sectors', str(self.image.total_sectors)),
            ('Media Descriptor', f'0x{self.image.media_descriptor:02X}'),
            ('Sectors per FAT', str(self.image.sectors_per_fat)),
            ('Sectors per Track', str(self.image.sectors_per_track)),
            ('Number of Heads', str(self.image.number_of_heads)),
            ('Hidden Sectors', str(self.image.hidden_sectors)),
        ]
        
        bpb_table.setRowCount(len(bpb_data))
        for i, (field, value) in enumerate(bpb_data):
            bpb_table.setItem(i, 0, QTableWidgetItem(field))
            bpb_table.setItem(i, 1, QTableWidgetItem(value))
        
        bpb_table.resizeColumnsToContents()
        tabs.addTab(bpb_table, "BIOS Parameter Block")
        
        # Extended BPB Table
        # Only show if signature is 0x29 (Extended BPB present)
        if hasattr(self.image, 'boot_signature') and self.image.boot_signature == 0x29:
            ebpb_table = QTableWidget()
            ebpb_table.setColumnCount(2)
            ebpb_table.setHorizontalHeaderLabels(['Field', 'Value'])
            ebpb_table.horizontalHeader().setStretchLastSection(True)
            ebpb_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            ebpb_table.setAlternatingRowColors(True)
            
            ebpb_data = [
                ('Drive Number', f'0x{self.image.drive_number:02X}'),
                ('Reserved', f'0x{self.image.reserved_ebpb:02X}'),
                ('Boot Signature', f'0x{self.image.boot_signature:02X} (Valid)'),
                ('Volume ID', f'0x{self.image.volume_id:08X}'),
                ('Volume Label', self.image.volume_label),
                ('File System Type', self.image.fs_type_label),
            ]
            
            ebpb_table.setRowCount(len(ebpb_data))
            for i, (field, value) in enumerate(ebpb_data):
                ebpb_table.setItem(i, 0, QTableWidgetItem(field))
                ebpb_table.setItem(i, 1, QTableWidgetItem(value))
            
            ebpb_table.resizeColumnsToContents()
            tabs.addTab(ebpb_table, "Extended BPB")
                
        # Calculated Info Table
        vol_geom_table = QTableWidget()
        vol_geom_table.setColumnCount(2)
        vol_geom_table.setHorizontalHeaderLabels(['Field', 'Value'])
        vol_geom_table.horizontalHeader().setStretchLastSection(True)
        vol_geom_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        vol_geom_table.setAlternatingRowColors(True)
        
        total_bytes = self.image.get_total_capacity()
        
        vol_geom_data = [
            ('Detected File System Type', self.image.fat_type),
            ('FAT Start Offset', f'{self.image.fat_start:,} bytes'),
            ('Root Directory Start', f'{self.image.root_start:,} bytes'),
            ('Root Directory Size', f'{self.image.root_size:,} bytes'),
            ('Data Area Start', f'{self.image.data_start:,} bytes'),
            ('Bytes per Cluster', str(self.image.bytes_per_cluster)),
            ('Total Data Sectors', str(self.image.total_data_sectors)),
            ('Total Capacity', f'{total_bytes:,} bytes ({total_bytes / 1024 / 1024:.2f} MB)'),
        ]
        
        vol_geom_table.setRowCount(len(vol_geom_data))
        for i, (field, value) in enumerate(vol_geom_data):
            vol_geom_table.setItem(i, 0, QTableWidgetItem(field))
            vol_geom_table.setItem(i, 1, QTableWidgetItem(value))
        
        vol_geom_table.resizeColumnsToContents()
        tabs.addTab(vol_geom_table, "Volume Geometry")
        
        layout.addWidget(tabs)
        
        # Close button in a horizontal layout (right-aligned)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
        # Auto-resize to fit content
        self.adjustSize()
        self.setMinimumSize(380, 470)

class DirectoryViewer(QDialog):
    """Dialog to view complete root directory information with detailed VFAT tooltips"""
    
    def __init__(self, image: FAT12Image, parent=None):
        super().__init__(parent)
        self.image = image
        self.raw_entries = []  # Store raw directory entry data
        logger.debug("Opening Directory Viewer")
        self.setup_ui()
    
    def format_raw_entry_tooltip(self, index: int) -> str:
        """Format a detailed tooltip showing the raw directory entry structure
        
        This shows the complete 32-byte layout of the directory entry including
        all LFN entries that precede the short entry.
        """
        # Sanity check - make sure index is within bounds
        if index >= len(self.raw_entries):
            return "<html><body>Invalid entry index</body></html>"
        
        related_entries = get_raw_entry_chain(self.raw_entries, index)
        
        # Build HTML tooltip with transposed (horizontal) tables
        html = "<html><head><style>"
        html += "table { border-collapse: collapse; font-family: monospace; font-size: 11px; margin-bottom: 8px; }"
        html += "th, td { border: 1px solid #666; padding: 3px 6px; text-align: left; }"
        html += "th { background-color: #444; color: white; font-weight: bold; }"
        html += ".lfn { background-color: #e8f4f8; }"
        html += ".short { background-color: #f8f4e8; }"
        html += "</style></head><body>"
        
        for entry_idx, entry_data in related_entries:
            attr = entry_data[11]
            
            if attr == 0x0F:  # LFN Entry
                info = parse_raw_lfn_entry(entry_data)
                
                html += f"<b style='background-color: #2c5aa0; color: white; padding: 3px 6px; display: block;'>"
                html += f"Entry #{entry_idx}: LFN (Seq {info['seq_num']}{' LAST' if info['is_last'] else ''})</b>"
                html += "<table class='lfn'>"
                
                # Row 1: Field names
                html += "<tr><th>Sequence</th><th>Chars 1-5</th><th>Attr</th>"
                html += "<th>Type</th><th>Chksum</th><th>Chars 6-11</th><th>Cluster</th><th>Chars 12-13</th></tr>"
                
                # Row 2: Values
                html += f"<tr>"
                html += f"<td>0x{info['seq']:02X}<br>({info['seq_num']})</td>"
                html += f"<td>{info['chars1_hex']}<br>'{info['text1']}'</td>"
                html += f"<td>0x{info['attr']:02X}</td>"
                html += f"<td>0x{info['lfn_type']:02X}</td>"
                html += f"<td>0x{info['checksum']:02X}</td>"
                html += f"<td>{info['chars2_hex']}<br>'{info['text2']}'</td>"
                html += f"<td>0x{info['first_cluster']:04X}</td>"
                html += f"<td>{info['chars3_hex']}<br>'{info['text3']}'</td></tr>"
                
                html += "</table>"
                
            else:  # Short Entry
                info = parse_raw_short_entry(entry_data)
                
                html += f"<b style='background-color: #a07c2c; color: white; padding: 3px 6px; display: block;'>"
                html += f"Entry #{entry_idx}: Short Entry (8.3)</b>"
                html += "<table class='short'>"
                
                # Row 1: Field names
                html += "<tr><th>Name</th><th>Attr</th><th>Res</th><th>Cr10ms</th>"
                html += "<th>CrTime</th><th>CrDate</th><th>AccDate</th><th>ClusHi</th>"
                html += "<th>ModTime</th><th>ModDate</th><th>ClusLo</th><th>Size</th></tr>"
                
                # Row 2: Values
                html += f"<tr>"
                html += f"<td>'{info['name']}'</td>"
                html += f"<td>0x{info['attr']:02X}<br>{info['attr_str']}</td>"
                html += f"<td>0x{info['reserved']:02X}</td>"
                html += f"<td>{info['creation_time_tenth']}</td>"
                html += f"<td>{info['creation_time_str']}</td>"
                html += f"<td>{info['creation_date_str']}</td>"
                html += f"<td>{info['last_access_date_str']}</td>"
                html += f"<td>0x{info['first_cluster_high']:04X}</td>"
                html += f"<td>{info['last_modified_time_str']}</td>"
                html += f"<td>{info['last_modified_date_str']}</td>"
                html += f"<td>{info['first_cluster_low']}</td>"
                html += f"<td>{info['file_size']:,}</td></tr>"
                
                html += "</table>"
        
        html += "</body></html>"
        return html
        
    def setup_ui(self):
        """Setup the viewer UI"""
        self.setWindowTitle("Directory Information")
        
        layout = QVBoxLayout(self)
        
        # Read raw entries
        self.raw_entries = self.image.read_raw_directory_entries()
        
        # Info label
        entries = self.image.read_root_directory()
        info_label = QLabel(
            f"Total entries: {len(entries)} of {self.image.root_entries} available | Each entry is 32 bytes | "
            f"Hover over any row to see detailed directory entry structure"
        )
        info_label.setStyleSheet("QLabel { font-weight: bold; padding: 5px; }")
        layout.addWidget(info_label)
        
        # Table
        table = QTableWidget()
        table.setColumnCount(12)
        table.setHorizontalHeaderLabels([
            'Index',
            'Name (Long)', 
            'Name (8.3)',
            'Size (bytes)',
            'Created Date/Time',
            'Last Accessed',
            'Last Modified',
            'Read-Only',
            'Hidden',
            'System',
            'Directory',
            'Archive'
        ])
        
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        
        # Populate table
        table.setRowCount(len(entries))
        for i, entry in enumerate(entries):

            # Index
            item = QTableWidgetItem(str(entry['index']))
            item.setToolTip(self.format_raw_entry_tooltip(entry['index']))
            table.setItem(i, 0, item)

            # Long filename
            item = QTableWidgetItem(entry['name'])
            item.setToolTip(self.format_raw_entry_tooltip(entry['index']))
            table.setItem(i, 1, item)
            
            # Short filename (8.3)
            item = QTableWidgetItem(entry['short_name'])
            item.setToolTip(self.format_raw_entry_tooltip(entry['index']))
            table.setItem(i, 2, item)
            
            # Size
            size_item = QTableWidgetItem(f"{entry['size']:,}")
            size_item.setData(Qt.ItemDataRole.UserRole, entry['size'])  # For sorting
            size_item.setToolTip(self.format_raw_entry_tooltip(entry['index']))
            table.setItem(i, 3, size_item)
            
            # Creation date/time
            item = QTableWidgetItem(entry['creation_datetime_str'])
            item.setToolTip(self.format_raw_entry_tooltip(entry['index']))
            table.setItem(i, 4, item)
            
            # Last accessed
            item = QTableWidgetItem(entry['last_accessed_str'])
            item.setToolTip(self.format_raw_entry_tooltip(entry['index']))
            table.setItem(i, 5, item)
            
            # Last modified
            item = QTableWidgetItem(entry['last_modified_datetime_str'])
            item.setToolTip(self.format_raw_entry_tooltip(entry['index']))
            table.setItem(i, 6, item)
            
            # Attribute flags
            for col_offset, flag in enumerate([
                'is_read_only', 'is_hidden', 'is_system', 'is_dir', 'is_archive'
            ]):
                item = QTableWidgetItem('Yes' if entry[flag] else 'No')
                item.setToolTip(self.format_raw_entry_tooltip(entry['index']))
                table.setItem(i, 7 + col_offset, item)
            
        # Resize columns
        header = table.horizontalHeader()
        for col in range(table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        
        layout.addWidget(table)
        
        # Close button in a horizontal layout (right-aligned)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
        # Auto-resize to fit content
        self.adjustSize()
        self.setMinimumSize(1240, 500)


class FATViewer(QDialog):
    """Dialog to view File Allocation Table as a grid"""
    
    def __init__(self, image: FAT12Image, parent=None):
        super().__init__(parent)
        self.image = image
        self.fat_data = None
        self.total_clusters = 0
        self.selected_chain = set()  # Track selected cluster chain
        self.cluster_widgets = {}  # Map cluster number to widget
        self.cluster_to_file = {}  # Map cluster number to filename
        
        # Load settings
        self.settings = QSettings('FloppyManager', 'Settings')
        logger.debug("Opening FAT Viewer")
        
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the viewer UI"""
        self.setWindowTitle("File Allocation Table Viewer")
        self.setGeometry(100, 100, 1200, 700)
        
        layout = QVBoxLayout(self)
        
        # Read FAT data
        self.fat_data = self.image.read_fat()
        
        # Calculate total number of clusters
        # FAT12 has 12 bits per entry, so we can calculate max clusters
        # based on FAT size
        self.total_clusters = self.image.get_total_cluster_count()
        
        # Build cluster to filename mapping
        self.cluster_to_file = self.image.get_cluster_map()
        
        # Info label
        info_text = (
            f"<b>FAT Type:</b> {self.image.fat_type} | "
            f"<b>FAT Size:</b> {len(self.fat_data):,} bytes ({self.image.sectors_per_fat} sectors) | "
            f"<b>Total Clusters:</b> {self.total_clusters} | "
            f"<b>Number of FATs:</b> {self.image.num_fats}"
        )
        self.info_label = QLabel(info_text)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        
        # Legend
        self.legend_frame = QFrame()
        self.legend_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        
        # Create initial legend layout
        self.create_legend_layout()
        
        layout.addWidget(self.legend_frame)
        
        # Controls
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Clusters per row:"))
        
        self.clusters_per_row_spinbox = QSpinBox()
        self.clusters_per_row_spinbox.setRange(8, 64)
        # Load saved value or default to 32
        saved_clusters_per_row = self.settings.value('clusters_per_row', 32, type=int)
        self.clusters_per_row_spinbox.setValue(saved_clusters_per_row)
        self.clusters_per_row_spinbox.setSingleStep(8)
        self.clusters_per_row_spinbox.valueChanged.connect(self.on_clusters_per_row_changed)
        controls_layout.addWidget(self.clusters_per_row_spinbox)
        
        # Clear selection button next to spinbox
        clear_btn = QPushButton("Clear Selection")
        clear_btn.clicked.connect(self.clear_selection)
        controls_layout.addWidget(clear_btn)
        
        # Status label for showing "Rebuilding grid..."
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("QLabel { color: #666; font-style: italic; }")
        controls_layout.addWidget(self.status_label)
        
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Create scroll area for the grid
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Container widget for grid
        self.grid_container = QWidget()
        self.scroll.setWidget(self.grid_container)
        
        layout.addWidget(self.scroll)
        
        # Build initial grid
        self.rebuild_grid()
        
        # Close button in a horizontal layout (right-aligned)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
    
    def on_clusters_per_row_changed(self):
        """Handle clusters per row change with status indication"""
        # Save to settings
        self.settings.setValue('clusters_per_row', self.clusters_per_row_spinbox.value())
        
        self.status_label.setText("⏳ Rebuilding grid...")
        self.status_label.repaint()  # Force immediate update
        QApplication.processEvents()  # Process UI events
        
        self.rebuild_grid()
        
        self.status_label.setText("✓ Grid updated")
        QApplication.processEvents()
        
        # Clear status after 1 second
        QTimer.singleShot(1000, lambda: self.status_label.setText(""))
    
    def clear_selection(self):
        """Clear the selected cluster chain"""
        self.selected_chain.clear()
        self.update_cluster_colors()
    
    def cluster_clicked(self, cluster_num):
        """Handle cluster click - select entire chain (or deselect if already selected)"""
        try:
            # Get the full chain from the backend
            chain_list = self.image.get_cluster_chain(cluster_num)
            chain = set(chain_list)
            
            # Toggle: if this chain is already selected, deselect it
            if chain == self.selected_chain:
                self.selected_chain.clear()
            else:
                self.selected_chain = chain
            
            self.update_cluster_colors()
        except FAT12CorruptionError as e:
            logger.error(f"Error selecting cluster chain {cluster_num}: {e}")
            QMessageBox.warning(self, "Corruption Detected", str(e))
            return
    
    def create_legend_layout(self):
        """Create or recreate the legend layout with current theme colors"""
        # Remove old layout if it exists
        old_layout = self.legend_frame.layout()
        if old_layout:
            # Delete all widgets in the old layout
            while old_layout.count():
                item = old_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()
            # Delete the old layout
            QWidget().setLayout(old_layout)
        
        # Create new layout
        self.legend_layout = QHBoxLayout(self.legend_frame)
        
        # Add Legend label
        self.legend_layout.addWidget(QLabel("<b>Legend:</b>"))
        
        # Check if we're in dark mode
        app = QApplication.instance()
        palette = app.palette()
        is_dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        
        # Create legend items with theme-appropriate colors
        if is_dark:
            legend_items = [
                ("Free (0x000)", QColor(45, 45, 45)),
                ("Reserved (System)", QColor(60, 60, 120)),
                ("Used (0x002-0xFF7)", QColor(60, 120, 60)),
                ("Bad Cluster (0xFF7)", QColor(120, 60, 60)),
                ("End of Chain (0xFF8-0xFFF)", QColor(180, 140, 0)),
                ("Selected Chain", QColor(70, 130, 180))
            ]
        else:
            legend_items = [
                ("Free (0x000)", QColor(240, 240, 240)),
                ("Reserved (System)", QColor(200, 200, 255)),
                ("Used (0x002-0xFF7)", QColor(144, 238, 144)),
                ("Bad Cluster (0xFF7)", QColor(255, 200, 200)),
                ("End of Chain (0xFF8-0xFFF)", QColor(255, 215, 0)),
                ("Selected Chain", QColor(100, 149, 237))
            ]
        
        for text, color in legend_items:
            color_box = QLabel()
            color_box.setFixedSize(20, 20)
            color_box.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #666;")
            self.legend_layout.addWidget(color_box)
            self.legend_layout.addWidget(QLabel(text))
        
        self.legend_layout.addStretch()
    
    def update_cluster_colors(self):
        """Update colors of all cluster widgets based on selection"""
        # Check if we're in dark mode
        app = QApplication.instance()
        palette = app.palette()
        is_dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        
        for cluster_num, cell in self.cluster_widgets.items():
            value = self.image.get_fat_entry(self.fat_data, cluster_num)
            status = self.image.classify_cluster(value)
            
            # Determine if this cluster is in the selected chain
            is_selected = cluster_num in self.selected_chain
            
            # Get base color - adjust for dark mode
            if is_selected:
                if is_dark:
                    color = QColor(70, 130, 180)  # Steel blue for dark mode
                    text_color = "white"
                else:
                    color = QColor(100, 149, 237)  # Cornflower blue for light mode
                    text_color = "white"
            elif status == FAT12Image.CLUSTER_FREE:
                if is_dark:
                    color = QColor(45, 45, 45)  # Dark gray for dark mode
                    text_color = "#888"
                else:
                    color = QColor(240, 240, 240)  # Light gray for light mode
                    text_color = "#666"
            elif status == FAT12Image.CLUSTER_RESERVED:
                if is_dark:
                    color = QColor(60, 60, 120)  # Darker blue for dark mode
                    text_color = "white"
                else:
                    color = QColor(200, 200, 255)  # Light blue for light mode
                    text_color = "black"
            elif status == FAT12Image.CLUSTER_BAD:
                if is_dark:
                    color = QColor(120, 60, 60)  # Darker red for dark mode
                    text_color = "white"
                else:
                    color = QColor(255, 200, 200)  # Light red for light mode
                    text_color = "black"
            elif status == FAT12Image.CLUSTER_EOF:
                if is_dark:
                    color = QColor(180, 140, 0)  # Darker gold for dark mode
                    text_color = "white"
                else:
                    color = QColor(255, 215, 0)  # Gold for light mode
                    text_color = "black"
            else:
                # CLUSTER_USED
                if is_dark:
                    color = QColor(60, 120, 60)  # Darker green for dark mode
                    text_color = "white"
                else:
                    color = QColor(144, 238, 144)  # Light green for light mode
                    text_color = "black"
            
            cell.setStyleSheet(
                f"background-color: {color.name()}; "
                f"color: {text_color}; "
                f"border: 1px solid #666; "
                f"font-size: 10px; "
                f"font-weight: bold;"
            )
    
    def rebuild_grid(self):
        """Rebuild the FAT grid with current settings"""
        clusters_per_row = self.clusters_per_row_spinbox.value()
        
        # Update legend colors for current theme
        self.create_legend_layout()
        
        # Clear old layout
        old_layout = self.grid_container.layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(old_layout)  # Delete old layout
        
        # Clear widget tracking
        self.cluster_widgets.clear()
        
        # Create new grid layout
        grid_layout = QGridLayout(self.grid_container)
        grid_layout.setSpacing(2)
        
        # Add column headers (cluster numbers)
        for col in range(clusters_per_row):
            header_label = QLabel(f"<b>{col}</b>")
            header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_label.setStyleSheet("font-size: 9px;")
            grid_layout.addWidget(header_label, 0, col + 1)
        
        # Add rows
        num_rows = (self.total_clusters + clusters_per_row - 1) // clusters_per_row
        
        for row in range(num_rows):
            # Add row header
            row_start = row * clusters_per_row
            header_label = QLabel(f"<b>{row_start}</b>")
            header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_label.setStyleSheet("font-size: 9px;")
            grid_layout.addWidget(header_label, row + 1, 0)
            
            # Add cluster cells
            for col in range(clusters_per_row):
                cluster_num = row * clusters_per_row + col
                
                if cluster_num >= self.total_clusters:
                    break
                
                # Get FAT entry value
                value = self.image.get_fat_entry(self.fat_data, cluster_num)
                
                # Special handling for reserved clusters 0 and 1
                if cluster_num == 0:
                    status = FAT12Image.CLUSTER_RESERVED
                    text = "ID"
                    tooltip = f"Cluster 0: Media Descriptor (0x{value:03X})"
                elif cluster_num == 1:
                    status = FAT12Image.CLUSTER_RESERVED
                    text = "RES"
                    tooltip = f"Cluster 1: Reserved (0x{value:03X})"
                else:
                    status = self.image.classify_cluster(value)
                
                # Create cell widget
                cell = QLabel()
                cell.setFixedSize(30, 30)  # Smaller size
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFrameStyle(QFrame.Shape.Box)
                
                # Make clickable
                cell.mousePressEvent = lambda event, c=cluster_num: self.cluster_clicked(c)
                cell.setCursor(Qt.CursorShape.PointingHandCursor)
                
                # Determine text based on value
                if cluster_num <= 1:
                    # Text and tooltip already set above for 0 and 1
                    pass
                elif status == FAT12Image.CLUSTER_FREE:
                    text = ""  # Empty for free clusters
                    tooltip = f"Cluster {cluster_num}: Free (0x000)"
                elif status == FAT12Image.CLUSTER_RESERVED:
                    text = "RES"
                    tooltip = f"Cluster {cluster_num}: Reserved (0x001)"
                elif status == FAT12Image.CLUSTER_BAD:
                    text = "BAD"
                    tooltip = f"Cluster {cluster_num}: Bad Cluster (0xFF7)"
                elif status == FAT12Image.CLUSTER_EOF:
                    text = "EOF"
                    tooltip = f"Cluster {cluster_num}: End of Chain (0x{value:03X})"
                else:
                    # Used cluster - points to next cluster
                    text = f"{value}"
                    tooltip = f"Cluster {cluster_num}: Points to cluster {value} (0x{value:03X})"
                
                # Add filename to tooltip if this cluster belongs to a file
                if cluster_num in self.cluster_to_file:
                    tooltip += f"\nName: {self.cluster_to_file[cluster_num]}"
                elif status == FAT12Image.CLUSTER_USED or status == FAT12Image.CLUSTER_EOF:
                    tooltip += "\nStatus: Orphaned / Unknown (Not linked in directory)"
                
                cell.setText(text)
                cell.setToolTip(tooltip)
                
                # Store reference
                self.cluster_widgets[cluster_num] = cell
                
                grid_layout.addWidget(cell, row + 1, col + 1)
        
        # Update colors (in case there's a selection)
        self.update_cluster_colors()
        
        # Add spacer to push everything to top-left
        grid_layout.setRowStretch(num_rows + 1, 1)
        grid_layout.setColumnStretch(clusters_per_row + 1, 1)

class FileAttributesDialog(QDialog):
    """Dialog for editing file attributes"""
    
    def __init__(self, entry: dict, image: FAT12Image = None, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.image = image
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the attributes editor UI"""
        is_dir = self.entry.get('is_dir', False)
        type_label = "Folder" if is_dir else "File"
        
        self.setWindowTitle(f"{type_label} Properties")
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # Info label
        info_label = QLabel(f"<b>{type_label}:</b> {self.entry['name']}")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Add spacing
        layout.addSpacing(5)
        
        # --- Size Info ---
        info_grid = QGridLayout()
        info_grid.setColumnStretch(1, 1)
        
        row = 0
        
        # Size
        size_bytes = self.entry['size']
        info_grid.addWidget(QLabel("Size:"), row, 0)
        info_grid.addWidget(QLabel(f"{size_bytes:,} bytes"), row, 1)
        row += 1
        
        # Size on Disk
        if not is_dir and self.image:
            on_disk = self.image.calculate_size_on_disk(size_bytes)
            
            info_grid.addWidget(QLabel("Size on disk:"), row, 0)
            info_grid.addWidget(QLabel(f"{on_disk:,} bytes"), row, 1)
            row += 1
            
        layout.addLayout(info_grid)
        
        # Divider 1
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line1)
        
        # --- Timestamps ---
        time_grid = QGridLayout()
        time_grid.setColumnStretch(1, 1)
        
        t_row = 0
        time_grid.addWidget(QLabel("Created:"), t_row, 0)
        time_grid.addWidget(QLabel(self.entry.get('creation_datetime_str', 'N/A')), t_row, 1)
        t_row += 1
        
        time_grid.addWidget(QLabel("Modified:"), t_row, 0)
        time_grid.addWidget(QLabel(self.entry.get('last_modified_datetime_str', 'N/A')), t_row, 1)
        t_row += 1
        
        time_grid.addWidget(QLabel("Accessed:"), t_row, 0)
        time_grid.addWidget(QLabel(self.entry.get('last_accessed_str', 'N/A')), t_row, 1)
        t_row += 1
        
        layout.addLayout(time_grid)
        
        # Divider 2
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line2)
        
        # Create checkboxes for each attribute
        from PySide6.QtWidgets import QCheckBox, QGroupBox
        
        attr_group = QGroupBox("Attributes")
        attr_layout = QGridLayout()
        
        # Read-only checkbox
        self.readonly_cb = QCheckBox("Read-only")
        self.readonly_cb.setChecked(self.entry['is_read_only'])
        self.readonly_cb.setToolTip(f"Prevents the {type_label.lower()} from being modified or deleted")
        attr_layout.addWidget(self.readonly_cb, 0, 0)
        
        # Hidden checkbox
        self.hidden_cb = QCheckBox("Hidden")
        self.hidden_cb.setChecked(self.entry['is_hidden'])
        self.hidden_cb.setToolTip(f"Hides the {type_label.lower()} from normal directory listings")
        attr_layout.addWidget(self.hidden_cb, 0, 1)
        
        # Archive checkbox
        self.archive_cb = QCheckBox("Archive")
        self.archive_cb.setChecked(self.entry['is_archive'])
        self.archive_cb.setToolTip(f"Indicates the {type_label.lower()} has been modified since last backup")
        attr_layout.addWidget(self.archive_cb, 1, 0)
        
        # System checkbox
        self.system_cb = QCheckBox("System")
        self.system_cb.setChecked(self.entry['is_system'])
        self.system_cb.setToolTip(f"Marks the {type_label.lower()} as a system item")
        attr_layout.addWidget(self.system_cb, 1, 1)
        
        attr_group.setLayout(attr_layout)
        layout.addWidget(attr_group)
        
        # Buttons
        layout.addSpacing(10)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(80)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
        
        # Set size
        self.setMinimumWidth(320)
        self.adjustSize()
    
    def get_attributes(self):
        """Get the selected attributes as a dictionary"""
        return {
            'is_read_only': self.readonly_cb.isChecked(),
            'is_hidden': self.hidden_cb.isChecked(),
            'is_system': self.system_cb.isChecked(),
            'is_archive': self.archive_cb.isChecked(),
        }

class SortableTreeWidgetItem(QTreeWidgetItem):
    """Tree item that sorts folders before files, then by column data."""
    def __lt__(self, other):
        # Get the full entry data, which is always stored in column 0
        my_entry = self.data(0, Qt.ItemDataRole.UserRole)
        other_entry = other.data(0, Qt.ItemDataRole.UserRole)

        # Primary sort: folders vs files
        if my_entry and other_entry:
            my_is_dir = my_entry.get('is_dir', False)
            other_is_dir = other_entry.get('is_dir', False)

            if my_is_dir != other_is_dir:
                # Directories are "less than" files, so they come first in ascending sort.
                # my_is_dir is a bool (True for dir). True > False is True.
                return my_is_dir > other_is_dir

        # Secondary sort: by the selected column's data
        tree = self.treeWidget()
        if tree is None:
            return self.text(0) < other.text(0)
            
        column = tree.sortColumn()
        if column == -1:
            column = 0
            
        my_data = self.data(column, Qt.ItemDataRole.UserRole)
        other_data = other.data(column, Qt.ItemDataRole.UserRole)
        
        if my_data is not None and other_data is not None:
            # For column 0 (Filename), UserRole is the entry dict. Fall back to text sorting.
            if not isinstance(my_data, dict):
                return my_data < other_data
            
        # Fallback to default text-based sorting for the column
        # Avoid super().__lt__ to prevent potential C++ segfaults
        return self.text(column) < other.text(column)

class FileTreeWidget(QTreeWidget):
    """Custom TreeWidget that supports dragging files out and dropping files in"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
    
    def startDrag(self, supportedActions):
        # Get main window reference to access image
        main_window = self.window()
        if not hasattr(main_window, 'image') or not main_window.image:
            return

        selected_items = self.selectedItems()
        if not selected_items:
            return

        # Create a temporary directory
        temp_dir = tempfile.mkdtemp(prefix="fat12_drag_")
        
        try:
            urls = []
            files_exported = False
            
            for item in selected_items:
                entry = item.data(0, Qt.ItemDataRole.UserRole)
                
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
                        logger.warning(f"Failed to extract file '{entry.get('name')}' for drag: {e}")
                        pass # Skip files that fail to extract during drag init
            
            if not files_exported:
                return

            logger.info(f"Prepared {len(urls)} files for drag-and-drop export")

            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setUrls(urls)
            mime_data.setData("application/x-fat12-item", b"1")
            drag.setMimeData(mime_data)
            
            # Execute drag - blocks until drop is finished
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
            
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
            # Default to Copy
            action = Qt.DropAction.CopyAction
            
            # If internal drag, default to Move
            if event.mimeData().hasFormat("application/x-fat12-item"):
                action = Qt.DropAction.MoveAction
            
            # If Ctrl is held, force Copy
            if event.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                action = Qt.DropAction.CopyAction
                
            event.setDropAction(action)
            event.accept()
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
                # Check for internal drag
                is_internal = event.mimeData().hasFormat("application/x-fat12-item")
                
                # Determine if we should Copy or Move
                # Default to Copy (external files)
                is_copy = True
                
                # If internal drag and Ctrl NOT held, it's a Move
                if is_internal and not (event.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
                    is_copy = False
                
                logger.debug(f"Drop event: is_internal={is_internal}, is_copy={is_copy}, files={len(files)}")
                
                # Determine target directory
                target_item = self.itemAt(event.position().toPoint())
                parent_cluster = None
                
                if target_item:
                    entry = target_item.data(0, Qt.ItemDataRole.UserRole)
                    if entry:
                        if entry['is_dir']:
                            parent_cluster = entry['cluster']
                        else:
                            parent_cluster = entry.get('parent_cluster')
                            if parent_cluster == 0: parent_cluster = None
                
                # Check for circular reference (folder into itself or subfolder)
                if is_internal:
                    source_items = self.selectedItems()
                    for item in source_items:
                        src_entry = item.data(0, Qt.ItemDataRole.UserRole)
                        if src_entry and src_entry.get('is_dir'):
                            src_cluster = src_entry['cluster']
                            
                            # Check if target is the source folder itself
                            if parent_cluster == src_cluster:
                                logger.debug("Drop ignored: Target is source folder")
                                event.ignore()
                                return
                            
                            # Check if target is a subfolder of source
                            # Traverse up from parent_cluster
                            curr_cluster = parent_cluster
                            
                            # Safety counter to prevent infinite loops in corrupted FS
                            safety_counter = 0
                            while curr_cluster is not None and curr_cluster != 0 and safety_counter < 100:
                                if curr_cluster == src_cluster:
                                    logger.warning("Drop ignored: Circular reference detected")
                                    event.ignore()
                                    return
                                
                                # Get parent of curr_cluster
                                try:
                                    dir_entries = main_window.image.read_directory(curr_cluster)
                                    dotdot = next((e for e in dir_entries if e['name'] == '..'), None)
                                    
                                    if dotdot:
                                        curr_cluster = dotdot['cluster']
                                        if curr_cluster == 0: curr_cluster = None
                                    else:
                                        break
                                except Exception:
                                    break
                                
                                safety_counter += 1

                entries_to_delete = []
                if is_internal and not is_copy:
                    # Check if moving to same folder
                    # source_items already populated above
                    if source_items:
                        first_entry = source_items[0].data(0, Qt.ItemDataRole.UserRole)
                        source_parent = first_entry.get('parent_cluster')
                        if source_parent == 0: source_parent = None
                        
                        if source_parent == parent_cluster:
                            logger.debug("Drop ignored: Source and target folders are the same")
                            event.ignore()
                            return
                        
                        entries_to_delete = [item.data(0, Qt.ItemDataRole.UserRole) for item in source_items]
                    
                    event.setDropAction(Qt.DropAction.MoveAction)
                else:
                    event.setDropAction(Qt.DropAction.CopyAction)

                event.accept()
                
                # Don't refresh yet, we might delete files next
                success_count = main_window.add_files_from_list(files, parent_cluster, refresh=False)

                # Handle Move (Delete source) if internal and copy was successful
                if is_internal and not is_copy and success_count == len(files):
                    deleted_count = 0
                    for entry in entries_to_delete:
                        try:
                            main_window.image.delete_file(entry)
                            deleted_count += 1
                        except Exception as e:
                            logger.warning(f"Failed to delete source file '{entry.get('name')}' during move: {e}")
                            pass
                    
                    main_window.refresh_file_list()
                    main_window.status_bar.showMessage(f"Moved {deleted_count} file(s)")
                    logger.info(f"Moved {deleted_count} file(s) via drag and drop")
                elif is_internal and is_copy and success_count > 0:
                    main_window.status_bar.showMessage(f"Copied {success_count} file(s)")
                    main_window.refresh_file_list()
                else:
                    main_window.refresh_file_list()
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

class FormatDialog(QDialog):
    """Dialog for selecting format options with explanations"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Format Options")
        self.full_format = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        lbl = QLabel("Select format type:")
        layout.addWidget(lbl)
        
        self.rb_quick = QRadioButton("Quick Format")
        self.rb_quick.setToolTip("Resets the filesystem (FAT and Root Directory).\nAll files and subdirectories are removed from the listing, but their data remains on disk until overwritten.")
        self.rb_quick.setChecked(True)
        layout.addWidget(self.rb_quick)
        
        self.rb_full = QRadioButton("Full Format")
        self.rb_full.setToolTip("Resets the filesystem and overwrites all data sectors with zeros.\nAll files, subdirectories, and data are permanently erased.")
        layout.addWidget(self.rb_full)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
    def accept(self):
        self.full_format = self.rb_full.isChecked()
        super().accept()

class NewImageDialog(QDialog):
    """Dialog for creating a new image with format selection and OEM name"""
    def __init__(self, formats, display_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Image")
        self.formats = formats
        self.display_names = display_names
        self.selected_format = formats[0] if formats else '1.44MB'
        
        self.settings = QSettings('FloppyManager', 'Settings')
        self.oem_name = self.settings.value('last_oem_name', "MSDOS5.0", type=str)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Select Disk Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(self.display_names)
        layout.addWidget(self.format_combo)
        
        layout.addWidget(QLabel("OEM Name (Max 8 chars):"))
        self.oem_input = QLineEdit()
        self.oem_input.setMaxLength(8)
        self.oem_input.setText(self.oem_name)
        self.oem_input.setPlaceholderText("MSDOS5.0")
        self.oem_input.setToolTip("MSDOS5.0 is recommended for maximum compatibility.")
        self.oem_input.setFocus()
        self.oem_input.selectAll()
        layout.addWidget(self.oem_input)
        
        # Add spacing
        layout.addSpacing(10)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.validate)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def validate(self):
        name = self.oem_input.text()
        
        # Check for ASCII
        try:
            name.encode('ascii')
        except UnicodeEncodeError:
            logger.warning(f"Invalid OEM name provided: {name} (Non-ASCII)")
            QMessageBox.warning(self, "Invalid Name", "OEM Name must be ASCII characters only.")
            return
            
        # Check for safe characters (Alphanumeric + standard punctuation)
        if not all(c.isalnum() or c in " .-_" for c in name):
            logger.warning(f"Invalid OEM name provided: {name} (Invalid characters)")
            QMessageBox.warning(self, "Invalid Name", "OEM Name contains invalid characters.\nAllowed: A-Z, 0-9, space, period, dash, underscore.")
            return
            
        self.oem_name = name
        self.settings.setValue('last_oem_name', self.oem_name)
        self.selected_format = self.formats[self.format_combo.currentIndex()]
        self.accept()

class LogViewer(QDialog):
    """Dialog to view application log"""
    def __init__(self, log_path, parent=None):
        super().__init__(parent)
        self.log_path = log_path
        self.setWindowTitle("Application Log")
        self.resize(800, 600)
        
        self.settings = QSettings('FloppyManager', 'Settings')
        
        # Track file state for polling
        self._last_mtime = 0
        self._last_size = 0
        
        layout = QVBoxLayout(self)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        
        # Load word wrap setting
        word_wrap = self.settings.value('log_word_wrap', False, type=bool)
        self.set_word_wrap(word_wrap)
        
        font = self.text_edit.font()
        font.setFamily("Consolas")
        font.setStyleHint(font.StyleHint.Monospace)
        self.text_edit.setFont(font)
        
        layout.addWidget(self.text_edit)
        
        # Load log
        self.load_log(self.log_path)
        
        # Setup timer for real-time updates
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_update)
        self.timer.start(1000)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.wrap_cb = QCheckBox("Word Wrap")
        self.wrap_cb.setChecked(word_wrap)
        self.wrap_cb.toggled.connect(self.on_word_wrap_toggled)
        btn_layout.addWidget(self.wrap_cb)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        
    def check_update(self):
        """Check if log file has changed"""
        if not os.path.exists(self.log_path):
            return
            
        try:
            stat = os.stat(self.log_path)
            if stat.st_mtime != self._last_mtime or stat.st_size != self._last_size:
                self.load_log(self.log_path)
        except OSError:
            pass
            
    def set_word_wrap(self, enabled):
        if enabled:
            self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        else:
            self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

    def on_word_wrap_toggled(self, checked):
        self.set_word_wrap(checked)
        self.settings.setValue('log_word_wrap', checked)
        
    def load_log(self, path):
        if os.path.exists(path):
            try:
                # Update stats
                stat = os.stat(path)
                self._last_mtime = stat.st_mtime
                self._last_size = stat.st_size
                
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Determine colors based on theme (check background lightness)
                app = QApplication.instance()
                palette = app.palette()
                is_dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
                
                html_parts = ['<html><body style="font-family: Consolas, monospace; font-size: 10pt;">']
                
                for line in lines:
                    line = line.rstrip()
                    if not line:
                        continue
                        
                    # Default style
                    color = "#000000" if not is_dark else "#ffffff"
                    weight = "normal"
                    
                    # Determine style based on log level
                    if " - ERROR - " in line:
                        color = "#d32f2f" if not is_dark else "#ff6b6b" # Red
                    elif " - WARNING - " in line:
                        color = "#e65100" if not is_dark else "#ffb74d" # Orange
                    elif " - CRITICAL - " in line:
                        color = "#b71c1c" if not is_dark else "#ff5252" # Dark Red
                        weight = "bold"
                    elif " - DEBUG - " in line:
                        color = "#757575" if not is_dark else "#9e9e9e" # Gray
                    elif " - INFO - " in line:
                        color = "#2e7d32" if not is_dark else "#81c784" # Green
                    
                    # Simple HTML escaping
                    safe_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    html_parts.append(f'<span style="color:{color}; font-weight:{weight};">{safe_line}</span><br>')
                
                html_parts.append('</body></html>')
                self.text_edit.setHtml("".join(html_parts))
                self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
            except Exception as e:
                self.text_edit.setText(f"Error reading log file: {e}")
        else:
            self.text_edit.setText("Log file not found.")
