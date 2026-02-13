import pytest
import datetime
import struct
from unittest.mock import patch
from fat12_handler import FAT12Image
from vfat_utils import decode_fat_date, decode_fat_time, calculate_lfn_checksum
from fat12_directory import FAT12Error, FAT12CorruptionError

@pytest.fixture
def handler():
    # Create instance without running full __init__ to test methods in isolation
    return FAT12Image.__new__(FAT12Image)

@pytest.fixture
def handler(tmp_path):
    img_path = tmp_path / "test.img"
    FAT12Image.create_empty_image(str(img_path))
    return FAT12Image(str(img_path))

class TestInitialization:
    def test_fat12_bit_packing(self, handler):
        # FAT12 stores two 12-bit entries (1.5 bytes each) across 3 bytes
        fat_buffer = bytearray(10)
        
        # Set Cluster 2 to 0xABC and Cluster 3 to 0x123
        handler.set_fat_entry(fat_buffer, 2, 0xABC)
        handler.set_fat_entry(fat_buffer, 3, 0x123)
        
        # Verify values are retrieved correctly despite being packed
        assert handler.get_fat_entry(fat_buffer, 2) == 0xABC
        assert handler.get_fat_entry(fat_buffer, 3) == 0x123

    def test_fat_packing_max_values(self, handler):
        # Test 0xFFF (max value) and 0x000 (min value) boundaries
        fat_buffer = bytearray(6)
        
        handler.set_fat_entry(fat_buffer, 2, 0xFFF)
        handler.set_fat_entry(fat_buffer, 3, 0x000)
        
        assert handler.get_fat_entry(fat_buffer, 2) == 0xFFF
        assert handler.get_fat_entry(fat_buffer, 3) == 0x000
        
        # Swap
        handler.set_fat_entry(fat_buffer, 2, 0x000)
        handler.set_fat_entry(fat_buffer, 3, 0xFFF)
        
        assert handler.get_fat_entry(fat_buffer, 2) == 0x000
        assert handler.get_fat_entry(fat_buffer, 3) == 0xFFF

    def test_boot_sector_initialization(self, handler):
        # Verify the OEM Name from the snippet
        assert "MSDOS5.0" in handler.oem_name
        assert handler.bytes_per_cluster == 512
        assert handler.sectors_per_cluster == 1
        assert handler.reserved_sectors == 1
        assert handler.num_fats == 2
        assert handler.root_entries == 224
        assert handler.total_sectors == 2880
        assert handler.media_descriptor == 0xF0
        assert handler.sectors_per_fat == 9
        assert handler.sectors_per_track == 18
        
        # Verify the FAT type is FAT12
        assert handler.fat_type == "FAT12"
        
        # Verify the FAT is initialized to 0xFF
        fat_data = handler.read_fat()
        assert fat_data[0] == 0xF0
        assert fat_data[1] == 0xFF
        assert fat_data[2] == 0xFF

    def test_fat_type_detection(self, tmp_path):
        # Test FAT16 detection
        img_path_16 = tmp_path / "test_fat16.img"
        # Create a minimal boot sector with enough sectors to be FAT16 (> 4085 clusters)
        with open(img_path_16, 'wb') as f:
            f.write(b'\x00' * 512)
            f.seek(0)
            # Write BPB
            f.seek(11); f.write(struct.pack('<H', 512)) # Bytes per sector
            f.seek(13); f.write(b'\x01')                # Sectors per cluster
            f.seek(14); f.write(struct.pack('<H', 1))  # Reserved sectors
            f.seek(16); f.write(b'\x02')                # Num FATs
            f.seek(17); f.write(struct.pack('<H', 224)) # Root entries
            f.seek(19); f.write(struct.pack('<H', 5000)) # Total sectors (small) -> ~5000 clusters
            f.seek(22); f.write(struct.pack('<H', 9))   # Sectors per FAT
            
        handler = FAT12Image(str(img_path_16))
        assert handler.fat_type == 'FAT16'

        # Test FAT32 detection
        img_path_32 = tmp_path / "test_fat32.img"
        with open(img_path_32, 'wb') as f:
            f.write(b'\x00' * 512)
            f.seek(0)
            # BPB
            f.seek(11); f.write(struct.pack('<H', 512))
            f.seek(13); f.write(b'\x01')
            f.seek(14); f.write(struct.pack('<H', 1))
            f.seek(16); f.write(b'\x02')
            f.seek(17); f.write(struct.pack('<H', 224))
            f.seek(19); f.write(struct.pack('<H', 0))   # Total sectors (small) = 0
            f.seek(32); f.write(struct.pack('<I', 70000)) # Total sectors (large) -> ~70000 clusters
            f.seek(22); f.write(struct.pack('<H', 9))
            
        handler = FAT12Image(str(img_path_32))
        assert handler.fat_type == 'FAT32'

