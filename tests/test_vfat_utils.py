import pytest
import datetime
from vfat_utils import (
    decode_fat_time, decode_fat_date, 
    encode_fat_time, encode_fat_date,
    generate_83_name
)

def test_fat_time_conversion():
    # 10:30:10 -> (10 << 11) | (30 << 5) | (5)
    time_val = (10 << 11) | (30 << 5) | 5
    assert decode_fat_time(time_val) == "10:30:10"
    
    dt = datetime.datetime(2023, 1, 1, 10, 30, 10)
    assert encode_fat_time(dt) == time_val

def test_fat_date_conversion():
    # 2023-10-25 -> ((2023-1980) << 9) | (10 << 5) | 25
    date_val = ((2023-1980) << 9) | (10 << 5) | 25
    assert decode_fat_date(date_val) == "2023-10-25"
    
    dt = datetime.datetime(2023, 10, 25)
    assert encode_fat_date(dt) == date_val

def test_invalid_date():
    assert decode_fat_date(0) == "Invalid" # Month 0 is invalid

def test_83_name_generation():
    # Long name conversion (typical Windows behavior)
    long_name = "ThisIsALongFileName.txt"
    short_name = generate_83_name(long_name, use_numeric_tail=True)
    assert short_name == "THISIS~1TXT"
    assert len(short_name) <= 12
    assert "~1" in short_name
    short_name = generate_83_name(long_name, use_numeric_tail=False)
    assert short_name == "THISISALTXT"