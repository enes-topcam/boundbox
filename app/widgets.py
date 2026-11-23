"""Ortak arayüz parçaları: simgeli düğmeler, tuş rozeti, renk noktası, seçim düğmesi."""
import shiboken6
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QToolButton, QWidget,
)

from . import icons, theme

# ---------------------------------------------------------------------------
#  Temaya göre renklenen simgeler
# ---------------------------------------------------------------------------
_bound = []      # [(widget, simge adı, renk rolü)]


def set_icon(widget, name, role="ink"):
    """Düğmeye simge koyar; tema değişince simge yeni renge boyanır.
    role: tema rengi adı ('ink', 'dim', 'accent_ink' ...) ya da '#rrggbb'."""
    for i, (w, _n, _r) in enumerate(_bound):
        if w is widget:
            _bound[i] = (widget, name, role)
            break
    else:
        _bound.append((widget, name, role))
    _apply_icon(widget, name, role)


def _apply_icon(widget, name, role):
    color = role if role.startswith("#") else theme.c(role)
    widget.setIcon(icons.icon(name, color, disabled=theme.c("disabled")))


def _refresh_icons():
    alive = []
    for w, name, role in _bound:
        if shiboken6.isValid(w):
            _apply_icon(w, name, role)
            alive.append((w, name, role))
    _bound[:] = alive


_hooked = False


def hook_theme():
    """Uygulama başlarken bir kere çağrılır."""
    global _hooked
    if not _hooked:
        theme.notifier().changed.connect(_refresh_icons)
        _hooked = True


def prop(widget, name, value):
    """QSS'in okuduğu dinamik özellik; değişince yeniden boyar."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        theme.repolish(widget)


# ---------------------------------------------------------------------------
#  Küçük parçalar
# ---------------------------------------------------------------------------
def tool_button(text="", icon=None, tip="", slot=None, outline=False, primary=False, role="ink",
                square=False):
    b = QToolButton()
    if text:
        b.setText(text)
    if icon:
        set_icon(b, icon, "#FFFFFF" if primary else role)
        b.setIconSize(QSize(17, 17) if not square else QSize(16, 16))
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text
                         else Qt.ToolButtonStyle.ToolButtonIconOnly)
    if tip:
        b.setToolTip(tip)
    if outline:
        b.setProperty("outline", True)
    if primary:
        b.setProperty("primary", True)
    if square:
        b.setFixedSize(32, 32)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def push_button(text, icon=None, slot=None, primary=False, role="ink"):
    b = QPushButton(text)
    if icon:
        set_icon(b, icon, "#FFFFFF" if primary else role)
        b.setIconSize(QSize(16, 16))
    if primary:
        b.setProperty("primary", True)
    if slot:
        b.clicked.connect(slot)
    return b


def label(text="", role=None, wrap=False):
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    if wrap:
        lb.setWordWrap(True)
    return lb


def kbd(text):
    lb = QLabel(text)
    lb.setProperty("role", "kbd")
    lb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lb


def hline():
    f = QFrame()
    f.setProperty("hline", True)
    return f


def vline():
    f = QFrame()
    f.setProperty("vline", True)
    return f


def dot_pixmap(color, size=10, radius=3):
    dpr = 2.0
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(23, 36, 53, 40), 1))
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(0.5, 0.5, pm.width() - 1, pm.height() - 1), radius * dpr, radius * dpr)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def dot_icon(color, size=10):
    pm = dot_pixmap(color, size)
    ic = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
        ic.addPixmap(pm, mode)       # seçili satırda renk değişmesin
    return ic


def dot_label(color, size=8):
    lb = QLabel()
    lb.setFixedSize(size, size)
    lb.setPixmap(dot_pixmap(color, size, 2))
    return lb


def dialog_header(title):
    """Pencerelerin üstündeki büyük başlık."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(label(title, "dialogTitle"))
    lay.addStretch()
    return w


def draw_kbd(p, x, cy, text, font=None):
    """Tuş rozetini (x, dikey orta) noktasına çizer; genişliğini döner."""
    f = font or theme.mono_font(10)
    p.save()
    p.setFont(f)
    fm = p.fontMetrics()
    w = fm.horizontalAdvance(text) + 10
    h = fm.height() + 4
    r = QRectF(x, cy - h / 2, w, h)
    p.setPen(QPen(theme.qc("line"), 1))
    p.setBrush(theme.qc("sub"))
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
    p.setPen(theme.qc("dim"))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
    p.restore()
    return w


# ---------------------------------------------------------------------------
#  Seçim düğmesi (Kutu etiketi penceresinde sınıf / seçenek)
# ---------------------------------------------------------------------------
class ChoiceButton(QAbstractButton):
    """[● ad  (1)] — seçiliyken mavi zemin. Odak almaz; tuşlar pencerede yakalanır."""

    def __init__(self, text, key="", color=None, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.key = key
        self.color = color
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _font(self):
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def sizeHint(self):
        fm = QFontMetrics(self._font())
        w = 12 + fm.horizontalAdvance(self.text()) + 12
        if self.color:
            w += 16
        if self.key:
            w += theme_mono_width(self.key) + 18
        return QSize(max(w, 64), 32)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        checked = self.isChecked()
        hover = self.underMouse()
        bg = theme.qc("accent_soft") if checked else (theme.qc("sub") if hover else theme.qc("surface"))
        border = theme.qc("accent_line") if checked else theme.qc("line")
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 6, 6)
        x = 11
        cy = self.height() / 2
        if self.color:
            p.setPen(QPen(QColor(23, 36, 53, 40), 1))
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(QRectF(x, cy - 5, 10, 10), 3, 3)
            x += 16
        p.setFont(self._font())
        p.setPen(theme.qc("accent_ink") if checked else theme.qc("ink"))
        fm = p.fontMetrics()
        key_w = (theme_mono_width(self.key) + 18) if self.key else 0
        text_rect = QRectF(x, 0, self.width() - x - 10 - key_w, self.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, int(text_rect.width())))
        if self.key:
            draw_kbd(p, self.width() - key_w - 2, cy, self.key)
        p.end()


# ---------------------------------------------------------------------------
#  İstatistik ağacı satırları
# ---------------------------------------------------------------------------
ROLE_KIND = Qt.ItemDataRole.UserRole + 10    # "class" | "attr" | "option" | "photo"
ROLE_DOT = Qt.ItemDataRole.UserRole + 11     # sınıf rengi
ROLE_KBD = Qt.ItemDataRole.UserRole + 12     # kısayol
ROLE_COUNT = Qt.ItemDataRole.UserRole + 13   # sağdaki sayı
ROLE_PHOTOS = Qt.ItemDataRole.UserRole + 15  # kaç farklı fotoğrafta geçtiği (None: gösterme)
ROLE_SHARE = Qt.ItemDataRole.UserRole + 16   # seçeneğin sınıf içindeki payı (0..1), dağılım çubuğu
ROLE_EXPANDABLE = Qt.ItemDataRole.UserRole + 17  # açılabilir mi (fotoğraf listesi / sınıf kartı)
ROLE_STATE = Qt.ItemDataRole.UserRole + 14   # "active" | "pending" | "zero" | "current" | "browse" | None


def theme_mono_width(text):
    return QFontMetrics(theme.mono_font(10)).horizontalAdvance(text)
