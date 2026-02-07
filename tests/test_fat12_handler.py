import pytest
import datetime
import struct
from fat12_handler import FAT12Image
from vfat_utils import decode_fat_date, decode_fat_time, calculate_lfn_checksum

@pytest.fixture
def handler():
    # Create instance without running full __init__ to test methods in isolation
    return FAT12Image.__new__(FAT12Image)

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

    def test_boot_sector_initialization(self, tmp_path):
        # Create a temporary blank image
        img_path = tmp_path / "test.img"
        # Use the class method to create a default image
        FAT12Image.create_empty_image(str(img_path))
        
        # Load it and verify the OEM Name from the snippet
        handler = FAT12Image(str(img_path))
        assert "YAMAHA" in handler.oem_name
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

class TestClusterManagement:
    def test_find_free_clusters(self, tmp_path):
        img_path = tmp_path / "test_clusters.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Request 5 free clusters
        free_clusters = handler.find_free_clusters(5)
        assert len(free_clusters) == 5
        # Clusters start at 2
        assert free_clusters == [2, 3, 4, 5, 6]

    def test_find_all_free_clusters(self, tmp_path):
        img_path = tmp_path / "test_all_clusters.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_disk_full_data_area(self, tmp_path):
        img_path = tmp_path / "test_full_disk.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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
        assert not handler.write_file_to_image("fail.txt", b"data")

    def test_format_disk(self, tmp_path):
        img_path = tmp_path / "test_format.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        handler.write_file_to_image("file1.txt", b"data")
        handler.write_file_to_image("file2.txt", b"data")
        
        assert len(handler.read_root_directory()) == 2
        
        handler.format_disk()
        
        assert len(handler.read_root_directory()) == 0
        # Check FAT is empty (cluster 2 should be 0)
        fat = handler.read_fat()
        assert handler.get_fat_entry(fat, 2) == 0

class TestFileIO:
    def test_write_and_read_file(self, tmp_path):
        img_path = tmp_path / "test_io.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_write_and_read_multicluster_file(self, tmp_path):
        img_path = tmp_path / "test_mc.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_write_zero_byte_file(self, tmp_path):
        img_path = tmp_path / "test_zero.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        assert handler.write_file_to_image("empty.txt", b"")
        
        entries = handler.read_root_directory()
        assert len(entries) == 1
        assert entries[0]['size'] == 0
        assert entries[0]['cluster'] == 0
        
        # Extracting should return empty bytes
        assert handler.extract_file(entries[0]) == b""

    def test_write_exact_sector_size(self, tmp_path):
        img_path = tmp_path / "test_exact.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # 512 bytes = exactly 1 sector/cluster
        data = b"X" * 512
        handler.write_file_to_image("exact.txt", data)
        
        entries = handler.read_root_directory()
        assert entries[0]['size'] == 512
        
        extracted = handler.extract_file(entries[0])
        assert len(extracted) == 512
        assert extracted == data

    def test_file_too_large_for_disk(self, tmp_path):
        img_path = tmp_path / "test_large.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # 2MB data (disk is 1.44MB)
        data = b"A" * (2 * 1024 * 1024)
        assert not handler.write_file_to_image("huge.bin", data)

    def test_delete_file(self, tmp_path):
        img_path = tmp_path / "test_del.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        handler.write_file_to_image("delete_me.txt", b"some data")
        entries = handler.read_root_directory()
        assert len(entries) == 1
        
        assert handler.delete_file(entries[0])
        
        entries_after = handler.read_root_directory()
        assert len(entries_after) == 0

    def test_delete_reclaims_clusters(self, tmp_path):
        img_path = tmp_path / "test_reclaim.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_extract_corrupted_chain(self, tmp_path):
        img_path = tmp_path / "test_corrupt.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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
        extracted = handler.extract_file(entries[0])
        
        # Should get first cluster only (512 bytes) despite size saying 1024
        assert len(extracted) == 512
        assert extracted == data[:512]