class TestClusterManagement:
    def test_find_free_clusters(self, handler):
        # Request 5 free clusters
        free_clusters = handler.find_free_clusters(5)
        assert len(free_clusters) == 5
        # Clusters start at 2
        assert free_clusters == [2, 3, 4, 5, 6]

    def test_find_all_free_clusters(self, handler):
        # Mark a few clusters as used
        fat = handler.read_fat()
        handler.set_fat_entry(fat, 10, 0xFFF)
        handler.set_fat_entry(fat, 20, 0xFFF)
        handler.write_fat(fat)
        
        # Find all free clusters (count=None)
        all_free = handler.find_free_clusters(count=None)
        
        # Total clusters on a 1.44MB floppy is 2847. We used 2.
        total_clusters = handler.total_data_sectors // handler.sectors_per_cluster
        assert len(all_free) == total_clusters - 2
        assert 10 not in all_free
        assert 20 not in all_free
        assert 2 in all_free

    def test_disk_full_data_area(self, handler):
        # Manually fill the FAT to simulate full disk
        fat_data = handler.read_fat()
        
        # Calculate total clusters available
        non_data_sectors = handler.data_start // handler.bytes_per_sector
        total_data_sectors = handler.total_sectors - non_data_sectors
        total_clusters = total_data_sectors // handler.sectors_per_cluster
        
        # Mark all clusters as EOF (0xFFF)
        for cluster in range(2, total_clusters + 2):
            handler.set_fat_entry(fat_data, cluster, 0xFFF)
            
        handler.write_fat(fat_data)
        
        # Try to write a file (should fail as no clusters are free)
        with pytest.raises(FAT12Error):
            handler.write_file_to_image("fail.txt", b"data")

    def test_format_disk(self, handler):
        handler.write_file_to_image("file1.txt", b"data")
        handler.write_file_to_image("file2.txt", b"data")
        
        assert len(handler.read_root_directory()) == 2
        
        handler.format_disk()
        
        assert len(handler.read_root_directory()) == 0
        # Check FAT is empty (cluster 2 should be 0)
        fat = handler.read_fat()
        assert handler.get_fat_entry(fat, 2) == 0

    def test_format_disk_cleans_fat_and_root(self, handler):
        # Fill up some clusters
        handler.write_file_to_image("file1.txt", b"A" * 2048) # 4 clusters
        
        # Verify FAT is used
        fat_before = handler.read_fat()
        assert handler.get_fat_entry(fat_before, 2) != 0
        
        handler.format_disk()
        
        # Verify FAT is reset
        fat_after = handler.read_fat()
        
        # Check Media Descriptor (0xF0 for 1.44MB)
        assert fat_after[0] == 0xF0
        assert fat_after[1] == 0xFF
        assert fat_after[2] == 0xFF
        
        # Check rest of FAT is 0
        assert all(b == 0 for b in fat_after[3:])
        
        # Verify Root Directory is zeroed
        with open(handler.image_path, 'rb') as f:
            f.seek(handler.root_start)
            root_data = f.read(handler.root_size)
            assert all(b == 0 for b in root_data)
            
        # Verify second FAT copy is also reset
        fat_size = handler.sectors_per_fat * handler.bytes_per_sector
        fat2_start = handler.fat_start + fat_size
        
        with open(handler.image_path, 'rb') as f:
            f.seek(fat2_start)
            fat2_data = f.read(fat_size)
            
            assert fat2_data[0] == 0xF0
            assert fat2_data[1] == 0xFF
            assert fat2_data[2] == 0xFF
            assert all(b == 0 for b in fat2_data[3:])

class TestFileIO:
    def test_write_and_read_file(self, handler):
        content = b"Hello FAT12 World"
        filename = "hello.txt"
        
        # Write file
        assert handler.write_file_to_image(filename, content)
        
        # Verify file exists in directory
        entries = handler.read_root_directory()
        assert len(entries) == 1
        entry = entries[0]
        assert entry['name'] == filename
        assert entry['size'] == len(content)
        
        # Verify content extraction
        extracted = handler.extract_file(entry)
        assert extracted == content

    def test_write_and_read_multicluster_file(self, handler):
        # Create content larger than one cluster (512 bytes)
        content = b"A" * 600
        filename = "largefile.bin"
        
        # Write file
        assert handler.write_file_to_image(filename, content)
        
        # Verify file exists in directory
        entries = handler.read_root_directory()
        assert len(entries) == 1
        entry = entries[0]
        assert entry['name'] == filename
        assert entry['size'] == len(content)
        
        # Verify content extraction
        extracted = handler.extract_file(entry)
        assert extracted == content

    def test_write_zero_byte_file(self, handler):
        assert handler.write_file_to_image("empty.txt", b"")
        
        entries = handler.read_root_directory()
        assert len(entries) == 1
        assert entries[0]['size'] == 0
        assert entries[0]['cluster'] == 0
        
        # Extracting should return empty bytes
        assert handler.extract_file(entries[0]) == b""

    def test_write_exact_sector_size(self, handler):
        # 512 bytes = exactly 1 sector/cluster
        data = b"X" * 512
        handler.write_file_to_image("exact.txt", data)
        
        entries = handler.read_root_directory()
        assert entries[0]['size'] == 512
        
        extracted = handler.extract_file(entries[0])
        assert len(extracted) == 512
        assert extracted == data

    def test_file_too_large_for_disk(self, handler):
        # 2MB data (disk is 1.44MB)
        data = b"A" * (2 * 1024 * 1024)
        with pytest.raises(FAT12Error):
            handler.write_file_to_image("huge.bin", data)

    def test_delete_file(self, handler):
        handler.write_file_to_image("delete_me.txt", b"some data")
        entries = handler.read_root_directory()
        assert len(entries) == 1
        
        assert handler.delete_file(entries[0])
        
        entries_after = handler.read_root_directory()
        assert len(entries_after) == 0

    def test_delete_reclaims_clusters(self, handler):
        # Write 1KB file (2 clusters)
        data = b"A" * 1024
        handler.write_file_to_image("file.bin", data)
        
        entries = handler.read_root_directory()
        cluster = entries[0]['cluster']
        
        # Check FAT is marked (not 0)
        fat = handler.read_fat()
        assert handler.get_fat_entry(fat, cluster) != 0
        
        # Delete
        handler.delete_file(entries[0])
        
        # Check FAT is free (0)
        fat = handler.read_fat()
        assert handler.get_fat_entry(fat, cluster) == 0

    def test_extract_corrupted_chain(self, handler):
        # Write 2 clusters
        data = b"A" * 1024
        handler.write_file_to_image("file.txt", data)
        
        entries = handler.read_root_directory()
        start_cluster = entries[0]['cluster']
        
        # Corrupt FAT: Mark first cluster as EOF
        fat = handler.read_fat()
        handler.set_fat_entry(fat, start_cluster, 0xFFF)
        handler.write_fat(fat)
        
        # Extract
        with pytest.raises(FAT12CorruptionError):
            handler.extract_file(entries[0])

