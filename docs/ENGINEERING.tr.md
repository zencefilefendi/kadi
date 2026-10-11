# Kadı: Mühendislik Raporu

Bu rapor neyin yapıldığını, hangi tekniklerin neden kullanıldığını, neyin ölçüldüğünü, nelerin ters gidip nasıl düzeltildiğini ve neyin henüz doğrulanmadığını anlatır. Buradaki her rakam bu repodaki dosyalardan yeniden üretilebilir. Formel ifadeler [THEORY.md](THEORY.md), güvenlik ayrıntıları [THREAT_MODEL.md](THREAT_MODEL.md) belgesindedir. İngilizce sürüm: [ENGINEERING.md](ENGINEERING.md).

---

## 1. Tek paragrafta problem ve çözüm

LLM ajanları çok sayıda küçük, çoktan seçmeli karar verir. Frontier model bu kararları doğru verir ama yavaş ve pahalıdır. Küçük bir model ucuzdur ama hata oranı bilinmez.

Kadı üç katmanlı bir kaskattır: önce birebir hafıza, sonra yerel refleks, en son oracle. Refleks, **yalnızca istatistiksel bir test** yerel cevabın oracle ile ayrışmasını kullanıcının seçtiği α'nın altında tuttuğunu sertifikaladığında cevap verir. Geri kalan her şey oracle'a gider ve her yükseltme refleksi eğitir.

v0.6'dan itibaren kararları yalnızca **dondurulmuş** model sürümleri veriyor. Her sürüm, dondurulduktan sonra gelen verilerle sertifikalanıyor; Learn-then-Test sertifikası da zamanın her anında geçerli. İki açık niyet sınıflandırma benchmark'ında Kadı, **α = %5'te oracle çağrılarının %65–79'unu ortadan kaldırdı**; her an geçerli LTT sertifikasıyla bu oran %61–73. Hata sınırı **126 koşunun 126'sında** tuttu.

## 2. Sürüm geçmişi

| Sürüm | Getirdiği |
|---|---|
| 0.1 | Prototip: hafıza → refleks → oracle kaskatı, adaptif conformal tahmin, panel |
| 0.2 | Üretim katmanı: gölge mod, replay, Mondrian conformal, sapma kesicisi, fallback, PII maskeleme, sertleştirilmiş HTTP API, TypeScript istemcisi, Docker, CI. Ayrıca **kalibrasyon seçim yanlılığı hatası** (§5.1) ve **güvenlik denetiminin 11 bulgusu** (§5.3) düzeltildi |
| 0.3 | Learn then Test (yüksek olasılıklı garanti), kurcalanamaz defter, açık benchmark |
| 0.4 | Anlamsal refleks: cümle embedding'leri + k-NN (isteğe bağlı ek paket) |
| 0.4.1 | Belge yaması: durum ve sınırlar, yeniden ölçülen demo |
| 0.5 | **Ajanın oracle olduğu** MCP sunucusu (API anahtarı gerekmez) |
| 0.5.1 | İkinci güvenlik denetimi (V1–V7 düzeltildi), beş mühendislik yol haritası, istatistiksel kısıtların belgelenmesi |
| 0.7 | **Yol haritası P1 (kanıt)**: Türkçe ve içerik denetimi benchmark'ları, adil karşılaştırma yöntemleri, ablasyonlar, bootstrap güven aralıkları ve Clopper–Pearson sınırlarıyla 10 tohumlu istatistik, simüle gürültülü oracle, gerçek oracle altyapısı (karar önbelleği, maliyet tahmini, tutarlılık ölçümü) |
| 0.6 | **Yol haritası P0**: dondurulmuş model sürümleri, her an geçerli LTT, e-detektör, sürümler arası δ harcaması, boş küme kuralı, uyarlamalı bedava örnekleme, kilit dışı ikili checkpoint, `kadi-cascade` dağıtım adı |

## 3. Kullanılan teknikler

