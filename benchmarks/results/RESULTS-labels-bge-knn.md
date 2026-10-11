# Kadı benchmark — oracle: `labels`

Seeds [0, 1, 2] · audit rate 0.05 · stream length full dataset · Python 3.12.14

Mean ± sd over seeds. *error* = share of returned decisions that disagree with the oracle (here: gold labels). *calls/dec* includes audits; oracle-only = 1.00.

## banking77

| policy | target α | local | steady local | error | steady error | calls/dec | bound met |
|---|---|---|---|---|---|---|---|
| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |
| conformal | 2% | 46.5% ± 10.5% | 51.5% ± 16.8% | 0.46% ± 0.17% | 0.38% ± 0.17% | 0.59 | ✅ |
| conformal | 5% | 70.2% ± 7.1% | 82.1% ± 12.1% | 2.52% ± 0.96% | 3.27% ± 1.77% | 0.35 | ✅ |
| conformal | 10% | 85.1% ± 1.6% | 94.5% ± 2.3% | 6.78% ± 1.22% | 7.66% ± 0.97% | 0.20 | ✅ |
| ltt | 2% | 42.5% ± 6.5% | 49.1% ± 12.9% | 0.94% ± 0.80% | 0.99% ± 0.86% | 0.63 | ✅ |
| ltt | 5% | 66.2% ± 3.1% | 79.5% ± 7.4% | 1.74% ± 0.53% | 1.78% ± 0.70% | 0.39 | ✅ |
| ltt | 10% | 81.7% ± 1.5% | 93.5% ± 1.0% | 3.88% ± 0.44% | 4.78% ± 0.29% | 0.24 | ✅ |

## clinc150

| policy | target α | local | steady local | error | steady error | calls/dec | bound met |
|---|---|---|---|---|---|---|---|
| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |
| conformal | 2% | 68.1% ± 3.7% | 80.3% ± 3.4% | 0.89% ± 0.04% | 1.06% ± 0.34% | 0.37 | ✅ |
| conformal | 5% | 84.7% ± 2.2% | 94.4% ± 3.8% | 3.40% ± 0.57% | 3.81% ± 0.92% | 0.21 | ✅ |
| conformal | 10% | 91.1% ± 2.5% | 96.8% ± 4.3% | 7.08% ± 0.79% | 7.34% ± 1.31% | 0.14 | ✅ |
| ltt | 2% | 63.5% ± 2.0% | 77.9% ± 1.9% | 0.37% ± 0.08% | 0.40% ± 0.09% | 0.42 | ✅ |
| ltt | 5% | 78.1% ± 0.8% | 87.9% ± 0.9% | 1.32% ± 0.24% | 1.33% ± 0.12% | 0.27 | ✅ |
| ltt | 10% | 87.6% ± 1.4% | 97.4% ± 1.4% | 4.00% ± 0.60% | 4.67% ± 0.82% | 0.18 | ✅ |

Dataset files (SHA-256):

- `banking77/train.csv` `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`
- `banking77/test.csv` `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`
- `clinc150/data_full.json` `36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0`
