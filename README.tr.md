<div align="center">

# Kadı ⚖︎

**Frontier modelinizin önünde oturan, kalibre edilmiş bir yargıç.**

Rutin kararları yerelde verir. Bu kararların oracle ile ne sıklıkla ayrıştığına dağılımdan bağımsız bir üst sınır koyar.<br>
Geri kalan her şeyi oracle'a yükseltir ve her yükseltmeden öğrenir.

[English](README.md) · [Yol haritası](ROADMAP.tr.md) · [Mühendislik raporu](docs/ENGINEERING.tr.md) · [Teori](docs/THEORY.md) · [Tehdit modeli](docs/THREAT_MODEL.md) · [MCP sunucusu](docs/MCP.md)

</div>

---

## Özet

LLM tabanlı ajanlar ve uygulamalar çok sayıda küçük, şeması belli karar verir: bir talebi doğru ekibe yönlendirmek, spam'i işaretlemek, sıradaki aracı seçmek, bir değişikliği onaylamak gibi. Her birini frontier modele sormak doğru sonuç verir ama yavaş ve pahalıdır. Küçük bir modele sormak ucuzdur ama hata oranı bilinmez.

Kadı üç katmanlı bir kaskattır: **hafıza → yerel refleks → oracle**. Ortadaki katman yalnızca **istatistiksel bir sertifika izin verdiğinde** cevap verir. Bu sertifika ya en fazla bir etiket içeren bir split-conformal tahmin kümesidir ya da bir Learn-then-Test eşiğidir. Değiştirilebilirlik (exchangeability) varsayımı altında bu, dönen bir kararın oracle ile ayrışma olasılığını kullanıcının seçtiği α ile sınırlar. Sınır isteğe bağlı olarak her etiket için ayrı ayrı (Mondrian) tutulabilir; Learn-then-Test ile **≥ 1 − δ olasılıkla ve zamanın her anında** geçerlidir.

Bunu canlı akan (online) bir sistemde doğru yapmak dört mekanizma gerektirir (v0.6):

- **Dondurulmuş model sürümleri.** Canlı model oracle'ın her etiketinden öğrenir, ama kararları yalnızca dondurulmuş anlık görüntüler verir. Her sürüm, dondurulduktan *sonra* gelen örneklerle sertifikalanır. Böylece puanlayan model kalibrasyon verisinden gerçekten bağımsızdır.
- **Rastgele kalibrasyon örnekleri.** Örnekleme yazı-turası girdiye asla bağlı değildir. Oracle'a giden örneklerle kalibrasyon asla yapılmaz.
- **Her an geçerli sertifika.** Bahis e-süreçleri ve Ville eşitsizliği kullanılır; δ sürümler arasında paylaştırılır. Böylece verilen her sertifika zamanın her anında geçerlidir.
- **Sunulan riski izleyen bir e-detektör.** Yanlış alarm aralığı sınırlıdır; alarmda sunulan sürüm yeniden sertifikalanır.

Bunlara ek olarak dağılım dışı ve saldırgan girdilere karşı bir yenilik koruması, gölge mod, KVKK odaklı PII maskeleme ve sertleştirilmiş bir HTTP servisi bulunur. Tamamı Python standart kütüphanesiyle yazılmıştır ve **sıfır bağımlılıklıdır**.

## Nasıl çalışır

| Katman | Gecikme | Maliyet | Ne zaman cevap verir |
|---|---|---|---|
| **Hafıza** | µs | $0 | aynı girdi daha önce oracle'a sorulduysa |
| **Refleks** | ms | $0 | sunulan dondurulmuş sürümün sertifikası izin veriyorsa ve tüm korumalar geçiyorsa |
| **Oracle** | sn | $$ | diğer her durumda; verdiği karar refleksi eğitir |
| **Fallback** | ms | $0 | oracle çöktüyse ve politika `best_guess` ise; işaretlidir, garanti taşımaz |

**Tek satırlık garanti:**

$$
\Pr\big(\hat{y} \neq O(x)\big) \;\le\; \Pr\big(O(x) \notin C(x)\big) \;\le\; \alpha
$$

Bir ayrışma ancak yerel cevapta mümkündür; yerel cevap da ancak |C(x)| ≤ 1 olduğunda verilir. Küme boşsa en olası etiket verilir; bu durum zaten bir kapsamama olayı olarak α bütçesinde sayılmıştır. Tam ifade, varsayımlar, Mondrian varyantı, ACI sınırı ve **neyin garanti edilmediği** [docs/THEORY.md](docs/THEORY.md) belgesindedir.

### İki politika

