"""Sağ panelin çizimi: 'Bu fotoğraftaki etiketler' listesi ve proje istatistiği kartları.

Listeler hâlâ QListWidget / QTreeWidget; davranış (seçme, gezinme, açma / kapama)
main_window'da. Burada sadece görünüm ve tıklanan yerin hangi düğme olduğu var.
"""
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QStyle, QStyledItemDelegate, QWidget

from . import icons, theme
from .widgets import (ROLE_COUNT, ROLE_DOT, ROLE_EXPANDABLE, ROLE_KBD, ROLE_KIND, ROLE_PHOTOS,
                      ROLE_SHARE, ROLE_STATE, draw_kbd, label)

def pretty(name: str) -> str:
    """Ekranda gösterilen ad: projede nasıl tanımlandıysa aynen (ör. 'yan_urun')."""
    return name or ""


def _icon_pm(name, color, size):
    return icons.icon(name, color).pixmap(size, size)


def _elide(p, text, width):
    return p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(8, int(width)))


class Panel(QWidget):
    """Sağ panelin kabı; boyutu değişince haber verir (sığdırma kararı için)."""
    resized = Signal()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.resized.emit()


# =====================================================================
#  Özet kartı (Toplam etiket / Etiketli fotoğraf)
# =====================================================================
class SummaryCard(QFrame):
    def __init__(self, icon_name, caption, tip="", short=None):
        super().__init__()
        self.setProperty("card", True)
        self.icon_name = icon_name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(9)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        self.lay = lay
        self.col = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self.col.setSpacing(0)
        self.value = label("–", "cardValue")
        self.captions = (caption, short or caption)
        self.caption = label(caption, "small", wrap=True)
        self.col.addWidget(self.value)
        self.col.addWidget(self.caption)
        self.col.addStretch(1)
        lay.addLayout(self.col, 1)
        if tip:
            self.setToolTip(tip)
        self.refresh_icon()

    def set_compact(self, on):
        """Kompakt: sayı ve açıklama yan yana, tek satır."""
        self.lay.setContentsMargins(10, 4, 10, 4) if on else self.lay.setContentsMargins(10, 8, 10, 8)
        self.col.setDirection(QBoxLayout.Direction.LeftToRight if on else QBoxLayout.Direction.TopToBottom)
        self.col.setSpacing(6 if on else 0)
        self.lay.setAlignment(self.icon, Qt.AlignmentFlag.AlignVCenter if on else Qt.AlignmentFlag.AlignTop)
        self.caption.setWordWrap(not on)
        self.caption.setText(self.captions[1 if on else 0])

    def refresh_icon(self):
        self.icon.setPixmap(_icon_pm(self.icon_name, theme.c("accent"), 18))

    def set_value(self, v):
        self.value.setText(str(v))


