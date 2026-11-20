"""Proje modeli: sınıflar / attribute'ler / seçenekler ve resim etiketleri.

Ortak klasör yapısı:
    <proje>/
        proje.json        -> sınıf tanımları
        images/           -> resimler
        annotations/      -> her resim için bir .json (otomatik kayıt)
        export/           -> dışa aktarımlar
        .cop/             -> silinen resimler (geri alınabilsin diye)
"""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
    "#f032e6", "#9a6324", "#469990", "#800000", "#808000", "#000075",
]


def clean_name(text: str) -> str:
    """Boşlukları alt çizgiye çevirir (XML/YOLO uyumu için)."""
    return "_".join(text.strip().split())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class Project:
    FILE = "proje.json"

    def __init__(self, root):
        self.root = Path(root)
        self.classes = []       # [{"ad", "renk", "attributeler": [{"ad", "secenekler": []}]}]
        self.annotations = {}   # resim adı -> {"genislik", "yukseklik", "kutular": [...]}

    # ---------- klasörler ----------
    @property
    def name(self):
        return self.root.name

    @property
    def images_dir(self):
        return self.root / "images"

    @property
    def ann_dir(self):
        return self.root / "annotations"

    @property
    def export_dir(self):
        return self.root / "export"

    @property
    def trash_dir(self):
        return self.root / ".cop"

    # ---------- aç / oluştur / kaydet ----------
    @staticmethod
    def is_project(root) -> bool:
        return (Path(root) / Project.FILE).exists()

    @classmethod
    def open_or_create(cls, root):
        p = cls(root)
        for d in (p.images_dir, p.ann_dir, p.export_dir):
            d.mkdir(parents=True, exist_ok=True)
        if cls.is_project(root):
            with open(p.root / cls.FILE, encoding="utf-8") as f:
                data = json.load(f)
            p.classes = data.get("siniflar", [])
            for i, c in enumerate(p.classes):
                c.setdefault("kisayol", str(i + 1) if i < 9 else "")
                for a in c["attributeler"]:
                    keys = a.setdefault("kisayollar", {})
                    for j, v in enumerate(a["secenekler"]):
                        if v not in keys:          # hiç atanmamışsa sırayla 1, 2, 3 ...
                            keys[v] = str(j + 1) if j < 9 else ""
        else:
            p.save()
        p.load_annotations()
        return p

    def save(self):
        write_json(self.root / self.FILE, {"proje_adi": self.name, "siniflar": self.classes})

    def load_annotations(self):
        self.annotations = {}
        for f in self.ann_dir.glob("*.json"):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.annotations[data["resim"]] = data
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    # ---------- resimler ----------
    def list_images(self):
        return sorted(
            p.name for p in self.images_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        )

    def image_path(self, name) -> Path:
        return self.images_dir / name

    def importable(self, paths):
        """Eklenebilecek resim dosyalarını süzer (proje klasörünün içindekiler hariç)."""
        result = []
        for src in map(Path, paths):
            if src.suffix.lower() in IMAGE_EXTS and src.is_file() \
                    and src.parent.resolve() != self.images_dir.resolve():
                result.append(src)
        return result

    def add_image(self, src, replace=False) -> str:
        """Tek resmi ortak klasöre kopyalar.
        replace=True: aynı isimli resmin üstüne yazar (etiketleri korunur).
        replace=False: isim doluysa _1, _2 ... ekler."""
        src = Path(src)
        dst = self.images_dir / src.name
        if not replace:
            i = 1
            while dst.exists():
                dst = self.images_dir / f"{src.stem}_{i}{src.suffix}"
                i += 1
        shutil.copy2(src, dst)
        return dst.name

    def add_images(self, paths) -> int:
        """Çakışmaları sormadan ekler (aynı isim varsa yeni isim verir)."""
        files = self.importable(paths)
        for src in files:
            self.add_image(src)
        return len(files)

    def delete_images(self, names):
        """Resimleri (ve etiketlerini) .cop klasörüne taşır. Geri almak için token listesi döner."""
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        tokens = []
        for name in names:
            src = self.image_path(name)
            if not src.exists():
                continue
            stamp = time.time_ns()
            img_dst = self.trash_dir / f"{stamp}__{name}"
            shutil.move(str(src), str(img_dst))
            ann_dst = None
            ann_src = self._ann_path(name)
            if ann_src.exists():
                ann_dst = self.trash_dir / f"{stamp}__{name}.json"
                shutil.move(str(ann_src), str(ann_dst))
            self.annotations.pop(name, None)
            tokens.append({"resim": name, "resim_yol": str(img_dst),
                           "etiket_yol": str(ann_dst) if ann_dst else None})
        return tokens

    def restore_images(self, tokens):
        """delete_images'in tersi. Geri gelen resim adlarını döner."""
        restored = []
        for t in tokens:
            src = Path(t["resim_yol"])
            if not src.exists():
                continue
            name = t["resim"]
            dst = self.image_path(name)
            i = 1
            while dst.exists():
                stem, ext = os.path.splitext(t["resim"])
                name = f"{stem}_{i}{ext}"
                dst = self.image_path(name)
                i += 1
            shutil.move(str(src), str(dst))
            if t["etiket_yol"] and Path(t["etiket_yol"]).exists():
                with open(t["etiket_yol"], encoding="utf-8") as f:
                    data = json.load(f)
                Path(t["etiket_yol"]).unlink()
                self.set_boxes(name, data["genislik"], data["yukseklik"], data["kutular"])
            restored.append(name)
        return restored

    def trash_count(self):
        if not self.trash_dir.exists():
            return 0
        return sum(1 for f in self.trash_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS)

    def empty_trash(self):
        shutil.rmtree(self.trash_dir, ignore_errors=True)

    # ---------- etiketler ----------
    def _ann_path(self, image) -> Path:
        return self.ann_dir / (image + ".json")

    def get_boxes(self, image):
        return self.annotations.get(image, {}).get("kutular", [])

    def set_boxes(self, image, width, height, boxes):
        """Resmin kutularını kaydeder (boşsa dosyayı siler)."""
        path = self._ann_path(image)
        if not boxes:
            self.annotations.pop(image, None)
            if path.exists():
                path.unlink()
            return
        data = {"resim": image, "genislik": width, "yukseklik": height, "kutular": boxes}
        self.annotations[image] = data
        write_json(path, data)

    def _rewrite_boxes(self, fn) -> int:
        """Tüm kutulara fn(kutu) uygular; fn None dönerse kutu silinir. Değişen kutu sayısını döner."""
        changed = 0
        for image, data in list(self.annotations.items()):
            new_boxes, dirty = [], False
            for b in data["kutular"]:
                before = json.dumps(b, sort_keys=True)
                nb = fn(dict(b, attributeler=dict(b.get("attributeler", {}))))
                if nb is None or json.dumps(nb, sort_keys=True) != before:
                    dirty = True
                    changed += 1
                if nb is not None:
                    new_boxes.append(nb)
            if dirty:
                self.set_boxes(image, data["genislik"], data["yukseklik"], new_boxes)
        return changed

    # ---------- sınıf tanımları ----------
    def class_names(self):
        return [c["ad"] for c in self.classes]

    def get_class(self, name):
        return next((c for c in self.classes if c["ad"] == name), None)

    def get_attr(self, cls_name, attr_name):
        c = self.get_class(cls_name)
        if not c:
            return None
        return next((a for a in c["attributeler"] if a["ad"] == attr_name), None)

    def color(self, cls_name):
        c = self.get_class(cls_name)
        return c["renk"] if c else "#ffffff"

    def add_class(self, name, color=None):
        name = clean_name(name)
        if not name or self.get_class(name):
            return False
        color = color or PALETTE[len(self.classes) % len(PALETTE)]
        used = {c.get("kisayol") for c in self.classes}
        key = next((str(d) for d in range(1, 10) if str(d) not in used), "")
        self.classes.append({"ad": name, "renk": color, "kisayol": key, "attributeler": []})
        self.save()
        return True

    def add_attribute(self, cls_name, name):
        name = clean_name(name)
        c = self.get_class(cls_name)
        if not c or not name or self.get_attr(cls_name, name):
            return False
        c["attributeler"].append({"ad": name, "secenekler": [], "kisayollar": {}})
        self.save()
        return True

    def add_option(self, cls_name, attr_name, value):
        value = clean_name(value)
        a = self.get_attr(cls_name, attr_name)
        if not a or not value or value in a["secenekler"]:
            return False
        a["secenekler"].append(value)
        keys = a.setdefault("kisayollar", {})
        used = set(keys.values())
        keys[value] = next((str(d) for d in range(1, 10) if str(d) not in used), "")
        self.save()
        return True

    # kullanım sayıları (silmeden önce uyarı için)
    def count_class(self, cls_name):
        return sum(1 for d in self.annotations.values() for b in d["kutular"] if b["sinif"] == cls_name)

    def count_option(self, cls_name, attr_name, value):
        return sum(
            1 for d in self.annotations.values() for b in d["kutular"]
            if b["sinif"] == cls_name and b.get("attributeler", {}).get(attr_name) == value
        )

    def remove_class(self, cls_name):
        self.classes = [c for c in self.classes if c["ad"] != cls_name]
        self.save()
        self._rewrite_boxes(lambda b: None if b["sinif"] == cls_name else b)

    def remove_attribute(self, cls_name, attr_name):
        c = self.get_class(cls_name)
        c["attributeler"] = [a for a in c["attributeler"] if a["ad"] != attr_name]
        self.save()

        def fn(b):
            if b["sinif"] == cls_name:
                b["attributeler"].pop(attr_name, None)
            return b
        self._rewrite_boxes(fn)

    def remove_option(self, cls_name, attr_name, value):
        a = self.get_attr(cls_name, attr_name)
        a["secenekler"] = [v for v in a["secenekler"] if v != value]
        a.setdefault("kisayollar", {}).pop(value, None)
        self.save()

        def fn(b):
            if b["sinif"] == cls_name and b["attributeler"].get(attr_name) == value:
                b["attributeler"].pop(attr_name)
            return b
        self._rewrite_boxes(fn)

    def rename_class(self, old, new):
        new = clean_name(new)
        if not new or self.get_class(new):
            return False
        self.get_class(old)["ad"] = new
        self.save()

        def fn(b):
            if b["sinif"] == old:
                b["sinif"] = new
            return b
        self._rewrite_boxes(fn)
        return True

    def rename_attribute(self, cls_name, old, new):
        new = clean_name(new)
        if not new or self.get_attr(cls_name, new):
            return False
        self.get_attr(cls_name, old)["ad"] = new
        self.save()

        def fn(b):
            if b["sinif"] == cls_name and old in b["attributeler"]:
                b["attributeler"][new] = b["attributeler"].pop(old)
            return b
        self._rewrite_boxes(fn)
        return True

    def rename_option(self, cls_name, attr_name, old, new):
        new = clean_name(new)
        a = self.get_attr(cls_name, attr_name)
        if not new or new in a["secenekler"]:
            return False
        a["secenekler"][a["secenekler"].index(old)] = new
        keys = a.setdefault("kisayollar", {})
        if old in keys:
            keys[new] = keys.pop(old)
        self.save()

        def fn(b):
            if b["sinif"] == cls_name and b["attributeler"].get(attr_name) == old:
                b["attributeler"][attr_name] = new
            return b
        self._rewrite_boxes(fn)
        return True

    def set_class_color(self, cls_name, color):
        self.get_class(cls_name)["renk"] = color
        self.save()

    # ---------- istatistik ----------
    def stats(self):
        """{"toplam_kutu", "etiketli_resim", "siniflar": {sinif: {"toplam", "attr": {attr: {secenek: n}}}}}"""
        result = {"toplam_kutu": 0, "etiketli_resim": len(self.annotations), "siniflar": {}}
        for c in self.classes:
            result["siniflar"][c["ad"]] = {
                "toplam": 0,
                "attr": {a["ad"]: {v: 0 for v in a["secenekler"]} for a in c["attributeler"]},
            }
        for data in self.annotations.values():
            for b in data["kutular"]:
                result["toplam_kutu"] += 1
                s = result["siniflar"].setdefault(b["sinif"], {"toplam": 0, "attr": {}})
                s["toplam"] += 1
                for attr_name, counts in s["attr"].items():
                    val = b.get("attributeler", {}).get(attr_name) or "(seçilmemiş)"
                    counts[val] = counts.get(val, 0) + 1
        return result


