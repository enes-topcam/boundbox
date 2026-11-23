"""Dışa aktarma: JSON, COCO, YOLO, Pascal VOC XML, CVAT XML, etiketli JPG, kesilmiş kutular (yeni proje)."""
import itertools
import copy
import json
import random
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QImage

from .imageutil import box_caption, image_size, load_image
from .project import Project


def _xml_write(root: ET.Element, path: Path):
    ET.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


class Exporter:
    def __init__(self, project, out_dir, only_labeled=True, copy_images=True,
                 yolo_mode="sinif", val_percent=0, crop_padding=6, crop_project=None, limit=0,
                 progress=None):
        self.p = project
        self.out = Path(out_dir)
        self.copy_images = copy_images
        self.yolo_mode = yolo_mode          # "sinif" veya "sinif_attr"
        self.val_percent = val_percent
        self.crop_padding = crop_padding    # kesilen kutunun her kenarına eklenen piksel
        self.crop_project = crop_project    # kesitlerden oluşturulacak yeni proje klasörü
        self.crop_count = 0
        self.progress = progress or (lambda text: None)
        self.warnings = []
        self.notes = []

        images = project.list_images()
        if only_labeled:
            images = [i for i in images if project.get_boxes(i)]
        if limit > 0:
            images = images[:limit]
        self.images = images
        self._sizes = {}

    def size(self, image):
        ann = self.p.annotations.get(image)
        if ann:
            return ann["genislik"], ann["yukseklik"]
        if image not in self._sizes:
            self._sizes[image] = image_size(self.p.image_path(image))
        return self._sizes[image]

    def run(self, formats):
        if any(f != "kirp" for f in formats):
            self.out.mkdir(parents=True, exist_ok=True)
        jobs = {
            "json": self.export_json, "coco": self.export_coco, "yolo": self.export_yolo,
            "voc": self.export_voc, "cvat": self.export_cvat, "jpg": self.export_jpg,
            "kirp": self.export_crops,
        }
        for f in formats:
            jobs[f]()
        return self.warnings

    # ---------- JSON (kendi formatımız) ----------
    def export_json(self):
        self.progress("JSON yazılıyor...")
        data = {
            "proje_adi": self.p.name,
            "olusturma": datetime.now().isoformat(timespec="seconds"),
            "siniflar": self.p.classes,
            "resimler": [],
        }
        for img in self.images:
            w, h = self.size(img)
            data["resimler"].append({"resim": img, "genislik": w, "yukseklik": h,
                                     "kutular": self.p.get_boxes(img)})
        d = self.out / "json"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "etiketler.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ---------- COCO ----------
    def export_coco(self):
        self.progress("COCO JSON yazılıyor...")
        cat_ids = {c["ad"]: i + 1 for i, c in enumerate(self.p.classes)}
        coco = {
            "info": {"description": self.p.name, "date_created": datetime.now().isoformat(timespec="seconds")},
            "licenses": [],
            "categories": [{"id": i, "name": n, "supercategory": ""} for n, i in cat_ids.items()],
            "images": [],
            "annotations": [],
        }
        ann_id = 1
        for img_id, img in enumerate(self.images, start=1):
            w, h = self.size(img)
            coco["images"].append({"id": img_id, "file_name": img, "width": w, "height": h})
            for b in self.p.get_boxes(img):
                if b["sinif"] not in cat_ids:
                    continue
                bw, bh = b["x2"] - b["x1"], b["y2"] - b["y1"]
                coco["annotations"].append({
                    "id": ann_id, "image_id": img_id, "category_id": cat_ids[b["sinif"]],
                    "bbox": [round(b["x1"], 2), round(b["y1"], 2), round(bw, 2), round(bh, 2)],
                    "area": round(bw * bh, 2), "iscrowd": 0, "segmentation": [],
                    "attributes": b.get("attributeler", {}),
                })
                ann_id += 1
        d = self.out / "coco"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "annotations.json", "w", encoding="utf-8") as f:
            json.dump(coco, f, ensure_ascii=False, indent=2)
        if self.copy_images:
            self._copy_images(self.images, d / "images")

    # ---------- YOLO ----------
    def yolo_names(self):
        """YOLO sınıf listesi ve kutu -> sınıf id eşlemesi."""
        if self.yolo_mode == "sinif":
            names = self.p.class_names()
            return names, lambda b: names.index(b["sinif"]) if b["sinif"] in names else None

        names, key_to_id = [], {}
        for c in self.p.classes:
            attrs = [a for a in c["attributeler"] if a["secenekler"]]
            for combo in itertools.product(*[a["secenekler"] for a in attrs]):
                key = (c["ad"],) + combo
                key_to_id[key] = len(names)
                names.append("_".join(key))
        attr_order = {c["ad"]: [a["ad"] for a in c["attributeler"] if a["secenekler"]] for c in self.p.classes}

        def lookup(b):
            order = attr_order.get(b["sinif"])
            if order is None:
                return None
            vals = tuple(b.get("attributeler", {}).get(a) for a in order)
            return key_to_id.get((b["sinif"],) + vals)
        return names, lookup

    def export_yolo(self):
        self.progress("YOLO yazılıyor...")
        d = self.out / "yolo"
        names, lookup = self.yolo_names()
        images = list(self.images)
        splits = {"train": images}
        if self.val_percent > 0 and len(images) > 1:
            rnd = random.Random(42)
            shuffled = images[:]
            rnd.shuffle(shuffled)
            n_val = max(1, round(len(images) * self.val_percent / 100))
            splits = {"train": sorted(shuffled[n_val:]), "val": sorted(shuffled[:n_val])}

        skipped = 0
        for split, imgs in splits.items():
            lbl_dir = d / "labels" / split
            lbl_dir.mkdir(parents=True, exist_ok=True)
            for img in imgs:
                w, h = self.size(img)
                lines = []
                for b in self.p.get_boxes(img):
                    cid = lookup(b)
                    if cid is None:
                        skipped += 1
                        continue
                    cx = (b["x1"] + b["x2"]) / 2 / w
                    cy = (b["y1"] + b["y2"]) / 2 / h
                    bw = (b["x2"] - b["x1"]) / w
                    bh = (b["y2"] - b["y1"]) / h
                    lines.append(f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
                (lbl_dir / (Path(img).stem + ".txt")).write_text("\n".join(lines), encoding="utf-8")
            if self.copy_images:
                self._copy_images(imgs, d / "images" / split)

        (d / "classes.txt").write_text("\n".join(names), encoding="utf-8")
        val = "images/val" if "val" in splits else "images/train"
        yaml = [f"path: {d.resolve().as_posix()}", "train: images/train", f"val: {val}", "", "names:"]
        yaml += [f"  {i}: {n}" for i, n in enumerate(names)]
        (d / "data.yaml").write_text("\n".join(yaml) + "\n", encoding="utf-8")
        if skipped:
            self.warnings.append(f"YOLO: {skipped} kutu atlandı (attribute'u seçilmemiş).")

    # ---------- Pascal VOC XML ----------
    def export_voc(self):
        self.progress("Pascal VOC XML yazılıyor...")
        d = self.out / "voc"
        for img in self.images:
            w, h = self.size(img)
            root = ET.Element("annotation")
            _sub(root, "folder", "JPEGImages")
            _sub(root, "filename", img)
            src = _sub(root, "source")
            _sub(src, "database", self.p.name)
            size = _sub(root, "size")
            _sub(size, "width", w)
            _sub(size, "height", h)
            _sub(size, "depth", 3)
            _sub(root, "segmented", 0)
            for b in self.p.get_boxes(img):
                obj = _sub(root, "object")
                _sub(obj, "name", b["sinif"])
                _sub(obj, "pose", "Unspecified")
                _sub(obj, "truncated", 0)
                _sub(obj, "difficult", 0)
                box = _sub(obj, "bndbox")
                _sub(box, "xmin", round(b["x1"], 2))
                _sub(box, "ymin", round(b["y1"], 2))
                _sub(box, "xmax", round(b["x2"], 2))
                _sub(box, "ymax", round(b["y2"], 2))
                attrs = b.get("attributeler", {})
                if attrs:
                    ael = _sub(obj, "attributes")
                    for k, v in attrs.items():
                        a = _sub(ael, "attribute")
                        _sub(a, "name", k)
                        _sub(a, "value", v)
            _xml_write(root, d / "Annotations" / (Path(img).stem + ".xml"))
        main = d / "ImageSets" / "Main"
        main.mkdir(parents=True, exist_ok=True)
        (main / "default.txt").write_text("\n".join(Path(i).stem for i in self.images), encoding="utf-8")
        (d / "labelmap.txt").write_text(
            "# label:color_rgb:parts:actions\n" + "\n".join(f"{n}:::" for n in self.p.class_names()),
            encoding="utf-8")
        if self.copy_images:
            self._copy_images(self.images, d / "JPEGImages")

    # ---------- CVAT for images 1.1 XML (örnekteki format) ----------
    def export_cvat(self):
        self.progress("CVAT XML yazılıyor...")
        now = datetime.now(timezone.utc).isoformat(sep=" ")
        root = ET.Element("annotations")
        _sub(root, "version", "1.1")
        meta = _sub(root, "meta")
        job = _sub(meta, "job")
        _sub(job, "size", len(self.images))
        _sub(job, "mode", "annotation")
        _sub(job, "overlap", 0)
        _sub(job, "created", now)
        _sub(job, "updated", now)
        _sub(job, "subset", "default")
        _sub(job, "start_frame", 0)
        _sub(job, "stop_frame", max(0, len(self.images) - 1))
        labels = _sub(job, "labels")
        for c in self.p.classes:
            lab = _sub(labels, "label")
            _sub(lab, "name", c["ad"])
            _sub(lab, "color", c["renk"])
            _sub(lab, "type", "rectangle")
            attrs = _sub(lab, "attributes")
            for a in c["attributeler"]:
                at = _sub(attrs, "attribute")
                _sub(at, "name", a["ad"])
                _sub(at, "mutable", "False")
                _sub(at, "input_type", "select")
                _sub(at, "default_value", a["secenekler"][0] if a["secenekler"] else "")
                _sub(at, "values", " ".join(a["secenekler"]))
        _sub(meta, "dumped", now)

        for i, img in enumerate(self.images):
            w, h = self.size(img)
            im = _sub(root, "image", id=i, name=img, width=w, height=h)
            for b in self.p.get_boxes(img):
                bx = _sub(im, "box", label=b["sinif"], source="manual", occluded=0,
                          xtl=f"{b['x1']:.2f}", ytl=f"{b['y1']:.2f}",
                          xbr=f"{b['x2']:.2f}", ybr=f"{b['y2']:.2f}", z_order=0)
                for k, v in b.get("attributeler", {}).items():
                    _sub(bx, "attribute", v, name=k)
        _xml_write(root, self.out / "cvat" / "annotations.xml")

    # ---------- Etiketli JPG ----------
    def export_jpg(self):
        d = self.out / "jpg"
        d.mkdir(parents=True, exist_ok=True)
        for n, img in enumerate(self.images, start=1):
            self.progress(f"Etiketli JPG çiziliyor... {n}/{len(self.images)}")
            image = load_image(self.p.image_path(img)).convertToFormat(QImage.Format.Format_RGB32)
            draw_boxes(image, self.p.get_boxes(img), self.p.color)
            image.save(str(d / (Path(img).stem + ".jpg")), "JPG", 92)

    # ---------- Kesilmiş kutular → yeni etiketli proje ----------
    def export_crops(self):
        """Her kutuyu kenarlarından `crop_padding` piksel taşacak şekilde keser ve
        `crop_project` klasöründe yeni bir proje oluşturur: aynı sınıflar, her kesitte
        asıl kutu aynı sınıf / seçeneklerle etiketli."""
        root = Path(self.crop_project)
        new = Project.open_or_create(root)
        new.classes = copy.deepcopy(self.p.classes)
        new.save()
        pad = self.crop_padding
        count = 0
        for n, img in enumerate(self.images, start=1):
            self.progress(f"Kutular kesiliyor... {n}/{len(self.images)}")
            boxes = self.p.get_boxes(img)
            if not boxes:
                continue
            image = load_image(self.p.image_path(img))
            w, h = image.width(), image.height()
            stem = Path(img).stem
            for i, b in enumerate(boxes, start=1):
                bx1, bx2 = sorted((b["x1"], b["x2"]))
                by1, by2 = sorted((b["y1"], b["y2"]))
                x1 = max(0, int(bx1) - pad)
                y1 = max(0, int(by1) - pad)
                x2 = min(w, int(round(bx2)) + pad)
                y2 = min(h, int(round(by2)) + pad)
                cw, ch = x2 - x1, y2 - y1
                if cw < 1 or ch < 1:
                    continue
                crop = image.copy(x1, y1, cw, ch).convertToFormat(QImage.Format.Format_RGB32)
                name = f"{stem}_{i}.jpg"
                crop.save(str(new.image_path(name)), "JPG", 95)
                nb = copy.deepcopy(b)
                nb.update(x1=max(0.0, bx1 - x1), y1=max(0.0, by1 - y1),
                          x2=min(float(cw), bx2 - x1), y2=min(float(ch), by2 - y1))
                new.set_boxes(name, cw, ch, [nb])
                count += 1
        self.crop_count = count
        self.notes.append(f"{count} kutu kesildi ({pad} px pay), yeni proje:\n{root}")

    # ---------- yardımcı ----------
    def _copy_images(self, images, dst):
        dst.mkdir(parents=True, exist_ok=True)
        for img in images:
            target = dst / img
            if not target.exists():
                shutil.copy2(self.p.image_path(img), target)


def draw_boxes(image: QImage, boxes, color_fn):
    """Kutuları ve etiket yazılarını resmin üzerine çizer (Türkçe karakter destekli)."""
    w = image.width()
    line = max(2, round(w / 450))
    font = QFont()
    font.setPixelSize(max(14, round(w / 55)))
    font.setBold(True)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(font)
    fm = p.fontMetrics()
    for b in boxes:
        color = QColor(color_fn(b["sinif"]))
        rect = QRectF(b["x1"], b["y1"], b["x2"] - b["x1"], b["y2"] - b["y1"])
        p.setPen(QPen(color, line))
        p.drawRect(rect)
        text = box_caption(b)
        pad = line * 2
        tw, th = fm.horizontalAdvance(text) + pad * 2, fm.height() + pad
        ty = rect.top() - th if rect.top() - th >= 0 else rect.top()
        p.fillRect(QRectF(rect.left(), ty, tw, th), color)
        p.setPen(QColor("white"))
        p.drawText(QRectF(rect.left() + pad, ty, tw, th), Qt.AlignmentFlag.AlignVCenter, text)
    p.end()
