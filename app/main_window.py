import copy
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QComboBox, QFileDialog, QHBoxLayout,
    QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressDialog, QPushButton, QSizePolicy, QSplitter, QTextEdit, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import shortcuts, theme, voice
from .canvas import Canvas
from .dialogs import DuplicateDialog, ExportDialog, LabelDialog, SettingsDialog, SetupDialog, color_icon
from .exporters import Exporter
from .image_list import ImageList
from .imageutil import box_caption, load_image
from .importers import merge_labels, read_cvat
from .project import IMAGE_EXTS, DuplicateFinder, Project
from .selection import KeySelector

GREEN = "#2e7d32"
ROLE_KEY = Qt.ItemDataRole.UserRole + 1     # istatistik satırının altında fotoğraf listesi var: (sinif, attr, secenek)
ROLE_PHOTO = Qt.ItemDataRole.UserRole + 2   # istatistikte fotoğraf satırı: resim adı
UNSET = "(seçilmemiş)"


def _as_int(v):
    """Qt enum / bayrak -> int (PySide6 sürümleri arasında farklı tipler dönebiliyor)."""
    return v.value if hasattr(v, "value") else int(v)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Etiketleme")
        self.resize(1400, 850)
        self.setAcceptDrops(True)
        self.settings = QSettings("etiketleme", "etiketleme")
        self.project = None
        self.images = []
        self.current = None          # aktif resim adı
        self.current_image = None    # QImage
        self.boxes = []              # aktif resmin kutuları
        self.undo_stack = []         # [{"tip": "kutu"|"resim_sil", ...}]
        self.memory = {"attr": {}}   # menüde son seçilenler: {"sinif", "attr": {sinif: {attr: deger}}}
        self.sel = None              # tuşla seçim (KeySelector)
        self.key_objects = []        # oluşturulan QShortcut'lar
        self.browse = None           # etikete göre gezinme: (sinif, attr, secenek) — A/D sadece onlarda gezer
        self.stats_open = set()      # istatistikte fotoğraf listesi açık olan satırlar

        # ---------- sesle seçim ----------
        self.voice_missing = voice.missing_packages()
        self.voice = None if self.voice_missing else voice.VoiceEngine()
        self.voice_matcher = None
        self.voice_state = "kapali"
        self.voice_speaking = False
        self.voice_mode = self.settings.value("ses/mod", "baskonus")
        self.ptt_key = ""
        self.ptt_held = False
        self.downloader = None
        self.dl_dialog = None
        self.last_heard = ""         # sesle seçimde en son duyulan (öğretmek için)
        if self.voice:
            self.voice.stateChanged.connect(self._on_voice_state)
            self.voice.error.connect(self._on_voice_error)
            self.voice.speaking.connect(self._on_voice_speaking)
            self.voice.partial.connect(self._on_voice_partial)
            self.voice.heard.connect(self._on_voice_heard)
            QApplication.instance().installEventFilter(self)

        self._build_ui()
        self._build_toolbar()
        self.apply_shortcuts()

        last = self.settings.value("last_project", "")
        if last and Project.is_project(last):
            self.open_project(last)
        else:
            self._update_enabled()
        if self.voice and self.settings.value("ses/acik", False, type=bool):
            self._voice_start(ask=False)

    # =================================================================
    #  Arayüz
    # =================================================================
    def _build_ui(self):
        # ---------- sol: resim listesi ----------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)
        self.filter = QComboBox()
        self.filter.addItems(["Tüm fotoğraflar", "Etiketlenmemiş", "Etiketlenmiş"])
        self.filter.currentIndexChanged.connect(lambda _: self.refresh_image_list())
        self.image_list = ImageList()
        self.image_list.emptyClicked.connect(self.on_empty_list_click)
        self.image_list.filesDropped.connect(self.handle_drop)
        self.image_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.image_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.image_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.image_list.customContextMenuRequested.connect(self.on_image_menu)
        self.image_list.currentItemChanged.connect(self._on_image_selected)
        # en son soldaki listeye tıklandıysa Del fotoğrafı siler, yoksa kutuyu
        self.list_active = False
        self.image_list.itemPressed.connect(self._on_list_pressed)
        self.progress_label = QLabel()
        ll.addWidget(QLabel("<b>Fotoğraflar</b>  <span style='color:gray'>(sağ tık: sil)</span>"))
        ll.addWidget(self.filter)
        ll.addWidget(self.image_list)
        ll.addWidget(self.progress_label)

        # ---------- orta: üst bar + canvas + alt bar ----------
        self.canvas = Canvas(lambda c: self.project.color(c) if self.project else "#fff")
        self.canvas.boxDrawn.connect(self.on_box_drawn)
        self.canvas.boxRightClicked.connect(self.on_box_menu)
        self.canvas.pressed.connect(lambda: setattr(self, "list_active", False))
        self.canvas.hint.connect(lambda t: self.hint_label.setText(t))
        self.canvas.zoomChanged.connect(lambda z: self.zoom_label.setText(f"Zoom: %{z}" if z else ""))

        top = QHBoxLayout()
        self.btn_prev = self._tool_button("◀ Önceki", "Önceki fotoğraf", lambda: self.step(-1))
        self.btn_next = self._tool_button("Sonraki ▶", "Sonraki fotoğraf", lambda: self.step(1))
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight:bold; padding:0 6px;")
        self.zoom_label = QLabel()
        self.zoom_label.setStyleSheet("color:gray; padding-right:6px;")
        self.btn_fit = self._tool_button("⛶ Sığdır", "Fotoğrafı ekrana sığdır", self.canvas.fit)
        self.btn_del_img = self._tool_button("🗑 Fotoğrafı Sil", "Bu fotoğrafı sil", self.delete_images)
        self.btn_browse = self._tool_button("", "Etikete göre gezinmeyi bitir (tüm fotoğraflarda gezin)",
                                            self.end_browse)
        self.btn_browse.setStyleSheet("QToolButton{background:#1565c0; color:white; font-weight:bold;"
                                      " border-radius:4px; padding:2px 8px;}")
        self.btn_browse.hide()
        top.addWidget(self.btn_prev)
        top.addWidget(self.title_label)
        top.addWidget(self.btn_next)
        top.addWidget(self.btn_browse)
        top.addStretch()
        top.addWidget(self.zoom_label)
        top.addWidget(self.btn_fit)
        top.addWidget(self.btn_del_img)

        bottom = QHBoxLayout()
        self.active_label = QLabel()
        self.active_label.setStyleSheet("font-weight:bold;")
        self.hint_label = QLabel()
        self.hint_label.setStyleSheet("color:#c77800; font-weight:bold;")
        bottom.addWidget(self.active_label)
        bottom.addStretch()
        bottom.addWidget(self.hint_label)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 4, 0, 4)
        cl.addLayout(top)
        cl.addWidget(self.canvas, 1)
        cl.addLayout(bottom)

        # ---------- sağ: kutular + istatistik ----------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        rl.addWidget(QLabel("<b>Bu fotoğraftaki kutular</b>"))
        self.box_list = QListWidget()
        self.box_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.box_list.currentRowChanged.connect(self.canvas.set_selected)
        self.box_list.itemPressed.connect(lambda _: setattr(self, "list_active", False))
        self.box_list.itemDoubleClicked.connect(lambda _: self.edit_box(self.box_list.currentRow()))
        brow = QHBoxLayout()
        b_edit = QPushButton("Düzenle")
        b_del = QPushButton("Kutuyu Sil")
        b_edit.clicked.connect(lambda: self.edit_box(self.box_list.currentRow()))
        b_del.clicked.connect(lambda: self.delete_box(self.box_list.currentRow()))
        brow.addWidget(b_edit)
        brow.addWidget(b_del)
        rl.addWidget(self.box_list, 1)
        rl.addLayout(brow)

        rl.addWidget(QLabel("<b>İstatistik</b>  <span style='color:gray'>(tıkla = aktif yap)</span>"))
        self.stats_summary = QLabel()
        self.stats_tree = QTreeWidget()
        self.stats_tree.setHeaderLabels(["", "Adet"])
        self.stats_tree.setColumnWidth(0, 230)
        self.stats_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stats_tree.itemClicked.connect(self._on_stats_clicked)
        self.stats_tree.itemExpanded.connect(self._on_stats_expanded)
        self.stats_tree.itemCollapsed.connect(self._on_stats_collapsed)
        rl.addWidget(self.stats_summary)
        rl.addWidget(self.stats_tree, 2)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(right)
        split.setSizes([230, 880, 320])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

    def _tool_button(self, text, tip, slot):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setAutoRaise(False)
        b.clicked.connect(slot)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    def _build_toolbar(self):
        tb = self.addToolBar("Araçlar")
        tb.setMovable(False)

        def act(text, slot):
            a = QAction(text, self)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        act("📁 Proje Klasörü Aç / Oluştur", self.choose_project)
        tb.addSeparator()
        self.a_setup = act("🏷 Sınıfları Düzenle", self.open_setup)
        self.a_add = act("➕ Fotoğraf Ekle", self.add_images)
        self.a_add_dir = act("➕ Klasörden Ekle", self.add_image_folder)
        self.a_refresh = act("🔄 Yenile", self.reload_project)
        tb.addSeparator()
        self.a_import = act("📥 CVAT XML İçe Aktar", self.import_cvat)
        self.a_export = act("📤 Dışa Aktar", self.export)
        self.a_open_dir = act("📂 Klasörü Göster", self.show_folder)
        tb.addSeparator()
        self.a_settings = act("⚙ Ayarlar", lambda: self.open_settings())

        # ---------- sağ üst: mikrofon + tema seçimi ----------
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.mic_btn = QToolButton()
        self.mic_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.mic_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mic_btn.clicked.connect(self.toggle_voice)
        mic_menu = QMenu(self.mic_btn)
        mic_menu.aboutToShow.connect(lambda: self._fill_mic_menu(mic_menu))
        self.mic_btn.setMenu(mic_menu)
        tb.addWidget(self.mic_btn)
        gap = QWidget()
        gap.setFixedWidth(6)
        tb.addWidget(gap)
        current = self.settings.value("tema", "sistem")
        self.theme_btn = QToolButton()
        self.theme_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.theme_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.theme_btn.setStyleSheet("QToolButton { font-size: 15px; padding: 0 6px; }"
                                     "QToolButton::menu-indicator { image: none; width: 0; }")
        menu = QMenu(self.theme_btn)
        group = QActionGroup(self)
        for key, icon, name in theme.MODES:
            a = menu.addAction(f"{icon}  {name}")
            a.setCheckable(True)
            a.setChecked(key == current)
            a.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            group.addAction(a)
        self.theme_btn.setMenu(menu)
        tb.addWidget(self.theme_btn)
        self._show_theme(current)

    def _show_theme(self, key):
        _, icon, name = next((m for m in theme.MODES if m[0] == key), theme.MODES[0])
        self.theme_btn.setText(icon)
        self.theme_btn.setToolTip(f"Tema: {name}  (değiştirmek için tıklayın)")

    def set_theme(self, key):
        theme.apply(key)
        self.settings.setValue("tema", key)
        self._show_theme(key)

    def _update_enabled(self):
        on = self.project is not None
        for w in (self.a_setup, self.a_add, self.a_add_dir, self.a_refresh, self.a_import,
                  self.a_export, self.a_open_dir, self.a_settings, self.btn_fit, self.btn_del_img,
                  self.btn_prev, self.btn_next, self.mic_btn):
            w.setEnabled(on)
        if not on:
            self.title_label.setText("Başlamak için üstten 'Proje Klasörü Aç / Oluştur'a tıklayın.")
            self.image_list.placeholder = "📁\n\nÖnce proje klasörü açın\n\n(buraya tıklayın)"
            self.image_list.viewport().update()

    # =================================================================
    #  Kısayollar
    # =================================================================
    def apply_shortcuts(self):
        """Genel + sınıf/seçenek kısayollarını (yeniden) oluşturur."""
        for s in self.key_objects:
            s.setEnabled(False)
            s.deleteLater()
        self.key_objects = []

        def bind(key, fn):
            if key:
                s = QShortcut(QKeySequence(key), self)
                s.activated.connect(fn)
                self.key_objects.append(s)

        g = shortcuts.load_general(self.settings)
        actions = {
            "onceki": lambda: self.step(-1), "sonraki": lambda: self.step(1),
            "sigdir": self.canvas.fit, "foto_sil": self.delete_images,
            "kutu_sil": self.delete_selected_box, "geri_al": self.undo,
            "iptal": self.canvas.cancel, "sifirla": self.clear_selection,
            "disa_aktar": self.export, "yenile": self.reload_project,
            "ses_ac_kapat": self.toggle_voice,
        }
        for k, fn in actions.items():
            bind(g[k], lambda fn=fn: self.project and fn())
        used = set(g.values())
        # ok tuşları da gezinsin (başka işe atanmadıysa)
        for key, d in (("Left", -1), ("Right", 1)):
            if key not in used:
                bind(key, lambda d=d: self.project and self.step(d))

        # sınıf / seçenek tuşları: aynı tuş (ör. 1) duruma göre sınıf ya da seçenek seçer
        if self.sel:
            for key in self.sel.all_keys() - used:
                bind(key, lambda k=key: self.on_label_key(k))

        tips = {"onceki": self.btn_prev, "sonraki": self.btn_next, "sigdir": self.btn_fit,
                "foto_sil": self.btn_del_img}
        for k, btn in tips.items():
            base = btn.toolTip().split("  (")[0]
            btn.setToolTip(base + (f"  ({g[k]})" if g[k] else ""))
        self.statusBar().showMessage(
            f"Sol üst köşeye tıkla → sağ alt köşeye tıkla → seç.  Tekerlek: zoom.  "
            f"Sağ tık basılı sürükle: gezin.  {g['geri_al']}: geri al.  {g['sigdir']}: sığdır.")

        # sesle seçim: bas-konuş tuşu QShortcut değil (basılı tutma / bırakma gerekiyor), eventFilter'da
        self.ptt_key = g["ses_baskonus"]
        self.voice_matcher = voice.VoiceMatcher(self.project) if self.project else None
        if self.voice:
            self.voice.set_phrases(self.voice_matcher.phrases() if self.voice_matcher else [])
        self._voice_update_button()

    # =================================================================
    #  Tuşla seçim (1 → corba, sonra 3 → mantar)
    # =================================================================
    def on_label_key(self, key):
        if self.project and self.sel.press(key):
            self._selection_changed()

    def clear_selection(self):
        self.sel.reset()
        self._selection_changed()
        self.statusBar().showMessage("Seçim sıfırlandı — kutu çizince menü açılacak.", 3000)

    def set_active(self, cls, attr=None, value=None):
        """İstatistik listesine tıklayınca seçim."""
        if attr:
            attrs = dict(self.sel.attrs) if self.sel.cls == cls else {}
            attrs[attr] = value
            self.sel.set_class(cls, attrs)
        else:
            self.sel.set_class(cls)
        self._selection_changed()

    def _selection_changed(self):
        self._update_active_label()
        self.refresh_stats()

    def _update_active_label(self):
        sel = self.sel
        reset_key = shortcuts.load_general(self.settings)["sifirla"]
        reset = f"   ({reset_key}: sıfırla)" if reset_key else ""
        if not self.project or not sel or not sel.cls:
            self.active_label.setStyleSheet("color:gray;")
            self.active_label.setText("Seçim yok — kutu çizince menü açılır.   (sınıf tuşuna basarak seçebilirsiniz)")
            return
        color = self.project.color(sel.cls)
        chosen = " → ".join([sel.cls] + list(sel.attrs.values()))
        if sel.complete():
            self.active_label.setStyleSheet(
                "background:#1b5e20; color:white; font-weight:bold; padding:3px 8px; border-radius:4px;")
            self.active_label.setText(f"<span style='color:{color}'>■</span> {chosen}   ✔ HAZIR — kutular "
                                      f"menü açılmadan böyle etiketlenecek{reset}")
        else:
            self.active_label.setStyleSheet(
                "background:#5d4300; color:white; font-weight:bold; padding:3px 8px; border-radius:4px;")
            self.active_label.setText(f"<span style='color:{color}'>■</span> {chosen} → <u>{sel.pending}</u>?   "
                                      f"{sel.options_hint()}{reset}")

    def open_settings(self, tab=0):
        if SettingsDialog(self.project, self.settings, self, tab=tab).exec():
            self.apply_shortcuts()
            self.sel.validate()
            self._selection_changed()
            self.set_voice_mode(self.settings.value("ses/mod", "baskonus"))

    # =================================================================
    #  Sesle seçim ("mercimek çorbası" → corba → mercimek)
    # =================================================================
    _MIC_STYLE = ("QToolButton {{ font-size: 14px; font-weight: bold; padding: 2px 6px; border-radius: 4px;"
                  " border: 1px solid {border}; background: {bg}; {color} }}"
                  "QToolButton::menu-button {{ border: none; width: 16px; }}")

    def _voice_update_button(self):
        if not hasattr(self, "mic_btn"):
            return
        mute_key = shortcuts.load_general(self.settings)["ses_ac_kapat"]
        mute = f" ({mute_key})" if mute_key else ""
        on = bool(self.voice and self.voice.running)
        if not self.voice:
            look = ("🎤", "#808080", "transparent", "color: gray;")
            tip = "Sesle seçim için kütüphane eksik:\npip install " + " ".join(self.voice_missing)
        elif not on:
            look = ("🔇 Kapalı", "#c62828", "rgba(198,40,40,0.18)", "color: #e53935;")
            tip = f"Mikrofon kapalı. Açmak için tıkla{mute}.\nOk: dinleme şekli, mikrofon seçimi"
        elif self.voice_state == "yukleniyor":
            look = ("⏳ Hazırlanıyor", "#c77800", "rgba(199,120,0,0.18)", "")
            tip = "Ses modeli yükleniyor…"
        elif self.ptt_held or (self.voice_mode == "surekli" and self.voice_speaking):
            look = ("🎤 Dinliyor", "#1b5e20", "#2e7d32", "color: white;")
            tip = "Konuşuyorsun — söylediğin sınıf / seçenek seçilecek"
        elif self.voice_mode == "surekli":
            look = ("🎤 Sürekli", "#2e7d32", "rgba(46,125,50,0.18)", "")
            tip = f"Sürekli dinliyor. Sınıfı / seçeneği söylemen yeter.\nKapatmak (sessize almak) için tıkla{mute}."
        else:
            k = self.ptt_key or "tuş atanmamış"
            look = (f"🎤 Bas-konuş ({k})", "#808080", "transparent", "")
            tip = (f"{k} tuşunu basılı tutarken söyle, bırakınca seçilir.\n"
                   f"Kapatmak (sessize almak) için tıkla{mute}.")
        text, border, bg, color = look
        self.mic_btn.setText(text)
        self.mic_btn.setToolTip(tip)
        self.mic_btn.setStyleSheet(self._MIC_STYLE.format(border=border, bg=bg, color=color))

    def _fill_mic_menu(self, menu):
        menu.clear()
        if not self.voice:
            menu.addAction("Kütüphane eksik: pip install " + " ".join(self.voice_missing)).setEnabled(False)
            return
        mute_key = shortcuts.load_general(self.settings)["ses_ac_kapat"]
        a = menu.addAction(("🔇 Mikrofonu kapat" if self.voice.running else "🎤 Mikrofonu aç")
                           + (f"\t{mute_key}" if mute_key else ""))
        a.triggered.connect(self.toggle_voice)
        menu.addSeparator()
        group = QActionGroup(menu)
        for key, text in voice.MODES:
            if key == "baskonus" and self.ptt_key:
                text += f"  [{self.ptt_key}]"
            a = menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(key == self.voice_mode)
            a.triggered.connect(lambda _=False, k=key: self.set_voice_mode(k))
            group.addAction(a)
        menu.addSeparator()
        dev_menu = menu.addMenu("Mikrofon seç")
        dev_group = QActionGroup(dev_menu)
        current = self.settings.value("ses/cihaz", "")
        for _idx, name in [(None, "")] + voice.input_devices():
            a = dev_menu.addAction(name or "Varsayılan (Windows ayarı)")
            a.setCheckable(True)
            a.setChecked(name == current)
            a.triggered.connect(lambda _=False, n=name: self.set_voice_device(n))
            dev_group.addAction(a)
        menu.addSeparator()
        a = menu.addAction(f"Son duyulanı öğret: “{self.last_heard}”…" if self.last_heard
                           else "Son duyulanı öğret… (henüz bir şey duyulmadı)")
        a.setEnabled(bool(self.last_heard and self.project))
        a.triggered.connect(self.teach_last_heard)
        menu.addAction("Sesli adlar ve tuşlar…").triggered.connect(
            lambda: self.project and self.open_settings(SettingsDialog.TAB_SES))

    def teach_last_heard(self):
        """Program bir adı yanlış duyuyorsa: duyduğunu o sınıfa / seçeneğe sesli ad olarak ekle."""
        heard = self.last_heard
        if not heard or not self.project:
            return
        targets = []          # (görünen ad, sınıf, attr, değer)
        for c in self.project.classes:
            targets.append((c["ad"], c["ad"], None, None))
            for a in c["attributeler"]:
                for v in a["secenekler"]:
                    targets.append((f"{c['ad']} → {v}", c["ad"], a["ad"], v))
        labels = [t[0] for t in targets]
        cur = f"{self.sel.cls} → {next(iter(self.sel.attrs.values()))}" if self.sel and self.sel.attrs else ""
        label, ok = QInputDialog.getItem(
            self, "Son duyulanı öğret",
            f"Program son olarak “{heard}” duydu.\nBunu söylediğinde hangisi seçilsin?",
            labels, labels.index(cur) if cur in labels else 0, False)
        if not ok:
            return
        _l, cls, attr, val = targets[labels.index(label)]
        c = self.project.get_class(cls)
        if attr:
            a = next(x for x in c["attributeler"] if x["ad"] == attr)
            voices = a.setdefault("sesli_adlar", {})
            old = voices.get(val, "")
        else:
            old = c.get("sesli_ad", "")
        parts = [x.strip() for x in old.split(",") if x.strip()]
        if heard not in parts:
            parts.append(heard)
        if attr:
            voices[val] = ", ".join(parts)
        else:
            c["sesli_ad"] = ", ".join(parts)
        self.project.save()
        self.apply_shortcuts()               # tanıyıcı kelime listesi + eşleştirme yenilensin
        self.statusBar().showMessage(f"🎤 Öğrenildi: “{heard}” → {label}", 4000)

    def _voice_device(self):
        name = self.settings.value("ses/cihaz", "")
        return next((i for i, n in voice.input_devices() if n == name), None) if name else None

    def set_voice_device(self, name):
        self.settings.setValue("ses/cihaz", name)
        if self.voice and self.voice.running:
            self._voice_stop()
            self._voice_start(ask=False)

    def set_voice_mode(self, mode):
        if mode not in dict(voice.MODES):
            mode = "baskonus"
        self.voice_mode = mode
        self.settings.setValue("ses/mod", mode)
        self.ptt_held = False
        self.voice_speaking = False
        if self.voice:
            self.voice.set_mode(mode)
        self._voice_update_button()

    def toggle_voice(self):
        if not self.voice:
            QMessageBox.information(self, "Sesle seçim",
                                    "Sesle seçim için şu kütüphaneler gerekli:\n\n"
                                    f"pip install {' '.join(self.voice_missing)}\n\n"
                                    "Kurduktan sonra programı yeniden açın.")
            return
        if self.voice.running:
            self._voice_stop()
            self.settings.setValue("ses/acik", False)
            self.statusBar().showMessage("🔇 Mikrofon kapatıldı.", 2500)
        else:
            self._voice_start(ask=True)

    def _voice_start(self, ask=True):
        if not self.voice or self.voice.running or self.downloader:
            return
        path = voice.find_model()
        if not path:
            if ask and QMessageBox.question(
                    self, "Ses modeli",
                    f"Sesle seçim için Türkçe konuşma modeli (~{voice.MODEL_SIZE_MB} MB) bir kere indirilecek.\n"
                    "İnternet sadece indirme için gerekir; tanıma bilgisayarında, internetsiz yapılır.\n\n"
                    "İndirilsin mi?") == QMessageBox.StandardButton.Yes:
                self._download_model()
            return
        self.voice_state = "yukleniyor"
        self.voice.set_mode(self.voice_mode)
        self.voice.set_phrases(self.voice_matcher.phrases() if self.voice_matcher else [])
        self.voice.start(path, self._voice_device())
        self.settings.setValue("ses/acik", True)
        self._voice_update_button()

    def _voice_stop(self):
        if self.voice:
            self.voice.stop()
        self.voice_state = "kapali"
        self.ptt_held = False
        self.voice_speaking = False
        self._voice_update_button()

    # ---------- model indirme ----------
    def _download_model(self):
        dlg = QProgressDialog("Türkçe ses modeli indiriliyor…", "İptal", 0, 0, self)
        dlg.setWindowTitle("Ses modeli")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        d = voice.ModelDownloader()
        d.progress.connect(self._on_dl_progress)
        d.finished.connect(self._on_dl_done)
        d.failed.connect(self._on_dl_failed)
        dlg.canceled.connect(lambda: setattr(d, "cancelled", True))
        self.downloader, self.dl_dialog = d, dlg
        dlg.show()
        d.start()

    def _on_dl_progress(self, done, total):
        if self.dl_dialog:
            if total:
                self.dl_dialog.setMaximum(total)
                self.dl_dialog.setValue(done)
            self.dl_dialog.setLabelText(f"Türkçe ses modeli indiriliyor…  {done / 1e6:.1f}"
                                        + (f" / {total / 1e6:.1f} MB" if total else " MB"))

    def _close_download(self):
        self.downloader = None
        if self.dl_dialog:
            self.dl_dialog.canceled.disconnect()
            self.dl_dialog.close()
            self.dl_dialog = None

    def _on_dl_done(self, _path):
        self._close_download()
        self._voice_start(ask=False)

    def _on_dl_failed(self, msg):
        self._close_download()
        if msg:
            QMessageBox.warning(
                self, "İndirilemedi",
                f"Ses modeli indirilemedi:\n{msg}\n\nİstersen elle indir:\n{voice.MODEL_URL}\n\n"
                f"ve zip'i şu klasöre çıkar:\n{voice.user_model_dir()}")

    # ---------- tanıyıcıdan gelenler ----------
    def _on_voice_state(self, state):
        self.voice_state = state
        if state == "hazir" and self.voice_mode == "surekli":
            self.statusBar().showMessage("🎤 Dinliyor — sınıfı / seçeneği söyle (ör. \"mercimek çorbası\").", 4000)
        self._voice_update_button()

    def _on_voice_error(self, msg):
        self._voice_stop()
        self.settings.setValue("ses/acik", False)
        QMessageBox.warning(self, "Mikrofon", f"Mikrofon / ses tanıma başlatılamadı:\n\n{msg}\n\n"
                                              "Mikrofonun takılı olduğundan ve Windows'ta uygulamalara mikrofon "
                                              "izni verildiğinden emin ol. 🎤 okundan başka mikrofon da seçebilirsin.")

    def _on_voice_speaking(self, on):
        self.voice_speaking = on
        self._voice_update_button()

    def _on_voice_partial(self, text):
        if text:
            self.statusBar().showMessage(f"🎤 {text} …", 3000)

    def _on_voice_heard(self, text):
        if not self.project or not self.sel or not self.voice_matcher or QApplication.activeModalWidget():
            return
        if not text:
            self.statusBar().showMessage("🎤 Anlaşılamadı, tekrar dene.", 3000)
            return
        self.last_heard = text
        r = self.voice_matcher.resolve(text, self.sel.cls, self.sel.attrs)
        if r is None:
            self.statusBar().showMessage(f"🎤 \"{text}\" — eşleşen yok. Yanlış duyduysa 🎤 okundan "
                                         "'Son duyulanı öğret' ile doğru seçeneğe bağlayabilirsin.", 6000)
        elif r[0] == "?":
            self.statusBar().showMessage(f"🎤 \"{text}\" birden fazla sınıfta var ({', '.join(r[1])}) — "
                                         "sınıfı da söyle.", 5000)
        else:
            cls, attrs = r
            self.sel.set_class(cls, attrs)
            self._selection_changed()
            chosen = " → ".join([cls] + list(self.sel.attrs.values()))
            self.statusBar().showMessage(f"🎤 \"{text}\"  ✔ {chosen}", 4000)

    # ---------- bas-konuş tuşu ----------
    def _ptt_match(self, ev, release):
        if not self.ptt_key:
            return False
        comb = QKeySequence(self.ptt_key)[0]
        if ev.key() != _as_int(comb.key()):
            return False
        if release:
            return True
        mods = ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        return _as_int(mods) == _as_int(comb.keyboardModifiers())

    def _ptt_context(self):
        """Bas-konuş tuşu şu an dinlenmeli mi (yazı kutusunda / pencere arkadayken değil)."""
        if self.voice_mode != "baskonus" or not self.project:
            return False
        if QApplication.activeWindow() is not self or QApplication.activeModalWidget():
            return False
        fw = QApplication.focusWidget()
        if isinstance(fw, QComboBox):
            return not fw.isEditable()
        return not isinstance(fw, (QLineEdit, QTextEdit, QPlainTextEdit, QKeySequenceEdit, QAbstractSpinBox))

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            release = t == QEvent.Type.KeyRelease
            if self.ptt_held and release and self._ptt_match(ev, True):
                if not ev.isAutoRepeat():
                    self._ptt_up()
                return True
            if not release and self._ptt_match(ev, False) and self._ptt_context():
                if ev.isAutoRepeat() or self.ptt_held:
                    return True
                if self.voice.running and self.voice_state == "hazir":
                    self._ptt_down()
                elif not self.voice.running:
                    mute_key = shortcuts.load_general(self.settings)["ses_ac_kapat"]
                    self.statusBar().showMessage(
                        "🔇 Mikrofon kapalı — açmak için 🎤 simgesine tıkla"
                        + (f" ya da {mute_key} tuşuna bas." if mute_key else "."), 3000)
                return True
        elif t in (QEvent.Type.ApplicationDeactivate, QEvent.Type.WindowDeactivate) and self.ptt_held:
            self._ptt_up()
        return super().eventFilter(obj, ev)

    def _ptt_down(self):
        self.ptt_held = True
        self.voice.ptt_press()
        self.statusBar().showMessage("🎤 Dinliyor…")
        self._voice_update_button()

    def _ptt_up(self):
        self.ptt_held = False
        self.voice.ptt_release()
        self._voice_update_button()

    def closeEvent(self, ev):
        if self.downloader:
            self.downloader.cancelled = True
        if self.voice:
            self.voice.stop()
        super().closeEvent(ev)

    # =================================================================
    #  Proje
    # =================================================================
    def choose_project(self):
        d = QFileDialog.getExistingDirectory(
            self, "Ortak proje klasörünü seçin (yoksa yeni klasör oluşturun)",
            self.settings.value("last_project", str(Path.home())))
        if d:
            self.open_project(d)

    def open_project(self, root):
        try:
            self.project = Project.open_or_create(root)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Hata", f"Proje açılamadı:\n{e}")
            return
        self.settings.setValue("last_project", str(root))
        self.setWindowTitle(f"Etiketleme — {self.project.name}  ({root})")
        self.undo_stack.clear()
        self.current = None
        self.current_image = None
        self.memory = {"attr": {}}
        self.browse = None
        self.stats_open.clear()
        self.btn_browse.hide()
        self.sel = KeySelector(self.project)
        self._update_enabled()
        self.apply_shortcuts()
        self.refresh_image_list()
        self.refresh_stats()
        self._update_active_label()
        if not self.project.classes:
            QMessageBox.information(self, "Hoş geldiniz",
                                    "Önce sınıfları tanımlayalım (ör. corba → corba_turu → mercimek, ezogelin).\n\n"
                                    "Elinizde CVAT XML dosyası varsa 'CVAT XML İçe Aktar' ile de doldurabilirsiniz.")
            self.open_setup()

    def reload_project(self):
        if self.project:
            cur = self.current
            self.project = Project.open_or_create(self.project.root)
            self.current_image = None
            self.sel.p = self.project
            self.sel.validate()
            self.apply_shortcuts()
            self.refresh_image_list(select=cur)
            self._selection_changed()

    def open_setup(self):
        SetupDialog(self.project, self).exec()
        self.boxes = copy.deepcopy(self.project.get_boxes(self.current)) if self.current else []
        self.canvas.set_boxes(self.boxes)
        self.sel.validate()
        self.apply_shortcuts()
        self.refresh_box_list()
        self.refresh_image_list(select=self.current)
        self._selection_changed()

    def show_folder(self):
        os.startfile(self.project.root)

    # =================================================================
    #  Fotoğraf ekleme (buton + sürükle-bırak)
    # =================================================================
    def add_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Fotoğraf seç", "", "Resimler (" + " ".join("*" + e for e in sorted(IMAGE_EXTS)) + ")")
        self._import_files(files)

    def add_image_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Fotoğraf klasörü seç")
        if d:
            self._import_files([str(p) for p in Path(d).rglob("*") if p.suffix.lower() in IMAGE_EXTS])

    def on_empty_list_click(self):
        if self.project:
            self.add_images()
        else:
            self.choose_project()

    def _import_files(self, files):
        files = self.project.importable(files)
        if not files:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            finder = DuplicateFinder(self.project)
            pending = [finder.check(f) is not None for f in files]   # kaç çakışma var (ön sayım)
        finally:
            QApplication.restoreOverrideCursor()

        added, replaced, skipped = [], [], 0
        remembered = None            # "kalan hepsine uygula" seçilirse
        for i, src in enumerate(files):
            dup = finder.check(src)
            if dup is None:
                name = self.project.add_image(src)
                finder.added(name)
                added.append(name)
                continue
            kind, existing = dup
            choice = remembered
            if choice is None:
                remaining = sum(pending[i + 1:])
                dlg = DuplicateDialog(self.project, src, kind, existing, remaining, self)
                dlg.exec()
                choice = dlg.choice
                if dlg.apply_all:
                    remembered = choice
            if choice == "iptal":
                skipped += len(files) - i
                break
            if choice == "degistir" and kind != "icerik":
                name = self.project.add_image(src, replace=True)
                finder.added(name)
                replaced.append(name)
            elif choice == "ekle":
                name = self.project.add_image(src)
                finder.added(name)
                added.append(name)
            else:
                skipped += 1

        if self.current in replaced:
            self.current_image = None      # değişen fotoğrafı yeniden yükle
        self.refresh_image_list(select=self.current or (added[0] if added else None))
        parts = [f"{len(added)} fotoğraf eklendi"]
        if replaced:
            parts.append(f"{len(replaced)} değiştirildi")
        if skipped:
            parts.append(f"{skipped} atlandı")
        self.statusBar().showMessage(", ".join(parts) + ".", 6000)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self.image_list.set_drag_active(True)
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.image_list.set_drag_active(False)

    def dropEvent(self, e):
        self.image_list.set_drag_active(False)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        e.acceptProposedAction()
        self.handle_drop(paths)

    def handle_drop(self, paths):
        if not self.project:
            QMessageBox.information(self, "Proje yok", "Önce bir proje klasörü açın.")
            return
        xmls = [p for p in paths if p.suffix.lower() == ".xml"]
        files = []
        for p in paths:
            if p.is_dir():
                files += [str(f) for f in p.rglob("*") if f.suffix.lower() in IMAGE_EXTS]
            elif p.suffix.lower() in IMAGE_EXTS:
                files.append(str(p))
        self._import_files(files)
        for x in xmls:
            self.import_cvat(str(x))

    # =================================================================
    #  Fotoğraf listesi / gezinme
    # =================================================================
    def refresh_image_list(self, select=None):
        if not self.project:
            return
        select = select or self.current
        self.images = self.project.list_images()
        mode = self.filter.currentIndex()
        self.image_list.blockSignals(True)
        self.image_list.clear()
        labeled = 0
        for name in self.images:
            n = len(self.project.get_boxes(name))
            labeled += n > 0
            if (mode == 1 and n) or (mode == 2 and not n):
                continue
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, name)
            self._style_item(it, name, n)
            self.image_list.addItem(it)
        self.image_list.blockSignals(False)
        self.progress_label.setText(f"Etiketlenen: <b>{labeled}</b> / {len(self.images)} fotoğraf")
        self.image_list.placeholder = (
            "" if not self.images else "Bu filtrede fotoğraf yok\n\n(eklemek için tıklayın\nveya sürükleyin)")
        self.image_list.viewport().update()

        row = next((i for i in range(self.image_list.count())
                    if self.image_list.item(i).data(Qt.ItemDataRole.UserRole) == select), None)
        if row is None and self.image_list.count():
            row = 0
        if row is not None:
            self.image_list.setCurrentRow(row)
        else:
            self.current = None
            self.current_image = None
            self.boxes = []
            self.canvas.set_image(None, [])
            self.title_label.setText("Fotoğraf yok — 'Fotoğraf Ekle' ya da sürükleyip bırakın.")
            self.refresh_box_list()

    @staticmethod
    def _style_item(it, name, n):
        it.setText(f"✔ {name}  ({n})" if n else f"     {name}")
        if n:
            it.setForeground(QBrush(QColor(GREEN)))
        else:
            it.setData(Qt.ItemDataRole.ForegroundRole, None)

    def _on_image_selected(self, item, _prev=None):
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if name == self.current and self.current_image is not None:
            return
        img = load_image(self.project.image_path(name))
        if img.isNull():
            self.statusBar().showMessage(f"Fotoğraf açılamadı: {name}", 5000)
            return
        self.current = name
        self.current_image = img
        self.boxes = copy.deepcopy(self.project.get_boxes(name))
        self.canvas.set_image(img, self.boxes)
        self._update_title()
        self.refresh_box_list()
        self._mark_current_photo()
        self.canvas.setFocus()

    def _update_title(self):
        name = self.current
        if not name:
            return
        idx = self.images.index(name) + 1 if name in self.images else 0
        self.title_label.setText(f"{name}   ({idx}/{len(self.images)})")
        if self.browse:
            names = [n for n, _ in self._photos_for(self.browse)]
            pos = f"{names.index(name) + 1}/{len(names)}" if name in names else f"–/{len(names)}"
            self.btn_browse.setText(f"🔎 {self._browse_label(self.browse)}  {pos}   ✕")

    def step(self, d):
        if self.browse:
            return self._browse_step(d)
        if not self.image_list.count():
            return
        row = self.image_list.currentRow() + d
        if 0 <= row < self.image_list.count():
            self.image_list.setCurrentRow(row)

    # =================================================================
    #  Fotoğraf silme
    # =================================================================
    def on_image_menu(self, pos):
        item = self.image_list.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.image_list.setCurrentItem(item)
        names = self._selected_names()
        m = QMenu(self)
        text = "🗑 Sil" if len(names) == 1 else f"🗑 Seçili {len(names)} fotoğrafı sil"
        a_del = m.addAction(text)
        if m.exec(self.image_list.viewport().mapToGlobal(pos)) == a_del:
            self.delete_images(names)

    def _selected_names(self):
        names = [it.data(Qt.ItemDataRole.UserRole) for it in self.image_list.selectedItems()]
        return names or ([self.current] if self.current else [])

    def delete_images(self, names=None):
        names = names if isinstance(names, list) else self._selected_names()
        if not names:
            return
        n_boxes = sum(len(self.project.get_boxes(n)) for n in names)
        what = f"'{names[0]}' fotoğrafı" if len(names) == 1 else f"{len(names)} fotoğraf"
        msg = f"{what} silinsin mi?"
        if n_boxes:
            msg += f"\n\nİçindeki {n_boxes} etiket de silinecek."
        key = shortcuts.load_general(self.settings)["geri_al"]
        msg += f"\n\n(Yanlışlıkla silerseniz {key} ile geri alabilirsiniz.)"
        box = QMessageBox(QMessageBox.Icon.Question, "Silmek istediğinize emin misiniz?", msg, parent=self)
        yes = box.addButton("Evet, sil", QMessageBox.ButtonRole.YesRole)
        box.addButton("Vazgeç", QMessageBox.ButtonRole.NoRole)
        box.exec()
        if box.clickedButton() != yes:
            return

        # silindikten sonra hangi fotoğrafa geçilecek
        visible = [self.image_list.item(i).data(Qt.ItemDataRole.UserRole)
                   for i in range(self.image_list.count())]
        rows = [visible.index(n) for n in names if n in visible]
        rest = [n for n in visible if n not in names]
        nxt = None
        if rest:
            after = [n for n in visible[max(rows) + 1:] if n not in names] if rows else []
            nxt = after[0] if after else rest[-1]

        tokens = self.project.delete_images(names)
        self.undo_stack.append({"tip": "resim_sil", "tokens": tokens})
        if self.current in names:
            self.current = None
            self.current_image = None
        self.refresh_image_list(select=nxt)
        self.refresh_stats()
        self.statusBar().showMessage(f"{len(tokens)} fotoğraf silindi.  {key}: geri al", 6000)

    # =================================================================
    #  Kutular
    # =================================================================
    def _save(self):
        """Aktif fotoğrafın kutularını diske yazar (otomatik kayıt)."""
        self.project.set_boxes(self.current, self.current_image.width(),
                               self.current_image.height(), copy.deepcopy(self.boxes))
        self.canvas.set_boxes(self.boxes)
        self.refresh_box_list()
        self._refresh_current_list_item()
        self.refresh_stats()

    def _push_box_undo(self):
        self.undo_stack.append({"tip": "kutu", "resim": self.current, "w": self.current_image.width(),
                                "h": self.current_image.height(), "kutular": copy.deepcopy(self.boxes)})
        del self.undo_stack[:-100]

    def undo(self):
        if not self.undo_stack:
            self.statusBar().showMessage("Geri alınacak bir şey yok.", 3000)
            return
        u = self.undo_stack.pop()
        if u["tip"] == "resim_sil":
            restored = self.project.restore_images(u["tokens"])
            self.current_image = None
            self.refresh_image_list(select=restored[0] if restored else self.current)
            self.refresh_stats()
            self.statusBar().showMessage(f"{len(restored)} fotoğraf geri getirildi.", 4000)
            return
        self.project.set_boxes(u["resim"], u["w"], u["h"], u["kutular"])
        if u["resim"] == self.current:
            self.boxes = copy.deepcopy(u["kutular"])
            self.canvas.set_boxes(self.boxes)
            self.refresh_box_list()
            self._refresh_current_list_item()
        else:
            self.current_image = None
            self.refresh_image_list(select=u["resim"])
        self.refresh_stats()
        self.statusBar().showMessage("Geri alındı.", 3000)

    def _ask_label(self, current=None):
        if not self.project.classes:
            QMessageBox.information(self, "Sınıf yok", "Önce sınıf tanımlamanız gerekiyor.")
            self.open_setup()
            if not self.project.classes:
                return None
        # tuşla seçim tamamsa (ör. 1 → 3 = corba / mantar) menü açmadan direkt etiketle
        if current is None and self.sel.complete():
            return self.sel.cls, dict(self.sel.attrs)
        # eksik seçim varsa menü o seçimle açılır (ör. sadece 1'e basıldıysa corba seçili gelir)
        dlg = LabelDialog(self.project, current=current, memory=self.memory,
                          selector=self.sel if current is None else None, parent=self)
        if dlg.exec() != LabelDialog.DialogCode.Accepted:
            return None
        cls, attrs = dlg.result_box()
        self.memory["sinif"] = cls
        self.memory["attr"].setdefault(cls, {}).update(attrs)
        if current is None and self.sel.cls:
            # yarım seçim menüde tamamlandı -> artık o seçim aktif (sonraki kutular sormadan)
            self.sel.set_class(cls, attrs)
            self._selection_changed()
        return cls, attrs

    def on_box_drawn(self, x1, y1, x2, y2):
        if self.current is None:
            return
        preview = {"sinif": "?", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "attributeler": {}}
        self.canvas.set_boxes(self.boxes + [preview])
        res = self._ask_label()
        if res is None:
            self.canvas.set_boxes(self.boxes)
            return
        self._push_box_undo()
        cls, attrs = res
        self.boxes.append({"sinif": cls, "x1": round(x1, 2), "y1": round(y1, 2),
                           "x2": round(x2, 2), "y2": round(y2, 2), "attributeler": attrs})
        self._save()
        self.statusBar().showMessage(f"Kaydedildi: {box_caption(self.boxes[-1])}", 3000)

    def edit_box(self, i):
        if not (0 <= i < len(self.boxes)):
            return
        res = self._ask_label(current=self.boxes[i])
        if res is None:
            return
        self._push_box_undo()
        self.boxes[i]["sinif"], self.boxes[i]["attributeler"] = res
        self._save()
        self.box_list.setCurrentRow(i)

    def delete_box(self, i):
        if not (0 <= i < len(self.boxes)):
            return
        self._push_box_undo()
        del self.boxes[i]
        self._save()

    def delete_selected_box(self):
        if self.list_active:
            self.delete_images()      # onay penceresi delete_images içinde
            return
        self.delete_box(self.box_list.currentRow())

    def on_box_menu(self, i, pos):
        self.box_list.setCurrentRow(i)
        m = QMenu(self)
        a_edit = m.addAction("Düzenle (sınıf / attribute değiştir)")
        a_del = m.addAction("Kutuyu sil")
        chosen = m.exec(pos)
        if chosen == a_edit:
            self.edit_box(i)
        elif chosen == a_del:
            self.delete_box(i)

    def refresh_box_list(self):
        self.box_list.blockSignals(True)
        self.box_list.clear()
        for b in self.boxes:
            self.box_list.addItem(QListWidgetItem(color_icon(self.project.color(b["sinif"])), box_caption(b)))
        self.box_list.blockSignals(False)
        self.canvas.set_selected(-1)

    def _refresh_current_list_item(self):
        it = self.image_list.currentItem()
        if it:
            self._style_item(it, self.current, len(self.boxes))
        labeled = sum(1 for i in self.images if self.project.get_boxes(i))
        self.progress_label.setText(f"Etiketlenen: <b>{labeled}</b> / {len(self.images)} fotoğraf")

    # =================================================================
    #  İstatistik
    # =================================================================
    def refresh_stats(self):
        scroll = self.stats_tree.verticalScrollBar().value()
        self.stats_tree.clear()
        if not self.project:
            return
        st = self.project.stats()
        self.stats_summary.setText(
            f"Toplam <b>{st['toplam_kutu']}</b> kutu, <b>{st['etiketli_resim']}</b> etiketli fotoğraf")
        bold = QFont()
        bold.setBold(True)
        sel = self.sel
        sel_bg = QBrush(QColor(47, 128, 237, 110))     # seçili satır arka planı
        pend_fg = QBrush(QColor("#f0a020"))

        def highlight(item, brush):
            for col in (0, 1):
                item.setBackground(col, brush)
                item.setFont(col, bold)

        for cls, info in st["siniflar"].items():
            c = self.project.get_class(cls) or {}
            mark = "▶ " if sel and sel.cls == cls else ""
            top = QTreeWidgetItem([mark + cls + shortcuts.label_for(c.get("kisayol", "")), str(info["toplam"])])
            top.setData(0, Qt.ItemDataRole.UserRole, (cls, None, None))
            top.setIcon(0, color_icon(self.project.color(cls)))
            top.setFont(0, bold)
            top.setFont(1, bold)
            if mark:
                highlight(top, sel_bg)
            if not info["attr"]:                     # seçeneksiz sınıf: fotoğraflar doğrudan altında
                self._make_photo_owner(top, (cls, None, None), info["toplam"])
            for attr, counts in info["attr"].items():
                a_def = self.project.get_attr(cls, attr) or {}
                keys = a_def.get("kisayollar", {})
                waiting = sel and sel.cls == cls and sel.pending == attr
                a_item = QTreeWidgetItem([attr + ("   ← tuşla seçin" if waiting else ""), ""])
                a_item.setData(0, Qt.ItemDataRole.UserRole, (cls, None, None))
                if waiting:
                    a_item.setForeground(0, pend_fg)
                    a_item.setFont(0, bold)
                for val, n in counts.items():
                    chosen = sel and sel.cls == cls and sel.attrs.get(attr) == val
                    v_item = QTreeWidgetItem([("✔ " if chosen else "") + val
                                              + shortcuts.label_for(keys.get(val, "")), str(n)])
                    v_item.setData(0, Qt.ItemDataRole.UserRole, (cls, attr, val))
                    if chosen:
                        highlight(v_item, sel_bg)
                    elif n == 0:
                        v_item.setForeground(0, QBrush(QColor("#999")))
                        v_item.setForeground(1, QBrush(QColor("#c62828")))
                    self._make_photo_owner(v_item, (cls, attr, val), n)
                    a_item.addChild(v_item)
                top.addChild(a_item)
            self.stats_tree.addTopLevelItem(top)
            if info["attr"]:
                top.setExpanded(True)
                for i in range(top.childCount()):
                    top.child(i).setExpanded(True)
        # fotoğraf listesi açık olanları geri aç (açılınca doldurulur)
        for item in self._stats_items():
            if item.data(0, ROLE_KEY) in self.stats_open:
                item.setExpanded(True)
        self._mark_current_photo(scroll=False)
        self.stats_tree.verticalScrollBar().setValue(scroll)
        if self.browse:
            self._update_title()

    def _on_stats_clicked(self, item, _col):
        photo = item.data(0, ROLE_PHOTO)
        if photo:
            return self.start_browse(item.parent().data(0, ROLE_KEY), photo)
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            cls, attr, val = data
            if attr and self.project.get_attr(cls, attr) and val in self.project.get_attr(cls, attr)["secenekler"]:
                self.set_active(cls, attr, val)
            else:
                self.set_active(cls)

    # =================================================================
    #  Etikete göre gezinme (istatistikte seçeneğin solundaki ok)
    # =================================================================
    @staticmethod
    def _make_photo_owner(item, key, n):
        item.setData(0, ROLE_KEY, key)
        if n:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            item.setToolTip(0, "Soldaki oka tıkla: bu etiketli fotoğraflar.\n"
                               "Bir fotoğrafa tıklayınca A / D sadece bunlarda gezer.")

    def _stats_items(self):
        """İstatistik ağacındaki tüm satırlar (liste olarak, gezerken ağaç değişebilir)."""
        out, stack = [], [self.stats_tree.topLevelItem(i) for i in range(self.stats_tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            out.append(item)
            stack[:0] = [item.child(i) for i in range(item.childCount())]
        return out

    @staticmethod
    def _browse_label(key):
        cls, _attr, val = key
        return f"{cls} › {val}" if val else cls

    def _photos_for(self, key):
        """Bu etiketli kutusu olan fotoğraflar (liste sırasıyla): [(ad, kutu sayısı)]"""
        cls, attr, val = key
        out = []
        for name in self.images:
            n = sum(1 for b in self.project.get_boxes(name) if b["sinif"] == cls and (
                attr is None or (b.get("attributeler", {}).get(attr) or UNSET) == val))
            if n:
                out.append((name, n))
        return out

    def _on_stats_expanded(self, item):
        key = item.data(0, ROLE_KEY)
        if not key or not self.project:
            return
        self.stats_open.add(key)
        if item.childCount():
            return
        photos = self._photos_for(key)
        for name, n in photos:
            p = QTreeWidgetItem(["🖼 " + name, str(n)])
            p.setData(0, ROLE_PHOTO, name)
            p.setToolTip(0, f"{name}\nTıkla: aç — A / D ile '{self._browse_label(key)}' fotoğraflarında gezin")
            item.addChild(p)
        if not photos:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        self._mark_current_photo(scroll=False)

    def _on_stats_collapsed(self, item):
        key = item.data(0, ROLE_KEY)
        if key:
            self.stats_open.discard(key)
            if key == self.browse:
                self.end_browse()

    def _mark_current_photo(self, scroll=True):
        """İstatistikteki fotoğraf satırlarında açık olanı vurgular."""
        bold = QFont()
        bold.setBold(True)
        target = None
        for item in self._stats_items():
            name = item.data(0, ROLE_PHOTO)
            if name:
                on = name == self.current
                in_browse = on and item.parent().data(0, ROLE_KEY) == self.browse
                brush = QBrush(QColor(21, 101, 192, 120)) if in_browse else (
                    QBrush(QColor(47, 128, 237, 50)) if on else QBrush())
                for col in (0, 1):
                    item.setBackground(col, brush)
                    item.setFont(col, bold if on else QFont())
                if in_browse:
                    target = item
        if scroll and target is not None:
            self.stats_tree.scrollToItem(target)

    def _show_image(self, name):
        """Fotoğrafı açar; soldaki filtre gizliyorsa filtreyi 'Tüm fotoğraflar' yapar."""
        def row_of():
            return next((i for i in range(self.image_list.count())
                         if self.image_list.item(i).data(Qt.ItemDataRole.UserRole) == name), None)
        row = row_of()
        if row is None and self.filter.currentIndex() != 0:
            self.filter.setCurrentIndex(0)
            row = row_of()
        if row is not None:
            self.image_list.setCurrentRow(row)
            self.image_list.scrollToItem(self.image_list.item(row))

    def start_browse(self, key, name):
        if not key:
            return
        self.browse = key
        self.btn_browse.show()
        if name == self.current:
            self._update_title()
            self._mark_current_photo()
        else:
            self._show_image(name)
        self.statusBar().showMessage(
            f"'{self._browse_label(key)}' fotoğraflarında geziniyorsunuz — A / D. "
            "Bitirmek için üstteki mavi düğme ya da oku kapatın.", 6000)

    def end_browse(self):
        if not self.browse:
            return
        self.browse = None
        self.btn_browse.hide()
        self._mark_current_photo(scroll=False)
        self.statusBar().showMessage("Etikete göre gezinme bitti — A / D tüm fotoğraflarda gezer.", 3000)

    def _browse_step(self, d):
        names = [n for n, _ in self._photos_for(self.browse)]
        label = self._browse_label(self.browse)
        if not names:
            self.end_browse()
            self.statusBar().showMessage(f"'{label}' etiketli fotoğraf kalmadı — gezinme bitti.", 4000)
            return
        if self.current in names:
            i = names.index(self.current) + d
        else:   # bu fotoğraftan etiket kaldırıldı: genel sıraya göre bir sonraki / önceki
            order = {n: k for k, n in enumerate(self.images)}
            cur = order.get(self.current, -1)
            after = [k for k, n in enumerate(names) if order[n] > cur]
            first_after = after[0] if after else len(names)
            i = first_after if d > 0 else first_after - 1
        if 0 <= i < len(names):
            self._show_image(names[i])
        else:
            edge = "Son" if d > 0 else "İlk"
            self.statusBar().showMessage(f"{edge} '{label}' fotoğrafı ({len(names)} fotoğraf).", 3000)

    def _on_list_pressed(self, item):
        self.list_active = True
        # soldan bu etikette olmayan bir fotoğraf seçildi -> normal gezinmeye dön
        if self.browse and item.data(Qt.ItemDataRole.UserRole) not in dict(self._photos_for(self.browse)):
            self.end_browse()

    # =================================================================
    #  İçe / Dışa aktar
    # =================================================================
    def import_cvat(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "CVAT XML seç", "", "XML (*.xml)")
        if not path:
            return
        try:
            labels, images = read_cvat(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Hata", f"XML okunamadı:\n{e}")
            return
        existing = set(self.project.list_images())
        with_boxes = {k: v for k, v in images.items() if v["kutular"]}
        found = {k: v for k, v in with_boxes.items() if k in existing}
        missing = len(with_boxes) - len(found)
        n_boxes = sum(len(v["kutular"]) for v in found.values())
        msg = (f"{len(labels)} sınıf tanımı bulundu (eksik olanlar eklenecek).\n"
               f"{len(found)} fotoğrafta toplam {n_boxes} kutu içe aktarılacak.\n")
        if missing:
            msg += (f"\nUYARI: Kutusu olan {missing} fotoğraf proje klasöründe yok, atlanacak.\n"
                    "(Önce o fotoğrafları ekleyip tekrar deneyin.)\n")
        msg += "\nBu fotoğraflarda mevcut kutular XML'dekilerle DEĞİŞTİRİLECEK. Devam edilsin mi?"
        if QMessageBox.question(self, "CVAT içe aktar", msg) != QMessageBox.StandardButton.Yes:
            return
        merge_labels(self.project, labels)
        for name, data in found.items():
            self.project.set_boxes(name, data["genislik"], data["yukseklik"], data["kutular"])
        self.current_image = None
        self.apply_shortcuts()
        self.refresh_image_list(select=self.current)
        self.refresh_stats()
        QMessageBox.information(self, "Tamam", f"{n_boxes} kutu içe aktarıldı.")

    def export(self):
        dlg = ExportDialog(self.project, self)
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            return
        opts = dlg.options()
        out = opts.pop("out_dir")

        def progress(text):
            self.statusBar().showMessage(text)
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ex = Exporter(self.project, out, progress=progress, **opts)
            if not ex.images:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, "Uyarı", "Aktarılacak etiketli fotoğraf yok.")
                return
            warnings = ex.run(dlg.formats())
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Hata", f"Dışa aktarma başarısız:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage("Dışa aktarma tamamlandı.", 5000)
        text = f"{len(ex.images)} fotoğraf dışa aktarıldı:\n{out}"
        if warnings:
            text += "\n\n" + "\n".join(warnings)
        box = QMessageBox(QMessageBox.Icon.Information, "Tamam", text, parent=self)
        open_btn = box.addButton("Klasörü Aç", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Kapat", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == open_btn:
            os.startfile(out)
