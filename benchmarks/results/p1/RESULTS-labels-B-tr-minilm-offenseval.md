# Kadı benchmark — oracle: `labels`

Reflex `minilm+knn` · seeds [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] · audit rate 0.05 · baseline prefix budget 500 · stream length full dataset · Python 3.12.14

Mean over seeds with a 95% bootstrap CI. *err (oracle)* is disagreement with the oracle, the quantity α bounds. *err (gold)* is against the dataset label. *Violations* counts runs with err (oracle) > α; *CP95* is the Clopper–Pearson 95% upper bound on the per-run violation probability. *Calls/dec* includes audits; oracle-only = 1.00.

## offenseval_tr

Oracle: kind = labels, oracle_vs_gold = 1

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| tuned | 2% | 11.4% (10.5%–12.4%) | 11.1% | 0.33% | 0.33% | 0.89 | 0/10 | 26% |
| tuned | 5% | 24.8% (23.9%–25.7%) | 23.8% | 1.31% | 1.31% | 0.75 | 0/10 | 26% |
| tuned | 10% | 49.3% (47.6%–51.0%) | 48.1% | 4.59% | 4.59% | 0.51 | 0/10 | 26% |
| deferral | 2% | 20.5% (13.8%–27.0%) | 20.2% | 1.07% | 1.07% | 0.79 | 1/10 | 39% |
| deferral | 5% | 32.2% (28.2%–37.0%) | 31.6% | 2.13% | 2.13% | 0.68 | 0/10 | 26% |
| deferral | 10% | 55.2% (50.7%–60.0%) | 54.7% | 6.10% | 6.10% | 0.45 | 0/10 | 26% |
| conformal | 2% | 31.9% (30.9%–33.0%) | 34.8% | 1.87% | 1.87% | 0.73 | 1/10 | 39% |
| conformal | 5% | 49.4% (48.2%–50.5%) | 51.3% | 4.60% | 4.60% | 0.56 | 1/10 | 39% |
| conformal | 10% | 68.7% (67.4%–69.8%) | 71.1% | 9.65% | 9.65% | 0.36 | 2/10 | 51% |
| ltt | 2% | 19.5% (18.8%–20.2%) | 22.4% | 0.78% | 0.78% | 0.86 | 0/10 | 26% |
| ltt | 5% | 37.0% (35.6%–38.5%) | 42.0% | 2.56% | 2.56% | 0.68 | 0/10 | 26% |
| ltt | 10% | 56.3% (55.3%–57.7%) | 60.8% | 6.25% | 6.25% | 0.49 | 0/10 | 26% |

Dataset files (SHA-256):

- `offenseval_tr/offenseval2020-turkish.zip` `7977e96255dbc9b8d14893f1b14cbe3dec53c70358503c062c5a59720ec9c2f2`
