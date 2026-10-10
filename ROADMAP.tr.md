# Kadı Yol Haritası

Bu yol haritası beş mühendislik incelemesinden çıktı: istatistik, makine öğrenmesi, sistem, güvenlik ve araştırma/ekosistem. Her mühendis kodu ve belgeleri bağımsız olarak okudu; birkaçı ölçüm de yaptı. Maddeler öncelik sırasına göre dizildi ve **geçerlilik düzeltmeleri en başta**. İngilizce sürüm: [ROADMAP.md](ROADMAP.md).

## P0: Doğruluk ve geçerlilik (yeni özelliklerden önce)

| # | Madde | Neden | Bitti sayılması için |
|---|---|---|---|
| 1 | **Her an geçerli sertifika ve izleme** (güven dizileri ve bahis tabanlı sınırlar; Howard vd. 2021, Waudby-Smith & Ramdas 2024) | LTT her örnekte yeniden sertifikalanıyor, bu yüzden "≥ 1−δ olasılıkla" ifadesi her an için ayrı ayrı geçerli, bütün zaman boyunca birden değil. Sapma kesicisi de Pr(yanlış \| yerel) oranını Wald aralığıyla, örtüşen pencerelerde test ediyor | 10⁶ simüle kararda yanlış gözetim oranı ≤ δ′; regresyon testiyle sabitlenmiş |
| 2 | **Dondurulmuş model anlık görüntülerini sertifikalamak** | Eğitimden ayrı tutulan örnekler, hangi yükseltmelerin refleksi eğiteceğini dolaylı olarak etkiliyor. "Model kalibrasyondan bağımsız" varsayımı yalnızca yaklaşık doğru | Saldırgan geri beslemede bile simüle ihlaller ≤ δ; her kararda sertifika ve model sürümü kayıtlı |
| 3 | **Checkpoint'i sıcak yoldan çıkarmak, ikili formata geçmek** | Ölçüldü: 150 etiketle checkpoint 365 MB JSON; `json.dumps` 6 saniye sürüyor ve bu sürede **o sorunun kilidi tutuluyor** | Checkpoint sırasında refleks p99 değişmiyor; anlık görüntü ≤ 70 MB |
| 4 | ~~Kalan güvenlik bulguları V5–V7~~ | İkinci güvenlik denetimi | ✅ **v0.5.1'de yapıldı**: kesintisiz baştan budama, yanıt başına CSP nonce, hata mesajlarında kısaltılmış tek satırlık yansıtma |
| 5 | **Paket adı** | `kadi` adı PyPI'da başkasına ait (Kadi4Mat); `import kadi` çakışır | `kadi-cascade` adıyla Trusted Publishing üzerinden yayın; import adına karar verilmesi |

İkinci güvenlik denetiminin yedi bulgusunun (V1–V7) tamamı v0.5.1'de düzeltildi; her biri `TestSecurityRegressionsV2` içinde test ediliyor.

## P1: Kanıt (iddiaları inandırıcı kılmak)

- **Gerçek LLM oracle koşuları.** Oracle kararları önbelleğe alınır; böylece tek bir ücretli koşu bütün yapılandırmalar için yeniden kullanılır. Bunlara ek olarak:
  - 1.000 karar başına maliyet hesaplanır;
  - oracle'ın kendi kendisiyle tutarlılığı (ε) ölçülür: madde başına 5 örnek ve ikinci bir model;
  - Kadı↔oracle, oracle↔gerçek etiket ve Kadı↔gerçek etiket uyuşmaları ayrı ayrı raporlanır.
