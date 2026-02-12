#!/usr/bin/env python3

# Copyright (c) 2026 Stephen P Smith
# MIT License

"""
FAT12 Directory Operations

This module provides low-level logic for handling FAT12 directory structures, including:
- Reading and parsing directory entries (Root and Subdirectories).
- Full VFAT Long Filename (LFN) support (reading, writing, checksums).
- Creating, renaming, and deleting files and directories.
- Managing directory cluster chains (expansion and cleanup).
- Handling 8.3 short name generation and collision detection.
- Modifying file attributes.

It serves as the core directory manipulation layer used by the FAT12Image handler.
"""

import struct
import os
import datetime
from pathlib import Path
from typing import List, Optional

from vfat_utils import (
    decode_lfn_text, decode_short_name, decode_raw_83_name,
    calculate_lfn_checksum, create_lfn_entries, generate_83_name,
    format_83_name, decode_fat_date, decode_fat_time,
    encode_fat_time, encode_fat_date,
    DIR_ATTR_OFFSET, LFN_CHECKSUM_OFFSET, DIR_CRT_TIME_TENTH_OFFSET, DIR_SHORT_NAME_LEN,
    DIR_LAST_MOD_TIME_OFFSET
)

def iter_directory_entries(fs, cluster: int = None):
    """
    Iterates through all 32-byte directory entries in a given directory.

    This generator handles both the fixed-size root directory and cluster-chained
    subdirectories. It yields each entry as a raw bytes object along with its
    sequential index within the directory. Includes cycle detection to prevent
    infinite loops on corrupted disk images.

    Args:
        fs: The FAT12Image filesystem object.
        cluster: The starting cluster of the directory to read. If None or 0,
                 the root directory is read.

    Yields:
        A tuple of (int, bytes) representing the entry's index and its
        32-byte raw data.
    """
    with open(fs.image_path, 'rb') as f:
        if cluster is None or cluster == 0:
            # Root Directory
            f.seek(fs.root_start)
            for i in range(fs.root_entries):
                yield i, f.read(32)
        else:
            # Subdirectory (Cluster Chain)
            fat_data = fs.read_fat()
            current_cluster = cluster
            idx = 0
            visited = set()
            
            while current_cluster >= 2 and current_cluster < 0xFF8:
                if current_cluster in visited:
                    print(f"Warning: Loop detected in directory cluster chain at {current_cluster}")
                    break
                visited.add(current_cluster)

                offset = fs.data_start + ((current_cluster - 2) * fs.bytes_per_cluster)
                f.seek(offset)
                
                entries_per_cluster = fs.bytes_per_cluster // 32
                for _ in range(entries_per_cluster):
                    yield idx, f.read(32)
                    idx += 1
                    
                current_cluster = fs.get_fat_entry(fat_data, current_cluster)