### 3.1 İstatistik: Kadı ne zaman tek başına karar verebilir?

| Teknik | Nerede | Neden | Kaynak |
|---|---|---|---|
| Split conformal tahmin | `kadi/conformal.py` | Herhangi bir skoru, kapsaması ≥ 1 − α olan kümelere çevirir; yalnızca \|C(x)\| ≤ 1 olduğunda cevap vermek ayrışmayı sınırlar | Vovk vd. 2005; Papadopoulos vd. 2002; Lei vd. 2018 |
| Boş küme kuralı (v0.6) | `engine._route` | Boş küme zaten bir kapsamama olayıdır; orada en olası etiketi vermek α'ya hiçbir şey eklemez ve yerel oranı α'ya göre tutarlı (monoton) kılar | — |
| Adaptive Conformal Inference | `alpha_t` | Trafik değiştikçe uzun dönem kapsamamayı α civarında tutar | Gibbs & Candès 2021 |
| Mondrian (etiket başına) conformal | `MondrianConformal` | Nadir ama kritik bir etikete kendi sınırını verir | Vovk 2012 |
| **Her an geçerli Learn then Test** (v0.6) | `LearnThenTest` | Her eşik için bahis e-süreci ve Ville eşitsizliği: risk ≤ α, ≥ 1 − δ olasılıkla, **zamanın her anında birden** | Angelopoulos vd. 2021; Ramdas vd. 2023; Waudby-Smith & Ramdas 2024 |
| **Dondurulmuş model sürümleri** (v0.6) | `engine._Brain` (`live`, `served`, `candidate`) | Puanlayan model kalibrasyon verisinden gerçekten bağımsız: her sürüm yalnızca dondurulduktan sonra gelen örneklerle kalibre edilir; hiçbir şey yeniden puanlanmaz | — |
| **Sürümler arası δ harcaması** (v0.6) | `version_delta` | δ_v = δ·6/(π²v²) toplamı δ'dır; tüm sertifikalar aynı anda geçerli olur, terfi kuralı ne olursa olsun güvenlidir | — |
| Girdiden bağımsız rastgele örnekleme | `engine._route` | Kalibrasyon yazı-turası yalnızca geçmişe bağlıdır (§5.1); oracle'a giden kararlar bedavaya örneklenir, yerel cevaplar `sample_budget` içinde kalır | — |
| Tutarlılık kuralı | `_route` | Tek elemanlı küme modelin en olası etiketiyle uyuşmazsa karar oracle'a gider | — |

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
| **Sapma e-detektörü** (v0.6) | Sunulan sürümün birleşik riski Shiryaev–Roberts e-detektörüyle izlenir; yanlış alarmın beklenen zamanı ≥ ARL. Alarmda sunulan sürüm yeniden sertifikalanır, gözetim moduna geçilir ve webhook alarmı gider (Shin, Ramdas & Rinaldo) |
| Gölge mod ve replay | Canlıya almadan önce değeri risksiz kanıtlar |
| Fallback | Oracle çöktüğünde işaretli yerel cevap döner |
| Kurcalanamaz defter | Her karar bir öncekine HMAC ile zincirlenir; `kadi verify` ve `kadi anchor` |
| Sağlama toplamlı PII maskeleme | TC kimlik numarası (algoritmik kontrol), IBAN (mod-97), kart numarası (Luhn + IIN), telefon, e-posta, API anahtarları |
| Sertleştirilmiş HTTP | Sabit zamanlı token doğrulaması, CSRF ve DNS rebinding korumaları, hız sınırı, gövde limitleri, CSP |
| Prompt injection ayraçları | Kullanıcı metni oracle'a "güvenilmez veri" olarak işaretlenmiş gider; çıktı, tanımlı seçeneklere kilitlidir |
| **Ajanın oracle olduğu** iki aşamalı API | MCP üzerinden çağıran model oracle'ın kendisidir; kör denetimler ölçülen uyuşmayı dürüst tutar |
| Tedarik zinciri | Çekirdekte sıfır bağımlılık; benchmark verileri SHA-256 ile sabitlenmiş |
| **Kilit dışı ikili checkpoint** (v0.6) | Kilit altında ~10 ms'lik yakalama; paketleme (float32, canlı modelle ortak satırlar tekrar yazılmaz) ve atomik yazma arka planda; SHA-256 SQLite'ta saklanır, kurcalanmış dosya reddedilir |

