import pytest
from fat12_backend.handler import FAT12Image
from fat12_backend.directory import (
    iter_directory_entries, get_entry_offset, 
    get_existing_83_names_in_directory, find_free_directory_entries,
    free_cluster_chain, FAT12Error, FAT12CorruptionError
)

@pytest.fixture
def handler(tmp_path):
    img_path = tmp_path / "test_dir.img"
    FAT12Image.create_empty_image(str(img_path))
    return FAT12Image(str(img_path))

class TestDirectoryCreation:
    def test_create_directory_root(self, handler):
        handler.create_directory("TESTDIR")
        entries = handler.read_root_directory()
        entry = next((e for e in entries if e['name'] == "TESTDIR"), None)
        assert entry is not None
        assert entry['is_dir']
        assert entry['cluster'] >= 2

    def test_create_nested_directory(self, handler):
        handler.create_directory("PARENT")
        parent = next(e for e in handler.read_root_directory() if e['name'] == "PARENT")
        
        handler.create_directory("CHILD", parent_cluster=parent['cluster'])
        
        sub_entries = handler.read_directory(parent['cluster'])
        child = next((e for e in sub_entries if e['name'] == "CHILD"), None)
        assert child is not None
        assert child['is_dir']

class TestDirectoryDeletion:
    def test_delete_empty_directory(self, handler):
        handler.create_directory("EMPTY")
        entry = next(e for e in handler.read_root_directory() if e['name'] == "EMPTY")
        
        handler.delete_directory(entry)
        
        entries = handler.read_root_directory()
        assert not any(e['name'] == "EMPTY" for e in entries)

    def test_delete_non_empty_directory_fails(self, handler):
        handler.create_directory("FULL")
        entry = next(e for e in handler.read_root_directory() if e['name'] == "FULL")
        
        handler.write_file_to_image("FILE.TXT", b"data", parent_cluster=entry['cluster'])
        
        # Should fail without recursive=True
        with pytest.raises(FAT12Error):
            handler.delete_directory(entry)

    def test_delete_recursive(self, handler):
        handler.create_directory("RECURSIVE")
        entry = next(e for e in handler.read_root_directory() if e['name'] == "RECURSIVE")
        
        handler.write_file_to_image("FILE.TXT", b"data", parent_cluster=entry['cluster'])
        
        handler.delete_directory(entry, recursive=True)
        
        entries = handler.read_root_directory()
        assert not any(e['name'] == "RECURSIVE" for e in entries)

class TestFileOperationsInDirectory:
    def test_write_file_to_subdir(self, handler):
        handler.create_directory("DOCS")
        docs = next(e for e in handler.read_root_directory() if e['name'] == "DOCS")
        
        handler.write_file_to_image("NOTE.TXT", b"content", parent_cluster=docs['cluster'])
        
        sub_entries = handler.read_directory(docs['cluster'])
        file_entry = next((e for e in sub_entries if e['name'] == "NOTE.TXT"), None)
        assert file_entry is not None
        assert file_entry['size'] == 7

    def test_delete_file_in_subdir(self, handler):
        handler.create_directory("TRASH")
        trash = next(e for e in handler.read_root_directory() if e['name'] == "TRASH")
        
        handler.write_file_to_image("JUNK.TXT", b"junk", parent_cluster=trash['cluster'])
        
        sub_entries = handler.read_directory(trash['cluster'])
        junk = next(e for e in sub_entries if e['name'] == "JUNK.TXT")
        
        handler.delete_file(junk)
        
        sub_entries = handler.read_directory(trash['cluster'])
        assert not any(e['name'] == "JUNK.TXT" for e in sub_entries)

class TestIterDirectoryEntries:
    def test_iter_root_directory(self, handler):
        """Test iterating over the fixed-size root directory"""
        # Write some files to root
        handler.write_file_to_image("FILE1.TXT", b"1")
        handler.write_file_to_image("FILE2.TXT", b"2")
        
        # Iterate
        entries = list(iter_directory_entries(handler, 0))
        
        # Root has 224 entries fixed
        assert len(entries) == 224
        
        # Check first entry (FILE1)
        idx, data = entries[0]
        assert idx == 0
        assert data[:5] == b"FILE1"
        
        # Check second entry (FILE2)
        idx, data = entries[1]
        assert idx == 1
        assert data[:5] == b"FILE2"

    def test_iter_subdirectory_chain(self, handler):
        """Test iterating over a subdirectory that spans multiple clusters"""
        handler.create_directory("SUBDIR")
        entries = handler.read_root_directory()
        subdir_entry = next(e for e in entries if e['name'] == "SUBDIR")
        cluster = subdir_entry['cluster']
        
        # Fill the subdirectory to force a cluster chain extension
        # 1 cluster = 512 bytes = 16 entries. . and .. take 2.
        # Writing 20 files + 2 existing = 22 entries.
        # This requires 2 clusters (capacity 32 entries).
        for i in range(20):
            handler.write_file_to_image(f"F{i}.TXT", b"x", parent_cluster=cluster)
            
        entries = list(iter_directory_entries(handler, cluster))
        
        # Should yield exactly 32 slots (16 * 2 clusters)
        assert len(entries) == 32
        
        # Verify indices are sequential
        indices = [e[0] for e in entries]
        assert indices == list(range(32))