class TestDirectoryOperations:
    def test_rename_file(self, tmp_path):
        img_path = tmp_path / "test_rename.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        handler.write_file_to_image("old_name.txt", b"content")
        entries = handler.read_root_directory()
        
        assert handler.rename_file(entries[0], "new_name.txt")
        
        entries_new = handler.read_root_directory()
        assert len(entries_new) == 1
        assert entries_new[0]['name'] == "new_name.txt"
        # Check 8.3 generation happened
        assert entries_new[0]['short_name'] == "NEW_NAME.TXT"

    def test_rename_file_lfn_expansion(self, tmp_path):
        img_path = tmp_path / "test_rename_lfn.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Short name file
        handler.write_file_to_image("SHORT.TXT", b"data")
        entries = handler.read_root_directory()
        
        # Rename to Long Name
        long_name = "ThisIsAVeryLongName.txt"
        handler.rename_file(entries[0], long_name, use_numeric_tail=True)
        
        entries = handler.read_root_directory()
        assert entries[0]['name'] == long_name
        assert entries[0]['short_name'] == "THISIS~1.TXT"

    def test_rename_shrink_lfn_to_short(self, tmp_path):
        img_path = tmp_path / "test_shrink.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Write Long Filename (e.g. "LongFile.txt" -> LFN + Short = 2 entries)
        long_name = "LongFile.txt"
        handler.write_file_to_image(long_name, b"content")
        
        entries = handler.read_root_directory()
        original_index = entries[0]['index'] # Index of the short entry
        
        # Rename to Short Name
        new_name = "SHORT.TXT"
        handler.rename_file(entries[0], new_name)
        
        entries_new = handler.read_root_directory()
        assert len(entries_new) == 1
        assert entries_new[0]['name'] == "SHORT.TXT"
        
        # Verify the extra slot was marked deleted
        # The file originally occupied [LFN, Short]. 
        # After rename to short, it occupies [Short, Deleted].
        # The new short entry overwrites the old LFN slot (start of block).
        with open(str(img_path), 'rb') as f:
            # Check the slot immediately following the new file
            # The new file should be at original_index - 1 (start of the block)
            f.seek(handler.root_start + (original_index * 32)) 
            byte = f.read(1)
            assert byte == b'\xE5'

    def test_rename_expand_fail_full_dir(self, tmp_path):
        img_path = tmp_path / "test_rename_full.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Fill the directory, leaving no contiguous space for an LFN entry
        for i in range(224):
            handler.write_file_to_image(f"F{i}.TXT", b"")
            
        entries = handler.read_root_directory()
        last_file_entry = entries[-1]
        
        # Try to rename to a long name, which requires more than one slot. This should fail.
        assert not handler.rename_file(last_file_entry, "ThisIsALongName.txt")

    def test_lfn_case_preservation(self, tmp_path):
        img_path = tmp_path / "test_case.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        filename = "MixCase.txt"
        handler.write_file_to_image(filename, b"content")
        
        entries = handler.read_root_directory()
        assert entries[0]['name'] == "MixCase.txt"
        # Short name should be uppercase
        assert entries[0]['short_name'] == "MIXCASE.TXT"

    def test_lfn_cleanup_on_delete(self, tmp_path):
        img_path = tmp_path / "test_lfn_del.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Write file with long name (needs LFN entries)
        long_name = "ThisIsALongName.txt"
        handler.write_file_to_image(long_name, b"content")
        
        entries = handler.read_root_directory()
        target = entries[0]
        
        # Delete it
        handler.delete_file(target)
        
        # Verify raw entries are marked 0xE5 (Deleted)
        with open(str(img_path), 'rb') as f:
            f.seek(handler.root_start)
            # "ThisIsALongName.txt" is 19 chars -> 2 LFN entries + 1 Short entry = 3 entries
            # All 3 should be marked with 0xE5 at the start
            for _ in range(3):
                byte = f.read(1)
                assert byte == b'\xE5'
                f.seek(31, 1) # Skip rest of entry

    def test_lfn_checksum_mismatch(self, tmp_path):
        img_path = tmp_path / "test_checksum.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        filename = "ChecksumTest.txt"
        handler.write_file_to_image(filename, b"data")
        
        # Verify it reads correctly first
        entries = handler.read_root_directory()
        assert entries[0]['name'] == filename
        
        # Manually corrupt the checksum in the LFN entry
        # LFN entries are written before the short entry.
        # For this length, there is 1 LFN entry at index 0, Short entry at index 1.
        with open(str(img_path), 'r+b') as f:
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

    def test_orphaned_lfn_entries(self, tmp_path):
        img_path = tmp_path / "test_orphan.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Manually write an LFN entry followed by a non-matching file
        # LFN entry (Seq 0x41, Checksum 0x99)
        lfn_entry = b'\x41\x41\x00\x41\x00\x41\x00\x41\x00\x41\x00\x0F\x00\x99\x41\x00\x41\x00\x41\x00\x41\x00\x41\x00\x41\x00\x00\x00\x41\x00\x41\x00'
        
        with open(str(img_path), 'r+b') as f:
            f.seek(handler.root_start)
            f.write(lfn_entry)
            
        # Write a normal file (will go to index 1, skipping the "occupied" index 0)
        handler.write_file_to_image("OTHER.TXT", b"data")
        
        entries = handler.read_root_directory()
        assert len(entries) == 1
        # Should not pick up the garbage LFN because checksum mismatch
        assert entries[0]['name'] == "OTHER.TXT"

    def test_shift_jis_e5_handling(self, tmp_path):
        img_path = tmp_path / "test_sjis.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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
        with open(str(img_path), 'r+b') as f:
            f.seek(handler.root_start + (free_entry_idx * 32))
            f.write(entry_data)
            
        # 4. Read the directory and verify the name is decoded correctly
        entries = handler.read_root_directory()
        assert len(entries) == 1
        
        # The handler should convert 0x05 back to 0xE5 and then decode.
        # Since we use ascii(errors='ignore'), the 0xE5 is dropped, but the
        # rest of the name proves the file was not skipped as "deleted".
        assert entries[0]['short_name'] == "FILENAM.TXT"

    def test_volume_label_skip(self, tmp_path):
        img_path = tmp_path / "test_vol.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Manually write a volume label entry (Attr 0x08)
        with open(str(img_path), 'r+b') as f:
            f.seek(handler.root_start)
            # "MYLABEL    " + attr 0x08
            entry = b"MYLABEL    \x08" + b"\x00"*20
            f.write(entry)
            
        # Read directory - should be empty (label skipped)
        entries = handler.read_root_directory()
        assert len(entries) == 0

    def test_read_raw_directory_entries(self, tmp_path):
        img_path = tmp_path / "test_raw.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_file_timestamps(self, tmp_path):
        img_path = tmp_path / "test_time.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_root_directory_full(self, tmp_path):
        img_path = tmp_path / "test_full_root.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # Fill root directory (224 entries)
        # We use short names to ensure 1 entry per file
        for i in range(224):
            fname = f"F{i}.TXT"
            assert handler.write_file_to_image(fname, b"")
            
        # Try to write one more
        assert not handler.write_file_to_image("FULL.TXT", b"")

    def test_directory_fragmentation_reuse(self, tmp_path):
        img_path = tmp_path / "test_frag.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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
    def test_get_cluster_map(self, tmp_path):
        img_path = tmp_path / "test_map.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_get_cluster_chain(self, tmp_path):
        img_path = tmp_path / "test_chain.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_get_cluster_chain_fragmented(self, tmp_path):
        img_path = tmp_path / "test_frag_chain.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
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

    def test_lfn_invalid_utf16(self, tmp_path):
        img_path = tmp_path / "test_bad_lfn.img"
        FAT12Image.create_empty_image(str(img_path))
        handler = FAT12Image(str(img_path))
        
        # 1. Manually write a malformed LFN entry at Index 0
        # LFN entry with invalid UTF-16 sequence
        lfn_entry = bytearray(32)
        lfn_entry[0] = 0x41 # Last entry, seq 1
        lfn_entry[11] = 0x0F # LFN attr
        lfn_entry[13] = calculate_lfn_checksum(b"BADLFN  TXT")
        # Invalid UTF-16LE: High surrogate (0xD800) followed by space (0x0020)
        # This ensures strict decoding fails
        lfn_entry[1:5] = b'\x00\xD8\x20\x00' 
        
        with open(str(img_path), 'r+b') as f:
            f.seek(handler.root_start)
            f.write(lfn_entry)
            
        # 2. Write the file (will skip Index 0 because it's occupied, and write to Index 1)
        handler.write_file_to_image("BADLFN.TXT", b"data")
            
        # Read directory
        entries = handler.read_root_directory()
        
        # Should ignore the LFN and show short name
        assert entries[0]['name'] == "BADLFN.TXT"