def _file_hash(path, cache):
    key = str(path)
    if key not in cache:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        cache[key] = h.hexdigest()
    return cache[key]


class DuplicateFinder:
    """Eklenecek bir dosyanın projede zaten olup olmadığını bulur.

    check() sonucu:
        None                    -> çakışma yok
        ("ayni", ad)            -> aynı isim, içerik de aynı
        ("isim", ad)            -> aynı isim, içerik farklı
        ("icerik", ad)          -> farklı isim ama birebir aynı fotoğraf
    """

    def __init__(self, project):
        self.p = project
        self.cache = {}
        self.by_size = {}
        for name in project.list_images():
            self._index(name)

    def _index(self, name):
        size = self.p.image_path(name).stat().st_size
        self.by_size.setdefault(size, set()).add(name)

    def _same(self, a, b):
        return a.stat().st_size == b.stat().st_size and _file_hash(a, self.cache) == _file_hash(b, self.cache)

    def check(self, src):
        src = Path(src)
        existing = self.p.image_path(src.name)
        if existing.exists():
            return ("ayni" if self._same(src, existing) else "isim", src.name)
        for name in sorted(self.by_size.get(src.stat().st_size, ())):
            if self._same(src, self.p.image_path(name)):
                return ("icerik", name)
        return None

    def added(self, name):
        """Yeni eklenen / üzerine yazılan dosyayı dizine işler."""
        path = self.p.image_path(name)
        self.cache.pop(str(path), None)
        for names in self.by_size.values():
            names.discard(name)
        self._index(name)
