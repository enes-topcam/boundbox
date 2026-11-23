# Etiketleme

Fotoğraflara dikdörtgen kutu çizip sınıf ve özellik (attribute) atamak için masaüstü etiketleme aracı. PySide6 ile yazıldı.

- Kutu çizme, seçme, silme, geri alma
- Kutu düzeltme: kenarına / köşesine tıkla, yeni yerine götürüp tekrar tıkla (sürüklemek de olur); kenardan yeni kutu başlatmak için Shift + tık
- Sınıflar ve seçmeli özellikler (ör. `corba` → `mercimek / ezogelin / mantar`)
- CVAT for images 1.1 XML içe aktarma
- Dışa aktarma: JSON, COCO, YOLO, Pascal VOC XML, CVAT XML, etiketli JPG
- Kesilmiş kutular: her kutu, kenarlarından ayarlanabilir piksel payla kesilir ve seçilen klasörde **yeni bir proje** olarak kaydedilir. Sınıflar aynen kopyalanır, her kesitte asıl kutu aynı sınıf ve seçeneklerle etiketli gelir.
- Açık / koyu tema (sağ üstten seçilir, "Sistem" Windows ayarını takip eder)
- Sesle seçim: "mercimek çorbası" de, corba → mercimek seçilsin; sen sadece kutuyu çiz
- Etikete göre gezinme: sağdaki istatistikte bir seçeneğin (ör. `mercimek`) solundaki oka tıkla, o etiketli fotoğraflar açılsın; birine tıklayınca A / D sadece onlarda gezer (üstteki "… filtresi ×" göstergesiyle biter)
- Sade, iki temalı arayüz: küçük resimli fotoğraf listesi, aktif etiket rozeti (Hazır / … seç), istatistikte her etiketin kısayolu

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
| Esc | Çizimi / kenar düzeltmeyi iptal et |
| Shift + tık | Kutunun kenarından yeni kutu başlat (düzeltme yerine) |
| X | Seçimi sıfırla |
| Ctrl+E | Dışa aktar |
| F5 | Yenile |

Kısayollar program içinden değiştirilebilir.

## Sesle seçim

Sağ üstteki mikrofon düğmesi ("Kapalı") mikrofonu açar / kapatır (kısayol **M**). Sınıfı ve seçeneği söylemen yeter:
"mercimek çorbası" → `corba → mercimek`. Sadece "mercimek" demek de olur; aynı ad birden fazla
sınıfta varsa sınıfı da söylemen gerekir.

- **Bas-konuş** (varsayılan): **Space** basılı tutarken konuş, bırakınca seçilir.
- **Sürekli dinle**: tuşa basmadan söylersin. Konuşurken düğme yeşile döner.

Dinleme şeklini ve mikrofonu mikrofon düğmesinin yanındaki oktan ya da Ayarlar → Sesle seçim'den seçebilirsin.
Sonradan taktığın mikrofon listede yoksa **Yenile**'ye bas. Bas-konuş ve aç / kapat tuşlarını Ayarlar → Sesle seçim'den
(ya da Genel kısayollar'dan) istediğin tuşla değiştirebilirsin. Program bir adı iyi anlamıyorsa Ayarlar → Sesle seçim'den ona **sesli ad** ver:
kutuya yaz, **Enter**'a bas; her Enter'da bir ad eklenir (ör. `ezogelin` için "ezo", "ezogelin").
Silmek için adın üstüne tıkla.

Tanıma internetsiz, bilgisayarda yapılır ([Vosk](https://alphacephei.com/vosk/)). İlk açılışta Türkçe model
(~37 MB) bir kere indirilir ve `%LOCALAPPDATA%\Etiketleme\models` klasörüne kaydedilir. İnternetsiz bir
bilgisayarda kullanmak için modeli programın yanına, `models\vosk-model-small-tr-0.3` klasörüne koyabilirsin.

## Exe'yi kendin derlemek

```
pip install pyinstaller
pyinstaller --noconfirm --windowed --name Etiketleme ^
  --hidden-import vosk --hidden-import sounddevice ^
  --collect-binaries vosk --collect-all _sounddevice_data ^
  --exclude-module vosk.transcriber --exclude-module numpy --exclude-module pandas ^
  --exclude-module scipy --exclude-module pyarrow --exclude-module matplotlib main.py
```

Çıktı `dist\Etiketleme\` klasörüne düşer.
