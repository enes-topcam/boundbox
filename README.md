# Etiketleme

Fotoğraflara dikdörtgen kutu çizip sınıf ve özellik (attribute) atamak için masaüstü etiketleme aracı. PySide6 ile yazıldı.

- Kutu çizme, seçme, silme, geri alma
- Sınıflar ve seçmeli özellikler (ör. `corba` → `mercimek / ezogelin / mantar`)
- CVAT for images 1.1 XML içe aktarma
- Dışa aktarma: JSON, COCO, YOLO, Pascal VOC XML, CVAT XML, etiketli JPG

## Kurulum

### 1. Hazır program (Python gerekmez)

1. [Releases](../../releases) sayfasından `Etiketleme-v1.0-windows.zip` dosyasını indir.
2. Zip'i bir klasöre çıkar.
3. `Etiketleme\Etiketleme.exe` dosyasına çift tıkla.

> Windows "bilinmeyen yayıncı" uyarısı verirse **Ek bilgi → Yine de çalıştır** de.
> `_internal` klasörünü silme ya da exe'yi tek başına başka yere taşıma; ikisi birlikte durmalı.

### 2. Kaynak koddan çalıştırma

Python 3.10 veya üstü gerekir.

```
git clone https://github.com/enes-topcam/boundbox.git
cd boundbox
pip install -r requirements.txt
python main.py
```

Windows'ta `baslat.bat` dosyasına çift tıklayarak da açabilirsin.

## Kısayollar

| Tuş | İşlem |
|---|---|
| A / D | Önceki / sonraki fotoğraf |
| F | Sığdır |
| Del | Seçili kutuyu sil |
| Ctrl+Del | Fotoğrafı sil |
| Ctrl+Z | Geri al |
| Esc | Çizimi iptal et |
| X | Seçimi sıfırla |
| Ctrl+E | Dışa aktar |
| F5 | Yenile |

Kısayollar program içinden değiştirilebilir.

## Exe'yi kendin derlemek

```
pip install pyinstaller
pyinstaller --noconfirm --windowed --name Etiketleme main.py
```

Çıktı `dist\Etiketleme\` klasörüne düşer.
