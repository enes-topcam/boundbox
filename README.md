# Etiketleme

Fotoğraflara dikdörtgen kutu çizip sınıf ve özellik (attribute) atamak için masaüstü etiketleme aracı. PySide6 ile yazıldı.

- Kutu çizme, seçme, silme, geri alma
- Sınıflar ve seçmeli özellikler (ör. `corba` → `mercimek / ezogelin / mantar`)
- CVAT for images 1.1 XML içe aktarma
- Dışa aktarma: JSON, COCO, YOLO, Pascal VOC XML, CVAT XML, etiketli JPG
- Açık / koyu tema (sağ üstten seçilir, "Sistem" Windows ayarını takip eder)
- Sesle seçim: "mercimek çorbası" de, corba → mercimek seçilsin; sen sadece kutuyu çiz
- Etikete göre gezinme: sağdaki listede bir seçeneğin (ör. `mercimek`) solundaki oka tıkla, o etiketli fotoğraflar açılsın; birine tıklayınca A / D sadece onlarda gezer (üstteki mavi düğmeyle biter)

## Kurulum

### 1. Hazır program (Python gerekmez)

1. [Releases](../../releases) sayfasından en son sürümün `Etiketleme-vX.X-windows.zip` dosyasını indir.
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
| Del | Seçili kutuyu sil (soldaki listede fotoğraf seçiliyken: fotoğrafı sil, onay sorar) |
| Ctrl+Del | Fotoğrafı sil |
| Ctrl+Z | Geri al |
| Esc | Çizimi iptal et |
| X | Seçimi sıfırla |
| Ctrl+E | Dışa aktar |
| F5 | Yenile |

Kısayollar program içinden değiştirilebilir.

## Sesle seçim

Sağ üstteki 🎤 düğmesi mikrofonu açar / kapatır (kısayol **M**). Sınıfı ve seçeneği söylemen yeter:
"mercimek çorbası" → `corba → mercimek`. Sadece "mercimek" demek de olur; aynı ad birden fazla
sınıfta varsa sınıfı da söylemen gerekir.

- **Bas-konuş** (varsayılan): **Space** basılı tutarken konuş, bırakınca seçilir.
- **Sürekli dinle**: tuşa basmadan söylersin. Konuşurken simge yeşile döner.

Dinleme şeklini ve mikrofonu 🎤 düğmesinin okundan seçebilirsin. İki tuşu da Ayarlar → Genel kısayollar'dan
değiştirebilirsin. Program bir adı iyi anlamıyorsa Ayarlar → Sesle seçim'den ona **sesli ad** ver
(ör. `ezogelin` için "ezo").

Tanıma internetsiz, bilgisayarda yapılır ([Vosk](https://alphacephei.com/vosk/)). İlk açılışta Türkçe model
(~37 MB) bir kere indirilir ve `%LOCALAPPDATA%\Etiketleme\models` klasörüne kaydedilir. İnternetsiz bir
bilgisayarda kullanmak için modeli programın yanına, `models\vosk-model-small-tr-0.3` klasörüne koyabilirsin.

## Exe'yi kendin derlemek

```
pip install pyinstaller
pyinstaller --noconfirm --windowed --name Etiketleme --collect-binaries vosk ^
  --exclude-module numpy --exclude-module pandas --exclude-module scipy ^
  --exclude-module matplotlib --exclude-module pyarrow main.py
```

Çıktı `dist\Etiketleme\` klasörüne düşer.