class TestDirectoryOperations:
    def test_rename_file(self, handler):
        handler.write_file_to_image("old_name.txt", b"content")
        entries = handler.read_root_directory()
        
        assert handler.rename_entry(entries[0], "new_name.txt")
        
        entries_new = handler.read_root_directory()
        assert len(entries_new) == 1
        assert entries_new[0]['name'] == "new_name.txt"
        # Check 8.3 generation happened
        assert entries_new[0]['short_name'] == "NEW_NAME.TXT"

    def test_rename_file_lfn_expansion(self, handler):
        # Short name file
        handler.write_file_to_image("SHORT.TXT", b"data")
        entries = handler.read_root_directory()
        
        # Rename to Long Name
        long_name = "ThisIsAVeryLongName.txt"
        handler.rename_entry(entries[0], long_name, use_numeric_tail=True)
        
        entries = handler.read_root_directory()
        assert entries[0]['name'] == long_name
        assert entries[0]['short_name'] == "THISIS~1.TXT"

    def test_rename_shrink_lfn_to_short(self, handler):
        # Write Long Filename (e.g. "LongFile.txt" -> LFN + Short = 2 entries)
        long_name = "LongFile.txt"
        handler.write_file_to_image(long_name, b"content")
        
        entries = handler.read_root_directory()
        original_index = entries[0]['index'] # Index of the short entry
        
        # Rename to Short Name
        new_name = "SHORT.TXT"
        handler.rename_entry(entries[0], new_name)
        
        entries_new = handler.read_root_directory()
        assert len(entries_new) == 1
        assert entries_new[0]['name'] == "SHORT.TXT"
        
        # Verify the extra slot was marked deleted
        # The file originally occupied [LFN, Short]. 
        # After rename to short, it occupies [Short, Deleted].
        # The new short entry overwrites the old LFN slot (start of block).
        with open(handler.image_path, 'rb') as f:
            # Check the slot immediately following the new file
            # The new file should be at original_index - 1 (start of the block)
            f.seek(handler.root_start + (original_index * 32)) 
            byte = f.read(1)
            assert byte == b'\xE5'

    def test_rename_expand_fail_full_dir(self, handler):
        # Fill the directory, leaving no contiguous space for an LFN entry
        for i in range(224):
            handler.write_file_to_image(f"F{i}.TXT", b"")
            
        entries = handler.read_root_directory()
        last_file_entry = entries[-1]
        
        # Try to rename to a long name, which requires more than one slot. This should fail.
        with pytest.raises(FAT12Error):
            handler.rename_entry(last_file_entry, "ThisIsALongName.txt")

    def test_lfn_case_preservation(self, handler):
        filename = "MixCase.txt"
        handler.write_file_to_image(filename, b"content")
        
        entries = handler.read_root_directory()
        assert entries[0]['name'] == "MixCase.txt"
        # Short name should be uppercase
        assert entries[0]['short_name'] == "MIXCASE.TXT"

    def test_rename_file_unicode_error(self, handler):
        handler.write_file_to_image("old.txt", b"")
        entries = handler.read_root_directory()
        
        # Mock generate_83_name to return a non-ascii string to trigger UnicodeEncodeError
        with patch('fat12_directory.generate_83_name', return_value="FÏLE    TXT"):
            handler.rename_entry(entries[0], "new.txt")
            
        entries = handler.read_root_directory()
        # 'Ï' is dropped by 'ignore', resulting in "FLE    TXT " (padded)
        assert "FLE" in entries[0]['short_name']

    def test_rename_file_exception(self, handler):
        handler.write_file_to_image("file.txt", b"")
        entries = handler.read_root_directory()
        
        # Mock open to raise exception during rename
        with patch('builtins.open', side_effect=IOError("Mock error")):
            with pytest.raises(IOError):
                handler.rename_entry(entries[0], "new.txt")

    def test_lfn_cleanup_on_delete(self, handler):
        # Write file with long name (needs LFN entries)
        long_name = "ThisIsALongName.txt"
        handler.write_file_to_image(long_name, b"content")
        
        entries = handler.read_root_directory()
        target = entries[0]
        
        # Delete it
        handler.delete_file(target)
        
        # Verify raw entries are marked 0xE5 (Deleted)
        with open(handler.image_path, 'rb') as f:
            f.seek(handler.root_start)
            # "ThisIsALongName.txt" is 19 chars -> 2 LFN entries + 1 Short entry = 3 entries
            # All 3 should be marked with 0xE5 at the start
            for _ in range(3):
                byte = f.read(1)
                assert byte == b'\xE5'
                f.seek(31, 1) # Skip rest of entry

    def test_delete_file_exception(self, handler):
        handler.write_file_to_image("file.txt", b"")
        entries = handler.read_root_directory()
        
        with patch('builtins.open', side_effect=IOError("Mock error")):
            with pytest.raises(IOError):
                handler.delete_file(entries[0])

    def test_lfn_checksum_mismatch(self, handler):
        filename = "ChecksumTest.txt"
        handler.write_file_to_image(filename, b"data")
        
        # Verify it reads correctly first
        entries = handler.read_root_directory()
        assert entries[0]['name'] == filename
        
        # Manually corrupt the checksum in the LFN entry
        # LFN entries are written before the short entry.
        # For this length, there is 1 LFN entry at index 0, Short entry at index 1.
        with open(handler.image_path, 'r+b') as f:
            f.seek(handler.root_start)
            
            # Read LFN entry (Index 0)
            lfn_data = bytearray(f.read(32))
            assert lfn_data[11] == 0x0F # Verify it is LFN
            
            # Corrupt checksum at offset 13
            lfn_data[13] = (lfn_data[13] + 1) & 0xFF
            
            # Write back
            f.seek(handler.root_start)
            f.write(lfn_data)
            
        # Read directory again
        entries = handler.read_root_directory()
        
        # Should fall back to short name because checksum mismatch
        assert entries[0]['name'] != filename
        assert entries[0]['name'] == entries[0]['short_name']
        assert "CHECKS" in entries[0]['name'] # Short name base

    def test_orphaned_lfn_entries(self, handler):
        # Manually write an LFN entry followed by a non-matching file
        # LFN entry (Seq 0x41, Checksum 0x99)
        lfn_entry = b'\x41\x41\x00\x41\x00\x41\x00\x41\x00\x41\x00\x0F\x00\x99\x41\x00\x41\x00\x41\x00\x41\x00\x41\x00\x41\x00\x00\x00\x41\x00\x41\x00'
        
        with open(handler.image_path, 'r+b') as f:
            f.seek(handler.root_start)
            f.write(lfn_entry)
            
        # Write a normal file (will go to index 1, skipping the "occupied" index 0)
        handler.write_file_to_image("OTHER.TXT", b"data")
        
        entries = handler.read_root_directory()
        assert len(entries) == 1
        # Should not pick up the garbage LFN because checksum mismatch
        assert entries[0]['name'] == "OTHER.TXT"

    def test_read_root_directory_fat32(self, handler):
        # Force FAT32 type
        handler.fat_type = 'FAT32'
        
        # Create a directory entry with high cluster bits
        # Offset 20-21 is high cluster (0x1234), 26-27 is low cluster (0x5678)
        # Total cluster = 0x12345678
        entry = bytearray(32)
        entry[0:11] = b"FAT32   TXT"
        entry[20:22] = struct.pack('<H', 0x1234) # High
        entry[26:28] = struct.pack('<H', 0x5678) # Low
        
        # Write to root dir
        with open(handler.image_path, 'r+b') as f:
            f.seek(handler.root_start)
            f.write(entry)
            
        entries = handler.read_root_directory()
        assert len(entries) == 1
        assert entries[0]['cluster'] == 0x12345678

    def test_rename_case_change_no_tail(self, handler):
        handler.write_file_to_image("FILE.TXT", b"content")
        entries = handler.read_root_directory()
        assert entries[0]['short_name'] == "FILE.TXT"
        
        # Rename "FILE.TXT" to "File.txt"
        # Should result in "FILE.TXT" short name (no ~1) and "File.txt" long name
        handler.rename_entry(entries[0], "File.txt")
        
        entries = handler.read_root_directory()
        assert entries[0]['name'] == "File.txt"
        assert entries[0]['short_name'] == "FILE.TXT" # Should NOT be FILE~1.TXT

    def test_shift_jis_e5_handling(self, handler):
        # In Shift-JIS, a filename starting with 0xE5 must be stored as 0x05
        # to avoid being confused with a deleted entry. We test this by manually
        # writing such an entry and ensuring it's read back correctly.
        
        # 1. Find a free entry and cluster
        free_entry_idx = handler.find_free_root_entries(1)
        free_cluster = handler.find_free_clusters(1)[0]
        
        # 2. Create the raw directory entry with a name starting with 0x05
        entry_data = bytearray(32)
        sjis_name = b'\x05FILENAM' # Represents a name starting with 0xE5
        ext = b'TXT'
        entry_data[0:11] = sjis_name.ljust(8) + ext.ljust(3)
        entry_data[11] = 0x20 # Archive
        entry_data[26:28] = struct.pack('<H', free_cluster) # cluster
        entry_data[28:32] = struct.pack('<I', 4) # size
        
        # 3. Write it to the disk image
        with open(handler.image_path, 'r+b') as f:
            f.seek(handler.root_start + (free_entry_idx * 32))
            f.write(entry_data)
            
        # 4. Read the directory and verify the name is decoded correctly
        entries = handler.read_root_directory()
        assert len(entries) == 1
        
        # The handler should convert 0x05 back to 0xE5 and then decode.
        # Since we use ascii(errors='ignore'), the 0xE5 is dropped, but the
        # rest of the name proves the file was not skipped as "deleted".
        assert entries[0]['short_name'] == "FILENAM.TXT"

    def test_volume_label_skip(self, handler):
        # Manually write a volume label entry (Attr 0x08)
        with open(handler.image_path, 'r+b') as f:
            f.seek(handler.root_start)
            # "MYLABEL    " + attr 0x08
            entry = b"MYLABEL    \x08" + b"\x00"*20
            f.write(entry)
            
        # Read directory - should be empty (label skipped)
        entries = handler.read_root_directory()
        assert len(entries) == 0

    def test_read_raw_directory_entries(self, handler):
        handler.write_file_to_image("FILE1.TXT", b"1")
        
        raw_entries = handler.read_raw_directory_entries()
        
        # First entry should be FILE1.TXT
        idx, data = raw_entries[0]
        assert idx == 0
        assert data[0:8] == b'FILE1   '
        
        # Second entry should be end of directory marker
        idx, data = raw_entries[1]
        assert idx == 1
        assert data[0] == 0x00

    def test_file_timestamps(self, handler):
        before = datetime.datetime.now()
        handler.write_file_to_image("timed.txt", b"data")
        after = datetime.datetime.now()
        
        entries = handler.read_root_directory()
        entry = entries[0]
        
        # Decode the timestamp from the entry
        created_date = decode_fat_date(entry['creation_date'])
        created_time = decode_fat_time(entry['creation_time'])
        created_dt = datetime.datetime.strptime(f"{created_date} {created_time}", "%Y-%m-%d %H:%M:%S")
        
        # Check if the created time is between 'before' and 'after', allowing for 2s precision loss
        assert (before - datetime.timedelta(seconds=2)) <= created_dt <= (after + datetime.timedelta(seconds=2))

    def test_root_directory_full(self, handler):
        # Fill root directory (224 entries)
        # We use short names to ensure 1 entry per file
        for i in range(224):
            fname = f"F{i}.TXT"
            assert handler.write_file_to_image(fname, b"")
            
        # Try to write one more
        with pytest.raises(FAT12Error):
            handler.write_file_to_image("FULL.TXT", b"")

    def test_directory_fragmentation_reuse(self, handler):
        # Write 3 short files (1 entry each)
        handler.write_file_to_image("FILE1.TXT", b"1")
        handler.write_file_to_image("FILE2.TXT", b"2")
        handler.write_file_to_image("FILE3.TXT", b"3")
        
        entries = handler.read_root_directory()
        assert len(entries) == 3
        
        # Delete middle file (FILE2)
        file2 = next(e for e in entries if e['name'] == "FILE2.TXT")
        handler.delete_file(file2)
        
        # Write new file (FILE4)
        handler.write_file_to_image("FILE4.TXT", b"4")
        
        # Verify FILE4 took the slot of FILE2 (index reuse)
        entries_new = handler.read_root_directory()
        file4 = next(e for e in entries_new if e['name'] == "FILE4.TXT")
        
        assert file4['index'] == file2['index']