## 4. Başarı oranları

### 4.1 Açık benchmark'lar

**Düzenek.**
- **Veri setleri.** Banking77'de 77 niyet ve 13.083 sorgu, CLINC150'de 150 niyet ve 22.500 sorgu var.
- **Yöntem.** Her veri seti tohumlu rastgele bir sırayla bir kez akıtıldı. Oracle olarak veri setinin kendi etiketi kullanıldı; bu yüzden *hata* hem oracle ile ayrışma hem de gerçek doğruya göre hatadır. Değerler v0.6 motoruyla, 0–2 tohumlarının ortalamasıdır.
- **Çağrı** = karar başına oracle çağrısı, denetimler dahil; her kararı oracle'a sormak 1,00 demektir.

**α = %5:**

| Refleks | Politika | Banking77 yerel / hata / çağrı | CLINC150 yerel / hata / çağrı |
|---|---|---|---|
| — | saf eşik τ = 0,5 (garantisiz) | %85,9 / **%18,80** / 0,14 | %87,2 / **%10,41** / 0,13 |
| — | elle ayarlanmış eşik τ = 0,9 (garantisiz) | %65,4 / %2,89 / 0,35 | %73,5 / %1,47 / 0,27 |
| n-gram | conformal | %46,7 / %1,15 / 0,58 | %64,2 / %1,69 / 0,41 |
| n-gram | LTT | %49,1 / %1,66 / 0,56 | %65,2 / %1,72 / 0,40 |
| MiniLM + k-NN | conformal | %63,8 / %2,46 / 0,42 | %77,4 / %3,27 / 0,28 |
| MiniLM + k-NN | LTT | %57,4 / %1,92 / 0,48 | %71,4 / %1,14 / 0,34 |
| **bge-small + k-NN** | **conformal** | **%70,2 / %2,52 / 0,35** | **%84,7 / %3,40 / 0,21** |
| **bge-small + k-NN** | **LTT** | **%66,2 / %1,74 / 0,39** | **%78,1 / %1,32 / 0,27** |

**Öne çıkan rakamlar:**

| Ölçüt | Değer |
|---|---|
| Garantinin tuttuğu koşu | **126 / 126**, her tohum ayrı ayrı kontrol edildi |
| α = %5'te ortadan kalkan oracle çağrısı (en iyi yapılandırma) | **%65** (Banking77), **%79** (CLINC150) bge + conformal ile; her an geçerli LTT ile %61 / %73 |
| Katı geçerliliğin yerel orana bedeli (v0.6 ve v0.5) | 36 yapılandırmada medyan 9,3 puan (aralık −1,5 ile +19,7) |
| Conformal ve LTT | Conformal 18 yapılandırmanın 13'ünde daha çok yerel karar verdi (garantisi daha zayıf) |
| Saf güven eşiği | Hiçbir uyarı vermeden %10–19 hata |

v0.5 rakamları git geçmişinde, `v0.5.1` etiketinde duruyor.

### 4.1b P1 kanıtı (v0.7): beş veri seti, adil karşılaştırma, ablasyonlar

Tam rapor: [benchmarks/results/p1/REPORT.md](../benchmarks/results/p1/REPORT.md).

**Düzenek.**
- **Veri setleri:** iki dilde beş veri seti. Banking77, CLINC150, MASSIVE tr-TR, OffensEval-2020 TR, Measuring Hate Speech.
- **Izgara:** 10 tohum, α ∈ {%2, %5, %10}, iki refleks.
- **Karşılaştırma yöntemleri:** ayarlanmış eşik ve öğrenilmiş erteleme; ikisi de aynı 500 etiketlik başlangıç dilimiyle ayarlandı.

