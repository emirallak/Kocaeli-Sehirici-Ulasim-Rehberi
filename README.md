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

Kök dizini proje kökü olarak seçin. `public/` statik dosyaları CDN'den sunulur. Vercel'deki `/api/chat` isteği `vercel.json` ile uygulamanın `/chat` yoluna eşlenir; yerel FastAPI uygulaması her iki yolu da kabul eder. `/api/health` veri grafiğinin yüklenip yüklenmediğini gösterir. GTFS dosyası kodun bulunduğu dizine göre yüklenir; çalışma dizinine veya dış ağa bağımlı değildir. İlk soğuk istekte veri grafiğinin kurulması birkaç saniye sürebilir.

Süre ve varış tahminleri ortalama hız, durak sayısı ve biniş başına varsayılan 5 dakika bekleme üzerinden hesaplanır. Canlı sefer ve trafik verisi içermez.

## Durak önerileri ve RAPTOR

Kalkış ve varış alanları aktif durak listesini `/api/stops` üzerinden bir kez yükler. Her tuşta tarayıcı içinde filtreleme yapılır; Türkçe harfler ve aksansız yazımlar desteklenir. Önek eşleşmeleri önce gösterilir. Ok tuşları ve Enter ile seçim, Escape ile kapatma yapılabilir. Aynı ad/ilçedeki yön peronları tek öneri olarak gösterilir; rota motoru uygun peronları ayrı değerlendirir. `/api/stops?q=U&limit=12` sunucu tarafında öneri araması da sağlar. Vercel için `/stops` eşdeğer yolu bulunur.

`api/app/routing/raptor.py`, [RAPTOR](https://www.microsoft.com/en-us/research/publication/round-based-public-transit-routing/) yaklaşımını mevcut sıklık tabanlı süre tahminlerine uygular. Her biniş turunda işaretlenmiş duraklardan bir rota kuyruğu oluşturulur; her güzergâh yalnızca bir kez, ilk erişilebilir biniş konumundan itibaren taranır. Takvim kesişimleri, biniş/iniş izinleri, döngü durakları ve yürüyüş aktarmaları korunur. Yolculuklar ana etiket bağlantılarından yalnızca istenen sonuç sayısı kadar oluşturulur. En az aktarmalı modda yeterli sonuç bulununca sonraki turlar atlanır; diğer modlarda hedef maliyetiyle güvenli budama uygulanır.

Veri modeli sefer saatleri içermediğinden bu sürüm zaman çizelgesi RAPTOR'u değildir: mevcut ortalama hız ve 5 dakika bekleme tahminleri korunur. En fazla dört biniş, binişler arasında bir yürüyüş bağlantısı ve durak başına 10–20 farklı hat geçmişi tutulur; tüm Pareto-optimal yolculukları listeleme garantisi yoktur.

Ek kontroller:

```sh
node --test tests/test_autocomplete.cjs
```

Yerel Kocaeli verisinde (8.511 durak, 2.161 güzergâh kalıbı), üç en az aktarmalı sorgu önceki aramayla aynı ilk üç hat seçeneğini verdi: sıcak veriyle önceki 9,6–10,0 saniye yerine 28–36 ms. Kuruçeşme Işıklar → Yeni Cuma Doğu sorgusunda diğer üç mod 0,54–0,94 saniye sürdü (önceki 9,5–10,4 saniye). Bunlar tek çalıştırma ölçümleridir; GTFS yükleme ve HTTP süreleri dahil değildir, performans garantisi değildir.

Aynı en az aktarmalı sorguda `tracemalloc` ile ölçülen sorgu başına tepe Python tahsisi 116,35 MiB yerine 1,24 MiB oldu; önceden yüklenmiş GTFS belleği bu ölçüme dahil değildir.
