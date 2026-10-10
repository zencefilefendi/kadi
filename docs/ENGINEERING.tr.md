# Kadı: Mühendislik Raporu

Bu rapor neyin yapıldığını, hangi tekniklerin neden kullanıldığını, neyin ölçüldüğünü, nelerin ters gidip nasıl düzeltildiğini ve neyin henüz doğrulanmadığını anlatır. Buradaki her rakam bu repodaki dosyalardan yeniden üretilebilir. Formel ifadeler [THEORY.md](THEORY.md), güvenlik ayrıntıları [THREAT_MODEL.md](THREAT_MODEL.md) belgesindedir. İngilizce sürüm: [ENGINEERING.md](ENGINEERING.md).

---

## 1. Tek paragrafta problem ve çözüm

LLM ajanları çok sayıda küçük, çoktan seçmeli karar verir. Frontier model bu kararları doğru verir ama yavaş ve pahalıdır. Küçük bir model ucuzdur ama hata oranı bilinmez.

Kadı üç katmanlı bir kaskattır: önce birebir hafıza, sonra yerel refleks, en son oracle. Refleks, **yalnızca istatistiksel bir test** yerel cevabın oracle ile ayrışmasını kullanıcının seçtiği α'nın altında tuttuğunu sertifikaladığında cevap verir. Geri kalan her şey oracle'a gider ve her yükseltme refleksi eğitir.

İki açık niyet sınıflandırma benchmark'ında Kadı, **α = %5'te oracle çağrılarının %75–85'ini ortadan kaldırdı**. Hata sınırı **126 koşunun 126'sında** tuttu.

## 2. Sürüm geçmişi

| Sürüm | Getirdiği |
|---|---|
| 0.1 | Prototip: hafıza → refleks → oracle kaskatı, adaptif conformal tahmin, panel |
| 0.2 | Üretim katmanı: gölge mod, replay, Mondrian conformal, sapma kesicisi, fallback, PII maskeleme, sertleştirilmiş HTTP API, TypeScript istemcisi, Docker, CI. Ayrıca **kalibrasyon seçim yanlılığı hatası** (§5.1) ve **güvenlik denetiminin 11 bulgusu** (§5.3) düzeltildi |
| 0.3 | Learn then Test (yüksek olasılıklı garanti), kurcalanamaz defter, açık benchmark |
| 0.4 | Anlamsal refleks: cümle embedding'leri + k-NN (isteğe bağlı ek paket) |
| 0.4.1 | Belge yaması: durum ve sınırlar, yeniden ölçülen demo |
| 0.5 | **Ajanın oracle olduğu** MCP sunucusu (API anahtarı gerekmez) |

## 3. Kullanılan teknikler

### 3.1 İstatistik: Kadı ne zaman tek başına karar verebilir?

| Teknik | Nerede | Neden | Kaynak |
|---|---|---|---|
| Split conformal tahmin | `kadi/conformal.py` | Herhangi bir skoru, kapsaması ≥ 1 − α olan tahmin kümelerine çevirir; yalnızca tek elemanlı kümede cevap vermek ayrışmayı sınırlar | Vovk vd. 2005; Papadopoulos vd. 2002; Lei vd. 2018 |
| Adaptive Conformal Inference | aynı dosya, `alpha_t` | Trafik değiştikçe uzun dönem kapsamamayı α civarında tutar | Gibbs & Candès 2021 |
| Mondrian (etiket başına) conformal | `MondrianConformal` | Nadir ama kritik bir etikete kendi sınırını verir | Vovk 2012 |
| **Learn then Test** | `LearnThenTest` | PAC tipi garanti: risk ≤ α, **≥ 1 − δ olasılıkla**. Karar riskini doğrudan test ettiği için daha çok yerel cevap verir | Angelopoulos, Bates, Candès, Jordan & Lei 2021 |
| Kesin binom p-değerleri, sabit sıralı test | `binom_cdf`, `LTT_GRID` | Normal yaklaşımı gerektirmeyen geçerli test; eşik ızgarası LTT'nin gerektirdiği gibi önceden sabitlenmiştir | — |
| **Eğitimden ayrı, rastgele kalibrasyon** | `engine.py` | Kalibrasyon verisi akıştan rastgele seçilmeli ve modelin eğitiminde hiç kullanılmamalıdır (§5.1) | — |
| Zaman bütçeli yeniden puanlama | `_Brain.refresh` | Saklanan kalibrasyon girdilerini güncel modelle yeniden puanlar; toplam sürenin en fazla ~%10'unu kullanır | — |
| Tutarlılık kuralı | `_route` | Tek elemanlı küme modelin en olası etiketiyle uyuşmazsa karar oracle'a gider. Oracle'a göndermek hiçbir zaman hata eklemez | — |