| Yöntem | Vaadi | Hedefi aşan koşu | Ortalaması hedefi aşan hücre |
|---|---|---|---|
| Kadı LTT | %95 olasılıkla ve her an risk ≤ α | **0/220** (CP95 ≤ %1,4) | **0/22** |
| Kadı conformal | ortalamada risk ≤ α | 26/220 | **0/22** |
| ayarlanmış eşik | yok | 34/220 | 3/22 |
| öğrenilmiş erteleme | yok | 57/220 | 4/22 |

**Ne gösteriyor?**
- **Kadı'nın her politikası tam olarak kendi sözünü tutuyor.** Kalibrasyonsuz yöntemler bazı veri setlerinde çok iyi, bazılarında sessizce bozuk. Örneğin MASSIVE-tr'de n-gram refleksiyle öğrenilmiş erteleme 10 koşunun 10'unda hedefi aştı.
- **Ablasyonlar v0.1'deki seçim yanlılığı hatasını yeniden üretiyor.** İkili denetim görevinde α = %5'te %18 hata çıkıyor; niyet görevlerinde ise aynı hata zararsız biçimde tutucu kalıyor.
- **Bedava, uyarlamalı örnekleme** yerel orana 0,6–11,9 puan (medyan 7) katıyor.
- **Dondurulmuş sürümler** 5–14 puana mal oluyor; dondurma kapatıldığında da ihlal görülmüyor. Kazandırdıkları şey kanıtlanabilirlik, gözlenen bir hatanın önlenmesi değil.
- **%3 gürültülü oracle'da** Kadı oracle'a göre α içinde kalıyor; gerçek etikete göre hatası gürültü tabanında.

### 4.2 Simüle destek masası

6.000 talep, %2 hatalı simüle bir oracle, akışın %30–33'ünde bir oracle kesintisi ve %50'sinde bir kelime kayması:

| | Yerel | Denetimde uyuşma | Gerçekleşen kapsamama | Yalnız oracle'a göre harcama |
|---|---|---|---|---|
| `route_ticket` (marjinal, α = %5) | %77,8 | %94,9 | %6,3 | $19,96 / $72 |
| `is_urgent` (etiket başına, α = %5) | %52,2 | %95,5 | %5,5 | $36,73 / $72 |

v0.6 ile ölçüldü. Denetimlerden tahmin edilen karar düzeyindeki hata, yani yerel oran × denetimde ayrışma, **%4,0 ve %2,3** ile α'nın altında. Kalibrasyon örneklerindeki küme kapsamaması ise α'nın biraz üstünde. Ortalamada geçerli bir garanti buna izin verir: koşu bir kesinti, bir kayma ve gürültülü bir oracle içeriyor (bkz. THEORY §7c, §9). v0.4'e göre (%94,3 / %62,6 yerel) burada da katı geçerliliğin bedeli görülüyor.

### 4.3 Ajanın oracle olduğu MCP

1.200 simüle vakada ajan her bileti kendisi çözdü. İkinci yarıda kararların **%60'tan fazlasını** Kadı tek başına verdi ve toplam hata ≤ %5 kaldı. Denetim biletleri Kadı'nın kendi cevabını hiçbir zaman göstermedi.

## 5. Ters gidenler ve nasıl düzeltildikleri

### 5.1 Kalibrasyon seçim yanlılığı

