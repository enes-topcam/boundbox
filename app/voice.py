"""Sesle seçim: "mercimek çorbası" deyince corba → mercimek seçilir.

Tanıma Vosk ile internetsiz yapılır. Tanıyıcıya serbest konuşma yerine sadece
sınıf / seçenek adlarından çıkan kelimeler verilir (grammar); hem hızlı hem isabetli olur.
Modelin sözlüğünde olmayan kelimeler (ör. "ezogelin") sözlükteki parçalara bölünür
("ezo" + "gelin"); eşleştirme boşluklar atılarak yapıldığı için yine bulunur.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.request
import zipfile
from array import array
from collections import Counter, deque
from math import sqrt
from pathlib import Path

from PySide6.QtCore import QObject, Signal

MODEL_NAME = "vosk-model-small-tr-0.3"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_SIZE_MB = 37

MODES = [("baskonus", "Bas-konuş (tuşu basılı tutarken dinler)"),
         ("surekli", "Sürekli dinle")]


def missing_packages():
    """Eksik kütüphane varsa adlarını döner (boşsa ses kullanılabilir)."""
    out = []
    for mod in ("vosk", "sounddevice"):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001  (sounddevice PortAudio bulamazsa OSError verir)
            out.append(mod)
    return out


# =====================================================================
#  Model dosyaları
# =====================================================================
def _app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def user_model_dir():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Etiketleme" / "models"


def find_model():
    """Model klasörünü döner; yoksa None. Önce programın yanındaki models/ klasörüne bakar."""
    for d in (_app_dir() / "models", user_model_dir()):
        p = d / MODEL_NAME
        if (p / "final.mdl").exists() or (p / "am" / "final.mdl").exists():
            return p
    return None


def _native_path(p):
    """Vosk, Türkçe karakterli Windows yollarını açamayabiliyor; kısa (8.3) yola çevirir."""
    s = str(p)
    if os.name != "nt" or s.isascii():
        return s
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(s, buf, 1024):
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    return s


class ModelDownloader(QObject):
    progress = Signal(int, int)      # indirilen, toplam (bayt)
    finished = Signal(str)           # model klasörü
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.cancelled = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        dest = user_model_dir()
        tmp = dest / (MODEL_NAME + ".zip.part")
        try:
            dest.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Etiketleme"})
            with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while chunk := r.read(256 * 1024):
                    if self.cancelled:
                        raise InterruptedError
                    f.write(chunk)
                    done += len(chunk)
                    self.progress.emit(done, total)
            with zipfile.ZipFile(tmp) as z:
                root = dest.resolve()
                for name in z.namelist():           # zip dışına yazmaya çalışan girdileri reddet
                    if not (dest / name).resolve().is_relative_to(root):
                        raise ValueError(f"Geçersiz zip girdisi: {name}")
                z.extractall(dest)
            tmp.unlink(missing_ok=True)
            p = find_model()
            if not p:
                raise FileNotFoundError("Zip açıldı ama model dosyaları bulunamadı.")
            self.finished.emit(str(p))
        except InterruptedError:
            tmp.unlink(missing_ok=True)
            self.failed.emit("")
        except Exception as e:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            self.failed.emit(str(e))


# =====================================================================
#  Metin eşleştirme
# =====================================================================
_TR = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def tr_lower(s):
    return s.replace("I", "ı").replace("İ", "i").lower()


def norm(s):
    """'Çorbası' -> 'corbasi'. Karşılaştırmalar bu biçimde yapılır."""
    return re.sub(r"[^a-z0-9]", "", tr_lower(s).translate(_TR))


def _split_words(s):
    return [w for w in re.split(r"[\s_\-/.,;]+", tr_lower(s)) if w]


def _aliases(text):
    return [a.strip() for a in (text or "").split(",") if a.strip()]


class _Entry:
    __slots__ = ("kind", "cls", "attr", "val", "forms", "weak")

    def __init__(self, kind, cls, attr, val, forms):
        self.kind, self.cls, self.attr, self.val = kind, cls, attr, val
        self.forms = [f for f in dict.fromkeys(norm(x) for x in forms) if f]    # tam adlar
        self.weak = []                                                          # kısa söyleyişler


_STRIP = ("leri", "lari", "ler", "lar", "si", "su", "li", "lu", "i", "u")    # norm() edilmiş ekler


def _stem(f):
    """'kremali' -> 'krema', 'pilavi' -> 'pilav' (kök en az 4 harf kalmalı)."""
    return next((f[:-len(s)] for s in _STRIP if f.endswith(s) and len(f) - len(s) >= 4), None)


def _tolerance(f):
    """Tam adda kaç harf yanlışlığa izin verilir (kısa adlarda hiç)."""
    return 0 if len(f) < 5 else 1 if len(f) < 8 else 2


def _match(s, f, fuzzy):
    """Söylenen parça s, ad f'ye uyuyor mu? Uyuyorsa harf farkı (0, 1, 2), uymuyorsa None.

    Sona ek gelebilir ("çorba" ~ "çorbası", "mantar" ~ "mantarlı").
    """
    if s == f or (len(f) >= 3 and s.startswith(f) and len(s) - len(f) <= 4):
        return 0
    tol = _tolerance(f) if fuzzy else 0
    if not tol:
        return None
    best = tol + 1
    for k in range(0, 5):                         # k: sondaki ek uzunluğu
        if len(s) - k < len(f) - tol:
            break
        best = min(best, _lev(s[:len(s) - k] if k else s, f, tol))
    return best if best <= tol else None


class VoiceMatcher:
    def __init__(self, project):
        self.entries = []
        self._phrases = []
        all_names = []
        class_entry = {}
        for c in project.classes if project else []:
            names = [c["ad"]] + _aliases(c.get("sesli_ad"))
            e = _Entry("sinif", c["ad"], None, None, names)
            class_entry[c["ad"]] = e
            self.entries.append(e)
            all_names.append(names)
            for a in c["attributeler"]:
                for v in a["secenekler"]:
                    names = [v] + _aliases(a.get("sesli_adlar", {}).get(v))
                    self.entries.append(_Entry("secenek", c["ad"], a["ad"], v, names))
                    all_names.append(names)
        for names in all_names:
            self._phrases += names

        # Kısa söyleyişler:
        #  - çok kelimeli adın bir kelimesi: "kremali_sebze" -> "kremalı" / "sebze", "yan_urun" -> "yan"
        #  - kökler: "kremalı" ~ "krema", "kreması"
        #  - bitişik yazılmış uzun adın sonu: "cigkofte" -> "köfte"
        # Tek bir seçeneğe aitse o seçeneği seçer. Aynı sınıfın birden çok seçeneğinde geçiyorsa
        # ("pilav": pirinç / bulgur pilavı) sınıfı seçer, türü sonra sorulur.
        weak = []
        for e, names in zip(self.entries, all_names):
            ws = set()
            for n in names:
                parts = [norm(p) for p in _split_words(n)]
                parts = [p for p in parts if p]
                if len(parts) > 1:
                    ws.update(p for p in parts if len(p) >= 3)
                elif parts and len(parts[0]) >= 7:
                    w = parts[0]
                    ws.update(w[i:] for i in range(2, len(w) - 4))
                for p in parts + ["".join(parts)]:
                    if st := _stem(p):
                        ws.add(st)
            weak.append(ws - set(e.forms))
        strong = {f for e in self.entries for f in e.forms}
        owners = {}
        for e, ws in zip(self.entries, weak):
            for w in ws:
                owners.setdefault(w, []).append(e)
        for w, es in owners.items():
            if w in strong:
                continue
            if len(es) == 1:
                es[0].weak.append(w)
            elif len({x.cls for x in es}) == 1 and es[0].cls in class_entry:
                ce = class_entry[es[0].cls]
                if w not in ce.weak:
                    ce.weak.append(w)

    def phrases(self):
        """Tanıyıcının bilmesi gereken adlar (sınıflar, seçenekler, sesli adlar)."""
        return list(dict.fromkeys(self._phrases))

    def _find(self, text):
        toks = [t for t in (norm(w) for w in _split_words(text)) if t]
        cands = []
        for si in range(len(toks)):
            for sj in range(si + 1, min(len(toks), si + 3) + 1):     # 1-3 kelime birlikte ("yan ürün")
                s = "".join(toks[si:sj])
                for e in self.entries:
                    for f, fuzzy in [(f, True) for f in e.forms] + [(f, False) for f in e.weak]:
                        d = _match(s, f, fuzzy)
                        if d is not None:
                            cands.append((len(f) - 2 * d + (1 if fuzzy else 0), si, sj, e))
        cands.sort(key=lambda c: (-c[0], c[1]))
        chosen, used = [], {}              # used: (si, sj) -> puan
        for score, si, sj, e in cands:
            if any(e is x for _, x in chosen):
                continue
            same = used.get((si, sj)) == score     # aynı ad birden çok sınıfta olabilir ("diğer")
            if same or all(sj <= a or si >= b for a, b in used):
                chosen.append((si, e))
                used.setdefault((si, sj), score)
        return [e for _, e in sorted(chosen, key=lambda c: c[0])]

    def resolve(self, text, cur_cls=None, cur_attrs=None):
        """Söyleneni seçime çevirir.

        Dönüş: (sinif, attrs) | ("?", [aday sınıflar]) belirsizse | None hiçbir şey bulunamadıysa.
        """
        found = self._find(text)
        if not found:
            return None
        classes = [e.cls for e in found if e.kind == "sinif"]
        opts = [e for e in found if e.kind == "secenek"]
        if classes:
            cls = next((c for c in reversed(classes) if any(o.cls == c for o in opts)), classes[-1])
        else:
            counts = Counter(o.cls for o in opts)
            best = max(counts.values())
            top = [c for c, n in counts.items() if n == best]
            if cur_cls in top:
                cls = cur_cls
            elif len(top) == 1:
                cls = top[0]
            else:
                return "?", top
        mine = [o for o in opts if o.cls == cls]
        attrs = dict(cur_attrs or {}) if (mine and cls == cur_cls) else {}
        for o in mine:
            attrs[o.attr] = o.val
        return cls, attrs


# =====================================================================
#  Tanıyıcı kelime listesi (grammar)
# =====================================================================
_ASCII_TO_TR = {"c": "ç", "g": "ğ", "i": "ı", "o": "ö", "s": "ş", "u": "ü"}
_SUFFIXES = ("sı", "si", "su", "sü", "ı", "i", "u", "ü", "lı", "li", "lu", "lü",
             "lar", "ler", "ları", "leri", "da", "de", "dan", "den")


def _variants(w, limit=8):
    """'corba' -> 'corba', 'çorba', 'corbâ'... (ASCII yazılmış Türkçe kelimeler için)."""
    pos = [i for i, ch in enumerate(w) if ch in _ASCII_TO_TR][:limit]
    out = []
    for mask in range(1 << len(pos)):
        chars = list(w)
        for bit, i in enumerate(pos):
            if mask >> bit & 1:
                chars[i] = _ASCII_TO_TR[chars[i]]
        out.append("".join(chars))
    return out


def _in_vocab(model, w):
    return model.vosk_model_find_word(w) >= 0


def _forms(model, w):
    found = [v for v in _variants(w) if _in_vocab(model, v)]
    out = set()
    if not found:
        # sözlükte yoksa: kökünü dene ('kremalı' yok ama 'krema', 'kreması' var), parçalara da böl
        out = _pieces(model, w)
        n = norm(w)
        for s in _STRIP:
            if n.endswith(s) and len(n) - len(s) >= 3:
                found = [v for v in _variants(w[:-len(s)]) if _in_vocab(model, v)]
                if found:
                    break
    out.update(found)
    for f in list(found or out):           # parçalara da ek: "köfte" -> "köftesi", "köfteli"
        out.update(f + s for s in _SUFFIXES if _in_vocab(model, f + s))
    return out


def load_vocab(model_path):
    """Modelin kelime listesi (Gr.fst içindeki OpenFst sembol tablosu). Okunamazsa boş liste."""
    import struct
    try:
        b = (Path(model_path) / "Gr.fst").read_bytes()
        i = b.find(b"\x74\xfb\xb2\x7e", 4)            # sembol tablosu başlangıcı (magic)
        if i < 0:
            return []
        i += 4
        n = struct.unpack_from("<i", b, i)[0]
        i += 4 + n + 8                                 # ad, available_key
        size = struct.unpack_from("<q", b, i)[0]
        i += 8
        if not 0 < size < 5_000_000:
            return []
        words = []
        for _ in range(size):
            n = struct.unpack_from("<i", b, i)[0]
            words.append(b[i + 4:i + 4 + n].decode("utf-8", "replace"))
            i += 4 + n + 8
        return [w for w in words if w and w[0] not in "<#"]
    except Exception:  # noqa: BLE001
        return []


class VocabIndex:
    """Sözlükte olmayan kelimeye yazılışça en yakın sözlük kelimelerini bulur.

    'kremalı' sözlükte yok; tanıyıcı o sesi 'klimalı' / 'romalı' gibi kelimelere benzetiyor.
    Bu kelimeler listeye eklenir ve duyulunca asıl ada çevrilir.
    """

    def __init__(self, words):
        self.by_len = {}
        for w in words:
            n = norm(w)
            if n:
                self.by_len.setdefault(len(n), []).append((w, n))

    def near(self, w, count=4):
        n = norm(w)
        if len(n) < 4:
            return []
        maxd = 1 if len(n) <= 5 else 2
        hits = []
        for ln in range(len(n) - maxd, len(n) + maxd + 1):
            for word, wn in self.by_len.get(ln, ()):
                if wn[-2:] != n[-2:] and wn[:2] != n[:2]:      # başı ya da sonu benzemeli
                    continue
                d = _lev(n, wn, maxd)
                if d <= maxd:
                    common = next((k for k in range(min(len(n), len(wn)), 0, -1) if n[-k:] == wn[-k:]), 0)
                    hits.append((d, -common, word))
        hits.sort()
        return list(dict.fromkeys(h[2] for h in hits))[:count]


def _lev(a, b, maxd):
    """Levenshtein uzaklığı; maxd'yi geçince erken bırakır."""
    if abs(len(a) - len(b)) > maxd:
        return maxd + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > maxd:
            return maxd + 1
        prev = cur
    return prev[-1]


