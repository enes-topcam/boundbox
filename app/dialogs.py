from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QKeySequenceEdit, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
    QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import shortcuts, voice
from .selection import KeySelector


def color_icon(color):
    pm = QPixmap(14, 14)
    pm.fill(QColor(color))
    return QIcon(pm)


# =====================================================================
#  Sınıf / Attribute / Seçenek ayarları
# =====================================================================
class _Column(QGroupBox):
    """Başlık + liste + 'yaz, Enter' kutusu + butonlar."""

    def __init__(self, title, placeholder, parent=None):
        super().__init__(title, parent)
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.btn_rename = QPushButton("Yeniden adlandır")
        self.btn_delete = QPushButton("Sil")
        row = QHBoxLayout()
        row.addWidget(self.btn_rename)
        row.addWidget(self.btn_delete)
        self.extra = row
        lay.addWidget(self.list)
        lay.addWidget(self.edit)
        lay.addLayout(row)

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
        for w in (self.list, self.edit, self.btn_rename, self.btn_delete):
            w.setEnabled(on)


class SetupDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.p = project
        self.setWindowTitle("Sınıfları Düzenle")
        self.resize(820, 460)

        info = QLabel(
            "1) Sınıf adını yazıp <b>Enter</b>'a basın (ör. <i>corba</i>)   "
            "2) Sınıfı seçip attribute ekleyin (ör. <i>corba_turu</i>)   "
            "3) Attribute'u seçip seçenekleri tek tek yazıp <b>Enter</b>'a basın (ör. <i>mercimek</i>, <i>ezogelin</i>)")
        info.setWordWrap(True)

        self.c_cls = _Column("Sınıflar", "Sınıf adı yaz, Enter")
        self.c_attr = _Column("Attribute'ler", "Attribute adı yaz, Enter")
        self.c_opt = _Column("Seçenekler", "Seçenek yaz, Enter (ör. mercimek)")
        self.btn_color = QPushButton("Renk")
        self.c_cls.extra.insertWidget(0, self.btn_color)

        cols = QHBoxLayout()
        for c in (self.c_cls, self.c_attr, self.c_opt):
            cols.addWidget(c)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        # Enter tuşu dialogu kapatmasın
        for b in close.buttons():
            b.setAutoDefault(False)

        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addLayout(cols)
        lay.addWidget(close)

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
        self.btn_color.setEnabled(bool(names))
        self.refresh_attrs()

    def refresh_attrs(self, keep=None):
        cls = self.p.get_class(self.c_cls.current() or "")
        self.c_attr.set_enabled(cls is not None)
        self.c_attr.setTitle(f"Attribute'ler — {cls['ad']}" if cls else "Attribute'ler")
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
            QMessageBox.warning(self, "Uyarı", "Bu attribute zaten var.")
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
            if self._confirm(f"'{attr}' attribute'u silinsin mi?\n(Kutulardaki bu bilgi de silinir.)"):
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
        self.setWindowTitle("Bu ne?")
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#c77800; font-weight:bold;")
        lay.addWidget(self.hint)
        lay.addWidget(QLabel("<b>Sınıf</b>"))
        self.cls_group = QButtonGroup(self)
        grid = QGridLayout()
        for i, c in enumerate(project.classes):
            key = c.get("kisayol", "")
            rb = QRadioButton(c["ad"] + (f"  [{key}]" if key else ""))
            rb.setIcon(color_icon(c["renk"]))
            self.cls_group.addButton(rb, i)
            grid.addWidget(rb, i // 3, i % 3)
        lay.addLayout(grid)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(line)
        self.attr_holder = QVBoxLayout()
        lay.addLayout(self.attr_holder)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Tamam (Enter)")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal (Esc)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

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
            self.hint.setText(f"{cls} → {self.sel.pending} için tuşa basın:   {self.sel.options_hint()}")
        else:
            self.hint.setText("Tuşla seçebilirsiniz: önce sınıf, sonra seçenek.  Enter: tamam")

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
        for a in self.sel.attr_defs(cls):
            self.attr_lay.addWidget(QLabel(f"<b>{a['ad']}</b>"))
            group = QButtonGroup(self.attr_box)
            grid = QGridLayout()
            keys = a.get("kisayollar", {})
            for j, v in enumerate(a["secenekler"]):
                rb = QRadioButton(v + (f"  [{keys[v]}]" if keys.get(v) else ""))
                rb.clicked.connect(lambda _=False, an=a["ad"], val=v: self._option_clicked(an, val))
                group.addButton(rb, j)
                grid.addWidget(rb, j // 3, j % 3)
            # henüz seçilmediyse son kullanılanı ya da ilkini işaretle
            want = remembered.get(a["ad"])
            group.button(a["secenekler"].index(want) if want in a["secenekler"] else 0).setChecked(True)
            self.attr_lay.addLayout(grid)
            self.attr_groups[a["ad"]] = (group, a["secenekler"])
        if not self.attr_groups:
            self.attr_lay.addWidget(QLabel("<span style='color:gray'>Bu sınıfın attribute'u yok.</span>"))
        self.adjustSize()

    def result_box(self):
        cls = self.p.classes[self.cls_group.checkedId()]["ad"]
        attrs = {name: values[g.checkedId()] for name, (g, values) in self.attr_groups.items()
                 if g.checkedId() >= 0}
        return cls, attrs


# =====================================================================
#  Dışa aktar
# =====================================================================
class ExportDialog(QDialog):
    FORMATS = [
        ("json", "JSON  (kendi formatımız, sınıf + attribute'ler)", True),
        ("jpg", "Etiketli JPG  (kutular resmin üstüne çizilmiş)", True),
        ("cvat", "CVAT XML  (örnek dosyanızdaki format, CVAT'a geri yüklenebilir)", True),
        ("voc", "Pascal VOC XML  (her resim için bir .xml)", False),
        ("yolo", "YOLO  (txt + data.yaml, model eğitmek için)", True),
        ("coco", "COCO JSON  (Detectron, MMDetection vb.)", False),
    ]

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.p = project
        self.setWindowTitle("Dışa Aktar")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)

        fbox = QGroupBox("Hangi formatlar?")
        fl = QVBoxLayout(fbox)
        self.checks = {}
        for key, text, default in self.FORMATS:
            cb = QCheckBox(text)
            cb.setChecked(default)
            fl.addWidget(cb)
            self.checks[key] = cb
        lay.addWidget(fbox)

        self.ybox = QGroupBox("YOLO ayarları")
        yl = QVBoxLayout(self.ybox)
        self.y_cls = QRadioButton("YOLO sınıfı = sadece sınıf  (corba)")
        self.y_attr = QRadioButton("YOLO sınıfı = sınıf + seçenek  (corba_mercimek, corba_ezogelin ...)")
        self.y_attr.setChecked(True)
        yl.addWidget(self.y_cls)
        yl.addWidget(self.y_attr)
        vrow = QHBoxLayout()
        self.val_check = QCheckBox("Train / Val olarak ayır, val oranı %")
        self.val_check.setChecked(True)
        self.val_spin = QSpinBox()
        self.val_spin.setRange(5, 50)
        self.val_spin.setValue(20)
        vrow.addWidget(self.val_check)
        vrow.addWidget(self.val_spin)
        vrow.addStretch()
        yl.addLayout(vrow)
        lay.addWidget(self.ybox)
        self.checks["yolo"].toggled.connect(self.ybox.setEnabled)

        gbox = QGroupBox("Genel")
        gl = QVBoxLayout(gbox)
        self.only_labeled = QCheckBox("Sadece etiketlenmiş resimleri aktar")
        self.only_labeled.setChecked(True)
        self.copy_images = QCheckBox("Orijinal resimleri de kopyala (YOLO / VOC / COCO klasörlerine)")
        self.copy_images.setChecked(True)
        gl.addWidget(self.only_labeled)
        gl.addWidget(self.copy_images)
        orow = QHBoxLayout()
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        self.out_edit = QLineEdit(str(project.export_dir / stamp))
        browse = QPushButton("Seç...")
        browse.clicked.connect(self._browse)
        orow.addWidget(QLabel("Klasör:"))
        orow.addWidget(self.out_edit)
        orow.addWidget(browse)
        gl.addLayout(orow)
        lay.addWidget(gbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Dışa Aktar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Dışa aktarma klasörü", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _ok(self):
        if not self.formats():
            QMessageBox.warning(self, "Uyarı", "En az bir format seçin.")
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
        }


# =====================================================================
#  Ayarlar (kısayollar + diğer)
# =====================================================================
def _key_edit(value):
    ed = QKeySequenceEdit(QKeySequence(value or ""))
    ed.setMaximumSequenceLength(1)
    ed.setClearButtonEnabled(True)
    ed.setMinimumWidth(140)
    return ed


def _key_text(ed):
    return shortcuts.norm(ed.keySequence().toString(QKeySequence.SequenceFormat.PortableText))


class SettingsDialog(QDialog):
    TAB_SES = 2

    def __init__(self, project, settings, parent=None, tab=0):
        super().__init__(parent)
        self.p = project
        self.settings = settings
        self.setWindowTitle("Ayarlar")
        self.resize(580, 600)
        tabs = QTabWidget()

        # ---------- sınıf / seçenek kısayolları ----------
        t1 = QWidget()
        l1 = QVBoxLayout(t1)
        info = QLabel(
            "Kutuya tıklayıp tuşa basarak kısayol atayın (silmek için ✕).<br><br>"
            "<b>Nasıl çalışır:</b> önce <b>sınıf</b> tuşuna, sonra <b>seçenek</b> tuşuna basılır.<br>"
            "Ör. <b>1</b> sonra <b>3</b> = corba → mantar. Hepsi seçilince kutular "
            "<b>menü açılmadan</b> direkt bu şekilde etiketlenir.<br>"
            "Seçenek tuşları sadece kendi sınıfı seçiliyken çalışır, bu yüzden her sınıfta 1, 2, 3 "
            "kullanılabilir. Seçimi sıfırlama tuşu 'Genel kısayollar' sekmesinde.")
        info.setWordWrap(True)
        l1.addWidget(info)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Sınıf / Seçenek", "Kısayol"])
        self.tree.setColumnWidth(0, 300)
        self.class_edits = {}     # sinif -> edit
        self.option_edits = {}    # (sinif, attr, deger) -> edit
        bold = QFont()
        bold.setBold(True)
        for c in project.classes:
            top = QTreeWidgetItem([c["ad"]])
            top.setIcon(0, color_icon(c["renk"]))
            top.setFont(0, bold)
            self.tree.addTopLevelItem(top)
            ed = _key_edit(c.get("kisayol", ""))
            self.tree.setItemWidget(top, 1, ed)
            self.class_edits[c["ad"]] = ed
            for a in c["attributeler"]:
                a_item = QTreeWidgetItem([a["ad"] + "   (sınıftan sonra basılır)"])
                top.addChild(a_item)
                for v in a["secenekler"]:
                    v_item = QTreeWidgetItem([v])
                    a_item.addChild(v_item)
                    ed = _key_edit(a.get("kisayollar", {}).get(v, ""))
                    self.tree.setItemWidget(v_item, 1, ed)
                    self.option_edits[(c["ad"], a["ad"], v)] = ed
        self.tree.expandAll()
        l1.addWidget(self.tree)
        tabs.addTab(t1, "Sınıf / seçenek kısayolları")

        # ---------- genel kısayollar ----------
        t2 = QWidget()
        l2 = QGridLayout(t2)
        current = shortcuts.load_general(settings)
        self.general_edits = {}
        for row, (k, text, _default) in enumerate(shortcuts.GENERAL):
            l2.addWidget(QLabel(text), row, 0)
            ed = _key_edit(current[k])
            l2.addWidget(ed, row, 1)
            self.general_edits[k] = ed
        l2.setRowStretch(len(shortcuts.GENERAL), 1)
        tabs.addTab(t2, "Genel kısayollar")

        # ---------- sesle seçim ----------
        t4 = QWidget()
        l4 = QVBoxLayout(t4)
        keys = shortcuts.load_general(settings)
        info = QLabel(
            "Seçmek istediğini söyle, ör. <b>\"mercimek çorbası\"</b> → corba → mercimek seçilir, "
            "sen sadece kutuyu çizersin. Sadece seçeneği söylemek de yeter (<b>\"mercimek\"</b>).<br><br>"
            f"Mikrofonu aç / kapat: <b>{keys['ses_ac_kapat'] or '—'}</b> ya da üstteki 🎤 simgesine tıkla. "
            f"Bas-konuş tuşu: <b>{keys['ses_baskonus'] or '—'}</b>. Tuşları 'Genel kısayollar' sekmesinden "
            "değiştirebilirsin.<br><br>"
            "<b>Sesli ad:</b> program bir adı iyi anlamıyorsa ya da kısaca söylemek istersen buraya yaz. "
            "Birden fazlası virgülle ayrılır (ör. <i>ezo, ezogelin</i>). Boş bırakılırsa adın kendisi kullanılır.")
        info.setWordWrap(True)
        l4.addWidget(info)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Dinleme şekli:"))
        self.mode_buttons = {}
        cur_mode = settings.value("ses/mod", "baskonus")
        for key, text in voice.MODES:
            rb = QRadioButton(text)
            rb.setChecked(key == cur_mode)
            self.mode_buttons[key] = rb
            mode_row.addWidget(rb)
        mode_row.addStretch()
        l4.addLayout(mode_row)
        self.voice_tree = QTreeWidget()
        self.voice_tree.setHeaderLabels(["Sınıf / Seçenek", "Sesli ad"])
        self.voice_tree.setColumnWidth(0, 240)
        self.class_voice = {}     # sinif -> edit
        self.option_voice = {}    # (sinif, attr, deger) -> edit

        def voice_edit(value, name):
            ed = QLineEdit(value or "")
            ed.setPlaceholderText(name.replace("_", " "))
            return ed
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
                    v_item = QTreeWidgetItem([f"{v}   ({a['ad']})"])
                    top.addChild(v_item)
                    ed = voice_edit(a.get("sesli_adlar", {}).get(v), v)
                    self.voice_tree.setItemWidget(v_item, 1, ed)
                    self.option_voice[(c["ad"], a["ad"], v)] = ed
        self.voice_tree.expandAll()
        l4.addWidget(self.voice_tree)
        tabs.addTab(t4, "Sesle seçim")

        # ---------- diğer ----------
        t3 = QWidget()
        l3 = QVBoxLayout(t3)
        n = project.trash_count()
        self.trash_label = QLabel(f"Çöp kutusunda {n} silinmiş fotoğraf var (geri al ile geri getirilebilirler).")
        self.trash_btn = QPushButton("Çöp kutusunu boşalt (kalıcı olarak sil)")
        self.trash_btn.setEnabled(n > 0)
        self.trash_btn.clicked.connect(self._empty_trash)
        l3.addWidget(self.trash_label)
        l3.addWidget(self.trash_btn)
        l3.addStretch()
        tabs.addTab(t3, "Diğer")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText("Varsayılanlar")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        for b in buttons.buttons():
            b.setAutoDefault(False)

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)
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

    def _empty_trash(self):
        if QMessageBox.question(self, "Onay", "Çöp kutusundaki fotoğraflar KALICI olarak silinecek. "
                                              "Bunlar artık geri alınamaz. Emin misiniz?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.p.empty_trash()
        self.trash_label.setText("Çöp kutusu boş.")
        self.trash_btn.setEnabled(False)

    def _clashes(self):
        clashes = []

        def check(entries):
            used = {}
            for name, key in entries:
                if not key:
                    continue
                if key in used:
                    clashes.append(f"[{key}]  {used[key]}  ve  {name}")
                else:
                    used[key] = name

        # sınıflar kendi aralarında farklı olmalı
        check([(f"sınıf '{c}'", _key_text(ed)) for c, ed in self.class_edits.items()])
        # aynı attribute'un seçenekleri kendi aralarında farklı olmalı
        for c in self.p.classes:
            for a in c["attributeler"]:
                check([(f"'{c['ad']} → {v}'", _key_text(self.option_edits[(c["ad"], a["ad"], v)]))
                       for v in a["secenekler"]])
        # genel kısayollar hem birbirinden hem sınıf/seçenek tuşlarından farklı olmalı
        label_keys = {}
        for c, ed in self.class_edits.items():
            label_keys.setdefault(_key_text(ed), f"sınıf '{c}'")
        for (c, _a, v), ed in self.option_edits.items():
            label_keys.setdefault(_key_text(ed), f"'{c} → {v}'")
        label_keys.pop("", None)
        check([(f"'{t}'", _key_text(self.general_edits[k])) for k, t, _d in shortcuts.GENERAL])
        for k, t, _d in shortcuts.GENERAL:
            key = _key_text(self.general_edits[k])
            if key and key in label_keys:
                clashes.append(f"[{key}]  '{t}'  ve  {label_keys[key]}")
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
def _thumb(path, size=180):
    from .imageutil import load_image
    img = load_image(path)
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet("border:1px solid #666;")
    if not img.isNull():
        lbl.setPixmap(QPixmap.fromImage(img).scaled(size - 4, size - 4, Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))
    return lbl


class DuplicateDialog(QDialog):
    """Sonuç: self.choice in {"degistir", "atla", "ekle", "iptal"}, self.apply_all: bool"""

    def __init__(self, project, src, kind, existing, remaining, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bu fotoğraf zaten var")
        self.choice = "iptal"
        self.apply_all = False
        n_boxes = len(project.get_boxes(existing))

        if kind == "ayni":
            head = f"<b>{src.name}</b> projede zaten var.<br>İçerik de <b>birebir aynı</b> (aynı fotoğraf)."
        elif kind == "isim":
            head = (f"<b>{src.name}</b> adında bir fotoğraf zaten var,<br>"
                    f"ama <b>içerikleri farklı</b> (başka bir fotoğraf).")
        else:
            head = (f"Bu fotoğrafın birebir aynısı projede <b>{existing}</b> adıyla zaten var.<br>"
                    f"<span style='color:gray'>(eklemek istediğiniz: {src.name})</span>")
        if n_boxes:
            head += f"<br><br>Projedeki fotoğrafta <b>{n_boxes} etiket</b> var."
            if kind != "icerik":
                head += " Değiştirirseniz etiketler korunur."

        lay = QVBoxLayout(self)
        text = QLabel(head)
        text.setWordWrap(True)
        lay.addWidget(text)

        thumbs = QHBoxLayout()
        for title, path in (("Projedeki", project.image_path(existing)), ("Eklenmek istenen", src)):
            col = QVBoxLayout()
            col.addWidget(QLabel(f"<b>{title}</b>"), alignment=Qt.AlignmentFlag.AlignCenter)
            col.addWidget(_thumb(path))
            thumbs.addLayout(col)
        lay.addLayout(thumbs)

        self.all_check = QCheckBox(f"Kalan {remaining} çakışma için de aynısını yap")
        self.all_check.setVisible(remaining > 0)
        lay.addWidget(self.all_check)

        row = QHBoxLayout()
        buttons = [
            ("degistir", "Değiştir", "Projedeki fotoğrafın üstüne yaz"),
            ("atla", "Atla", "Bu fotoğrafı ekleme"),
            ("ekle", "Yine de ekle", "Yeni bir isimle ekle (ör. foto_1.jpg)"),
            ("iptal", "Hepsini iptal et", "Kalan dosyaların hiçbirini ekleme"),
        ]
        for key, label, tip in buttons:
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._done(k))
            if key == "degistir" and kind == "icerik":
                b.setEnabled(False)
                b.setToolTip("Aynı fotoğraf farklı isimle var, değiştirilecek bir şey yok")
            if key == "atla":
                b.setDefault(True)
            row.addWidget(b)
        lay.addLayout(row)

    def _done(self, key):
        self.choice = key
        self.apply_all = self.all_check.isChecked()
        self.accept()

    def reject(self):
        self.choice = "iptal"
        super().reject()
