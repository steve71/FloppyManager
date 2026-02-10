# Copyright (c) 2026 Stephen P Smith
# MIT License

import struct
import datetime
from pathlib import Path
from typing import List, Tuple, Optional

def decode_fat_time(time_value: int) -> str:
    """Decode FAT time format to HH:MM:SS string

    Bits 15-11: Hours (0-23)
    Bits 10-5: Minutes (0-59)
    Bits 4-0: Seconds/2 (0-29, multiply by 2 to get actual seconds)
    """
    hours = (time_value >> 11) & 0x1F
    minutes = (time_value >> 5) & 0x3F
    seconds = (time_value & 0x1F) * 2
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def decode_fat_date(date_value: int) -> str:
    """Decode FAT date format to YYYY-MM-DD string

    Bits 15-9: Year (0 = 1980, 127 = 2107)
    Bits 8-5: Month (1-12)
    Bits 4-0: Day (1-31)
    """
    year = ((date_value >> 9) & 0x7F) + 1980
    month = (date_value >> 5) & 0x0F
    day = date_value & 0x1F

    # Handle invalid dates
    if month < 1 or month > 12 or day < 1 or day > 31:
        return "Invalid"

    return f"{year:04d}-{month:02d}-{day:02d}"


def decode_fat_datetime(date_value: int, time_value: int) -> Optional[datetime.datetime]:
    """Decode FAT date and time values into a datetime object"""
    year = ((date_value >> 9) & 0x7F) + 1980
    month = (date_value >> 5) & 0x0F
    day = date_value & 0x1F
    
    hour = (time_value >> 11) & 0x1F
    minute = (time_value >> 5) & 0x3F
    second = (time_value & 0x1F) * 2
    
    try:
        return datetime.datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None

