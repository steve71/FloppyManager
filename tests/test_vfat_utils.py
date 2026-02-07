import pytest
import datetime
import struct
from vfat_utils import (
    decode_fat_time, decode_fat_date, 
    encode_fat_time, encode_fat_date,
    generate_83_name, is_valid_83_char,
    calculate_lfn_checksum, create_lfn_entries,
    parse_raw_lfn_entry, parse_raw_short_entry,
    decode_lfn_text, decode_short_name,
    format_83_name, get_raw_entry_chain,
    decode_raw_83_name
)

class TestTimeDate:
    def test_fat_time_conversion(self):
        # 10:30:10 -> (10 << 11) | (30 << 5) | (5)
        time_val = (10 << 11) | (30 << 5) | 5
        assert decode_fat_time(time_val) == "10:30:10"
        
        dt = datetime.datetime(2023, 1, 1, 10, 30, 10)
        assert encode_fat_time(dt) == time_val

    def test_fat_date_conversion(self):
        # 2023-10-25 -> ((2023-1980) << 9) | (10 << 5) | 25
        date_val = ((2023-1980) << 9) | (10 << 5) | 25
        assert decode_fat_date(date_val) == "2023-10-25"
        
        dt = datetime.datetime(2023, 10, 25)
        assert encode_fat_date(dt) == date_val

    def test_invalid_date(self):
        assert decode_fat_date(0) == "Invalid" # Month 0 is invalid

    def test_fat_date_boundaries(self):
        # Min date: 1980-01-01
        min_val = ((1980-1980) << 9) | (1 << 5) | 1
        assert decode_fat_date(min_val) == "1980-01-01"
        
        # Max date: 2107-12-31 (Year 127)
        max_val = (127 << 9) | (12 << 5) | 31
        assert decode_fat_date(max_val) == "2107-12-31"

    def test_fat_time_precision(self):
        # FAT stores seconds/2, so odd seconds lose precision
        # 10:00:01 -> 10:00:00
        dt = datetime.datetime(2023, 1, 1, 10, 0, 1)
        encoded = encode_fat_time(dt)
        decoded = decode_fat_time(encoded)
        assert decoded == "10:00:00"

    def test_decode_fat_date_invalid_day_month(self):
        # Month 13
        invalid_month = ((2023-1980) << 9) | (13 << 5) | 1
        assert decode_fat_date(invalid_month) == "Invalid"
        # Day 32
        invalid_day = ((2023-1980) << 9) | (1 << 5) | 32
        assert decode_fat_date(invalid_day) == "Invalid"
        # Day 0
        invalid_day_zero = ((2023-1980) << 9) | (1 << 5) | 0
        assert decode_fat_date(invalid_day_zero) == "Invalid"

