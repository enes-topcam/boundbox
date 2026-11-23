import copy
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QActionGroup, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QProgressDialog, QSizePolicy, QSplitter, QTextEdit, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import icons, panel, shortcuts, theme, voice
from . import widgets as W
from .canvas import Canvas
from .dialogs import DuplicateDialog, ExportDialog, LabelDialog, SettingsDialog, SetupDialog, StatsDialog
from .exporters import Exporter
from .image_list import ROLE_COUNT, ROLE_PATH, ImageList
from .imageutil import box_label, load_image
from .importers import merge_labels, read_cvat
from .project import IMAGE_EXTS, DuplicateFinder, Project
from .selection import KeySelector

FILTERS = ["Tüm fotoğraflar", "Etiketlenenler", "Etiket bekleyenler"]
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
        self.stats_closed = set()    # istatistikte kapatılmış sınıf kartları

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
        # ---------- sol: fotoğraf listesi ----------
        left = QWidget()
        left.setProperty("surface", "panel")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 10, 12, 6)
        head.addWidget(W.label("Fotoğraflar", "panelTitle"))
        head.addStretch()
        self.photo_count = W.label("", "count")
        head.addWidget(self.photo_count)
        ll.addLayout(head)
        self.filter = QComboBox()
        self.filter.setProperty("filter", True)
        self.filter.addItems(FILTERS)
        self.filter.setToolTip("Fotoğraf filtresi")
        self.filter.currentIndexChanged.connect(lambda _: self.refresh_image_list())
        frow = QHBoxLayout()
        frow.setContentsMargins(10, 0, 10, 6)
        frow.addWidget(self.filter)
        ll.addLayout(frow)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Fotoğraf ara (ad)")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Adın bir kısmını ya da tamamını yaz / yapıştır. Enter: ilk sonucu aç, "
                               "Esc: aramayı temizle.")
        self.search_icon = self.search.addAction(icons.icon("search", theme.c("dim")),
                                                 QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _: self.refresh_image_list())
        self.search.returnPressed.connect(self._search_enter)
        self.search.installEventFilter(self)
        srow = QHBoxLayout()
        srow.setContentsMargins(10, 0, 10, 6)
        srow.addWidget(self.search)
        ll.addLayout(srow)
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
        ll.addWidget(self.image_list, 1)
        foot = QFrame()
        foot.setProperty("strip", "foot")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(12, 10, 12, 12)
        fl.setSpacing(7)
        prow = QHBoxLayout()
        prow.addWidget(W.label("Etiketlenen", "small"))
        prow.addStretch()
        self.progress_label = W.label("", "strong")
        prow.addWidget(self.progress_label)
        fl.addLayout(prow)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        fl.addWidget(self.progress_bar)
        ll.addWidget(foot)

        # ---------- orta: gezinme + çizim satırı + tuval ----------
        self.canvas = Canvas(lambda c: self.project.color(c) if self.project else "#fff")
        self.canvas.boxDrawn.connect(self.on_box_drawn)
        self.canvas.boxRightClicked.connect(self.on_box_menu)
        self.canvas.boxResized.connect(self.on_box_resized)
        self.canvas.pressed.connect(lambda: setattr(self, "list_active", False))
        self.canvas.hint.connect(lambda t: self.hint_label.setText(t))
        self.canvas.emptyAction.connect(self.on_empty_list_click)

        nav = QFrame()
        nav.setProperty("strip", "nav")
        top = QHBoxLayout(nav)
        top.setContentsMargins(10, 6, 10, 6)
        top.setSpacing(6)
        self.btn_prev = W.tool_button(icon="chevron-left", tip="Önceki fotoğraf", slot=lambda: self.step(-1),
                                      outline=True, square=True)
        self.btn_next = W.tool_button(icon="chevron-right", tip="Sonraki fotoğraf", slot=lambda: self.step(1),
                                      outline=True, square=True)
        self.title_label = W.label("", "strong")
        self.title_label.setMinimumWidth(60)
        self.btn_copy_name = W.tool_button(icon="copy", tip="Fotoğrafın adını kopyala", slot=self.copy_name,
                                           role="dim", square=True)
        self.pos_label = W.label("", "count")
        self.btn_browse = W.tool_button("", icon="x", tip="Etiket filtresini kapat (tüm fotoğraflarda gezin)",
                                        slot=self.end_browse, role="accent_ink")
        self.btn_browse.setProperty("chip", "filter")
        self.btn_browse.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_browse.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.btn_browse.setIconSize(QSize(13, 13))
        self.btn_browse.hide()
        self.btn_fit = W.tool_button(icon="maximize", tip="Fotoğrafı sığdır", slot=self.canvas.fit, square=True)
        self.btn_del_img = W.tool_button(icon="trash-2", tip="Fotoğrafı sil", slot=self.delete_images, square=True)
        top.addWidget(self.btn_prev)
        top.addWidget(self.btn_next)
        top.addSpacing(4)
        top.addWidget(self.title_label)
        top.addWidget(self.btn_copy_name)
        top.addWidget(self.pos_label)
        top.addSpacing(6)
        top.addWidget(self.btn_browse)
        top.addStretch(1)
        top.addWidget(self.btn_fit)
        top.addWidget(self.btn_del_img)

        draw = QFrame()
        draw.setProperty("strip", "draw")
        dl = QHBoxLayout(draw)
        dl.setContentsMargins(10, 6, 10, 6)
        dl.setSpacing(8)
        mode = W.tool_button("Kutu çiz", icon="square-dashed",
                             tip="İki tıkla kutu çiz: önce sol üst, sonra sağ alt köşe")
        mode.setProperty("chip", "info")
        mode.setIconSize(QSize(15, 15))
        mode.setCursor(Qt.CursorShape.ArrowCursor)
        mode.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.pill = QFrame()
        self.pill.setProperty("pill", "empty")
        pl = QHBoxLayout(self.pill)
        pl.setContentsMargins(7, 3, 8, 3)
        pl.setSpacing(6)
        self.pill_dot = W.dot_label("#888888", 8)
        self.pill_text = QLabel()
        pl.addWidget(self.pill_dot)
        pl.addWidget(self.pill_text)
        self.btn_clear_sel = W.tool_button(icon="x", tip="Aktif etiketi sıfırla",
                                           slot=lambda: self.project and self.clear_selection(), role="dim")
        self.btn_clear_sel.setFixedSize(24, 24)
        self.btn_clear_sel.setIconSize(QSize(14, 14))
        self.options_label = W.label("", "small")
        self.hint_label = W.label("", "small")
        dl.addWidget(mode)
        dl.addWidget(self.pill)
        dl.addWidget(self.btn_clear_sel)
        dl.addWidget(self.options_label)
        dl.addWidget(self.hint_label)
        dl.addStretch()

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(nav)
        cl.addWidget(draw)
        cl.addWidget(self.canvas, 1)

        # ---------- sağ: kutular + istatistik ----------
        right = panel.Panel()
        right.setProperty("surface", "panel")
        self.right_panel = right
        self.panel_compact = False
        self._want_scroll = False
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit_panel)
        right.resized.connect(self._fit_timer.start)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        # ---------- Bu fotoğraftaki etiketler ----------
        def section_head(icon_name, title, right=None, margins=(12, 12, 12, 8)):
            row = QHBoxLayout()
            row.setContentsMargins(*margins)
            row.setSpacing(7)
            ic = QLabel()
            ic.setFixedSize(16, 16)
            self.panel_icons.append((ic, icon_name))
            row.addWidget(ic)
            row.addWidget(W.label(title, "panelTitle"))
            row.addStretch()
            if right is not None:
                row.addWidget(right)
            return row

        self.panel_icons = []
        self.box_count = W.label("", "countPill")
        self.box_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addLayout(section_head("tags", "Bu fotoğraftaki etiketler", self.box_count))
        self.box_list = QListWidget()
        self.box_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.box_list.setMouseTracking(True)
        self.box_list.setStyleSheet("QListView { margin: 0 8px; background: transparent; }"
                                    "QListView::item, QListView::item:hover, QListView::item:selected "
                                    "{ background: transparent; border: 0; padding: 0; margin: 0; }")
        self.box_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.box_list.setItemDelegate(panel.BoxDelegate(
            self.box_list, on_edit=self._edit_box_row, on_delete=self._delete_box_row,
            color_fn=lambda c: self.project.color(c) if self.project else "#888888"))
        self.box_list.currentRowChanged.connect(self.canvas.set_selected)
        self.box_list.currentRowChanged.connect(lambda _: self._update_box_buttons())
        self.box_list.itemPressed.connect(lambda _: setattr(self, "list_active", False))
        self.box_list.itemDoubleClicked.connect(lambda _: self.edit_box(self.box_list.currentRow()))
        self.box_empty = W.label("Bu fotoğrafta henüz etiket yok.", "muted", wrap=True)
        self.box_empty.setContentsMargins(12, 2, 12, 6)
        self.box_empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        rl.addWidget(self.box_list)
        rl.addWidget(self.box_empty)
        rl.addSpacing(10)
        rl.addWidget(W.hline())

        # ---------- Proje istatistikleri ----------
        stats_help = W.tool_button(icon="info", role="dim", square=True)
        stats_help.setToolTip("Satıra tıkla: aktif etiket yap.\n"
                              "Yemeğin solundaki oka tıkla: o etiketli fotoğraflar (A / D sadece onlarda gezer).\n"
                              "Sınıfın sağındaki ok: kartı aç / kapat.\n\n"
                              "Etiket: çizilen her işaretleme. Fotoğraf: o etiketin geçtiği farklı fotoğraf sayısı\n"
                              "(bir fotoğrafta 3 mercimek varsa 3 etiket, 1 fotoğraf).")
        stats_help.setCursor(Qt.CursorShape.WhatsThisCursor)
        rl.addLayout(section_head("chart-column", "Proje istatistikleri", stats_help, (12, 12, 8, 8)))
        cards = QHBoxLayout()
        cards.setContentsMargins(10, 0, 10, 0)
        cards.setSpacing(8)
        self.card_boxes = panel.SummaryCard("tags", "Toplam etiket", "Fotoğraflardaki bütün işaretlemeler", short="etiket")
        self.card_photos = panel.SummaryCard("image", "Etiketli fotoğraf",
                                             "En az bir etiketi olan fotoğraflar (her fotoğraf bir kez sayılır)",
                                             short="fotoğraf")
        cards.addWidget(self.card_boxes, 1)
        cards.addWidget(self.card_photos, 1)
        rl.addLayout(cards)
        self.stats_summary = W.label("", "small", wrap=True)
        self.stats_summary.setContentsMargins(13, 6, 12, 2)
        rl.addWidget(self.stats_summary)
        self.stats_tree = QTreeWidget()
        self.stats_tree.setHeaderHidden(True)
        self.stats_tree.setColumnCount(1)
        self.stats_tree.setIndentation(0)
        self.stats_tree.setRootIsDecorated(False)
        self.stats_tree.setExpandsOnDoubleClick(False)
        self.stats_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stats_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.stats_tree.setMouseTracking(True)
        self.stats_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stats_tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.stats_delegate = panel.StatsDelegate(self.stats_tree)
        self.stats_tree.setItemDelegate(self.stats_delegate)
        self.stats_tree.setStyleSheet("QTreeView { margin: 0 6px 6px 6px; background: transparent; }"
                                      "QTreeView::item, QTreeView::item:hover { background: transparent; "
                                      "padding: 0; }")
        self.stats_tree.itemClicked.connect(self._on_stats_clicked)
        self.stats_tree.itemExpanded.connect(self._on_stats_expanded)
        self.stats_tree.itemCollapsed.connect(self._on_stats_collapsed)
        rl.addWidget(self.stats_tree, 2)
        self._refresh_panel_icons()

        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(right)
        left.setMinimumWidth(190)
        right.setMinimumWidth(260)
        split.setSizes([232, 840, 340])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        self.setCentralWidget(split)

        # ---------- alt durum çubuğu ----------
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.status_default = QLabel("İki tıkla kutu çiz")
        self.status_default.setContentsMargins(6, 0, 0, 0)
        sb.addWidget(self.status_default, 1)
        self.status_keys = QWidget()
        self.status_keys_lay = QHBoxLayout(self.status_keys)
        self.status_keys_lay.setContentsMargins(0, 0, 8, 0)
        self.status_keys_lay.setSpacing(4)
        sb.addPermanentWidget(self.status_keys)
        self.save_label = QLabel()
        self.save_label.setContentsMargins(0, 0, 8, 0)
        sb.addPermanentWidget(self.save_label)
        self._set_save_state(True)
        theme.notifier().changed.connect(self._on_theme_changed)

    def _set_save_state(self, ok, err=""):
        self.save_ok = ok
        self.save_label.setProperty("role", "saved" if ok else "saveError")
        self.save_label.setText("✓ Otomatik kayıt" if ok else "⚠ Kayıt başarısız")
        self.save_label.setToolTip("Her değişiklik anında diske yazılır." if ok
                                   else f"Son değişiklik diske yazılamadı:\n{err}\n\n"
                                        "Klasöre erişimi / disk alanını kontrol edip işlemi tekrarlayın.")
        theme.repolish(self.save_label)

    def _update_status_keys(self, g):
        lay = self.status_keys_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        groups = [([g["onceki"], g["sonraki"]], "Gezin"), ([g["sigdir"]], "Sığdır"), ([g["geri_al"]], "Geri al")]
        for keys, text in groups:
            keys = [k for k in keys if k]
            if not keys:
                continue
            for k in keys:
                lay.addWidget(W.kbd(k))
            lay.addWidget(QLabel(text))
            lay.addSpacing(6)

    def _on_theme_changed(self):
        self._show_theme(self.settings.value("tema", "sistem"))
        self._update_active_label()
        self._refresh_panel_icons()
        self.stats_tree.viewport().update()
        self.box_list.viewport().update()

    def _refresh_panel_icons(self):
        self.search_icon.setIcon(icons.icon("search", theme.c("dim")))
        for lb, name in self.panel_icons:
            lb.setPixmap(icons.icon(name, theme.c("dim")).pixmap(16, 16))
        self.card_boxes.refresh_icon()
        self.card_photos.refresh_icon()

    def _build_toolbar(self):
        tb = self.addToolBar("Araçlar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.toggleViewAction().setEnabled(False)
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        tb.setIconSize(QSize(17, 17))

        # ---------- proje ----------
        self.project_btn = QToolButton()
        self.project_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.project_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.project_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pl = QHBoxLayout(self.project_btn)
        pl.setContentsMargins(8, 2, 8, 2)
        pl.setSpacing(8)
        self.project_icon = QLabel()
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.project_name = W.label("", "strong")
        self.project_sub = W.label("", "small")
        texts.addWidget(self.project_name)
        texts.addWidget(self.project_sub)
        self.project_chev = QLabel()
        pl.addWidget(self.project_icon)
        pl.addLayout(texts)
        pl.addWidget(self.project_chev)
        for w in (self.project_icon, self.project_name, self.project_sub, self.project_chev):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        pm = QMenu(self.project_btn)
        a = pm.addAction("Proje aç / oluştur…", self.choose_project)
        W.set_icon(a, "folder-open")
        pm.addSeparator()
        self.a_refresh = pm.addAction("Yenile", self.reload_project)
        W.set_icon(self.a_refresh, "refresh-cw")
        self.a_open_dir = pm.addAction("Klasörü göster", self.show_folder)
        W.set_icon(self.a_open_dir, "folder-open")
        self.project_btn.setMenu(pm)
        tb.addWidget(self.project_btn)
        tb.addSeparator()

        # ---------- fotoğraf / sınıf / içe aktar ----------
        self.btn_add = W.tool_button("Fotoğraf ekle", icon="image-plus", tip="Fotoğraf ekle (dosya seç)",
                                     slot=self.add_images, outline=True)
        self.btn_add.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_add.setProperty("split", True)
        am = QMenu(self.btn_add)
        a = am.addAction("Dosya seç…", self.add_images)
        W.set_icon(a, "image-plus")
        a = am.addAction("Klasörden ekle…", self.add_image_folder)
        W.set_icon(a, "folder-plus")
        self.btn_add.setMenu(am)
        self.btn_setup = W.tool_button("Sınıflar", icon="tags", tip="Sınıfları düzenle", slot=self.open_setup)
        self.btn_import = W.tool_button("İçe aktar", icon="upload", tip="CVAT XML içe aktar",
                                        slot=lambda: self.import_cvat())
        for b in (self.btn_add, self.btn_setup, self.btn_import):
            tb.addWidget(b)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # ---------- mikrofon / tema / ayarlar / dışa aktar ----------
        self.mic_btn = W.tool_button("Kapalı", icon="mic-off", slot=self.toggle_voice, role="dim")
        self.mic_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.mic_btn.setProperty("split", True)
        mic_menu = QMenu(self.mic_btn)
        mic_menu.aboutToShow.connect(lambda: self._fill_mic_menu(mic_menu))
        self.mic_btn.setMenu(mic_menu)
        tb.addWidget(self.mic_btn)

        current = self.settings.value("tema", "sistem")
        self.theme_btn = W.tool_button(icon="monitor", square=True)
        self.theme_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.theme_btn)
        group = QActionGroup(self)
        for key, icon_name, name in theme.MODES:
            a = menu.addAction(name)
            W.set_icon(a, icon_name)
            a.setCheckable(True)
            a.setChecked(key == current)
            a.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            group.addAction(a)
        self.theme_btn.setMenu(menu)
        tb.addWidget(self.theme_btn)

        self.btn_stats = W.tool_button("İstatistik", icon="chart-column", tip="İstatistik",
                                       slot=self.open_stats)
        tb.addWidget(self.btn_stats)
        self.btn_settings = W.tool_button(icon="settings", tip="Ayarlar", slot=lambda: self.open_settings(),
                                          square=True)
        tb.addWidget(self.btn_settings)
        self.btn_export = W.tool_button("Dışa aktar", icon="download", tip="Dışa aktar", slot=self.export,
                                        primary=True)
        tb.addWidget(self.btn_export)
        self._show_theme(current)

    def _update_project_button(self):
        self.project_icon.setPixmap(icons.icon("folder-open", theme.c("accent_ink")).pixmap(18, 18))
        self.project_chev.setPixmap(icons.icon("chevron-down", theme.c("dim")).pixmap(14, 14))
        if self.project:
            self.project_name.setText(self.project.name)
            parent = self.project.root.parent
            self.project_sub.setText(parent.name or str(parent))
            self.project_btn.setToolTip(f"{self.project.root}\n\nProje aç / oluştur, yenile, klasörü göster")
        else:
            self.project_name.setText("Proje aç")
            self.project_sub.setText("klasör seçilmedi")
            self.project_btn.setToolTip("Proje klasörü aç / oluştur")
        fm_name = self.project_name.fontMetrics()
        fm_sub = self.project_sub.fontMetrics()
        text_w = max(fm_name.horizontalAdvance(self.project_name.text()) + 8,
                     fm_sub.horizontalAdvance(self.project_sub.text()) + 8)
        self.project_btn.setFixedWidth(min(text_w, 260) + 18 + 14 + 16 + 16)
        self.project_btn.setMinimumHeight(38)

    def _show_theme(self, key):
        _, icon_name, name = next((m for m in theme.MODES if m[0] == key), theme.MODES[0])
        W.set_icon(self.theme_btn, icon_name)
        self.theme_btn.setToolTip(f"Tema: {name}  (değiştirmek için tıklayın)")
        self._update_project_button()

    def set_theme(self, key):
        self.settings.setValue("tema", key)
        theme.apply(key)

    def _update_enabled(self):
        on = self.project is not None
        for w in (self.btn_setup, self.btn_add, self.a_refresh, self.btn_import, self.btn_export, self.btn_stats,
                  self.a_open_dir, self.btn_settings, self.btn_fit, self.btn_del_img,
                  self.btn_prev, self.btn_next, self.mic_btn, self.search, self.btn_copy_name):
            w.setEnabled(on)
        self._update_project_button()
        if not on:
            self.title_label.setText("Proje açık değil")
            self.pos_label.setText("")
            self.photo_count.setText("")
            self.progress_label.setText("–")
            self.progress_bar.setValue(0)
            self.image_list.placeholder = "Önce proje aç / oluştur"
            self.image_list.viewport().update()
            self.canvas.set_empty("Proje açık değil", "Proje aç / oluştur")
            self.refresh_box_list()

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
            "disa_aktar": self.export, "istatistik": self.open_stats, "yenile": self.reload_project,
            "ara": self.focus_search, "ad_kopyala": self.copy_name,
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
                "foto_sil": self.btn_del_img, "sifirla": self.btn_clear_sel,
                "disa_aktar": self.btn_export, "istatistik": self.btn_stats,
                "ad_kopyala": self.btn_copy_name}
        for k, btn in tips.items():
            base = btn.toolTip().split("  (")[0]
            btn.setToolTip(base + (f"  ({g[k]})" if g[k] else ""))
        self.a_refresh.setText("Yenile" + (f"\t{g['yenile']}" if g["yenile"] else ""))
        self._update_status_keys(g)

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
        self._want_scroll = True
        self._fit_timer.start()

    def _update_active_label(self):
        """Çizim satırındaki aktif etiket rozeti: Hazır / ... seç / Etiket seçilmedi."""
        sel = self.sel
        if not self.project or not sel or not sel.cls:
            W.prop(self.pill, "pill", "empty")
            self.pill_dot.hide()
            self.pill_text.setText("Etiket seçilmedi")
            self.pill.setToolTip("Kutu çizince etiket penceresi açılır. Sınıf tuşuna basarak "
                                 "önceden seçebilirsin.")
            self.btn_clear_sel.hide()
            self.options_label.hide()
            return
        self.pill_dot.setPixmap(W.dot_pixmap(self.project.color(sel.cls), 8, 2))
        self.pill_dot.show()
        self.btn_clear_sel.show()
        chosen = " › ".join([sel.cls] + list(sel.attrs.values()))
        if sel.complete():
            W.prop(self.pill, "pill", "ready")
            self.pill_text.setText(f"{chosen} · Hazır")
            self.pill.setToolTip("Kutular etiket penceresi açılmadan bu etiketle kaydedilir.")
            self.options_label.hide()
        else:
            W.prop(self.pill, "pill", "partial")
            self.pill_text.setText(f"{chosen} · {sel.pending} seç")
            self.pill.setToolTip(f"Sıradaki: {sel.pending}. Tuşuna bas ya da kutuyu çiz, pencerede seç.")
            self.options_label.setText(sel.options_hint())
            self.options_label.setVisible(bool(sel.options_hint()))

    def open_settings(self, tab=0):
        dlg = SettingsDialog(self.project, self.settings, self, tab=tab,
                             refresh_devices=self.refresh_voice_devices if self.voice else None)
        if dlg.exec():
            self.apply_shortcuts()
            self.sel.validate()
            self._selection_changed()
            self.set_voice_mode(self.settings.value("ses/mod", "baskonus"))
            if dlg.device_name != self.settings.value("ses/cihaz", ""):
                self.set_voice_device(dlg.device_name)

    # =================================================================
    #  Sesle seçim ("mercimek çorbası" → corba → mercimek)
    # =================================================================
    def _voice_update_button(self):
        if not hasattr(self, "mic_btn"):
            return
        mute_key = shortcuts.load_general(self.settings)["ses_ac_kapat"]
        mute = f" ({mute_key})" if mute_key else ""
        on = bool(self.voice and self.voice.running)
        if not self.voice:
            state, icon, role, text = "none", "mic-off", "disabled", "Kullanılamıyor"
            tip = "Sesle seçim için kütüphane eksik:\npip install " + " ".join(self.voice_missing)
        elif not on:
            state, icon, role, text = "off", "mic-off", "dim", "Kapalı"
            tip = f"Mikrofon kapalı. Açmak için tıkla{mute}.\nYanındaki ok: dinleme şekli, mikrofon seçimi"
        elif self.voice_state == "yukleniyor":
            state, icon, role, text = "wait", "mic", "warn", "Hazırlanıyor…"
            tip = "Ses modeli yükleniyor…"
        elif self.ptt_held or (self.voice_mode == "surekli" and self.voice_speaking):
            state, icon, role, text = "live", "mic", "good", "Dinliyor"
            tip = "Konuşuyorsun — söylediğin sınıf / seçenek seçilecek"
        elif self.voice_mode == "surekli":
            state, icon, role, text = "on", "mic", "good", "Sürekli"
            tip = f"Sürekli dinliyor. Sınıfı / seçeneği söylemen yeter.\nKapatmak (sessize almak) için tıkla{mute}."
        else:
            k = self.ptt_key or "tuş atanmamış"
            state, icon, role, text = "ptt", "mic", "ink", f"Bas-konuş ({k})"
            tip = (f"{k} tuşunu basılı tutarken söyle, bırakınca seçilir.\n"
                   f"Kapatmak (sessize almak) için tıkla{mute}.")
        self.mic_btn.setText(text)
        self.mic_btn.setToolTip(tip)
        W.set_icon(self.mic_btn, icon, role)
        W.prop(self.mic_btn, "mic", state)

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
        current = self.settings.value("ses/cihaz", "")
        devices = [n for _i, n in voice.input_devices()]
        shown = current if current in devices else "Varsayılan"
        dev_menu = menu.addMenu(f"🎙 Mikrofon: {shown}")
        dev_group = QActionGroup(dev_menu)
        for name in [""] + devices:
            a = dev_menu.addAction(name or "Varsayılan (Windows ayarı)")
            a.setCheckable(True)
            a.setChecked(name == (current if current in devices else ""))
            a.triggered.connect(lambda _=False, n=name: self.set_voice_device(n))
            dev_group.addAction(a)
        dev_menu.addSeparator()
        dev_menu.addAction("🔄 Listeyi yenile (yeni taktığın mikrofon yoksa)").triggered.connect(
            self.refresh_voice_devices)
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
        self.statusBar().showMessage(f"🎙 Mikrofon: {name or 'Varsayılan (Windows ayarı)'}", 3000)

    def refresh_voice_devices(self):
        """Sonradan takılan mikrofonlar görünsün; dinleme açıksa kısa süre kapatılıp yeniden açılır."""
        if not self.voice:
            return
        was_on = self.voice.running
        if was_on:
            self._voice_stop()
        ok = self.voice.refresh_devices()
        if was_on:
            self._voice_start(ask=False)
        n = len(voice.input_devices())
        self.statusBar().showMessage(f"🔄 Mikrofon listesi yenilendi: {n} mikrofon bulundu." if ok
                                     else "Mikrofon listesi şu an yenilenemedi, birazdan tekrar dene.", 3500)

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
        if obj is getattr(self, "search", None) and ev.type() in (QEvent.Type.ShortcutOverride,
                                                                   QEvent.Type.KeyPress) \
                and ev.key() == Qt.Key.Key_Escape:
            if t == QEvent.Type.ShortcutOverride:   # Esc "çizimi iptal et" kısayoluna gitmesin
                ev.accept()
                return True
            self.search.clear()
            self.canvas.setFocus()
            return True
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
                                    "Önce sınıfları tanımlayalım (ör. corba → tur → mercimek, ezogelin).\n\n"
                                    "Elinizde CVAT XML dosyası varsa üstteki 'İçe aktar' ile de doldurabilirsiniz.")
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
        query = self._search_query()
        self.image_list.blockSignals(True)
        self.image_list.clear()
        labeled = 0
        for name in self.images:
            n = len(self.project.get_boxes(name))
            labeled += n > 0
            if (mode == 1 and not n) or (mode == 2 and n):
                continue
            if query and query not in name.lower():
                continue
            it = QListWidgetItem(name)
            it.setData(Qt.ItemDataRole.UserRole, name)
            it.setData(ROLE_PATH, str(self.project.image_path(name)))
            it.setToolTip(name)
            it.setData(ROLE_COUNT, n)
            self.image_list.addItem(it)
        self.image_list.blockSignals(False)
        self._update_progress(labeled)
        if query:
            self.photo_count.setText(f"{self.image_list.count()} / {len(self.images)}")
        empty = "Aramayla eşleşen fotoğraf yok" if query else "Bu filtrede fotoğraf yok"
        self.image_list.placeholder = "Fotoğraf ekle veya bırak" if not self.images else empty
        self.image_list.viewport().update()
        if self.images:
            self.canvas.set_empty(empty)
        else:
            self.canvas.set_empty("Henüz fotoğraf eklenmedi", "Fotoğraf ekle")

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
            self.title_label.setText("Fotoğraf yok" if not self.images else empty)
            self.btn_copy_name.setEnabled(False)
            self.pos_label.setText("")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.refresh_box_list()

    def _update_progress(self, labeled=None):
        if labeled is None:
            labeled = sum(1 for i in self.images if self.project.get_boxes(i))
        total = len(self.images)
        self.photo_count.setText(str(total))
        self.progress_label.setText(f"{labeled} / {total}")
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(labeled)

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
        fm = self.title_label.fontMetrics()
        self.title_label.setText(fm.elidedText(name, Qt.TextElideMode.ElideMiddle, 320))
        self.title_label.setToolTip(name)
        self.btn_copy_name.setEnabled(True)
        if self.browse:
            # etikete göre gezinme: sıra o etiketli fotoğraflar içinde
            names = [n for n, _ in self._photos_for(self.browse)]
            i = names.index(name) if name in names else -1
            self.pos_label.setText(f"{i + 1} / {len(names)}" if i >= 0 else f"– / {len(names)}")
            self.btn_browse.setText(f"{self._browse_label(self.browse)} filtresi")
            self.btn_prev.setEnabled(bool(names))
            self.btn_next.setEnabled(bool(names))
        else:
            row = self.image_list.currentRow()
            self.pos_label.setText(f"{row + 1} / {self.image_list.count()}")
            self.btn_prev.setEnabled(row > 0)
            self.btn_next.setEnabled(row < self.image_list.count() - 1)

    # ---------- fotoğraf adı: kopyala / ara ----------
    def _copy_text(self, text):
        QApplication.clipboard().setText(text)
        shown = text if "\n" not in text else f"{text.count(chr(10)) + 1} fotoğraf adı"
        self.statusBar().showMessage(f"Kopyalandı: {shown}", 3000)

    def copy_name(self):
        if self.current:
            self._copy_text(self.current)

    def _search_query(self):
        """Aranan metin (büyük / küçük harf fark etmez, kopyalarken gelen tırnak ve boşluklar atılır)."""
        return self.search.text().strip().strip("'\"").strip().lower()

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _search_enter(self):
        if self.image_list.count():
            self.image_list.setCurrentRow(0)
            self.image_list.scrollToItem(self.image_list.item(0))
        self.canvas.setFocus()

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
        a_copy = m.addAction("Adı kopyala" if len(names) == 1 else f"{len(names)} fotoğrafın adını kopyala")
        W.set_icon(a_copy, "copy")
        m.addSeparator()
        text = "🗑 Sil" if len(names) == 1 else f"🗑 Seçili {len(names)} fotoğrafı sil"
        a_del = m.addAction(text)
        chosen = m.exec(self.image_list.viewport().mapToGlobal(pos))
        if chosen == a_del:
            self.delete_images(names)
        elif chosen == a_copy:
            self._copy_text("\n".join(names))

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
        try:
            self.project.set_boxes(self.current, self.current_image.width(),
                                   self.current_image.height(), copy.deepcopy(self.boxes))
        except OSError as e:
            self._set_save_state(False, str(e))
            self.statusBar().showMessage(f"Kayıt başarısız: {e}", 8000)
        else:
            if not self.save_ok:
                self._set_save_state(True)
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
        self.statusBar().showMessage("İşlem geri alındı.", 3000)

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
        self.statusBar().showMessage(f"Kutu eklendi: {box_label(self.boxes[-1])}", 3000)

    def on_box_resized(self, i, x1, y1, x2, y2):
        """Kutunun kenarı / köşesi taşındı: etiketi aynı kalır, sadece yeri değişir."""
        if self.current is None or not (0 <= i < len(self.boxes)):
            return
        self._push_box_undo()
        b = self.boxes[i]
        b["x1"], b["y1"], b["x2"], b["y2"] = (round(v, 2) for v in (x1, y1, x2, y2))
        self._save()
        self.box_list.setCurrentRow(i)
        key = shortcuts.load_general(self.settings)["geri_al"]
        self.statusBar().showMessage(f"Kutu kenarı güncellendi: {box_label(b)}"
                                     + (f"  ({key}: geri al)" if key else ""), 3000)

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

    def _edit_box_row(self, i):
        self.box_list.setCurrentRow(i)
        self.edit_box(i)

    def _delete_box_row(self, i):
        self.box_list.setCurrentRow(i)
        self.delete_box(i)

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
        a_edit = m.addAction("Etiketi düzenle")
        W.set_icon(a_edit, "pencil")
        a_del = m.addAction("Kutuyu sil")
        W.set_icon(a_del, "trash-2")
        chosen = m.exec(pos)
        if chosen == a_edit:
            self.edit_box(i)
        elif chosen == a_del:
            self.delete_box(i)

    def refresh_box_list(self):
        self.box_list.blockSignals(True)
        self.box_list.clear()
        for b in self.boxes if self.project else []:
            it = QListWidgetItem(box_label(b))
            it.setData(Qt.ItemDataRole.UserRole, b)
            it.setToolTip(box_label(b) + "\nTıkla: seç · Çift tıkla: düzenle")
            self.box_list.addItem(it)
        self.box_list.blockSignals(False)
        self.canvas.set_selected(-1)
        n = self.box_list.count()
        # liste içeriği kadar uzasın (en fazla 5 satır), kalan yer istatistiğe kalsın
        self._size_box_list()
        self.box_count.setText(str(n) if self.current else "")
        self.box_count.setVisible(bool(self.current))
        self.box_list.setVisible(n > 0)
        self.box_empty.setVisible(n == 0)
        self.box_empty.setText("Bu fotoğrafta henüz etiket yok." if self.current else "Açık fotoğraf yok.")
        self._update_box_buttons()

    def _update_box_buttons(self):
        self.box_list.viewport().update()

    def _size_box_list(self):
        """Etiket listesi içeriği kadar uzasın (en fazla 5 satır), kalan yer istatistiğe kalsın."""
        n = self.box_list.count()
        self.box_list.setFixedHeight(min(max(n, 1), 5) * self.box_list.itemDelegate().row_h + 2)
        self._fit_timer.start()

    # ---------- sağ panel: önce sığdır, sığmazsa seçili etikete kaydır ----------
    def _set_compact(self, on):
        if on == self.panel_compact:
            return
        self.panel_compact = on
        self.stats_delegate.compact = on
        self.box_list.itemDelegate().compact = on
        self.card_boxes.set_compact(on)
        self.card_photos.set_compact(on)
        self.stats_summary.setVisible(not on)
        n = self.box_list.count()
        self.box_list.setFixedHeight(min(max(n, 1), 5) * self.box_list.itemDelegate().row_h + 2)
        self.box_list.doItemsLayout()
        self.stats_tree.doItemsLayout()

    def _stats_need(self):
        """İstatistik ağacının kaydırmadan sığması için gereken yükseklik."""
        need = 0
        stack = [self.stats_tree.topLevelItem(i) for i in range(self.stats_tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            need += self.stats_delegate.row_height(item.data(0, W.ROLE_KIND))
            if item.isExpanded():
                stack.extend(item.child(i) for i in range(item.childCount()))
        return need + 4

    def _fit_panel(self):
        if not self.project:
            return
        for compact in (False, True):
            self._set_compact(compact)
            self.right_panel.layout().activate()
            if self._stats_need() <= self.stats_tree.viewport().height():
                break
        if self._want_scroll:
            self._want_scroll = False
            self._scroll_to_active()

    def _scroll_to_active(self):
        """Kısayolla / sesle seçilen etiket görünmüyorsa istatistik oraya kayar."""
        items = self._stats_items()
        target = next((i for i in items if i.data(0, W.ROLE_STATE) in ("active", "pending")), None)
        if target is None:
            return
        tree = self.stats_tree
        cls_item = target
        while cls_item.parent():
            cls_item = cls_item.parent()
        if target is cls_item and cls_item.isExpanded() and cls_item.childCount():
            # sınıf seçildi, seçenek bekleniyor: kartın tamamı görünsün (sığmıyorsa başlığı)
            last = cls_item.child(cls_item.childCount() - 1)
            tree.scrollToItem(last, QAbstractItemView.ScrollHint.EnsureVisible)
            tree.scrollToItem(cls_item, QAbstractItemView.ScrollHint.EnsureVisible)
        else:
            tree.scrollToItem(target, QAbstractItemView.ScrollHint.EnsureVisible)

    def _refresh_current_list_item(self):
        it = self.image_list.currentItem()
        if it:
            it.setData(ROLE_COUNT, len(self.boxes))
        self._update_progress()

    # =================================================================
    #  İstatistik
    # =================================================================
    def refresh_stats(self):
        scroll = self.stats_tree.verticalScrollBar().value()
        self.stats_tree.clear()
        if not self.project:
            return
        st = self.project.stats()
        self.card_boxes.set_value(st["toplam_kutu"])
        self.card_photos.set_value(st["etiketli_resim"])
        n_all = len(self.images)
        self.stats_summary.setText(f"{n_all} fotoğrafın {st['etiketli_resim']} tanesi etiketli · "
                                   "fotoğraflar tekil sayılır")
        sel = self.sel
        self.stats_delegate.set_names(
            list(st["siniflar"]), [v for i in st["siniflar"].values() for cnt in i["attr"].values() for v in cnt])
        big = max([1] + [i["toplam"] for i in st["siniflar"].values()])
        big_photo = max([1] + [i["foto"] for i in st["siniflar"].values()])
        self.stats_delegate.count_digits = len(str(big))
        self.stats_delegate.photo_digits = len(str(big_photo))

        def row(kind, text, data, count=None, key="", dot=None, state=None, photos=None):
            it = QTreeWidgetItem([text])
            it.setData(0, W.ROLE_PHOTOS, photos)
            it.setData(0, Qt.ItemDataRole.UserRole, data)
            it.setData(0, W.ROLE_KIND, kind)
            it.setData(0, W.ROLE_COUNT, count)
            it.setData(0, W.ROLE_KBD, key or "")
            it.setData(0, W.ROLE_DOT, dot)
            it.setData(0, W.ROLE_STATE, state)
            return it

        for cls, info in st["siniflar"].items():
            total = info["toplam"]
            c = self.project.get_class(cls) or {}
            on = bool(sel and sel.cls == cls)
            top = row("class", cls, (cls, None, None), info["toplam"], c.get("kisayol", ""),
                      self.project.color(cls), "active" if on and not sel.attrs else None,
                      photos=info["foto"])
            top.setToolTip(0, f"{cls}\n{info['toplam']} etiket · {info['foto']} fotoğraf\nTıkla: aktif etiket yap")
            top.setData(0, W.ROLE_EXPANDABLE, bool(info["attr"]))
            if not info["attr"]:                     # seçeneksiz sınıf: fotoğraflar doğrudan altında
                self._make_photo_owner(top, (cls, None, None), info["toplam"])
            flat = len(info["attr"]) == 1            # tek özellik: seçenekler doğrudan sınıfın altında
            for attr, counts in info["attr"].items():
                a_def = self.project.get_attr(cls, attr) or {}
                keys = a_def.get("kisayollar", {})
                waiting = on and sel.pending == attr
                parent = top
                if not flat:
                    parent = row("attr", attr + ("  · tuşla seç" if waiting else ""), (cls, None, None),
                                 state="pending" if waiting else None)
                    top.addChild(parent)
                for val, n in counts.items():
                    n_photo = info["attr_foto"].get(attr, {}).get(val, 0)
                    chosen = on and sel.attrs.get(attr) == val
                    # tam tuş sırası: önce sınıfın tuşu, sonra seçeneğin (ör. 1 sonra 2)
                    cls_key, opt_key = c.get("kisayol", ""), keys.get(val, "")
                    v_item = row("option", val, (cls, attr, val), n,
                                 f"{cls_key}\t{opt_key}" if cls_key and opt_key else "",
                                 state="active" if chosen else ("zero" if n == 0 else None), photos=n_photo)
                    v_item.setData(0, W.ROLE_SHARE, n / total if total else 0)
                    v_item.setToolTip(0, f"{cls} › {val}\n{n} etiket · {n_photo} fotoğraf\nTıkla: aktif etiket yap")
                    self._make_photo_owner(v_item, (cls, attr, val), n)
                    parent.addChild(v_item)
            self.stats_tree.addTopLevelItem(top)
            if info["attr"] and cls not in self.stats_closed:
                top.setExpanded(True)
                for i in range(top.childCount()):
                    if top.child(i).data(0, W.ROLE_KIND) == "attr":
                        top.child(i).setExpanded(True)
        # fotoğraf listesi açık olanları geri aç (açılınca doldurulur)
        for item in self._stats_items():
            if item.data(0, ROLE_KEY) in self.stats_open:
                item.setExpanded(True)
        self._mark_current_photo(scroll=False)
        self.stats_tree.verticalScrollBar().setValue(scroll)
        if self.browse:
            self._update_title()
        self._fit_timer.start()

    def _on_stats_clicked(self, item, _col):
        kind = item.data(0, W.ROLE_KIND)
        if item.data(0, W.ROLE_EXPANDABLE):
            pos = self.stats_tree.viewport().mapFromGlobal(QCursor.pos())
            area = self.stats_delegate.chevron_rect(kind, self.stats_tree.visualItemRect(item))
            if area.contains(pos.toPointF()):
                item.setExpanded(not item.isExpanded())
                return
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
        item.setData(0, W.ROLE_EXPANDABLE, bool(n))
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
        self._fit_timer.start()
        if item.data(0, W.ROLE_KIND) == "class":
            self.stats_closed.discard(item.text(0))
        key = item.data(0, ROLE_KEY)
        if not key or not self.project:
            return
        self.stats_open.add(key)
        if item.childCount():
            return
        photos = self._photos_for(key)
        for name, n in photos:
            p = QTreeWidgetItem([name])
            p.setData(0, W.ROLE_KIND, "photo")
            p.setData(0, W.ROLE_COUNT, n)
            p.setData(0, ROLE_PHOTO, name)
            p.setToolTip(0, f"{name}\nTıkla: aç — A / D ile '{self._browse_label(key)}' fotoğraflarında gezin")
            item.addChild(p)
        if not photos:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        self._mark_current_photo(scroll=False)

    def _on_stats_collapsed(self, item):
        self._fit_timer.start()
        if item.data(0, W.ROLE_KIND) == "class" and not item.data(0, ROLE_KEY):
            self.stats_closed.add(item.text(0))
        key = item.data(0, ROLE_KEY)
        if key:
            self.stats_open.discard(key)
            if key == self.browse:
                self.end_browse()

    def _mark_current_photo(self, scroll=True):
        """İstatistikteki fotoğraf satırlarında açık olanı vurgular."""
        target = None
        for item in self._stats_items():
            name = item.data(0, ROLE_PHOTO)
            if name:
                on = name == self.current
                in_browse = on and item.parent().data(0, ROLE_KEY) == self.browse
                item.setData(0, W.ROLE_STATE, "browse" if in_browse else ("current" if on else None))
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
        if row is None and self.search.text():
            self.search.clear()
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
            "Bitirmek için üstteki filtrenin × düğmesine basın ya da oku kapatın.", 6000)

    def end_browse(self):
        if not self.browse:
            return
        self.browse = None
        self.btn_browse.hide()
        self._mark_current_photo(scroll=False)
        self._update_title()
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

    def open_stats(self):
        if self.project:
            StatsDialog(self.project, self).exec()

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
        only_crops = dlg.formats() == ["kirp"]
        text = f"{len(ex.images)} fotoğraf işlendi." if only_crops \
            else f"{len(ex.images)} fotoğraf dışa aktarıldı:\n{out}"
        if ex.notes:
            text += "\n\n" + "\n".join(ex.notes)
        if warnings:
            text += "\n\n" + "\n".join(warnings)
        box = QMessageBox(QMessageBox.Icon.Information, "Tamam", text, parent=self)
        crop_btn = None
        if ex.crop_count:
            crop_btn = box.addButton("Yeni projeyi aç", QMessageBox.ButtonRole.ActionRole)
        open_btn = box.addButton("Klasörü Aç", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Kapat", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if crop_btn is not None and box.clickedButton() == crop_btn:
            self.open_project(opts["crop_project"])
        elif box.clickedButton() == open_btn:
            os.startfile(opts["crop_project"] if only_crops else out)
