import pytest
import datetime
from vfat_utils import (
    decode_fat_time, decode_fat_date, 
    encode_fat_time, encode_fat_date,
    generate_83_name, is_valid_83_char,
    calculate_lfn_checksum, create_lfn_entries
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
