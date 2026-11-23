"""Resim gösterme, iki tıkla kutu çizme, zoom ve gezinme alanı.

- Sol tık: 1. tık sol üst köşe, 2. tık sağ alt köşe
- Tekerlek: mouse'un olduğu yere doğru zoom
- Sağ tık basılı tutup sürükle (veya orta tuş): fotoğrafta gezin
- Sağ tık (sürüklemeden): çizimi iptal eder; çizim yokken kutunun üstünde menü açar
- Kutu kenarını düzenleme sadece düzenleme tuşu (varsayılan Shift, ayarlardan değişir) basılıyken
  ya da sağ tık > "Kutuyu düzenle" denince açılır. O zaman kenara / köşeye sol tık: kenar fareyi
  takip eder, ikinci tıkla yerine oturur (basılı tutup sürüklemek de olur).
"""
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from . import theme
from .imageutil import box_label

MAX_SCALE = 12.0     # en fazla 1 resim pikseli = 12 ekran pikseli
ZOOM_STEP = 1.2
DRAG_THRESHOLD = 4
EDGE_PAD = 30        # resmin çevresinde bırakılan boşluk (ekran pikseli); kenara tıklamayı kolaylaştırır
HANDLE_TOL = 6       # kutu kenarını yakalama mesafesi (ekran pikseli)
MIN_BOX = 3          # en küçük kutu (resim pikseli)

_HANDLE_CURSORS = {
    frozenset("l"): Qt.CursorShape.SizeHorCursor, frozenset("r"): Qt.CursorShape.SizeHorCursor,
    frozenset("t"): Qt.CursorShape.SizeVerCursor, frozenset("b"): Qt.CursorShape.SizeVerCursor,
    frozenset("lt"): Qt.CursorShape.SizeFDiagCursor, frozenset("rb"): Qt.CursorShape.SizeFDiagCursor,
    frozenset("rt"): Qt.CursorShape.SizeBDiagCursor, frozenset("lb"): Qt.CursorShape.SizeBDiagCursor,
}

_MODIFIERS = {"Shift": Qt.KeyboardModifier.ShiftModifier,
              "Ctrl": Qt.KeyboardModifier.ControlModifier,
              "Alt": Qt.KeyboardModifier.AltModifier}
_MODIFIER_KEYS = (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta)