def _pieces(model, w):
    """Sözlükte olmayan kelimeyi sözlükteki en az sayıda parçaya böler ('ezogelin' -> ezo + gelin)."""
    n = len(w)
    best = [None] * (n + 1)          # best[i] = w[:i] için parça listesi
    best[0] = []
    for j in range(1, n + 1):
        for i in range(j):
            if best[i] is None or (j - i < 2 and n > 1):
                continue
            hit = next((v for v in _variants(w[i:j], 6) if _in_vocab(model, v)), None)
            if hit and (best[j] is None or len(best[i]) + 1 < len(best[j])):
                best[j] = best[i] + [hit]
    return set(best[n] or [])


# Sık kullanılan kelimeler. Tanıyıcı sadece bizim adlarımızı bilirse alakasız konuşmayı da onlara
# benzetir ("merhaba nasılsın" -> "mercimek"). Bunlar listede olunca alakasız konuşma bunlara oturur,
# eşleştirme de bunları yok sayar.
FILLERS = """
    ve bir bu da de ne o ben sen biz siz onlar şu için ile gibi çok daha en var yok değil mi mı mu mü
    ama fakat ki ya evet hayır tamam peki olur oldu olsun şimdi sonra önce bugün yarın dün akşam sabah
    öğle gece hafta ay yıl saat dakika zaman iş işte burada orada nerede neden nasıl kim hangi kaç biraz
    hep hiç her bazı başka aynı yeni eski büyük küçük güzel iyi kötü doğru yanlış hızlı yavaş sıcak
    soğuk merhaba selam günaydın hoşça kal teşekkürler teşekkür ederim lütfen pardon tabii bence galiba
    belki aslında yani şey falan filan hadi gel git gidiyorum geliyorum yap yapalım yaptım bak baktım
    gör gördüm söyle söyledim dedi diyor bil bilmiyorum biliyorum anladım anlamadım istiyorum
    istemiyorum olmaz oluyor nasılsın iyiyim kardeşim abi abla hocam arkadaş anne baba ev okul araba yol
    para telefon bilgisayar fotoğraf resim kutu etiket dosya klasör program sonraki önceki sil kaydet aç
    kapat çık geç dur bekle başla bitti toplantı pazartesi salı çarşamba perşembe cuma cumartesi pazar
    ocak şubat mart nisan mayıs haziran temmuz ağustos eylül ekim kasım aralık iki üç dört beş altı yedi
    sekiz dokuz on yirmi otuz kırk elli yüz bin su çay kahve ekmek yemek yiyelim içelim yorgun yorgunum
    hava koy koyar buraya şuraya oraya kahvaltı yemeği tatlı tuz şeker
""".split()