def read_directory(fs, cluster: int = None) -> List[dict]:
    """
    Reads and parses all entries in a directory, processing VFAT Long Filenames.

    This function iterates through raw 32-byte entries, reconstructs long
    filenames from LFN fragments, and parses short filename entries into a
    structured dictionary format. It handles checksum verification to correctly
    associate LFNs with their corresponding short entries.

    Args:
        fs: The FAT12Image filesystem object.
        cluster: The starting cluster of the directory to read. If None or 0,
                 the root directory is read.

    Returns:
        A list of dictionaries, where each dictionary represents a file or
        subdirectory with its parsed attributes (e.g., name, size, dates,
        attributes).
    """
    entries = []
    
    # LFN accumulator
    lfn_parts = []
    lfn_checksum = None
    
    for i, entry_data in iter_directory_entries(fs, cluster):
            
        # Check if entry is end of directory
        if entry_data[0] == 0x00:
            break
                
        # Check if entry is free (deleted)
        if entry_data[0] == 0xE5:
            lfn_parts = []
            lfn_checksum = None
            continue
            
        attr = entry_data[DIR_ATTR_OFFSET]
            
        # Check if this is an LFN entry
        if attr == 0x0F:
            seq = entry_data[0]
            checksum = entry_data[LFN_CHECKSUM_OFFSET]
                
            text = decode_lfn_text(entry_data)
            if text is not None:
                if seq & 0x40:
                    # This is the last entry, start fresh
                    lfn_parts = [text]
                    lfn_checksum = checksum
                else:
                    # This is a continuation, append to the end
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
            
        if name and name[0] not in ('\x00',):
            short_name_83 = f"{name}.{ext}" if ext else name
                
            # Store raw 11-byte name for robust collision detection
            raw_short_name = decode_raw_83_name(entry_data)
                
            # Check if we have a valid LFN for this entry
            long_name = None
            if lfn_parts and lfn_checksum is not None:
                # Verify checksum
                short_name_bytes = entry_data[0:DIR_SHORT_NAME_LEN]
                calculated_checksum = calculate_lfn_checksum(short_name_bytes)
                    
                if calculated_checksum == lfn_checksum:
                    # LFN entries are stored in reverse order, so reverse the list
                    long_name = ''.join(reversed(lfn_parts))
                
            # Use long name if available, otherwise use short name
            display_name = long_name if long_name else short_name_83
                
            creation_time_tenth = entry_data[DIR_CRT_TIME_TENTH_OFFSET]
            creation_time = struct.unpack('<H', entry_data[14:16])[0]
            creation_date = struct.unpack('<H', entry_data[16:18])[0]
            last_accessed_date = struct.unpack('<H', entry_data[18:20])[0]
            last_modified_time = struct.unpack('<H', entry_data[DIR_LAST_MOD_TIME_OFFSET:DIR_LAST_MOD_TIME_OFFSET+2])[0]
            last_modified_date = struct.unpack('<H', entry_data[24:26])[0]

            if fs.fat_type == 'FAT32':
                hi_cluster = struct.unpack('<H', entry_data[20:22])[0]
            else:
                hi_cluster = 0

            lo_cluster = struct.unpack('<H', entry_data[26:28])[0]
            entry_cluster = (hi_cluster << 16) | lo_cluster
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
                'cluster': entry_cluster,
                'file_type': file_type,
                'index': i,
                'parent_cluster': cluster if cluster is not None else 0,
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

def get_existing_83_names_in_directory(fs, cluster: int = None) -> List[str]:
    """
    Retrieves a list of all existing 8.3 short names from a directory.

    This is used for collision detection when generating new short names. It
    returns the raw 11-byte names, converted to uppercase, to ensure
    case-insensitive comparison. It correctly skips LFN entries and volume labels.

    Args:
        fs: The FAT12Image filesystem object.
        cluster: The starting cluster of the directory. If None or 0, the root
                 directory is scanned.

    Returns:
        A list of uppercase, 11-character 8.3 short names.
    """
    names = []
    for _, entry_data in iter_directory_entries(fs, cluster):
        if entry_data[0] in (0x00, 0xE5):
            continue
        attr = entry_data[DIR_ATTR_OFFSET]
        if attr == 0x0F or (attr & 0x08):
            continue
        names.append(decode_raw_83_name(entry_data).upper())
    return names

def read_raw_directory_entries(fs):
    """Read all raw directory entries from disk"""
    raw_entries = []
    with open(fs.image_path, 'rb') as f:
        f.seek(fs.root_start)
        for i in range(fs.root_entries):
            entry_data = f.read(32)
            raw_entries.append((i, entry_data))
            if entry_data[0] == 0x00:  # End of directory
                break
    return raw_entries