class TestClusterAnalysis:
    def test_get_cluster_map(self, handler):
        # Write a file that takes 2 clusters (512 bytes per cluster)
        # 600 bytes -> 2 clusters
        handler.write_file_to_image("file1.txt", b"A" * 600)
        
        # Write another file (1 cluster)
        handler.write_file_to_image("file2.txt", b"B" * 100)
        
        # Get map
        cluster_map = handler.get_cluster_map()
        
        # file1 should be at cluster 2 and 3 (since it's the first file)
        # file2 should be at cluster 4
        
        assert cluster_map.get(2) == "file1.txt"
        assert cluster_map.get(3) == "file1.txt"
        assert cluster_map.get(4) == "file2.txt"
        
        # Check size
        assert len(cluster_map) == 3

    def test_get_cluster_chain(self, handler):
        # Write a file that takes 3 clusters
        # 1200 bytes -> 3 clusters (512 * 2 = 1024, need 3rd)
        handler.write_file_to_image("chain.txt", b"C" * 1200)
        
        # Clusters should be 2, 3, 4
        
        # Test getting chain from start
        chain = handler.get_cluster_chain(2)
        assert chain == [2, 3, 4]
        
        # Test getting chain from middle
        chain = handler.get_cluster_chain(3)
        assert chain == [2, 3, 4]
        
        # Test getting chain from end
        chain = handler.get_cluster_chain(4)
        assert chain == [2, 3, 4]
        
        # Test single cluster file
        handler.write_file_to_image("single.txt", b"S" * 100)
        # Should be cluster 5
        chain = handler.get_cluster_chain(5)
        assert chain == [5]

    def test_get_cluster_chain_fragmented(self, handler):
        # Create fragmentation
        # Write file A (1 cluster) -> 2
        handler.write_file_to_image("A.txt", b"A" * 100)
        # Write file B (1 cluster) -> 3
        handler.write_file_to_image("B.txt", b"B" * 100)
        # Write file C (1 cluster) -> 4
        handler.write_file_to_image("C.txt", b"C" * 100)
        
        # Delete B -> Cluster 3 is free
        entries = handler.read_root_directory()
        entry_b = next(e for e in entries if e['name'] == "B.txt")
        handler.delete_file(entry_b)
        
        # Write file D (2 clusters) -> Should take 3, then 5
        handler.write_file_to_image("D.txt", b"D" * 600)
        
        # Verify D's chain
        # It should use cluster 3 (reclaimed) and cluster 5 (next free)
        
        chain = handler.get_cluster_chain(3)
        assert chain == [3, 5]
        
        chain = handler.get_cluster_chain(5)
        assert chain == [3, 5]

    def test_lfn_invalid_utf16(self, handler):
        # 1. Manually write a malformed LFN entry at Index 0
        # LFN entry with invalid UTF-16 sequence
        lfn_entry = bytearray(32)
        lfn_entry[0] = 0x41 # Last entry, seq 1
        lfn_entry[11] = 0x0F # LFN attr
        lfn_entry[13] = calculate_lfn_checksum(b"BADLFN  TXT")
        # Invalid UTF-16LE: High surrogate (0xD800) followed by space (0x0020)
        # This ensures strict decoding fails
        lfn_entry[1:5] = b'\x00\xD8\x20\x00' 
        
        with open(handler.image_path, 'r+b') as f:
            f.seek(handler.root_start)
            f.write(lfn_entry)
            
        # 2. Write the file (will skip Index 0 because it's occupied, and write to Index 1)
        handler.write_file_to_image("BADLFN.TXT", b"data")
            
        # Read directory
        entries = handler.read_root_directory()
        
        # Should ignore the LFN and show short name
        assert entries[0]['name'] == "BADLFN.TXT"

