# Kadı Yol Haritası

Bu yol haritası beş mühendislik incelemesinden çıktı: istatistik, makine öğrenmesi, sistem, güvenlik ve araştırma/ekosistem. Her mühendis kodu ve belgeleri bağımsız olarak okudu; birkaçı ölçüm de yaptı. Maddeler öncelik sırasına göre dizildi ve **geçerlilik düzeltmeleri en başta**. İngilizce sürüm: [ROADMAP.md](ROADMAP.md).

## P0: Doğruluk ve geçerlilik — ✅ v0.6'da tamamlandı

| # | Madde | v0.6'daki durum | Kanıt |
|---|---|---|---|
| 1 | **Her an geçerli sertifika ve izleme** | ✅ LTT, bahis e-süreçleri ve Ville eşitsizliğiyle sertifikalanıyor; garanti zaman boyunca geçerli. Wald testine dayalı sapma kesicisinin yerini, sunulan birleşik riski izleyen ve ARL kontrollü bir Shiryaev–Roberts e-detektörü aldı. *Kriter değişti*: detektör, tek bir koşudaki yanlış alarm olasılığını değil, yanlış alarma kadar geçen beklenen sürenin ≥ ARL olmasını garanti ediyor | `test_ltt_certificate_is_anytime_valid` (1.000 örneklik 200 akış), `test_drift_detector_false_alarms_and_detection`, `test_drift_alarm_recertifies_and_alerts` |
| 2 | **Dondurulmuş model anlık görüntülerini sertifikalamak** | ✅ Canlı, sunulan ve aday sürümler var. Her sürüm yalnızca dondurulduktan sonra gelen örneklerle kalibre ediliyor. δ sürümler arasında harcanıyor; böylece tüm sertifikalar aynı anda geçerli. Model sürümü her kararda **hash zincirinin içinde** kaydediliyor. Orijinal kriterdeki "saldırgan geri besleme" simülasyonu ayrıca koşulmadı: bağımsızlık artık yapı gereği sağlanıyor ve motor düzeyindeki sınır testleri geçiyor | `TestVersions`, `test_model_version_is_recorded_and_chained`, `TestGuarantee`; 126/126 benchmark koşusu |
| 3 | **Checkpoint'i sıcak yoldan çıkarmak, ikili format** | ✅ Kilit 11 ms tutuluyor (eskiden 5,82 s). Anlık görüntü 43 MB (eskiden 411 MB JSON). Dosya arka planda ve atomik olarak yazılıyor, yüklenirken SHA-256 ile doğrulanıyor | `test_checkpoint_holds_the_lock_only_briefly`, `test_tampered_snapshot_is_refused`; ENGINEERING §5.5 |
| 4 | Kalan güvenlik bulguları V5–V7 | ✅ v0.5.1'de yapıldı | `TestSecurityRegressionsV2` |
| 5 | **Paket adı** | ◐ Dağıtım adı artık `kadi-cascade`; import adı `kadi` olarak kaldı. **Açık kalanlar**: PyPI'a yayın (bakımcının hesabı ve Trusted Publishing kurulumu gerekiyor) ve Kadi4Mat ile import adı çakışması hakkında nihai karar | `pyproject.toml` |

**Ölçülen bedel.** Katı geçerlilik, 36 benchmark yapılandırmasında yerel karar oranından medyan 9,3 puan götürüyor (aralık −1,5 ile +19,7). P3 bu farkı hedefliyor.

## P1: Kanıt (iddiaları inandırıcı kılmak)

> **Durum (v0.7.0):** büyük ölçüde tamam. Ayrıntılar: [benchmarks/results/p1/REPORT.md](benchmarks/results/p1/REPORT.md).
> - ✅ **Karşılaştırma yöntemleri:** ayarlanmış eşik ve öğrenilmiş erteleme yönlendiricisi (lojistik; FrugalGPT ve RouteLLM tarzında). İkisi de aynı 500 etiketlik başlangıç dilimiyle ayarlandı.
> - ✅ **Ablasyonlar:** yükseltilen örneklerle kalibrasyon, dondurma yok, yenilik koruması yok, tutarlılık denetimi yok, sabit örnekleme.
> - ✅ **İstatistik:** 10 tohum, bootstrap güven aralıkları, Clopper–Pearson sınırları, risk–kapsam grafikleri.
> - ✅ **Türkçe benchmark'lar:** MASSIVE tr-TR ve OffensEval-2020 TR.
> - ✅ **İçerik denetimi:** OffensEval-TR ve Measuring Hate Speech (İngilizce).
> - ✅ **Simüle gürültülü oracle;** üç yönlü metriklerle raporlandı.
> - ⏳ **Gerçek oracle koşusu:** altyapı hazır (karar önbelleği, maliyet tahmini, tutarlılık ölçümü; bkz. [docs/REAL_ORACLE.md](docs/REAL_ORACLE.md)). API anahtarı gerektirdiği için henüz koşulmadı.
> - ⏳ Kod inceleme kapısı ve araç seçimi görevleri.
> - ⏳ Türkçe destek talebi seti.
> - ⏳ ACI'sız ablasyon.


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
