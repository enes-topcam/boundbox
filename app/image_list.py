"""Sol taraftaki fotoğraf listesi.

- Her satırda küçük önizleme, dosya adı, kutu sayısı ve durum simgesi
- Küçük resimler arka planda hazırlanır, liste beklemez
- Boş alana tıklayınca 'fotoğraf ekle' penceresini açar
- Fotoğraf sürüklenirken renklenip 'Bırak, eklensin' der
"""
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QFont, QImageReader, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QStyle, QStyledItemDelegate

from . import icons, theme

ROLE_COUNT = Qt.ItemDataRole.UserRole + 3     # kutu sayısı
ROLE_PATH = Qt.ItemDataRole.UserRole + 4      # fotoğrafın tam yolu (önizleme için)
ROW_H = 38
THUMB_W, THUMB_H = 32, 24


# ---------------------------------------------------------------------------
#  Küçük resimler
# ---------------------------------------------------------------------------
class _Signals(QObject):
    ready = Signal(str, object)       # yol, QImage


class _ThumbJob(QRunnable):
    def __init__(self, path, signals):
        super().__init__()
        self.path = path
        self.signals = signals

    def run(self):
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            # en boy oranını koruyarak kırpılacak alanı dolduracak kadar küçült
            k = max(THUMB_W * 2 / size.width(), THUMB_H * 2 / size.height())
            reader.setScaledSize(QSize(max(1, round(size.width() * k)), max(1, round(size.height() * k))))
        img = reader.read()
        self.signals.ready.emit(self.path, img)


class ThumbCache(QObject):
    updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(2)
        self.items = {}          # yol -> QPixmap | None (yükleniyor)
        self.signals = _Signals()
        self.signals.ready.connect(self._done)

    def get(self, path):
        if not path:
            return None
        if path in self.items:
            return self.items[path]
        self.items[path] = None
        self.pool.start(_ThumbJob(path, self.signals))
        return None

    def forget(self, path=None):
        if path is None:
            self.items.clear()
        else:
            self.items.pop(path, None)

    def _done(self, path, img):
        if path in self.items:
            self.items[path] = QPixmap.fromImage(img) if img is not None and not img.isNull() else QPixmap()
            self.updated.emit()


# ---------------------------------------------------------------------------
#  Satır çizimi
# ---------------------------------------------------------------------------
class _RowDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_H)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 2, -6, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            p.setPen(QPen(theme.qc("accent_line"), 1))
            p.setBrush(theme.qc("accent_soft"))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        elif hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.qc("sub"))
            p.drawRoundedRect(r, 6, 6)

        # önizleme
        tr = QRectF(r.left() + 7, r.center().y() - THUMB_H / 2, THUMB_W, THUMB_H)
        clip = QPainterPath()
        clip.addRoundedRect(tr, 4, 4)
        pm = self.view.thumbs.get(index.data(ROLE_PATH))
        p.save()
        p.setClipPath(clip)
        p.fillRect(tr, theme.qc("line"))
        if pm is not None and not pm.isNull():
            src = QRectF(pm.rect())
            k = max(tr.width() / src.width(), tr.height() / src.height())
            w, h = tr.width() / k, tr.height() / k
            p.drawPixmap(tr, pm, QRectF(src.center().x() - w / 2, src.center().y() - h / 2, w, h))
        p.restore()

        # durum simgesi + sayı
        n = index.data(ROLE_COUNT) or 0
        right = r.right() - 8
        ic = icons.icon("check" if n else "circle", theme.c("good") if n else theme.c("dim"))
        ic.paint(p, int(right - 14), int(r.center().y() - 7), 14, 14)
        right -= 22
        if n:
            p.setFont(theme.ui_font(11))
            p.setPen(theme.qc("dim"))
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(str(n))
            p.drawText(QRectF(right - w, r.top(), w, r.height()), Qt.AlignmentFlag.AlignVCenter, str(n))
            right -= w + 8

        # dosya adı
        f = theme.ui_font(13, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(theme.qc("ink"))
        x = tr.right() + 9
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        fm = p.fontMetrics()
        p.drawText(QRectF(x, r.top(), right - x, r.height()), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(name, Qt.TextElideMode.ElideMiddle, int(right - x)))
        p.restore()


class ImageList(QListWidget):
    emptyClicked = Signal()
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setStyleSheet("QListView::item { border: 0; margin: 0; padding: 0; }")
        self.thumbs = ThumbCache(self)
        self.thumbs.updated.connect(self.viewport().update)
        self.setItemDelegate(_RowDelegate(self))
        self.drag_active = False
        self.placeholder = ""     # liste boşken gösterilecek yazı
        theme.notifier().changed.connect(self.viewport().update)

    def set_drag_active(self, on):
        if self.drag_active != on:
            self.drag_active = on
            self.viewport().update()

    def _empty_rect(self):
        """Son öğenin altındaki boş alan."""
        vp = self.viewport().rect()
        if self.count() == 0:
            return QRectF(vp)
        last = self.visualItemRect(self.item(self.count() - 1))
        top = last.bottom() + 1
        return QRectF(vp.left(), top, vp.width(), vp.bottom() - top) if top < vp.bottom() else QRectF()

    # ---------- tıklama ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.itemAt(e.position().toPoint()) is None:
            self.emptyClicked.emit()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        empty = self.itemAt(e.position().toPoint()) is None
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if empty else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    # ---------- sürükle bırak ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self.set_drag_active(True)
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.set_drag_active(False)

    def dropEvent(self, e):
        self.set_drag_active(False)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.filesDropped.emit(paths)

    # ---------- çizim ----------
    def _drop_box(self, p, rect, text, active=False):
        p.setPen(QPen(theme.qc("accent") if active else theme.qc("line"), 1.5 if active else 1, Qt.PenStyle.DashLine))
        p.setBrush(theme.qc("accent_soft") if active else theme.qc("sub"))
        p.drawRoundedRect(rect, 6, 6)
        p.setFont(theme.ui_font(12))
        fm = p.fontMetrics()
        lines = text.split("\n")
        tw = max(fm.horizontalAdvance(s) for s in lines)
        th = fm.height() * len(lines)
        ic_size = 15
        x = rect.center().x() - (tw + ic_size + 6) / 2
        ic = icons.icon("image-plus", theme.c("accent_ink") if active else theme.c("dim"))
        ic.paint(p, int(x), int(rect.center().y() - ic_size / 2), ic_size, ic_size)
        p.setPen(theme.qc("accent_ink") if active else theme.qc("dim"))
        p.drawText(QRectF(x + ic_size + 6, rect.center().y() - th / 2, tw + 2, th),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        vp = QRectF(self.viewport().rect())

        if self.drag_active:
            self._drop_box(p, vp.adjusted(8, 8, -8, -8), "Bırak, fotoğraflar eklensin", active=True)
            return

        if self.count() == 0:
            box = QRectF(vp.left() + 10, vp.top() + 8, vp.width() - 20, 64)
            self._drop_box(p, box, self.placeholder or "Fotoğraf ekle veya bırak")
            return

        # listenin altında boş yer varsa ekleme alanı
        free = self._empty_rect()
        if free.height() >= 50:
            self._drop_box(p, QRectF(free.left() + 10, free.top() + 8, free.width() - 20, 36),
                           "Fotoğraf ekle veya bırak")
