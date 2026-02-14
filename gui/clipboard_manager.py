#!/usr/bin/env python3

# Copyright (c) 2026 Stephen P Smith
# MIT License

"""
Clipboard Manager for FloppyManager
Handles copy/cut/paste operations for FAT12 image files
"""

import os
import tempfile
import shutil
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

from PySide6.QtCore import QUrl, QMimeData
from PySide6.QtWidgets import QApplication


@dataclass
class ClipboardResult:
    """Result of a clipboard operation"""
    success: bool = False
    message: str = ""
    error: Optional[str] = None
    file_count: int = 0
    excluded_dirs: int = 0
    is_cut_operation: bool = False


class ClipboardManager:
    """Manages clipboard operations for FAT12 image files
    
    This class handles:
    - Copying files from FAT12 image to system clipboard
    - Cutting files (copy + mark for deletion)
    - Pasting files from clipboard to FAT12 image
    - Temporary file management
    - Internal operation detection
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize clipboard manager
        
        Args:
            logger: Logger instance for operation logging
        """
        self.logger = logger or logging.getLogger(__name__)
        
        # Temporary directory for clipboard files
        self._temp_dir: Optional[str] = None
        
        # Source cluster where files were copied from
        self._source_cluster: Optional[int] = None
        
        # Entries marked for cut (move) operation
        self._cut_entries: List[dict] = []
    
    def copy_files(self, entries: List[dict], image) -> ClipboardResult:
        """Copy files from FAT12 image to system clipboard
        
        Args:
            entries: List of file entry dictionaries from FAT12 image
            image: FAT12Image instance
            
        Returns:
            ClipboardResult with operation status
        """
        result = ClipboardResult()
        
        # Cancel any pending cut operation
        if self._cut_entries:
            self._cut_entries = []
            self.logger.debug("Cancelled pending cut operation")
        
        # Separate files and directories
        files = [e for e in entries if not e.get('is_dir', False)]
        dirs = [e for e in entries if e.get('is_dir', False)]
        
        result.excluded_dirs = len(dirs)
        
        if not files:
            result.message = "No files selected to copy"
            return result
        
        # Store source cluster for duplicate detection
        if files:
            self._source_cluster = self._normalize_cluster(
                files[0].get('parent_cluster')
            )
        
        # Cleanup previous temp directory
        self.cleanup()
        
        # Create new temp directory
        self._temp_dir = tempfile.mkdtemp(prefix="fat12_copy_")
        self.logger.debug(f"Created temp directory: {self._temp_dir}")
        
        # Extract files to temp directory
        urls = []
        for entry in files:
            try:
                data = image.extract_file(entry)
                filename = entry['name']
                filepath = os.path.join(self._temp_dir, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(data)
                
                urls.append(QUrl.fromLocalFile(filepath))
                self.logger.debug(f"Extracted file for copy: {filename}")
                
            except Exception as e:
                self.logger.warning(
                    f"Failed to extract {entry.get('name', 'unknown')} for copy: {e}"
                )
        
        # Set clipboard data
        if urls:
            mime_data = QMimeData()
            mime_data.setUrls(urls)
            QApplication.clipboard().setMimeData(mime_data)
            
            result.success = True
            result.file_count = len(urls)
            result.message = f"Copied {len(urls)} file(s) to clipboard"
            self.logger.info(result.message)
        else:
            result.message = "Failed to copy files"
            self.logger.warning(result.message)
        
        return result
    
    def cut_files(self, entries: List[dict], image) -> ClipboardResult:
        """Cut files (copy to clipboard and mark for deletion)
        
        Args:
            entries: List of file entry dictionaries from FAT12 image
            image: FAT12Image instance
            
        Returns:
            ClipboardResult with operation status
        """
        # First copy the files
        result = self.copy_files(entries, image)
        
        if result.success:
            # Mark files for deletion after paste
            self._cut_entries = [e for e in entries if not e.get('is_dir', False)]
            result.is_cut_operation = True
            result.message = f"Cut {result.file_count} file(s)"
            self.logger.info(result.message)
        
        return result
    
    def paste_files(self, image, target_cluster: Optional[int], 
                   rename_on_collision: bool = False) -> ClipboardResult:
        """Paste files from clipboard to FAT12 image
        
        Args:
            image: FAT12Image instance
            target_cluster: Target directory cluster (None for root)
            rename_on_collision: If True, rename files on collision
            
        Returns:
            ClipboardResult with operation status
        """
        result = ClipboardResult()
        
        # Get clipboard data
        mime_data = QApplication.clipboard().mimeData()
        if not mime_data or not mime_data.hasUrls():
            result.message = "Clipboard is empty or contains no files"
            return result
        
        # Extract file paths from clipboard
        files = []
        for url in mime_data.urls():
            if url.isLocalFile():
                fpath = url.toLocalFile()
                if os.path.isfile(fpath):
                    files.append(fpath)
        
        if not files:
            result.message = "No valid files in clipboard"
            return result
        
        # Check if this is an internal operation
        is_internal_cut, is_internal_copy = self._check_internal_operation(files)
        
        # Handle external clipboard content during pending cut
        if self._cut_entries and not is_internal_cut:
            self._cut_entries = []
            result.message = "External clipboard content detected. Cut operation cancelled."
            self.logger.info(result.message)
            return result
        
        # Normalize target cluster
        target_cluster = self._normalize_cluster(target_cluster)
        
        # Check if pasting to same location (cut only)
        if self._cut_entries:
            first_cut = self._cut_entries[0]
            src_parent = self._normalize_cluster(first_cut.get('parent_cluster'))
            
            if src_parent == target_cluster:
                self._cut_entries = []
                QApplication.clipboard().clear()
                result.message = "Source and destination are the same. Move cancelled."
                self.logger.info(result.message)
                return result
        
        # Determine rename behavior
        should_rename = rename_on_collision
        
        # Auto-rename for internal copy to same folder
        if is_internal_copy and self._source_cluster == target_cluster:
            should_rename = True
            self.logger.debug("Enabled auto-rename for duplicate operation")
        
        # Disable rename for cut operations
        if self._cut_entries:
            should_rename = False
        
        result.file_count = len(files)
        result.is_cut_operation = bool(self._cut_entries)
        
        # This will be handled by the caller (floppymanager.py)
        # as it needs access to add_files_from_list() method
        result.success = True
        result.message = "Ready to paste"
        
        return result
    
    def get_paste_info(self) -> Tuple[List[str], bool, bool]:
        """Get information about clipboard files for pasting
        
        Returns:
            Tuple of (file_paths, rename_on_collision, is_cut_operation)
        """
        mime_data = QApplication.clipboard().mimeData()
        if not mime_data or not mime_data.hasUrls():
            return [], False, False
        
        files = []
        for url in mime_data.urls():
            if url.isLocalFile():
                fpath = url.toLocalFile()
                if os.path.isfile(fpath):
                    files.append(fpath)
        
        is_internal_cut, is_internal_copy = self._check_internal_operation(files)
        
        rename = is_internal_copy and not is_internal_cut
        is_cut = bool(self._cut_entries)
        
        return files, rename, is_cut
    
    def get_cut_entries(self) -> List[dict]:
        """Get entries marked for cut operation
        
        Returns:
            List of entry dictionaries
        """
        return self._cut_entries.copy()
    
    def complete_cut_operation(self) -> None:
        """Complete a cut operation by clearing cut entries"""
        self._cut_entries = []
        self.cleanup()
        QApplication.clipboard().clear()
        self.logger.info("Cut operation completed")
    
    def cancel_cut(self) -> None:
        """Cancel pending cut operation without deleting files"""
        if self._cut_entries:
            self._cut_entries = []
            self.logger.info("Cut operation cancelled")
    
    def has_clipboard_data(self) -> bool:
        """Check if clipboard contains file data
        
        Returns:
            True if clipboard has files
        """
        mime_data = QApplication.clipboard().mimeData()
        return mime_data is not None and mime_data.hasUrls()
    
    def is_cut_pending(self) -> bool:
        """Check if there's a pending cut operation
        
        Returns:
            True if cut operation is pending
        """
        return len(self._cut_entries) > 0
    
    def cleanup(self) -> None:
        """Clean up temporary directory"""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir)
                self.logger.info(f"Cleaned up temp directory: {self._temp_dir}")
            except Exception as e:
                self.logger.warning(f"Failed to cleanup temp directory: {e}")
            finally:
                self._temp_dir = None
    
    def _check_internal_operation(self, files: List[str]) -> Tuple[bool, bool]:
        """Check if files are from internal temp directory
        
        Args:
            files: List of file paths
            
        Returns:
            Tuple of (is_internal_cut, is_internal_copy)
        """
        if not self._temp_dir or not files:
            return False, False
        
        try:
            temp_parent = Path(self._temp_dir).resolve()
            
            # Check if all files are from our temp directory
            all_internal = all(
                Path(f).parent.resolve() == temp_parent 
                for f in files
            )
            
            if not all_internal:
                return False, False
            
            # It's internal - determine if cut or copy
            is_cut = bool(self._cut_entries)
            is_copy = not is_cut
            
            return is_cut, is_copy
            
        except Exception as e:
            self.logger.warning(f"Failed to verify internal operation: {e}")
            return False, False
    
    @staticmethod
    def _normalize_cluster(cluster: Optional[int]) -> int:
        """Normalize cluster number for comparison
        
        Args:
            cluster: Cluster number or None
            
        Returns:
            Normalized cluster number (0 for None/root)
        """
        return 0 if cluster is None else cluster
