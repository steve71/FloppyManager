#!/usr/bin/env python3

# Copyright (c) 2026 Stephen P Smith
# MIT License

"""
File Icon Helper for FAT12 FloppyManager
Maps file extensions to appropriate Qt StandardPixmap icons
"""

from PySide6.QtWidgets import QStyle
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

class FileIconProvider:
    """Provides icons for different file types"""
    
    # File type categories mapped to Qt standard icons
    ICON_MAP = {
        # Audio/Music files
        'audio': [
            'MP3', 'WAV', 'MID', 'MIDI', 'OGG', 'FLAC', 'AAC', 'WMA', 
            'M4A', 'STY', 'SFF', 'KAR', 'RMI'
        ],
        
        # Image files
        'image': [
            'JPG', 'JPEG', 'PNG', 'GIF', 'BMP', 'TIF', 'TIFF', 'ICO', 
            'SVG', 'WEBP', 'PCX', 'TGA'
        ],
        
        # Document files
        'document': [
            'TXT', 'DOC', 'DOCX', 'PDF', 'RTF', 'ODT', 'TEX', 'WPD',
            'LOG', 'README', 'NFO', 'DIZ'
        ],
        
        # Code/Script files
        'code': [
            'PY', 'C', 'CPP', 'H', 'HPP', 'JAVA', 'JS', 'HTML', 'CSS',
            'PHP', 'RB', 'PL', 'SH', 'BAT', 'CMD', 'VBS', 'PS1',
            'JSON', 'XML', 'YAML', 'YML', 'INI', 'CFG', 'CONF'
        ],
        
        # Archive files
        'archive': [
            'ZIP', 'RAR', 'TAR', 'GZ', 'BZ2', '7Z', 'CAB', 'ISO',
            'ARJ', 'LZH', 'ACE', 'JAR', 'WAR'
        ],
    }
    
    # Special Yamaha keyboard files
    YAMAHA_FILES = {
        'STY': 'Yamaha Style File',
        'SFF': 'Yamaha Style File Format',
        'MID': 'MIDI File',
        'MIDI': 'MIDI File',
        'KAR': 'Karaoke MIDI File',
        'RMI': 'RIFF MIDI File'
    }
    
    def __init__(self, style):
        """
        Initialize the icon provider
        
        Args:
            style: QStyle instance from the application
        """
        self.style = style
        self._cache = {}
    
    def get_icon(self, entry: dict) -> QIcon:
        """
        Get appropriate icon for a file entry
        
        Args:
            entry: File entry dictionary with 'is_dir' and 'file_type' keys
            
        Returns:
            QIcon for the file type
        """
        # Directory
        if entry.get('is_dir', False):
            return self.style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        
        # Get file extension
        file_type = entry.get('file_type', '').upper()
        
        # Check cache first
        if file_type in self._cache:
            return self._cache[file_type]
        
        # Determine icon based on file type
        icon = self._get_icon_for_type(file_type)
        
        # Cache it
        self._cache[file_type] = icon
        return icon
    
    def _get_icon_for_type(self, file_type: str) -> QIcon:
        """Get icon based on file extension"""
        
        # Check each category
        for category, extensions in self.ICON_MAP.items():
            if file_type in extensions:
                return self._get_category_icon(category, file_type)
        
        # Default to generic file icon
        return self.style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
    
    def _get_category_icon(self, category: str, file_type: str) -> QIcon:
        """
        Get icon for a specific category
        """
        # Map categories to Qt standard icons where available
        if category == 'audio':
            # Use media player icon or create a custom colored icon
            # Qt doesn't have a dedicated audio icon, so we'll create one
            return self.style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        
        elif category == 'image':
            return self.style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        
        elif category == 'document':
            return self.style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        
        elif category == 'code':
            return self._create_colored_icon('#2196F3', '<>')  # Blue code brackets
        
        elif category == 'archive':
            return self._create_colored_icon('#795548', '⊟')  # Brown box
        
        # Fallback
        return self.style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
    
    def _create_colored_icon(self, color: str, symbol: str = '') -> QIcon:
        """
        Create a simple colored icon with optional symbol
        
        Args:
            color: Hex color string (e.g., '#FF0000')
            symbol: Optional single character or symbol to display
            
        Returns:
            QIcon with colored background
        """
        # Create a 16x16 pixmap
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw colored rectangle with slight border
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(1, 2, 14, 12, 2, 2)
        
        # Add white border
        painter.setPen(QColor('#FFFFFF'))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(1, 2, 14, 12, 2, 2)
        
        # Draw symbol if provided
        if symbol:
            painter.setPen(QColor('#FFFFFF'))
            painter.setFont(painter.font())
            font = painter.font()
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(1, 2, 14, 12, Qt.AlignmentFlag.AlignCenter, symbol)
        
        painter.end()
        
        return QIcon(pixmap)
    
    def get_file_type_description(self, file_type: str) -> str:
        """
        Get a human-readable description of a file type
        
        Args:
            file_type: File extension (e.g., 'STY', 'MID')
            
        Returns:
            Description string
        """
        file_type = file_type.upper()
        
        # Check Yamaha-specific files first
        if file_type in self.YAMAHA_FILES:
            return self.YAMAHA_FILES[file_type]
        
        # Check categories
        for category, extensions in self.ICON_MAP.items():
            if file_type in extensions:
                return f"{category.title()} File"
        
        # Unknown
        return f"{file_type} File" if file_type else "File"


# Convenience function
def get_file_icon(style, entry: dict) -> QIcon:
    """
    Convenience function to get an icon for a file entry
    
    Args:
        style: QStyle instance
        entry: File entry dictionary
        
    Returns:
        Appropriate QIcon for the file
    """
    provider = FileIconProvider(style)
    return provider.get_icon(entry)
