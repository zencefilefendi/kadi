# Kadı benchmark — oracle: `labels`

Reflex `hashed` · seeds [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] · audit rate 0.05 · baseline prefix budget 500 · stream length full dataset · Python 3.12.14

Mean over seeds with a 95% bootstrap CI. *err (oracle)* is disagreement with the oracle, the quantity α bounds. *err (gold)* is against the dataset label. *Violations* counts runs with err (oracle) > α; *CP95* is the Clopper–Pearson 95% upper bound on the per-run violation probability. *Calls/dec* includes audits; oracle-only = 1.00.

## banking77

Oracle: kind = labels, oracle_vs_gold = 1

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| tuned | 5% | 67.2% (65.7%–68.7%) | 76.5% | 3.26% | 3.26% | 0.33 | 0/10 | 26% |
| deferral | 5% | 69.0% (68.0%–70.2%) | 78.4% | 3.86% | 3.86% | 0.31 | 1/10 | 39% |
| conformal | 5% | 46.5% (44.8%–48.4%) | 60.8% | 1.17% | 1.17% | 0.59 | 0/10 | 26% |
| ltt | 5% | 48.1% (46.0%–50.5%) | 61.4% | 1.80% | 1.80% | 0.57 | 0/10 | 26% |

## clinc150

Oracle: kind = labels, oracle_vs_gold = 0.9998

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| tuned | 5% | 78.5% (77.4%–79.5%) | 86.8% | 2.83% | 2.84% | 0.22 | 0/10 | 26% |
| deferral | 5% | 80.3% (79.3%–81.2%) | 88.4% | 3.63% | 3.64% | 0.20 | 0/10 | 26% |
| conformal | 5% | 66.0% (64.5%–67.5%) | 82.0% | 1.99% | 2.00% | 0.39 | 0/10 | 26% |
| ltt | 5% | 64.2% (62.8%–65.8%) | 79.7% | 1.61% | 1.62% | 0.41 | 0/10 | 26% |

Dataset files (SHA-256):

- `banking77/train.csv` `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`
- `banking77/test.csv` `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`
- `clinc150/data_full.json` `36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0`
