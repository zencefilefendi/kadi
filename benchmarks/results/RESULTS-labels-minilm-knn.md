# Kadı benchmark — oracle: `labels`

Seeds [0, 1, 2] · audit rate 0.05 · stream length full dataset · Python 3.12.14

Mean ± sd over seeds. *error* = share of returned decisions that disagree with the oracle (here: gold labels). *calls/dec* includes audits; oracle-only = 1.00.

## banking77

| policy | target α | local | steady local | error | steady error | calls/dec | bound met |
|---|---|---|---|---|---|---|---|
| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |
| conformal | 2% | 38.0% ± 4.0% | 43.4% ± 9.9% | 0.25% ± 0.05% | 0.19% ± 0.01% | 0.67 | ✅ |
| conformal | 5% | 63.8% ± 5.6% | 78.6% ± 5.7% | 2.46% ± 1.15% | 3.36% ± 1.66% | 0.42 | ✅ |
| conformal | 10% | 74.9% ± 3.5% | 87.8% ± 1.6% | 6.02% ± 0.98% | 7.26% ± 0.28% | 0.31 | ✅ |
| ltt | 2% | 42.0% ± 1.2% | 57.2% ± 2.6% | 0.54% ± 0.11% | 0.54% ± 0.10% | 0.63 | ✅ |
| ltt | 5% | 57.4% ± 2.2% | 70.9% ± 2.7% | 1.92% ± 0.77% | 1.56% ± 0.31% | 0.48 | ✅ |
| ltt | 10% | 71.6% ± 0.8% | 84.6% ± 2.5% | 4.29% ± 0.98% | 4.64% ± 0.77% | 0.34 | ✅ |

## clinc150

| policy | target α | local | steady local | error | steady error | calls/dec | bound met |
|---|---|---|---|---|---|---|---|
| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |
| conformal | 2% | 64.6% ± 4.5% | 77.6% ± 6.0% | 0.73% ± 0.28% | 0.89% ± 0.49% | 0.41 | ✅ |
| conformal | 5% | 77.4% ± 2.8% | 86.9% ± 4.8% | 3.27% ± 0.64% | 4.00% ± 1.14% | 0.28 | ✅ |
| conformal | 10% | 87.0% ± 1.1% | 95.8% ± 2.5% | 8.13% ± 0.53% | 9.24% ± 1.40% | 0.18 | ✅ |
| ltt | 2% | 58.1% ± 2.7% | 72.8% ± 4.1% | 0.45% ± 0.19% | 0.55% ± 0.24% | 0.47 | ✅ |
| ltt | 5% | 71.4% ± 0.7% | 84.3% ± 1.5% | 1.14% ± 0.10% | 1.29% ± 0.04% | 0.34 | ✅ |
| ltt | 10% | 80.2% ± 1.2% | 88.9% ± 0.9% | 3.56% ± 0.49% | 4.15% ± 0.50% | 0.25 | ✅ |

Dataset files (SHA-256):

- `banking77/train.csv` `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`
- `banking77/test.csv` `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`
- `clinc150/data_full.json` `36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0`