class Test83NameGeneration:
    def test_83_name_generation(self):
        # Long name conversion (typical Windows behavior)
        long_name = "ThisIsALongFileName.txt"
        short_name = generate_83_name(long_name, use_numeric_tail=True)
        assert short_name == "THISIS~1TXT"
        assert len(short_name) <= 12
        assert "~1" in short_name
        short_name = generate_83_name(long_name, use_numeric_tail=False)
        assert short_name == "THISISALTXT"
        # check spaces are removed
        long_name = "This Is A Long File Name.txt"
        short_name = generate_83_name(long_name, use_numeric_tail=True)
        assert short_name == "THISIS~1TXT"
        long_name = "MY_ONE.MI"
        short_name = generate_83_name(long_name, use_numeric_tail=False)
        # names are generated in a strict 8.3 format:
        # always 11 bytes, filename with 8 bytes even if long file name is shorter
        # dot removed and extension with 3 bytes even if extension is shorter
        assert short_name == "MY_ONE  MI "

    def test_83_name_collision(self):
        # Test collision handling with numeric tails
        # Existing names must be in 11-byte format (no dot)
        existing = ["FILE    TXT", "FILE~1  TXT"]
        
        # Should generate FILE~2.TXT -> "FILE~2  TXT"
        name = generate_83_name("File.txt", existing, use_numeric_tail=True)
        assert name == "FILE~2  TXT"

    def test_is_valid_83_char(self):
        assert is_valid_83_char("A")
        assert is_valid_83_char("1")
        assert is_valid_83_char("#")
        assert not is_valid_83_char(".")
        assert not is_valid_83_char(" ")
        assert not is_valid_83_char("*")
        assert not is_valid_83_char("?")
        # Non-ASCII check
        assert not is_valid_83_char("é")

    def test_83_name_special_cases(self):
        # Multiple dots: archive.tar.gz -> ARCHIVET.GZ
        name = generate_83_name("archive.tar.gz")
        assert name == "ARCHIVETGZ "
        
        # Leading dot: .gitignore -> GITIGNOR
        name = generate_83_name(".gitignore")
        assert name == "GITIGNOR   "

    def test_numeric_tail_rollover(self):
        # Test transition from ~9 (6 chars base) to ~10 (5 chars base)
        # We must include the base name "FILE.TXT" in existing, otherwise it returns that
        existing = ["FILE    TXT"] + [f"FILE~{i}  TXT" for i in range(1, 10)]
        
        name = generate_83_name("File.txt", existing, use_numeric_tail=True)
        assert name == "FILE~10 TXT"

    def test_numeric_tail_rollover_large(self):
        # Test transition from ~99 to ~100
        existing = ["FILE    TXT"]
        for i in range(1, 100):
            # Ensure correct padding: FILE~1 needs 2 spaces, FILE~10 needs 1 space
            existing.append(f"FILE~{i}".ljust(8) + "TXT")
        
        name = generate_83_name("File.txt", existing, use_numeric_tail=True)
        # Base name shrinks from 5 to 4 chars
        assert name == "FILE~100TXT"
    
    def test_generate_83_name_large_tail_1000(self):
        # Test transition to ~1000 (3 chars base)
        # We simulate existing names up to ~999
        existing = ["FILE    TXT"]
        for i in range(1, 1000):
            # Ensure correct padding for existing names
            base = f"FILE~{i}".ljust(8)
            existing.append(f"{base}TXT")
        
        name = generate_83_name("File.txt", existing, use_numeric_tail=True)
        # Base name shrinks from 4 to 3 chars: FIL~1000.TXT -> FIL~1000TXT
        assert name == "FIL~1000TXT"

    def test_generate_83_name_with_invalid_chars(self):
        # These characters are invalid and should be stripped
        name = generate_83_name("my file+[].txt")
        assert name == "MYFILE  TXT"

    def test_generate_83_name_degenerate(self):
        # Filename that strips down to empty string
        # "..." -> stem "...", suffix "" -> strip -> ""
        # With numeric tail, should generate ~1
        name = generate_83_name("...", use_numeric_tail=True)
        assert name.strip() == "~1"
        
        # Without numeric tail, results in spaces (technically valid return for the function)
        name = generate_83_name("...", use_numeric_tail=False)
        assert name == "           "

    def test_generate_83_name_exact_match(self):
        # Filename that is exactly 8.3 but mixed case
        name = generate_83_name("FileName.Ext")
        assert name == "FILENAMEEXT"

    def test_generate_83_name_no_extension(self):
        name = generate_83_name("MAKEFILE")
        assert name == "MAKEFILE   "

