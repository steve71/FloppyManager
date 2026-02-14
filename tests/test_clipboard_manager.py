#!/usr/bin/env python3

# Copyright (c) 2026 Stephen P Smith
# MIT License

"""
Pytest tests for ClipboardManager

Tests the clipboard functionality independently of the UI.
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch
from pathlib import Path

from gui.clipboard_manager import ClipboardManager, ClipboardResult


@pytest.fixture
def mock_logger():
    """Fixture for mock logger"""
    return Mock()


@pytest.fixture
def clipboard_mgr(mock_logger):
    """Fixture for ClipboardManager instance"""
    mgr = ClipboardManager(mock_logger)
    yield mgr
    # Cleanup after each test
    mgr.cleanup()


@pytest.fixture
def mock_image():
    """Fixture for mock FAT12Image"""
    image = Mock()
    image.extract_file = Mock(return_value=b"test data")
    return image


@pytest.fixture
def test_entries():
    """Fixture for test file entries"""
    return [
        {
            'name': 'test1.txt',
            'is_dir': False,
            'cluster': 10,
            'parent_cluster': 0,
            'index': 0
        },
        {
            'name': 'test2.txt',
            'is_dir': False,
            'cluster': 11,
            'parent_cluster': 0,
            'index': 1
        },
        {
            'name': 'testdir',
            'is_dir': True,
            'cluster': 12,
            'parent_cluster': 0,
            'index': 2
        }
    ]


class TestClipboardManagerInitialization:
    """Tests for ClipboardManager initialization"""
    
    def test_initialization(self, clipboard_mgr):
        """Test clipboard manager initializes with correct defaults"""
        assert clipboard_mgr._temp_dir is None
        assert clipboard_mgr._source_cluster is None
        assert len(clipboard_mgr._cut_entries) == 0


class TestCopyFiles:
    """Tests for copy_files functionality"""
    
    def test_copy_files_success(self, clipboard_mgr, mock_image, test_entries):
        """Test successful file copy operation"""
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            # Mock clipboard
            mock_clipboard = Mock()
            mock_qapp.clipboard.return_value = mock_clipboard
            
            # Perform copy
            result = clipboard_mgr.copy_files(test_entries, mock_image)
            
            # Verify result
            assert result.success is True
            assert result.file_count == 2  # 2 files, 1 dir excluded
            assert result.excluded_dirs == 1
            assert "Copied 2 file(s)" in result.message
            
            # Verify temp directory created
            assert clipboard_mgr._temp_dir is not None
            assert os.path.exists(clipboard_mgr._temp_dir)
            
            # Verify files were extracted
            assert mock_image.extract_file.call_count == 2
            
            # Verify clipboard was set
            mock_clipboard.setMimeData.assert_called_once()
    
    def test_copy_files_excludes_directories(self, clipboard_mgr, mock_image, test_entries):
        """Test that directories are excluded from copy"""
        with patch('gui.clipboard_manager.QApplication'):
            result = clipboard_mgr.copy_files(test_entries, mock_image)
            
            # Should exclude 1 directory
            assert result.excluded_dirs == 1
            
            # Should only extract 2 files
            assert mock_image.extract_file.call_count == 2
    
    def test_copy_files_empty_selection(self, clipboard_mgr, mock_image):
        """Test copy with no files selected"""
        with patch('gui.clipboard_manager.QApplication'):
            result = clipboard_mgr.copy_files([], mock_image)
            
            assert result.success is False
            assert result.file_count == 0
            assert "No files selected" in result.message
    
    def test_copy_files_only_directories(self, clipboard_mgr, mock_image, test_entries):
        """Test copy with only directories selected"""
        dir_only = [e for e in test_entries if e['is_dir']]
        
        with patch('gui.clipboard_manager.QApplication'):
            result = clipboard_mgr.copy_files(dir_only, mock_image)
            
            assert result.success is False
            assert result.excluded_dirs == 1
            assert result.file_count == 0
    
    def test_copy_files_extraction_failure(self, clipboard_mgr, test_entries):
        """Test copy when file extraction fails"""
        # Mock image with failing extract
        mock_image = Mock()
        mock_image.extract_file = Mock(side_effect=Exception("Extract failed"))
        
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            mock_clipboard = Mock()
            mock_qapp.clipboard.return_value = mock_clipboard
            
            result = clipboard_mgr.copy_files(test_entries, mock_image)
            
            # Should fail gracefully
            assert result.success is False
            assert result.file_count == 0


class TestCutFiles:
    """Tests for cut_files functionality"""
    
    def test_cut_files(self, clipboard_mgr, mock_image, test_entries):
        """Test cut operation"""
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            mock_clipboard = Mock()
            mock_qapp.clipboard.return_value = mock_clipboard
            
            result = clipboard_mgr.cut_files(test_entries, mock_image)
            
            # Verify cut was successful
            assert result.success is True
            assert result.is_cut_operation is True
            assert "Cut" in result.message
            
            # Verify entries were marked for deletion
            assert len(clipboard_mgr._cut_entries) == 2  # 2 files
    
    def test_cut_cancels_previous_cut(self, clipboard_mgr, mock_image, test_entries):
        """Test that new cut cancels previous cut"""
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            mock_clipboard = Mock()
            mock_qapp.clipboard.return_value = mock_clipboard
            
            # First cut
            clipboard_mgr.cut_files([test_entries[0]], mock_image)
            assert len(clipboard_mgr._cut_entries) == 1
            
            # Second cut should replace
            clipboard_mgr.cut_files([test_entries[1]], mock_image)
            assert len(clipboard_mgr._cut_entries) == 1
            assert clipboard_mgr._cut_entries[0]['name'] == 'test2.txt'
    
    def test_copy_cancels_cut(self, clipboard_mgr, mock_image, test_entries):
        """Test that copy operation cancels pending cut"""
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            mock_clipboard = Mock()
            mock_qapp.clipboard.return_value = mock_clipboard
            
            # Set up a cut operation
            clipboard_mgr._cut_entries = [test_entries[0]]
            
            # Perform copy
            clipboard_mgr.copy_files(test_entries, mock_image)
            
            # Cut should be cancelled
            assert len(clipboard_mgr._cut_entries) == 0


class TestClipboardState:
    """Tests for clipboard state management"""
    
    def test_has_clipboard_data(self, clipboard_mgr):
        """Test clipboard data detection"""
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            # Mock clipboard with URLs
            mock_clipboard = Mock()
            mock_mime_data = Mock()
            mock_mime_data.hasUrls.return_value = True
            mock_clipboard.mimeData.return_value = mock_mime_data
            mock_qapp.clipboard.return_value = mock_clipboard
            
            assert clipboard_mgr.has_clipboard_data() is True
            
            # Mock empty clipboard
            mock_mime_data.hasUrls.return_value = False
            assert clipboard_mgr.has_clipboard_data() is False
    
    def test_is_cut_pending(self, clipboard_mgr, test_entries):
        """Test cut pending detection"""
        # Initially no cut pending
        assert clipboard_mgr.is_cut_pending() is False
        
        # Set cut entries
        clipboard_mgr._cut_entries = [test_entries[0]]
        assert clipboard_mgr.is_cut_pending() is True
        
        # Clear cut entries
        clipboard_mgr._cut_entries = []
        assert clipboard_mgr.is_cut_pending() is False
    
    def test_cancel_cut(self, clipboard_mgr, test_entries):
        """Test cancelling a cut operation"""
        clipboard_mgr._cut_entries = [test_entries[0]]
        
        clipboard_mgr.cancel_cut()
        
        assert len(clipboard_mgr._cut_entries) == 0
    
    def test_complete_cut_operation(self, clipboard_mgr, test_entries):
        """Test completing a cut operation"""
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            mock_clipboard = Mock()
            mock_qapp.clipboard.return_value = mock_clipboard
            
            # Set up cut state
            clipboard_mgr._cut_entries = [test_entries[0]]
            clipboard_mgr._temp_dir = tempfile.mkdtemp()
            
            # Complete operation
            clipboard_mgr.complete_cut_operation()
            
            # Verify cleanup
            assert len(clipboard_mgr._cut_entries) == 0
            mock_clipboard.clear.assert_called_once()


class TestCleanup:
    """Tests for cleanup functionality"""
    
    def test_cleanup(self, clipboard_mgr, mock_image, test_entries):
        """Test cleanup of temporary directory"""
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            mock_clipboard = Mock()
            mock_qapp.clipboard.return_value = mock_clipboard
            
            # Create temp dir through copy
            clipboard_mgr.copy_files(test_entries, mock_image)
            
            temp_dir = clipboard_mgr._temp_dir
            assert os.path.exists(temp_dir)
            
            # Cleanup
            clipboard_mgr.cleanup()
            
            # Verify cleanup
            assert not os.path.exists(temp_dir)
            assert clipboard_mgr._temp_dir is None


class TestUtilityMethods:
    """Tests for utility methods"""
    
    def test_normalize_cluster(self):
        """Test cluster normalization"""
        # None should become 0
        assert ClipboardManager._normalize_cluster(None) == 0
        
        # Regular number stays the same
        assert ClipboardManager._normalize_cluster(42) == 42
        
        # 0 stays 0
        assert ClipboardManager._normalize_cluster(0) == 0
    
    def test_source_cluster_tracking(self, clipboard_mgr, mock_image):
        """Test that source cluster is tracked correctly"""
        with patch('gui.clipboard_manager.QApplication') as mock_qapp:
            mock_clipboard = Mock()
            mock_qapp.clipboard.return_value = mock_clipboard
            
            # Copy files with parent_cluster = 5
            entries = [
                {
                    'name': 'test.txt',
                    'is_dir': False,
                    'cluster': 10,
                    'parent_cluster': 5,
                    'index': 0
                }
            ]
            
            clipboard_mgr.copy_files(entries, mock_image)
            
            # Verify source cluster was set
            assert clipboard_mgr._source_cluster == 5


class TestClipboardResult:
    """Tests for ClipboardResult dataclass"""
    
    def test_default_values(self):
        """Test default result values"""
        result = ClipboardResult()
        
        assert result.success is False
        assert result.message == ""
        assert result.error is None
        assert result.file_count == 0
        assert result.excluded_dirs == 0
        assert result.is_cut_operation is False
    
    def test_custom_values(self):
        """Test setting custom values"""
        result = ClipboardResult(
            success=True,
            message="Test message",
            file_count=5,
            excluded_dirs=2,
            is_cut_operation=True
        )
        
        assert result.success is True
        assert result.message == "Test message"
        assert result.file_count == 5
        assert result.excluded_dirs == 2
        assert result.is_cut_operation is True
