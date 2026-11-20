"""İki adımlı tuş seçimi.

1. tuş sınıfı seçer (ör. 1 = corba), sonraki tuşlar sırayla attribute seçeneklerini
seçer (ör. 3 = mantar). Hepsi seçilince seçim "hazır" olur: kutular sormadan etiketlenir.
"""


class KeySelector:
    def __init__(self, project):
        self.p = project
        self.reset()

    def reset(self):
        self.cls = None
        self.attrs = {}
        self.pending = None      # sırada seçilmeyi bekleyen attribute adı

    # ---------- yardımcılar ----------
    def attr_defs(self, cls=None):
        c = self.p.get_class(cls or self.cls) if (cls or self.cls) else None
        return [a for a in c["attributeler"] if a["secenekler"]] if c else []

    def pending_def(self):
        return next((a for a in self.attr_defs() if a["ad"] == self.pending), None)

    def all_keys(self):
        keys = set()
        for c in self.p.classes:
            if c.get("kisayol"):
                keys.add(c["kisayol"])
            for a in c["attributeler"]:
                keys.update(k for k in a.get("kisayollar", {}).values() if k)
        return keys

    # ---------- durum ----------
    def set_class(self, cls, attrs=None, waiting=True):
        if not self.p.get_class(cls):
            self.reset()
            return
        self.cls = cls
        valid = {a["ad"]: a["secenekler"] for a in self.attr_defs()}
        self.attrs = {k: v for k, v in (attrs or {}).items() if k in valid and v in valid[k]}
        if waiting:
            self._advance()
        else:
            self.pending = None

    def set_option(self, attr, value):
        self.attrs[attr] = value
        self._advance()

    def _advance(self):
        self.pending = next((a["ad"] for a in self.attr_defs() if a["ad"] not in self.attrs), None)

    def complete(self):
        return self.cls is not None and all(a["ad"] in self.attrs for a in self.attr_defs())

    def validate(self):
        """Sınıflar değiştiyse (silme / yeniden adlandırma) seçimi düzeltir."""
        if self.cls and self.p.get_class(self.cls):
            self.set_class(self.cls, self.attrs)
        else:
            self.reset()

    def press(self, key) -> bool:
        """Tuşa basıldı. Bir şey seçildiyse True döner."""
        a = self.pending_def() if self.cls else None
        if a:
            for v in a["secenekler"]:
                if a.get("kisayollar", {}).get(v) == key:
                    self.set_option(a["ad"], v)
                    return True
        for c in self.p.classes:
            if c.get("kisayol") == key:
                self.set_class(c["ad"])
                return True
        return False

    def options_hint(self):
        """'1 mercimek · 2 ezogelin · 3 mantar' gibi."""
        a = self.pending_def()
        if not a:
            return ""
        keys = a.get("kisayollar", {})
        return "  ·  ".join(f"[{keys[v]}] {v}" if keys.get(v) else v for v in a["secenekler"])
