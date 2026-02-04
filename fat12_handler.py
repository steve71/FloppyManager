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
FAT12 Filesystem Handler
Core functionality for reading/writing FAT12 floppy disk images
"""

import struct
import datetime
from pathlib import Path
from typing import List, Optional


class FAT12Image:
    """Handler for FAT12 floppy disk images"""
    
    def __init__(self, image_path: str):
        self.image_path = image_path
        self.load_boot_sector()
        
    def load_boot_sector(self):
        """Read and parse the boot sector"""
        with open(self.image_path, 'rb') as f:
            boot_sector = f.read(512)
            
        # Parse BPB (BIOS Parameter Block)
        self.oem_name = boot_sector[3:11].decode('ascii', errors='ignore').rstrip()
        self.bytes_per_sector = struct.unpack('<H', boot_sector[11:13])[0]
        self.sectors_per_cluster = boot_sector[13]
        self.reserved_sectors = struct.unpack('<H', boot_sector[14:16])[0]
        self.num_fats = boot_sector[16]
        self.root_entries = struct.unpack('<H', boot_sector[17:19])[0]
        total_sectors_short = struct.unpack('<H', boot_sector[19:21])[0]

        self.media_descriptor = boot_sector[21]

        self.sectors_per_fat = struct.unpack('<H', boot_sector[22:24])[0]

        self.sectors_per_track = struct.unpack('<H', boot_sector[24:26])[0]
        self.number_of_heads = struct.unpack('<H', boot_sector[26:28])[0]
        self.hidden_sectors = struct.unpack('<I', boot_sector[28:32])[0]

        if total_sectors_short != 0:
            self.total_sectors = total_sectors_short
        else:
            # 2. If 0, read the 32-bit total sectors at 0x20
            self.total_sectors = struct.unpack('<I', boot_sector[32:36])[0]

        #
        # Extended BIOS Parameter Block (EBPB)
        #

        # Drive Number (Offset 36)
        self.drive_number = boot_sector[36] 

        # Reserved/Current Head (Offset 37) - Usually 0
        self.reserved_ebpb = boot_sector[37]

        # Boot Signature (Offset 38)
        # If this is 0x28 or 0x29, the following fields are valid
        self.boot_signature = boot_sector[38]

        # Volume ID / Serial Number (Offset 39)
        self.volume_id = struct.unpack('<I', boot_sector[39:43])[0]

        # Volume Label (Offset 43 to 54)
        self.volume_label = boot_sector[43:54].decode('ascii', errors='ignore').rstrip()

        # File System Type (Offset 54 to 62)
        # Should determine the FAT type by calculating the number of clusters, 
        # not by reading this string
        self.fs_type = boot_sector[54:62].decode('ascii', errors='ignore').strip()

        # Calculations
        self.fat_start = self.reserved_sectors * self.bytes_per_sector
        self.root_start = self.fat_start + (self.num_fats * self.sectors_per_fat * self.bytes_per_sector)
        self.root_size = (self.root_entries * 32)
        self.data_start = self.root_start + self.root_size
        self.bytes_per_cluster = self.bytes_per_sector * self.sectors_per_cluster
        
    def read_fat(self) -> bytearray:
        """Read the FAT table"""
        with open(self.image_path, 'rb') as f:
            f.seek(self.fat_start)
            return bytearray(f.read(self.sectors_per_fat * self.bytes_per_sector))
    
    def write_fat(self, fat_data: bytearray):
        """Write FAT table to both FAT copies"""
        with open(self.image_path, 'r+b') as f:
            for i in range(self.num_fats):
                offset = self.fat_start + (i * self.sectors_per_fat * self.bytes_per_sector)
                f.seek(offset)
                f.write(fat_data)
    
    def get_fat_entry(self, fat_data: bytearray, cluster: int) -> int:
        """Get FAT12 entry for a cluster"""
        # Offset to the fat entry for the cluster
        offset = cluster + (cluster // 2)
        value = struct.unpack('<H', fat_data[offset:offset+2])[0]
        
        # If the last bit of a binary number is 1, it is odd, else it is even
        # If the cluster is odd, the value is in the upper 4 bits
        if cluster & 1:
            return value >> 4
        else:
            return value & 0xFFF
    
    def set_fat_entry(self, fat_data: bytearray, cluster: int, value: int):
        """Set FAT12 entry for a cluster"""
        # Offset to the fat entry for the cluster
        offset = cluster + (cluster // 2)
        current = struct.unpack('<H', fat_data[offset:offset+2])[0]
        
        # If the last bit of a binary number is 1, it is odd, else it is even
        # If the cluster is odd, the value is in the upper 4 bits
        if cluster & 1:
            new_value = (current & 0x000F) | (value << 4)
        else:
            new_value = (current & 0xF000) | (value & 0xFFF)
        
        fat_data[offset:offset+2] = struct.pack('<H', new_value)
    
    def read_root_directory(self) -> List[dict]:
        """Read root directory entries"""
        entries = []
        
        with open(self.image_path, 'rb') as f:
            f.seek(self.root_start)
            
            for i in range(self.root_entries):
                entry_data = f.read(32)
                
                # Check if entry is free or end of directory
                if entry_data[0] == 0x00 or entry_data[0] == 0xE5:
                    continue
                
                # Skip volume labels and long file name entries
                attr = entry_data[11]
                if attr & 0x08:  # Volume label
                    continue
                if attr == 0x0F:  # LFN entry
                    continue
                
                # Parse entry
                name = entry_data[0:8].decode('ascii', errors='ignore').strip()
                ext = entry_data[8:11].decode('ascii', errors='ignore').strip()
                
                if name and name[0] not in ('.', '\x00'):
                    full_name = f"{name}.{ext}" if ext else name
                    
                    size = struct.unpack('<I', entry_data[28:32])[0]
                    cluster = struct.unpack('<H', entry_data[26:28])[0]
                    
                    # Parse date/time
                    date_val = struct.unpack('<H', entry_data[24:26])[0]
                    time_val = struct.unpack('<H', entry_data[22:24])[0]
                    
                    entries.append({
                        'name': full_name,
                        'size': size,
                        'cluster': cluster,
                        'index': i,
                        'is_dir': bool(attr & 0x10),
                        'date': date_val,
                        'time': time_val
                    })
        
        return entries
    
    def find_free_clusters(self, count: int = None) -> List[int]:
        """Find free clusters in the FAT. If count is None, find all."""
        fat_data = self.read_fat()
        free_clusters = []
        
        # Total data clusters available on the disk
        total_clusters = (self.total_sectors - (self.data_start // self.bytes_per_sector)) // self.sectors_per_cluster
        
        for cluster in range(2, total_clusters + 2):
            if self.get_fat_entry(fat_data, cluster) == 0:
                free_clusters.append(cluster)
                # Only break if a specific count was requested
                if count is not None and len(free_clusters) >= count:
                    break
        
        return free_clusters
    
    def write_file_to_image(self, filename: str, data: bytes) -> bool:
        """Write a file to the disk image"""
        # Calculate clusters needed
        clusters_needed = (len(data) + self.bytes_per_cluster - 1) // self.bytes_per_cluster
        
        # Find free clusters
        free_clusters = self.find_free_clusters(clusters_needed)
        if len(free_clusters) < clusters_needed:
            return False
        
        # Find free directory entry
        with open(self.image_path, 'r+b') as f:
            f.seek(self.root_start)
            entry_index = -1
            
            for i in range(self.root_entries):
                entry_data = f.read(32)
                if entry_data[0] in (0x00, 0xE5):
                    entry_index = i
                    break
            
            if entry_index == -1:
                return False
            
            # Prepare filename (8.3 format)
            base_name = Path(filename).stem.upper()[:8].ljust(8)
            extension = Path(filename).suffix.lstrip('.').upper()[:3].ljust(3)
            
            # Create directory entry
            entry = bytearray(32)
            entry[0:8] = base_name.encode('ascii')
            entry[8:11] = extension.encode('ascii')
            entry[11] = 0x20  # Archive attribute
            
            # Set date/time (current)
            now = datetime.datetime.now()
            date_val = ((now.year - 1980) << 9) | (now.month << 5) | now.day
            time_val = (now.hour << 11) | (now.minute << 5) | (now.second // 2)
            
            entry[22:24] = struct.pack('<H', time_val)
            entry[24:26] = struct.pack('<H', date_val)
            entry[26:28] = struct.pack('<H', free_clusters[0])  # First cluster
            entry[28:32] = struct.pack('<I', len(data))  # File size
            
            # Write directory entry
            f.seek(self.root_start + (entry_index * 32))
            f.write(entry)
            
            # Write file data to clusters
            offset = 0
            fat_data = self.read_fat()
            
            for i, cluster in enumerate(free_clusters):
                # Write data
                cluster_offset = self.data_start + ((cluster - 2) * self.bytes_per_cluster)
                f.seek(cluster_offset)
                chunk = data[offset:offset + self.bytes_per_cluster]
                f.write(chunk)
                offset += len(chunk)
                
                # Update FAT
                if i < len(free_clusters) - 1:
                    self.set_fat_entry(fat_data, cluster, free_clusters[i + 1])
                else:
                    self.set_fat_entry(fat_data, cluster, 0xFFF)  # End of file
            
            # Write FAT
            self.write_fat(fat_data)
        
        return True
    
    def delete_file(self, entry: dict) -> bool:
        """Delete a file from the image"""
        try:
            # Mark directory entry as deleted
            with open(self.image_path, 'r+b') as f:
                f.seek(self.root_start + (entry['index'] * 32))
                f.write(b'\xE5')
            
            # Free clusters in FAT
            if entry['cluster'] >= 2:
                fat_data = self.read_fat()
                current_cluster = entry['cluster']
                
                while current_cluster < 0xFF8:
                    next_cluster = self.get_fat_entry(fat_data, current_cluster)
                    self.set_fat_entry(fat_data, current_cluster, 0)
                    current_cluster = next_cluster
                
                self.write_fat(fat_data)
            
            return True
        except Exception as e:
            print(f"Error deleting file: {e}")
            return False
    
    def extract_file(self, entry: dict) -> bytes:
        """Extract file data from the image"""
        data = bytearray()
        
        with open(self.image_path, 'rb') as f:
            if entry['cluster'] < 2:
                return bytes()
            
            fat_data = self.read_fat()
            current_cluster = entry['cluster']
            remaining = entry['size']
            
            while current_cluster < 0xFF8 and remaining > 0:
                cluster_offset = self.data_start + ((current_cluster - 2) * self.bytes_per_cluster)
                f.seek(cluster_offset)
                
                to_read = min(self.bytes_per_cluster, remaining)
                data.extend(f.read(to_read))
                remaining -= to_read
                
                current_cluster = self.get_fat_entry(fat_data, current_cluster)
        
        return bytes(data[:entry['size']])
    
    @staticmethod
    def create_blank_image(filepath: str):
        """Create a blank FAT12 floppy disk image (1.44 MB)
        
        Args:
            filepath: Path where the image file will be created
        """
        # Standard 1.44 MB floppy parameters
        bytes_per_sector = 512
        sectors_per_cluster = 1
        reserved_sectors = 1
        num_fats = 2
        root_entries = 224
        total_sectors = 2880
        media_descriptor = 0xF0
        sectors_per_fat = 9
        sectors_per_track = 18
        heads = 2
        
        # Create image file
        total_size = total_sectors * bytes_per_sector
        
        with open(filepath, 'wb') as f:
            # Write zeros for entire image
            f.write(b'\x00' * total_size)
            
            # Go back to start to write boot sector
            f.seek(0)
            
            # Create boot sector
            boot_sector = bytearray(512)
            
            # Jump instruction
            boot_sector[0:3] = b'\xEB\x3C\x90'
            
            # OEM name
            boot_sector[3:11] = b'MSDOS5.0'
            
            # BPB (BIOS Parameter Block)
            boot_sector[11:13] = bytes_per_sector.to_bytes(2, 'little')  # Bytes per sector
            boot_sector[13] = sectors_per_cluster  # Sectors per cluster
            boot_sector[14:16] = reserved_sectors.to_bytes(2, 'little')  # Reserved sectors
            boot_sector[16] = num_fats  # Number of FATs
            boot_sector[17:19] = root_entries.to_bytes(2, 'little')  # Root entries
            boot_sector[19:21] = total_sectors.to_bytes(2, 'little')  # Total sectors
            boot_sector[21] = media_descriptor  # Media descriptor
            boot_sector[22:24] = sectors_per_fat.to_bytes(2, 'little')  # Sectors per FAT
            boot_sector[24:26] = sectors_per_track.to_bytes(2, 'little')  # Sectors per track
            boot_sector[26:28] = heads.to_bytes(2, 'little')  # Number of heads
            
            # Boot signature
            boot_sector[510:512] = b'\x55\xAA'
            
            f.write(boot_sector)
            
            # Initialize FAT tables
            fat_start = reserved_sectors * bytes_per_sector
            fat_size = sectors_per_fat * bytes_per_sector
            
            # Create initial FAT (mark first two entries)
            fat_data = bytearray(fat_size)
            # First entry: media descriptor
            fat_data[0] = media_descriptor
            fat_data[1] = 0xFF
            fat_data[2] = 0xFF
            
            # Write both FAT copies
            for i in range(num_fats):
                f.seek(fat_start + (i * fat_size))
                f.write(fat_data)


if __name__ == "__main__":
    # Test with the FAT12 floppy image
    import sys
    
    image_path = "./fat12floppy.img"
    
    print("Testing FAT12 Image Handler")
    print("=" * 50)
    
    img = FAT12Image(image_path)
    
    print("\nBoot Sector Information:")
    print(f"  OEM name: {img.oem_name}")
    print(f"  Bytes per sector: {img.bytes_per_sector}")
    print(f"  Sectors per cluster: {img.sectors_per_cluster}")
    print(f"  Reserved sectors: {img.reserved_sectors}")
    print(f"  Number of FATs: {img.num_fats}")
    print(f"  Root entries: {img.root_entries}")
    print(f"  Total sectors: {img.total_sectors}")
    print(f"  Media descriptor: 0x{img.media_descriptor:02X}")
    print(f"  Sectors per FAT: {img.sectors_per_fat}")
    print(f"  Sectors per track: {img.sectors_per_track}")
    print(f"  Number of heads: {img.number_of_heads}")
    print(f"  Number of hidden sectors: {img.hidden_sectors}")

    print("\nExtended BIOS Parameter Block (EBPB):")
    print(f"  Drive number: {img.drive_number} (0x{img.drive_number:02X})")
    print(f"  Reserved/current head: {img.reserved_ebpb}")
    boot_sig_status = "Valid" if img.boot_signature == 0x29 else "Invalid/Old"
    print(f"  Boot signature: 0x{img.boot_signature:02X} ({boot_sig_status})")
    print(f"  Volume ID: 0x{img.volume_id:08X}")
    print(f"  Volume label: {img.volume_label}")
    print(f"  File system type: {img.fs_type}")
    
    print("\nDirectory Contents:")
    entries = img.read_root_directory()
    if entries:
        for e in entries:
            print(f"  {e['name']:12} {e['size']:8,} bytes  Cluster: {e['cluster']}")
    else:
        print("  (empty)")
    
    free = len(img.find_free_clusters())
    free_bytes = free * img.bytes_per_cluster
    total_bytes = img.total_sectors * img.bytes_per_sector
    
    print(f"\nDisk Space:")
    print(f"  Total capacity: {total_bytes:,} bytes ({total_bytes / 1024 / 1024:.2f} MB)")
    print(f"  Free space: {free_bytes:,} bytes ({free_bytes / 1024:.2f} KB)")
    print(f"  Free clusters: {free}")
