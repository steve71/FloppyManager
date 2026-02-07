from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, 
    QTabWidget, QHeaderView, QPushButton, QLabel, QGridLayout,
    QWidget, QScrollArea, QSizePolicy, QSpinBox, QFrame, QApplication
)
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor, QPalette
import struct

# Import the FAT12 handler
from fat12_handler import FAT12Image

class BootSectorViewer(QDialog):
    """Dialog to view boot sector information"""
    
    def __init__(self, image: FAT12Image, parent=None):
        super().__init__(parent)
        self.image = image
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the viewer UI"""
        self.setWindowTitle("Boot Sector Information")
        self.setGeometry(100, 100, 800, 600)
        
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
                
        # Calculated Info Table
        vol_geom_table = QTableWidget()
        vol_geom_table.setColumnCount(2)
        vol_geom_table.setHorizontalHeaderLabels(['Field', 'Value'])
        vol_geom_table.horizontalHeader().setStretchLastSection(True)
        vol_geom_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        vol_geom_table.setAlternatingRowColors(True)
        
        total_bytes = self.image.total_sectors * self.image.bytes_per_sector
        
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
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class RootDirectoryViewer(QDialog):
    """Dialog to view complete root directory information with detailed VFAT tooltips"""
    
    def __init__(self, image: FAT12Image, parent=None):
        super().__init__(parent)
        self.image = image
        self.raw_entries = []  # Store raw directory entry data
        self.setup_ui()
    
    def format_raw_entry_tooltip(self, index: int) -> str:
        """Format a detailed tooltip showing the raw directory entry structure
        
        This shows the complete 32-byte layout of the directory entry including
        all LFN entries that precede the short entry.
        """
        # Find all entries related to this file (LFN + short entry)
        related_entries = []
        
        # Sanity check - make sure index is within bounds
        if index >= len(self.raw_entries):
            return "<html><body>Invalid entry index</body></html>"
        
        # Get the short entry first
        short_entry_data = self.raw_entries[index][1]
        related_entries.append((index, short_entry_data))
        
        # Walk backwards to find LFN entries
        i = index - 1
        while i >= 0:
            entry_data = self.raw_entries[i][1]
            attr = entry_data[11]
            
            # Check if LFN entry
            if attr == 0x0F:
                related_entries.insert(0, (i, entry_data))
                i -= 1
            else:
                # Not an LFN entry, stop searching
                break
        
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
                seq = entry_data[0]
                is_last = (seq & 0x40) != 0
                seq_num = seq & 0x1F
                checksum = entry_data[13]
                lfn_type = entry_data[12]
                first_cluster = struct.unpack('<H', entry_data[26:28])[0]
                
                # Extract character portions
                chars1 = entry_data[1:11]   # 5 chars (10 bytes)
                chars2 = entry_data[14:26]  # 6 chars (12 bytes)
                chars3 = entry_data[28:32]  # 2 chars (4 bytes)
                
                # Try to decode
                try:
                    text1 = chars1.decode('utf-16le').replace('\x00', '∅').replace('\uffff', '█')
                    text2 = chars2.decode('utf-16le').replace('\x00', '∅').replace('\uffff', '█')
                    text3 = chars3.decode('utf-16le').replace('\x00', '∅').replace('\uffff', '█')
                except:
                    text1 = '???'
                    text2 = '???'
                    text3 = '???'
                
                # Format hex for all characters (show more bytes)
                hex1 = ' '.join(f'{b:02X}' for b in chars1)
                hex2 = ' '.join(f'{b:02X}' for b in chars2)
                hex3 = ' '.join(f'{b:02X}' for b in chars3)
                
                html += f"<b style='background-color: #2c5aa0; color: white; padding: 3px 6px; display: block;'>"
                html += f"Entry #{entry_idx}: LFN (Seq {seq_num}{' LAST' if is_last else ''})</b>"
                html += "<table class='lfn'>"
                
                # Row 1: Field names
                html += "<tr><th>Sequence</th><th>Chars 1-5</th><th>Attr</th>"
                html += "<th>Type</th><th>Chksum</th><th>Chars 6-11</th><th>Cluster</th><th>Chars 12-13</th></tr>"
                
                # Row 2: Values
                html += f"<tr>"
                html += f"<td>0x{seq:02X}<br>({seq_num})</td>"
                html += f"<td>{hex1}<br>'{text1}'</td>"
                html += f"<td>0x{attr:02X}</td>"
                html += f"<td>0x{lfn_type:02X}</td>"
                html += f"<td>0x{checksum:02X}</td>"
                html += f"<td>{hex2}<br>'{text2}'</td>"
                html += f"<td>0x{first_cluster:04X}</td>"
                html += f"<td>{hex3}<br>'{text3}'</td></tr>"
                
                html += "</table>"
                
            else:  # Short Entry
                filename = entry_data[0:11].decode('ascii', errors='replace')
                attributes = entry_data[11]
                reserved = entry_data[12]
                creation_time_tenth = entry_data[13]
                creation_time = struct.unpack('<H', entry_data[14:16])[0]
                creation_date = struct.unpack('<H', entry_data[16:18])[0]
                last_access_date = struct.unpack('<H', entry_data[18:20])[0]
                first_cluster_high = struct.unpack('<H', entry_data[20:22])[0]
                last_modified_time = struct.unpack('<H', entry_data[22:24])[0]
                last_modified_date = struct.unpack('<H', entry_data[24:26])[0]
                first_cluster_low = struct.unpack('<H', entry_data[26:28])[0]
                file_size = struct.unpack('<I', entry_data[28:32])[0]
                
                # Decode attribute flags
                attr_flags = []
                if attributes & 0x01: attr_flags.append("RO")
                if attributes & 0x02: attr_flags.append("HID")
                if attributes & 0x04: attr_flags.append("SYS")
                if attributes & 0x08: attr_flags.append("VOL")
                if attributes & 0x10: attr_flags.append("DIR")
                if attributes & 0x20: attr_flags.append("ARC")
                attr_str = ",".join(attr_flags) if attr_flags else "-"
                
                html += f"<b style='background-color: #a07c2c; color: white; padding: 3px 6px; display: block;'>"
                html += f"Entry #{entry_idx}: Short Entry (8.3)</b>"
                html += "<table class='short'>"
                
                # Row 1: Field names
                html += "<tr><th>Filename</th><th>Attr</th><th>Res</th><th>Cr10ms</th>"
                html += "<th>CrTime</th><th>CrDate</th><th>AccDate</th><th>ClusHi</th>"
                html += "<th>ModTime</th><th>ModDate</th><th>ClusLo</th><th>Size</th></tr>"
                
                # Row 2: Values
                html += f"<tr>"
                html += f"<td>'{filename}'</td>"
                html += f"<td>0x{attributes:02X}<br>{attr_str}</td>"
                html += f"<td>0x{reserved:02X}</td>"
                html += f"<td>{creation_time_tenth}</td>"
                html += f"<td>{(creation_time>>11)&0x1F:02d}:{(creation_time>>5)&0x3F:02d}:{(creation_time&0x1F)*2:02d}</td>"
                html += f"<td>{((creation_date>>9)&0x7F)+1980}-{(creation_date>>5)&0x0F:02d}-{creation_date&0x1F:02d}</td>"
                html += f"<td>{((last_access_date>>9)&0x7F)+1980}-{(last_access_date>>5)&0x0F:02d}-{last_access_date&0x1F:02d}</td>"
                html += f"<td>0x{first_cluster_high:04X}</td>"
                html += f"<td>{(last_modified_time>>11)&0x1F:02d}:{(last_modified_time>>5)&0x3F:02d}:{(last_modified_time&0x1F)*2:02d}</td>"
                html += f"<td>{((last_modified_date>>9)&0x7F)+1980}-{(last_modified_date>>5)&0x0F:02d}-{last_modified_date&0x1F:02d}</td>"
                html += f"<td>{first_cluster_low}</td>"
                html += f"<td>{file_size:,}</td></tr>"
                
                html += "</table>"
        
        html += "</body></html>"
        return html
        
    def setup_ui(self):
        """Setup the viewer UI"""
        self.setWindowTitle("Root Directory Information")
        self.setGeometry(100, 100, 1200, 600)
        
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
            'Filename (Long)', 
            'Filename (8.3)',
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
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


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
        self.setup_ui()
        
    def build_cluster_to_file_mapping(self):
        """Build a mapping from cluster numbers to filenames"""
        self.cluster_to_file.clear()
        
        # Read directory entries
        entries = self.image.read_root_directory()
        
        for entry in entries:
            if entry['cluster'] >= 2:
                # Follow the cluster chain for this file
                current = entry['cluster']
                visited = set()
                while current < 0xFF8 and current not in visited:
                    self.cluster_to_file[current] = entry['name']
                    visited.add(current)
                    next_cluster = self.image.get_fat_entry(self.fat_data, current)
                    if next_cluster >= 2 and next_cluster < 0xFF8:
                        current = next_cluster
                    else:
                        break
        
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
        fat_size_bytes = len(self.fat_data)
        self.total_clusters = min((fat_size_bytes * 8) // 12, 4084)
        
        # Build cluster to filename mapping
        self.build_cluster_to_file_mapping()
        
        # Info label
        info_text = (
            f"<b>FAT Type:</b> {self.image.fat_type} | "
            f"<b>FAT Size:</b> {fat_size_bytes:,} bytes ({self.image.sectors_per_fat} sectors) | "
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
        self.clusters_per_row_spinbox.setValue(32)
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
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    
    def on_clusters_per_row_changed(self):
        """Handle clusters per row change with status indication"""
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
        # Build the chain starting from this cluster
        chain = set()
        
        # Follow forward from this cluster
        current = cluster_num
        visited = set()
        while current < 0xFF8 and current not in visited:
            chain.add(current)
            visited.add(current)
            next_cluster = self.image.get_fat_entry(self.fat_data, current)
            if next_cluster >= 2 and next_cluster < 0xFF8:
                current = next_cluster
            else:
                break
        
        # Find all clusters that point to this one (backwards)
        for c in range(2, self.total_clusters):
            if c not in chain:
                next_c = self.image.get_fat_entry(self.fat_data, c)
                if next_c in chain:
                    # This cluster points into our chain, follow it backwards
                    temp = c
                    temp_visited = set()
                    while temp >= 2 and temp < 0xFF8 and temp not in temp_visited:
                        chain.add(temp)
                        temp_visited.add(temp)
                        # Find what points to temp
                        found = False
                        for check in range(2, self.total_clusters):
                            if self.image.get_fat_entry(self.fat_data, check) == temp:
                                temp = check
                                found = True
                                break
                        if not found:
                            break
        
        # Toggle: if this chain is already selected, deselect it
        if chain == self.selected_chain:
            self.selected_chain.clear()
        else:
            self.selected_chain = chain
        
        self.update_cluster_colors()
    
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
                ("Reserved (0x001)", QColor(60, 60, 120)),
                ("Used (0x002-0xFF7)", QColor(60, 120, 60)),
                ("Bad Cluster (0xFF7)", QColor(120, 60, 60)),
                ("End of Chain (0xFF8-0xFFF)", QColor(180, 140, 0)),
                ("Selected Chain", QColor(70, 130, 180))
            ]
        else:
            legend_items = [
                ("Free (0x000)", QColor(240, 240, 240)),
                ("Reserved (0x001)", QColor(200, 200, 255)),
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
            elif value == 0x000:
                if is_dark:
                    color = QColor(45, 45, 45)  # Dark gray for dark mode
                    text_color = "#888"
                else:
                    color = QColor(240, 240, 240)  # Light gray for light mode
                    text_color = "#666"
            elif value == 0x001:
                if is_dark:
                    color = QColor(60, 60, 120)  # Darker blue for dark mode
                    text_color = "white"
                else:
                    color = QColor(200, 200, 255)  # Light blue for light mode
                    text_color = "black"
            elif value == 0xFF7:
                if is_dark:
                    color = QColor(120, 60, 60)  # Darker red for dark mode
                    text_color = "white"
                else:
                    color = QColor(255, 200, 200)  # Light red for light mode
                    text_color = "black"
            elif value >= 0xFF8:
                if is_dark:
                    color = QColor(180, 140, 0)  # Darker gold for dark mode
                    text_color = "white"
                else:
                    color = QColor(255, 215, 0)  # Gold for light mode
                    text_color = "black"
            else:
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
                
                # Create cell widget
                cell = QLabel()
                cell.setFixedSize(30, 30)  # Smaller size
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFrameStyle(QFrame.Shape.Box)
                
                # Make clickable
                cell.mousePressEvent = lambda event, c=cluster_num: self.cluster_clicked(c)
                cell.setCursor(Qt.CursorShape.PointingHandCursor)
                
                # Determine text based on value
                if value == 0x000:
                    text = ""  # Empty for free clusters
                    tooltip = f"Cluster {cluster_num}: Free (0x000)"
                elif value == 0x001:
                    text = "RES"
                    tooltip = f"Cluster {cluster_num}: Reserved (0x001)"
                elif value == 0xFF7:
                    text = "BAD"
                    tooltip = f"Cluster {cluster_num}: Bad Cluster (0xFF7)"
                elif value >= 0xFF8:
                    text = "EOF"
                    tooltip = f"Cluster {cluster_num}: End of Chain (0x{value:03X})"
                else:
                    # Used cluster - points to next cluster
                    text = f"{value}"
                    tooltip = f"Cluster {cluster_num}: Points to cluster {value} (0x{value:03X})"
                
                # Add filename to tooltip if this cluster belongs to a file
                if cluster_num in self.cluster_to_file:
                    tooltip += f"\nFile: {self.cluster_to_file[cluster_num]}"
                
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