class Canvas(QWidget):
    boxDrawn = Signal(float, float, float, float)    # resim koordinatı x1, y1, x2, y2
    boxRightClicked = Signal(int, object)             # kutu index, global pozisyon
    boxResized = Signal(int, float, float, float, float)  # kutu index, yeni x1, y1, x2, y2
    hint = Signal(str)
    zoomChanged = Signal(int)                         # yüzde
    pressed = Signal()                                # fotoğraf alanına tıklandı
    emptyAction = Signal()                            # boş durumdaki düğmeye tıklandı

    def __init__(self, color_fn, parent=None):
        super().__init__(parent)
        self.color_fn = color_fn
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._dots = None          # noktalı zemin dokusu
        self.empty_text = ""
        self.empty_btn = QPushButton(self)
        self.empty_btn.setProperty("primary", True)
        self.empty_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.empty_btn.clicked.connect(self.emptyAction)
        self.empty_btn.hide()
        theme.notifier().changed.connect(self._theme_changed)
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
        self.edit = None           # kenar düzenleme: {"i", "sides", "orig", "rect", "press", "held", "moved"}
        self.armed = -1            # sağ tık > "Kutuyu düzenle" ile düzenlemeye açılan kutu
        self.edit_mod_name = "Shift"
        self.edit_mod = Qt.KeyboardModifier.ShiftModifier
        self._hint_text = None
        # düzenleme tuşuna basınca / bırakınca imleç fare kımıldamadan da değişsin
        QApplication.instance().installEventFilter(self)

    # ================================================================
    #  Dışarıdan çağrılanlar
    # ================================================================
    def set_image(self, image, boxes):
        self.image = image if image is not None and not image.isNull() else None
        self.pix = QPixmap.fromImage(self.image) if self.image is not None else None
        self.cache = None
        self.boxes = boxes
        self.first = None
        self.edit = None
        self.armed = -1
        self.selected = -1
        self.hover = -1
        self._place_empty_button()
        self.fit()
        self._emit_hint()

    def set_empty(self, text, button=""):
        """Fotoğraf yokken ortada görünen yazı ve (varsa) düğme."""
        self.empty_text = text
        self.empty_btn.setText(button)
        self.empty_btn.adjustSize()
        self._place_empty_button()
        self.update()

    def _place_empty_button(self):
        show = self.image is None and bool(self.empty_btn.text())
        self.empty_btn.setVisible(show)
        if show:
            b = self.empty_btn
            b.move(round((self.width() - b.width()) / 2), round(self.height() / 2 + 14))

    def _theme_changed(self):
        self._dots = None
        self.update()

    def set_boxes(self, boxes):
        self.boxes = boxes
        if self.edit and self.edit["i"] >= len(boxes):
            self.edit = None
        if self.armed >= len(boxes):
            self.armed = -1
        if self.selected >= len(boxes):
            self.selected = -1
        self._update_cursor()
        self.update()

    def set_selected(self, index):
        self.selected = index
        if self.armed >= 0 and index != self.armed:
            self.armed = -1
            self._update_cursor()
        self.update()

    def set_edit_modifier(self, name):
        """Kenar düzenlemek için basılı tutulacak tuş: "Shift", "Ctrl" ya da "Alt"."""
        self.edit_mod_name = name if name in _MODIFIERS else "Shift"
        self.edit_mod = _MODIFIERS[self.edit_mod_name]
        self._hint_text = None
        self._update_cursor()

    def arm_edit(self, i):
        """Sağ tık > "Kutuyu düzenle": tuşa basmadan bu kutunun kenarları tutulabilir (Esc ile biter)."""
        if not (0 <= i < len(self.boxes)):
            return
        self.first = None
        self.edit = None
        self.armed = i
        self.selected = i
        self.setFocus()
        self._update_cursor()
        self.update()

    def _mod_held(self, mods=None):
        if mods is None:
            mods = QApplication.queryKeyboardModifiers()
        return bool(mods & self.edit_mod)

    def cancel(self):
        if self.edit is not None:
            self.edit = None
            self._update_cursor()
            self.update()
            return True
        if self.armed >= 0:
            self.armed = -1
            self._update_cursor()
            self.update()
            return True
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

    def _handle_at(self, p, mods=None):
        """Farenin altındaki kutu kenarı / köşesi: (kutu index, {"l","r","t","b"} alt kümesi) ya da None.
        Düzenleme tuşu basılı değilse sadece sağ tıkla düzenlemeye açılan kutu yakalanır."""
        if self._mod_held(mods):
            candidates = range(len(self.boxes))
        elif 0 <= self.armed < len(self.boxes):
            candidates = (self.armed,)
        else:
            return None
        best = None
        for i in candidates:
            b = self.boxes[i]
            a, c = self.to_widget(b["x1"], b["y1"]), self.to_widget(b["x2"], b["y2"])
            left, right = sorted((a.x(), c.x()))
            top, bottom = sorted((a.y(), c.y()))
            if not (left - HANDLE_TOL <= p.x() <= right + HANDLE_TOL
                    and top - HANDLE_TOL <= p.y() <= bottom + HANDLE_TOL):
                continue
            d = {"l": abs(p.x() - left), "r": abs(p.x() - right),
                 "t": abs(p.y() - top), "b": abs(p.y() - bottom)}
            sides = set()
            for h, v in (("l", "r"), ("t", "b")):
                near = min((h, v), key=d.get)        # küçük kutuda iki kenar da yakınsa yakın olan
                if d[near] <= HANDLE_TOL:
                    sides.add(near)
            if not sides:
                continue
            dist = min(d[x] for x in sides)
            key = (dist, i != self.selected, (right - left) * (bottom - top))
            if best is None or key < best[0]:
                best = (key, i, frozenset(sides))
        return (best[1], best[2]) if best else None

    def _start_edit(self, i, sides, p):
        b = self.boxes[i]
        x1, x2 = sorted((b["x1"], b["x2"]))
        y1, y2 = sorted((b["y1"], b["y2"]))
        self.edit = {"i": i, "sides": sides, "orig": (x1, y1, x2, y2), "rect": [x1, y1, x2, y2],
                     "press": p, "held": True, "moved": False}
        self.hover = -1
        self._emit_hint()

    def _move_edit(self, p):
        e = self.edit
        x1, y1, x2, y2 = e["orig"]
        px, py = self.to_image(e["press"])
        mx, my = self.to_image(p)
        dx, dy = mx - px, my - py
        nx1, ny1, nx2, ny2 = x1, y1, x2, y2
        if "l" in e["sides"]:
            nx1 = x1 + dx
        if "r" in e["sides"]:
            nx2 = x2 + dx
        if "t" in e["sides"]:
            ny1 = y1 + dy
        if "b" in e["sides"]:
            ny2 = y2 + dy
        nx1, ny1 = self._clamp(nx1, ny1)
        nx2, ny2 = self._clamp(nx2, ny2)
        e["rect"] = [nx1, ny1, nx2, ny2]

    def _finish_edit(self):
        e, self.edit = self.edit, None
        x1, x2 = sorted((e["rect"][0], e["rect"][2]))
        y1, y2 = sorted((e["rect"][1], e["rect"][3]))
        self._update_cursor()
        self.update()
        if x2 - x1 >= MIN_BOX and y2 - y1 >= MIN_BOX and (x1, y1, x2, y2) != e["orig"]:
            self.boxResized.emit(e["i"], x1, y1, x2, y2)

    def _update_cursor(self):
        shape = Qt.CursorShape.CrossCursor
        if self.edit is not None:
            shape = _HANDLE_CURSORS[self.edit["sides"]]
        elif self.first is None and self.pan is None and self.mouse is not None and self.image is not None:
            h = self._handle_at(self.mouse)
            if h:
                shape = _HANDLE_CURSORS[h[1]]
        if self.cursor().shape() != shape:
            self.setCursor(shape)
        self._emit_hint()

    def _emit_hint(self):
        if self.image is None:
            text = "Soldan bir fotoğraf seç"
        elif self.edit is not None:
            text = ("Bırakınca yerine oturur · Esc iptal" if self.edit["held"]
                    else "Kenarı yeni yerine götürüp tıkla · Esc iptal")
        elif self.first is not None:
            text = "Sağ alt köşeye tıkla · Esc iptal"
        elif self.cursor().shape() != Qt.CursorShape.CrossCursor:
            text = "Kenarı taşımak için tıkla ya da sürükle"
            if self.armed >= 0:
                text += " · Esc: düzenlemeyi bitir"
        elif self.armed >= 0:
            text = "Düzenlenecek kutunun kenarını / köşesini tut · Esc ya da boşa tık: bitir"
        else:
            text = f"Sol üst köşeye tıkla · {self.edit_mod_name} basılı: kutu kenarını düzenle"
        if text != self._hint_text:
            self._hint_text = text
            self.hint.emit(text)

    # ================================================================
    #  Olaylar
    # ================================================================
    def resizeEvent(self, e):
        self._place_empty_button()
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
            if self.edit is not None:            # tıkla-götür-tıkla: ikinci tık yerine oturtur
                self._move_edit(p)
                self._finish_edit()
                return
            handle = self._handle_at(p, e.modifiers()) if self.first is None else None
            if handle:
                self._start_edit(handle[0], handle[1], p)
                self.update()
                return
            if self.armed >= 0 and self.first is None:
                # düzenleme modundayken boşa tık: modu bitirir, yanlışlıkla kutu başlatmaz
                self.armed = -1
                self._update_cursor()
                self.update()
                return
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
        if self.edit is not None:
            d = self.mouse - self.edit["press"]
            if self.edit["held"] and math.hypot(d.x(), d.y()) >= DRAG_THRESHOLD:
                self.edit["moved"] = True
            if self.pan is None:
                self._move_edit(self.mouse)
        self.hover = (self._box_at(self.mouse)
                      if self.first is None and self.pan is None and self.edit is None else -1)
        if self.pan is None:
            self._update_cursor()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.edit is not None and self.edit["held"] and e.button() == Qt.MouseButton.LeftButton:
            if self.edit["moved"]:               # sürükle-bırak
                self._move_edit(e.position())
                self._finish_edit()
            else:                                # sadece tıklandı: kenar fareyi takip etsin
                self.edit["held"] = False
                self._emit_hint()
            return
        if self.pan is None or e.button() != self.pan["button"]:
            return
        moved = self.pan["moved"]
        self.pan = None
        self._update_cursor()
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
        self._update_cursor()
        self.update()

    def eventFilter(self, obj, ev):
        # düzenleme tuşuna basılınca / bırakılınca imleç ve ipucu hemen güncellensin
        if ev.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and ev.key() in _MODIFIER_KEYS \
                and self.mouse is not None and self.isVisible():
            self._update_cursor()
        return False

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

    def _dot_brush(self):
        """Tuval zeminindeki silik nokta deseni (16 px aralıklı)."""
        if self._dots is None:
            dpr = self.devicePixelRatioF()
            pm = QPixmap(round(16 * dpr), round(16 * dpr))
            pm.fill(theme.qc("paper"))
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(175, 193, 211, 34))
            q.drawEllipse(QPointF(pm.width() / 2, pm.height() / 2), dpr, dpr)
            q.end()
            pm.setDevicePixelRatio(dpr)
            self._dots = QBrush(pm)
        return self._dots

    @staticmethod
    def _handle(p, center, size):
        r = QRectF(center.x() - size / 2, center.y() - size / 2, size, size)
        p.setPen(QPen(QColor(theme.LABEL_BG), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(r, 2, 2)

    def _draw_label(self, p, rect, text, short, color, fm, strong=False):
        """Kutunun içinde sol alt köşede küçük koyu etiket: ● sınıf › seçenek.
        Yan yana / üst üste kutularda etiketler birbirini kapatmasın diye kutu genişliğine sığdırılır;
        sığmazsa sadece seçenek (ör. "Mercimek") yazılır. Kutu çok alçaksa etiket kutunun hemen altına çıkar."""
        pad, dot, gap, inset = 4, 5, 4, 4
        th = fm.height() + 2
        # kutu genişliği kadar (çok küçük kutuda en az 64 px), ekranın sağından da taşmasın
        avail = min(max(64.0, rect.width() - 2 * inset), self.width() - rect.left() - inset - 2)
        room = int(max(16.0, avail - pad * 2 - dot - gap))
        if fm.horizontalAdvance(text) > room:
            text = short
        text = fm.elidedText(text, Qt.TextElideMode.ElideRight, room)
        tw = fm.horizontalAdvance(text) + pad * 2 + dot + gap
        x = rect.left() + inset
        if rect.height() >= th + 2 * inset:
            y = rect.bottom() - th - inset                 # içeride, sol alt
        elif rect.bottom() + 2 + th <= self.height():
            y = rect.bottom() + 3                          # kutu alçak: hemen altına
        else:
            y = rect.top() - th - 3                        # en alttaysa üstüne
        r = QRectF(x, y, tw, th)
        path = QPainterPath()
        path.addRoundedRect(r, 3, 3)
        bg = QColor(theme.LABEL_BG)
        bg.setAlpha(240 if strong else 200)
        p.setPen(QPen(QColor(255, 255, 255, 60 if strong else 30), 1))
        p.setBrush(bg)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(x + pad, r.center().y() - dot / 2, dot, dot))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(x + pad + dot + gap, y, tw, th), Qt.AlignmentFlag.AlignVCenter, text)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self._dot_brush())
        if self.image is None:
            if self.empty_text:
                p.setFont(theme.ui_font(14, QFont.Weight.DemiBold))
                p.setPen(QColor("#C3CDDE"))
                r = QRectF(self.rect())
                r.setBottom(r.center().y() + 4)
                p.drawText(r, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.empty_text)
            return
        # fotoğrafın altına hafif gölge
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        img_rect = QRectF(self.to_widget(0, 0), self.to_widget(self.image.width(), self.image.height()))
        for k, a in ((10, 18), (5, 30), (2, 45)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(img_rect.adjusted(-k, -k + 4, k, k + 4), k, k)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._draw_image(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        outline = QColor(18, 24, 38, 143)
        labels = []                # (öncelik, rect, yazı, renk): kutulardan sonra, en üstte çizilir

        for i, b in enumerate(self.boxes):
            color = QColor(self.color_fn(b["sinif"]))
            editing = self.edit is not None and self.edit["i"] == i
            if editing:
                x1, y1, x2, y2 = self.edit["rect"]
                rect = QRectF(self.to_widget(x1, y1), self.to_widget(x2, y2)).normalized()
            else:
                rect = QRectF(self.to_widget(b["x1"], b["y1"]), self.to_widget(b["x2"], b["y2"])).normalized()
            armed = i == self.armed and not editing
            selected = i == self.selected or editing or armed
            width = 3 if selected else 2
            if i == self.hover or selected:
                fill = QColor(color)
                fill.setAlpha(26)
                p.fillRect(rect, fill)
            # ince koyu dış hat: açık / koyu fotoğrafta kutu seçilsin
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(outline, 1))
            p.drawRect(rect.adjusted(-width / 2 - 0.5, -width / 2 - 0.5, width / 2 + 0.5, width / 2 + 0.5))
            p.setPen(QPen(color, width))
            p.drawRect(rect)
            if armed:
                # sağ tıkla düzenlemeye açıldı: bütün kenarlar kesikli
                p.setPen(QPen(QColor(theme.EDIT_EDGE), 2, Qt.PenStyle.DashLine))
                p.drawRect(rect)
            if editing:
                # taşınan kenar(lar) kesikli
                p.setPen(QPen(QColor(theme.EDIT_EDGE), 3, Qt.PenStyle.DashLine))
                sides = self.edit["sides"]
                lines = {"l": (rect.topLeft(), rect.bottomLeft()), "r": (rect.topRight(), rect.bottomRight()),
                         "t": (rect.topLeft(), rect.topRight()), "b": (rect.bottomLeft(), rect.bottomRight())}
                for s in sides:
                    p.drawLine(*lines[s])
            if selected:
                for corner in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                    self._handle(p, corner, 7)
                if editing:
                    sides = self.edit["sides"]
                    cx = rect.left() if "l" in sides else rect.right() if "r" in sides else rect.center().x()
                    cy = rect.top() if "t" in sides else rect.bottom() if "b" in sides else rect.center().y()
                    self._handle(p, QPointF(cx, cy), 11)
            short = " › ".join(v for v in b.get("attributeler", {}).values() if v) or b["sinif"]
            labels.append((2 if selected else 1 if i == self.hover else 0, i, rect, box_label(b), short, color))

        # etiketler: seçili / üstüne gelinen kutununki en üstte kalsın
        p.setFont(theme.ui_font(10, QFont.Weight.DemiBold))
        fm = p.fontMetrics()
        for prio, _i, rect, text, short, color in sorted(labels, key=lambda t: (t[0], t[1])):
            self._draw_label(p, rect, text, short, color, fm, strong=prio > 0)

        # çizim önizlemesi
        if self.first is not None and self.mouse is not None:
            a = self.to_widget(*self.first)
            b = self.to_widget(*self._clamp(*self.to_image(self.mouse)))
            r = QRectF(a, b).normalized()
            p.setPen(QPen(QColor(22, 32, 52, 168), 1))
            p.setBrush(QColor(255, 213, 110, 23))
            p.drawRect(r.adjusted(-1.5, -1.5, 1.5, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(theme.DRAFT), 2, Qt.PenStyle.DashLine))
            p.drawRect(r)

        # artı imleç çizgileri (köşeyi tam denk getirmek için)
        if self.mouse is not None and self.pan is None and self._inside(self.mouse):
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setPen(QPen(QColor(255, 255, 255, 153), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(self.mouse.x(), 0), QPointF(self.mouse.x(), self.height()))
            p.drawLine(QPointF(0, self.mouse.y()), QPointF(self.width(), self.mouse.y()))

        # yakınlaştırma oranı (sağ alt köşe)
        p.setFont(theme.ui_font(11))
        p.setPen(QColor("#C3CDDE"))
        p.drawText(QRectF(0, 0, self.width() - 10, self.height() - 8),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, f"%{round(self.scale * 100)}")
