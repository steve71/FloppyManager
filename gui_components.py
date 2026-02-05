from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
    QTabWidget, QHeaderView, QPushButton
)
from PyQt6.QtCore import Qt

# Import the FAT12 handler
from fat12_handler import FAT12Image

class BootSectorViewer(QDialog):
    """Dialog to view boot sector and EBPB information"""
    
    def __init__(self, image: FAT12Image, parent=None):
        super().__init__(parent)
        self.image = image
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the viewer UI"""
        self.setWindowTitle("Boot Sector & EBPB Information")
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
        
        # EBPB Table
        ebpb_table = QTableWidget()
        ebpb_table.setColumnCount(2)
        ebpb_table.setHorizontalHeaderLabels(['Field', 'Value'])
        ebpb_table.horizontalHeader().setStretchLastSection(True)
        ebpb_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        ebpb_table.setAlternatingRowColors(True)
        
        boot_sig_status = "Valid (0x29)" if self.image.boot_signature == 0x29 else f"Invalid/Old (0x{self.image.boot_signature:02X})"
        
        # EBPB data
        ebpb_data = [
            ('Drive Number', f'{self.image.drive_number} (0x{self.image.drive_number:02X})'),
            ('Reserved/Current Head', str(self.image.reserved_ebpb)),
            ('Boot Signature', boot_sig_status),
            ('Volume ID (Serial Number)', f'0x{self.image.volume_id:08X}'),
            ('Volume Label', self.image.volume_label if self.image.volume_label else '(none)'),
            ('File System Type (from EBPB)', self.image.fs_type_from_EBPB if self.image.fs_type_from_EBPB else '(none)'),
        ]
        
        ebpb_table.setRowCount(len(ebpb_data))
        for i, (field, value) in enumerate(ebpb_data):
            ebpb_table.setItem(i, 0, QTableWidgetItem(field))
            ebpb_table.setItem(i, 1, QTableWidgetItem(value))
        
        ebpb_table.resizeColumnsToContents()
        tabs.addTab(ebpb_table, "Extended BIOS Parameter Block")
        
        # Calculated Info Table
        calc_table = QTableWidget()
        calc_table.setColumnCount(2)
        calc_table.setHorizontalHeaderLabels(['Field', 'Value'])
        calc_table.horizontalHeader().setStretchLastSection(True)
        calc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        calc_table.setAlternatingRowColors(True)
        
        total_bytes = self.image.total_sectors * self.image.bytes_per_sector
        
        calc_data = [
            ('Detected File System Type', self.image.fat_type),
            ('FAT Start Offset', f'{self.image.fat_start:,} bytes'),
            ('Root Directory Start', f'{self.image.root_start:,} bytes'),
            ('Root Directory Size', f'{self.image.root_size:,} bytes'),
            ('Data Area Start', f'{self.image.data_start:,} bytes'),
            ('Bytes per Cluster', str(self.image.bytes_per_cluster)),
            ('Total Data Sectors', str(self.image.total_data_sectors)),
            ('Total Capacity', f'{total_bytes:,} bytes ({total_bytes / 1024 / 1024:.2f} MB)'),
        ]
        
        calc_table.setRowCount(len(calc_data))
        for i, (field, value) in enumerate(calc_data):
            calc_table.setItem(i, 0, QTableWidgetItem(field))
            calc_table.setItem(i, 1, QTableWidgetItem(value))
        
        calc_table.resizeColumnsToContents()
        tabs.addTab(calc_table, "Calculated Information")
        
        layout.addWidget(tabs)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class RootDirectoryViewer(QDialog):
    """Dialog to view complete root directory information"""
    
    def __init__(self, image: FAT12Image, parent=None):
        super().__init__(parent)
        self.image = image
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the viewer UI"""
        self.setWindowTitle("Root Directory Information")
        self.setGeometry(100, 100, 1200, 600)
        
        layout = QVBoxLayout(self)
        
        # Info label
        entries = self.image.read_root_directory()
        info_label = QLabel(f"Total entries: {len(entries)} of {self.image.root_entries} available")
        info_label.setStyleSheet("QLabel { font-weight: bold; padding: 5px; }")
        layout.addWidget(info_label)
        
        # Table
        table = QTableWidget()
        table.setColumnCount(14)
        table.setHorizontalHeaderLabels([
            'Filename (Long)', 
            'Filename (8.3)',
            'Size (bytes)', 
            'First Cluster',
            'Attributes',
            'Created Date/Time',
            'Last Accessed',
            'Last Modified',
            'Read-Only',
            'Hidden',
            'System',
            'Directory',
            'Archive',
            'Index'
        ])
        
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        
        # Populate table
        table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            # Long filename
            table.setItem(i, 0, QTableWidgetItem(entry['name']))
            
            # Short filename (8.3)
            table.setItem(i, 1, QTableWidgetItem(entry['short_name']))
            
            # Size
            size_item = QTableWidgetItem(f"{entry['size']:,}")
            size_item.setData(Qt.ItemDataRole.UserRole, entry['size'])  # For sorting
            table.setItem(i, 2, size_item)
            
            # First Cluster
            table.setItem(i, 3, QTableWidgetItem(str(entry['cluster'])))
            
            # Attributes (hex)
            table.setItem(i, 4, QTableWidgetItem(f"0x{entry['attributes']:02X}"))
            
            # Creation date/time
            table.setItem(i, 5, QTableWidgetItem(entry['creation_datetime_str']))
            
            # Last accessed
            table.setItem(i, 6, QTableWidgetItem(entry['last_accessed_str']))
            
            # Last modified
            table.setItem(i, 7, QTableWidgetItem(entry['last_modified_datetime_str']))
            
            # Attribute flags
            table.setItem(i, 8, QTableWidgetItem('Yes' if entry['is_read_only'] else 'No'))
            table.setItem(i, 9, QTableWidgetItem('Yes' if entry['is_hidden'] else 'No'))
            table.setItem(i, 10, QTableWidgetItem('Yes' if entry['is_system'] else 'No'))
            table.setItem(i, 11, QTableWidgetItem('Yes' if entry['is_dir'] else 'No'))
            table.setItem(i, 12, QTableWidgetItem('Yes' if entry['is_archive'] else 'No'))
            
            # Index
            table.setItem(i, 13, QTableWidgetItem(str(entry['index'])))
        
        # Resize columns
        header = table.horizontalHeader()
        for col in range(table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        
        layout.addWidget(table)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)