def grammar_words(model, phrases, vocab=None):
    """Tanıyıcıya verilecek kelimeler ve geri çevirme tablosu.

    Dönüş: (kelimeler, {benzer_kelime: asıl_kelime}). Tanıyıcı 'klimalı' duyarsa 'kremali' yapılır.
    """
    words, alias = set(), {}
    oov = []
    for ph in phrases:
        for w in _split_words(ph):
            if not any(_in_vocab(model, v) for v in _variants(w)):
                oov.append(w)
            words |= _forms(model, w)
    forms = {norm(ph) for ph in phrases} | {norm(w) for ph in phrases for w in _split_words(ph)}
    forms = [f for f in forms | {_stem(f) for f in forms} if f and len(f) >= 3]

    def ours(w):          # bizim adlarımızdan birine benziyor mu (dolgu / benzer kelime olamaz)
        n = norm(w)
        return any(n.startswith(f) or f.startswith(n) for f in forms)

    fillers = {w for w in FILLERS if _in_vocab(model, w) and not ours(w)}
    if vocab and oov:
        taken = words | fillers
        for w in dict.fromkeys(oov):
            for near in vocab.near(w):
                if near in taken or near in alias:
                    continue
                if ours(near):          # "çiğköftem": zaten bizim ada benziyor, çevirmeye gerek yok
                    words.add(near)
                else:                   # "temalı" -> "kremali"
                    alias[near] = w
    return sorted(words) + sorted(fillers - words) + sorted(alias), alias


