import datetime
from pathlib import Path
from typing import List

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
