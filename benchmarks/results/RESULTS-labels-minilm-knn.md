# Kadı benchmark — oracle: `labels`

Seeds [0, 1, 2] · audit rate 0.05 · stream length full dataset · Python 3.12.14

Mean ± sd over seeds. *error* = share of returned decisions that disagree with the oracle (here: gold labels). *calls/dec* includes audits; oracle-only = 1.00.

## banking77

| policy | target α | local | steady local | error | steady error | calls/dec | bound met |
|---|---|---|---|---|---|---|---|
| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |
| conformal | 2% | 45.7% ± 8.5% | 63.2% ± 13.7% | 0.48% ± 0.48% | 0.75% ± 0.86% | 0.57 | ✅ |
| conformal | 5% | 63.6% ± 4.1% | 76.9% ± 4.7% | 1.50% ± 0.57% | 1.80% ± 0.78% | 0.40 | ✅ |
| conformal | 10% | 80.4% ± 3.4% | 90.8% ± 1.9% | 6.14% ± 1.13% | 7.21% ± 1.32% | 0.24 | ✅ |
| ltt | 2% | 54.5% ± 6.4% | 65.8% ± 4.7% | 0.49% ± 0.19% | 0.51% ± 0.19% | 0.48 | ✅ |
| ltt | 5% | 70.7% ± 2.2% | 82.1% ± 2.3% | 1.82% ± 0.54% | 2.36% ± 0.84% | 0.33 | ✅ |
| ltt | 10% | 82.1% ± 1.9% | 90.6% ± 1.0% | 5.74% ± 0.97% | 6.47% ± 0.90% | 0.22 | ✅ |

## clinc150

| policy | target α | local | steady local | error | steady error | calls/dec | bound met |
|---|---|---|---|---|---|---|---|
| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |
| conformal | 2% | 69.8% ± 3.8% | 80.8% ± 4.9% | 0.91% ± 0.29% | 1.07% ± 0.24% | 0.34 | ✅ |
| conformal | 5% | 82.5% ± 1.2% | 90.3% ± 1.6% | 3.40% ± 0.87% | 3.60% ± 0.94% | 0.22 | ✅ |
| conformal | 10% | 88.9% ± 1.0% | 94.5% ± 1.2% | 7.60% ± 0.69% | 7.60% ± 0.78% | 0.16 | ✅ |
| ltt | 2% | 76.1% ± 0.6% | 86.1% ± 0.8% | 0.85% ± 0.02% | 0.95% ± 0.09% | 0.28 | ✅ |
| ltt | 5% | 81.9% ± 0.1% | 88.6% ± 0.8% | 2.58% ± 0.18% | 2.76% ± 0.25% | 0.22 | ✅ |
| ltt | 10% | 88.6% ± 0.4% | 94.0% ± 1.1% | 7.37% ± 0.46% | 7.54% ± 0.72% | 0.16 | ✅ |

Dataset files (SHA-256):

- `banking77/train.csv` `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`
- `banking77/test.csv` `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`
- `clinc150/data_full.json` `36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0`
