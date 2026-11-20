"""Açık / koyu tema. 'sistem' seçiliyse Windows'un ayarını takip eder."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

MODES = [("sistem", "💻", "Sistem"), ("acik", "☀", "Açık"), ("koyu", "🌙", "Koyu")]   # (anahtar, simge, ad)

_mode = "sistem"


def _dark_palette():
    p = QPalette()
    c = {
        QPalette.ColorRole.Window: "#2b2b2b",
        QPalette.ColorRole.WindowText: "#e6e6e6",
        QPalette.ColorRole.Base: "#1f1f1f",
        QPalette.ColorRole.AlternateBase: "#292929",
        QPalette.ColorRole.ToolTipBase: "#353535",
        QPalette.ColorRole.ToolTipText: "#e6e6e6",
        QPalette.ColorRole.PlaceholderText: "#8a8a8a",
        QPalette.ColorRole.Text: "#e6e6e6",
        QPalette.ColorRole.Button: "#353535",
        QPalette.ColorRole.ButtonText: "#e6e6e6",
        QPalette.ColorRole.BrightText: "#ff5555",
        QPalette.ColorRole.Light: "#454545",
        QPalette.ColorRole.Midlight: "#3c3c3c",
        QPalette.ColorRole.Mid: "#2f2f2f",
        QPalette.ColorRole.Dark: "#1a1a1a",
        QPalette.ColorRole.Shadow: "#000000",
        QPalette.ColorRole.Highlight: "#2f80ed",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#5aa9ff",
        QPalette.ColorRole.LinkVisited: "#b48cff",
    }
    for role, color in c.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6e6e6e"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor("#4a4a4a"))
    return p


def _system_is_dark(app):
    hints = app.styleHints()
    return hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark


def apply(mode):
    """mode: 'sistem' | 'acik' | 'koyu'"""
    global _mode
    _mode = mode if mode in [m[0] for m in MODES] else "sistem"
    app = QApplication.instance()
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):   # Qt 6.8+: pencere başlığı da temaya uyar
        hints.setColorScheme({"acik": Qt.ColorScheme.Light, "koyu": Qt.ColorScheme.Dark}
                             .get(_mode, Qt.ColorScheme.Unknown))
    dark = _mode == "koyu" or (_mode == "sistem" and _system_is_dark(app))
    app.setPalette(_dark_palette() if dark else app.style().standardPalette())
    # kendi styleSheet'i olan widget'lar eski paleti tutar; yeniden uygulayınca yeni renkleri alır
    for w in app.allWidgets():
        ss = w.styleSheet()
        if ss:
            w.setStyleSheet("")
            w.setStyleSheet(ss)


def follow_system():
    """Sistem teması değişince (mod 'sistem' ise) yeniden uygula."""
    app = QApplication.instance()
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda _: _mode == "sistem" and apply("sistem"))