class TestHelperMethods:
    def test_get_total_capacity(self, handler):
        # 2880 sectors * 512 bytes = 1,474,560 bytes
        assert handler.get_total_capacity() == 1474560

    def test_get_free_space(self, handler):
        # Initial free space: 2847 clusters * 512 bytes
        initial_free = 2847 * 512
        assert handler.get_free_space() == initial_free
        
        # Write 1024 bytes (2 clusters)
        handler.write_file_to_image("test.txt", b"A" * 1024)
        
        # Should decrease by 2 clusters
        assert handler.get_free_space() == initial_free - 1024

    def test_calculate_size_on_disk(self, handler):
        # Cluster size is 512 bytes for 1.44MB image
        assert handler.bytes_per_cluster == 512
        
        # 0 bytes -> 0 on disk
        assert handler.calculate_size_on_disk(0) == 0
        # 1 byte -> 1 cluster (512)
        assert handler.calculate_size_on_disk(1) == 512
        # 512 bytes -> 1 cluster (512)
        assert handler.calculate_size_on_disk(512) == 512
        # 513 bytes -> 2 clusters (1024)
        assert handler.calculate_size_on_disk(513) == 1024

    def test_find_entry_by_83_name(self, handler):
        handler.write_file_to_image("FILE.TXT", b"content")
        handler.write_file_to_image("NOEXT", b"content")
        
        # Correct format search
        entry = handler.find_entry_by_83_name("FILE    TXT")
        assert entry is not None
        assert entry['name'] == "FILE.TXT"
        
        # Lowercase input should work (method upper()s it)
        entry = handler.find_entry_by_83_name("file    txt")
        assert entry is not None
        assert entry['name'] == "FILE.TXT"
        
        # Search for file without extension
        entry = handler.find_entry_by_83_name("NOEXT      ")
        assert entry is not None
        assert entry['name'] == "NOEXT"
        
        # Wrong format (with dot) should fail to find
        entry = handler.find_entry_by_83_name("FILE.TXT")
        assert entry is None
        
        # Non-existent file
        entry = handler.find_entry_by_83_name("NONEXIST   ")
        assert entry is None

    def test_get_existing_83_names(self, handler):
        handler.write_file_to_image("A.TXT", b"")
        handler.write_file_to_image("LONGFILENAME.TXT", b"", use_numeric_tail=True) # LONGFILENAME.TXT -> LONGFI~1.TXT -> LONGFI~1TXT
        
        names = handler.get_existing_83_names()
        assert "A       TXT" in names
        assert "LONGFI~1TXT" in names
        assert len(names) == 2

    def test_get_fat_entry_count(self, handler):
        # Sectors per FAT = 9
        # Bytes per sector = 512
        # Total bytes = 4608
        # 12 bits per entry = 1.5 bytes
        # 4608 / 1.5 = 3072 entries
        assert handler.get_fat_entry_count() == 3072

    def test_classify_cluster(self, handler):
        assert handler.classify_cluster(0x000) == FAT12Image.CLUSTER_FREE
        assert handler.classify_cluster(0x001) == FAT12Image.CLUSTER_RESERVED
        assert handler.classify_cluster(0x002) == FAT12Image.CLUSTER_USED
        assert handler.classify_cluster(0xFEF) == FAT12Image.CLUSTER_USED
        assert handler.classify_cluster(0xFF7) == FAT12Image.CLUSTER_BAD
        assert handler.classify_cluster(0xFF8) == FAT12Image.CLUSTER_EOF
        assert handler.classify_cluster(0xFFF) == FAT12Image.CLUSTER_EOF

    def test_predict_short_name(self, handler):
        # Write a file to occupy a name
        handler.write_file_to_image("FILE.TXT", b"")
        
        # Predict collision
        assert handler.predict_short_name("File.txt", use_numeric_tail=True) == "FILE~1  TXT"
        assert handler.predict_short_name("NewFile.txt") == "NEWFILE TXT"

    def test_get_total_cluster_count(self, handler):
        # Standard 1.44MB floppy
        # FAT size = 9 sectors * 512 bytes = 4608 bytes
        # Entries = (4608 * 8) / 12 = 3072
        # Result should be min(3072, 4084) = 3072
        assert handler.get_total_cluster_count() == 3072

    def test_get_existing_83_names_filtering(self, handler):
        # 1. Write a file and delete it (marks as 0xE5)
        handler.write_file_to_image("DEL.TXT", b"")
        entries = handler.read_root_directory()
        handler.delete_file(entries[0])
        
        # 2. Manually write a file with 0x05 (Shift-JIS 0xE5) at index 1
        with open(handler.image_path, 'r+b') as f:
            f.seek(handler.root_start + 32) # Index 1
            entry = bytearray(32)
            entry[0] = 0x05
            entry[1:11] = b"EST    TXT" # 10 bytes to fit slice
            f.write(entry)
            
        names = handler.get_existing_83_names()
        
        # Should NOT contain DEL.TXT (deleted files are skipped)
        # Should contain the 0x05 file (decoded as "EST    TXT" due to replace errors)
        assert "\uFFFDEST    TXT" in names
        assert len(names) == 1

    def test_find_entry_by_83_name_raw_match(self, handler):
        handler.write_file_to_image("FILE.TXT", b"")
        
        # Search using the raw 11-byte format
        entry = handler.find_entry_by_83_name("FILE    TXT")
        assert entry is not None
        assert entry['raw_short_name'] == "FILE    TXT"

    def test_predict_short_name_collision_sjis(self, handler):
        # If we have a file "\xE5BCDEFGH.TXT" (stored as 0x05 + BCDEFGHTXT), it decodes to "BCDEFGHTXT"
        # If we try to add "BCDEFGH.TXT" (candidate "BCDEFGH TXT"), it should NOT collide because names differ.
        
        # Manually write the 0x05 entry
        with open(handler.image_path, 'r+b') as f:
            f.seek(handler.root_start)
            entry = bytearray(32)
            entry[0] = 0x05
            entry[1:11] = b"BCDEFGHTXT" # 10 bytes
            f.write(entry)
            
        # Predict
        predicted = handler.predict_short_name("BCDEFGH.TXT", use_numeric_tail=True)
        assert predicted == "BCDEFGH TXT"
