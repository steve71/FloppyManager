#!/usr/bin/env python3

# Copyright (c) 2026 Stephen P Smith
# MIT License

"""
FAT12 Filesystem Handler
Core functionality for reading/writing FAT12 floppy disk images with VFAT long filename support
"""

import os
import struct
import datetime
import random
from pathlib import Path
from typing import List, Optional

from vfat_utils import (encode_fat_time, encode_fat_date, 
                        generate_83_name, create_lfn_entries, 
                        format_83_name, DIR_ATTR_OFFSET, DIR_CRT_TIME_TENTH_OFFSET,
                        DIR_SHORT_NAME_LEN, DIR_LAST_MOD_TIME_OFFSET)

from fat12_directory import (
    read_directory, get_existing_83_names_in_directory,
    find_free_directory_entries, write_directory_entries,
    create_directory, delete_directory, delete_directory_entry,
    get_entry_offset, predict_short_name, rename_entry,
    read_raw_directory_entries, find_free_root_entries, delete_entry,
    find_entry_by_83_name, set_entry_attributes
)

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

        # Parse Extended BPB
        self.drive_number = boot_sector[36]
        self.reserved_ebpb = boot_sector[37]
        self.boot_signature = boot_sector[38]
        self.volume_id = struct.unpack('<I', boot_sector[39:43])[0]
        self.volume_label = boot_sector[43:54].decode('ascii', errors='ignore').rstrip()
        self.fs_type_label = boot_sector[54:62].decode('ascii', errors='ignore').rstrip()

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

    def calculate_size_on_disk(self, size_bytes: int) -> int:
        """Calculate the size on disk (allocated space) for a given file size"""
        if size_bytes == 0:
            return 0
        clusters = (size_bytes + self.bytes_per_cluster - 1) // self.bytes_per_cluster
        return clusters * self.bytes_per_cluster

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

    def predict_short_name(self, long_name: str, use_numeric_tail: bool = False, parent_cluster: int = None) -> str:
        """Predict the 8.3 short name that will be generated for a file"""
        return predict_short_name(self, long_name, use_numeric_tail, parent_cluster)

    def find_entry_by_83_name(self, target_83_name: str) -> Optional[dict]:
        """Find a directory entry by its 11-character 8.3 name (no dot)"""
        return find_entry_by_83_name(self, target_83_name)

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
            f.flush()
            os.fsync(f.fileno())
    
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
    
    def read_directory(self, cluster: int = None) -> List[dict]:
        """Read directory entries from root (None) or a specific cluster"""
        return read_directory(self, cluster)

    def read_root_directory(self) -> List[dict]:
        """Read root directory entries (wrapper for read_directory)"""
        return self.read_directory(None)
    
    def read_raw_directory_entries(self):
        """Read all raw directory entries from disk"""
        return read_raw_directory_entries(self)
    
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
        return get_existing_83_names_in_directory(self, None)
    
    def get_cluster_map(self) -> dict:
        """
        Return a dictionary mapping cluster numbers to filenames.
        Used to visualize which file occupies which clusters.
        """
        mapping = {}
        fat_data = self.read_fat()
        
        # Queue for traversal: (cluster, path_prefix)
        # Use None for root
        queue = [(None, "")]
        processed_dirs = set()
        
        while queue:
            dir_cluster, path_prefix = queue.pop(0)
            
            # Avoid processing the same directory cluster twice (loops)
            if dir_cluster is not None:
                if dir_cluster in processed_dirs:
                    continue
                processed_dirs.add(dir_cluster)
            
            entries = self.read_directory(dir_cluster)
            
            for entry in entries:
                name = entry['name']
                if name in ('.', '..'):
                    continue
                
                full_name = f"{path_prefix}/{name}" if path_prefix else name
                
                # Map clusters for this entry
                cluster = entry['cluster']
                if cluster >= 2:
                    curr = cluster
                    visited_chain = set()
                    while curr >= 2 and curr < 0xFF8:
                        if curr == 0xFF7: # Bad cluster
                            break
                        if curr in visited_chain:
                            break
                        visited_chain.add(curr)
                        mapping[curr] = full_name
                        curr = self.get_fat_entry(fat_data, curr)
                
                # If directory, add to queue
                if entry['is_dir']:
                    queue.append((entry['cluster'], full_name))
                
        return mapping

    def get_cluster_chain(self, cluster: int) -> List[int]:
        """
        Get the full chain of clusters containing the specified cluster.
        Traverses backwards to find the start, then forwards to the end.
        """
        fat_data = self.read_fat()
        # Calculate max cluster based on data area size
        max_cluster = (self.total_data_sectors // self.sectors_per_cluster) + 2
        
        # If cluster is bad or reserved, don't try to trace chain
        if cluster == 0xFF7 or cluster < 2:
            return [cluster]
        
        # 1. Find the start of the chain
        # Scan FAT for any entry pointing to 'current' until we find the head
        current = cluster
        visited_backwards = {current}

        while True:
            parent = None
            for c in range(2, max_cluster):
                if self.get_fat_entry(fat_data, c) == current:
                    parent = c
                    break
            
            if parent is not None:
                if parent in visited_backwards:
                    # Loop detected in backward traversal
                    break
                visited_backwards.add(parent)
                current = parent
            else:
                # No parent found, 'current' is the start
                break
                
        # 2. Traverse forward from start
        chain = []
        curr = current
        visited = set()
        
        while curr >= 2 and curr < 0xFF8:
            if curr == 0xFF7:
                break
            if curr in visited: # Cycle detection
                break
            visited.add(curr)
            chain.append(curr)
            curr = self.get_fat_entry(fat_data, curr)
            
        return chain

    def write_file_to_image(self, filename: str, data: bytes, 
                           use_numeric_tail: bool = False, 
                           modification_dt: Optional[datetime.datetime] = None,
                           parent_cluster: int = None) -> bool:
        """Write a file to the disk image with VFAT long filename support
        
        Args:
            filename: Original filename (can be long)
            data: File data
            use_numeric_tail: Whether to use numeric tails for 8.3 name generation
            modification_dt: Optional modification datetime (defaults to now)
            parent_cluster: Cluster of the parent directory (None for root)
            
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
        existing_83_names = get_existing_83_names_in_directory(self, parent_cluster)
        
        # Generate 8.3 name
        short_name_83 = generate_83_name(filename, existing_83_names, use_numeric_tail)
        short_name_bytes = short_name_83.encode('ascii')[:DIR_SHORT_NAME_LEN]  # 11 bytes, no dot
        
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
        
        # Find free entries
        entry_index = find_free_directory_entries(self, parent_cluster, total_entries_needed)
        if entry_index == -1:
            return False
            
        try:
            # Create short directory entry
            entry = bytearray(32)
            entry[0:DIR_SHORT_NAME_LEN] = short_name_bytes
            entry[DIR_ATTR_OFFSET] = 0x20  # Archive attribute
            
            # Set date/time (current)
            now = datetime.datetime.now()
            mod_dt = modification_dt if modification_dt is not None else now

            creation_time = encode_fat_time(now)
            creation_date = encode_fat_date(now)
            modified_time = encode_fat_time(mod_dt)
            modified_date = encode_fat_date(mod_dt)
            
            entry[DIR_CRT_TIME_TENTH_OFFSET] = 0  # Creation time tenth
            entry[14:16] = struct.pack('<H', creation_time)
            entry[16:18] = struct.pack('<H', creation_date)
            entry[18:20] = struct.pack('<H', creation_date)  # Last access date
            entry[DIR_LAST_MOD_TIME_OFFSET:DIR_LAST_MOD_TIME_OFFSET+2] = struct.pack('<H', modified_time)  # Last modified time
            entry[24:26] = struct.pack('<H', modified_date)  # Last modified date
            
            if len(data) > 0:
                entry[26:28] = struct.pack('<H', free_clusters[0])  # First cluster
            else:
                entry[26:28] = struct.pack('<H', 0)  # No cluster for empty files
                
            entry[28:32] = struct.pack('<I', len(data))  # File size
            
            # Write entries
            write_directory_entries(self, parent_cluster, entry_index, lfn_entries, entry)
            
            # Write file data to clusters (if not empty)
            if len(data) > 0:
                offset = 0
                fat_data = self.read_fat()
                
                with open(self.image_path, 'r+b') as f:
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
                    
                    f.flush()
                    os.fsync(f.fileno())
                
                # Write FAT
                self.write_fat(fat_data)
        
            return True
        except Exception:
            return False

    def get_existing_83_names_in_directory(self, cluster: int = None) -> List[str]:
        """Get list of all existing 8.3 names in a directory"""
        return get_existing_83_names_in_directory(self, cluster)

    def find_free_directory_entries(self, cluster: int = None, required_slots: int = 1) -> int:
        """Find contiguous free directory entries"""
        return find_free_directory_entries(self, cluster, required_slots)

    def create_directory(self, dir_name: str, parent_cluster: int = None, use_numeric_tail: bool = True) -> bool:
        """Create a new directory"""
        return create_directory(self, dir_name, parent_cluster, use_numeric_tail)

    def find_free_root_entries(self, required_slots: int) -> int:
        """
        Find a contiguous block of free root directory entries.
        Returns the starting index, or -1 if no space is found.
        """
        return find_free_root_entries(self, required_slots)

    def rename_entry(self, entry: dict, new_name: str, use_numeric_tail: bool = False) -> bool:
        """
        Rename a file, updating 8.3 name, LFN entries, and handling directory slot reallocation.
        """
        return rename_entry(self, entry, new_name, use_numeric_tail)

    def delete_file(self, entry: dict) -> bool:
        """Delete a file from the image (including LFN entries)"""
        return delete_entry(self, entry)
    
    def delete_directory(self, entry: dict, recursive: bool = False) -> bool:
        """Delete a directory
        Args:
            entry: Directory entry dictionary
            recursive: If True, delete non-empty directories
        Returns:
            True if successful, False otherwise
        """
        return delete_directory(self, entry, recursive)

    def delete_directory_entry(self, parent_cluster: int, entry_index: int) -> bool:
        """Delete a directory entry (mark as deleted)"""
        return delete_directory_entry(self, parent_cluster, entry_index)

    def extract_file(self, entry: dict) -> bytes:
        """Extract file data from the image"""
        data = bytearray()
        
        with open(self.image_path, 'rb') as f:
            if entry['cluster'] < 2:
                return bytes()
            
            fat_data = self.read_fat()
            current_cluster = entry['cluster']
            remaining = entry['size']
            visited = set()
            
            while current_cluster < 0xFF8 and remaining > 0:
                if current_cluster in visited:
                    print(f"Warning: Loop detected in file cluster chain at {current_cluster}")
                    break
                visited.add(current_cluster)

                cluster_offset = self.data_start + ((current_cluster - 2) * self.bytes_per_cluster)
                f.seek(cluster_offset)
                
                to_read = min(self.bytes_per_cluster, remaining)
                data.extend(f.read(to_read))
                remaining -= to_read
                
                current_cluster = self.get_fat_entry(fat_data, current_cluster)
        
        return bytes(data[:entry['size']])
    
    @staticmethod
    def create_empty_image(filepath: str, format_key: str = '1.44M', oem_name: str = 'MSDOS5.0'):
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
            
            # OEM Name (8 bytes, space padded)
            oem_bytes = oem_name.encode('ascii', 'replace')[:8].ljust(8, b' ')
            boot_sector[3:11] = oem_bytes
            boot_sector[11:13] = bytes_per_sector.to_bytes(2, 'little')
            boot_sector[13] = sectors_per_cluster
            boot_sector[14:16] = reserved_sectors.to_bytes(2, 'little')
            boot_sector[16] = num_fats
            boot_sector[17:19] = root_entries.to_bytes(2, 'little')
            
            if total_sectors < 65536:
                boot_sector[19:21] = total_sectors.to_bytes(2, 'little')
                boot_sector[32:36] = (0).to_bytes(4, 'little')
            else:
                boot_sector[19:21] = (0).to_bytes(2, 'little')
                boot_sector[32:36] = total_sectors.to_bytes(4, 'little')

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
    

    def set_entry_attributes(self, entry: dict, is_read_only: bool = None, 
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
        return set_entry_attributes(self, entry, is_read_only, is_hidden, is_system, is_archive)

    def format_disk(self, full_format: bool = False):
        """Format the disk - erase all files and reset FAT to clean state
        
        Args:
            full_format: If True, also zero out the data area (slower but more secure)
        """
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
            f.flush()
            os.fsync(f.fileno())
            
            # If full format, clear data area
            if full_format:
                f.seek(self.data_start)
                # Calculate data size
                total_size = self.total_sectors * self.bytes_per_sector
                data_size = total_size - self.data_start
                
                # Write in chunks
                chunk_size = 65536
                zeros = b'\x00' * chunk_size
                remaining = data_size
                while remaining > 0:
                    write_size = min(remaining, chunk_size)
                    f.write(zeros[:write_size])
                    remaining -= write_size
                f.flush()
                os.fsync(f.fileno())

    def defragment_filesystem(self) -> bool:
        """
        Defragment the filesystem by reading all files to memory,
        formatting the disk, and writing them back contiguously.
        Preserves attributes and timestamps.
        """
        try:
            # 1. Collect all items recursively
            all_items = [] # List of (parent_path_tuple, entry_dict)
            files_data = {} # Map id(entry) -> bytes
            
            def collect(cluster, parent_path):
                entries = self.read_directory(cluster)
                for entry in entries:
                    if entry['name'] in ('.', '..'): continue
                    
                    all_items.append( (parent_path, entry) )
                    
                    if entry['is_dir']:
                        collect(entry['cluster'], parent_path + (entry['name'],))
                    else:
                        files_data[id(entry)] = self.extract_file(entry)
            
            collect(None, ())
            
            # 2. Format (Quick format preserves BPB but clears FAT/Root)
            self.format_disk(full_format=False)
            
            # 3. Restore
            # Map path tuple to cluster ID. Root is None.
            path_to_cluster = { (): None }
            
            # Sort by path length (parents first) then name (alphabetical sort)
            all_items.sort(key=lambda x: (len(x[0]), x[1]['name']))
            
            for parent_path, entry in all_items:
                parent_cluster = path_to_cluster[parent_path]
                
                if entry['is_dir']:
                    if not self.create_directory(entry['name'], parent_cluster, use_numeric_tail=True):
                        return False
                        
                    # Find the new cluster
                    new_entries = self.read_directory(parent_cluster)
                    new_entry = next(e for e in new_entries if e['name'] == entry['name'])
                    path_to_cluster[parent_path + (entry['name'],)] = new_entry['cluster']
                    target_entry = new_entry
                else:
                    data = files_data[id(entry)]
                    if not self.write_file_to_image(entry['name'], data, use_numeric_tail=True, parent_cluster=parent_cluster):
                        return False
                    
                    # Find the new entry to patch metadata
                    new_entries = self.read_directory(parent_cluster)
                    target_entry = next(e for e in new_entries if e['name'] == entry['name'])

                # Patch Metadata (Attributes & Timestamps) directly
                with open(self.image_path, 'r+b') as f:
                    offset = get_entry_offset(self, parent_cluster, target_entry['index'])
                    if offset != -1:
                        # Attributes (Offset 11)
                        f.seek(offset + DIR_ATTR_OFFSET)
                        f.write(bytes([entry['attributes']]))
                        
                        # Timestamps (Offset 13-26)
                        f.seek(offset + DIR_CRT_TIME_TENTH_OFFSET)
                        f.write(struct.pack('B', entry['creation_time_tenth']))
                        f.write(struct.pack('<H', entry['creation_time']))
                        f.write(struct.pack('<H', entry['creation_date']))
                        f.write(struct.pack('<H', entry['last_accessed_date']))
                        # Skip High Cluster (2 bytes at 20)
                        f.seek(offset + DIR_LAST_MOD_TIME_OFFSET)
                        f.write(struct.pack('<H', entry['last_modified_time']))
                        f.write(struct.pack('<H', entry['last_modified_date']))
            
            return True
            
        except Exception as e:
            print(f"Defrag error: {e}")
            return False
