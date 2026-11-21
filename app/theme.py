"""Açık / koyu tema. 'sistem' seçiliyse Windows'un ayarını takip eder.

Renkler tek yerde (TOKENS) tanımlı; pencereler, listeler ve çizim alanı buradan okur.
Tema değişince `notifier().changed` sinyali yayılır, kendi çizen bileşenler yeniden boyanır.
"""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from . import icons

MODES = [("sistem", "monitor", "Sistem"), ("acik", "sun", "Açık"), ("koyu", "moon", "Koyu")]   # (anahtar, simge, ad)

PRIMARY = "#335BDB"          # ana düğme (iki temada aynı)
PRIMARY_HOVER = "#2448C4"
LABEL_BG = "#142031"         # kutu başlığı zemini (iki temada aynı)
DRAFT = "#FFDC76"            # çizilmekte olan kutu
EDIT_EDGE = "#FFE08A"        # taşınan kenar

TOKENS = {
    "acik": {
        "shell": "#F7F8FB", "surface": "#FFFFFF", "sub": "#F0F3F8", "line": "#DBE2EB",
        "ink": "#1A2638", "dim": "#536175", "accent": "#335BDB", "accent_ink": "#2748BB",
        "accent_soft": "#EAF0FF", "accent_line": "#AEBFFF", "paper": "#192433",
        "good": "#176046", "good_bg": "#E7F4ED", "warn": "#805008", "warn_bg": "#FFF3D7",
        "danger": "#AB2942", "focus": "#4970FF", "disabled": "#A7B0BE", "ctl": "#B5C0CF",
    },
    "koyu": {
        "shell": "#141C29", "surface": "#1B2534", "sub": "#212D3F", "line": "#324157",
        "ink": "#ECF1F8", "dim": "#ACB8CC", "accent": "#91A7FF", "accent_ink": "#BAC8FF",
        "accent_soft": "#28395F", "accent_line": "#6E88F3", "paper": "#101722",
        "good": "#92E4BF", "good_bg": "#163B32", "warn": "#F9CE81", "warn_bg": "#433419",
        "danger": "#FF9AAC", "focus": "#91A7FF", "disabled": "#5D6B80", "ctl": "#52627A",
    },
}

FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Cascadia Mono"

_mode = "sistem"
_active = "acik"
_notifier = None


class _Notifier(QObject):
    changed = Signal()


def notifier():
    global _notifier
    if _notifier is None:
        _notifier = _Notifier()
    return _notifier


def c(name):
    """Etkin temadaki renk: c('ink'), c('line') ..."""
    return TOKENS[_active][name]


def qc(name, alpha=None):
    col = QColor(c(name))
    if alpha is not None:
        col.setAlpha(alpha)
    return col


def is_dark():
    return _active == "koyu"


def ui_font(px=13, weight=QFont.Weight.Normal):
    f = QFont(FONT_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def mono_font(px=10):
    f = QFont(MONO_FAMILY)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight.DemiBold)
    return f


def _palette(t):
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["shell"],
        QPalette.ColorRole.WindowText: t["ink"],
        QPalette.ColorRole.Base: t["surface"],
        QPalette.ColorRole.AlternateBase: t["sub"],
        QPalette.ColorRole.ToolTipBase: t["surface"],
        QPalette.ColorRole.ToolTipText: t["ink"],
        QPalette.ColorRole.PlaceholderText: t["dim"],
        QPalette.ColorRole.Text: t["ink"],
        QPalette.ColorRole.Button: t["surface"],
        QPalette.ColorRole.ButtonText: t["ink"],
        QPalette.ColorRole.BrightText: t["danger"],
        QPalette.ColorRole.Light: t["surface"],
        QPalette.ColorRole.Midlight: t["sub"],
        QPalette.ColorRole.Mid: t["line"],
        QPalette.ColorRole.Dark: t["line"],
        QPalette.ColorRole.Shadow: "#000000",
        QPalette.ColorRole.Highlight: PRIMARY,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.Link: t["accent_ink"],
        QPalette.ColorRole.LinkVisited: t["accent_ink"],
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["disabled"]))
    return p


