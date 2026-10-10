# Kadı benchmark — oracle: `labels`

Seeds [0, 1, 2] · audit rate 0.05 · stream length full dataset · Python 3.12.14

Mean ± sd over seeds. *error* = share of returned decisions that disagree with the oracle (here: gold labels). *calls/dec* includes audits; oracle-only = 1.00.

## banking77

| policy | target α | local | steady local | error | steady error | calls/dec | bound met |
|---|---|---|---|---|---|---|---|
| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |
| conformal | 2% | 55.1% ± 3.0% | 73.6% ± 6.0% | 0.63% ± 0.27% | 0.93% ± 0.44% | 0.48 | ✅ |
| conformal | 5% | 76.9% ± 2.4% | 89.1% ± 2.8% | 2.64% ± 0.47% | 3.34% ± 0.68% | 0.27 | ✅ |
| conformal | 10% | 86.6% ± 1.1% | 94.3% ± 0.5% | 4.88% ± 0.47% | 5.24% ± 0.69% | 0.18 | ✅ |
| ltt | 2% | 61.2% ± 5.6% | 73.6% ± 2.7% | 0.54% ± 0.25% | 0.69% ± 0.29% | 0.42 | ✅ |
| ltt | 5% | 79.6% ± 1.6% | 90.2% ± 0.5% | 2.14% ± 0.40% | 2.73% ± 0.38% | 0.25 | ✅ |
| ltt | 10% | 89.3% ± 2.4% | 97.2% ± 1.7% | 6.14% ± 1.38% | 7.39% ± 1.72% | 0.15 | ✅ |

## clinc150

| policy | target α | local | steady local | error | steady error | calls/dec | bound met |
|---|---|---|---|---|---|---|---|
| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |
| conformal | 2% | 79.4% ± 3.6% | 91.0% ± 1.4% | 1.07% ± 0.23% | 1.36% ± 0.28% | 0.25 | ✅ |
| conformal | 5% | 89.0% ± 1.3% | 95.3% ± 1.0% | 3.15% ± 0.61% | 3.21% ± 0.51% | 0.16 | ✅ |
| conformal | 10% | 89.6% ± 0.8% | 91.7% ± 1.4% | 3.93% ± 0.37% | 2.59% ± 0.34% | 0.15 | ✅ |
| ltt | 2% | 80.3% ± 2.2% | 90.0% ± 1.5% | 0.72% ± 0.26% | 0.86% ± 0.31% | 0.24 | ✅ |
| ltt | 5% | 89.8% ± 1.0% | 95.3% ± 1.0% | 3.18% ± 0.47% | 3.35% ± 0.53% | 0.15 | ✅ |
| ltt | 10% | 94.1% ± 1.0% | 99.4% ± 0.7% | 6.19% ± 0.63% | 7.02% ± 0.90% | 0.11 | ✅ |

Dataset files (SHA-256):

- `banking77/train.csv` `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`
- `banking77/test.csv` `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`
- `clinc150/data_full.json` `36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0`