def find_free_directory_entries(fs, cluster: int = None, required_slots: int = 1) -> int:
    """
    Finds a contiguous block of free directory entries.

    This function searches for a specified number of available slots (either
    deleted `0xE5` or never-used `0x00`). For subdirectories, if not enough
    space is found in the currently allocated clusters, it will attempt to
    expand the directory by allocating new clusters and extending the FAT chain.
    The root directory has a fixed size and cannot be expanded.

    Args:
        fs: The FAT12Image filesystem object.
        cluster: The starting cluster of the directory. If None or 0, searches
                 the root directory.
        required_slots: The number of contiguous 32-byte entries required.

    Returns:
        The starting index of the found block of free entries.
        Returns -1 if a sufficiently large block cannot be found or allocated
        (e.g., root directory is full, or the disk is out of free clusters).
    """
    consecutive = 0
    start_index = -1
    last_index = -1
    
    for i, data in iter_directory_entries(fs, cluster):
        last_index = i
        if data[0] == 0x00:
            # End of directory found, all subsequent entries are free.
            if consecutive == 0:
                start_index = i
            
            # For root directory, check if there's enough space to the end.
            if cluster is None or cluster == 0:
                if fs.root_entries - start_index >= required_slots:
                    return start_index
                else:
                    return -1 # Not enough space in root directory
            else:
                # For subdirectories, we can expand later, so return the start.
                return start_index

        if data[0] == 0xE5:
            if consecutive == 0:
                start_index = i
            consecutive += 1
            if consecutive >= required_slots:
                return start_index
        else:
            consecutive = 0
            start_index = -1
    
    # If we are here, we ran out of allocated slots in the directory
    
    # Root directory cannot be expanded
    if cluster is None or cluster == 0:
        return -1
        
    # Subdirectory expansion logic
    if start_index == -1:
        start_index = last_index + 1
        
    needed = required_slots - consecutive
    entries_per_cluster = fs.bytes_per_cluster // 32
    clusters_needed = (needed + entries_per_cluster - 1) // entries_per_cluster
    
    free_clusters = fs.find_free_clusters(clusters_needed)
    if len(free_clusters) < clusters_needed:
        return -1 # Disk full
        
    # Extend the cluster chain
    fat_data = fs.read_fat()
    curr = cluster
    while True:
        next_clus = fs.get_fat_entry(fat_data, curr)
        if next_clus >= 0xFF8:
            break
        curr = next_clus
        
    for new_cluster in free_clusters:
        fs.set_fat_entry(fat_data, curr, new_cluster)
        fs.set_fat_entry(fat_data, new_cluster, 0xFFF)
        curr = new_cluster
        
        # Zero out the new cluster
        with open(fs.image_path, 'r+b') as f:
            offset = fs.data_start + ((new_cluster - 2) * fs.bytes_per_cluster)
            f.seek(offset)
            f.write(b'\x00' * fs.bytes_per_cluster)
            f.flush()
            os.fsync(f.fileno())
            
    fs.write_fat(fat_data)
    
    return start_index

def find_free_root_entries(fs, required_slots: int) -> int:
    """
    Find a contiguous block of free root directory entries.
    Returns the starting index, or -1 if no space is found.
    """
    with open(fs.image_path, 'rb') as f:
        f.seek(fs.root_start)
        consecutive = 0
        start_index = -1

        for i in range(fs.root_entries):
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

def get_entry_offset(fs, parent_cluster: int, index: int, fat_data: bytearray = None) -> int:
    """
    Calculates the absolute physical byte offset of a directory entry in the image.

    This function is used to seek the correct location to read or write
    a specific directory entry. It correctly handles the fixed layout of the
    root directory and traverses the cluster chain for subdirectories.

    Args:
        fs: The FAT12Image filesystem object.
        parent_cluster: The starting cluster of the parent directory.
                        If None or 0, assumes the root directory.
        index: The sequential index of the entry within the directory listing.
        fat_data: An optional pre-read FAT to avoid re-reading.

    Returns:
        The absolute byte offset of the entry from the start of the disk image,
        or -1 if the offset is invalid (e.g., corrupted chain).
    """
    if parent_cluster is None or parent_cluster == 0:
        return fs.root_start + (index * 32)
    
    if fat_data is None:
        fat_data = fs.read_fat()
        
    entries_per_cluster = fs.bytes_per_cluster // 32
    cluster_skip = index // entries_per_cluster
    entry_offset = index % entries_per_cluster
    
    curr = parent_cluster
    for _ in range(cluster_skip):
        curr = fs.get_fat_entry(fat_data, curr)
        if curr >= 0xFF8: return -1
        
    return fs.data_start + ((curr - 2) * fs.bytes_per_cluster) + (entry_offset * 32)