def _stylesheet(t):
    chevron = icons.file("chevron-down", t["dim"], 2)
    chevron_r = icons.file("chevron-right", t["dim"], 2)
    check = icons.file("check", "#FFFFFF", 3)
    radio = icons.dot_file("#FFFFFF")
    return f"""
* {{ font-family: "{FONT_FAMILY}"; }}
QMainWindow, QDialog {{ background: {t['shell']}; }}
QWidget {{ color: {t['ink']}; }}
QToolTip {{ background: {t['surface']}; color: {t['ink']}; border: 1px solid {t['line']};
            border-radius: 6px; padding: 5px 7px; }}

/* ---------- yüzeyler ---------- */
QWidget[surface="panel"] {{ background: {t['surface']}; }}
QWidget[surface="shell"] {{ background: {t['shell']}; }}
QFrame[strip="nav"] {{ background: {t['surface']}; border: 0; border-bottom: 1px solid {t['line']}; }}
QFrame[strip="draw"] {{ background: {t['shell']}; border: 0; border-bottom: 1px solid {t['line']}; }}
QFrame[strip="foot"] {{ background: {t['surface']}; border: 0; border-top: 1px solid {t['line']}; }}
QFrame[hline="true"] {{ background: {t['line']}; border: 0; max-height: 1px; min-height: 1px; }}
QFrame[vline="true"] {{ background: {t['line']}; border: 0; max-width: 1px; min-width: 1px; }}
QSplitter::handle {{ background: {t['line']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

/* ---------- yazılar ---------- */
QLabel[role="panelTitle"] {{ font-size: 14px; font-weight: 700; }}
QLabel[role="dialogTitle"] {{ font-size: 18px; font-weight: 700; }}
QLabel[role="muted"] {{ color: {t['dim']}; }}
QLabel[role="small"] {{ color: {t['dim']}; font-size: 11px; }}
QLabel[role="count"] {{ color: {t['dim']}; font-size: 11px; }}
QLabel[role="strong"] {{ font-weight: 700; }}
QLabel[role="error"] {{ color: {t['danger']}; font-weight: 600; }}
QLabel[role="kbd"] {{ font-family: "{MONO_FAMILY}", monospace; font-size: 10px; font-weight: 600;
    color: {t['dim']}; background: {t['sub']}; border: 1px solid {t['line']}; border-radius: 4px;
    padding: 1px 5px; }}
QLabel[role="saved"] {{ color: {t['good']}; }}
QLabel[role="saveError"] {{ color: {t['danger']}; font-weight: 600; }}

/* aktif etiket rozeti */
QFrame[pill="ready"] {{ background: {t['good_bg']}; border-radius: 5px; }}
QFrame[pill="partial"] {{ background: {t['warn_bg']}; border-radius: 5px; }}
QFrame[pill="empty"] {{ background: {t['sub']}; border-radius: 5px; }}
QFrame[pill="ready"] QLabel {{ color: {t['good']}; font-size: 12px; font-weight: 650; }}
QFrame[pill="partial"] QLabel {{ color: {t['warn']}; font-size: 12px; font-weight: 650; }}
QFrame[pill="empty"] QLabel {{ color: {t['dim']}; font-size: 12px; font-weight: 650; }}

/* ---------- düğmeler ---------- */
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 5px 8px; font-weight: 600; color: {t['ink']}; }}
QToolButton:hover {{ background: {t['sub']}; }}
QToolButton:pressed, QToolButton:checked {{ background: {t['line']}; }}
QToolButton:disabled {{ color: {t['disabled']}; }}
QToolButton[outline="true"] {{ border-color: {t['line']}; background: {t['surface']}; }}
QToolButton[outline="true"]:hover {{ background: {t['sub']}; }}
QToolButton[outline="true"]:disabled {{ background: transparent; }}
QToolButton[primary="true"] {{ background: {PRIMARY}; border-color: {PRIMARY}; color: #FFFFFF; }}
QToolButton[primary="true"]:hover {{ background: {PRIMARY_HOVER}; }}
QToolButton[primary="true"]:disabled {{ background: {t['line']}; border-color: {t['line']}; color: {t['disabled']}; }}
QToolButton[chip="filter"] {{ background: {t['accent_soft']}; border-color: {t['accent_line']};
    color: {t['accent_ink']}; padding: 2px 8px; }}
QToolButton[chip="filter"]:hover {{ border-color: {t['accent']}; }}
QToolButton[chip="info"] {{ border-color: {t['line']}; background: {t['surface']}; font-size: 12px;
    padding: 2px 6px; }}
QToolButton[mic="off"] {{ border-color: {t['line']}; color: {t['dim']}; background: {t['surface']}; }}
QToolButton[mic="wait"] {{ border-color: {t['warn_bg']}; color: {t['warn']}; background: {t['warn_bg']}; }}
QToolButton[mic="ptt"] {{ border-color: {t['line']}; color: {t['ink']}; background: {t['surface']}; }}
QToolButton[mic="on"] {{ border-color: {t['good_bg']}; color: {t['good']}; background: {t['good_bg']}; }}
QToolButton[mic="live"] {{ border-color: {t['good']}; color: {t['good']}; background: {t['good_bg']}; }}
QToolButton[mic="none"] {{ border-color: {t['line']}; color: {t['disabled']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[split="true"] {{ padding-right: 24px; }}
QToolButton::menu-button {{ border: 0; border-left: 1px solid {t['line']}; width: 18px;
    border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
QToolButton::menu-button:hover {{ background: {t['sub']}; }}
QToolButton::menu-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}

QPushButton {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 6px;
    padding: 6px 12px; font-weight: 600; color: {t['ink']}; min-height: 18px; }}
QPushButton:hover {{ background: {t['sub']}; }}
QPushButton:pressed {{ background: {t['line']}; }}
QPushButton:disabled {{ color: {t['disabled']}; background: transparent; }}
QPushButton:focus {{ border-color: {t['focus']}; }}
QPushButton[primary="true"] {{ background: {PRIMARY}; border-color: {PRIMARY}; color: #FFFFFF; }}
QPushButton[primary="true"]:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton[primary="true"]:disabled {{ background: {t['line']}; border-color: {t['line']}; color: {t['disabled']}; }}
QPushButton[flat="true"] {{ border-color: transparent; background: transparent; }}
QPushButton[flat="true"]:hover {{ background: {t['sub']}; }}
QPushButton[mini="true"] {{ padding: 4px; min-width: 22px; }}
QPushButton[chip="true"] {{ border-radius: 9px; padding: 1px 8px; font-weight: 600; font-size: 12px;
    background: {t['sub']}; min-height: 16px; }}
QPushButton[chip="true"]:hover {{ border-color: {t['danger']}; color: {t['danger']}; }}

/* ---------- giriş alanları ---------- */
QLineEdit, QComboBox, QSpinBox {{ background: {t['surface']}; border: 1px solid {t['line']};
    border-radius: 6px; padding: 5px 8px; color: {t['ink']};
    selection-background-color: {PRIMARY}; selection-color: #FFFFFF; min-height: 18px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {t['focus']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {t['disabled']}; background: {t['shell']}; }}
QLineEdit[path="true"] {{ background: {t['shell']}; }}
QLineEdit[invalid="true"], QKeySequenceEdit[invalid="true"] QLineEdit {{ border-color: {t['danger']}; }}
QComboBox[filter="true"] {{ background: {t['sub']}; }}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['line']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']}; outline: 0; padding: 3px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: 0; }}
QSpinBox {{ padding-right: 8px; }}

/* ---------- onay / radyo ---------- */
QCheckBox, QRadioButton {{ spacing: 8px; min-height: 22px; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t['disabled']}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px;
    border: 1px solid {t['ctl']}; background: {t['surface']}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t['accent_line']}; }}
QCheckBox::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; image: url({check}); }}
QRadioButton::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; image: url({radio}); }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ background: {t['shell']}; border-color: {t['line']}; }}

/* ---------- gruplar / sekmeler ---------- */
QGroupBox {{ border: 1px solid {t['line']}; border-radius: 7px; margin-top: 12px;
    padding: 14px 10px 8px 10px; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QGroupBox:disabled {{ color: {t['disabled']}; }}
QFrame[column="true"] {{ background: {t['shell']}; border: 1px solid {t['line']}; border-radius: 7px; }}
QFrame[column="true"] QListView {{ background: transparent; }}
QTabWidget::pane {{ border: 0; border-top: 1px solid {t['line']}; top: -1px; }}
QTabBar::tab {{ background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 6px 10px; margin: 0 4px 7px 0; font-weight: 600; color: {t['ink']}; }}
QTabBar::tab:hover {{ background: {t['sub']}; }}
QTabBar::tab:selected {{ background: {t['accent_soft']}; border-color: {t['accent_line']}; color: {t['accent_ink']}; }}

/* ---------- listeler ---------- */
QListView, QTreeView {{ background: {t['surface']}; border: 0; outline: 0; }}
QListView[framed="true"], QTreeView[framed="true"] {{ border: 1px solid {t['line']}; border-radius: 7px; }}
QListView::item {{ border: 1px solid transparent; border-radius: 6px; padding: 4px 6px; margin: 1px 0; color: {t['ink']}; }}
QListView::item:hover {{ background: {t['sub']}; }}
QListView::item:selected {{ background: {t['accent_soft']}; border-color: {t['accent_line']}; color: {t['ink']}; }}
QTreeView::item {{ padding: 3px 2px; color: {t['ink']}; }}
QTreeView::item:hover {{ background: {t['sub']}; }}
QTreeView::item:selected {{ background: {t['accent_soft']}; color: {t['ink']}; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:closed {{ image: url({chevron_r}); }}
QTreeView::branch:has-children:open {{ image: url({chevron}); }}
QHeaderView::section {{ background: {t['surface']}; color: {t['dim']}; border: 0;
    border-bottom: 1px solid {t['line']}; padding: 5px 6px; font-weight: 600; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {t['line']}; border-radius: 3px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {t['dim']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{ background: {t['sub']}; border: 0; border-radius: 2px; max-height: 5px; min-height: 5px; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 2px; }}

/* ---------- menü / araç çubuğu / durum ---------- */
QMenu {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 10px; border-radius: 5px; color: {t['ink']}; }}
QMenu::item:selected {{ background: {t['sub']}; }}
QMenu::item:disabled {{ color: {t['disabled']}; }}
QMenu::separator {{ height: 1px; background: {t['line']}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; padding-left: 6px; }}
QMenu::indicator:checked {{ image: url({icons.file("check", t['accent_ink'], 2.5)}); }}
QToolBar {{ background: {t['surface']}; border: 0; border-bottom: 1px solid {t['line']};
    padding: 8px 12px; spacing: 6px; }}
QToolBar::separator {{ background: {t['line']}; width: 1px; margin: 4px 6px; }}
QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['line']}; color: {t['dim']};
    font-size: 12px; min-height: 30px; }}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ color: {t['dim']}; font-size: 12px; }}
QMessageBox QLabel {{ color: {t['ink']}; }}
"""


def _system_is_dark(app):
    hints = app.styleHints()
    return hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark


def apply(mode):
    """mode: 'sistem' | 'acik' | 'koyu'"""
    global _mode, _active
    _mode = mode if mode in [m[0] for m in MODES] else "sistem"
    app = QApplication.instance()
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):   # Qt 6.8+: pencere başlığı da temaya uyar
        hints.setColorScheme({"acik": Qt.ColorScheme.Light, "koyu": Qt.ColorScheme.Dark}
                             .get(_mode, Qt.ColorScheme.Unknown))
    dark = _mode == "koyu" or (_mode == "sistem" and _system_is_dark(app))
    _active = "koyu" if dark else "acik"
    t = TOKENS[_active]
    app.setFont(ui_font(13))
    app.setPalette(_palette(t))
    app.setStyleSheet(_stylesheet(t))
    notifier().changed.emit()


def follow_system():
    """Sistem teması değişince (mod 'sistem' ise) yeniden uygula."""
    app = QApplication.instance()
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda _: _mode == "sistem" and apply("sistem"))


def repolish(widget):
    """Dinamik özellik (setProperty) değişince QSS'in yeniden uygulanması için."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