class TestLFN:
    def test_calculate_lfn_checksum(self):
        # Checksum for "FILE    TXT"
        # Simple regression test for the algorithm
        short_name = b"FILE    TXT"
        chk = calculate_lfn_checksum(short_name)
        assert isinstance(chk, int)
        assert 0 <= chk <= 255

    def test_create_lfn_entries(self):
        long_name = "LongFileName.txt"
        short_name = b"LONGFIL~1TXT"
        entries = create_lfn_entries(long_name, short_name)
        
        # "LongFileName.txt" is 16 chars -> needs 2 LFN entries (13 chars each)
        assert len(entries) == 2
        
        # Verify last entry (which is first in the list because they are reversed)
        # has the 0x40 bit set in the sequence number
        assert entries[0][0] & 0x40

    def test_lfn_entry_boundaries(self):
        short = b"123456  123"
        
        # 12 chars -> 24 bytes + 2 null = 26 bytes -> 1 entry
        lfn_12 = "1" * 12
        entries = create_lfn_entries(lfn_12, short)
        assert len(entries) == 1
        
        # 13 chars -> 26 bytes + 2 null = 28 bytes -> 2 entries
        lfn_13 = "1" * 13
        entries = create_lfn_entries(lfn_13, short)
        assert len(entries) == 2

    def test_lfn_unicode(self):
        # Unicode characters
        lfn = "👍.txt" 
        short = b"__      TXT"
        entries = create_lfn_entries(lfn, short)
        assert len(entries) > 0

    def test_lfn_padding_and_checksum(self):
        long_name = "A"
        short_name = b"A       TXT" 
        entries = create_lfn_entries(long_name, short_name)
        
        assert len(entries) == 1
        entry = entries[0]
        
        # Checksum verification
        expected_chk = calculate_lfn_checksum(short_name)
        assert entry[13] == expected_chk
        
        # Padding verification (0xFF)
        # "A" (2 bytes) + Null (2 bytes) = 4 bytes used
        # Entry has 26 bytes for name chars. 22 bytes padding.
        # chars1 (10 bytes) -> 4 bytes used, 6 bytes padding
        assert entry[5:11] == b'\xff' * 6
        # chars2 (12 bytes) -> all padding
        assert entry[14:26] == b'\xff' * 12
        # chars3 (4 bytes) -> all padding
        assert entry[28:32] == b'\xff' * 4

class TestRawEntryParsing:
    def test_parse_raw_short_entry(self):
        # Create a mock 32-byte short entry
        # Filename: "TEST    TXT" (11 bytes)
        # Attr: 0x20 (Archive)
        # Reserved: 0x00
        # Time/Date: Arbitrary valid values
        # Size: 1024
        
        entry = bytearray(32)
        entry[0:11] = b"TEST    TXT"
        entry[11] = 0x20
        entry[28:32] = struct.pack('<I', 1024)
        
        info = parse_raw_short_entry(entry)
        
        assert info['filename'] == "TEST    TXT"
        assert info['attr'] == 0x20
        assert "ARC" in info['attr_str']
        assert info['file_size'] == 1024
        assert info['creation_date_str'] == "Invalid" # Default 0 is invalid

    def test_parse_raw_lfn_entry(self):
        # Create a mock LFN entry
        # Seq: 0x41 (Last, index 1)
        # Name: "A" (UTF-16LE: 0x41 0x00)
        
        entry = bytearray(32)
        entry[0] = 0x41
        entry[1:3] = b'A\x00' # First char
        entry[11] = 0x0F # LFN Attr
        
        info = parse_raw_lfn_entry(entry)
        
        assert info['seq_num'] == 1
        assert info['is_last'] is True
        assert info['attr'] == 0x0F
        assert info['text1'].startswith('A')

class TestNameDecoding:
    def test_decode_lfn_text(self):
        # Create a mock LFN entry with "ABC"
        entry = bytearray(32)
        # Chars 1-5 (bytes 1-11)
        entry[1:7] = b'A\x00B\x00C\x00'
        entry[7:9] = b'\x00\x00' # Null terminator
        entry[9:11] = b'\xFF\xFF' # Padding
        # Chars 6-11 (bytes 14-26) - all padding
        entry[14:26] = b'\xFF' * 12
        # Chars 12-13 (bytes 28-32) - all padding
        entry[28:32] = b'\xFF' * 4
        
        text = decode_lfn_text(entry)
        assert text == "ABC"
        
    def test_decode_lfn_text_exception(self):
        # Pass truncated data to cause odd-length bytearray which fails utf-16le decode
        data = b'\x00\x41' # 2 bytes. entry_data[1:11] slice will be 1 byte.
        assert decode_lfn_text(data) is None

    def test_parse_raw_lfn_entry_exception(self):
        # Similar to above, force exception in decoding inside parse_raw_lfn_entry
        # We use invalid UTF-16LE data (lone high surrogate) to trigger exception
        data = bytearray(32)
        data[0] = 0x41
        data[11] = 0x0F
        # Put lone high surrogate at end of chars1 (indices 9-10 of entry_data)
        data[9] = 0x00
        data[10] = 0xD8
        
        info = parse_raw_lfn_entry(data)
        # Should return '???' for text fields on exception
        assert info['text1'] == '???'

    def test_decode_raw_83_name(self):
        # Standard name
        assert decode_raw_83_name(b"FILE    TXT") == "FILE    TXT"
        
        # 0x05 handling (Shift-JIS 0xE5 marker)
        # 0x05 -> 0xE5. 
        data = b"\x05BCDEFGHTXT"
        # With errors='ignore', 0xE5 (non-ASCII) is dropped.
        assert decode_raw_83_name(data, errors='ignore') == "BCDEFGHTXT"
        
        # With errors='replace' (default), 0xE5 becomes the replacement char ''
        assert decode_raw_83_name(data) == "\uFFFDBCDEFGHTXT"

    def test_decode_short_name(self):
        # Test standard name
        entry = bytearray(32)
        entry[0:11] = b"FILE    TXT"
        assert decode_short_name(entry) == ("FILE", "TXT")
        
        # Test Shift-JIS 0x05 fix
        entry[0] = 0x05
        entry[1:8] = b"ILENAME"
        # Should decode 0x05 as 0xE5, but ascii ignore drops it?
        # Wait, decode_short_name uses errors='ignore'. 
        # 0xE5 is not ASCII. So it will be dropped.
        # "ILENAME"
        name, ext = decode_short_name(entry)
        assert name == "ILENAME"