| `policy` | Yerel cevap koşulu | Garanti | En uygun olduğu yer |
|---|---|---|---|
| `"conformal"` (varsayılan) | conformal küme en fazla bir etiketli | Ayrışma ≤ α, **ortalamada**; ACI kaymaya uyum sağlar; istenirse **etiket başına** | aynı α'da en çok yerel karar; nadir ama kritik etiketler |
| `"ltt"` | max p ≥ λ̂; λ̂ **her an geçerli Learn then Test** ile sertifikalı | **≥ 1 − δ olasılıkla, zamanın her anında** ayrışma ≤ α | yüksek olasılıklı ve zamandan bağımsız garanti gerektiğinde (denetim, düzenlemeye tabi kullanım) |

## Neden basit bir güven eşiği değil?

| | Güven eşiği / hazır yönlendirici | Kadı |
|---|---|---|
| Yerel cevap koşulu | Kalibre edilmemiş skor > elle seçilen eşik | Tek elemanlı conformal küme, argmax ile tutarlı |
| Hata iddiası | Başkasının verisinde benchmark doğruluğu | ***Sizin* oracle'ınızla ayrışma ≤ α**; soru başına, istenirse etiket başına |
| Kayma olunca | Sessizce bozulur | ACI α<sub>t</sub>'yi ayarlar; yanlış alarm oranı sınırlı bir e-detektör yeniden sertifikalar, kararları oracle'a gönderir ve alarm verir |
| Kanıt | Çevrimdışı değerlendirme | Canlı trafikte sürekli rastgele denetim, panelde görünür |
| Devreye alma | Geçip umut etmek | `replay` → `shadow` → soru soru `live` |

## Kurulum ve hızlı başlangıç

```bash
pip install git+https://github.com/zencefilefendi/kadi                       # çekirdek: sıfır bağımlılık
pip install "kadi-cascade[embed] @ git+https://github.com/zencefilefendi/kadi"       # + anlamsal refleks (fastembed/ONNX)
kadi --help
```

Demo, oracle kesintisi ve dil kayması içeren simüle bir destek masasıyla birlikte Divan panelini çalıştırır:

```bash
git clone https://github.com/zencefilefendi/kadi && cd kadi
python examples/demo.py          # ardından http://127.0.0.1:8765
python -m unittest discover -s tests
```

## Projenize güvenle almak: replay → gölge → canlı

**1. Geçmişinizi yeniden oynatın.** Birkaç dakika sürer ve canlı trafiğe dokunmaz. Geçmiş kararlarınızı JSONL olarak dışa aktarın; her satır `{"text": ..., "label": ...}` biçiminde olsun:

```bash
kadi replay gecmis.jsonl --cost 0.012 --alphas 0.01,0.03,0.05,0.1
```

Her α değeri için yerelde verilecek karar oranını, hatayı ve maliyeti tablo olarak gösterir.

**2. Gölge mod (1–2 hafta).** `mode = "shadow"` ayarlayın. Cevabı oracle vermeye devam eder, Kadı yalnızca kendi vereceği kararı kaydeder. Panel "yerelde %X karar verirdim, %Y uyuşurdum" diye raporlar.

**3. Soru soru canlıya geçin.** Düşük riskli sorularda α = %3–5 kullanın. Para, hukuk ve sağlık gibi yüksek riskli sorularda α ≤ %1 ve `conditional = true` kullanın ya da Kadı'yı sadece ön eleme için çalıştırın.

> **α'yı oracle'ınızın gürültü tabanının üstünde seçin.** Kendi kendisiyle ε oranında çelişen bir oracle'a bundan daha yakın uyulamaz. α ≈ ε seçerseniz Kadı neredeyse her şeyi oracle'a gönderir; bu, garantiyi korumanın tek doğru yoludur.

## Kullanım

### Python, aynı süreç içinde

```python
from kadi import Kadi, Choice, AnthropicOracle

kadi = Kadi(AnthropicOracle(model="claude-opus-5-5"), db="kadi.db",
            audit_rate=0.05, on_oracle_error="best_guess")

alan = Choice("hukuk_alani", ["is", "aile", "ceza", "ticaret"],
              "Bu dilekçe hangi hukuk alanına giriyor?", target_error=0.02, conditional=True)

karar = kadi.decide(alan, dilekce_metni)
karar.label, karar.tier, karar.reason      # 'is', 'reflex', 'confident'
```

### Ajanlar için MCP aracı olarak: API anahtarı gerekmez

```bash
claude mcp add kadi -- kadi mcp          # Claude Code; Claude Desktop için docs/MCP.md
```

Çağıran ajan **oracle'ın kendisidir**. `kadi_decide` ya bir etiket ya da bir bilet döndürür. Ajan biletli vakaları kendisi değerlendirir ve kararını `kadi_resolve` ile bildirir. Kadı bu kararlardan öğrenir; hata hedefini sertifikalayabildiği noktadan sonra rutin vakaları ajana sormayı bırakır. Garanti bu durumda ajanın kendi yargısına göredir. Ayrıntılı rehber: [docs/MCP.md](docs/MCP.md).