def write_directory_entries(fs, parent_cluster: int, entry_index: int,
                            lfn_entries: List[bytes], short_entry: bytes):
    """
    Writes a sequence of LFN entries and one short entry to the disk.

    This function handles the low-level writing of directory entry data. It
    calculates the correct offsets for both root and subdirectories and can
    span across cluster boundaries if necessary when writing to a subdirectory.

    Args:
        fs: The FAT12Image filesystem object.
        parent_cluster: The starting cluster of the parent directory.
                        If None or 0, writes to the root directory.
        entry_index: The starting index in the directory to begin writing.
        lfn_entries: A list of raw 32-byte LFN entries to write.
        short_entry: The raw 32-byte short file name entry to write.
    """
    with open(fs.image_path, 'r+b') as f:
        if parent_cluster is None or parent_cluster == 0:
            # Root directory
            base_offset = fs.root_start
            for i, lfn_entry in enumerate(lfn_entries):
                f.seek(base_offset + ((entry_index + i) * 32))
                f.write(lfn_entry)
            
            short_entry_index = entry_index + len(lfn_entries)
            f.seek(base_offset + (short_entry_index * 32))
            f.write(short_entry)
            f.flush()
            os.fsync(f.fileno())
        else:
            # Subdirectory - handle cluster chain
            current_cluster = parent_cluster
            entries_per_cluster = fs.bytes_per_cluster // 32
            
            # Calculate start position
            start_cluster_idx = entry_index // entries_per_cluster
            offset_in_cluster = entry_index % entries_per_cluster
            
            # Navigate to the correct cluster
            fat_data = fs.read_fat()
            for _ in range(start_cluster_idx):
                current_cluster = fs.get_fat_entry(fat_data, current_cluster)
            
            # Write entries
            all_entries = lfn_entries + [short_entry]
            
            for i, entry_data in enumerate(all_entries):
                current_idx_in_cluster = offset_in_cluster + i
                
                if current_idx_in_cluster >= entries_per_cluster:
                    current_cluster = fs.get_fat_entry(fat_data, current_cluster)
                    offset_in_cluster = 0
                    current_idx_in_cluster = 0
                
                cluster_offset = fs.data_start + ((current_cluster - 2) * fs.bytes_per_cluster)
                f.seek(cluster_offset + (current_idx_in_cluster * 32))
                f.write(entry_data)
            f.flush()
            os.fsync(f.fileno())

def initialize_directory(fs, dir_cluster: int, parent_cluster: int = None):
    """
    Initializes a new directory cluster with the special '.' and '..' entries.

    Every new subdirectory must contain these two entries.
    - The '.' entry points to the directory's own starting cluster.
    - The '..' entry points to the parent directory's starting cluster (or 0 for root).
    The rest of the cluster is zeroed out.

    Args:
        fs: The FAT12Image filesystem object.
        dir_cluster: The cluster number of the new directory to initialize.
        parent_cluster: The cluster number of the parent directory.
                        If None or 0, the parent is the root directory.
    """
    now = datetime.datetime.now()
    creation_time = encode_fat_time(now)
    creation_date = encode_fat_date(now)
    
    # Create . entry
    dot_entry = bytearray(32)
    dot_entry[0:DIR_SHORT_NAME_LEN] = b'.          '
    dot_entry[DIR_ATTR_OFFSET] = 0x10
    dot_entry[14:16] = struct.pack('<H', creation_time)
    dot_entry[16:18] = struct.pack('<H', creation_date)
    dot_entry[18:20] = struct.pack('<H', creation_date)
    dot_entry[DIR_LAST_MOD_TIME_OFFSET:DIR_LAST_MOD_TIME_OFFSET+2] = struct.pack('<H', creation_time)
    dot_entry[24:26] = struct.pack('<H', creation_date)
    dot_entry[26:28] = struct.pack('<H', dir_cluster)
    dot_entry[28:32] = struct.pack('<I', 0)
    
    # Create .. entry
    dotdot_entry = bytearray(32)
    dotdot_entry[0:DIR_SHORT_NAME_LEN] = b'..         '
    dotdot_entry[DIR_ATTR_OFFSET] = 0x10
    dotdot_entry[14:16] = struct.pack('<H', creation_time)
    dotdot_entry[16:18] = struct.pack('<H', creation_date)
    dotdot_entry[18:20] = struct.pack('<H', creation_date)
    dotdot_entry[DIR_LAST_MOD_TIME_OFFSET:DIR_LAST_MOD_TIME_OFFSET+2] = struct.pack('<H', creation_time)
    dotdot_entry[24:26] = struct.pack('<H', creation_date)
    parent_clus = parent_cluster if parent_cluster is not None else 0
    dotdot_entry[26:28] = struct.pack('<H', parent_clus)
    dotdot_entry[28:32] = struct.pack('<I', 0)
    
    with open(fs.image_path, 'r+b') as f:
        cluster_offset = fs.data_start + ((dir_cluster - 2) * fs.bytes_per_cluster)
        f.seek(cluster_offset)
        f.write(dot_entry)
        f.write(dotdot_entry)
        remaining = fs.bytes_per_cluster - 64
        f.write(b'\x00' * remaining)
        f.flush()
        os.fsync(f.fileno())

