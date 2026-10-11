# Kadı benchmark — oracle: `labels`

Reflex `bge+knn` · seeds [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] · audit rate 0.05 · baseline prefix budget 500 · stream length full dataset · Python 3.12.14

Mean over seeds with a 95% bootstrap CI. *err (oracle)* is disagreement with the oracle, the quantity α bounds. *err (gold)* is against the dataset label. *Violations* counts runs with err (oracle) > α; *CP95* is the Clopper–Pearson 95% upper bound on the per-run violation probability. *Calls/dec* includes audits; oracle-only = 1.00.

## hatespeech_en

Oracle: kind = labels, oracle_vs_gold = 1

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| tuned | 2% | 19.2% (18.2%–20.3%) | 19.8% | 0.61% | 0.61% | 0.81 | 0/10 | 26% |
| tuned | 5% | 33.6% (31.2%–36.2%) | 34.1% | 2.23% | 2.23% | 0.66 | 0/10 | 26% |
| tuned | 10% | 51.3% (48.5%–53.7%) | 51.8% | 5.66% | 5.66% | 0.49 | 0/10 | 26% |
| deferral | 2% | 21.7% (19.1%–24.6%) | 22.3% | 0.84% | 0.84% | 0.78 | 0/10 | 26% |
| deferral | 5% | 35.7% (31.9%–39.7%) | 36.5% | 2.62% | 2.62% | 0.64 | 0/10 | 26% |
| deferral | 10% | 53.5% (49.7%–56.9%) | 54.2% | 6.26% | 6.26% | 0.47 | 0/10 | 26% |
| conformal | 2% | 31.8% (30.7%–33.1%) | 33.8% | 1.89% | 1.89% | 0.73 | 4/10 | 70% |
| conformal | 5% | 48.9% (48.0%–49.9%) | 50.2% | 4.83% | 4.83% | 0.56 | 2/10 | 51% |
| conformal | 10% | 66.4% (65.1%–67.8%) | 67.9% | 9.63% | 9.63% | 0.39 | 3/10 | 61% |
| ltt | 2% | 22.6% (22.0%–23.2%) | 24.3% | 0.82% | 0.82% | 0.82 | 0/10 | 26% |
| ltt | 5% | 37.0% (36.4%–37.6%) | 40.6% | 2.58% | 2.58% | 0.68 | 0/10 | 26% |
| ltt | 10% | 52.6% (51.6%–53.4%) | 55.1% | 5.99% | 5.99% | 0.53 | 0/10 | 26% |

Dataset files (SHA-256):

- `hatespeech_en/measuring-hate-speech.parquet` `6819525ce61bc24344df9fc3f7bf48270b31038273cc27c67fc225b51433b0e1`