- **Belirti.** Canlı panelde etiket başına garantili `is_urgent` sorusunda denetim uyuşması **%42** çıktı. Vaat edilen değer %95'ti.
- **Sebep.** Kalibrasyon yalnızca oracle'a gönderilen örneklerden besleniyordu. Bir örnek, tahmin kümesi birden fazla etiket içerdiği *için* oracle'a gider; bu yüzden doğru etiket tanım gereği zaten kümenin içindedir. Sistem kapsamanın mükemmel olduğunu sandı ve eşiği gevşetti. Kümeler küçüldü, gözlenmeyen yanlış yerel cevaplar arttı ve döngü kendi kendini besledi.
- **Düzeltme.** Kalibrasyon artık akıştan rastgele seçilen ve eğitimde hiç kullanılmayan örneklerle yapılıyor. v0.2–v0.5'te saklanan girdiler güncel modelle yeniden puanlanıyordu. v0.6'dan itibaren her dondurulmuş sürüm yalnızca kendinden sonra gelen örneklerle kalibre ediliyor; hiçbir şey yeniden puanlanmıyor.
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

### 5.4 İkinci güvenlik denetimi (v0.5)

Beş mühendislik yol haritası çalışması sırasında yapılan ikinci bağımsız inceleme **7 sorun daha** buldu. Hepsi düzeltildi ve her biri için bir regresyon testi var (`TestSecurityRegressionsV2`):

- **V1:** zincir başladıktan sonra özetsiz satırlar eklenip `verify`'dan kaçırılabiliyordu.
- **V2:** prompt ayraçları iç içe yazılarak (`</in</input>put>`) sahtelenebiliyordu, çünkü etiketler kaçırılmak yerine siliniyordu.
- **V3:** derin iç içe tek bir JSON satırı MCP sunucusunu çökertiyordu.
- **V4:** hız sınırı kimlik doğrulamadan önce uygulandığı için hatalı tokenlar gerçek kullanıcıların kotasını tüketebiliyordu.
- **V5:** saat geriye kaydığında budama işlemi zinciri ortadan kesebiliyordu.
- **V6:** panelin CSP'si `'unsafe-inline'` script'e izin veriyordu; artık her yanıtta yeni bir nonce kullanılıyor.
- **V7:** çağıranın metni, LLM ajanlarına geri dönen hata mesajlarına olduğu gibi yansıyordu; artık kısaltılıyor ve tek satıra indiriliyor.

Aynı inceleme THEORY §7c'deki istatistiksel kısıtları da ortaya çıkardı.

### 5.5 v0.6: Katı geçerliliğin bedeli ve bedelin mühendislikle düşürülmesi

Yol haritasındaki P0 maddeleri (dondurulmuş sürümler, her an geçerli sertifika, ARL kontrollü dedektör) garantiyi tam hale getiriyor. Bunun bedeli ayrı ayar tohumlarında ölçüldü (Banking77, 4.000 karar, LTT α = %5) ve üç adımda düşürüldü:

| Adım | n-gram yerel | bge + k-NN yerel |
|---|---|---|
| v0.5 (yaklaşık geçerlilik) | %37,2* | %56,0* |
| v0.6 ilk deneme: sabit %5–10 örnekleme | %10,1* | %22,2* |
| + oracle'a giden kararları bedava örneklemek, `sample_budget`'a göre uyarlamalı oran | %21,0* | %37,2* |
| + LTT'de yerel paya göre terfi, ilk dondurma 300 etikette | ~%24–25 | ~%44–46 |

<sub>*0–1 tohumlarında ölçüldü. Sonraki satırlar 100–101 ayar tohumlarında ölçüldü; son yapılandırma §4.1'deki rakamlar için 0–2 tohumlarında yalnızca bir kez değerlendirildi.</sub>

Her adımın dayandığı fikir:

1. **Bedava örnekleme.** Her kalibrasyon etiketi, kendinden önce dondurulmuş sürümleri kalibre ettikten *sonra* canlı modeli de eğitebiliyor. Bu yüzden oracle'a giden bir kararı örneklemek bedava. Oran geçmişe (son yerel paya) bağlı olabilir, mevcut girdiye asla.
2. **Paya göre terfi.** δ harcaması tüm sertifikaları aynı anda geçerli kıldığı için, adayın kendi örnekleri üzerinde daha sık cevap veren sertifikalı sürüm güvenle seçilebiliyor.
3. **Boş küme kuralı.** Bir replay testi, α gevşedikçe conformal'ın yerel oranının *düştüğünü* gösterdi: sıkılaşan eşikler boş kümeler üretiyor, bunlar da oracle'a gidiyordu. Boş küme zaten bir kapsamama olayı; orada en olası etiketi vermek α'ya hiçbir şey eklemiyor. Düzeltmeyle tutarlılık geri geldi.

