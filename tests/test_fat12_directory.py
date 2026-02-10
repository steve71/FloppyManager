import pytest
from fat12_handler import FAT12Image
from fat12_directory import (
    iter_directory_entries, get_entry_offset, 
    get_existing_83_names_in_directory, find_free_directory_entries
)

@pytest.fixture
def image(tmp_path):
    img_path = tmp_path / "test_dir.img"
    FAT12Image.create_empty_image(str(img_path))
    return FAT12Image(str(img_path))

class TestDirectoryCreation:
    def test_create_directory_root(self, image):
        assert image.create_directory("TESTDIR")
        entries = image.read_root_directory()
        entry = next((e for e in entries if e['name'] == "TESTDIR"), None)
        assert entry is not None
        assert entry['is_dir']
        assert entry['cluster'] >= 2

    def test_create_nested_directory(self, image):
        image.create_directory("PARENT")
        parent = next(e for e in image.read_root_directory() if e['name'] == "PARENT")
        
        assert image.create_directory("CHILD", parent_cluster=parent['cluster'])
        
        sub_entries = image.read_directory(parent['cluster'])
        child = next((e for e in sub_entries if e['name'] == "CHILD"), None)
        assert child is not None
        assert child['is_dir']

class TestDirectoryDeletion:
    def test_delete_empty_directory(self, image):
        image.create_directory("EMPTY")
        entry = next(e for e in image.read_root_directory() if e['name'] == "EMPTY")
        
        assert image.delete_directory(entry)
        
        entries = image.read_root_directory()
        assert not any(e['name'] == "EMPTY" for e in entries)

    def test_delete_non_empty_directory_fails(self, image):
        image.create_directory("FULL")
        entry = next(e for e in image.read_root_directory() if e['name'] == "FULL")
        
        image.write_file_to_image("FILE.TXT", b"data", parent_cluster=entry['cluster'])
        
        # Should fail without recursive=True
        assert not image.delete_directory(entry)

    def test_delete_recursive(self, image):
        image.create_directory("RECURSIVE")
        entry = next(e for e in image.read_root_directory() if e['name'] == "RECURSIVE")
        
        image.write_file_to_image("FILE.TXT", b"data", parent_cluster=entry['cluster'])
        
        assert image.delete_directory(entry, recursive=True)
        
        entries = image.read_root_directory()
        assert not any(e['name'] == "RECURSIVE" for e in entries)

class TestFileOperationsInDirectory:
    def test_write_file_to_subdir(self, image):
        image.create_directory("DOCS")
        docs = next(e for e in image.read_root_directory() if e['name'] == "DOCS")
        
        assert image.write_file_to_image("NOTE.TXT", b"content", parent_cluster=docs['cluster'])
        
        sub_entries = image.read_directory(docs['cluster'])
        file_entry = next((e for e in sub_entries if e['name'] == "NOTE.TXT"), None)
        assert file_entry is not None
        assert file_entry['size'] == 7

    def test_delete_file_in_subdir(self, image):
        image.create_directory("TRASH")
        trash = next(e for e in image.read_root_directory() if e['name'] == "TRASH")
        
        image.write_file_to_image("JUNK.TXT", b"junk", parent_cluster=trash['cluster'])
        
        sub_entries = image.read_directory(trash['cluster'])
        junk = next(e for e in sub_entries if e['name'] == "JUNK.TXT")
        
        assert image.delete_file(junk)
        
        sub_entries = image.read_directory(trash['cluster'])
        assert not any(e['name'] == "JUNK.TXT" for e in sub_entries)