### 3.2 Refleks (yerel model)

| Teknik | Nerede | Neden |
|---|---|---|
| Kelime ve harf n-gram'larında feature hashing | `features.py` | Sıfır bağımlılık, deterministik (crc32), sınırlı (girdi başına ≤ 2.048 özellik) |
| AdaGrad'lı çevrimiçi lojistik regresyon | `learner.py` | Oracle'ın her kararından öğrenir (çevrimiçi damıtma) |
| Yenilik (dağılım dışı girdi) koruması | `learner.novelty` | Özellikleri çoğunlukla hiç görülmemiş girdileri oracle'a gönderir; anlamsız metinle yapılan saldırıları da durdurur |
| Cümle embedding'leri (fastembed/ONNX) | `embed.py` (isteğe bağlı) | Anlamı yakalar: "kartım gelmedi" ≈ "kartım nerede" |
| k-NN oylamasıyla karıştırılmış lojistik model | `KNNHybridReflex` | Etiket başına az örnek olduğunda güçlüdür. Ayarları değerlendirme verisinde değil, ayrı bir akışta (tohum 100–102) seçildi |

### 3.3 İşletme ve güvenlik

| Teknik | Neden |
|---|---|
| Rastgele denetimler | Canlı trafikteki gerçek uyuşmayı ölçer; panel bunu varsayım olarak değil, ölçüm olarak gösterir |
| Sapma kesicisi | Denetimde ölçülen ayrışmanın %95 alt sınırı α'yı aşarsa gözetim moduna geçer (her şey oracle'a gider) ve webhook alarmı gönderir |
| Gölge mod ve replay | Canlıya almadan önce değeri risksiz kanıtlar |
| Fallback | Oracle çöktüğünde işaretli yerel cevap döner |
| Kurcalanamaz defter | Her karar bir öncekine HMAC ile zincirlenir; `kadi verify` ve `kadi anchor` |
| Sağlama toplamlı PII maskeleme | TC kimlik numarası (algoritmik kontrol), IBAN (mod-97), kart numarası (Luhn + IIN), telefon, e-posta, API anahtarları |
| Sertleştirilmiş HTTP | Sabit zamanlı token doğrulaması, CSRF ve DNS rebinding korumaları, hız sınırı, gövde limitleri, CSP |
| Prompt injection ayraçları | Kullanıcı metni oracle'a "güvenilmez veri" olarak işaretlenmiş gider; çıktı, tanımlı seçeneklere kilitlidir |
| **Ajanın oracle olduğu** iki aşamalı API | MCP üzerinden çağıran model oracle'ın kendisidir; kör denetimler ölçülen uyuşmayı dürüst tutar |
| Tedarik zinciri | Çekirdekte sıfır bağımlılık; benchmark verileri SHA-256 ile sabitlenmiş |

## 4. Başarı oranları

### 4.1 Açık benchmark'lar

**Düzenek.** Banking77'de 77 niyet ve 13.083 sorgu, CLINC150'de 150 niyet ve 22.500 sorgu var. Her veri seti tohumlu rastgele bir sırayla bir kez akıtıldı. Oracle olarak veri setinin kendi etiketi kullanıldı; bu yüzden *hata* hem oracle ile ayrışma hem de gerçek doğruya göre hatadır. Değerler 0–2 tohumlarının ortalamasıdır ve denetim oranı %5'tir. *Çağrı/karar* sütunu, denetimler dahil karar başına oracle çağrısını gösterir; her kararı oracle'a sormak 1,00 demektir.

**α = %5:**

