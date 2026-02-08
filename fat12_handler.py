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
Core functionality for reading/writing FAT12 floppy disk images with VFAT long filename support
"""

import struct
import datetime
import random
from pathlib import Path
from typing import List, Optional

from vfat_utils import (decode_fat_time, decode_fat_date,
                        encode_fat_time, encode_fat_date, 
                        generate_83_name, calculate_lfn_checksum, 
                        create_lfn_entries, decode_lfn_text,
                        decode_short_name, format_83_name, decode_raw_83_name)
class FAT12Image:
    """Handler for FAT12 floppy disk images"""
    
    # Cluster status constants
    CLUSTER_FREE = 'FREE'
    CLUSTER_RESERVED = 'RESERVED'
    CLUSTER_BAD = 'BAD'
    CLUSTER_EOF = 'EOF'
    CLUSTER_USED = 'USED'

    # Supported Floppy Formats
    FORMATS = {
        '1.44M': {
            'name': '3.5" High Density (1.44 MB)',
            'total_sectors': 2880,
            'sectors_per_cluster': 1,
            'sectors_per_track': 18,
            'heads': 2,
            'root_entries': 224,
            'media_descriptor': 0xF0,
            'sectors_per_fat': 9,
            'reserved_sectors': 1,
            'hidden_sectors': 0
        },
        '720K': {
            'name': '3.5" Double Density (720 KB)',
            'total_sectors': 1440,
            'sectors_per_cluster': 2,
            'sectors_per_track': 9,
            'heads': 2,
            'root_entries': 112,
            'media_descriptor': 0xF9,
            'sectors_per_fat': 3,
            'reserved_sectors': 1,
            'hidden_sectors': 0
        },
        '2.88M': {
            'name': '3.5" Extra High Density (2.88 MB)',
            'total_sectors': 5760,
            'sectors_per_cluster': 2,
            'sectors_per_track': 36,
            'heads': 2,
            'root_entries': 224,
            'media_descriptor': 0xF0,
            'sectors_per_fat': 9,
            'reserved_sectors': 1,
            'hidden_sectors': 0
        },
        '1.2M': {
            'name': '5.25" High Density (1.2 MB)',
            'total_sectors': 2400,
            'sectors_per_cluster': 1,
            'sectors_per_track': 15,
            'heads': 2,
            'root_entries': 224,
            'media_descriptor': 0xF9,
            'sectors_per_fat': 7,
            'reserved_sectors': 1,
            'hidden_sectors': 0
        },
        '360K': {
            'name': '5.25" Double Density (360 KB)',
            'total_sectors': 720,
            'sectors_per_cluster': 2,
            'sectors_per_track': 9,
            'heads': 2,
            'root_entries': 112,
            'media_descriptor': 0xFD,
            'sectors_per_fat': 2,
            'reserved_sectors': 1,
            'hidden_sectors': 0
        }
    }

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
            self.total_sectors = struct.unpack('<I', boot_sector[32:36])[0]

        # Fixed Regions
        self.fat_start = self.reserved_sectors * self.bytes_per_sector
        fat_region_size = self.num_fats * self.sectors_per_fat * self.bytes_per_sector
        self.root_start = self.fat_start + fat_region_size
        self.root_size = (self.root_entries * 32)
        self.data_start = self.root_start + self.root_size
        self.bytes_per_cluster = self.bytes_per_sector * self.sectors_per_cluster

        # Calculate number of clusters in the data area
        non_data_sectors = self.data_start // self.bytes_per_sector
        self.total_data_sectors = self.total_sectors - non_data_sectors
        num_data_clusters = self.total_data_sectors // self.sectors_per_cluster

        # Microsoft FAT Type thresholds
        if num_data_clusters < 4085:
            self.fat_type = 'FAT12'
        elif num_data_clusters < 65525:
            self.fat_type = 'FAT16'
        else:
            self.fat_type = 'FAT32'
        
    def get_total_capacity(self) -> int:
        """Get total disk capacity in bytes"""
        return self.total_sectors * self.bytes_per_sector

    def get_fat_entry_count(self) -> int:
        """Calculate total number of entries in the FAT"""
        fat_size_bytes = self.sectors_per_fat * self.bytes_per_sector
        return (fat_size_bytes * 8) // 12

    def get_total_cluster_count(self) -> int:
        """Get the total number of addressable clusters (limited by FAT12 spec)"""
        return min(self.get_fat_entry_count(), 4084)

    def get_free_space(self) -> int:
        """Get free space in bytes"""
        return len(self.find_free_clusters()) * self.bytes_per_cluster

    def classify_cluster(self, value: int) -> str:
        """Classify a FAT12 cluster value"""
        if value == 0x000:
            return self.CLUSTER_FREE
        elif value == 0x001:
            return self.CLUSTER_RESERVED
        elif value == 0xFF7:
            return self.CLUSTER_BAD
        elif value >= 0xFF8:
            return self.CLUSTER_EOF
        else:
            return self.CLUSTER_USED

    def predict_short_name(self, long_name: str, use_numeric_tail: bool = False) -> str:
        """Predict the 8.3 short name that will be generated for a file"""
        existing_names = self.get_existing_83_names()
        return generate_83_name(long_name, existing_names, use_numeric_tail)

    def find_entry_by_83_name(self, target_83_name: str) -> Optional[dict]:
        """Find a directory entry by its 11-character 8.3 name (no dot)"""
        # target_83_name should be 11 chars, space padded, uppercase
        target = target_83_name.upper().ljust(11)[:11]
        
        entries = self.read_root_directory()
        for entry in entries:
            # Compare against the raw 11-byte name stored in the entry
            if entry.get('raw_short_name') == target:
                return entry
        return None

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
        offset = cluster + (cluster // 2)
        value = struct.unpack('<H', fat_data[offset:offset+2])[0]
        
        if cluster & 1:
            return value >> 4
        else:
            return value & 0xFFF
    
    def set_fat_entry(self, fat_data: bytearray, cluster: int, value: int):
        """Set FAT12 entry for a cluster"""
        offset = cluster + (cluster // 2)
        current = struct.unpack('<H', fat_data[offset:offset+2])[0]
        
        if cluster & 1:
            new_value = (current & 0x000F) | (value << 4)
        else:
            new_value = (current & 0xF000) | (value & 0xFFF)
        
        fat_data[offset:offset+2] = struct.pack('<H', new_value)
    
    def read_root_directory(self) -> List[dict]:
        """Read root directory entries with VFAT long filename support"""
        entries = []
        
        with open(self.image_path, 'rb') as f:
            f.seek(self.root_start)
            
            # LFN accumulator
            lfn_parts = []
            lfn_checksum = None
            
            for i in range(self.root_entries):
                entry_data = f.read(32)
                
                # Check if entry is end of directory
                if entry_data[0] == 0x00:
                    break
                    
                # Check if entry is free (deleted)
                if entry_data[0] == 0xE5:
                    lfn_parts = []
                    lfn_checksum = None
                    continue
                
                attr = entry_data[11]
                
                # Check if this is an LFN entry
                if attr == 0x0F:
                    seq = entry_data[0]
                    checksum = entry_data[13]
                    
                    text = decode_lfn_text(entry_data)
                    if text is not None:
                        if seq & 0x40:
                            # This is the last entry, start fresh
                            lfn_parts = [text]
                            lfn_checksum = checksum
                        else:
                            # This is a continuation, append to the end
                            # (we're reading backwards through the entries)
                            lfn_parts.append(text)
                    else:
                        lfn_parts = []
                        lfn_checksum = None
                    
                    continue
                
                # Skip volume labels
                if attr & 0x08:
                    lfn_parts = []
                    lfn_checksum = None
                    continue
                
                # This is a regular 8.3 entry
                name, ext = decode_short_name(entry_data)
                
                if name and name[0] not in ('.', '\x00'):
                    short_name_83 = f"{name}.{ext}" if ext else name
                    
                    # Store raw 11-byte name for robust collision detection
                    raw_short_name = decode_raw_83_name(entry_data)
                    
                    # Check if we have a valid LFN for this entry
                    long_name = None
                    if lfn_parts and lfn_checksum is not None:
                        # Verify checksum
                        short_name_bytes = entry_data[0:11]
                        calculated_checksum = calculate_lfn_checksum(short_name_bytes)
                        
                        if calculated_checksum == lfn_checksum:
                            # LFN entries are stored in reverse order, so reverse the list
                            long_name = ''.join(reversed(lfn_parts))
                    
                    # Use long name if available, otherwise use short name
                    display_name = long_name if long_name else short_name_83
                    
                    creation_time_tenth = entry_data[13]
                    creation_time = struct.unpack('<H', entry_data[14:16])[0]
                    creation_date = struct.unpack('<H', entry_data[16:18])[0]
                    last_accessed_date = struct.unpack('<H', entry_data[18:20])[0]
                    last_modified_time = struct.unpack('<H', entry_data[22:24])[0]
                    last_modified_date = struct.unpack('<H', entry_data[24:26])[0]

                    if self.fat_type == 'FAT32':
                        hi_cluster = struct.unpack('<H', entry_data[20:22])[0]
                    else:
                        hi_cluster = 0

                    lo_cluster = struct.unpack('<H', entry_data[26:28])[0]
                    cluster = (hi_cluster << 16) | lo_cluster
                    size = struct.unpack('<I', entry_data[28:32])[0]
                    nt_case_info = entry_data[12]
                    
                    # Decode dates and times
                    creation_datetime_str = f"{decode_fat_date(creation_date)} {decode_fat_time(creation_time)}"
                    if creation_time_tenth > 0:
                        creation_datetime_str += f".{creation_time_tenth * 10:02d}"
                    
                    last_accessed_str = decode_fat_date(last_accessed_date)
                    last_modified_datetime_str = f"{decode_fat_date(last_modified_date)} {decode_fat_time(last_modified_time)}"
                    
                    # Derive file type from name
                    file_type = Path(display_name).suffix.upper().lstrip('.')

                    entries.append({
                        'name': display_name,
                        'short_name': short_name_83,
                        'raw_short_name': raw_short_name,
                        'size': size,
                        'cluster': cluster,
                        'file_type': file_type,
                        'index': i,
                        'is_read_only': bool(attr & 0x01),
                        'is_hidden': bool(attr & 0x02),
                        'is_system': bool(attr & 0x04),
                        'is_dir': bool(attr & 0x10),
                        'is_archive': bool(attr & 0x20),
                        'attributes': attr,
                        'nt_case_info': nt_case_info,
                        'creation_time': creation_time,
                        'creation_time_tenth': creation_time_tenth,
                        'creation_date': creation_date,
                        'creation_datetime_str': creation_datetime_str,
                        'last_accessed_date': last_accessed_date,
                        'last_accessed_str': last_accessed_str,
                        'last_modified_time': last_modified_time,
                        'last_modified_date': last_modified_date,
                        'last_modified_datetime_str': last_modified_datetime_str,
                    })
                
                # Reset LFN accumulator
                lfn_parts = []
                lfn_checksum = None
        
        return entries
    
    def read_raw_directory_entries(self):
        """Read all raw directory entries from disk"""
        raw_entries = []
        with open(self.image_path, 'rb') as f:
            f.seek(self.root_start)
            for i in range(self.root_entries):
                entry_data = f.read(32)
                raw_entries.append((i, entry_data))
                if entry_data[0] == 0x00:  # End of directory
                    break
        return raw_entries
    
    def find_free_clusters(self, count: int = None) -> List[int]:
        """Find free clusters in the FAT. If count is None, find all."""
        fat_data = self.read_fat()
        free_clusters = []
        
        total_clusters = (self.total_sectors - (self.data_start // self.bytes_per_sector)) // self.sectors_per_cluster
        
        for cluster in range(2, total_clusters + 2):
            if self.get_fat_entry(fat_data, cluster) == 0:
                free_clusters.append(cluster)
                if count is not None and len(free_clusters) >= count:
                    break
        
        return free_clusters
    
    def get_existing_83_names(self) -> List[str]:
        """Get list of all existing 8.3, 11 byte names (no dot) in the root directory"""
        names = []
        
        with open(self.image_path, 'rb') as f:
            f.seek(self.root_start)
            
            for i in range(self.root_entries):
                entry_data = f.read(32)
                
                if entry_data[0] in (0x00, 0xE5):
                    continue
                
                attr = entry_data[11]
                
                # Skip LFN entries and volume labels
                if attr == 0x0F or (attr & 0x08):
                    continue
                
                # Get the 8.3 name (11 bytes, no dot)
                names.append(decode_raw_83_name(entry_data))
        
        return names
    
    def get_cluster_map(self) -> dict:
        """
        Return a dictionary mapping cluster numbers to filenames.
        Used to visualize which file occupies which clusters.
        """
        mapping = {}
        fat_data = self.read_fat()
        entries = self.read_root_directory()
        
        for entry in entries:
            cluster = entry['cluster']
            if cluster < 2:
                continue
                
            # Follow chain
            curr = cluster
            visited = set()
            while curr >= 2 and curr < 0xFF8:
                if curr in visited:
                    break
                visited.add(curr)
                mapping[curr] = entry['name']
                curr = self.get_fat_entry(fat_data, curr)
                
        return mapping

    def get_cluster_chain(self, cluster: int) -> List[int]:
        """
        Get the full chain of clusters containing the specified cluster.
        Traverses backwards to find the start, then forwards to the end.
        """
        fat_data = self.read_fat()
        # Calculate max cluster based on data area size
        max_cluster = (self.total_data_sectors // self.sectors_per_cluster) + 2
        
        # 1. Find the start of the chain
        # Scan FAT for any entry pointing to 'current' until we find the head
        current = cluster
        while True:
            parent = None
            for c in range(2, max_cluster):
                if self.get_fat_entry(fat_data, c) == current:
                    parent = c
                    break
            
            if parent is not None:
                current = parent
            else:
                # No parent found, 'current' is the start
                break
                
        # 2. Traverse forward from start
        chain = []
        curr = current
        visited = set()
        
        while curr >= 2 and curr < 0xFF8:
            if curr in visited: # Cycle detection
                break
            visited.add(curr)
            chain.append(curr)
            curr = self.get_fat_entry(fat_data, curr)
            
        return chain

    def write_file_to_image(self, filename: str, data: bytes, use_numeric_tail: bool = False, modification_dt: Optional[datetime.datetime] = None) -> bool:
        """Write a file to the disk image with VFAT long filename support
        
        Args:
            filename: Original filename (can be long)
            data: File data
            use_numeric_tail: Whether to use numeric tails for 8.3 name generation
            modification_dt: Optional modification datetime (defaults to now)
            
        Returns:
            True if successful, False otherwise
        """
        # Calculate clusters needed
        clusters_needed = (len(data) + self.bytes_per_cluster - 1) // self.bytes_per_cluster
        if clusters_needed == 0:
            clusters_needed = 1  # Even empty files need at least one cluster
        
        # Find free clusters
        free_clusters = self.find_free_clusters(clusters_needed)
        if len(free_clusters) < clusters_needed:
            return False
        
        # Get existing 8.3 names to avoid collisions
        existing_83_names = self.get_existing_83_names()
        
        # Generate 8.3 name
        short_name_83 = generate_83_name(filename, existing_83_names, use_numeric_tail)
        short_name_bytes = short_name_83.encode('ascii')[:11]  # 11 bytes, no dot
        
        # Determine if we need LFN entries
        # Reconstruct what the short name looks like with a dot
        short_with_dot = format_83_name(short_name_83)
        
        # Need LFN if original name is different from short name (preserve case)
        needs_lfn = filename != short_with_dot
        
        # Create LFN entries if needed
        lfn_entries = []
        if needs_lfn:
            lfn_entries = create_lfn_entries(filename, short_name_bytes)
        
        # Calculate total entries needed
        total_entries_needed = len(lfn_entries) + 1  # LFN entries + short entry
        
        # Find contiguous free directory entries
        with open(self.image_path, 'r+b') as f:
            f.seek(self.root_start)
            entry_index = -1
            consecutive_free = 0
            start_index = -1
            
            for i in range(self.root_entries):
                entry_data = f.read(32)
                if entry_data[0] in (0x00, 0xE5):
                    if consecutive_free == 0:
                        start_index = i
                    consecutive_free += 1
                    
                    if consecutive_free >= total_entries_needed:
                        entry_index = start_index
                        break
                else:
                    consecutive_free = 0
                    start_index = -1
            
            if entry_index == -1:
                return False
            
            # Write LFN entries (if any)
            for i, lfn_entry in enumerate(lfn_entries):
                f.seek(self.root_start + ((entry_index + i) * 32))
                f.write(lfn_entry)
            
            # Create short directory entry
            entry = bytearray(32)
            entry[0:11] = short_name_bytes
            entry[11] = 0x20  # Archive attribute
            
            # Set date/time (current)
            now = datetime.datetime.now()
            mod_dt = modification_dt if modification_dt is not None else now

            creation_time = encode_fat_time(now)
            creation_date = encode_fat_date(now)
            modified_time = encode_fat_time(mod_dt)
            modified_date = encode_fat_date(mod_dt)
            
            entry[13] = 0  # Creation time tenth
            entry[14:16] = struct.pack('<H', creation_time)
            entry[16:18] = struct.pack('<H', creation_date)
            entry[18:20] = struct.pack('<H', creation_date)  # Last access date
            entry[22:24] = struct.pack('<H', modified_time)  # Last modified time
            entry[24:26] = struct.pack('<H', modified_date)  # Last modified date
            
            if len(data) > 0:
                entry[26:28] = struct.pack('<H', free_clusters[0])  # First cluster
            else:
                entry[26:28] = struct.pack('<H', 0)  # No cluster for empty files
                
            entry[28:32] = struct.pack('<I', len(data))  # File size
            
            # Write short directory entry
            short_entry_index = entry_index + len(lfn_entries)
            f.seek(self.root_start + (short_entry_index * 32))
            f.write(entry)
            
            # Write file data to clusters (if not empty)
            if len(data) > 0:
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
    
    def find_free_root_entries(self, required_slots: int) -> int:
        """
        Find a contiguous block of free root directory entries.
        Returns the starting index, or -1 if no space is found.
        """
        with open(self.image_path, 'rb') as f:
            f.seek(self.root_start)
            consecutive = 0
            start_index = -1

            for i in range(self.root_entries):
                data = f.read(32)
                # Check for End of Dir (0x00) or Deleted (0xE5)
                if data[0] == 0x00 or data[0] == 0xE5:
                    if consecutive == 0:
                        start_index = i
                    consecutive += 1

                    if consecutive >= required_slots:
                        return start_index
                else:
                    # Reset counter if we hit an occupied slot
                    consecutive = 0
                    start_index = -1

        return -1

    def rename_file(self, entry: dict, new_name: str, use_numeric_tail: bool = False) -> bool:
        """
        Rename a file, updating 8.3 name, LFN entries, and handling directory slot reallocation.
        """
        try:
            #
            # Prepare New Names
            #
            # Get existing names (excluding current file) to avoid collisions
            existing_names = self.get_existing_83_names()

            with open(self.image_path, 'rb') as f:
                f.seek(self.root_start + (entry['index'] * 32))
                current_raw = f.read(11)
                current_name_11 = current_raw.decode('ascii', errors='ignore')

            if current_name_11 in existing_names:
                existing_names.remove(current_name_11)

            # Generate and format new 8.3 name (11 bytes raw)
            short_name_11 = generate_83_name(new_name, existing_names, use_numeric_tail)
            
            try:
                raw_short_name = short_name_11.encode('ascii')[:11]
            except UnicodeEncodeError:
                raw_short_name = short_name_11.encode('ascii', 'ignore').ljust(11, b' ')[:11]

            # Generate LFN entries if needed
            base = short_name_11[:8].strip()
            ext = short_name_11[8:].strip()
            simple_name = f"{base}.{ext}" if ext else base

            needs_lfn = (new_name != simple_name) or (len(new_name) > 12)
            new_lfn_entries = []
            if needs_lfn:
                new_lfn_entries = create_lfn_entries(new_name, raw_short_name)

            total_new_slots = len(new_lfn_entries) + 1

            #
            # Analyze Current Location
            #
            # Find all current slots used by this file (Short + LFNs)
            old_lfn_indices = []
            idx = entry['index'] - 1
            with open(self.image_path, 'rb') as f:
                while idx >= 0:
                    f.seek(self.root_start + (idx * 32))
                    data = f.read(32)
                    if data[11] == 0x0F: # Attribute 0x0F is LFN
                        old_lfn_indices.append(idx)
                        idx -= 1
                    else:
                        break

            current_start_index = old_lfn_indices[-1] if old_lfn_indices else entry['index']
            total_old_slots = len(old_lfn_indices) + 1

            # Read original metadata (Cluster, Size, Dates) to preserve it
            with open(self.image_path, 'rb') as f:
                f.seek(self.root_start + (entry['index'] * 32))
                original_entry_data = bytearray(f.read(32))
            #
            # Determine Write Location
            #
            write_start_index = -1
            slots_to_delete = []

            if total_new_slots <= total_old_slots:
                # CASE A: Fits in current location
                write_start_index = current_start_index
                # Delete only the extra slots we no longer need
                slots_to_delete = range(current_start_index + total_new_slots, current_start_index + total_old_slots)
            else:
                # CASE B: Needs more space -> Find new contiguous block
                write_start_index = self.find_free_root_entries(total_new_slots)

                if write_start_index == -1:
                    print("Error: Disk full (root directory entries exhausted)")
                    return False

                # We are moving, so delete ALL old slots
                slots_to_delete = range(current_start_index, current_start_index + total_old_slots)

            #
            # Execute Write
            #
            with open(self.image_path, 'r+b') as f:
                # Mark old/unused slots as deleted (0xE5)
                for i in slots_to_delete:
                    f.seek(self.root_start + (i * 32))
                    f.write(b'\xE5')

                # Write New LFN Entries
                for i, lfn_data in enumerate(new_lfn_entries):
                    f.seek(self.root_start + ((write_start_index + i) * 32))
                    f.write(lfn_data)

                # Write New Short Entry
                new_short_entry = original_entry_data
                new_short_entry[0:11] = raw_short_name # Update 8.3 name

                short_entry_idx = write_start_index + len(new_lfn_entries)
                f.seek(self.root_start + (short_entry_idx * 32))
                f.write(new_short_entry)

            return True

        except Exception as e:
            print(f"Rename Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    
    def delete_file(self, entry: dict) -> bool:
        """Delete a file from the image (including LFN entries)"""
        try:
            with open(self.image_path, 'r+b') as f:
                # Mark the short entry as deleted
                f.seek(self.root_start + (entry['index'] * 32))
                f.write(b'\xE5')
                
                # Look backwards for LFN entries
                index = entry['index'] - 1
                while index >= 0:
                    f.seek(self.root_start + (index * 32))
                    entry_data = f.read(32)
                    
                    # Check if this is an LFN entry
                    if entry_data[11] == 0x0F:
                        # Mark as deleted
                        f.seek(self.root_start + (index * 32))
                        f.write(b'\xE5')
                        index -= 1
                    else:
                        break
            
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
    def create_empty_image(filepath: str, format_key: str = '1.44M'):
        """Create a blank FAT12 floppy disk image"""
        if format_key not in FAT12Image.FORMATS:
            raise ValueError(f"Unknown format: {format_key}")
            
        fmt = FAT12Image.FORMATS[format_key]
        
        bytes_per_sector = 512
        sectors_per_cluster = fmt['sectors_per_cluster']
        reserved_sectors = fmt['reserved_sectors']
        num_fats = 2
        root_entries = fmt['root_entries']
        total_sectors = fmt['total_sectors']
        media_descriptor = fmt['media_descriptor']
        sectors_per_fat = fmt['sectors_per_fat']
        sectors_per_track = fmt['sectors_per_track']
        heads = fmt['heads']
        hidden_sectors = fmt['hidden_sectors']
        
        total_size = total_sectors * bytes_per_sector
        
        with open(filepath, 'wb') as f:
            f.write(b'\x00' * total_size)
            f.seek(0)
            
            boot_sector = bytearray(512)
            boot_sector[0:3] = b'\xEB\x3C\x90'
            boot_sector[3:11] = b'YAMAHA  '  
            boot_sector[11:13] = bytes_per_sector.to_bytes(2, 'little')
            boot_sector[13] = sectors_per_cluster
            boot_sector[14:16] = reserved_sectors.to_bytes(2, 'little')
            boot_sector[16] = num_fats
            boot_sector[17:19] = root_entries.to_bytes(2, 'little')
            boot_sector[19:21] = total_sectors.to_bytes(2, 'little')
            boot_sector[21] = media_descriptor
            boot_sector[22:24] = sectors_per_fat.to_bytes(2, 'little')
            boot_sector[24:26] = sectors_per_track.to_bytes(2, 'little')
            boot_sector[26:28] = heads.to_bytes(2, 'little')
            boot_sector[28:32] = hidden_sectors.to_bytes(4, 'little')
            
            # Extended BPB
            boot_sector[36] = 0x00 # Drive number
            boot_sector[37] = 0x00 # Reserved
            boot_sector[38] = 0x29 # Boot signature
            # Volume ID (random)
            vol_id = random.getrandbits(32)
            boot_sector[39:43] = vol_id.to_bytes(4, 'little')
            boot_sector[43:54] = b'NO NAME    ' # Volume Label
            boot_sector[54:62] = b'FAT12   '    # FS Type
            
            boot_sector[510:512] = b'\x55\xAA'
            
            f.write(boot_sector)
            
            fat_start = reserved_sectors * bytes_per_sector
            fat_size = sectors_per_fat * bytes_per_sector
            
            fat_data = bytearray(fat_size)
            fat_data[0] = media_descriptor
            fat_data[1] = 0xFF
            fat_data[2] = 0xFF
            
            for i in range(num_fats):
                f.seek(fat_start + (i * fat_size))
                f.write(fat_data)
    

    def set_file_attributes(self, entry: dict, is_read_only: bool = None, 
                           is_hidden: bool = None, is_system: bool = None, 
                           is_archive: bool = None) -> bool:
        """
        Modify file attributes for a directory entry.
        
        Args:
            entry: Directory entry dictionary (must contain 'index' and 'attributes')
            is_read_only: Set read-only flag (None = no change)
            is_hidden: Set hidden flag (None = no change)
            is_system: Set system flag (None = no change)
            is_archive: Set archive flag (None = no change)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Start with current attributes
            current_attr = entry['attributes']
            new_attr = current_attr
            
            # Modify flags as requested (only if not None)
            if is_read_only is not None:
                if is_read_only:
                    new_attr |= 0x01  # Set read-only bit
                else:
                    new_attr &= ~0x01  # Clear read-only bit
            
            if is_hidden is not None:
                if is_hidden:
                    new_attr |= 0x02  # Set hidden bit
                else:
                    new_attr &= ~0x02  # Clear hidden bit
            
            if is_system is not None:
                if is_system:
                    new_attr |= 0x04  # Set system bit
                else:
                    new_attr &= ~0x04  # Clear system bit
            
            if is_archive is not None:
                if is_archive:
                    new_attr |= 0x20  # Set archive bit
                else:
                    new_attr &= ~0x20  # Clear archive bit
            
            # Preserve directory bit (0x10) - can't change this
            # Preserve volume label bit (0x08) - can't change this
            # These are structural attributes, not user-modifiable
            
            # Write the new attribute byte to disk
            with open(self.image_path, 'r+b') as f:
                # Attribute byte is at offset 11 in the directory entry
                f.seek(self.root_start + (entry['index'] * 32) + 11)
                f.write(bytes([new_attr]))
            
            return True
            
        except Exception as e:
            print(f"Error setting file attributes: {e}")
            return False

    def format_disk(self):
        """Format the disk - erase all files and reset FAT to clean state"""
        with open(self.image_path, 'r+b') as f:
            # Clear root directory
            f.seek(self.root_start)
            f.write(b'\x00' * self.root_size)
            
            # Reset FAT - keep media descriptor, clear everything else
            fat_data = bytearray(self.sectors_per_fat * self.bytes_per_sector)
            fat_data[0] = self.media_descriptor
            fat_data[1] = 0xFF
            fat_data[2] = 0xFF
            
            # Write to all FAT copies
            for i in range(self.num_fats):
                offset = self.fat_start + (i * self.sectors_per_fat * self.bytes_per_sector)
                f.seek(offset)
                f.write(fat_data)