class TestIterDirectoryEntries:
    def test_iter_root_directory(self, image):
        """Test iterating over the fixed-size root directory"""
        # Write some files to root
        image.write_file_to_image("FILE1.TXT", b"1")
        image.write_file_to_image("FILE2.TXT", b"2")
        
        # Iterate
        entries = list(iter_directory_entries(image, 0))
        
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

    def test_iter_subdirectory_chain(self, image):
        """Test iterating over a subdirectory that spans multiple clusters"""
        image.create_directory("SUBDIR")
        entries = image.read_root_directory()
        subdir_entry = next(e for e in entries if e['name'] == "SUBDIR")
        cluster = subdir_entry['cluster']
        
        # Fill the subdirectory to force a cluster chain extension
        # 1 cluster = 512 bytes = 16 entries. . and .. take 2.
        # Writing 20 files + 2 existing = 22 entries.
        # This requires 2 clusters (capacity 32 entries).
        for i in range(20):
            image.write_file_to_image(f"F{i}.TXT", b"x", parent_cluster=cluster)
            
        entries = list(iter_directory_entries(image, cluster))
        
        # Should yield exactly 32 slots (16 * 2 clusters)
        assert len(entries) == 32
        
        # Verify indices are sequential
        indices = [e[0] for e in entries]
        assert indices == list(range(32))

class TestDirectoryInternals:
    def test_get_entry_offset_root(self, image):
        """Test offset calculation for root directory"""
        # Index 0 should be at root_start
        offset = get_entry_offset(image, 0, 0)
        assert offset == image.root_start
        
        # Index 1 should be 32 bytes later
        offset = get_entry_offset(image, 0, 1)
        assert offset == image.root_start + 32

    def test_get_entry_offset_subdir(self, image):
        """Test offset calculation for subdirectory"""
        image.create_directory("SUB")
        entries = image.read_root_directory()
        sub = next(e for e in entries if e['name'] == "SUB")
        cluster = sub['cluster']
        
        # Index 0 of subdir should be at start of that cluster's data
        expected_offset = image.data_start + ((cluster - 2) * image.bytes_per_cluster)
        offset = get_entry_offset(image, cluster, 0)
        assert offset == expected_offset
        
        # Index 16 (start of next cluster, if it existed)
        # Since we only have 1 cluster, this should return -1 or handle chain end
        # get_entry_offset returns -1 if chain ends
        offset = get_entry_offset(image, cluster, 16)
        assert offset == -1

    def test_get_existing_names(self, image):
        """Test retrieving existing 8.3 names"""
        image.write_file_to_image("FILE1.TXT", b"")
        image.write_file_to_image("FILE2.TXT", b"")
        
        names = get_existing_83_names_in_directory(image, 0)
        assert "FILE1   TXT" in names
        assert "FILE2   TXT" in names
        assert len(names) == 2

    def test_find_free_entries_gaps(self, image):
        """Test finding free entries with gaps"""
        image.write_file_to_image("A.TXT", b"")
        image.write_file_to_image("B.TXT", b"")
        image.write_file_to_image("C.TXT", b"")
        
        entries = image.read_root_directory()
        b_entry = next(e for e in entries if e['name'] == "B.TXT")
        
        # Delete B to create a gap at index 1
        image.delete_file(b_entry)
        
        # Should find index 1
        idx = find_free_directory_entries(image, 0, 1)
        assert idx == 1

    def test_find_free_entries_expansion(self, image):
        """Test that finding entries triggers expansion calculation logic"""
        # Note: Actual expansion happens inside find_free_directory_entries if we call it
        # on a full subdirectory.
        image.create_directory("FULL")
        sub = next(e for e in image.read_root_directory() if e['name'] == "FULL")
        
        # Fill the first cluster (16 entries). . and .. take 0 and 1.
        # We write 14 files.
        for i in range(14):
            image.write_file_to_image(f"F{i}.TXT", b"", parent_cluster=sub['cluster'])
            
        # Now the directory is full (16/16 slots used).
        # Requesting 1 more slot should trigger expansion and return index 16.
        idx = find_free_directory_entries(image, sub['cluster'], 1)
        assert idx == 16
        
        # Verify the directory actually grew (chain length check)
        chain = image.get_cluster_chain(sub['cluster'])
        assert len(chain) == 2