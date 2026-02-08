#!/usr/bin/env python3
"""Simple test runner for file attributes functionality"""

import sys
import tempfile
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fat12_handler import FAT12Image

def test_set_read_only_attribute():
    """Test setting read-only attribute"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        img_path = Path(tmp_dir) / "test.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("TESTFILE.TXT", test_data), "Failed to add file"
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "TESTFILE.TXT")
        
        # Initially should not be read-only
        assert not entry['is_read_only'], "File should not be read-only initially"
        assert entry['attributes'] == 0x20, "Archive bit only should be set"
        
        # Set read-only
        assert handler.set_file_attributes(entry, is_read_only=True), "Failed to set read-only"
        
        # Verify it was set
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "TESTFILE.TXT")
        assert entry['is_read_only'], "File should be read-only"
        assert entry['attributes'] & 0x01, "Read-only bit should be set"
        assert entry['attributes'] & 0x20, "Archive bit should still be set"
        
        # Clear read-only
        assert handler.set_file_attributes(entry, is_read_only=False), "Failed to clear read-only"
        
        # Verify it was cleared
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "TESTFILE.TXT")
        assert not entry['is_read_only'], "File should not be read-only"
        assert not (entry['attributes'] & 0x01), "Read-only bit should be cleared"
        assert entry['attributes'] & 0x20, "Archive bit should still be set"
    
    print("✓ test_set_read_only_attribute passed")

def test_set_hidden_attribute():
    """Test setting hidden attribute"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        img_path = Path(tmp_dir) / "test.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("HIDDEN.TXT", test_data), "Failed to add file"
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "HIDDEN.TXT")
        
        # Initially should not be hidden
        assert not entry['is_hidden'], "File should not be hidden initially"
        
        # Set hidden
        assert handler.set_file_attributes(entry, is_hidden=True), "Failed to set hidden"
        
        # Verify it was set
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "HIDDEN.TXT")
        assert entry['is_hidden'], "File should be hidden"
        assert entry['attributes'] & 0x02, "Hidden bit should be set"
        
        # Clear hidden
        assert handler.set_file_attributes(entry, is_hidden=False), "Failed to clear hidden"
        
        # Verify it was cleared
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "HIDDEN.TXT")
        assert not entry['is_hidden'], "File should not be hidden"
        assert not (entry['attributes'] & 0x02), "Hidden bit should be cleared"
    
    print("✓ test_set_hidden_attribute passed")

def test_set_multiple_attributes():
    """Test setting multiple attributes at once"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        img_path = Path(tmp_dir) / "test.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("MULTI.TXT", test_data), "Failed to add file"
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "MULTI.TXT")
        
        # Set multiple attributes at once
        result = handler.set_file_attributes(
            entry, 
            is_read_only=True, 
            is_hidden=True, 
            is_system=True
        )
        assert result, "Failed to set multiple attributes"
        
        # Verify all were set
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "MULTI.TXT")
        assert entry['is_read_only'], "Read-only should be set"
        assert entry['is_hidden'], "Hidden should be set"
        assert entry['is_system'], "System should be set"
        assert entry['is_archive'], "Archive should still be set"
        
        # Verify the raw attribute byte
        expected_attr = 0x01 | 0x02 | 0x04 | 0x20  # R+H+S+A
        assert entry['attributes'] == expected_attr, f"Expected {expected_attr:02X}, got {entry['attributes']:02X}"
    
    print("✓ test_set_multiple_attributes passed")

def test_partial_attribute_update():
    """Test updating only some attributes (None means no change)"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        img_path = Path(tmp_dir) / "test.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("PARTIAL.TXT", test_data), "Failed to add file"
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "PARTIAL.TXT")
        
        # Set read-only and hidden
        assert handler.set_file_attributes(entry, is_read_only=True, is_hidden=True), "Failed to set attributes"
        
        # Now only change archive, leaving read-only and hidden alone
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "PARTIAL.TXT")
        assert handler.set_file_attributes(entry, is_archive=False), "Failed to clear archive"
        
        # Verify read-only and hidden are still set, but archive is cleared
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "PARTIAL.TXT")
        assert entry['is_read_only'], "Read-only should still be set"
        assert entry['is_hidden'], "Hidden should still be set"
        assert not entry['is_archive'], "Archive should be cleared"
        assert not entry['is_system'], "System should not be set"
    
    print("✓ test_partial_attribute_update passed")

def test_attributes_with_long_filename():
    """Test that attributes work correctly with files that have LFN entries"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        img_path = Path(tmp_dir) / "test.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Add a file with a long name that needs LFN entries
        test_data = b"Test file content"
        long_name = "This is a very long filename.txt"
        assert handler.write_file_to_image(long_name, test_data), "Failed to add file with long name"
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == long_name)
        
        # Set attributes
        assert handler.set_file_attributes(entry, is_read_only=True, is_hidden=True), "Failed to set attributes"
        
        # Verify attributes are set correctly
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == long_name)
        assert entry['is_read_only'], "Read-only should be set"
        assert entry['is_hidden'], "Hidden should be set"
        
        # Verify the file can still be read correctly
        assert len(entries) > 0, "Should have entries"
        assert entry['name'] == long_name, "Name should match"
    
    print("✓ test_attributes_with_long_filename passed")

if __name__ == "__main__":
    print("Running file attributes tests...")
    print()
    
    try:
        test_set_read_only_attribute()
        test_set_hidden_attribute()
        test_set_multiple_attributes()
        test_partial_attribute_update()
        test_attributes_with_long_filename()
        
        print()
        print("=" * 50)
        print("All tests passed! ✓")
        print("=" * 50)
    except AssertionError as e:
        print()
        print("=" * 50)
        print(f"Test failed: {e}")
        print("=" * 50)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 50)
        print(f"Error running tests: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 50)
        sys.exit(1)