class TestDirectoryInternals:
    def test_get_entry_offset_root(self, handler):
        """Test offset calculation for root directory"""
        # Index 0 should be at root_start
        offset = get_entry_offset(handler, 0, 0)
        assert offset == handler.root_start
        
        # Index 1 should be 32 bytes later
        offset = get_entry_offset(handler, 0, 1)
        assert offset == handler.root_start + 32

    def test_get_entry_offset_subdir(self, handler):
        """Test offset calculation for subdirectory"""
        handler.create_directory("SUB")
        entries = handler.read_root_directory()
        sub = next(e for e in entries if e['name'] == "SUB")
        cluster = sub['cluster']
        
        # Index 0 of subdir should be at start of that cluster's data
        expected_offset = handler.data_start + ((cluster - 2) * handler.bytes_per_cluster)
        offset = get_entry_offset(handler, cluster, 0)
        assert offset == expected_offset
        
        # Index 16 (start of next cluster, if it existed)
        # Since we only have 1 cluster, this should return -1 or handle chain end
        # get_entry_offset returns -1 if chain ends
        with pytest.raises(FAT12CorruptionError):
            get_entry_offset(handler, cluster, 16)

    def test_get_existing_names(self, handler):
        """Test retrieving existing 8.3 names"""
        handler.write_file_to_image("FILE1.TXT", b"")
        handler.write_file_to_image("FILE2.TXT", b"")
        
        names = get_existing_83_names_in_directory(handler, 0)
        assert "FILE1   TXT" in names
        assert "FILE2   TXT" in names
        assert len(names) == 2

    def test_find_free_entries_gaps(self, handler):
        """Test finding free entries with gaps"""
        handler.write_file_to_image("A.TXT", b"")
        handler.write_file_to_image("B.TXT", b"")
        handler.write_file_to_image("C.TXT", b"")
        
        entries = handler.read_root_directory()
        b_entry = next(e for e in entries if e['name'] == "B.TXT")
        
        # Delete B to create a gap at index 1
        handler.delete_file(b_entry)
        
        # Should find index 1
        idx = find_free_directory_entries(handler, 0, 1)
        assert idx == 1

    def test_find_free_entries_expansion(self, handler):
        """Test that finding entries triggers expansion calculation logic"""
        # Note: Actual expansion happens inside find_free_directory_entries if we call it
        # on a full subdirectory.
        handler.create_directory("FULL")
        sub = next(e for e in handler.read_root_directory() if e['name'] == "FULL")
        
        # Fill the first cluster (16 entries). . and .. take 0 and 1.
        # We write 14 files.
        for i in range(14):
            handler.write_file_to_image(f"F{i}.TXT", b"", parent_cluster=sub['cluster'])
            
        # Now the directory is full (16/16 slots used).
        # Requesting 1 more slot should trigger expansion and return index 16.
        idx = find_free_directory_entries(handler, sub['cluster'], 1)
        assert idx == 16
        
        # Verify the directory actually grew (chain length check)
        chain = handler.get_cluster_chain(sub['cluster'])
        assert len(chain) == 2

class TestFreeClusterChain:
    def test_free_simple_chain(self, handler):
        """Test freeing a simple contiguous chain"""
        # 2 -> 3 -> EOF
        fat = handler.read_fat()
        handler.set_fat_entry(fat, 2, 3)
        handler.set_fat_entry(fat, 3, 0xFFF)
        handler.write_fat(fat)
        
        free_cluster_chain(handler, 2)
        
        fat = handler.read_fat()
        assert handler.get_fat_entry(fat, 2) == 0
        assert handler.get_fat_entry(fat, 3) == 0

    def test_free_single_cluster(self, handler):
        """Test freeing a single cluster"""
        # 5 -> EOF
        fat = handler.read_fat()
        handler.set_fat_entry(fat, 5, 0xFFF)
        handler.write_fat(fat)
        
        free_cluster_chain(handler, 5)
        
        fat = handler.read_fat()
        assert handler.get_fat_entry(fat, 5) == 0

    def test_free_fragmented_chain(self, handler):
        """Test freeing a non-contiguous chain"""
        # 2 -> 10 -> 5 -> EOF
        fat = handler.read_fat()
        handler.set_fat_entry(fat, 2, 10)
        handler.set_fat_entry(fat, 10, 5)
        handler.set_fat_entry(fat, 5, 0xFFF)
        handler.write_fat(fat)
        
        free_cluster_chain(handler, 2)
        
        fat = handler.read_fat()
        assert handler.get_fat_entry(fat, 2) == 0
        assert handler.get_fat_entry(fat, 10) == 0
        assert handler.get_fat_entry(fat, 5) == 0

    def test_ignore_reserved_clusters(self, handler):
        """Test that it ignores start_cluster < 2"""
        # Setup cluster 2 as used
        fat = handler.read_fat()
        handler.set_fat_entry(fat, 2, 0xFFF)
        handler.write_fat(fat)
        
        # Try to free 0 and 1
        free_cluster_chain(handler, 0)
        free_cluster_chain(handler, 1)
        
        # Verify 2 is still used (indirect check that nothing weird happened)
        fat = handler.read_fat()
        assert handler.get_fat_entry(fat, 2) == 0xFFF
        # Verify 0 and 1 are unchanged (usually F0 FF FF for 1.44MB)
        assert fat[0] == 0xF0