- **Güçlü karşılaştırmalar, ablasyonlar ve istatistik:**
  - **Karşılaştırmalar:** aynı veri bütçesiyle başlangıç diliminde ayarlanmış sabit eşik; FrugalGPT ve RouteLLM tarzı yönlendiriciler.
  - **Ablasyonlar:** sadece yükseltilen örneklerle kalibrasyon (§5.1'deki hata); yeniden puanlama olmadan; ACI olmadan; yenilik koruması olmadan.
  - **İstatistik:** en az 10 tohum, bootstrap güven aralıkları, risk–kapsam eğrileri.
- **Yeni görev türleri:** içerik denetimi, kod inceleme kapısı, ajan araç seçimi.
- **Türkçe benchmark:**
  - MASSIVE tr-TR (niyet sınıflandırma);
  - OffensEval-2020 Türkçe (içerik denetimi; lisansı kontrol edilecek);
  - isteğe bağlı olarak sorumlu biçimde hazırlanmış bir Türkçe destek talebi seti: veri sayfası, iki işaretleyici, κ uyum ölçümü.

## P2: Performans ve ölçek

- **`kadi[fast]`:** numpy ile hızlı yol (ileride Rust); saf Python sürümüyle eşdeğerliği testle doğrulanır. Hedef: CLINC150 koşuları ~10 kat daha hızlı.
- **Oracle hattı:**
  - eşzamansız (async) çağrılar;
  - aynı anda gelen aynı girdiler için tek çağrı;
  - eşzamansız denetimler, yani yerel yol hiç beklemez;
  - prompt önbellekleme;
  - gölge mod, replay ve denetimler için Batch API.

  Hedef: oracle'a giden karar başına en az %40 daha ucuz.
- **Gözlemlenebilirlik:**
  - OpenTelemetry izleri ve katman başına gecikme histogramları;
  - **garanti SLO'su:** denetimde ölçülen ayrışmanın %95 üst sınırı ≤ α; hata bütçesi tükenme hızına göre alarm.
- **MCP:**
  - Streamable HTTP aktarımı;
  - yeniden başlatmada kaybolmayan biletler;
  - MCP Registry'de listeleme.
- **Çoklu sunucu:** Postgres desteği, soru başına ayrı hash zinciri, her soru için seçilmiş tek bir yazıcı.

## P3: Daha akıllı refleks (aynı α'da daha çok yerel karar)

Gerçekleşen hata, %5'lik bütçeye karşı %2–3 civarında; yani bütçenin bir kısmı kullanılmıyor.

1. **Max-p yerine öğrenilmiş seçim skoru.**
   - Girdileri: en olası iki etiket arasındaki fark, k-NN ile lojistik modelin uyuşması, en yakın komşu benzerliği ve yenilik skoru.
   - Prequential olarak öğrenilir; kalibrasyon verisiyle asla eğitilmez.
   - Hedef: α = %5'te Banking77'de yerel oran ≥ %84.
2. **Soğuk başlangıç.** LLM'in ürettiği tohum ifadeler `teach()` ile verilir; ısınma döneminde kalibrasyona ayrılan pay artırılır. Hedef: ilk yerel karardan önce gereken etiket sayısında en az %50 düşüş.
3. **Sınıf prototipleri ve etiket adından öncül bilgi.** Az örneği olan etiketler için k-NN refleksine eklenir.
4. **Çok katmanlı kaskat:** refleks → küçük LLM → frontier; katmanlar birlikte sertifikalanır.
5. **Embedding ince ayarı** (SetFit tarzı), `kadi[train]` ek paketi olarak.
6. **Sıralı ve sınırlı kayıp riski.** Puan (Score) soruları için sıralı kayıp; asimetrik maliyetler ve seçici risk için conformal risk control.
7. **Kümelenmiş conformal** (Ding vd. 2023). Ölçeklenmeyen Mondrian yerine grup başına garanti verir.
8. **Önem ağırlıklı, aktif denetimler** (Zrnic & Candès 2024). Denetim maliyetini düşürür.

## P4: Güvenlik ve gizlilik sertleştirmesi

- **Defter:**
  - kapsama kanıtları sunan bir Merkle günlüğü;
  - imzalı ağaç başlarının dışarıya sabitlenmesi (Sigstore Rekor ya da RFC 3161 zaman damgası);
  - model checkpoint özetlerinin de günlüğe yazılması;
  - `KADI_SECRET` olmadan çalışmayı reddetmek.
- **Tedarik zinciri:**
  - GitHub Action'ları ve imajları SHA veya digest ile sabitlemek;
  - `--require-hashes` ile kurulum;
  - Sigstore imzalı sürümler ve SLSA provenance;
  - CycloneDX SBOM;
  - OSSF Scorecard ≥ 8.
- **Fuzzing:** maskeleme, prompt oluşturucu, MCP ayrıştırıcısı ve HTTP işleyicileri için Atheris / ClusterFuzzLite.
- **Kimlik:**
  - OIDC/JWT ile roller: `decide`, `teach`, `read`, `admin`;
  - her defter satırında çağıranın kimliği;
  - hız sınırı kimlik doğrulamadan sonra.
- **Zehirlemeye karşı direnç:**
  - kaynak başına kota;
  - kırpılmış güncellemeler;
  - öğretme etiketleri için karantina;
  - kanarya seti ve geri alma.
- **Şifreleme ve KVKK/GDPR silme hakkı:**
  - zarf şifreleme;
  - kişi başına anahtar imhası (crypto-shredding). Zincir yalnızca taahhütleri tuttuğu için silme sonrasında da doğrulanmaya devam eder.
  - k-NN embedding hafızasında veri minimizasyonu.

## P5: Araştırma ve yaygınlaşma

- **Makale:** *Certified Cascades: Online Learn-then-Test Routing of LLM Decisions with Held-out, Re-scored Calibration.*
  - **İddialar:**
    - **C1:** kalibrasyon yanlılığı ve çözümü;
    - **C2:** her an geçerli garanti (P0 #1);
    - **C3:** gerçek oracle ile çağrılarda %60–85 azalma;
    - **C4:** ajanın oracle olduğu kurgu.
  - **Plan:** önce bir çalıştay makalesi, sonra TMLR ya da ICML.
- **Entegrasyonlar:**
  - LangGraph düğümü;
  - LlamaIndex yönlendiricisi;
  - OpenAI Agents SDK koruyucusu;
  - `kadi replay` defteri (notebook);
  - İngilizce ve Türkçe belge sitesi.
- **90 günlük hedefler:**
  - `pip install` çalışıyor;
  - gerçek oracle ve Türkçe sonuç tabloları yayında;
  - en az 3 gölge mod kurulumu;
  - en az 10 dış issue.

## Moonshot: Kanıt taşıyan kararlar

Motoru deterministik hale getirmek: model durumu, defterin saf bir fonksiyonu olur. Ardından her karar imzalı bir makbuz taşır:

- Merkle kapsama kanıtı;
- model anlık görüntüsünün özeti;
- sertifika durumu;
- küçük doğrusal ve conformal adım için isteğe bağlı bir zk kanıtı.

Böylece herkes günlüğü baştan oynatıp her yerel kararın, verildiği anda geçerli bir sertifikayla korunduğunu doğrulayabilir; üstelik ham veriyi görmeden. Düzenlemeye tabi kurumların (AB Yapay Zekâ Yasası, KVKK, BDDK) ihtiyaç duyacağı standart budur.