### Servis olarak, her dilden

```bash
kadi init                                   # kadi.toml oluşturur
export KADI_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export ANTHROPIC_API_KEY=...
kadi serve --config kadi.toml               # ya da: docker compose up -d
```

Next.js projeleri için tipli TypeScript istemcisi [clients/typescript](clients/typescript) klasöründedir. HTTP uç noktalarının tam listesi [İngilizce README](README.md#usage) içindedir.

## Açık benchmark sonuçları

`benchmarks/run.py`, **Banking77** (13.083 sorgu, 77 niyet) ve **CLINC150** (22.500 sorgu, 150 niyet) veri setlerini tohumlu rastgele sırayla taze bir Kadı örneğinden geçirir. Oracle rolünü veri setinin kendi etiketi oynar; yani *hata* hem oracle ile ayrışma hem de gerçek doğruya göre hatadır. Değerler v0.6 motoruyla, 3 tohumun ortalamasıdır. *Çağrı* = karar başına oracle çağrısı (her kararı oracle'a sormak = 1,00).

**α = %5'te yerel oran / hata / çağrı:**

| Refleks · politika | Banking77 | CLINC150 | Garanti |
|---|---|---|---|
| saf eşik τ = 0,5 | %85,9 / **%18,80** / 0,14 | %87,2 / **%10,41** / 0,13 | yok |
| elle ayarlanmış eşik τ = 0,9 | %65,4 / %2,89 / 0,35 | %73,5 / %1,47 / 0,27 | yok (eşik sonradan seçilmiş) |
| n-gram · conformal | %46,7 / %1,15 / 0,58 | %64,2 / %1,69 / 0,41 | ortalamada |
| n-gram · LTT | %49,1 / %1,66 / 0,56 | %65,2 / %1,72 / 0,40 | %95 olasılıkla, her an |
| MiniLM + k-NN · conformal | %63,8 / %2,46 / 0,42 | %77,4 / %3,27 / 0,28 | ortalamada |
| MiniLM + k-NN · LTT | %57,4 / %1,92 / 0,48 | %71,4 / %1,14 / 0,34 | %95 olasılıkla, her an |
| **bge-small + k-NN · conformal** | **%70,2 / %2,52 / 0,35** | **%84,7 / %3,40 / 0,21** | ortalamada |
| **bge-small + k-NN · LTT** | **%66,2 / %1,74 / 0,39** | **%78,1 / %1,32 / 0,27** | **%95 olasılıkla, her an** |

**Sonuçlar ne söylüyor:**

- **Garanti 126 koşunun tamamında tuttu.** Her tohum ayrı ayrı kontrol edildi.
- **En iyi yapılandırma (bge + conformal), α = %5'te oracle çağrılarının %65'ini (Banking77) ve %79'unu (CLINC150) ortadan kaldırıyor.** Her an geçerli LTT ile bu oranlar %61 ve %73.
- **Saf güven eşiği hiçbir uyarı vermeden %10–19 hata yapıyor.** Elle ayarlanmış bir eşik iyi görünebilir, ama ancak sonradan bakıldığında ve garantisiz. Kadı çalışma noktasını otomatik olarak ve sertifikayla seçiyor.
- **Katı geçerliliğin bedeli (v0.6 ve v0.5).** v0.5, öğrenmeye devam eden bir modeli kalibre ediyordu ve LTT sertifikası yalnızca o an için geçerliydi. v0.6 bu iki kısıtı kaldırıyor. Karşılığında aynı α'da daha az yerel karar veriyor: 36 yapılandırmada medyan 9,3 puan (aralık −1,5 ile +19,7). Sebebi, her sürümün sertifikasını taze veriyle kazanmak zorunda olması. Daha güçlü bir refleks bu kaybın çoğunu geri kazandırıyor; gerisi [yol haritasında](ROADMAP.tr.md) (P3).
- **Conformal, 18 yapılandırmanın 13'ünde LTT'den daha çok yerel karar verdi.** Garantisi daha zayıf (ortalamada); LTT ise zamanın her anında ve sürümler arasında paylaşılan bir garanti için ek kanıt istiyor. Hangi garantiye ihtiyacınız varsa ona göre seçin.
- **Etiket başına garanti (Mondrian) 77–150 etiketli sorularda ölçeklenmiyor:** yerel karar oranı ~%0. Yalnızca az etiketli sorularda kullanın.

```python
from kadi.embed import FastEmbedder, HybridFeaturizer, KNNHybridReflex, MULTILINGUAL
kadi = Kadi(oracle, featurizer=HybridFeaturizer(FastEmbedder(MULTILINGUAL)), reflex=KNNHybridReflex())
```

## Değerlendirme (sentetik, tekrarlanabilir)

Demoda simüle oracle %2 gürültülüdür ve çağrı başına $0,012 tutar. Akışın %30–33'ünde bir oracle kesintisi, %50'sinde bir kelime kayması vardır. 6.000 talep, 2 soru, α = %5, v0.6:

| | Yerel | Denetimde uyuşma | Karar hatası (tahmini) | Küme kapsamaması | Maliyet (yalnız oracle'a karşı) |
|---|---|---|---|---|---|
| `route_ticket`, marjinal | %77,8 | %94,9 | %4,0 | %6,3 | $19,96 / $72 |
| `is_urgent`, etiket başına | %52,2 | %95,5 | %2,3 | %5,5 | $36,73 / $72 |

Karar düzeyindeki hata α'nın altında. Küme kapsamaması ise α'nın biraz üstünde. Conformal garantisi ortalamada geçerli olduğu için buna izin verir; koşu bir kesinti, bir kayma ve gürültülü bir oracle içeriyor. Veri sentetik ve sözcüksel olarak kolaydır. Kendi verinizi `replay` ve gölge modla ölçün.

## Güvenlik ve gizlilik

Bağımsız bir saldırgan gözüyle yapılan inceleme 11 sorun buldu. Hepsi düzeltildi ve her biri için bir regresyon testi var. Ayrıntılar [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) belgesinde.

| Alan | Önlemler |
|---|---|
| Erişim | sabit zamanlı token doğrulaması, CSRF ve DNS rebinding korumaları, hız sınırı, gövde ve girdi limitleri |
| Sertleştirme | katı CSP, root olmayan ve salt okunur konteyner |
| Gizlilik | TC kimlik, IBAN, kart, telefon, e-posta ve anahtar maskeleme (kayıtta ve isteğe bağlı olarak oracle'a giderken), anahtarlı HMAC, saklama süresi |
| Bütünlük | şemaya kilitli çıktı, prompt injection ayraçları, yenilik koruması, sapma e-detektörü, SHA-256 doğrulamalı model anlık görüntüleri |
| Denetlenebilirlik | **kurcalanamaz defter**: her karar bir öncekine HMAC ile zincirlenir; `kadi verify` değiştirilmiş, silinmiş ya da araya eklenmiş satırı bulur; `kadi anchor` zincir başını dışarıda saklamak için verir |

## Durum ve bilinen sınırlar

Kadı v0.6, tek sunuculu kullanım için özellik açısından tamamdır. Neyin doğrulandığı ve neyin doğrulanmadığı:

| Alan | Durum |
|---|---|
| Kalibrasyon (conformal, Mondrian, her an geçerli LTT, e-detektör) | ✅ birim ve simülasyon testleri (LTT'nin zaman boyunca geçerliliği, detektörün ARL'si, δ harcaması); açık benchmark'ta garanti 126/126 koşuda tuttu |
| Refleks (n-gram, embedding + k-NN) | ✅ Banking77 ve CLINC150 üzerinde ölçüldü |
| Servis, güvenlik, defter, MCP, dondurulmuş sürümler | ✅ 101 test (iki güvenlik denetimi regresyon paketi, MCP stdio uçtan uca testi, terfi, yeniden başlatma ve kurcalanmış anlık görüntü testleri dahil); CI'da Python 3.11–3.13 ve Docker |
| İstatistiksel ayrıntılar | ⚠️ Değiştirilebilirlik (exchangeability) hâlâ varsayılıyor; kayma durumunda e-detektör koruma sağlıyor. ACI sınırı gevşek; hafıza cevapları denetlenmiyor. Bkz. [THEORY §7c](docs/THEORY.md) |
| **Gerçek LLM oracle** | ⚠️ kod hazır, ama benchmark'larda oracle olarak **gerçek etiketler** kullanıldı. API anahtarıyla yapılacak ilk iş: `benchmarks/run.py --oracle anthropic` |
| **Türkçe veri** | ⚠️ çok dilli model Türkçeyi destekliyor, ama Türkçe benchmark henüz koşulmadı |
| Ölçeklenme | ⚠️ tek süreç ve SQLite; çoklu sunucu için Postgres desteği yol haritasında |
| Canlı trafik | ⚠️ henüz gerçek bir uygulamanın arkasında çalıştırılmadı; sırayla replay → gölge → canlı izlenmeli |

## Lisans

[Apache-2.0](LICENSE). Katkılar memnuniyetle karşılanır; bkz. [CONTRIBUTING.md](CONTRIBUTING.md).