def encode_fat_time(dt: datetime.datetime) -> int:
    """Encode datetime to FAT time format"""
    return (dt.hour << 11) | (dt.minute << 5) | (dt.second // 2)


def encode_fat_date(dt: datetime.datetime) -> int:
    """Encode datetime to FAT date format"""
    return ((dt.year - 1980) << 9) | (dt.month << 5) | dt.day


def is_valid_83_char(char: str) -> bool:
    """Check if character is valid in 8.3 filename (Windows compatible)"""
    # Valid characters: A-Z, 0-9, and special chars
    # Windows allows: ! # $ % & ' ( ) - @ ^ _ ` { } ~
    # Windows does NOT allow: space + , . ; = [ ]
    if char.isalnum() and char.isascii():
        return True
    valid_special = "!#$%&'()-@^_`{}~"
    return char in valid_special


def generate_83_name(
    long_name: str, existing_names: List[str] = None, use_numeric_tail: bool = False
) -> str:
    """Generate a valid 8.3 filename from a long filename (Windows-compatible behavior)

    Windows 8.3 name generation algorithm:
    1. Convert to uppercase
    2. Remove leading/trailing spaces and dots
    3. Replace invalid characters with nothing (remove them)
    4. Remove all embedded spaces
    5. Truncate base name to fit with ~N tail if needed
    6. Keep first 3 chars of extension

    Args:
        long_name: The original long filename
        existing_names: List of existing 8.3 names to avoid collisions (11-byte format)
        use_numeric_tail: Whether to use numeric tails (~1, ~2, etc.) for uniqueness

    Returns:
        Valid 8.3 filename (11 bytes, no dot)
    """
    if existing_names is None:
        existing_names = []

    # Split name and extension
    path_obj = Path(long_name)
    name = path_obj.stem
    ext = path_obj.suffix.lstrip(".")

    # Convert to uppercase
    name = name.upper()
    ext = ext.upper()

    # Remove leading and trailing spaces/dots
    name = name.strip(" .")
    ext = ext.strip(" .")

    # Remove invalid characters (including spaces)
    name = "".join(c for c in name if is_valid_83_char(c))
    ext = "".join(c for c in ext if is_valid_83_char(c))

    # Take first 3 characters of extension
    ext = ext[:3]

    # Check if original name is already valid 8.3
    # Valid 8.3 means:
    # - 8 or fewer chars in base name
    # - 3 or fewer chars in extension
    # - No invalid characters
    # - No spaces
    original_name_upper = path_obj.stem.upper()
    original_ext_upper = path_obj.suffix.lstrip(".").upper()

    is_already_valid_83 = (
        1 <= len(original_name_upper) <= 8
        and 0 <= len(original_ext_upper) <= 3
        and " " not in original_name_upper
        and " " not in original_ext_upper
        and "." not in original_name_upper
        and "." not in original_ext_upper
        and all(is_valid_83_char(c) for c in original_name_upper)
        and all(is_valid_83_char(c) for c in original_ext_upper)
    )

    if is_already_valid_83:
        # Just uppercase and pad - no numeric tail needed
        base_name = original_name_upper[:8].ljust(8)
        ext_name = original_ext_upper[:3].ljust(3)
        candidate = base_name + ext_name
        if candidate not in existing_names or not use_numeric_tail:
            return candidate

    # Name needs modification
    if not use_numeric_tail:
        # Simple truncation without numeric tail (like Linux mount -o nonumtail)
        base_name = name[:8].ljust(8)
        ext_name = ext.ljust(3)
        return base_name + ext_name

    # Windows-style numeric tail generation
    # Windows uses first 6 chars + ~1, then tries ~2, ~3, etc.
    # For ~10 and higher, it uses 5 chars + ~10, etc.

    # Try different tail numbers
    for tail_num in range(1, 1000000):
        tail = f"~{tail_num}"

        # Calculate how many chars we can use from base name
        if tail_num < 10:
            # ~1 through ~9: use 6 chars + ~N = 8 chars total
            max_base_chars = 6
        elif tail_num < 100:
            # ~10 through ~99: use 5 chars + ~NN = 8 chars total
            max_base_chars = 5
        elif tail_num < 1000:
            # ~100 through ~999: use 4 chars + ~NNN = 8 chars total
            max_base_chars = 4
        else:
            # ~1000 and up: use 3 chars + ~NNNN = 8 chars total
            max_base_chars = 3

        # Truncate base to fit
        truncated_base = name[:max_base_chars]
        candidate_base = (truncated_base + tail).ljust(8)
        candidate_ext = ext.ljust(3)
        candidate = candidate_base + candidate_ext

        if candidate not in existing_names:
            return candidate

    # Fallback (should never reach here in practice)
    return name[:8].ljust(8) + ext.ljust(3)


def calculate_lfn_checksum(short_name: bytes) -> int:
    """Calculate checksum for LFN entries

    Args:
        short_name: 11-byte short filename (8.3 format, no dot)

    Returns:
        Checksum byte
    """
    checksum = 0
    for byte in short_name:
        checksum = ((checksum >> 1) | (checksum << 7)) & 0xFF
        checksum = (checksum + byte) & 0xFF
    return checksum


def create_lfn_entries(long_name: str, short_name: bytes) -> List[bytes]:
    """Create LFN (Long File Name) directory entries

    Args:
        long_name: The long filename
        short_name: The 8.3 short name (11 bytes, no dot)

    Returns:
        List of 32-byte LFN entries (in reverse order, ready to write)
    """
    checksum = calculate_lfn_checksum(short_name)

    # Encode to UTF-16LE
    lfn_unicode = long_name.encode("utf-16le")

    # Add null terminator
    lfn_unicode += b"\x00\x00"

    # Pad with 0xFF to make it a multiple of 26 bytes
    remainder = len(lfn_unicode) % 26
    if remainder != 0:
        lfn_unicode += b"\xff\xff" * ((26 - remainder) // 2)

    # Split into 13-character chunks (26 bytes each)
    entries = []
    num_entries = len(lfn_unicode) // 26

    for i in range(num_entries):
        entry = bytearray(32)

        # Sequence number (last entry has 0x40 OR'd)
        # seq = num_entries - i
        # if i == 0:
        #     seq |= 0x40  # Mark as last LFN entry
        seq = i + 1
        if i == num_entries - 1:
            seq |= 0x40

        entry[0] = seq

        # Get this chunk's characters (26 bytes = 13 UTF-16 chars)
        chunk_start = i * 26
        chunk = lfn_unicode[chunk_start : chunk_start + 26]

        # Characters 1-5 (bytes 1-10)
        entry[1:11] = chunk[0:10]

        # Attribute (0x0F = LFN)
        entry[11] = 0x0F

        # Type (0 = sub-component of long name)
        entry[12] = 0

        # Checksum
        entry[13] = checksum

        # Characters 6-11 (bytes 14-25)
        entry[14:26] = chunk[10:22]

        # First cluster (always 0 for LFN)
        entry[26:28] = b"\x00\x00"

        # Characters 12-13 (bytes 28-31)
        entry[28:32] = chunk[22:26]

        entries.append(bytes(entry))

    # Return in reverse order (LFN entries are written before the short entry)
    return list(reversed(entries))


def parse_raw_lfn_entry(entry_data: bytes) -> dict:
    """Parse a raw 32-byte LFN entry into a dictionary of fields"""
    seq = entry_data[0]
    is_last = (seq & 0x40) != 0
    seq_num = seq & 0x1F
    checksum = entry_data[13]
    lfn_type = entry_data[12]
    first_cluster = struct.unpack('<H', entry_data[26:28])[0]
    attr = entry_data[11]
    
    chars1 = entry_data[1:11]
    chars2 = entry_data[14:26]
    chars3 = entry_data[28:32]
    
    try:
        text1 = chars1.decode('utf-16le').replace('\x00', '∅').replace('\uffff', '█')
        text2 = chars2.decode('utf-16le').replace('\x00', '∅').replace('\uffff', '█')
        text3 = chars3.decode('utf-16le').replace('\x00', '∅').replace('\uffff', '█')
    except:
        text1 = '???'
        text2 = '???'
        text3 = '???'
        
    return {
        'seq': seq,
        'seq_num': seq_num,
        'is_last': is_last,
        'checksum': checksum,
        'lfn_type': lfn_type,
        'first_cluster': first_cluster,
        'attr': attr,
        'chars1_hex': ' '.join(f'{b:02X}' for b in chars1),
        'chars2_hex': ' '.join(f'{b:02X}' for b in chars2),
        'chars3_hex': ' '.join(f'{b:02X}' for b in chars3),
        'text1': text1,
        'text2': text2,
        'text3': text3
    }


def decode_raw_83_name(entry_data: bytes, errors: str = 'replace') -> str:
    """Decode raw 11-byte 8.3 name, handling 0x05 lead byte"""
    raw = list(entry_data[0:11])
    if raw[0] == 0x05:
        raw[0] = 0xE5
    return bytes(raw).decode('ascii', errors=errors)


def parse_raw_short_entry(entry_data: bytes) -> dict:
    """Parse a raw 32-byte short (8.3) entry into a dictionary of fields"""
    # Use decode_raw_83_name to handle 0x05 fix, use 'replace' for display
    name = decode_raw_83_name(entry_data, errors='replace')
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
    
    return {
        'name': name,
        'attr': attributes,
        'attr_str': attr_str,
        'reserved': reserved,
        'creation_time_tenth': creation_time_tenth,
        'creation_time_str': decode_fat_time(creation_time),
        'creation_date_str': decode_fat_date(creation_date),
        'last_access_date_str': decode_fat_date(last_access_date),
        'first_cluster_high': first_cluster_high,
        'last_modified_time_str': decode_fat_time(last_modified_time),
        'last_modified_date_str': decode_fat_date(last_modified_date),
        'first_cluster_low': first_cluster_low,
        'file_size': file_size
    }


def decode_lfn_text(entry_data: bytes) -> Optional[str]:
    """Extract and decode the UTF-16LE text from a raw LFN entry"""
    chars = bytearray()
    chars.extend(entry_data[1:11])   # First 5 chars (10 bytes)
    chars.extend(entry_data[14:26])  # Next 6 chars (12 bytes)
    chars.extend(entry_data[28:32])  # Last 2 chars (4 bytes)
    
    try:
        text = chars.decode('utf-16le')
        # Stop at null terminator or 0xFF padding
        null_pos = text.find('\x00')
        if null_pos != -1:
            text = text[:null_pos]
        text = text.replace('\uffff', '')  # Remove 0xFFFF padding
        return text
    except:
        return None


def decode_short_name(entry_data: bytes) -> Tuple[str, str]:
    """Decode 8.3 filename from entry data, handling 0x05 lead byte"""
    raw_name = list(entry_data[0:8])
    if raw_name[0] == 0x05:
        raw_name[0] = 0xE5
    name = bytes(raw_name).decode('ascii', errors='ignore').strip()
    ext = entry_data[8:11].decode('ascii', errors='ignore').strip()
    return name, ext


def format_83_name(raw_name_11: str) -> str:
    """Format an 11-character raw 8.3 name (e.g. 'FILE    TXT') to display format ('FILE.TXT')"""
    if len(raw_name_11) < 11:
        return raw_name_11.strip()
        
    name = raw_name_11[:8].strip()
    ext = raw_name_11[8:11].strip()
    
    if ext:
        return f"{name}.{ext}"
    return name


def get_raw_entry_chain(raw_entries: List[Tuple[int, bytes]], target_index: int) -> List[Tuple[int, bytes]]:
    """
    Given a list of raw directory entries and the index of a short entry,
    return the list of related entries (LFN entries + the short entry)
    in order (LFNs first, then short).
    """
    if target_index < 0 or target_index >= len(raw_entries):
        return []
        
    chain = [raw_entries[target_index]]
    
    # Walk backwards to find LFN entries
    for i in range(target_index - 1, -1, -1):
        idx, data = raw_entries[i]
        attr = data[11]
        if attr == 0x0F:
            chain.insert(0, (idx, data))
        else:
            break
            
    return chain


def split_filename_for_editing(filename: str) -> Tuple[str, int, int]:
    """Split filename into parts for inline editing (Windows-style).
    
    Returns (full_name, selection_start, selection_end) where:
    - full_name is the complete filename
    - selection_start is the index where to start selection (0)
    - selection_end is the index where to end selection (before extension if present)
    
    Windows behavior:
    - "document.txt" -> select "document" (0, 8)
    - "archive.tar.gz" -> select "archive.tar" (0, 11)
    - "README" -> select "README" (0, 6)
    - ".gitignore" -> select ".gitignore" (0, 10) - special case for dotfiles
    
    Args:
        filename: The filename to split
    
    Returns:
        Tuple of (full_name, start_index, end_index)
    """
    # Handle edge cases
    if not filename or filename == '.' or filename == '..':
        return filename, 0, len(filename)
    
    # Find the last dot
    last_dot_pos = filename.rfind('.')
    
    # If no dot or dot is at the beginning (hidden file in Unix), select all
    if last_dot_pos <= 0:
        return filename, 0, len(filename)
    
    # Select everything before the last dot
    return filename, 0, last_dot_pos