| Refleks | Politika | Banking77 yerel / hata / çağrı | CLINC150 yerel / hata / çağrı |
|---|---|---|---|
| — | saf eşik τ = 0,5 (garantisiz) | %85,9 / **%18,80** / 0,14 | %87,2 / **%10,41** / 0,13 |
| — | elle ayarlanmış eşik τ = 0,9 (garantisiz) | %65,4 / %2,89 / 0,35 | %73,5 / %1,47 / 0,27 |
| n-gram | conformal | %54,7 / %1,28 / 0,48 | %74,7 / %2,16 / 0,29 |
| n-gram | LTT | %63,9 / %2,47 / 0,39 | %79,5 / %3,19 / 0,25 |
| MiniLM + k-NN | LTT | %70,7 / %1,82 / 0,33 | %81,9 / %2,58 / 0,22 |
| **bge-small + k-NN** | **LTT** | **%79,6 / %2,14 / 0,25** | **%89,8 / %3,18 / 0,15** |

**bge-small + k-NN refleksiyle, farklı α değerlerinde LTT:**

| α | Banking77 yerel / hata | CLINC150 yerel / hata |
|---|---|---|
| %2 | %61,2 / %0,54 | %80,3 / %0,72 |
| %5 | %79,6 / %2,14 | %89,8 / %3,18 |
| %10 | %89,3 / %6,14 | %94,1 / %6,19 |

**Öne çıkan rakamlar:**

| Ölçüt | Değer |
|---|---|
| Garantinin tuttuğu koşu | **126 / 126**, her tohum ayrı ayrı kontrol edildi |
| α = %5'te ortadan kalkan oracle çağrısı (en iyi yapılandırma) | **%75** (Banking77), **%85** (CLINC150) |
| Anlamsal refleksin oracle çağrısına etkisi (α = %5) | −%36 (Banking77), −%40 (CLINC150) |
| LTT ve conformal karşılaştırması | 18 yapılandırmanın 16'sında LTT en az conformal kadar çok kararı yerelde verdi; kalan 2'si bir standart sapmanın içinde |
| Saf güven eşiği | Hiçbir uyarı vermeden %10–19 hata |

### 4.2 Simüle destek masası

6.000 talep, %2 hatalı simüle bir oracle, akışın %30–33'ünde bir oracle kesintisi ve %50'sinde bir kelime kayması:

| | Yerel | Denetimde uyuşma | Gerçekleşen kapsamama | Yalnız oracle'a göre harcama |
|---|---|---|---|---|
| `route_ticket` (marjinal, α = %5) | %94,3 | %99,1 | %3,0 | $6,83 / $72 |
| `is_urgent` (etiket başına, α = %5) | %62,6 | %97,8 | %3,7 | $28,09 / $72 |

### 4.3 Ajanın oracle olduğu MCP

1.200 simüle vakada ajan her bileti kendisi çözdü. İkinci yarıda kararların **%60'tan fazlasını** Kadı tek başına verdi ve toplam hata ≤ %5 kaldı. Denetim biletleri Kadı'nın kendi cevabını hiçbir zaman göstermedi.

## 5. Ters gidenler ve nasıl düzeltildikleri

### 5.1 Kalibrasyon seçim yanlılığı

- **Belirti.** Canlı panelde etiket başına garantili `is_urgent` sorusunda denetim uyuşması **%42** çıktı. Vaat edilen değer %95'ti.
- **Sebep.** Kalibrasyon yalnızca oracle'a gönderilen örneklerden besleniyordu. Bir örnek, tahmin kümesi birden fazla etiket içerdiği *için* oracle'a gider; bu yüzden doğru etiket tanım gereği zaten kümenin içindedir. Sistem kapsamanın mükemmel olduğunu sandı ve eşiği gevşetti. Kümeler küçüldü, gözlenmeyen yanlış yerel cevaplar arttı ve döngü kendi kendini besledi.
- **Düzeltme.** Kalibrasyon artık akıştan rastgele seçilen ve eğitimde hiç kullanılmayan örneklerle yapılıyor. Saklanan girdiler güncel modelle yeniden puanlanıyor.
- **Kalıcılık.** `TestGuarantee` testi, bu hatanın geri dönmesini engelliyor.

### 5.2 Oracle'ın gürültü tabanı

