from PySide6.QtGui import QImage, QImageReader, QImageIOHandler


def load_image(path) -> QImage:
    """Resmi telefon EXIF yönüne göre döndürülmüş olarak yükler."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    return reader.read()


def image_size(path):
    """Resmi tamamen açmadan (genişlik, yükseklik) döner."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    w, h = size.width(), size.height()
    if reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
        w, h = h, w
    return w, h


def box_label(box) -> str:
    """Ekranda gösterilen etiket: 'corba › mercimek'."""
    values = [v for v in box.get("attributeler", {}).values() if v]
    return " › ".join([box["sinif"]] + values)


def box_caption(box) -> str:
    """Dışa aktarılan etiketli JPG'deki yazı (biçimi değişmesin)."""
    attrs = box.get("attributeler", {})
    if not attrs:
        return box["sinif"]
    return box["sinif"] + ": " + ", ".join(attrs.values())