class TestFormatting:
    def test_format_83_name(self):
        assert format_83_name("FILE    TXT") == "FILE.TXT"
        assert format_83_name("NOEXT      ") == "NOEXT"
        assert format_83_name("A       B  ") == "A.B"
        assert format_83_name("SHORT") == "SHORT" # Less than 11 chars
        assert format_83_name("") == ""

class TestEntryChains:
    def test_get_raw_entry_chain(self):
        # Mock entries
        # 0: LFN 1
        # 1: LFN 2
        # 2: Short Entry (Target)
        # 3: Unrelated
        
        raw_entries = []
        
        # Entry 0: LFN
        e0 = bytearray(32)
        e0[11] = 0x0F
        raw_entries.append((0, bytes(e0)))
        
        # Entry 1: LFN
        e1 = bytearray(32)
        e1[11] = 0x0F
        raw_entries.append((1, bytes(e1)))
        
        # Entry 2: Short
        e2 = bytearray(32)
        e2[11] = 0x20
        raw_entries.append((2, bytes(e2)))
        
        # Entry 3: Short
        e3 = bytearray(32)
        e3[11] = 0x20
        raw_entries.append((3, bytes(e3)))
        
        # Test finding chain for index 2
        chain = get_raw_entry_chain(raw_entries, 2)
        assert len(chain) == 3
        assert chain[0][0] == 0
        assert chain[1][0] == 1
        assert chain[2][0] == 2
        
        # Test finding chain for index 3 (no LFNs before it, just itself)
        chain = get_raw_entry_chain(raw_entries, 3)
        assert len(chain) == 1
        assert chain[0][0] == 3
        
        # Test invalid index
        assert get_raw_entry_chain(raw_entries, 99) == []
        assert get_raw_entry_chain(raw_entries, -1) == []


class TestFilenameSplitting:
    def test_split_filename_for_editing(self):
        from vfat_utils import split_filename_for_editing
        
        # Standard file with extension
        full, start, end = split_filename_for_editing("document.txt")
        assert full == "document.txt"
        assert start == 0
        assert end == 8
        assert full[start:end] == "document"
        
        # Multiple dots - select up to last dot
        full, start, end = split_filename_for_editing("archive.tar.gz")
        assert full == "archive.tar.gz"
        assert start == 0
        assert end == 11
        assert full[start:end] == "archive.tar"
        
        # No extension
        full, start, end = split_filename_for_editing("README")
        assert full == "README"
        assert start == 0
        assert end == 6
        assert full[start:end] == "README"
        
        # Dotfile (Unix hidden file) - select all
        full, start, end = split_filename_for_editing(".gitignore")
        assert full == ".gitignore"
        assert start == 0
        assert end == 10
        assert full[start:end] == ".gitignore"
        
        # Edge cases
        full, start, end = split_filename_for_editing(".")
        assert full == "."
        assert start == 0
        assert end == 1
        
        full, start, end = split_filename_for_editing("..")
        assert full == ".."
        assert start == 0
        assert end == 2
        
        # Empty string
        full, start, end = split_filename_for_editing("")
        assert full == ""
        assert start == 0
        assert end == 0
