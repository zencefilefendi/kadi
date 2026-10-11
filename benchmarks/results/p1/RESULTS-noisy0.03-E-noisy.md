# Kadı benchmark — oracle: `noisy:0.03`

Reflex `hashed` · seeds [0, 1, 2, 3, 4] · audit rate 0.05 · baseline prefix budget 500 · stream length full dataset · Python 3.12.14

Mean over seeds with a 95% bootstrap CI. *err (oracle)* is disagreement with the oracle, the quantity α bounds. *err (gold)* is against the dataset label. *Violations* counts runs with err (oracle) > α; *CP95* is the Clopper–Pearson 95% upper bound on the per-run violation probability. *Calls/dec* includes audits; oracle-only = 1.00.

## banking77

Oracle: kind = noisy:0.03, flip_rate = 0.03, oracle_vs_gold = 0.9671

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| tuned | 2% | 53.0% (49.5%–56.0%) | 62.5% | 2.78% | 2.76% | 0.47 | 5/5 | 100% |
| tuned | 5% | 64.3% (62.9%–65.6%) | 73.7% | 4.76% | 4.06% | 0.36 | 2/5 | 81% |
| tuned | 10% | 72.3% (71.6%–73.1%) | 80.9% | 7.80% | 6.61% | 0.28 | 0/5 | 45% |
| conformal | 2% | 6.1% (5.5%–6.7%) | 7.9% | 0.07% | 3.23% | 0.98 | 0/5 | 45% |
| conformal | 5% | 27.7% (24.3%–31.5%) | 37.0% | 0.97% | 2.89% | 0.77 | 0/5 | 45% |
| conformal | 10% | 50.5% (47.1%–53.8%) | 63.8% | 3.35% | 3.79% | 0.55 | 0/5 | 45% |
| ltt | 2% | 18.3% (16.7%–19.9%) | 23.4% | 0.65% | 3.13% | 0.87 | 0/5 | 45% |
| ltt | 5% | 36.8% (34.5%–39.7%) | 45.6% | 1.89% | 3.25% | 0.68 | 0/5 | 45% |
| ltt | 10% | 53.4% (51.3%–56.7%) | 63.9% | 4.56% | 4.80% | 0.52 | 0/5 | 45% |

## offenseval_tr

Oracle: kind = noisy:0.03, flip_rate = 0.03, oracle_vs_gold = 0.9704

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| tuned | 2% | 22.8% (19.2%–27.2%) | 21.6% | 1.83% | 3.43% | 0.77 | 1/5 | 66% |
| tuned | 5% | 49.6% (45.1%–54.9%) | 50.1% | 5.32% | 5.48% | 0.50 | 2/5 | 81% |
| tuned | 10% | 71.6% (68.4%–75.9%) | 72.9% | 9.94% | 9.03% | 0.28 | 1/5 | 66% |
| conformal | 2% | 23.2% (22.1%–24.8%) | 26.7% | 1.69% | 3.60% | 0.82 | 0/5 | 45% |
| conformal | 5% | 43.6% (43.2%–43.8%) | 48.0% | 4.33% | 5.14% | 0.62 | 0/5 | 45% |
| conformal | 10% | 68.1% (66.0%–70.2%) | 73.9% | 9.88% | 9.50% | 0.37 | 1/5 | 66% |
| ltt | 2% | 12.6% (11.5%–13.8%) | 15.2% | 0.63% | 3.15% | 0.92 | 0/5 | 45% |
| ltt | 5% | 28.5% (27.4%–29.8%) | 33.5% | 2.38% | 4.00% | 0.77 | 0/5 | 45% |
| ltt | 10% | 47.6% (47.1%–48.3%) | 54.5% | 5.79% | 6.45% | 0.58 | 0/5 | 45% |

Dataset files (SHA-256):

- `banking77/train.csv` `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`
- `banking77/test.csv` `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`
- `offenseval_tr/offenseval2020-turkish.zip` `7977e96255dbc9b8d14893f1b14cbe3dec53c70358503c062c5a59720ec9c2f2`
