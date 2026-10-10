<div align="center">

# Kadı ⚖︎

**Frontier modelinizin önünde oturan, kalibre edilmiş bir yargıç.**

Rutin kararları yerelde verir. Bu kararların oracle ile ne sıklıkla ayrıştığına dağılımdan bağımsız bir üst sınır koyar.<br>
Geri kalan her şeyi oracle'a yükseltir ve her yükseltmeden öğrenir.

[English](README.md) · [Teori](docs/THEORY.md) · [Tehdit modeli](docs/THREAT_MODEL.md) · [MCP sunucusu](docs/MCP.md)

</div>

---

## Özet

LLM tabanlı ajanlar ve uygulamalar çok sayıda küçük, şeması belli karar verir: bir talebi doğru ekibe yönlendirmek, spam'i işaretlemek, sıradaki aracı seçmek, bir değişikliği onaylamak gibi. Her birini frontier modele sormak doğru sonuç verir ama yavaş ve pahalıdır. Küçük bir modele sormak ucuzdur ama hata oranı bilinmez.

Kadı üç katmanlı bir kaskattır: **hafıza → yerel refleks → oracle**. Ortadaki katman yalnızca **split-conformal tahmin kümesi tek bir etiket içerdiğinde** cevap verir. Değiştirilebilirlik (exchangeability) varsayımı altında bu, dönen bir kararın oracle ile ayrışma olasılığını kullanıcının seçtiği α ile sınırlar. Sınır isteğe bağlı olarak her etiket için ayrı ayrı (Mondrian) da tutulabilir.

Bunu canlı akan (online) bir sistemde doğru yapmak dört mekanizma gerektirir:

- Kalibrasyon, akıştan **rastgele seçilen ve eğitimde hiç kullanılmayan** örneklerle yapılır; yükseltilen örneklerle asla.
- Model öğrendikçe kalibrasyon skorları yeniden hesaplanır.
- Dağılım kaymasına karşı Adaptive Conformal Inference (ACI) kullanılır.
- İstatistiksel testle tetiklenen bir **sapma kesicisi** vardır.

Bunlara ek olarak dağılım dışı ve saldırgan girdilere karşı bir yenilik koruması, gölge mod, KVKK odaklı PII maskeleme ve sertleştirilmiş bir HTTP servisi bulunur. Tamamı Python standart kütüphanesiyle yazılmıştır ve **sıfır bağımlılıklıdır**.

## Nasıl çalışır

| Katman | Gecikme | Maliyet | Ne zaman cevap verir |
|---|---|---|---|
| **Hafıza** | µs | $0 | aynı girdi daha önce oracle'a sorulduysa |
| **Refleks** | ms | $0 | conformal küme tek etiketliyse ve tüm korumalar geçiyorsa |
| **Oracle** | sn | $$ | diğer her durumda; verdiği karar refleksi eğitir |
| **Fallback** | ms | $0 | oracle çöktüyse ve politika `best_guess` ise; işaretlidir, garanti taşımaz |

**Tek satırlık garanti:**

$$
\Pr\big(\hat{y} \neq O(x)\big) \;\le\; \Pr\big(O(x) \notin C(x)\big) \;\le\; \alpha
$$

Bir ayrışma ancak yerel cevapta mümkündür, yerel cevap da ancak C(x) = {ŷ} olduğunda verilir. Tam ifade, varsayımlar, Mondrian varyantı, ACI sınırı ve **neyin garanti edilmediği** [docs/THEORY.md](docs/THEORY.md) belgesindedir.

### İki politika

| `policy` | Yerel cevap koşulu | Garanti | En uygun olduğu yer |
|---|---|---|---|
| `"conformal"` (varsayılan) | conformal küme tek etiketli | Ayrışma ≤ α, **ortalamada**; ACI kaymaya uyum sağlar; istenirse **etiket başına** | nadir ama kritik etiketler, değişken trafik |
| `"ltt"` | max p ≥ λ̂; λ̂ **Learn then Test** ile sertifikalı | **≥ 1 − δ olasılıkla** ayrışma ≤ α | çok etiketli sorular; aynı α'da en çok yerel karar |

## Neden basit bir güven eşiği değil?

