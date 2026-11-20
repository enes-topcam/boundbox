"""Sol taraftaki fotoğraf listesi.

- Boş alana tıklayınca 'fotoğraf ekle' penceresini açar
- Boşken 'buraya sürükleyin' kutusu gösterir
- Fotoğraf sürüklenirken renklenip 'Bırakın, eklensin' der
"""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListWidget

ACCENT = QColor("#2f80ed")


class ImageList(QListWidget):
    emptyClicked = Signal()
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setMouseTracking(True)
        self.drag_active = False
        self.placeholder = ""     # liste boşken gösterilecek yazı

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
    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        vp = QRectF(self.viewport().rect())
        muted = self.palette().placeholderText().color()

        if self.drag_active:
            fill = QColor(ACCENT)
            fill.setAlpha(45)
            p.fillRect(vp, fill)
            p.setPen(QPen(ACCENT, 2, Qt.PenStyle.DashLine))
            p.drawRoundedRect(vp.adjusted(4, 4, -4, -4), 8, 8)
            font = QFont(self.font())
            font.setPointSize(font.pointSize() + 3)
            font.setBold(True)
            p.setFont(font)
            p.setPen(ACCENT)
            p.drawText(vp, Qt.AlignmentFlag.AlignCenter, "⬇\nBırakın,\nfotoğraflar eklensin")
            return

        if self.count() == 0:
            box = vp.adjusted(10, 10, -10, -10)
            p.setPen(QPen(muted, 2, Qt.PenStyle.DashLine))
            p.drawRoundedRect(box, 10, 10)
            p.setPen(muted)
            font = QFont(self.font())
            font.setPointSize(font.pointSize() + 1)
            p.setFont(font)
            text = self.placeholder or "📂\n\nFotoğrafları veya klasörü\nburaya sürükleyip bırakın\n\nya da tıklayıp seçin"
            p.drawText(box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
            return

        # listenin altında boş yer varsa küçük bir ipucu
        free = self._empty_rect()
        if free.height() >= 60:
            hint = QRectF(free.left() + 8, free.top() + 8, free.width() - 16, 46)
            p.setPen(QPen(muted, 1, Qt.PenStyle.DashLine))
            p.drawRoundedRect(hint, 6, 6)
            p.setPen(muted)
            p.drawText(hint, Qt.AlignmentFlag.AlignCenter, "+ Fotoğraf eklemek için tıklayın\nveya sürükleyip bırakın")