Kalan fark, tam ve her an geçerli bir garantinin dürüst bedeli. Yol haritasının P3'ü (öğrenilmiş seçim skoru, uyarlamalı bahis, soğuk başlangıç tohumları) bu farkı hedefliyor.

**Checkpoint.** CLINC150 ölçeğinde bir mahkemede ölçüldü: 75 bin özellik × 120 etiket, 14 sürüm.

| | v0.5 (JSON, kilit altında) | v0.6 (ikili, arka planda) |
|---|---|---|
| Kilidin tutulduğu süre | **5,82 s** | **0,011 s** |
| Boyut | 411 MB | **43 MB** |
| Yazma | kilit altında | 1,71 s, kilit dışında |
| Yükleme | — | 0,75 s |

### 5.6 P1 kanıtını üretirken bulunan hatalar

- **Benchmark'ta maskeleme uyuşmazlığı.** Kadı özellik çıkarmadan önce kişisel verileri maskeliyor. Telefon numarası içeren bir Türkçe tweet bu yüzden embedding tablosuna `<PHONE>` olarak ulaştı; tablo ise ham metinle eşleştirilmişti ve koşu çöktü. Banking77 ve CLINC150'de kişisel veri olmadığı için bu daha önce hiç görülmemişti. Düzeltme: tabloda olmayan metin aynı modelle anında embed ediliyor.
- **k-NN matrisinin her adımda yeniden kurulması.** Canlı k-NN modeli her güncellemeden sonra tüm vektör matrisini yeniden kuruyordu; maliyet karesel büyüyor ve karşılaştırma koşuları 400–480 saniye sürüyordu. Düzeltme: artımlı büyüyen bir tampon. Sonuçlar bit düzeyinde aynı (fark 0,0); dondurulmuş anlık görüntüler matrisin kopyasını alıyor.
- **Checkpoint işlerinde değişebilir referanslar.** `no_freeze` ablasyonunda sunulan model doğrudan canlı modelin kendisi olduğu için, arka plan yazıcısı değişmekte olan bir nesneyi paketlemeye çalışıyordu ("dictionary changed size during iteration"). Kalibratör durumları da referansla aktarılıyordu. Düzeltme: canlı modelle aynı nesneyi gösteren sürümler canlı anlık görüntüden paketleniyor ve tüm durum kilit altında derin kopyalanıyor. Regresyon testi eklendi.
- **Conformal'ın koşu başına davranışı.** ACI gerçekleşen kapsamamayı bilerek α'ya *yaklaştırıyor*. Bu yüzden zor ikili görevlerde tek tek koşuların ~%12'si α'nın biraz üstünde bitiyor, ama her hücrenin ortalaması altında kalıyor. Önceki belgeler iki politikayı ayırmadan "garanti her koşuda tuttu" diyordu. Artık ayrım net: LTT koşu başına ve zamandan bağımsız garanti veriyor; conformal ortalamada.

### 5.7 Diğer dersler

- **Hiç tetiklenmeyen sapma testi.** Oracle etiketleri ters çevirdiğinde Kadı ~40 kararda yeniden öğrendi; kesicinin devreye girmemesi doğru davranıştı. Test, kesiciyi doğrudan sınayacak şekilde yeniden yazıldı.
- **Etiket başına garanti 77–150 etikette ölçeklenmiyor.** Her etiketin kendi kanıtını toplaması gerekiyor. Bu durum belgelendi: az etiketli sorularda kullanılmalı.
- **Eskimiş rakamlar.** Motor değiştikten sonra demo tablosu eski haliyle bırakılmadı, yeniden ölçüldü.
- **Açıklanamayan tek test hatası.** v0.5 geliştirilirken testler bir kez düştü; sonraki 24 çalıştırmada ve CI'da tekrarlanmadı. Saklamak yerine burada kayda geçirildi.