# =====================================================================
#  Mikrofon + tanıma (arka plan iş parçacığı)
# =====================================================================
BLOCK_SEC = 0.1
PREROLL_BLOCKS = 3         # bas-konuşta tuşa basmadan önceki 0.3 sn de dinlensin (ilk hece kesilmesin)
TAIL_SEC = 0.3             # tuş bırakıldıktan sonra biraz daha dinle (son hece kesilmesin)


class VoiceEngine(QObject):
    stateChanged = Signal(str)      # "yukleniyor" | "hazir" | "kapali" | "hata"
    speaking = Signal(bool)         # sürekli modda ses algılanıyor mu
    partial = Signal(str)
    heard = Signal(str)             # tamamlanan cümle ("" = bir şey anlaşılamadı)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.mode = "baskonus"
        self.device = None
        self._model = None
        self._model_path = None
        self._thread = None
        self._old_thread = None
        self._stop = threading.Event()
        self._gen = 0
        self._lock = threading.Lock()
        self._phrases = []
        self._dirty = True
        self._gcache = {}
        self._vocab = None
        self._alias = {}
        self._ptt = False
        self._ptt_end = None

    @property
    def running(self):
        return self._thread is not None

    # ---------- ana iş parçacığından çağrılır ----------
    def start(self, model_path, device=None):
        if self.running:
            return
        self._gen += 1
        self._stop = threading.Event()
        self.device = device
        self._ptt = False
        self._ptt_end = None
        self._thread = threading.Thread(target=self._run, args=(self._gen, self._stop, str(model_path)),
                                        daemon=True)
        self._thread.start()

    def stop(self):
        t, self._thread = self._thread, None
        self._stop.set()
        self._gen += 1                   # eski iş parçacığının sinyalleri yok sayılsın
        if t:
            t.join(timeout=1.0)
        self._old_thread = t

    def refresh_devices(self):
        """Sonradan takılan mikrofonlar da listelensin diye ses sürücüsünü yeniden başlatır.
        Sadece dinleme kapalıyken yapılabilir; yapılamadıysa False döner."""
        if self.running or (self._old_thread and self._old_thread.is_alive()):
            return False
        try:
            import sounddevice as sd
            sd._terminate()
            sd._initialize()
        except Exception:  # noqa: BLE001
            return False
        return True

    def set_phrases(self, phrases):
        with self._lock:
            self._phrases = list(phrases)
            self._dirty = True

    def set_mode(self, mode):
        self.mode = mode
        self._ptt = False
        self._ptt_end = None
        self._dirty = True

    def ptt_press(self):
        self._ptt_end = None
        self._ptt = True

    def ptt_release(self):
        if self._ptt and self._ptt_end is None:
            self._ptt_end = time.monotonic() + TAIL_SEC

    # ---------- arka plan ----------
    def _run(self, gen, stop, model_path):
        def emit(sig, *a):
            if gen == self._gen:
                sig.emit(*a)

        try:
            import sounddevice as sd
            import vosk
            vosk.SetLogLevel(-1)
            if self._model is None or self._model_path != model_path:
                emit(self.stateChanged, "yukleniyor")
                self._model = vosk.Model(_native_path(model_path))
                self._model_path = model_path
                self._vocab = VocabIndex(load_vocab(model_path))
                self._gcache = {}
            if stop.is_set():
                return
            stream, rate = self._open_stream(sd)
        except Exception as e:  # noqa: BLE001
            emit(self.error, str(e) or e.__class__.__name__)
            emit(self.stateChanged, "hata")
            return

        rec, mode, feeding = None, None, False
        preroll = deque(maxlen=PREROLL_BLOCKS)
        last_partial, speaking, hold, noise = "", False, 0, 300.0
        frames = int(rate * BLOCK_SEC)
        emit(self.stateChanged, "hazir")
        try:
            with stream:
                while not stop.is_set():
                    data = bytes(stream.read(frames)[0])
                    if rec is None or self._dirty:
                        with self._lock:
                            phrases, self._dirty = tuple(self._phrases), False
                        rec = self._recognizer(vosk, rate, phrases)
                        mode, feeding, last_partial = self.mode, False, ""
                        preroll.clear()

                    if mode == "surekli":
                        # konuşma algılama (simge yeşile dönsün diye)
                        s = array("h", data)
                        rms = sqrt(sum(x * x for x in s) / len(s)) if s else 0
                        loud = rms > max(350.0, noise * 2.5)
                        if not loud:
                            noise = noise * 0.95 + rms * 0.05
                        hold = 4 if loud else max(0, hold - 1)
                        if (hold > 0) != speaking:
                            speaking = hold > 0
                            emit(self.speaking, speaking)

                        if rec.AcceptWaveform(data):
                            text = self._clean(json.loads(rec.Result()).get("text", ""))
                            last_partial = ""
                            if text:
                                emit(self.heard, text)
                        else:
                            p = self._clean(json.loads(rec.PartialResult()).get("partial", ""))
                            if p != last_partial:
                                last_partial = p
                                emit(self.partial, p)
                    else:
                        if not self._ptt:
                            preroll.append(data)
                            continue
                        if not feeding:
                            feeding = True
                            for b in preroll:
                                rec.AcceptWaveform(b)
                            preroll.clear()
                        rec.AcceptWaveform(data)
                        p = self._clean(json.loads(rec.PartialResult()).get("partial", ""))
                        if p != last_partial:
                            last_partial = p
                            emit(self.partial, p)
                        if self._ptt_end is not None and time.monotonic() >= self._ptt_end:
                            self._ptt, self._ptt_end = False, None
                            feeding, last_partial = False, ""
                            emit(self.heard, self._clean(json.loads(rec.FinalResult()).get("text", "")))
        except Exception as e:  # noqa: BLE001
            emit(self.error, str(e) or e.__class__.__name__)
            emit(self.stateChanged, "hata")
            return
        emit(self.stateChanged, "kapali")

    def _open_stream(self, sd):
        rates = [16000]
        try:
            rates.append(int(sd.query_devices(self.device, "input")["default_samplerate"]))
        except Exception:  # noqa: BLE001
            pass
        err = None
        for rate in rates:
            try:
                s = sd.RawInputStream(samplerate=rate, blocksize=int(rate * BLOCK_SEC), device=self.device,
                                      dtype="int16", channels=1)
                return s, rate
            except Exception as e:  # noqa: BLE001
                err = e
        raise err

    def _recognizer(self, vosk, rate, phrases):
        if phrases not in self._gcache:
            self._gcache[phrases] = grammar_words(self._model, phrases, self._vocab)
        words, self._alias = self._gcache[phrases]
        if not words:
            return vosk.KaldiRecognizer(self._model, rate)
        return vosk.KaldiRecognizer(self._model, rate, json.dumps(words + ["[unk]"], ensure_ascii=False))

    def _clean(self, text):
        return " ".join(self._alias.get(w, w) for w in text.split() if w != "[unk]")


# Windows'un "varsayılanı kullan" girişi; listede zaten "Varsayılan" seçeneği var.
_MAPPER_NAMES = ("microsoft sound mapper", "microsoft ses eşleştiricisi")


def input_devices():
    """[(index, ad)] — varsayılan ses sürücüsündeki mikrofonlar (aynı cihaz birkaç kez listelenmesin)."""
    try:
        import sounddevice as sd
        api = sd.default.hostapi
        return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0 and d["hostapi"] == api
                and not d["name"].lower().startswith(_MAPPER_NAMES)]
    except Exception:  # noqa: BLE001
        return []