class TestFileAttributes:
    """Test file attribute modification functionality"""
    
    def test_set_read_only_attribute(self, handler):
        """Test setting read-only attribute"""
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("TESTFILE.TXT", test_data)
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "TESTFILE.TXT")
        
        # Initially should not be read-only
        assert not entry['is_read_only']
        assert entry['attributes'] == 0x20  # Archive bit only
        
        # Set read-only
        assert handler.set_entry_attributes(entry, is_read_only=True)
        
        # Verify it was set
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "TESTFILE.TXT")
        assert entry['is_read_only']
        assert entry['attributes'] & 0x01  # Read-only bit set
        assert entry['attributes'] & 0x20  # Archive bit still set
        
        # Clear read-only
        assert handler.set_entry_attributes(entry, is_read_only=False)
        
        # Verify it was cleared
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "TESTFILE.TXT")
        assert not entry['is_read_only']
        assert not (entry['attributes'] & 0x01)  # Read-only bit cleared
        assert entry['attributes'] & 0x20  # Archive bit still set
    
    def test_set_hidden_attribute(self, handler):
        """Test setting hidden attribute"""
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("HIDDEN.TXT", test_data)
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "HIDDEN.TXT")
        
        # Initially should not be hidden
        assert not entry['is_hidden']
        
        # Set hidden
        assert handler.set_entry_attributes(entry, is_hidden=True)
        
        # Verify it was set
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "HIDDEN.TXT")
        assert entry['is_hidden']
        assert entry['attributes'] & 0x02  # Hidden bit set
        
        # Clear hidden
        assert handler.set_entry_attributes(entry, is_hidden=False)
        
        # Verify it was cleared
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "HIDDEN.TXT")
        assert not entry['is_hidden']
        assert not (entry['attributes'] & 0x02)  # Hidden bit cleared
    
    def test_set_system_attribute(self, handler):
        """Test setting system attribute"""
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("SYSTEM.SYS", test_data)
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "SYSTEM.SYS")
        
        # Initially should not be system
        assert not entry['is_system']
        
        # Set system
        assert handler.set_entry_attributes(entry, is_system=True)
        
        # Verify it was set
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "SYSTEM.SYS")
        assert entry['is_system']
        assert entry['attributes'] & 0x04  # System bit set
    
    def test_set_archive_attribute(self, handler):
        """Test setting archive attribute"""
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("ARCHIVE.TXT", test_data)
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "ARCHIVE.TXT")
        
        # Initially should be archive (set by default)
        assert entry['is_archive']
        
        # Clear archive
        assert handler.set_entry_attributes(entry, is_archive=False)
        
        # Verify it was cleared
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "ARCHIVE.TXT")
        assert not entry['is_archive']
        assert not (entry['attributes'] & 0x20)  # Archive bit cleared
        
        # Set archive again
        assert handler.set_entry_attributes(entry, is_archive=True)
        
        # Verify it was set
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "ARCHIVE.TXT")
        assert entry['is_archive']
        assert entry['attributes'] & 0x20  # Archive bit set
    
    def test_set_multiple_attributes(self, handler):
        """Test setting multiple attributes at once"""
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("MULTI.TXT", test_data)
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "MULTI.TXT")
        
        # Set multiple attributes at once
        assert handler.set_entry_attributes(
            entry, 
            is_read_only=True, 
            is_hidden=True, 
            is_system=True
        )
        
        # Verify all were set
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "MULTI.TXT")
        assert entry['is_read_only']
        assert entry['is_hidden']
        assert entry['is_system']
        assert entry['is_archive']  # Archive should still be set
        
        # Verify the raw attribute byte
        expected_attr = 0x01 | 0x02 | 0x04 | 0x20  # R+H+S+A
        assert entry['attributes'] == expected_attr
    
    def test_partial_attribute_update(self, handler):
        """Test updating only some attributes (None means no change)"""
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("PARTIAL.TXT", test_data)
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "PARTIAL.TXT")
        
        # Set read-only and hidden
        assert handler.set_entry_attributes(entry, is_read_only=True, is_hidden=True)
        
        # Now only change archive, leaving read-only and hidden alone
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "PARTIAL.TXT")
        assert handler.set_entry_attributes(entry, is_archive=False)
        
        # Verify read-only and hidden are still set, but archive is cleared
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "PARTIAL.TXT")
        assert entry['is_read_only']
        assert entry['is_hidden']
        assert not entry['is_archive']
        assert not entry['is_system']
    
    def test_attribute_bits_preserved(self, handler):
        """Test that directory bit (0x10) is preserved and can't be modified"""
        
        # Add a test file
        test_data = b"Test file content"
        assert handler.write_file_to_image("PRESERVE.TXT", test_data)
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "PRESERVE.TXT")
        
        # Store original attributes
        original_attr = entry['attributes']
        assert not (original_attr & 0x10)  # Should not be a directory
        
        # Try to set various attributes
        assert handler.set_entry_attributes(entry, is_read_only=True, is_hidden=True)
        
        # Verify directory bit is still clear
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "PRESERVE.TXT")
        assert not (entry['attributes'] & 0x10)  # Still not a directory
        assert not entry['is_dir']  # is_dir flag should be False
    
    def test_attributes_with_long_filename(self, handler):
        """Test that attributes work correctly with files that have LFN entries"""
        
        # Add a file with a long name that needs LFN entries
        test_data = b"Test file content"
        long_name = "This is a very long filename.txt"
        assert handler.write_file_to_image(long_name, test_data)
        
        # Get the file entry
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == long_name)
        
        # Set attributes
        assert handler.set_entry_attributes(entry, is_read_only=True, is_hidden=True)
        
        # Verify attributes are set correctly
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == long_name)
        assert entry['is_read_only']
        assert entry['is_hidden']
        
        # Verify the file can still be read correctly
        assert len(entries) > 0
        assert entry['name'] == long_name
        assert handler.set_entry_attributes(entry, is_read_only=True, is_hidden=True)
        
        # Verify attributes are set correctly
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == long_name)
        assert entry['is_read_only']
        assert entry['is_hidden']
        
        # Verify the file can still be read correctly
        assert len(entries) > 0
        assert entry['name'] == long_name

    def test_directory_attributes(self, handler):
        """Test setting attributes on a directory"""
        
        # Create a directory
        handler.create_directory("MYDIR")
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "MYDIR")
        
        assert entry['is_dir']
        
        # Set Hidden and System
        assert handler.set_entry_attributes(entry, is_hidden=True, is_system=True)
        
        # Verify
        entries = handler.read_root_directory()
        entry = next(e for e in entries if e['name'] == "MYDIR")
        
        assert entry['is_hidden']
        assert entry['is_system']
        assert entry['is_dir'] # Should still be a directory
        assert entry['attributes'] & 0x10 # Directory bit preserved