def create_directory(fs, dir_name: str, parent_cluster: int = None, use_numeric_tail: bool = True) -> bool:
    """
    Creates a new subdirectory.

    This process involves:
    1. Checking for Long Filename (LFN) collisions.
    2. Generating a unique 8.3 short name.
    3. Allocating a new cluster for the directory's contents.
    4. Finding space in the parent directory for the new entry.
    5. Writing the LFN and short name entries to the parent directory.
    6. Initializing the new directory's cluster with '.' and '..' entries.

    Args:
        fs: The FAT12Image filesystem object.
        dir_name: The desired name for the new directory.
        parent_cluster: The cluster of the parent directory. If None or 0,
                        the directory is created in the root.
        use_numeric_tail: Toggles the 8.3 name generation algorithm.

    Returns:
        True if the directory was created successfully, False otherwise.
    """
    # Check for LFN collision
    entries = read_directory(fs, parent_cluster)
    if any(e['name'].lower() == dir_name.lower() for e in entries):
        print(f"Error: Directory '{dir_name}' already exists")
        return False

    existing_names = get_existing_83_names_in_directory(fs, parent_cluster)
    short_name_83 = generate_83_name(dir_name, existing_names, use_numeric_tail)
    short_name_bytes = short_name_83.encode('ascii')[:DIR_SHORT_NAME_LEN]
    
    short_with_dot = format_83_name(short_name_83)
    needs_lfn = dir_name != short_with_dot
    
    lfn_entries = []
    if needs_lfn:
        lfn_entries = create_lfn_entries(dir_name, short_name_bytes)
        
    total_entries = len(lfn_entries) + 1
    
    free_clusters = fs.find_free_clusters(1)
    if not free_clusters:
        return False
    dir_cluster = free_clusters[0]
    
    entry_index = find_free_directory_entries(fs, parent_cluster, total_entries)
    if entry_index == -1:
        return False
        
    fat_data = fs.read_fat()
    fs.set_fat_entry(fat_data, dir_cluster, 0xFFF)
    fs.write_fat(fat_data)
    
    entry = bytearray(32)
    entry[0:11] = short_name_bytes
    entry[DIR_ATTR_OFFSET] = 0x10
    entry[26:28] = struct.pack('<H', dir_cluster)
    
    write_directory_entries(fs, parent_cluster, entry_index, lfn_entries, entry)
    initialize_directory(fs, dir_cluster, parent_cluster)
    
    return True

