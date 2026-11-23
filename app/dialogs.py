from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QKeySequenceEdit, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QRadioButton,
    QSpinBox, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import shortcuts, theme, voice
from . import widgets as W
from .exporters import box_wanted
from .panel import pretty
from .selection import KeySelector


def color_icon(color):
    return W.dot_icon(color)


def _dialog_layout(dlg, title):
    """Pencere iskeleti: üstte başlık, ortada gövde, altta düğmeler (araları çizgiyle ayrılmış)."""
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    head = QWidget()
    hl = QHBoxLayout(head)
    hl.setContentsMargins(18, 14, 18, 12)
    hl.addWidget(W.label(title, "dialogTitle"))
    hl.addStretch()
    outer.addWidget(head)
    outer.addWidget(W.hline())
    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(18, 14, 18, 14)
    bl.setSpacing(10)
    outer.addWidget(body, 1)
    outer.addWidget(W.hline())
    foot = QWidget()
    fl = QHBoxLayout(foot)
    fl.setContentsMargins(18, 12, 18, 12)
    fl.setSpacing(8)
    outer.addWidget(foot)
    return bl, fl


# =====================================================================
#  Sınıf / Attribute / Seçenek ayarları
# =====================================================================
class _Column(QFrame):
    """Başlık + liste + 'yaz, Enter' kutusu + düğmeler."""

    def __init__(self, title, placeholder, parent=None):
        super().__init__(parent)
        self.setProperty("column", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.title = W.label(title, "strong")
        self.title.setContentsMargins(4, 0, 0, 0)
        lay.addWidget(self.title)
        self.list = QListWidget()
        self.list.setIconSize(QSize(10, 10))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.btn_add = W.push_button("", "plus")
        self.btn_add.setProperty("mini", True)
        self.btn_add.setToolTip("Ekle (Enter)")
        self.btn_add.setAutoDefault(False)
        self.btn_add.clicked.connect(self.edit.returnPressed)
        add_row = QHBoxLayout()
        add_row.setSpacing(4)
        add_row.addWidget(self.edit, 1)
        add_row.addWidget(self.btn_add)
        self.btn_rename = W.push_button("Yeniden adlandır", "pencil")
        self.btn_delete = W.push_button("", "trash-2")
        self.btn_delete.setProperty("mini", True)
        self.btn_delete.setToolTip("Sil")
        for b in (self.btn_rename, self.btn_delete):
            b.setProperty("flat", True)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.btn_rename)
        row.addWidget(self.btn_delete)
        row.addStretch()
        self.extra = row
        lay.addWidget(self.list, 1)
        lay.addLayout(add_row)
        lay.addLayout(row)

    def setTitle(self, text):
        self.title.setText(text)

    def current(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def fill(self, names, keep=None, icons=None):
        self.list.blockSignals(True)
        self.list.clear()
        for n in names:
            it = QListWidgetItem(n)
            it.setData(Qt.ItemDataRole.UserRole, n)
            if icons:
                it.setIcon(icons[n])
            self.list.addItem(it)
        target = keep if keep in names else (names[0] if names else None)
        if target is not None:
            self.list.setCurrentRow(names.index(target))
        self.list.blockSignals(False)

    def set_enabled(self, on):
        for w in (self.list, self.edit, self.btn_add, self.btn_rename, self.btn_delete):
            w.setEnabled(on)


class SetupDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.p = project
        self.setWindowTitle("Sınıfları düzenle")
        self.resize(780, 480)
        body, foot = _dialog_layout(self, "Sınıfları düzenle")

        info = W.label("Sınıfı seç, özelliklerini ve seçeneklerini düzenle. Adı yazıp <b>Enter</b>'a bas "
                       "(ör. <i>corba</i> → <i>tur</i> → <i>mercimek</i>, <i>ezogelin</i>).", "muted", wrap=True)

        self.c_cls = _Column("Sınıflar", "Yeni sınıf")
        self.c_attr = _Column("Özellikler", "Yeni özellik")
        self.c_opt = _Column("Seçenekler", "Yeni seçenek")
        self.btn_color = W.push_button("Renk")
        self.btn_color.setProperty("flat", True)
        self.btn_color.setToolTip("Sınıfın rengini değiştir")
        self.c_cls.extra.insertWidget(2, self.btn_color)

        cols = QHBoxLayout()
        cols.setSpacing(9)
        for c in (self.c_cls, self.c_attr, self.c_opt):
            cols.addWidget(c, 1)
        close = W.push_button("Kapat", slot=self.accept)
        close.setAutoDefault(False)        # Enter pencereyi kapatmasın

        body.addWidget(info)
        body.addLayout(cols, 1)
        foot.addWidget(W.label("Değişiklikler otomatik kaydedilir.", "muted"))
        foot.addStretch()
        foot.addWidget(close)

        self.c_cls.list.currentRowChanged.connect(lambda _: self.refresh_attrs())
        self.c_attr.list.currentRowChanged.connect(lambda _: self.refresh_opts())
        self.c_cls.edit.returnPressed.connect(self.add_class)
        self.c_attr.edit.returnPressed.connect(self.add_attr)
        self.c_opt.edit.returnPressed.connect(self.add_opt)
        for col, kind in ((self.c_cls, "cls"), (self.c_attr, "attr"), (self.c_opt, "opt")):
            col.btn_rename.clicked.connect(lambda _=False, k=kind: self.rename(k))
            col.btn_delete.clicked.connect(lambda _=False, k=kind: self.delete(k))
            col.list.itemDoubleClicked.connect(lambda _it, k=kind: self.rename(k))
            for b in (col.btn_rename, col.btn_delete):
                b.setAutoDefault(False)
        self.btn_color.setAutoDefault(False)
        self.btn_color.clicked.connect(self.pick_color)

        self.refresh_classes()
        self.c_cls.edit.setFocus()

    # ---------- yenileme ----------
    def refresh_classes(self, keep=None):
        names = self.p.class_names()
        self.c_cls.fill(names, keep or self.c_cls.current(),
                        {c["ad"]: color_icon(c["renk"]) for c in self.p.classes})
        cur = self.c_cls.current()
        self.btn_color.setIcon(color_icon(self.p.color(cur)) if cur else QIcon())
        self.btn_color.setEnabled(bool(names))
        self.refresh_attrs()

    def refresh_attrs(self, keep=None):
        cls = self.p.get_class(self.c_cls.current() or "")
        self.c_attr.set_enabled(cls is not None)
        self.c_attr.setTitle(f"Özellikler — {cls['ad']}" if cls else "Özellikler")
        self.c_attr.fill([a["ad"] for a in cls["attributeler"]] if cls else [], keep or self.c_attr.current())
        self.refresh_opts()

    def refresh_opts(self, keep=None):
        cls, attr = self.c_cls.current(), self.c_attr.current()
        a = self.p.get_attr(cls, attr) if cls and attr else None
        self.c_opt.set_enabled(a is not None)
        self.c_opt.setTitle(f"Seçenekler — {attr}" if a else "Seçenekler")
        self.c_opt.fill(a["secenekler"] if a else [], keep)

    # ---------- ekleme ----------
    def _take(self, edit):
        text = edit.text().strip()
        edit.clear()
        return text

    def add_class(self):
        name = self._take(self.c_cls.edit)
        if name and not self.p.add_class(name):
            QMessageBox.warning(self, "Uyarı", "Bu sınıf zaten var.")
            return
        if name:
            self.refresh_classes(keep="_".join(name.split()))
            self.c_attr.edit.setFocus()

    def add_attr(self):
        name = self._take(self.c_attr.edit)
        if name and not self.p.add_attribute(self.c_cls.current(), name):
            QMessageBox.warning(self, "Uyarı", "Bu özellik zaten var.")
            return
        if name:
            self.refresh_attrs(keep="_".join(name.split()))
            self.c_opt.edit.setFocus()

    def add_opt(self):
        name = self._take(self.c_opt.edit)
        if name and not self.p.add_option(self.c_cls.current(), self.c_attr.current(), name):
            QMessageBox.warning(self, "Uyarı", "Bu seçenek zaten var.")
            return
        if name:
            self.refresh_opts()

    # ---------- yeniden adlandır / sil ----------
    def rename(self, kind):
        cls, attr, opt = self.c_cls.current(), self.c_attr.current(), self.c_opt.current()
        old = {"cls": cls, "attr": attr, "opt": opt}[kind]
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Yeniden adlandır", "Yeni ad:", text=old)
        if not ok or not new.strip() or new.strip() == old:
            return
        if kind == "cls":
            done = self.p.rename_class(old, new)
        elif kind == "attr":
            done = self.p.rename_attribute(cls, old, new)
        else:
            done = self.p.rename_option(cls, attr, old, new)
        if not done:
            QMessageBox.warning(self, "Uyarı", "Bu ad zaten kullanılıyor.")
            return
        new = "_".join(new.split())
        if kind == "cls":
            self.refresh_classes(keep=new)
        elif kind == "attr":
            self.refresh_attrs(keep=new)
        else:
            self.refresh_opts(keep=new)

    def delete(self, kind):
        cls, attr, opt = self.c_cls.current(), self.c_attr.current(), self.c_opt.current()
        if kind == "cls" and cls:
            n = self.p.count_class(cls)
            msg = f"'{cls}' sınıfı silinsin mi?"
            if n:
                msg += f"\n\nDİKKAT: Bu sınıfla etiketlenmiş {n} kutu da silinecek!"
            if self._confirm(msg):
                self.p.remove_class(cls)
                self.refresh_classes()
        elif kind == "attr" and attr:
            if self._confirm(f"'{attr}' özelliği silinsin mi?\n(Kutulardaki bu bilgi de silinir.)"):
                self.p.remove_attribute(cls, attr)
                self.refresh_attrs()
        elif kind == "opt" and opt:
            n = self.p.count_option(cls, attr, opt)
            msg = f"'{opt}' seçeneği silinsin mi?"
            if n:
                msg += f"\n\n{n} kutuda bu seçenek seçili; onlar '(seçilmemiş)' olarak kalacak."
            if self._confirm(msg):
                self.p.remove_option(cls, attr, opt)
                self.refresh_opts()

    def _confirm(self, msg):
        return QMessageBox.question(self, "Onay", msg) == QMessageBox.StandardButton.Yes

    def pick_color(self):
        cls = self.c_cls.current()
        if not cls:
            return
        c = QColorDialog.getColor(QColor(self.p.color(cls)), self, f"{cls} rengi")
        if c.isValid():
            self.p.set_class_color(cls, c.name())
            self.refresh_classes(keep=cls)


# =====================================================================
#  "Bu ne?" — kutu çizildikten sonra açılan seçim penceresi
# =====================================================================
class LabelDialog(QDialog):
    """Kutu çizilince açılan seçim penceresi. Tuşlar ana ekrandakiyle aynı çalışır:
    1. tuş sınıf, sonraki tuşlar sırayla seçenekler (ör. 1 sonra 3 = corba / mantar)."""

    def __init__(self, project, current=None, memory=None, selector=None, parent=None):
        super().__init__(parent)
        self.p = project
        self.memory = memory or {}
        self.sel = KeySelector(project)
        self.built_for = None
        self.attr_box = None
        self.attr_groups = {}
        self.setWindowTitle("Kutu etiketi")
        self.setMinimumWidth(420)
        lay, foot = _dialog_layout(self, "Kutu etiketi")

        self.hint = W.label("", "muted", wrap=True)
        lay.addWidget(self.hint)
        lay.addWidget(W.label("Sınıf", "strong"))
        self.cls_group = QButtonGroup(self)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, c in enumerate(project.classes):
            b = W.ChoiceButton(c["ad"], c.get("kisayol", ""), c["renk"])
            self.cls_group.addButton(b, i)
            grid.addWidget(b, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addWidget(W.hline())
        self.attr_holder = QVBoxLayout()
        lay.addLayout(self.attr_holder)

        cancel = W.push_button("İptal · Esc", slot=self.reject)
        ok = W.push_button("Onayla · Enter", slot=self.accept, primary=True)
        ok.setDefault(True)
        cancel.setAutoDefault(False)
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        foot.addStretch()
        foot.addWidget(cancel)
        foot.addWidget(ok)

        for key in self.sel.all_keys():
            QShortcut(QKeySequence(key), self).activated.connect(lambda k=key: self._on_key(k))
        self.cls_group.idClicked.connect(self._class_clicked)

        # başlangıç durumu
        names = project.class_names()
        if selector is not None and selector.cls:
            self.sel.set_class(selector.cls, selector.attrs, waiting=True)
        elif current:
            self.sel.set_class(current["sinif"], current.get("attributeler", {}), waiting=False)
        elif names:
            start = self.memory.get("sinif") if self.memory.get("sinif") in names else names[0]
            self.sel.set_class(start, self.memory.get("attr", {}).get(start, {}), waiting=False)
        self._sync()

    # ---------- olaylar ----------
    def _on_key(self, key):
        if self.sel.press(key):
            self._sync()

    def _class_clicked(self, idx):
        cls = self.p.classes[idx]["ad"]
        if cls != self.sel.cls:
            self.sel.set_class(cls)
            self._sync()

    def _option_clicked(self, attr, value):
        self.sel.set_option(attr, value)
        self._sync()

    # ---------- arayüzü seçimle eşitle ----------
    def _sync(self):
        cls = self.sel.cls
        if cls is None:
            return
        idx = self.p.class_names().index(cls)
        self.cls_group.button(idx).setChecked(True)
        if self.built_for != cls:
            self._build_attrs(cls)
        for name, (group, values) in self.attr_groups.items():
            v = self.sel.attrs.get(name)
            if v in values:
                group.button(values.index(v)).setChecked(True)
        if self.sel.pending:
            self.hint.setText(f"{cls} › <b>{self.sel.pending}</b> için tuşa bas:  {self.sel.options_hint()}")
        else:
            self.hint.setText("Önce sınıfın, sonra seçeneğin tuşuna bas ya da tıkla. Enter onaylar.")

    def _build_attrs(self, cls):
        self.built_for = cls
        if self.attr_box is not None:
            self.attr_box.deleteLater()
        self.attr_box = QWidget()
        self.attr_lay = QVBoxLayout(self.attr_box)
        self.attr_lay.setContentsMargins(0, 0, 0, 0)
        self.attr_holder.addWidget(self.attr_box)
        self.attr_groups = {}
        remembered = self.memory.get("attr", {}).get(cls, {})
        self.attr_lay.setSpacing(6)
        for a in self.sel.attr_defs(cls):
            self.attr_lay.addWidget(W.label(a["ad"], "strong"))
            group = QButtonGroup(self.attr_box)
            grid = QGridLayout()
            grid.setSpacing(6)
            keys = a.get("kisayollar", {})
            for j, v in enumerate(a["secenekler"]):
                b = W.ChoiceButton(v, keys.get(v, ""))
                b.clicked.connect(lambda _=False, an=a["ad"], val=v: self._option_clicked(an, val))
                group.addButton(b, j)
                grid.addWidget(b, j // 3, j % 3)
            # henüz seçilmediyse son kullanılanı ya da ilkini işaretle
            want = remembered.get(a["ad"])
            group.button(a["secenekler"].index(want) if want in a["secenekler"] else 0).setChecked(True)
            self.attr_lay.addLayout(grid)
            self.attr_groups[a["ad"]] = (group, a["secenekler"])
        if not self.attr_groups:
            self.attr_lay.addWidget(W.label("Bu sınıfa seçenek tanımlanmamış.", "muted"))
        self.adjustSize()

    def result_box(self):
        cls = self.p.classes[self.cls_group.checkedId()]["ad"]
        attrs = {name: values[g.checkedId()] for name, (g, values) in self.attr_groups.items()
                 if g.checkedId() >= 0}
        return cls, attrs


# =====================================================================
#  Dışa aktar
# =====================================================================
def _stepper(spin):
    """Sayı kutusunun yanına − / + düğmeleri koyar (temada okları gizli).
    Etkin / pasif yapmak için dönen widget kullanılır."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
    row.addWidget(W.tool_button("−", tip="Azalt", slot=spin.stepDown, outline=True, square=True))
    row.addWidget(spin)
    row.addWidget(W.tool_button("+", tip="Artır", slot=spin.stepUp, outline=True, square=True))
    return box


class ExportDialog(QDialog):
    FORMATS = [   # (anahtar, ad, açıklama, varsayılan)
        ("json", "JSON", "Proje etiketleri", True),
        ("jpg", "Etiketli JPG", "Kutuların görsel kontrolü", True),
        ("cvat", "CVAT XML", "CVAT'a geri yükleme", True),
        ("voc", "Pascal VOC XML", "Fotoğraf başına XML", False),
        ("yolo", "YOLO", "TXT ve data.yaml", True),
        ("coco", "COCO JSON", "COCO biçiminde tek dosya", False),
        ("kirp", "Kesilmiş kutular", "Her etiket ayrı foto, yeni proje", False),
    ]

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.p = project
        self.setWindowTitle("Dışa aktar")
        self.setMinimumWidth(640)
        lay, foot = _dialog_layout(self, "Dışa aktar")

        fbox = QGroupBox("Çıktı formatları")
        fl = QGridLayout(fbox)
        fl.setHorizontalSpacing(16)
        fl.setVerticalSpacing(2)
        self.checks = {}
        for i, (key, name, desc, default) in enumerate(self.FORMATS):
            cell = QHBoxLayout()
            cell.setSpacing(0)
            cb = QCheckBox(name)
            cb.setStyleSheet("QCheckBox { font-weight: 700; }")
            cb.setChecked(default)
            cell.addWidget(cb)
            cell.addWidget(W.label(f" · {desc}", "small"))
            cell.addStretch()
            fl.addLayout(cell, i // 2, i % 2)
            self.checks[key] = cb
            cb.toggled.connect(lambda _=False: self.err.hide())
        lay.addWidget(fbox)
        self.err = W.label("En az bir çıktı biçimi seç.", "error")
        self.err.hide()
        lay.addWidget(self.err)

        self.ybox = QGroupBox("YOLO ayarları")
        yl = QVBoxLayout(self.ybox)
        yl.setSpacing(2)
        self.y_cls = QRadioButton("Yalnızca sınıf · corba")
        self.y_attr = QRadioButton("Sınıf + seçenek · corba_mercimek, corba_ezogelin …")
        self.y_attr.setChecked(True)
        yl.addWidget(self.y_cls)
        yl.addWidget(self.y_attr)
        vrow = QHBoxLayout()
        self.val_check = QCheckBox("Train / Val olarak ayır")
        self.val_check.setChecked(True)
        self.val_spin = QSpinBox()
        self.val_spin.setRange(5, 50)
        self.val_spin.setValue(20)
        self.val_spin.setFixedWidth(64)
        vrow.addWidget(self.val_check)
        vrow.addStretch()
        vrow.addWidget(W.label("Val %", "muted"))
        val_box = _stepper(self.val_spin)
        self.val_check.toggled.connect(val_box.setEnabled)
        vrow.addWidget(val_box)
        yl.addLayout(vrow)
        lay.addWidget(self.ybox)
        self.checks["yolo"].toggled.connect(self.ybox.setEnabled)

        self.cbox = QGroupBox("Kesilmiş kutular · yeni etiketli proje olarak")
        cv = QVBoxLayout(self.cbox)
        cv.setSpacing(4)
        cl = QHBoxLayout()
        cv.addLayout(cl)
        cl.addWidget(W.label("Kutunun her kenarından dışarı pay", "muted"))
        cl.addStretch()
        self.pad_spin = QSpinBox()
        self.pad_spin.setRange(0, 500)
        self.pad_spin.setValue(6)
        self.pad_spin.setSuffix(" px")
        self.pad_spin.setFixedWidth(84)
        cl.addWidget(_stepper(self.pad_spin))
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.crop_edit = QLineEdit(str(self._default_crop_dir(project)))
        self.crop_edit.setProperty("path", True)
        self.crop_edit.setPlaceholderText("Yeni proje klasörü")
        self.crop_edit.setToolTip("Kesitler bu klasörde yeni bir proje olarak oluşturulur (klasör boş olmalı)")
        self.crop_edit.textChanged.connect(lambda _=None: self.crop_err.hide())
        cbrowse = W.push_button("Proje klasörü seç", "folder-open", slot=self._browse_crop)
        cbrowse.setAutoDefault(False)
        prow.addWidget(self.crop_edit, 1)
        prow.addWidget(cbrowse)
        cv.addLayout(prow)
        crow = QHBoxLayout()
        crow.addWidget(W.label("Kesilecek etiketler", "muted"))
        crow.addStretch()
        self.crop_count = W.label("", "small")
        crow.addWidget(self.crop_count)
        cv.addSpacing(4)
        cv.addLayout(crow)
        self.crop_tree = self._build_crop_tree(project)
        cv.addWidget(self.crop_tree)
        self.crop_err = W.label("", "error")
        self.crop_err.hide()
        cv.addWidget(self.crop_err)
        lay.addWidget(self.cbox)
        self._update_crop_count()
        # ayarlara dokunulunca biçimi de işaretle (unutulmasın)
        self.pad_spin.valueChanged.connect(lambda _=None: self.checks["kirp"].setChecked(True))
        self.crop_edit.textEdited.connect(lambda _=None: self.checks["kirp"].setChecked(True))

        gbox = QGroupBox("Kapsam ve klasör")
        gl = QVBoxLayout(gbox)
        gl.setSpacing(2)
        self.only_labeled = QCheckBox("Sadece etiketlenmiş fotoğraflar")
        self.only_labeled.setChecked(True)
        self.copy_images = QCheckBox("Orijinal fotoğrafları da kopyala (YOLO / VOC / COCO klasörlerine)")
        self.copy_images.setChecked(True)
        gl.addWidget(self.only_labeled)
        gl.addWidget(self.copy_images)
        lrow = QHBoxLayout()
        self.limit_check = QCheckBox("Sadece ilk N fotoğraf (deneme için)")
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 100000)
        self.limit_spin.setValue(10)
        self.limit_spin.setFixedWidth(84)
        limit_box = _stepper(self.limit_spin)
        limit_box.setEnabled(False)
        self.limit_check.toggled.connect(limit_box.setEnabled)
        lrow.addWidget(self.limit_check)
        lrow.addStretch()
        lrow.addWidget(limit_box)
        gl.addLayout(lrow)
        orow = QHBoxLayout()
        orow.setSpacing(6)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        self.out_edit = QLineEdit(str(project.export_dir / stamp))
        self.out_edit.setProperty("path", True)
        self.out_edit.setToolTip(self.out_edit.text())
        self.out_edit.textChanged.connect(self.out_edit.setToolTip)
        browse = W.push_button("Klasör seç", "folder-open", slot=self._browse)
        browse.setAutoDefault(False)
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(browse)
        gl.addSpacing(6)
        gl.addLayout(orow)
        lay.addWidget(gbox)

        cancel = W.push_button("İptal", slot=self.reject)
        cancel.setAutoDefault(False)
        ok = W.push_button("Dışa aktar", "download", slot=self._ok, primary=True)
        ok.setDefault(True)
        foot.addStretch()
        foot.addWidget(cancel)
        foot.addWidget(ok)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Dışa aktarma klasörü", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    # ---------- kesilecek etiket seçimi (sınıf / seçenek ağacı) ----------
    def _build_crop_tree(self, project):
        """Sınıf → (özellik →) seçenek, hepsi işaretli. Üst kutu alttakileri izler (yarım işaretli olabilir)."""
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tree.setProperty("framed", True)
        tree.setIndentation(18)
        counts = {}
        for data in getattr(project, "annotations", {}).values():
            for b in data["kutular"]:
                counts[b["sinif"]] = counts.get(b["sinif"], 0) + 1
                for a, v in b.get("attributeler", {}).items():
                    if v:
                        key = (b["sinif"], a, v)
                        counts[key] = counts.get(key, 0) + 1
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable

        def node(parent, text, n, data, tristate=False):
            it = QTreeWidgetItem([f"{text}  ({n})" if n is not None else text])
            it.setFlags(flags | (Qt.ItemFlag.ItemIsAutoTristate if tristate else Qt.ItemFlag.NoItemFlags))
            it.setCheckState(0, Qt.CheckState.Checked)
            it.setData(0, Qt.ItemDataRole.UserRole, data)
            (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(it)
            return it

        rows = 0
        for c in getattr(project, "classes", []):
            attrs = [a for a in c["attributeler"] if a["secenekler"]]
            top = node(tree, pretty(c["ad"]), counts.get(c["ad"], 0), ("class", c["ad"]), tristate=bool(attrs))
            top.setIcon(0, W.dot_icon(c["renk"]))
            rows += 1
            for a in attrs:
                parent = top
                if len(attrs) > 1:      # birden çok özellik: ara başlık
                    parent = node(top, pretty(a["ad"]), None, ("attr", c["ad"], a["ad"]), tristate=True)
                    rows += 1
                for v in a["secenekler"]:
                    node(parent, pretty(v), counts.get((c["ad"], a["ad"], v), 0), ("opt", c["ad"], a["ad"], v))
                    rows += 1
        tree.expandAll()
        tree.setFixedHeight(min(rows, 9) * 24 + 8)
        tree.itemChanged.connect(lambda *_: self._on_crop_tree_changed())
        return tree

    def _on_crop_tree_changed(self):
        self.crop_err.hide()
        self.checks["kirp"].setChecked(True)
        self._update_crop_count()

    def crop_filter(self):
        """None: hepsi. Yoksa {sınıf: {özellik: {seçenekler} ya da None (hepsi)}}."""
        out, everything = {}, True
        for i in range(self.crop_tree.topLevelItemCount()):
            top = self.crop_tree.topLevelItem(i)
            state = top.checkState(0)
            if state != Qt.CheckState.Checked:
                everything = False
            if state == Qt.CheckState.Unchecked:
                continue
            cls = top.data(0, Qt.ItemDataRole.UserRole)[1]
            attrs = {}
            stack = [top.child(k) for k in range(top.childCount())]
            while stack:
                it = stack.pop()
                data = it.data(0, Qt.ItemDataRole.UserRole)
                if data[0] == "attr":
                    stack.extend(it.child(k) for k in range(it.childCount()))
                    continue
                _, _, attr, val = data
                attrs.setdefault(attr, {"all": True, "on": set()})
                if it.checkState(0) == Qt.CheckState.Checked:
                    attrs[attr]["on"].add(val)
                else:
                    attrs[attr]["all"] = False
            out[cls] = {a: (None if d["all"] else d["on"]) for a, d in attrs.items()}
        return None if everything else out

    def _update_crop_count(self):
        f = self.crop_filter()
        n = sum(1 for d in getattr(self.p, "annotations", {}).values() for b in d["kutular"]
                if box_wanted(f, b))
        self.crop_count.setText(f"{n} etiket kesilecek")

    @staticmethod
    def _default_crop_dir(project):
        root = getattr(project, "root", None)
        if root is None:
            return ""
        base = root.parent / f"{root.name}-kesilmis"
        d, i = base, 2
        while d.exists() and any(d.iterdir()):
            d = base.with_name(f"{base.name}-{i}")
            i += 1
        return d

    def _browse_crop(self):
        d = QFileDialog.getExistingDirectory(self, "Kesitler için proje klasörü seçin (boş klasör)",
                                             self.crop_edit.text())
        if d:
            self.crop_edit.setText(d)
            self.checks["kirp"].setChecked(True)

    def _crop_dir_error(self):
        text = self.crop_edit.text().strip()
        if not text:
            return "Kesitler için bir proje klasörü seç."
        d = Path(text)
        if d.exists() and not d.is_dir():
            return "Seçilen yol bir klasör değil."
        if d.exists() and any(d.iterdir()):
            return "Bu klasör boş değil. Boş ya da yeni bir klasör seç."
        root = getattr(self.p, "root", None)
        if root is not None and d.resolve() == Path(root).resolve():
            return "Açık olan projenin klasörü seçilemez."
        return None

    def _ok(self):
        if not self.formats():
            self.err.show()
            return
        if "kirp" in self.formats():
            err = self._crop_dir_error()
            if not err and self.crop_filter() is not None and not self.crop_filter():
                err = "Kesilecek en az bir etiket seç."
            if err:
                self.crop_err.setText(err)
                self.crop_err.show()
                return
        self.accept()

    def formats(self):
        return [k for k, cb in self.checks.items() if cb.isChecked()]

    def options(self):
        return {
            "out_dir": self.out_edit.text().strip(),
            "only_labeled": self.only_labeled.isChecked(),
            "copy_images": self.copy_images.isChecked(),
            "yolo_mode": "sinif_attr" if self.y_attr.isChecked() else "sinif",
            "val_percent": self.val_spin.value() if self.val_check.isChecked() else 0,
            "crop_padding": self.pad_spin.value(),
            "crop_project": self.crop_edit.text().strip(),
            "crop_filter": self.crop_filter(),
            "limit": self.limit_spin.value() if self.limit_check.isChecked() else 0,
        }


# =====================================================================
#  İstatistik
# =====================================================================
class StatsDialog(QDialog):
    """Genel sayılar + her sınıf / seçenek için etiket ve fotoğraf sayısı."""
    COLS = ["Sınıf / seçenek", "Etiket", "Fotoğraf", "Fotoğrafların %'si", "Foto başına etiket"]

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.p = project
        self.setWindowTitle("İstatistik")
        self.resize(760, 640)
        lay, foot = _dialog_layout(self, f"İstatistik · {project.name}")

        st = project.stats()
        n_all = len(project.list_images())
        n_lab = st["etiketli_resim"]
        n_box = st["toplam_kutu"]
        self.summary = [
            ("Toplam fotoğraf", n_all),
            ("Etiketli fotoğraf", n_lab),
            ("Etiketsiz fotoğraf", n_all - n_lab),
            ("Toplam etiket", n_box),
            ("Foto başına etiket", f"{n_box / n_lab:.2f}".replace(".", ",") if n_lab else "–"),
            ("Sınıf", len(project.classes)),
        ]
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (name, value) in enumerate(self.summary):
            card = QFrame()
            card.setProperty("column", True)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 8, 12, 10)
            cl.setSpacing(0)
            cl.addWidget(W.label(name, "small"))
            cl.addWidget(W.label(str(value), "statValue"))
            grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(grid)

        lay.addWidget(W.label("Etiket: kaç kutu çizildi · Fotoğraf: o etiketin geçtiği farklı fotoğraf sayısı "
                              "(bir fotoğrafta 3 mercimek varsa 3 etiket, 1 fotoğraf). "
                              "Yüzde, etiketli fotoğraflara göre.", "small", wrap=True))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.COLS))
        self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.rows = []      # CSV için: (sınıf, özellik, seçenek, etiket, foto)

        bold = QFont()
        bold.setBold(True)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        def item(parent, text, n, photos, strong=False, dot=None):
            pct = f"%{100 * photos / n_lab:.1f}".replace(".", ",") if n_lab else "–"
            per = f"{n / photos:.2f}".replace(".", ",") if photos else "–"
            it = QTreeWidgetItem([text, str(n), str(photos), pct, per])
            for col in range(1, len(self.COLS)):
                it.setTextAlignment(col, right)
            if strong:
                for col in range(len(self.COLS)):
                    it.setFont(col, bold)
            if dot:
                it.setIcon(0, W.dot_icon(dot))
            if n == 0:
                for col in range(len(self.COLS)):
                    it.setForeground(col, theme.qc("dim"))
            (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(it)
            return it

        for cls, info in st["siniflar"].items():
            top = item(self.tree, cls, info["toplam"], info["foto"], strong=True, dot=project.color(cls))
            self.rows.append((cls, "", "", info["toplam"], info["foto"]))
            multi = len(info["attr"]) > 1
            for attr, counts in info["attr"].items():
                parent = top
                if multi:
                    parent = QTreeWidgetItem([attr])
                    parent.setForeground(0, theme.qc("dim"))
                    top.addChild(parent)
                for val, n in counts.items():
                    photos = info["attr_foto"].get(attr, {}).get(val, 0)
                    item(parent, val, n, photos)
                    self.rows.append((cls, attr, val, n, photos))
        self.tree.expandAll()
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        for col in range(1, len(self.COLS)):
            self.tree.header().setSectionResizeMode(col, self.tree.header().ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)

        csv_btn = W.push_button("CSV olarak kaydet", "download", slot=self._save_csv)
        csv_btn.setAutoDefault(False)
        close = W.push_button("Kapat", slot=self.accept, primary=True)
        close.setDefault(True)
        foot.addWidget(csv_btn)
        foot.addStretch()
        foot.addWidget(close)

    def _save_csv(self):
        import csv
        default = str(self.p.export_dir / f"istatistik_{datetime.now():%Y-%m-%d_%H-%M}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "İstatistiği kaydet", default, "CSV (*.csv)")
        if not path:
            return
        n_lab = self.summary[1][1]
        try:
            # utf-8-sig + ';' → Türkçe Excel'de doğrudan düzgün açılır
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                for name, value in self.summary:
                    w.writerow([name, value])
                w.writerow([])
                w.writerow(["Sınıf", "Özellik", "Seçenek", "Etiket", "Fotoğraf", "Fotoğrafların %'si"])
                for cls, attr, val, n, photos in self.rows:
                    pct = f"{100 * photos / n_lab:.1f}".replace(".", ",") if n_lab else ""
                    w.writerow([cls, attr, val, n, photos, pct])
        except OSError as e:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{e}")
            return
        QMessageBox.information(self, "Tamam", f"İstatistik kaydedildi:\n{path}")


# =====================================================================
#  Ayarlar (kısayollar + diğer)
# =====================================================================
def _key_edit(value):
    ed = QKeySequenceEdit(QKeySequence(value or ""))
    ed.setMaximumSequenceLength(1)
    ed.setClearButtonEnabled(True)
    ed.setMinimumWidth(140)
    line = ed.findChild(QLineEdit)
    if line is not None:
        line.setPlaceholderText("Tuşa bas")
        line.setFont(theme.mono_font(12))
    return ed


def _key_text(ed):
    return shortcuts.norm(ed.keySequence().toString(QKeySequence.SequenceFormat.PortableText))


class _AliasLine(QLineEdit):
    """Enter: yazılanı ekle (pencere kapanmasın). Boşken Backspace: son eklenen adı sil."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.owner.commit()
            e.accept()
            return
        if e.key() == Qt.Key.Key_Backspace and not self.text() and self.owner.names:
            self.owner.remove(self.owner.names[-1])
            e.accept()
            return
        super().keyPressEvent(e)


class AliasEdit(QWidget):
    """Birden fazla sesli ad: yaz + Enter → eklenir, ✕ ile silinir. text() virgülle birleştirir."""
    _CHIP = ("QToolButton { border: 1px solid palette(mid); border-radius: 9px; padding: 0 7px;"
             " background: palette(alternate-base); }"
             "QToolButton:hover { border-color: #e53935; color: #e53935; }")

    def __init__(self, value="", name="", parent=None):
        super().__init__(parent)
        self.name = name.replace("_", " ")
        self.names = []
        self._chips = {}
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 1, 0, 1)
        self._lay.setSpacing(3)
        self.edit = _AliasLine(self)
        self.edit.setMinimumWidth(90)
        self.edit.setToolTip("Yazıp Enter'a bas, eklensin. İstediğin kadar ekleyebilirsin.\n"
                             "Silmek için adın üstüne tıkla (ya da boş kutuda Backspace).")
        self._lay.addWidget(self.edit, 1)
        for n in voice._aliases(value):
            self.add(n)
        self._update_placeholder()

    def add(self, name):
        name = " ".join(name.split())
        if not name or name.lower() in (n.lower() for n in self.names):
            return
        b = QToolButton()
        b.setText(f"{name}  ✕")
        b.setToolTip("Silmek için tıkla")
        b.setStyleSheet(self._CHIP)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(lambda _=False, n=name: self.remove(n))
        self._lay.insertWidget(len(self.names), b)
        self.names.append(name)
        self._chips[name] = b
        self._update_placeholder()

    def remove(self, name):
        b = self._chips.pop(name, None)
        if b:
            self.names.remove(name)
            b.deleteLater()
            self._update_placeholder()
            self.edit.setFocus()

    def commit(self):
        """Kutuda yazılı olanı (virgülle birden fazla da olabilir) ekler."""
        for n in voice._aliases(self.edit.text()):
            self.add(n)
        self.edit.clear()

    def _update_placeholder(self):
        self.edit.setPlaceholderText("+ ekle (Enter)" if self.names else f"{self.name}  — yaz, Enter")

    def text(self):
        self.commit()                        # Enter'a basılmadan bırakılan da kaydedilsin
        return ", ".join(self.names)


class SettingsDialog(QDialog):
    TAB_SES = 2

    def __init__(self, project, settings, parent=None, tab=0, refresh_devices=None):
        super().__init__(parent)
        self.p = project
        self.settings = settings
        self._refresh_devices = refresh_devices
        self.setWindowTitle("Ayarlar")
        self.resize(640, 640)
        body, foot = _dialog_layout(self, "Ayarlar")
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        body.addWidget(tabs, 1)
        bold = QFont()
        bold.setBold(True)

        def tab_page(text):
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 10, 0, 0)
            lay.setSpacing(8)
            if text:
                lay.addWidget(W.label(text, "muted", wrap=True))
            return page, lay

        # ---------- sınıf / seçenek kısayolları ----------
        t1, l1 = tab_page(
            "Önce sınıfın, sonra seçeneğin tuşuna basılır (ör. <b>1</b> sonra <b>3</b> = corba › mantar). "
            "Seçenek tuşları farklı sınıflarda tekrar kullanılabilir. Tuşu değiştirmek için kutuya tıklayıp "
            "tuşa bas, silmek için ×.")
        self.tree = QTreeWidget()
        self.tree.setProperty("framed", True)
        self.tree.setHeaderLabels(["Sınıf / seçenek", "Kısayol"])
        self.tree.setColumnWidth(0, 330)
        self.tree.setIndentation(16)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.class_edits = {}     # sinif -> edit
        self.option_edits = {}    # (sinif, attr, deger) -> edit
        for c in project.classes:
            top = QTreeWidgetItem([c["ad"]])
            top.setIcon(0, color_icon(c["renk"]))
            top.setFont(0, bold)
            self.tree.addTopLevelItem(top)
            ed = _key_edit(c.get("kisayol", ""))
            self.tree.setItemWidget(top, 1, ed)
            self.class_edits[c["ad"]] = ed
            for a in c["attributeler"]:
                a_item = QTreeWidgetItem([a["ad"]])
                a_item.setForeground(0, self.palette().placeholderText())
                top.addChild(a_item)
                for v in a["secenekler"]:
                    v_item = QTreeWidgetItem([v])
                    a_item.addChild(v_item)
                    ed = _key_edit(a.get("kisayollar", {}).get(v, ""))
                    self.tree.setItemWidget(v_item, 1, ed)
                    self.option_edits[(c["ad"], a["ad"], v)] = ed
        self.tree.expandAll()
        l1.addWidget(self.tree, 1)
        tabs.addTab(t1, "Sınıf / seçenek")

        # ---------- genel kısayollar ----------
        t2, l2v = tab_page("")
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(12)
        current = shortcuts.load_general(settings)
        self.general_edits = {}
        for row, (k, text, _default) in enumerate(shortcuts.GENERAL):
            grid.addWidget(QLabel(text), row, 0)
            ed = _key_edit(current[k])
            grid.addWidget(ed, row, 1)
            self.general_edits[k] = ed
        grid.setColumnStretch(0, 1)
        l2v.addLayout(grid)
        l2v.addStretch()
        tabs.addTab(t2, "Genel kısayollar")

        # ---------- sesle seçim ----------
        t4, l4 = tab_page(
            "<b>\"Mercimek çorbası\"</b> ya da <b>\"mercimek\"</b> söyleyerek etiket seç; sen sadece kutuyu çizersin.")
        mode_box = QGroupBox("Dinleme modu")
        ml = QVBoxLayout(mode_box)
        ml.setSpacing(2)
        self.mode_buttons = {}
        cur_mode = settings.value("ses/mod", "baskonus")
        for key, text in voice.MODES:
            rb = QRadioButton(text)
            rb.setChecked(key == cur_mode)
            self.mode_buttons[key] = rb
            ml.addWidget(rb)
        l4.addWidget(mode_box)
        l4.addWidget(W.label("Mikrofon", "muted"))
        dev_row = QHBoxLayout()
        dev_row.setSpacing(6)
        self.device_combo = QComboBox()
        dev_row.addWidget(self.device_combo, 1)
        refresh = W.push_button("Yenile", "refresh-cw", slot=self._reload_devices)
        refresh.setToolTip("Sonradan taktığın mikrofon listede yoksa bas")
        refresh.setAutoDefault(False)
        refresh.setVisible(refresh_devices is not None)
        dev_row.addWidget(refresh)
        l4.addLayout(dev_row)
        self._fill_devices(settings.value("ses/cihaz", ""))
        key_grid = QGridLayout()
        key_grid.setVerticalSpacing(6)
        for row, (k, text) in enumerate((("ses_baskonus", "Bas-konuş"), ("ses_ac_kapat", "Mikrofonu aç / kapat"))):
            key_grid.addWidget(QLabel(text), row, 0)
            key_grid.addWidget(self._mirror_key_edit(k), row, 1)
        key_grid.setColumnStretch(0, 1)
        l4.addLayout(key_grid)
        l4.addWidget(W.label(
            "<b>Sesli ad:</b> program bir adı iyi anlamıyorsa ya da kısaca söylemek istersen yaz ve "
            "<b>Enter</b>'a bas; her Enter bir ad ekler (ör. <i>ezo</i>). Silmek için adın üstüne tıkla. "
            "Boş bırakılırsa adın kendisi kullanılır.", "muted", wrap=True))
        self.voice_tree = QTreeWidget()
        self.voice_tree.setProperty("framed", True)
        self.voice_tree.setHeaderLabels(["Sınıf / seçenek", "Sesli ad"])
        self.voice_tree.setColumnWidth(0, 200)
        self.voice_tree.setIndentation(16)
        self.voice_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.class_voice = {}     # sinif -> edit
        self.option_voice = {}    # (sinif, attr, deger) -> edit

        def voice_edit(value, name):
            return AliasEdit(value or "", name)
        for c in project.classes:
            top = QTreeWidgetItem([c["ad"]])
            top.setIcon(0, color_icon(c["renk"]))
            top.setFont(0, bold)
            self.voice_tree.addTopLevelItem(top)
            ed = voice_edit(c.get("sesli_ad"), c["ad"])
            self.voice_tree.setItemWidget(top, 1, ed)
            self.class_voice[c["ad"]] = ed
            for a in c["attributeler"]:
                for v in a["secenekler"]:
                    v_item = QTreeWidgetItem([v])
                    v_item.setToolTip(0, f"{c['ad']} › {a['ad']} › {v}")
                    top.addChild(v_item)
                    ed = voice_edit(a.get("sesli_adlar", {}).get(v), v)
                    self.voice_tree.setItemWidget(v_item, 1, ed)
                    self.option_voice[(c["ad"], a["ad"], v)] = ed
        self.voice_tree.expandAll()
        l4.addWidget(self.voice_tree, 1)
        tabs.addTab(t4, "Sesle seçim")

        # ---------- diğer ----------
        t3, l3 = tab_page("")
        n = project.trash_count()
        l3.addWidget(W.label("Çöp kutusu", "strong"))
        self.trash_label = W.label(f"Çöp kutusunda {n} silinmiş fotoğraf var (geri al ile geri getirilebilirler).",
                                   "muted", wrap=True)
        self.trash_btn = W.push_button("Çöp kutusunu boşalt (kalıcı olarak sil)", "trash-2", slot=self._empty_trash)
        self.trash_btn.setAutoDefault(False)
        self.trash_btn.setEnabled(n > 0)
        row = QHBoxLayout()
        row.addWidget(self.trash_btn)
        row.addStretch()
        l3.addWidget(self.trash_label)
        l3.addLayout(row)
        l3.addStretch()
        tabs.addTab(t3, "Diğer")

        defaults = W.push_button("Varsayılanlar", slot=self._defaults)
        cancel = W.push_button("İptal", slot=self.reject)
        save = W.push_button("Kaydet", slot=self._save, primary=True)
        for b in (defaults, cancel, save):
            b.setAutoDefault(False)
        foot.addWidget(defaults)
        foot.addStretch()
        foot.addWidget(cancel)
        foot.addWidget(save)
        tabs.setCurrentIndex(tab)

    def _defaults(self):
        for i, ed in enumerate(self.class_edits.values()):
            ed.setKeySequence(QKeySequence(str(i + 1) if i < 9 else ""))
        for c in self.p.classes:
            for a in c["attributeler"]:
                for j, v in enumerate(a["secenekler"]):
                    self.option_edits[(c["ad"], a["ad"], v)].setKeySequence(
                        QKeySequence(str(j + 1) if j < 9 else ""))
        for k, _t, default in shortcuts.GENERAL:
            self.general_edits[k].setKeySequence(QKeySequence(default))

    def _mirror_key_edit(self, k):
        """'Genel kısayollar'daki tuş kutusunun bu sekmedeki eşi: biri değişince öbürü de değişir."""
        main = self.general_edits[k]
        twin = _key_edit(_key_text(main))

        def sync(src, dst):
            if dst.keySequence() != src.keySequence():
                dst.setKeySequence(src.keySequence())
        twin.keySequenceChanged.connect(lambda _=None: sync(twin, main))
        main.keySequenceChanged.connect(lambda _=None: sync(main, twin))
        return twin

    def _fill_devices(self, current):
        self.device_combo.clear()
        self.device_combo.addItem("Varsayılan (Windows ayarı)", "")
        names = [n for _i, n in voice.input_devices()]
        for n in names:
            self.device_combo.addItem(n, n)
        if current and current not in names:
            self.device_combo.addItem(f"{current}  (şu an takılı değil)", current)
        self.device_combo.setCurrentIndex(max(0, self.device_combo.findData(current)))

    def _reload_devices(self):
        cur = self.device_combo.currentData() or ""
        if self._refresh_devices:
            self._refresh_devices()
        self._fill_devices(cur)

    @property
    def device_name(self):
        return self.device_combo.currentData() or ""

    def _empty_trash(self):
        if QMessageBox.question(self, "Onay", "Çöp kutusundaki fotoğraflar KALICI olarak silinecek. "
                                              "Bunlar artık geri alınamaz. Emin misiniz?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.p.empty_trash()
        self.trash_label.setText("Çöp kutusu boş.")
        self.trash_btn.setEnabled(False)

    def _clashes(self):
        """Çakışan tuşların açıklamaları; çakışan kutular kırmızı çerçeveyle işaretlenir."""
        clashes = []
        bad = set()

        def check(entries):
            used = {}
            for name, key, ed in entries:
                if not key:
                    continue
                if key in used:
                    clashes.append(f"[{key}]  {used[key][0]}  ve  {name}")
                    bad.update((used[key][1], ed))
                else:
                    used[key] = (name, ed)

        # sınıflar kendi aralarında farklı olmalı
        check([(f"sınıf '{c}'", _key_text(ed), ed) for c, ed in self.class_edits.items()])
        # aynı özelliğin seçenekleri kendi aralarında farklı olmalı
        for c in self.p.classes:
            for a in c["attributeler"]:
                check([(f"'{c['ad']} › {v}'", _key_text(ed), ed)
                       for v in a["secenekler"] for ed in [self.option_edits[(c["ad"], a["ad"], v)]]])
        # genel kısayollar hem birbirinden hem sınıf/seçenek tuşlarından farklı olmalı
        label_keys = {}
        for c, ed in self.class_edits.items():
            label_keys.setdefault(_key_text(ed), (f"sınıf '{c}'", []))[1].append(ed)
        for (c, _a, v), ed in self.option_edits.items():
            label_keys.setdefault(_key_text(ed), (f"'{c} › {v}'", []))[1].append(ed)
        label_keys.pop("", None)
        check([(f"'{t}'", _key_text(self.general_edits[k]), self.general_edits[k]) for k, t, _d in shortcuts.GENERAL])
        for k, t, _d in shortcuts.GENERAL:
            ed = self.general_edits[k]
            key = _key_text(ed)
            if key and key in label_keys:
                clashes.append(f"[{key}]  '{t}'  ve  {label_keys[key][0]}")
                bad.add(ed)
                bad.update(label_keys[key][1])
        for ed in list(self.class_edits.values()) + list(self.option_edits.values()) + list(self.general_edits.values()):
            W.prop(ed, "invalid", ed in bad)
            for child in ed.findChildren(QLineEdit):
                W.prop(child, "invalid", ed in bad)
        return clashes

    def _save(self):
        clashes = self._clashes()
        if clashes:
            QMessageBox.warning(self, "Aynı tuş birden fazla yerde",
                                "Şu kısayollar çakışıyor, lütfen düzeltin:\n\n" + "\n".join(clashes))
            return
        for c in self.p.classes:
            c["kisayol"] = _key_text(self.class_edits[c["ad"]])
            for a in c["attributeler"]:
                a["kisayollar"] = {v: _key_text(self.option_edits[(c["ad"], a["ad"], v)])
                                   for v in a["secenekler"]}
            c["sesli_ad"] = self.class_voice[c["ad"]].text().strip()
            for a in c["attributeler"]:
                a["sesli_adlar"] = {v: t for v in a["secenekler"]
                                    if (t := self.option_voice[(c["ad"], a["ad"], v)].text().strip())}
        self.p.save()
        shortcuts.save_general(self.settings, {k: _key_text(ed) for k, ed in self.general_edits.items()})
        self.settings.setValue("ses/mod", next((k for k, rb in self.mode_buttons.items() if rb.isChecked()), "baskonus"))
        self.accept()


# =====================================================================
#  Aynı fotoğraf zaten var
# =====================================================================
def _thumb(path, size=220):
    from .imageutil import load_image
    img = load_image(path)
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setFixedSize(size, round(size * 0.72))
    lbl.setStyleSheet("background: palette(alternate-base); border: 1px solid palette(mid); border-radius: 6px;")
    if not img.isNull():
        lbl.setPixmap(QPixmap.fromImage(img).scaled(lbl.width() - 6, lbl.height() - 6,
                                                    Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))
    return lbl


class DuplicateDialog(QDialog):
    """Sonuç: self.choice in {"degistir", "atla", "ekle", "iptal"}, self.apply_all: bool"""

    def __init__(self, project, src, kind, existing, remaining, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aynı fotoğraf bulundu")
        self.choice = "iptal"
        self.apply_all = False
        n_boxes = len(project.get_boxes(existing))
        lay, foot = _dialog_layout(self, "Aynı fotoğraf bulundu")

        if kind == "ayni":
            head = f"<b>{src.name}</b> projede zaten var. İçerik de <b>birebir aynı</b> (aynı fotoğraf)."
        elif kind == "isim":
            head = (f"<b>{src.name}</b> adında bir fotoğraf zaten var, "
                    f"ama <b>içerikleri farklı</b> (başka bir fotoğraf).")
        else:
            head = (f"Bu fotoğrafın birebir aynısı projede <b>{existing}</b> adıyla zaten var "
                    f"(eklemek istediğin: {src.name}).")
        if n_boxes:
            head += f"<br>Projedeki fotoğrafta <b>{n_boxes} etiket</b> var."
            if kind != "icerik":
                head += " Değiştirirsen etiketler korunur."
        lay.addWidget(W.label(head, "muted", wrap=True))

        thumbs = QHBoxLayout()
        thumbs.setSpacing(10)
        for title, path, name in (("Projedeki fotoğraf", project.image_path(existing), existing),
                                  ("Eklenen fotoğraf", src, src.name)):
            col = QVBoxLayout()
            col.setSpacing(5)
            col.addWidget(W.label(title, "strong"))
            col.addWidget(_thumb(path))
            cap = W.label(name, "small")
            cap.setToolTip(str(path))
            col.addWidget(cap)
            thumbs.addLayout(col)
        lay.addLayout(thumbs)

        self.all_check = QCheckBox(f"Kalan {remaining} çakışmaya uygula")
        self.all_check.setVisible(remaining > 0)
        lay.addWidget(self.all_check)

        buttons = [
            ("iptal", "Hepsini iptal et", "Kalan dosyaların hiçbirini ekleme"),
            ("degistir", "Değiştir", "Projedeki fotoğrafın üstüne yaz"),
            ("ekle", "Yine de ekle", "Yeni bir isimle ekle (ör. foto_1.jpg)"),
            ("atla", "Atla", "Bu fotoğrafı ekleme"),
        ]
        for key, text, tip in buttons:
            b = W.push_button(text, primary=key == "atla")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._done(k))
            if key == "degistir" and kind == "icerik":
                b.setEnabled(False)
                b.setToolTip("Aynı fotoğraf farklı isimle var, değiştirilecek bir şey yok")
            if key == "atla":
                b.setDefault(True)
            else:
                b.setAutoDefault(False)
            foot.addWidget(b)
            if key == "iptal":
                foot.addStretch()

    def _done(self, key):
        self.choice = key
        self.apply_all = self.all_check.isChecked()
        self.accept()

    def reject(self):
        self.choice = "iptal"
        super().reject()