## 6. Doğrulama envanteri

| Kontrol | Sonuç |
|---|---|
| Birim, entegrasyon, güvenlik regresyonu, MCP ve benchmark altyapısı testleri | **108 test**; numpy gerektiren 2 test standart Python ortamında atlanıyor |
| LTT'nin zaman boyunca geçerliliği | Simülasyon: 1.000 örneklik 200 akış. Sertifikalı eşiğin riskinin *herhangi bir anda* α'yı aştığı akış oranı δ sınırında (test toleransı +0,03) |
| Kesin sertifikalanma zamanı | Tam olarak `min_samples` temiz örnekten sonra sertifikalanıyor (α = δ = %5'te 74), asla daha önce değil |
| δ harcaması | Σ_v δ_v < δ, sayısal olarak doğrulandı |
| E-detektör | H0 altında yanlış alarma kadar geçen ortalama süre ≥ ARL; 4 katlık kaymada 150 örnekten kısa sürede tespit |
| Dondurulmuş sürümler | Canlı model ne kadar eğitilirse eğitilsin sunulan modelin tahminleri değişmiyor; sürümler ve sertifikalar yeniden başlatmada korunuyor; kurcalanmış anlık görüntü reddediliyor; 60 bin özellik × 150 etikette kilit < 0,25 s tutuluyor |
| Uçtan uca sapma | Sertifikalı modelin altında oracle tersine dönüyor: alarm, yeniden sertifikalama, uyarı ve yeni rejimde < %5 hataya dönüş |
| CI | Python 3.11, 3.12, 3.13; anlamsal refleks; TypeScript tip denetimi; Docker |
| Defter bütünlüğü | Değiştirilmiş, silinmiş, araya eklenmiş ve zincirsiz satırlar ile yanlış anahtar yakalanıyor |
| MCP | Eski ve yeni (2026-07-28) protokol el sıkışması, JSON-RPC hataları, öğrenme döngüsü, yeniden başlatmada kalıcılık, gerçek alt süreçle stdio uçtan uca testi |

## 7. Henüz doğrulanmayanlar

| Eksik | Nasıl kapanır |
|---|---|
| Benchmark'larda oracle olarak **gerçek LLM** yerine veri setinin etiketleri kullanıldı | API anahtarıyla `python benchmarks/run.py --oracle anthropic --n 2000` |
| Kod inceleme kapısı ve ajan araç seçimi görevleri | Uygun açık veri setlerini bulmak ya da oluşturmak |
| **Gerçek bir MCP istemcisiyle** (Claude Code/Desktop) denenmedi | Tekrar eden sınıflandırma işi olan bir projede `claude mcp add kadi -- kadi mcp` |
| Tek süreç; SQLite + anlık görüntü yan dosyaları | Postgres desteği (yol haritasında) |
| Canlı trafikte çalışmadı | Gerçek bir uygulamada sırasıyla replay → gölge → canlı |

## 8. Her şeyi yeniden üretmek

```bash
python -m unittest discover -s tests                         # 108 test
bash benchmarks/results/p1/run_all.sh                        # P1 kanıt matrisi (saatler sürer; [embed] + pyarrow gerekir)
python benchmarks/report.py benchmarks/results/p1            # REPORT.md + risk–kapsam SVG'leri
python examples/demo.py                                      # demo + panel, :8765
python benchmarks/run.py                                     # n-gram refleksi (~3,5 MB indirme, SHA-256 doğrulamalı)
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -e ".[embed]"
.venv/bin/python benchmarks/run.py --reflex bge --knn --policies conformal,ltt --taus "" --tag=-bge-knn
```
