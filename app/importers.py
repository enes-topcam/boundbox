"""CVAT for images 1.1 XML içe aktarma (sınıflar + kutular)."""
import xml.etree.ElementTree as ET


def read_cvat(path):
    """(labels, images) döner.
    labels: [{"ad", "renk", "attributeler": [{"ad", "secenekler"}]}]
    images: {resim_adi: {"genislik", "yukseklik", "kutular": [...]}}
    """
    root = ET.parse(path).getroot()
    labels = []
    for lab in root.iter("label"):
        name = (lab.findtext("name") or "").strip()
        if not name:
            continue
        attrs = []
        for at in lab.iter("attribute"):
            values = (at.findtext("values") or "").split()
            attrs.append({"ad": (at.findtext("name") or "").strip(), "secenekler": values})
        labels.append({"ad": name, "renk": (lab.findtext("color") or "").strip() or None,
                       "attributeler": [a for a in attrs if a["ad"]]})

    images = {}
    for im in root.iter("image"):
        boxes = []
        for bx in im.findall("box"):
            boxes.append({
                "sinif": bx.get("label"),
                "x1": round(float(bx.get("xtl")), 2), "y1": round(float(bx.get("ytl")), 2),
                "x2": round(float(bx.get("xbr")), 2), "y2": round(float(bx.get("ybr")), 2),
                "attributeler": {a.get("name"): (a.text or "").strip() for a in bx.findall("attribute")},
            })
        images[im.get("name")] = {
            "genislik": int(float(im.get("width", 0))),
            "yukseklik": int(float(im.get("height", 0))),
            "kutular": boxes,
        }
    return labels, images


def merge_labels(project, labels):
    """Eksik sınıf/attribute/seçenekleri projeye ekler."""
    for lab in labels:
        if not project.get_class(lab["ad"]):
            project.add_class(lab["ad"], lab["renk"])
        for a in lab["attributeler"]:
            project.add_attribute(lab["ad"], a["ad"])
            for v in a["secenekler"]:
                project.add_option(lab["ad"], a["ad"], v)
