<div align="center">

# Kadı ⚖︎

**Frontier modelinizin önünde oturan, kalibre edilmiş bir yargıç.**

Rutin kararları yerelde verir. Bu kararların oracle ile ne sıklıkla ayrıştığına dağılımdan bağımsız bir üst sınır koyar.<br>
Geri kalan her şeyi oracle'a yükseltir ve her yükseltmeden öğrenir.

[English](README.md) · [Teori](docs/THEORY.md) · [Tehdit modeli](docs/THREAT_MODEL.md)

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
pip install git+https://github.com/zencefilefendi/kadi
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

### Servis olarak, her dilden

```bash
kadi init                                   # kadi.toml oluşturur
export KADI_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export ANTHROPIC_API_KEY=...
kadi serve --config kadi.toml               # ya da: docker compose up -d
```

Next.js projeleri için tipli TypeScript istemcisi [clients/typescript](clients/typescript) klasöründedir. HTTP uç noktalarının tam listesi [İngilizce README](README.md#usage) içindedir.

## Değerlendirme (sentetik, tekrarlanabilir)

Demoda simüle oracle %2 gürültülüdür ve çağrı başına $0.012 tutar. Akışın %30–33'ünde bir oracle kesintisi, %50'sinde bir kelime kayması vardır. 6.000 talep, 2 soru, α = %5:

| | Yerel | Denetimde uyuşma | Gerçekleşen kapsamama | Maliyet (yalnız oracle'a karşı) |
|---|---|---|---|---|
| `route_ticket`, marjinal | %93,4 | %97,3 | %6,0 → ACI α<sub>t</sub>'yi %3,8'e çeker | $7,26 / $72 |
| `is_urgent`, etiket başına | %42,6 | %95,3 | %4,3 | $41,56 / $72 |

Veri sentetik ve sözcüksel olarak kolaydır. Kendi verinizi `replay` ve gölge modla ölçün.

## Güvenlik ve gizlilik

Bağımsız bir saldırgan gözüyle yapılan inceleme 11 sorun buldu. Hepsi düzeltildi ve her biri için bir regresyon testi var. Ayrıntılar [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) belgesinde.

| Alan | Önlemler |
|---|---|
| Erişim | sabit zamanlı token doğrulaması, CSRF ve DNS rebinding korumaları, hız sınırı, gövde ve girdi limitleri |
| Sertleştirme | katı CSP, root olmayan ve salt okunur konteyner |
| Gizlilik | TC kimlik, IBAN, kart, telefon, e-posta ve anahtar maskeleme (kayıtta ve isteğe bağlı olarak oracle'a giderken), anahtarlı HMAC, saklama süresi |
| Bütünlük | şemaya kilitli çıktı, prompt injection ayraçları, yenilik koruması, sapma kesicisi |

## Lisans

[Apache-2.0](LICENSE). Katkılar memnuniyetle karşılanır; bkz. [CONTRIBUTING.md](CONTRIBUTING.md).