# =====================================================================
#  Bu fotoğraftaki etiketler
# =====================================================================
class BoxDelegate(QStyledItemDelegate):
    """Satır: ● Yemek adı / sınıf (soluk), sağda düzenle + sil."""
    ROW_H = 48
    ROW_H_COMPACT = 34

    def __init__(self, parent, on_edit, on_delete, color_fn):
        super().__init__(parent)
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.color_fn = color_fn
        self.compact = False

    @property
    def row_h(self):
        return self.ROW_H_COMPACT if self.compact else self.ROW_H

    @property
    def BTN(self):  # noqa: N802
        return 22 if self.compact else 26

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.row_h)

    def _card(self, option):
        return QRectF(option.rect).adjusted(2, 2, -3, -2)

    def _buttons(self, option):
        r = self._card(option)
        y = r.center().y() - self.BTN / 2
        delete = QRectF(r.right() - 8 - self.BTN, y, self.BTN, self.BTN)
        edit = QRectF(delete.left() - 5 - self.BTN, y, self.BTN, self.BTN)
        return edit, delete

    def paint(self, p, option, index):
        box = index.data(Qt.ItemDataRole.UserRole) or {}
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._card(option)
        color = QColor(self.color_fn(box.get("sinif", "")))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            bg = QColor(color)
            bg.setAlpha(46 if theme.is_dark() else 30)
            edge = QColor(color)
            edge.setAlpha(190)
            p.setPen(QPen(edge, 1.2))
            p.setBrush(bg)
        else:
            p.setPen(QPen(theme.qc("line"), 1))
            p.setBrush(theme.qc("sub") if hover else theme.qc("shell"))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        cy = r.center().y()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(r.left() + 16, cy), 5, 5)

        values = [v for v in box.get("attributeler", {}).values() if v]
        main = " · ".join(pretty(v) for v in values) or pretty(box.get("sinif", ""))
        sub = pretty(box.get("sinif", "")) if values else "Seçenek seçilmedi"
        edit_r, _ = self._buttons(option)
        x = r.left() + 30
        w = edit_r.left() - 8 - x
        if self.compact:     # tek satır: "Ana yemek  Diger"
            p.setFont(theme.ui_font(12.5, QFont.Weight.Bold))
            p.setPen(theme.qc("ink"))
            main_s = _elide(p, main, w * 0.7)
            mw = p.fontMetrics().horizontalAdvance(main_s)
            p.drawText(QRectF(x, r.top(), mw + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, main_s)
            p.setFont(theme.ui_font(11))
            p.setPen(theme.qc("dim") if values else theme.qc("warn"))
            rest = w - mw - 8
            if rest > 20:
                p.drawText(QRectF(x + mw + 8, r.top(), rest, r.height()), Qt.AlignmentFlag.AlignVCenter,
                           _elide(p, sub, rest))
            self._paint_buttons(p, option, selected)
            p.restore()
            return
        p.setFont(theme.ui_font(13, QFont.Weight.Bold))
        p.setPen(theme.qc("ink"))
        p.drawText(QRectF(x, r.top() + 5, w, 20), Qt.AlignmentFlag.AlignVCenter, _elide(p, main, w))
        p.setFont(theme.ui_font(11))
        p.setPen(theme.qc("dim") if values else theme.qc("warn"))
        p.drawText(QRectF(x, r.top() + 24, w, 16), Qt.AlignmentFlag.AlignVCenter, _elide(p, sub, w))

        self._paint_buttons(p, option, selected)
        p.restore()

    def _paint_buttons(self, p, option, selected):
        icon = 13 if self.compact else 14
        for rect, name in zip(self._buttons(option), ("pencil", "trash-2")):
            p.setPen(QPen(theme.qc("line"), 1))
            p.setBrush(theme.qc("surface"))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            role = "danger" if name == "trash-2" and selected else "dim"
            pm = _icon_pm(name, theme.c(role), icon)
            p.drawPixmap(int(rect.center().x() - icon / 2), int(rect.center().y() - icon / 2), pm)

    def editorEvent(self, event, model, option, index):
        if event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            pos = event.position()
            edit_r, del_r = self._buttons(option)
            if edit_r.contains(pos) or del_r.contains(pos):
                if event.type() == QEvent.Type.MouseButtonRelease:
                    (self.on_edit if edit_r.contains(pos) else self.on_delete)(index.row())
                return True
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index):
        edit_r, del_r = self._buttons(option)
        pos = QPointF(event.pos())
        if edit_r.contains(pos) or del_r.contains(pos):
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(event.globalPos(), "Etiketi düzenle" if edit_r.contains(pos) else "Etiketi sil",
                              view)
            return True
        return super().helpEvent(event, view, option, index)


