"""Genel (projeden bağımsız) kısayollar. Kullanıcının bilgisayarında saklanır."""
from PySide6.QtGui import QKeySequence

# (anahtar, açıklama, varsayılan tuş)
GENERAL = [
    ("onceki", "Önceki fotoğraf", "A"),
    ("sonraki", "Sonraki fotoğraf", "D"),
    ("sigdir", "Sığdır (fit)", "F"),
    ("foto_sil", "Fotoğrafı sil", "Ctrl+Del"),
    ("kutu_sil", "Seçili kutuyu sil", "Del"),
    ("geri_al", "Geri al", "Ctrl+Z"),
    ("iptal", "Çizimi iptal et", "Esc"),
    ("sifirla", "Seçimi sıfırla (hiçbir şey seçili olmasın)", "X"),
    ("disa_aktar", "Dışa aktar", "Ctrl+E"),
    ("istatistik", "İstatistik penceresi", "Ctrl+I"),
    ("ara", "Fotoğraf ara (soldaki arama kutusu)", "Ctrl+F"),
    ("ad_kopyala", "Açık fotoğrafın adını kopyala", "Ctrl+Shift+C"),
    ("yenile", "Yenile", "F5"),
    ("ses_ac_kapat", "Mikrofonu aç / kapat (sesle seçim)", "M"),
    ("ses_baskonus", "Bas-konuş tuşu (basılı tutarken konuş)", "Space"),
]


# kutu kenarını düzenlemek için basılı tutulan tuş (ayarlardan değişir)
EDIT_MODIFIERS = ["Shift", "Ctrl", "Alt"]
EDIT_MODIFIER_DEFAULT = "Shift"


def load_edit_modifier(settings) -> str:
    v = settings.value("kisayol/kutu_duzenle_tus", EDIT_MODIFIER_DEFAULT)
    return v if v in EDIT_MODIFIERS else EDIT_MODIFIER_DEFAULT


def save_edit_modifier(settings, name: str):
    settings.setValue("kisayol/kutu_duzenle_tus", name if name in EDIT_MODIFIERS else EDIT_MODIFIER_DEFAULT)


def norm(key: str) -> str:
    """Tuş metnini standart biçime çevirir ('ctrl+delete' -> 'Ctrl+Del')."""
    if not key:
        return ""
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)


def load_general(settings) -> dict:
    return {k: norm(settings.value(f"kisayol/{k}", default)) for k, _, default in GENERAL}


def save_general(settings, keys: dict):
    for k, _, _ in GENERAL:
        settings.setValue(f"kisayol/{k}", keys.get(k, ""))


def label_for(key: str) -> str:
    return f"  (Kısayol: {key})" if key else ""
