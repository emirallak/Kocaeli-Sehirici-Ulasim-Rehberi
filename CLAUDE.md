# CLAUDE.md

Kocaeli otobüs/tramvay rota planlayıcısı. Statik GTFS verisi → bellek içi
değişmez rota grafiği → frekans tabanlı RAPTOR. FastAPI arka uç, çerçevesiz
(vanilla JS) ön uç, Vercel'de yayınlanır. Arayüz metinleri ve kullanıcıya
dönük hata mesajları Türkçedir; kod, docstring ve yorumlar İngilizcedir.

## Komutlar

```sh
pip install -r requirements.txt            # Python 3.13 (.python-version)
uvicorn api.index:app --reload             # http://127.0.0.1:8000/ (Windows: start.bat)
python -m unittest discover -s tests       # Python testleri (küçük fixture'lar, hızlı)
node --test tests/*.cjs                    # Ön uç testleri (vm ile public/*.js yükler)
python -m api.app.data.cache               # GTFS veya yükleyici kodu değişince önbelleği yeniden üret
```

## Mimari

- `api/index.py` — FastAPI uygulaması ve tüm HTTP uçları (`/api/chat`, `/api/stops`,
  `/api/lines`, `/api/lines/{id}`, `/api/health`). Her uç Vercel için `/api` öneksiz
  bir ikizle de kayıtlıdır (`vercel.json` `/api/:path*` → `/:path*` yeniden yazar);
  yeni uç eklerken ikisini de ekle. Yerelde `public/` aynı uygulamadan sunulur.
- `api/app/data/` — GTFS yükleme. `loader.py` CSV → `RoutingSnapshot`;
  `indexes.py` sorgu indeksleri (durak→pattern, konumlar, biniş/iniş izinleri,
  500 m yürüme komşuları); `cache.py` kurulmuş snapshot'ın pickle+lzma önbelleği.
  `raw/` altındaki GTFS dosyaları depoya dahildir.
- `api/app/schemas/` — `frozen, slots` dataclass'lar. `StopId`/`PatternId` süreç içi
  kompakt tamsayılardır; GTFS kimlikleri ayrıca saklanır. Eşlemeler
  `read_only_mapping` (MappingProxyType) ile salt okunurdur.
- `api/app/routing/` — `search.best_routes` → `raptor.raptor_routes`. Pattern =
  aynı hat/yön/durak dizisi/biniş kuralı/hizmet günleri. En fazla 4 biniş,
  binişler arası tek yürüme. `metrics.py` süre/maliyet modeli (ortalama hız +
  biniş başına 5 dk bekleme; gerçek sefer saati kullanılmaz). `grouping.py`
  aynı fiziksel yolu izleyen hatları tek kartta birleştirir (`line_options`).
  `direct.py`/`transfers.py`/`frontiers.py`/`ranking.py` eski arama
  aşamalarıdır; yalnız testler kullanır.
- `api/app/api/` — durak adı çözümleme (`stops.py`, Türkçe normalize + bulanık
  eşleşme) ve hat sayfası verisi (`lines.py`).
- `public/` — `index.html`+`app.js`+`autocomplete.js` rota sayfası;
  `lines.html`+`lines.js`+`line-display.js` hat sayfası; ortak `net.js`
  (`fetchJSON`: zaman aşımı + soğuk başlangıç yeniden denemesi) ve tek
  `styles.css` (renkler `:root` tokenları, `prefers-color-scheme` ile koyu tema).
  Leaflet unpkg'den yüklenir. `tests/*.cjs` `app.js`'i DOM'suz `vm` içinde
  çalıştırır: `routeCard`/`lineBadges` global kalmalı, sayfa başlatma kodu
  `typeof window` kontrolünün arkasında durmalı. Tüm API çağrıları `fetchJSON`
  ile yapılır; çıplak `fetch` kullanma.

## Dikkat edilecekler

- Döngüsel hatlar aynı durağı birden çok kez ziyaret eder: durak→konum değil,
  her zaman `indexes.positions[pid][stop]` (tüm konumlar) kullan.
- Biniş/iniş izinleri pattern'e özeldir; `boardable_positions` /
  `alightable_positions` kontrolünü atlama.
- Bir yolculuktaki tüm adımların en az bir ortak hizmet günü olmalı
  (`Itinerary` bunu doğrular).
- Snapshot önbelleği, `raw/` dosyalarının ve yükleyici kaynak kodunun parmak
  iziyle doğrulanır; uyuşmazsa CSV'den yeniden kurulur (soğuk başlangıç
  ~10 sn+; önbellekle ~0,5 sn). Yükleyiciyi (`api/app/data/*.py`),
  `schemas/snapshot.py`'yi veya GTFS'i değiştirdiysen önbelleği yeniden üretip
  commitle — yoksa Vercel her soğuk başlangıçta CSV'den kurar.
- Windows'ta `core.autocrlf=true`; parmak izi CRLF/LF farkını yok sayar.
- Vercel: `vercel.json` `includeFiles` ham GTFS'i ve önbelleği fonksiyona ekler
  (parmak izi için ham dosyalar da gerekir); `public/` CDN'den sunulur. Katalog
  uçları `STATIC_DATA_CACHE` başlığıyla CDN'de önbelleğe alınır.

## Rota motorunda performans çalışırken

- `raptor.py` sıcak döngüleri (`relax_footpaths`, tarama döngüsü) bilerek
  satır içine alınmış koddur; `Bag` sözlük + sıralı liste ile `worthwhile`/
  `retain` mantığının aynısıdır. Okunabilirlik için geri bölmeden önce ölç.
- Budamalar (kalan mesafe alt sınırı `lower_bound`, `budget`, son tur
  kısayolu) sonucu değiştirmemelidir. Değişiklikten önce ve sonra gerçek veriyle
  birçok sorgu × 4 mod için `/api/chat` JSON çıktısını karşılaştır; testlerdeki
  fixture'lar bu farkları yakalamaz. `fewest_transfers` dışındaki modlarda
  `budget` yalnızca K sonuç bulununca sonlu olur ve sadece küçülür.
- Durak çözümleme (`stops.resolve_stop_ids`) aynı skorları üretmeli;
  `SequenceMatcher` yalnızca `quick_ratio` üst sınırı eşiği geçerse çalışır.