def delete_directory_entry(fs, parent_cluster: int, entry_index: int) -> bool:
    """
    Marks a directory entry and its associated LFN entries as deleted.

    This is a low-level function that sets the first byte of the specified
    short entry and all preceding LFN entries to `0xE5`. It does not free
    any data clusters associated with the entry.

    Args:
        fs: The FAT12Image filesystem object.
        parent_cluster: The cluster of the directory containing the entry.
        entry_index: The index of the short filename entry to delete.

    Returns:
        True on success, False on failure (e.g., invalid index).
    """
    try:
        # Only read FAT if we are in a subdirectory
        fat_data = None
        if parent_cluster is not None and parent_cluster != 0:
            fat_data = fs.read_fat()
            
        with open(fs.image_path, 'r+b') as f:
            # Mark the short entry as deleted
            offset = get_entry_offset(fs, parent_cluster, entry_index, fat_data)
            if offset == -1:
                return False
                
            f.seek(offset)
            f.write(b'\xE5')
            
            # Look backwards for LFN entries
            index = entry_index - 1
            while index >= 0:
                offset = get_entry_offset(fs, parent_cluster, index, fat_data)
                if offset == -1: break
                f.seek(offset)
                entry_data = f.read(32)
                
                if entry_data and entry_data[DIR_ATTR_OFFSET] == 0x0F:
                    f.seek(offset)
                    f.write(b'\xE5')
                    index -= 1
                else:
                    break
            
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception as e:
        print(f"Error deleting directory entry: {e}")
        return False

def free_cluster_chain(fs, start_cluster: int):
    """Frees a chain of clusters starting from start_cluster."""
    if start_cluster < 2:
        return
        
    fat_data = fs.read_fat()
    current_cluster = start_cluster
    
    while current_cluster < 0xFF8:
        next_cluster = fs.get_fat_entry(fat_data, current_cluster)
        fs.set_fat_entry(fat_data, current_cluster, 0)
        current_cluster = next_cluster
    
    fs.write_fat(fat_data)

def delete_directory(fs, entry: dict, recursive: bool = False) -> bool:
    """
    Deletes a directory.

    By default, this fails if the directory is not empty. If `recursive` is
    True, it will first delete all files and subdirectories within it. The
    process involves freeing the cluster chain of the directory and its
    contents, and then marking its entry in the parent directory as deleted.

    Args:
        fs: The FAT12Image filesystem object.
        entry: The dictionary representing the directory to delete.
        recursive: If True, allows deletion of non-empty directories by
                   deleting their contents first.

    Returns:
        True on success, False on failure.
    """
    try:
        # Check if it's actually a directory
        if not entry.get('is_dir', False):
            print("Error: Entry is not a directory")
            return False
        
        # Read directory contents (skip . and ..)
        dir_entries = read_directory(fs, entry['cluster'])
        real_entries = [e for e in dir_entries if e['name'] not in ('.', '..')]
        
        # Check if directory is empty
        if len(real_entries) > 0 and not recursive:
            print("Error: Directory is not empty (use recursive=True to force)")
            return False
        
        # If recursive, delete all contents first
        if recursive and len(real_entries) > 0:
            for sub_entry in real_entries:
                if sub_entry['is_dir']:
                    if not delete_directory(fs, sub_entry, recursive=True):
                        return False
                else:
                    if not delete_entry(fs, sub_entry):
                        return False
        
        # Delete the directory entry itself and free clusters
        return delete_entry(fs, entry)
        
    except Exception as e:
        print(f"Error deleting directory: {e}")
        import traceback
        traceback.print_exc()
        return False

def delete_entry(fs, entry: dict) -> bool:
    """Delete a directory entry (file or directory) and free its clusters"""
    try:
        # Mark entry as deleted
        if not delete_directory_entry(fs, entry.get('parent_cluster'), entry['index']):
            return False
        
        # Free clusters in FAT
        free_cluster_chain(fs, entry['cluster'])
        
        return True
    except Exception as e:
        print(f"Error deleting entry: {e}")
        return False

