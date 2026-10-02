# Kocaeli Rota

Kocaeli otobüs ve tramvay güzergâhlarını statik GTFS verisiyle karşılaştıran web uygulaması. `public/` tarayıcı arayüzüdür; `api/index.py` Vercel Python/FastAPI giriş noktasıdır. Rota algoritması ve sıkıştırılmış GTFS verisi `api/app/` altındadır.

## Yerel çalıştırma

Python 3.13 ile:

```sh
python -m venv .venv
# Ortamınızı etkinleştirin, ardından:
pip install -r requirements.txt
uvicorn api.index:app --reload
```

`http://127.0.0.1:8000/` arayüzü açar. API isteği `POST /api/chat` adresine `{"message":"Kuruçeşme Işıklar durağından Yeni Cuma Doğu durağına","limit":3,"routing_mode":"fewest_transfers"}` biçiminde gönderilir. Diğer modlar: `fastest`, `minimal_walking`, `prefer_tram`.

```sh
python -m unittest discover -s tests
```

## Vercel

Kök dizini proje kökü olarak seçin. `public/` statik dosyaları CDN'den sunulur; `vercel.json` içindeki `/api/*` rewrite isteği `api/index.py` içindeki FastAPI uygulamasına iletir. GTFS dosyası kodun bulunduğu dizine göre yüklenir; çalışma dizinine veya dış ağa bağımlı değildir. İlk soğuk istekte veri grafiğinin kurulması birkaç saniye sürebilir.

Süre ve varış tahminleri ortalama hız, durak sayısı ve biniş başına varsayılan 5 dakika bekleme üzerinden hesaplanır. Canlı sefer ve trafik verisi içermez.
