"""Resim gösterme, iki tıkla kutu çizme, zoom ve gezinme alanı.

- Sol tık: 1. tık sol üst köşe, 2. tık sağ alt köşe
- Tekerlek: mouse'un olduğu yere doğru zoom
- Sağ tık basılı tutup sürükle (veya orta tuş): fotoğrafta gezin
- Sağ tık (sürüklemeden): çizimi iptal eder; çizim yokken kutunun üstünde menü açar
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .imageutil import box_caption

MAX_SCALE = 12.0     # en fazla 1 resim pikseli = 12 ekran pikseli
ZOOM_STEP = 1.2
DRAG_THRESHOLD = 4
EDGE_PAD = 30        # resmin çevresinde bırakılan boşluk (ekran pikseli); kenara tıklamayı kolaylaştırır


class Canvas(QWidget):
    boxDrawn = Signal(float, float, float, float)    # resim koordinatı x1, y1, x2, y2
    boxRightClicked = Signal(int, object)             # kutu index, global pozisyon
    hint = Signal(str)
    zoomChanged = Signal(int)                         # yüzde
    pressed = Signal()                                # fotoğraf alanına tıklandı

    def __init__(self, color_fn, parent=None):
        super().__init__(parent)
        self.color_fn = color_fn
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.image = None
        self.pix = None
        self.cache = None          # küçültülmüş resim (hız için)
        self.cache_scale = None
        self.scale = 1.0
        self.ox = self.oy = 0.0
        self.fitted = True
        self.boxes = []
        self.first = None          # ilk tık (resim koordinatı)
        self.mouse = None          # mouse (widget koordinatı)
        self.selected = -1
        self.hover = -1
        self.pan = None            # {"start", "ox", "oy", "button", "moved"}

    # ================================================================
    #  Dışarıdan çağrılanlar
    # ================================================================
    def set_image(self, image, boxes):
        self.image = image if image is not None and not image.isNull() else None
        self.pix = QPixmap.fromImage(self.image) if self.image is not None else None
        self.cache = None
        self.boxes = boxes
        self.first = None
        self.selected = -1
        self.hover = -1
        self.fit()
        self._emit_hint()

    def set_boxes(self, boxes):
        self.boxes = boxes
        if self.selected >= len(boxes):
            self.selected = -1
        self.update()

    def set_selected(self, index):
        self.selected = index
        self.update()

    def cancel(self):
        if self.first is not None:
            self.first = None
            self.update()
            self._emit_hint()
            return True
        return False

    def fit(self):
        self.fitted = True
        if self.image is not None:
            self.scale = self._fit_scale()
            self.ox = (self.width() - self.image.width() * self.scale) / 2
            self.oy = (self.height() - self.image.height() * self.scale) / 2
        self.update()
        self.zoomChanged.emit(round(self.scale * 100) if self.image is not None else 0)

    # ================================================================
    #  Koordinatlar
    # ================================================================
    def _fit_scale(self):
        w = max(1, self.width() - 2 * EDGE_PAD)
        h = max(1, self.height() - 2 * EDGE_PAD)
        return min(w / self.image.width(), h / self.image.height())

    def to_widget(self, x, y):
        return QPointF(self.ox + x * self.scale, self.oy + y * self.scale)

    def to_image(self, p):
        return (p.x() - self.ox) / self.scale, (p.y() - self.oy) / self.scale

    def _inside(self, p):
        """Resmin üstünde ya da kenarına EDGE_PAD kadar yakın mı (yakınsa kenara yapıştırılır)."""
        x, y = self.to_image(p)
        pad = EDGE_PAD / self.scale
        return -pad <= x <= self.image.width() + pad and -pad <= y <= self.image.height() + pad

    def _clamp(self, x, y):
        return (min(max(x, 0.0), float(self.image.width())),
                min(max(y, 0.0), float(self.image.height())))

    def _clamp_offset(self):
        """Resmin ekrandan kaçmasını engeller (kenarlarda EDGE_PAD kadar boşluk kalabilir); küçükse ortalar."""
        for axis in ("x", "y"):
            view = self.width() if axis == "x" else self.height()
            size = (self.image.width() if axis == "x" else self.image.height()) * self.scale
            o = self.ox if axis == "x" else self.oy
            if size + 2 * EDGE_PAD <= view:
                o = (view - size) / 2
            else:
                o = min(float(EDGE_PAD), max(view - size - EDGE_PAD, o))
            if axis == "x":
                self.ox = o
            else:
                self.oy = o

    def _box_at(self, p):
        x, y = self.to_image(p)
        hits = [
            (abs((b["x2"] - b["x1"]) * (b["y2"] - b["y1"])), i)
            for i, b in enumerate(self.boxes)
            if b["x1"] <= x <= b["x2"] and b["y1"] <= y <= b["y2"]
        ]
        return min(hits)[1] if hits else -1

    def _emit_hint(self):
        if self.image is None:
            self.hint.emit("Soldan bir fotoğraf seçin.")
        elif self.first is None:
            self.hint.emit("Kutunun SOL ÜST köşesine tıklayın.")
        else:
            self.hint.emit("Şimdi SAĞ ALT köşeye tıklayın  (iptal: sağ tık / Esc)")

    # ================================================================
    #  Olaylar
    # ================================================================
    def resizeEvent(self, e):
        if self.image is not None:
            if self.fitted:
                self.fit()
            else:
                self._clamp_offset()
        super().resizeEvent(e)

    def wheelEvent(self, e):
        if self.image is None:
            return
        steps = e.angleDelta().y() / 120
        if not steps:
            return
        fit = self._fit_scale()
        new = min(max(self.scale * (ZOOM_STEP ** steps), fit), max(MAX_SCALE, fit))
        if new <= fit * 1.0001:
            self.fit()
            return
        p = e.position()
        ix, iy = self.to_image(p)
        self.scale = new
        self.ox = p.x() - ix * new
        self.oy = p.y() - iy * new
        self.fitted = False
        self._clamp_offset()
        self.update()
        self.zoomChanged.emit(round(self.scale * 100))

    def mousePressEvent(self, e):
        self.pressed.emit()
        if self.image is None:
            return
        p = e.position()
        if e.button() == Qt.MouseButton.LeftButton:
            if self.first is None:
                if self._inside(p):
                    self.first = self._clamp(*self.to_image(p))
            else:
                x1, y1 = self.first
                x2, y2 = self._clamp(*self.to_image(p))
                self.first = None
                left, right = sorted((x1, x2))
                top, bottom = sorted((y1, y2))
                if right - left >= 3 and bottom - top >= 3:
                    self.boxDrawn.emit(left, top, right, bottom)
            self.update()
            self._emit_hint()
        elif e.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self.pan = {"start": p, "ox": self.ox, "oy": self.oy, "button": e.button(), "moved": False}

    def mouseMoveEvent(self, e):
        self.mouse = e.position()
        if self.image is None:
            return
        if self.pan is not None:
            d = self.mouse - self.pan["start"]
            if not self.pan["moved"] and math.hypot(d.x(), d.y()) >= DRAG_THRESHOLD:
                self.pan["moved"] = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self.pan["moved"]:
                self.ox = self.pan["ox"] + d.x()
                self.oy = self.pan["oy"] + d.y()
                self.fitted = False
                self._clamp_offset()
        self.hover = self._box_at(self.mouse) if self.first is None and self.pan is None else -1
        self.update()

    def mouseReleaseEvent(self, e):
        if self.pan is None or e.button() != self.pan["button"]:
            return
        moved = self.pan["moved"]
        self.pan = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        if moved or e.button() != Qt.MouseButton.RightButton:
            return
        # sürüklemeden sağ tık: iptal ya da kutu menüsü
        if not self.cancel():
            i = self._box_at(e.position())
            if i >= 0:
                self.boxRightClicked.emit(i, e.globalPosition().toPoint())

    def leaveEvent(self, e):
        self.mouse = None
        self.hover = -1
        self.update()

    # ================================================================
    #  Çizim
    # ================================================================
    def _draw_image(self, p):
        s = self.scale
        iw, ih = self.image.width(), self.image.height()
        if s < 1:
            # küçültülmüş hâli önbellekte tut, her harekette yeniden ölçekleme
            if self.cache is None or self.cache_scale != s:
                self.cache = self.pix.scaled(max(1, round(iw * s)), max(1, round(ih * s)),
                                             Qt.AspectRatioMode.IgnoreAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
                self.cache_scale = s
            p.drawPixmap(QPointF(self.ox, self.oy), self.cache)
        else:
            # yakınlaştırınca sadece görünen kısmı çiz (pikseller net görünür)
            x0 = max(0, math.floor(-self.ox / s))
            y0 = max(0, math.floor(-self.oy / s))
            x1 = min(iw, math.ceil((self.width() - self.ox) / s))
            y1 = min(ih, math.ceil((self.height() - self.oy) / s))
            if x1 > x0 and y1 > y0:
                target = QRectF(self.ox + x0 * s, self.oy + y0 * s, (x1 - x0) * s, (y1 - y0) * s)
                p.drawPixmap(target, self.pix, QRectF(x0, y0, x1 - x0, y1 - y0))

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1e1e1e"))
        if self.image is None:
            p.setPen(QColor("#aaaaaa"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Fotoğraf yok\n\nFotoğrafları veya klasörü buraya sürükleyip bırakabilirsiniz")
            return
        self._draw_image(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()

        for i, b in enumerate(self.boxes):
            color = QColor(self.color_fn(b["sinif"]))
            rect = QRectF(self.to_widget(b["x1"], b["y1"]), self.to_widget(b["x2"], b["y2"]))
            if i in (self.selected, self.hover):
                fill = QColor(color)
                fill.setAlpha(60)
                p.fillRect(rect, fill)
            p.setPen(QPen(color, 4 if i == self.selected else 2))
            p.drawRect(rect)
            text = box_caption(b)
            tw, th = fm.horizontalAdvance(text) + 8, fm.height() + 2
            ty = rect.top() - th if rect.top() - th >= 0 else rect.top()
            p.fillRect(QRectF(rect.left(), ty, tw, th), color)
            p.setPen(QColor("white"))
            p.drawText(QRectF(rect.left() + 4, ty, tw, th), Qt.AlignmentFlag.AlignVCenter, text)

        # çizim önizlemesi
        if self.first is not None and self.mouse is not None:
            a = self.to_widget(*self.first)
            b = self.to_widget(*self._clamp(*self.to_image(self.mouse)))
            p.setPen(QPen(QColor("#ffeb3b"), 2, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(a, b).normalized())

        # artı imleç çizgileri (köşeyi tam denk getirmek için)
        if self.mouse is not None and self.pan is None and self._inside(self.mouse):
            p.setPen(QPen(QColor(255, 255, 255, 160), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(self.mouse.x(), 0), QPointF(self.mouse.x(), self.height()))
            p.drawLine(QPointF(0, self.mouse.y()), QPointF(self.width(), self.mouse.y()))