def rename_entry(fs, entry: dict, new_name: str, use_numeric_tail: bool = False) -> bool:
    """
    Renames a file or directory, handling both LFN and 8.3 name updates.

    This function manages the logic of renaming, which may involve
    changing the number of directory slots required.
    - If the new name requires fewer slots, the existing block is reused and
      surplus slots are marked as deleted.
    - If the new name requires more slots, the old block is deleted and a new,
      larger contiguous block is found to store the new entries.

    It preserves all other metadata like timestamps, cluster, and size.

    Args:
        fs: The FAT12Image filesystem object.
        entry: The dictionary for the file or directory to be renamed.
        new_name: The target long name.
        use_numeric_tail: Toggles the 8.3 name generation algorithm for the
                          new short name.

    Returns:
        True on success, False on failure (e.g., name collision, directory full).
    """
    try:
        # Prepare New Names
        parent_cluster = entry.get('parent_cluster')
        parent_cluster = None if parent_cluster == 0 else parent_cluster
        
        # Check for LFN collision with other files
        entries = read_directory(fs, parent_cluster)
        if any(e['name'].lower() == new_name.lower() and e['index'] != entry['index'] for e in entries):
            print(f"Error: Entry '{new_name}' already exists")
            return False
            
        existing_names = get_existing_83_names_in_directory(fs, parent_cluster)

        with open(fs.image_path, 'rb') as f:
            f.seek(get_entry_offset(fs, parent_cluster, entry['index']))
            current_raw = f.read(DIR_SHORT_NAME_LEN)
            current_name_11 = decode_raw_83_name(current_raw).upper()

        if current_name_11 in existing_names:
            existing_names.remove(current_name_11)

        # Generate and format new 8.3 name (11 bytes raw)
        short_name_11 = generate_83_name(new_name, existing_names, use_numeric_tail)
        
        try:
            raw_short_name = short_name_11.encode('ascii')[:DIR_SHORT_NAME_LEN]
        except UnicodeEncodeError:
            raw_short_name = short_name_11.encode('ascii', 'ignore').ljust(DIR_SHORT_NAME_LEN, b' ')[:DIR_SHORT_NAME_LEN]

        # Generate LFN entries if needed
        base = short_name_11[:8].strip()
        ext = short_name_11[8:].strip()
        simple_name = f"{base}.{ext}" if ext else base

        needs_lfn = (new_name != simple_name) or (len(new_name) > 12)
        new_lfn_entries = []
        if needs_lfn:
            new_lfn_entries = create_lfn_entries(new_name, raw_short_name)

        total_new_slots = len(new_lfn_entries) + 1

        # Analyze Current Location
        old_lfn_indices = []
        idx = entry['index'] - 1
        fat_data = fs.read_fat()
        
        with open(fs.image_path, 'rb') as f:
            while idx >= 0:
                offset = get_entry_offset(fs, parent_cluster, idx, fat_data)
                if offset == -1: break
                f.seek(offset)
                data = f.read(32)
                if data[DIR_ATTR_OFFSET] == 0x0F: # Attribute 0x0F is LFN
                    old_lfn_indices.append(idx)
                    idx -= 1
                else:
                    break

        current_start_index = old_lfn_indices[-1] if old_lfn_indices else entry['index']
        total_old_slots = len(old_lfn_indices) + 1

        # Read original metadata (Cluster, Size, Dates) to preserve it
        with open(fs.image_path, 'rb') as f:
            f.seek(get_entry_offset(fs, parent_cluster, entry['index'], fat_data))
            original_entry_data = bytearray(f.read(32))
        
        # Determine Write Location
        write_start_index = -1
        slots_to_delete = []

        if total_new_slots <= total_old_slots:
            # CASE A: Fits in current location
            write_start_index = current_start_index
            # Delete only the extra slots we no longer need
            slots_to_delete = range(current_start_index + total_new_slots, current_start_index + total_old_slots)
        else:
            # CASE B: Needs more space -> Find new contiguous block
            write_start_index = find_free_directory_entries(fs, parent_cluster, total_new_slots)

            if write_start_index == -1:
                print("Error: Disk full (root directory entries exhausted)")
                return False

            # We are moving, so delete ALL old slots
            slots_to_delete = range(current_start_index, current_start_index + total_old_slots)

        # Execute Write
        with open(fs.image_path, 'r+b') as f:
            # Mark old/unused slots as deleted (0xE5)
            for i in slots_to_delete:
                offset = get_entry_offset(fs, parent_cluster, i, fat_data)
                f.seek(offset)
                f.write(b'\xE5')
            f.flush()
            os.fsync(f.fileno())

            # Write New LFN Entries
            for i, lfn_data in enumerate(new_lfn_entries):
                offset = get_entry_offset(fs, parent_cluster, write_start_index + i, fat_data)
                f.seek(offset)
                f.write(lfn_data)
            f.flush()
            os.fsync(f.fileno())

            # Write New Short Entry
            new_short_entry = original_entry_data
            new_short_entry[0:DIR_SHORT_NAME_LEN] = raw_short_name # Update 8.3 name

            short_entry_idx = write_start_index + len(new_lfn_entries)
            offset = get_entry_offset(fs, parent_cluster, short_entry_idx, fat_data)
            f.seek(offset)
            f.write(new_short_entry)
            f.flush()
            os.fsync(f.fileno())

        return True

    except Exception as e:
        print(f"Rename Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def predict_short_name(fs, long_name: str, use_numeric_tail: bool = False, parent_cluster: int = None) -> str:
    """
    Predicts the 8.3 short name that will be generated for a given long name.

    This function simulates the 8.3 name generation process, including
    collision detection, without writing anything to the disk. It is useful for
    providing UI feedback before a file is actually created or renamed.

    Args:
        fs: The FAT12Image filesystem object.
        long_name: The long filename to convert.
        use_numeric_tail: Toggles the 8.3 name generation algorithm.
        parent_cluster: The target directory's cluster for collision checking.

    Returns:
        The predicted 11-character 8.3 short name (no dot).
    """
    existing_names = get_existing_83_names_in_directory(fs, parent_cluster)
    return generate_83_name(long_name, existing_names, use_numeric_tail)

def find_entry_by_83_name(fs, target_83_name: str) -> Optional[dict]:
    """Find a directory entry by its 11-character 8.3 name (no dot)"""
    # target_83_name should be 11 chars, space padded, uppercase
    target = target_83_name.upper().ljust(11)[:11]
    
    entries = read_directory(fs, None)
    for entry in entries:
        # Compare against the raw 11-byte name stored in the entry
        raw_name = entry.get('raw_short_name')
        if raw_name and raw_name.upper() == target:
            return entry
    return None

def set_entry_attributes(fs, entry: dict, is_read_only: bool = None, 
                       is_hidden: bool = None, is_system: bool = None, 
                       is_archive: bool = None) -> bool:
    """
    Modify file attributes for a directory entry.
    Reads current attributes from disk to ensure bits like Directory (0x10) are preserved.
    
    Args:
        fs: The FAT12Image filesystem object.
        entry: Directory entry dictionary (must contain 'index' and 'parent_cluster')
        is_read_only: Set read-only flag (None = no change)
        is_hidden: Set hidden flag (None = no change)
        is_system: Set system flag (None = no change)
        is_archive: Set archive flag (None = no change)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(fs.image_path, 'r+b') as f:
            parent_cluster = entry.get('parent_cluster')
            offset = get_entry_offset(fs, parent_cluster, entry['index'])
            if offset == -1:
                print(f"Error: Could not find offset for entry {entry.get('name', 'Unknown')}")
                return False
            
            # Read current attributes from disk
            f.seek(offset + DIR_ATTR_OFFSET)
            current_attr_bytes = f.read(1)
            if len(current_attr_bytes) != 1:
                return False
            
            current_attr = current_attr_bytes[0]
            new_attr = current_attr
            
            # Modify flags as requested (only if not None)
            if is_read_only is not None:
                if is_read_only: new_attr |= 0x01
                else: new_attr &= ~0x01
            if is_hidden is not None:
                if is_hidden: new_attr |= 0x02
                else: new_attr &= ~0x02
            if is_system is not None:
                if is_system: new_attr |= 0x04
                else: new_attr &= ~0x04
            if is_archive is not None:
                if is_archive: new_attr |= 0x20
                else: new_attr &= ~0x20
            
            # Write back if changed
            if new_attr != current_attr:
                f.seek(offset + DIR_ATTR_OFFSET)
                f.write(bytes([new_attr]))
                f.flush()
                os.fsync(f.fileno())
                
        return True
    except Exception as e:
        print(f"Error setting file attributes: {e}")
        return False