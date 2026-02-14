#!/usr/bin/env python3

# Copyright (c) 2026 Stephen P Smith
# MIT License

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

def get_dark_palette():
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(127, 127, 127))
    
    # Set Disabled colors explicitly
    disabled_color = QColor(127, 127, 127)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_color)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_color)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_color)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(80, 80, 80))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, disabled_color)
    return palette

def get_light_palette():
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(0, 0, 255))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    
    # Set Disabled colors explicitly
    disabled_color = QColor(160, 160, 160)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_color)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_color)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_color)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(200, 200, 200))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, disabled_color)
    return palette

dark_toolbar_stylesheet = """
                QToolBar {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #404040, stop:1 #353535);
                    border-bottom: 1px solid #202020;
                    spacing: 4px;
                    padding: 2px;
                }
                QToolButton {
                    font-size: 10px;
                    min-width: 40px;
                    padding: 2px;
                    margin: 1px;
                    border-radius: 3px;
                    background: transparent;
                    color: #ffffff;
                }
                QToolButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #505050, stop:1 #454545);
                    border: 1px solid #606060;
                }
                QToolButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #303030, stop:1 #404040);
                    border: 1px solid #505050;
                }
                QToolButton:disabled {
                    color: #808080;
                }
            """

light_toolbar_stylesheet = """
                QToolBar {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f8f8f8, stop:1 #e8e8e8);
                    border-bottom: 1px solid #c0c0c0;
                    spacing: 4px;
                    padding: 2px;
                }
                QToolButton {
                    font-size: 10px;
                    min-width: 40px;
                    padding: 2px;
                    margin: 1px;
                    border-radius: 3px;
                    background: transparent;
                }
                QToolButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ffffff, stop:1 #e0e0e0);
                    border: 1px solid #b0b0b0;
                }
                QToolButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #d0d0d0, stop:1 #e8e8e8);
                    border: 1px solid #909090;
                }
                QToolButton:disabled {
                    color: #a0a0a0;
                }
            """

dark_info_label_stylesheet = """
                QLabel {
                    padding-right: 10px;
                    font-weight: bold;
                    font-size: 12px;
                    color: #ffffff;
                    background: transparent;
                }
            """

light_info_label_stylesheet = """
                QLabel {
                    padding-right: 10px;
                    font-weight: bold;
                    font-size: 12px;
                    color: #333333;
                    background: transparent;
                }
            """