- **Ne oldu.** %2 hatalı bir oracle ve α = %3 ile kararların yalnızca ~%46'sı yerelde kaldı; Kadı neredeyse her şeyi oracle'a gönderdi.
- **Neden doğru davranış.** Hiçbir sistem, oracle'ın kendi kendisiyle uyuştuğundan daha sık oracle'la uyuşamaz. α bu gürültüye çok yakın seçilirse garantiyi korumanın tek yolu kararları oracle'a göndermektir.
- **Ne değişti.** "α'yı oracle'ın gürültü tabanının üstünde seçin" kuralı belgelere eklendi.

### 5.3 Saldırgan gözüyle güvenlik denetimi

Bağımsız inceleme **11 sorun** buldu. Hepsi düzeltildi ve her biri için bir regresyon testi yazıldı. En ciddileri:

- tokensız yerel sunucuya CSRF ve DNS rebinding;
- gölge modun kalıcı olarak gözetim modunda takılması;
- rastgele 100 bin karakterlik girdilerle belleğin 841 MB'a şişirilebilmesi;
- negatif `Content-Length` ile gövde limitinin aşılması;
- maskelemenin farklı girdileri aynı hafıza anahtarında birleştirmesi;
- denetimin, oracle'ın az önce reddettiği etiketi döndürmesi.

### 5.4 Diğer dersler

- **Hiç tetiklenmeyen sapma testi.** Oracle etiketleri ters çevirdiğinde Kadı ~40 kararda yeniden öğrendi; kesicinin devreye girmemesi doğru davranıştı. Test, kesiciyi doğrudan sınayacak şekilde yeniden yazıldı.
- **Etiket başına garanti 77–150 etikette ölçeklenmiyor.** Her etiketin kendi kanıtını toplaması gerekiyor. Bu durum belgelendi: az etiketli sorularda kullanılmalı.
- **Eskimiş rakamlar.** Motor değiştikten sonra demo tablosu eski haliyle bırakılmadı, yeniden ölçüldü.
- **Açıklanamayan tek test hatası.** v0.5 geliştirilirken testler bir kez düştü; sonraki 24 çalıştırmada ve CI'da tekrarlanmadı. Saklamak yerine burada kayda geçirildi.

## 6. Doğrulama envanteri

| Kontrol | Sonuç |
|---|---|
| Birim, entegrasyon, güvenlik regresyonu ve MCP testleri | **87 test**; numpy gerektiren 2 test standart Python ortamında atlanıyor |
| LTT sertifikasının geçerliliği | 300 simülasyonda yanılma oranı δ sınırında kaldı (test toleransı +0,03) |
| CI | Python 3.11, 3.12, 3.13; anlamsal refleks; TypeScript tip denetimi; Docker. v0.5.0'da hepsi yeşil |
| Defter bütünlüğü | Değiştirilmiş, silinmiş ve araya eklenmiş satırlar ile yanlış anahtar testlerde yakalanıyor |
| MCP | Eski ve yeni (2026-07-28) protokol el sıkışması, JSON-RPC hataları, öğrenme döngüsü, yeniden başlatmada kalıcılık, gerçek alt süreçle stdio uçtan uca testi |

## 7. Henüz doğrulanmayanlar

| Eksik | Nasıl kapanır |
|---|---|
| Benchmark'larda oracle olarak **gerçek LLM** yerine veri setinin etiketleri kullanıldı | API anahtarıyla `python benchmarks/run.py --oracle anthropic --n 2000` |
| **Türkçe** benchmark yok | Çok dilli refleksle Türkçe bir niyet veri seti koşmak |
| **Gerçek bir MCP istemcisiyle** (Claude Code/Desktop) denenmedi | Tekrar eden sınıflandırma işi olan bir projede `claude mcp add kadi -- kadi mcp` |
| Tek süreç + SQLite | Postgres desteği (yol haritasında) |
| Canlı trafikte çalışmadı | Gerçek bir uygulamada sırasıyla replay → gölge → canlı |

## 8. Her şeyi yeniden üretmek

```bash
python -m unittest discover -s tests                         # 87 test
python examples/demo.py                                      # demo + panel, :8765
python benchmarks/run.py                                     # n-gram refleksi (~3,5 MB indirme, SHA-256 doğrulamalı)
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -e ".[embed]"
.venv/bin/python benchmarks/run.py --reflex bge --knn --policies conformal,ltt --taus "" --tag=-bge-knn
```