| | Güven eşiği / hazır yönlendirici | Kadı |
|---|---|---|
| Yerel cevap koşulu | Kalibre edilmemiş skor > elle seçilen eşik | Tek elemanlı conformal küme, argmax ile tutarlı |
| Hata iddiası | Başkasının verisinde benchmark doğruluğu | ***Sizin* oracle'ınızla ayrışma ≤ α**; soru başına, istenirse etiket başına |
| Kayma olunca | Sessizce bozulur | ACI α<sub>t</sub>'yi ayarlar; sapma kesicisi her şeyi yükseltir ve alarm verir |
| Kanıt | Çevrimdışı değerlendirme | Canlı trafikte sürekli rastgele denetim, panelde görünür |
| Devreye alma | Geçip umut etmek | `replay` → `shadow` → soru soru `live` |

## Kurulum ve hızlı başlangıç

```bash
pip install git+https://github.com/zencefilefendi/kadi                       # çekirdek: sıfır bağımlılık
pip install "kadi[embed] @ git+https://github.com/zencefilefendi/kadi"       # + anlamsal refleks (fastembed/ONNX)
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

`benchmarks/run.py`, **Banking77** (13.083 sorgu, 77 niyet) ve **CLINC150** (22.500 sorgu, 150 niyet) veri setlerini tohumlu rastgele sırayla taze bir Kadı örneğinden geçirir. Oracle rolünü gerçek etiket oynar, yani *hata* hem oracle ile ayrışma hem de gerçek doğruya göre hatadır. Değerler 3 tohumun ortalamasıdır; ayrıntılı tablolar [benchmarks/results/RESULTS-labels.md](benchmarks/results/RESULTS-labels.md) dosyasında.

| | Banking77 yerel / hata | CLINC150 yerel / hata | Hata kontrol altında mı? |
|---|---|---|---|
| eşik τ = 0,5 (saf yönlendirici) | %85,9 / **%18,80** | %87,2 / **%10,41** | hayır |
| eşik τ = 0,9 (elle ayarlı) | %65,4 / %2,89 | %73,5 / %1,47 | hayır |
| Kadı conformal, α = %5 | %54,7 / %1,28 | %74,7 / %2,16 | ✅ ortalamada |
| **Kadı LTT, α = %5** | **%63,9 / %2,47** | **%79,5 / %3,19** | ✅ %95 olasılıkla |
| **Kadı LTT, α = %10** | **%74,4 / %6,09** | **%85,4 / %6,94** | ✅ %95 olasılıkla |

**Sonuçlar ne söylüyor:**

- **Garanti, 54 koşunun tamamında tuttu** (2 veri seti × 3 politika × 3 α × 3 tohum); yalnızca ortalamada değil, her tohumda ayrı ayrı.
- **LTT, her α değerinde conformal'dan 3,5–9 puan daha fazla kararı yerelde verdi.**
- **İyi seçilmiş sabit bir eşik rekabetçi olabilir, ama bu ancak doğru eşiği önceden biliyorsanız işe yarar.** Doğru eşik veri setine göre değişir ve garanti taşımaz; τ = 0,5 seçilirse hata sessizce %10–19'a çıkar. Kadı bu çalışma noktasını otomatik olarak ve sertifikayla seçer.
- **Etiket başına garanti, çok etiketli sorularda ölçeklenmez.** Az etiketli ve nadir etiketin kritik olduğu sorularda kullanın.

### Anlamsal refleks: embedding + k-NN

İsteğe bağlı `[embed]` paketi; cümle embedding'leri, oracle'ın etiketlediği örnekler üzerinden k-en yakın komşu oylaması ve mevcut çevrimiçi modeli birleştiren hibrit bir refleks ekler. Kalibrasyon katmanı modelden bağımsızdır: daha güçlü bir refleks yalnızca **ne kadar sık** yerel karar verildiğini değiştirir, garantiyi asla. Ayarlar, değerlendirme koşularından ayrı bir ayar akışında seçildi.

**Yerelde verilen karar oranı (3 tohum ortalaması; her koşuda hata ≤ α):**

| Refleks | Banking77 LTT α=%2 / %5 / %10 | CLINC150 LTT α=%2 / %5 / %10 |
|---|---|---|
| n-gram (çekirdek, sıfır bağımlılık) | %47,0 / %63,9 / %74,4 | %69,8 / %79,5 / %85,4 |
| + çok dilli MiniLM + k-NN | %54,5 / %70,7 / %82,1 | %76,1 / %81,9 / %88,6 |
| **+ bge-small-en + k-NN** | **%61,2 / %79,6 / %89,3** | **%80,3 / %89,8 / %94,1** |

- **Garanti 126 koşunun 126'sında tuttu.**
- **α = %5'te bge reflexi, sıfır bağımlılıklı reflekse göre frontier çağrılarını %36 (Banking77) ve %40 (CLINC150) azalttı.**
- Çok dilli MiniLM bu İngilizce benchmark'larda bge'nin gerisinde kalıyor. Bu beklenen bir sonuç; MiniLM'in asıl değeri Türkçe ve diğer diller için.

```python
from kadi.embed import FastEmbedder, HybridFeaturizer, KNNHybridReflex, MULTILINGUAL
kadi = Kadi(oracle, featurizer=HybridFeaturizer(FastEmbedder(MULTILINGUAL)), reflex=KNNHybridReflex())
```

## Değerlendirme (sentetik, tekrarlanabilir)

Demoda simüle oracle %2 gürültülüdür ve çağrı başına $0.012 tutar. Akışın %30–33'ünde bir oracle kesintisi, %50'sinde bir kelime kayması vardır. 6.000 talep, 2 soru, α = %5:

| | Yerel | Denetimde uyuşma | Gerçekleşen kapsamama | Maliyet (yalnız oracle'a karşı) |
|---|---|---|---|---|
| `route_ticket`, marjinal | %94,3 | %99,1 | %3,0 | $6,83 / $72 |
| `is_urgent`, etiket başına | %62,6 | %97,8 | %3,7 | $28,09 / $72 |

Veri sentetik ve sözcüksel olarak kolaydır. Kendi verinizi `replay` ve gölge modla ölçün.

## Güvenlik ve gizlilik

Bağımsız bir saldırgan gözüyle yapılan inceleme 11 sorun buldu. Hepsi düzeltildi ve her biri için bir regresyon testi var. Ayrıntılar [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) belgesinde.

| Alan | Önlemler |
|---|---|
| Erişim | sabit zamanlı token doğrulaması, CSRF ve DNS rebinding korumaları, hız sınırı, gövde ve girdi limitleri |
| Sertleştirme | katı CSP, root olmayan ve salt okunur konteyner |
| Gizlilik | TC kimlik, IBAN, kart, telefon, e-posta ve anahtar maskeleme (kayıtta ve isteğe bağlı olarak oracle'a giderken), anahtarlı HMAC, saklama süresi |
| Bütünlük | şemaya kilitli çıktı, prompt injection ayraçları, yenilik koruması, sapma kesicisi |
| Denetlenebilirlik | **kurcalanamaz defter**: her karar bir öncekine HMAC ile zincirlenir; `kadi verify` değiştirilmiş, silinmiş ya da araya eklenmiş satırı bulur; `kadi anchor` zincir başını dışarıda saklamak için verir |

## Durum ve bilinen sınırlar

Kadı v0.4, tek sunuculu kullanım için özellik açısından tamamdır. Neyin doğrulandığı ve neyin doğrulanmadığı:

| Alan | Durum |
|---|---|
| Kalibrasyon (conformal, Mondrian, LTT) | ✅ birim ve simülasyon testleri; açık benchmark'ta garanti 126/126 koşuda tuttu |
| Refleks (n-gram, embedding + k-NN) | ✅ Banking77 ve CLINC150 üzerinde ölçüldü |
| Servis, güvenlik, defter, MCP | ✅ 87 test (MCP için stdio uçtan uca testi dahil); CI'da Python 3.11–3.13 ve Docker |
| **Gerçek LLM oracle** | ⚠️ kod hazır, ama benchmark'larda oracle olarak **gerçek etiketler** kullanıldı. API anahtarıyla yapılacak ilk iş: `benchmarks/run.py --oracle anthropic` |
| **Türkçe veri** | ⚠️ çok dilli model Türkçeyi destekliyor, ama Türkçe benchmark henüz koşulmadı |
| Ölçeklenme | ⚠️ tek süreç ve SQLite; çoklu sunucu için Postgres desteği yol haritasında |
| Canlı trafik | ⚠️ henüz gerçek bir uygulamanın arkasında çalıştırılmadı; sırayla replay → gölge → canlı izlenmeli |

## Lisans

[Apache-2.0](LICENSE). Katkılar memnuniyetle karşılanır; bkz. [CONTRIBUTING.md](CONTRIBUTING.md).
