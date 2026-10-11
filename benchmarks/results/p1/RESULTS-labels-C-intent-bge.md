# Kadı benchmark — oracle: `labels`

Reflex `bge+knn` · seeds [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] · audit rate 0.05 · baseline prefix budget 500 · stream length full dataset · Python 3.12.14

Mean over seeds with a 95% bootstrap CI. *err (oracle)* is disagreement with the oracle, the quantity α bounds. *err (gold)* is against the dataset label. *Violations* counts runs with err (oracle) > α; *CP95* is the Clopper–Pearson 95% upper bound on the per-run violation probability. *Calls/dec* includes audits; oracle-only = 1.00.

## banking77

Oracle: kind = labels, oracle_vs_gold = 1

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| tuned | 5% | 71.7% (70.5%–72.8%) | 78.2% | 0.95% | 0.95% | 0.28 | 0/10 | 26% |
| deferral | 5% | 78.2% (77.1%–79.1%) | 84.0% | 1.78% | 1.78% | 0.22 | 0/10 | 26% |
| conformal | 5% | 71.7% (69.4%–73.9%) | 84.6% | 2.52% | 2.52% | 0.34 | 0/10 | 26% |
| ltt | 5% | 66.7% (64.8%–68.5%) | 79.2% | 1.53% | 1.53% | 0.39 | 0/10 | 26% |

## clinc150

Oracle: kind = labels, oracle_vs_gold = 0.9998

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| tuned | 5% | 78.2% (77.1%–79.2%) | 84.1% | 0.46% | 0.46% | 0.22 | 0/10 | 26% |
| deferral | 5% | 83.6% (82.8%–84.5%) | 89.0% | 1.14% | 1.15% | 0.16 | 0/10 | 26% |
| conformal | 5% | 85.3% (84.3%–86.3%) | 94.8% | 3.64% | 3.65% | 0.20 | 0/10 | 26% |
| ltt | 5% | 78.4% (77.4%–79.3%) | 88.5% | 1.57% | 1.58% | 0.27 | 0/10 | 26% |

Dataset files (SHA-256):

- `banking77/train.csv` `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`
- `banking77/test.csv` `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`
- `clinc150/data_full.json` `36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0`