# =====================================================================
#  Proje istatistiği: sınıf kartları
# =====================================================================
class StatsDelegate(QStyledItemDelegate):
    """İstatistik ağacının her satırı, sınıf kartının bir dilimini çizer.

    sınıf  : kartın başlığı (renk, ad, kısayol, 'N etiket · M fotoğraf', aç / kapat oku)
    attr   : birden çok özellik varsa kart içinde küçük ara başlık
    option : yemek satırı (ad, kısayol, dağılım çubuğu, etiket / foto sayısı)
    photo  : etikete göre gezinmede fotoğraf satırı
    """
    # (normal, kompakt) yükseklikler; "gap": kartlar arası boşluk (sınıf satırının üstünde)
    SIZES = {"gap": (8, 5), "class": (50, 34), "option": (42, 26), "attr": (24, 20), "photo": (28, 24)}
    STRIPE = 3
    RADIUS = 8

    @property
    def GAP(self):  # noqa: N802
        return self._h("gap")

    @property
    def HEAD_H(self):  # noqa: N802
        return self._h("class")

    @property
    def OPT_H(self):  # noqa: N802
        return self._h("option")

    @property
    def ATTR_H(self):  # noqa: N802
        return self._h("attr")

    @property
    def PHOTO_H(self):  # noqa: N802
        return self._h("photo")

    def _h(self, name):
        return self.SIZES[name][1 if self.compact else 0]

    def row_height(self, kind):
        if kind == "class":
            return self.GAP + self.HEAD_H
        return self._h(kind if kind in self.SIZES else "option")

    def __init__(self, tree):
        super().__init__(tree)
        self.tree = tree
        self.count_digits = 2
        self.photo_digits = 2
        self.compact = False
        self.max_name = {"class": 0, "option": 0}   # en uzun adın genişliği (kısayol yazısı kararı için)

    def set_names(self, class_names, option_names):
        """'Kısayol' kelimesi ya bütün satırlarda ya hiçbirinde görünsün diye en uzun adları ölçer."""
        f_cls = QFontMetrics(theme.ui_font(14, QFont.Weight.Bold))
        f_opt = QFontMetrics(theme.ui_font(12, QFont.Weight.DemiBold))
        self.max_name = {"class": max([0] + [f_cls.horizontalAdvance(pretty(n)) for n in class_names]),
                         "option": max([0] + [f_opt.horizontalAdvance(pretty(n)) for n in option_names])}

    def _word_fits(self, kind, x, max_right, keys):
        f_key = QFontMetrics(theme.ui_font(11))
        mono = QFontMetrics(theme.mono_font(10))
        keys_w = max(1, len(keys)) * (mono.horizontalAdvance("9") + 13) + 3
        need = self.max_name[kind] + 8 + f_key.horizontalAdvance("Kısayol") + 5 + keys_w
        return x + need <= max_right

    # ---------- ölçüler ----------
    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.row_height(index.data(ROLE_KIND)))

    def _card_x(self, r):
        return r.left() + 3, r.right() - 3

    def chevron_rect(self, kind, rect):
        """Aç / kapat okunun tıklanabilir alanı (görünüm koordinatında)."""
        r = QRectF(rect)
        left, right = self._card_x(r)
        if kind == "class":
            top = r.top() + self.GAP
            return QRectF(right - 34, top + 4, 30, self.HEAD_H - 8)
        if kind == "option":
            return QRectF(left + self.STRIPE, r.top(), 24, r.height())
        return QRectF()

    def _right_cols(self, p_font_count, p_font_photo):
        cw = QFontMetrics(p_font_count).horizontalAdvance("0" * self.count_digits + " etiket")
        pw = QFontMetrics(p_font_photo).horizontalAdvance("0" * self.photo_digits + " foto")
        return max(cw, pw) + 4

    # ---------- kartın neresindeyiz ----------
    def _class_index(self, index):
        while index.parent().isValid():
            index = index.parent()
        return index

    def _last_visible(self, index):
        model = index.model()
        while self.tree.isExpanded(index) and model.rowCount(index) > 0:
            index = model.index(model.rowCount(index) - 1, 0, index)
        return index

    def _is_last(self, index):
        return self._last_visible(self._class_index(index)) == index

    # ---------- çizim ----------
    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect)
        kind = index.data(ROLE_KIND)
        cls_index = self._class_index(index)
        cls_color = QColor(cls_index.data(ROLE_DOT) or "#888888")
        first = kind == "class"
        last = self._is_last(index)

        # kart dilimi: ilk satır üst köşeleri, son satır alt köşeleri yuvarlar
        left, right = self._card_x(r)
        top = r.top() + (self.GAP if first else 0)
        ext = self.RADIUS * 2
        card = QRectF(left, top if first else r.top() - ext, right - left,
                      (r.bottom() + 1 - (top if first else r.top() - ext)) + (0 if last else ext))
        if last:
            card.setBottom(r.bottom() - 0.5)
        path = QPainterPath()
        path.addRoundedRect(card.adjusted(0.5, 0.5, -0.5, 0), self.RADIUS, self.RADIUS)
        p.setClipRect(QRectF(r.left(), top, r.width(), r.bottom() + 1 - top))
        p.fillPath(path, theme.qc("shell"))
        # sol renkli şerit
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        p.fillRect(QRectF(left, top, self.STRIPE + 0.5, r.bottom() + 1 - top), cls_color)
        p.restore()
        p.setPen(QPen(theme.qc("line"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        inner = QRectF(left + self.STRIPE, top, right - left - self.STRIPE, r.bottom() + 1 - top)
        state = index.data(ROLE_STATE)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if kind == "class" and self.compact:
            self._paint_class_compact(p, index, inner, state, hover, cls_color)
        elif kind == "class":
            self._paint_class(p, index, inner, state, hover, cls_color)
        elif kind == "attr":
            self._paint_attr(p, index, inner, state)
        elif kind == "photo":
            self._paint_photo(p, index, inner, state, hover)
        else:
            first_child = index.row() == 0 and index.parent() == cls_index
            paint = self._paint_option_compact if self.compact else self._paint_option
            paint(p, index, inner, state, hover, cls_color, first_child)
        p.restore()

    def _highlight(self, p, rect, state, hover):
        rr = rect.adjusted(4, 3, -5, -3)
        if state in ("active", "browse"):
            p.setPen(QPen(theme.qc("accent_line"), 1))
            p.setBrush(theme.qc("accent_soft"))
            p.drawRoundedRect(rr.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        elif state == "pending":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.qc("warn_bg"))
            p.drawRoundedRect(rr, 6, 6)
        elif state == "current" or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.qc("sub"))
            p.drawRoundedRect(rr, 6, 6)

    def _draw_keys(self, p, x, cy, keys, max_right, with_word=True):
        """'Kısayol [1] [1]' çizer; sığmazsa önce kelimeyi, sonra hepsini bırakır. Bitiş x'ini döner."""
        if not keys:
            return x
        f_key = theme.ui_font(11)
        word_w = QFontMetrics(f_key).horizontalAdvance("Kısayol")
        mono = QFontMetrics(theme.mono_font(10))
        keys_w = sum(mono.horizontalAdvance(k) + 13 for k in keys)
        if with_word and x + word_w + 5 + keys_w <= max_right:
            p.setFont(f_key)
            p.setPen(theme.qc("dim"))
            p.drawText(QRectF(x, cy - 9, word_w + 2, 18), Qt.AlignmentFlag.AlignVCenter, "Kısayol")
            x += word_w + 5
        elif x + keys_w > max_right:
            return x
        for k in keys:
            x += draw_kbd(p, x, cy, k) + 3
        return x

    def _paint_class(self, p, index, inner, state, hover, color):
        head = QRectF(inner.left(), inner.top(), inner.width(), self.HEAD_H)
        self._highlight(p, head, state, hover)
        expanded = self.tree.isExpanded(index)
        expandable = bool(index.data(ROLE_EXPANDABLE))
        if expanded and index.model().rowCount(index) > 0:
            p.setPen(QPen(theme.qc("line"), 1))
            p.drawLine(QPointF(head.left(), head.bottom() - 0.5), QPointF(head.right() - 1, head.bottom() - 0.5))

        x = head.left() + 12
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(x, head.top() + 12, 11, 11), 3, 3)
        x += 20
        chev_w = 26 if expandable else 0
        max_right = head.right() - 10 - chev_w
        name = pretty(index.data(Qt.ItemDataRole.DisplayRole) or "")
        p.setFont(theme.ui_font(14, QFont.Weight.Bold))
        p.setPen(theme.qc("accent_ink") if state == "active" else theme.qc("ink"))
        fm = p.fontMetrics()
        keys = [k for k in (index.data(ROLE_KBD) or "").split("\t") if k]
        mono = QFontMetrics(theme.mono_font(10))
        reserve = sum(mono.horizontalAdvance(k) + 13 for k in keys) + 8 if keys else 0
        name_w = max(30, min(fm.horizontalAdvance(name), max_right - x - reserve))
        shown = _elide(p, name, name_w)
        p.drawText(QRectF(x, head.top() + 6, name_w + 2, 22), Qt.AlignmentFlag.AlignVCenter, shown)
        self._draw_keys(p, x + fm.horizontalAdvance(shown) + 8, head.top() + 17, keys, max_right,
                        self._word_fits("class", x, max_right, keys))

        n, photos = index.data(ROLE_COUNT) or 0, index.data(ROLE_PHOTOS) or 0
        p.setFont(theme.ui_font(11))
        p.setPen(theme.qc("dim"))
        sub = f"{n} etiket · {photos} fotoğraf"
        p.drawText(QRectF(x, head.top() + 26, max_right - x, 18), Qt.AlignmentFlag.AlignVCenter,
                   _elide(p, sub, max_right - x))

        if expandable:
            chev = "chevron-up" if expanded else "chevron-down"
            pm = _icon_pm(chev, theme.c("dim"), 16)
            p.drawPixmap(int(head.right() - 30), int(head.center().y() - 8), pm)

    def _paint_class_compact(self, p, index, inner, state, hover, color):
        """Tek satır başlık: ■ Ad [1] ............ 186 etiket · 153 foto  ˄"""
        head = QRectF(inner.left(), inner.top(), inner.width(), self.HEAD_H)
        self._highlight(p, head, state, hover)
        expanded = self.tree.isExpanded(index)
        expandable = bool(index.data(ROLE_EXPANDABLE))
        if expanded and index.model().rowCount(index) > 0:
            p.setPen(QPen(theme.qc("line"), 1))
            p.drawLine(QPointF(head.left(), head.bottom() - 0.5), QPointF(head.right() - 1, head.bottom() - 0.5))
        cy = head.center().y()
        x = head.left() + 12
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(x, cy - 5, 10, 10), 3, 3)
        x += 18
        right = head.right() - 10 - (26 if expandable else 0)

        n, photos = index.data(ROLE_COUNT) or 0, index.data(ROLE_PHOTOS) or 0
        f_sub = theme.ui_font(11)
        fm_sub = QFontMetrics(f_sub)
        long_t, short_t = f"{n} etiket · {photos} foto", f"{n} · {photos}"
        name = pretty(index.data(Qt.ItemDataRole.DisplayRole) or "")
        f_name = theme.ui_font(13, QFont.Weight.Bold)
        fm = QFontMetrics(f_name)
        keys = [k for k in (index.data(ROLE_KBD) or "").split("\t") if k]
        mono = QFontMetrics(theme.mono_font(10))
        keys_w = sum(mono.horizontalAdvance(k) + 13 for k in keys) + 8 if keys else 0
        fits = x + fm.horizontalAdvance(name) + keys_w + fm_sub.horizontalAdvance(long_t) + 10 <= right
        sub = long_t if fits else short_t
        sub_w = fm_sub.horizontalAdvance(sub)
        p.setFont(f_sub)
        p.setPen(theme.qc("dim"))
        p.drawText(QRectF(right - sub_w, head.top(), sub_w + 1, head.height()),
                   Qt.AlignmentFlag.AlignVCenter, sub)
        max_right = right - sub_w - 10
        p.setFont(f_name)
        p.setPen(theme.qc("accent_ink") if state == "active" else theme.qc("ink"))
        name_w = max(30, min(fm.horizontalAdvance(name), max_right - x - keys_w))
        shown = _elide(p, name, name_w)
        p.drawText(QRectF(x, head.top(), name_w + 2, head.height()), Qt.AlignmentFlag.AlignVCenter, shown)
        self._draw_keys(p, x + fm.horizontalAdvance(shown) + 8, cy, keys, max_right, False)
        if expandable:
            chev = "chevron-up" if expanded else "chevron-down"
            p.drawPixmap(int(head.right() - 30), int(cy - 7), _icon_pm(chev, theme.c("dim"), 14))

    def _paint_option_compact(self, p, index, inner, state, hover, color, first_child):
        """Tek satır: ˃ Ad [1][1] ....... ▬▬▬ %58   108  105"""
        rect = QRectF(inner.left(), inner.top(), inner.width(), self.OPT_H)
        if not first_child:
            p.setPen(QPen(theme.qc("line", 90), 1))
            p.drawLine(QPointF(rect.left() + 12, rect.top() + 0.5), QPointF(rect.right() - 10, rect.top() + 0.5))
        self._highlight(p, rect.adjusted(0, -1, 0, 1), state, hover)
        n = index.data(ROLE_COUNT) or 0
        photos = index.data(ROLE_PHOTOS) or 0
        zero = n == 0
        cy = rect.center().y()
        x = rect.left() + 8
        if index.data(ROLE_EXPANDABLE):
            chev = "chevron-down" if self.tree.isExpanded(index) else "chevron-right"
            p.drawPixmap(int(x), int(cy - 6), _icon_pm(chev, theme.c("dim"), 12))
        x += 16

        # sağdan sola: "8 foto" | "8 etiket" | yüzde | çubuk (çubuk kalan yere göre kısalır)
        f_num = theme.ui_font(11.5, QFont.Weight.Bold)
        f_num_dim = theme.ui_font(11)
        f_unit = theme.ui_font(10)
        f_pct = theme.ui_font(10, QFont.Weight.DemiBold)
        fm_unit = QFontMetrics(f_unit)
        count_num_w = QFontMetrics(f_num).horizontalAdvance("0" * max(2, self.count_digits))
        photo_num_w = QFontMetrics(f_num_dim).horizontalAdvance("0" * max(2, self.photo_digits))
        pct_w = QFontMetrics(f_pct).horizontalAdvance("%100") + 2

        def num_unit(x_right, num, unit, f, pen, num_w):
            """Sayı (sağa yaslı, sabit genişlik) + birim. Sütunlar alt alta hizalı kalsın."""
            unit_w = fm_unit.horizontalAdvance(unit)
            p.setFont(f_unit)
            p.setPen(theme.qc("dim"))
            p.drawText(QRectF(x_right - unit_w, rect.top(), unit_w + 1, rect.height()),
                       Qt.AlignmentFlag.AlignVCenter, unit)
            p.setFont(f)
            p.setPen(pen)
            x_num = x_right - unit_w - 3 - num_w
            p.drawText(QRectF(x_num, rect.top(), num_w, rect.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(num))
            return x_num

        xr = rect.right() - 10
        xr = num_unit(xr, photos, "foto", f_num_dim, theme.qc("dim"), photo_num_w) - 8
        xr = num_unit(xr, n, "etiket", f_num, theme.qc("warn") if zero else theme.qc("ink"), count_num_w) - 8
        share = float(index.data(ROLE_SHARE) or 0)
        p.setFont(f_pct)
        p.setPen(theme.qc("dim"))
        p.drawText(QRectF(xr - pct_w, rect.top(), pct_w, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"%{round(share * 100)}")
        xr -= pct_w + 5
        # ad + kısayol için gereken yer (en uzun ada göre, bütün satırlarda aynı) ayrıldıktan sonra kalan: çubuk
        mono = QFontMetrics(theme.mono_font(10))
        keys_room = 2 * (mono.horizontalAdvance("9") + 13) + 6
        bar_w = min(60, xr - x - self.max_name["option"] - keys_room - 8)
        if bar_w >= 16:
            bar = QRectF(xr - bar_w, cy - 2, bar_w, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.qc("line"))
            p.drawRoundedRect(bar, 2, 2)
            if share > 0:
                p.setBrush(color)
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(4, bar_w * min(1.0, share)), 4), 2, 2)
            xr = bar.left()
        max_right = xr - 6

        name = pretty(index.data(Qt.ItemDataRole.DisplayRole) or "")
        p.setFont(theme.ui_font(12, QFont.Weight.DemiBold))
        if state == "active":
            p.setPen(theme.qc("accent_ink"))
        else:
            p.setPen(theme.qc("dim") if zero else theme.qc("ink"))
        fm = p.fontMetrics()
        keys = [k for k in (index.data(ROLE_KBD) or "").split("\t") if k]
        mono = QFontMetrics(theme.mono_font(10))
        reserve = sum(mono.horizontalAdvance(k) + 13 for k in keys) + 6 if keys else 0
        name_w = max(30, min(fm.horizontalAdvance(name), max_right - x - reserve))
        shown = _elide(p, name, name_w)
        p.drawText(QRectF(x, rect.top(), name_w + 2, rect.height()), Qt.AlignmentFlag.AlignVCenter, shown)
        self._draw_keys(p, x + fm.horizontalAdvance(shown) + 6, cy, keys, max_right,
                        self._word_fits("option", x, max_right, keys))

    def _paint_attr(self, p, index, inner, state):
        rect = QRectF(inner.left(), inner.top(), inner.width(), self.ATTR_H)
        if state == "pending":
            self._highlight(p, rect, state, False)
        p.setFont(theme.ui_font(11, QFont.Weight.DemiBold))
        p.setPen(theme.qc("warn") if state == "pending" else theme.qc("dim"))
        text = pretty(index.data(Qt.ItemDataRole.DisplayRole) or "")
        p.drawText(rect.adjusted(14, 2, -10, 0), Qt.AlignmentFlag.AlignVCenter, _elide(p, text, rect.width() - 24))

    def _paint_option(self, p, index, inner, state, hover, color, first_child):
        rect = QRectF(inner.left(), inner.top(), inner.width(), self.OPT_H)
        if not first_child:
            p.setPen(QPen(theme.qc("line", 110), 1))
            p.drawLine(QPointF(rect.left() + 12, rect.top() + 0.5), QPointF(rect.right() - 10, rect.top() + 0.5))
        self._highlight(p, rect, state, hover)

        n = index.data(ROLE_COUNT) or 0
        photos = index.data(ROLE_PHOTOS) or 0
        zero = n == 0
        expandable = bool(index.data(ROLE_EXPANDABLE))

        # etikete göre gezinme oku (solda)
        x = rect.left() + 8
        if expandable:
            chev = "chevron-down" if self.tree.isExpanded(index) else "chevron-right"
            p.drawPixmap(int(x), int(rect.top() + 6), _icon_pm(chev, theme.c("dim"), 14))
        x += 18

        f_count = theme.ui_font(12, QFont.Weight.Bold)
        f_photo = theme.ui_font(11)
        col_w = self._right_cols(f_count, f_photo)
        col_x = rect.right() - 12 - col_w
        p.setFont(f_count)
        p.setPen(theme.qc("warn") if zero else theme.qc("ink"))
        p.drawText(QRectF(col_x, rect.top() + 4, col_w, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{n} etiket")
        p.setFont(f_photo)
        p.setPen(theme.qc("dim"))
        p.drawText(QRectF(col_x, rect.top() + 21, col_w, 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{photos} foto")

        max_right = col_x - 10
        name = pretty(index.data(Qt.ItemDataRole.DisplayRole) or "")
        p.setFont(theme.ui_font(12, QFont.Weight.DemiBold))
        if state == "active":
            p.setPen(theme.qc("accent_ink"))
        else:
            p.setPen(theme.qc("dim") if zero else theme.qc("ink"))
        fm = p.fontMetrics()
        keys = [k for k in (index.data(ROLE_KBD) or "").split("\t") if k]
        reserve = 0
        if keys:
            mono = QFontMetrics(theme.mono_font(10))
            reserve = sum(mono.horizontalAdvance(k) + 13 for k in keys) + 6
        name_w = max(30, min(fm.horizontalAdvance(name), max_right - x - reserve))
        shown = _elide(p, name, name_w)
        p.drawText(QRectF(x, rect.top() + 3, name_w + 2, 20), Qt.AlignmentFlag.AlignVCenter, shown)
        self._draw_keys(p, x + fm.horizontalAdvance(shown) + 7, rect.top() + 13, keys, max_right,
                        self._word_fits("option", x, max_right, keys))

        # dağılım çubuğu: seçeneğin sınıfındaki payı
        share = float(index.data(ROLE_SHARE) or 0)
        # yüzde, çubuğun sağında (sınıfın etiketleri içindeki pay)
        f_pct = theme.ui_font(11, QFont.Weight.DemiBold)
        pct_w = QFontMetrics(f_pct).horizontalAdvance("%100") + 2
        pct_x = max_right - pct_w
        p.setFont(f_pct)
        p.setPen(theme.qc("dim"))
        p.drawText(QRectF(pct_x, rect.top() + 22, pct_w, 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"%{round(share * 100)}")
        bar = QRectF(x, rect.top() + 28, max(10, pct_x - 8 - x), 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.qc("line"))
        p.drawRoundedRect(bar, 2.5, 2.5)
        if share > 0:
            fill = QRectF(bar.left(), bar.top(), max(bar.height(), bar.width() * min(1.0, share)), bar.height())
            p.setBrush(color)
            p.drawRoundedRect(fill, 2.5, 2.5)

    def _paint_photo(self, p, index, inner, state, hover):
        rect = QRectF(inner.left(), inner.top(), inner.width(), self.PHOTO_H)
        self._highlight(p, rect, state, hover)
        x = rect.left() + 34
        n = index.data(ROLE_COUNT)
        count = f"{n} etiket" if n is not None else ""
        p.setFont(theme.ui_font(11))
        cw = p.fontMetrics().horizontalAdvance(count)
        p.setPen(theme.qc("dim"))
        p.drawText(QRectF(rect.right() - 12 - cw, rect.top(), cw, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter, count)
        p.drawPixmap(int(x - 18), int(rect.center().y() - 6), _icon_pm("image", theme.c("dim"), 12))
        weight = QFont.Weight.DemiBold if state in ("current", "browse") else QFont.Weight.Normal
        p.setFont(theme.ui_font(12, weight))
        p.setPen(theme.qc("accent_ink") if state == "browse" else theme.qc("ink"))
        w = rect.right() - 12 - cw - 8 - x
        p.drawText(QRectF(x, rect.top(), w, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                   _elide(p, index.data(Qt.ItemDataRole.DisplayRole) or "", w))
