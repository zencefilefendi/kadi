# Kadı benchmark — oracle: `labels`

Reflex `hashed` · seeds [0, 1, 2, 3, 4] · audit rate 0.05 · baseline prefix budget 500 · stream length full dataset · Python 3.12.14

Mean over seeds with a 95% bootstrap CI. *err (oracle)* is disagreement with the oracle, the quantity α bounds. *err (gold)* is against the dataset label. *Violations* counts runs with err (oracle) > α; *CP95* is the Clopper–Pearson 95% upper bound on the per-run violation probability. *Calls/dec* includes audits; oracle-only = 1.00.

## banking77

Oracle: kind = labels, oracle_vs_gold = 1

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| conformal-calibrate_on_escalated | 5% | 41.6% (41.2%–41.9%) | 54.9% | 0.69% | 0.69% | 0.58 | 0/5 | 45% |
| conformal-no_freeze | 5% | 60.3% (58.1%–62.5%) | 78.3% | 1.88% | 1.88% | 0.45 | 0/5 | 45% |
| conformal-no_novelty | 5% | 46.9% (44.9%–48.8%) | 61.7% | 1.23% | 1.23% | 0.58 | 0/5 | 45% |
| conformal-no_consistency | 5% | 46.9% (44.9%–48.8%) | 61.7% | 1.23% | 1.23% | 0.58 | 0/5 | 45% |
| conformal-fixed_sampling | 5% | 39.2% (37.2%–41.3%) | 56.4% | 1.15% | 1.15% | 0.63 | 0/5 | 45% |
| ltt-calibrate_on_escalated | 5% | 58.2% (56.2%–61.1%) | 69.8% | 3.17% | 3.17% | 0.42 | 0/5 | 45% |
| ltt-no_freeze | 5% | 62.2% (61.0%–63.5%) | 73.5% | 1.78% | 1.78% | 0.43 | 0/5 | 45% |
| ltt-no_novelty | 5% | 49.2% (47.3%–51.0%) | 62.3% | 1.86% | 1.86% | 0.56 | 0/5 | 45% |
| ltt-no_consistency | 5% | 49.2% (47.3%–51.0%) | 62.3% | 1.86% | 1.86% | 0.56 | 0/5 | 45% |
| ltt-fixed_sampling | 5% | 36.2% (34.0%–38.5%) | 56.2% | 1.41% | 1.41% | 0.66 | 0/5 | 45% |
| mondrian-calibrate_on_escalated | 5% | 0.1% (0.1%–0.1%) | 0.1% | 0.00% | 0.00% | 1.00 | 0/5 | 45% |
| mondrian-no_freeze | 5% | 24.0% (22.8%–25.3%) | 37.7% | 0.12% | 0.12% | 0.80 | 0/5 | 45% |
| mondrian-no_novelty | 5% | 0.1% (0.1%–0.1%) | 0.1% | 0.00% | 0.00% | 1.00 | 0/5 | 45% |
| mondrian-no_consistency | 5% | 0.1% (0.1%–0.1%) | 0.1% | 0.00% | 0.00% | 1.00 | 0/5 | 45% |
| mondrian-fixed_sampling | 5% | 0.1% (0.1%–0.1%) | 0.1% | 0.00% | 0.00% | 1.00 | 0/5 | 45% |

## clinc150

Oracle: kind = labels, oracle_vs_gold = 0.9998

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| conformal-calibrate_on_escalated | 5% | 56.1% (55.8%–56.5%) | 68.1% | 0.55% | 0.56% | 0.44 | 0/5 | 45% |
| conformal-no_freeze | 5% | 78.4% (77.3%–79.6%) | 94.3% | 3.53% | 3.54% | 0.27 | 0/5 | 45% |
| conformal-no_novelty | 5% | 66.0% (64.3%–68.0%) | 83.8% | 1.97% | 1.98% | 0.39 | 0/5 | 45% |
| conformal-no_consistency | 5% | 66.0% (64.3%–68.0%) | 83.8% | 1.97% | 1.98% | 0.39 | 0/5 | 45% |
| conformal-fixed_sampling | 5% | 61.9% (59.0%–63.7%) | 81.3% | 1.89% | 1.90% | 0.41 | 0/5 | 45% |
| ltt-calibrate_on_escalated | 5% | 69.4% (68.8%–70.1%) | 80.9% | 2.35% | 2.37% | 0.31 | 0/5 | 45% |
| ltt-no_freeze | 5% | 76.2% (75.1%–77.3%) | 87.1% | 1.64% | 1.65% | 0.29 | 0/5 | 45% |
| ltt-no_novelty | 5% | 65.1% (62.8%–67.7%) | 82.0% | 1.72% | 1.73% | 0.40 | 0/5 | 45% |
| ltt-no_consistency | 5% | 65.1% (62.8%–67.7%) | 82.0% | 1.72% | 1.73% | 0.40 | 0/5 | 45% |
| ltt-fixed_sampling | 5% | 55.1% (50.5%–59.1%) | 77.6% | 1.45% | 1.46% | 0.48 | 0/5 | 45% |
| mondrian-calibrate_on_escalated | 5% | 0.0% (0.0%–0.0%) | 0.0% | 0.00% | 0.02% | 1.00 | 0/5 | 45% |
| mondrian-no_freeze | 5% | 30.6% (27.8%–33.4%) | 45.3% | 0.06% | 0.08% | 0.73 | 0/5 | 45% |
| mondrian-no_novelty | 5% | 0.0% (0.0%–0.0%) | 0.0% | 0.00% | 0.02% | 1.00 | 0/5 | 45% |
| mondrian-no_consistency | 5% | 0.0% (0.0%–0.0%) | 0.0% | 0.00% | 0.02% | 1.00 | 0/5 | 45% |
| mondrian-fixed_sampling | 5% | 0.0% (0.0%–0.0%) | 0.0% | 0.00% | 0.02% | 1.00 | 0/5 | 45% |

## offenseval_tr

Oracle: kind = labels, oracle_vs_gold = 1

| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |
|---|---|---|---|---|---|---|---|---|
| conformal-calibrate_on_escalated | 5% | 93.7% (93.3%–94.3%) | 98.2% | 18.35% | 18.35% | 0.06 | 5/5 | 100% |
| conformal-no_freeze | 5% | 58.2% (57.5%–59.0%) | 64.2% | 4.56% | 4.56% | 0.47 | 0/5 | 45% |
| conformal-no_novelty | 5% | 51.4% (49.6%–53.0%) | 57.8% | 4.20% | 4.20% | 0.54 | 0/5 | 45% |
| conformal-no_consistency | 5% | 51.4% (49.6%–53.0%) | 57.8% | 4.20% | 4.20% | 0.54 | 0/5 | 45% |
| conformal-fixed_sampling | 5% | 50.7% (48.4%–53.1%) | 56.5% | 4.56% | 4.56% | 0.52 | 1/5 | 66% |
| ltt-calibrate_on_escalated | 5% | 60.6% (59.7%–61.5%) | 68.2% | 5.99% | 5.99% | 0.39 | 5/5 | 100% |
| ltt-no_freeze | 5% | 41.3% (40.0%–42.7%) | 45.9% | 2.22% | 2.22% | 0.64 | 0/5 | 45% |
| ltt-no_novelty | 5% | 35.7% (34.3%–37.1%) | 44.2% | 2.26% | 2.26% | 0.69 | 0/5 | 45% |
| ltt-no_consistency | 5% | 35.7% (34.3%–37.1%) | 44.2% | 2.26% | 2.26% | 0.69 | 0/5 | 45% |
| ltt-fixed_sampling | 5% | 29.6% (24.2%–33.8%) | 36.6% | 2.54% | 2.54% | 0.72 | 0/5 | 45% |
| mondrian-calibrate_on_escalated | 5% | 75.2% (74.2%–76.0%) | 88.2% | 18.70% | 18.70% | 0.25 | 5/5 | 100% |
| mondrian-no_freeze | 5% | 32.7% (31.0%–34.4%) | 37.7% | 4.10% | 4.10% | 0.72 | 0/5 | 45% |
| mondrian-no_novelty | 5% | 30.0% (28.8%–32.1%) | 34.9% | 4.10% | 4.10% | 0.75 | 0/5 | 45% |
| mondrian-no_consistency | 5% | 30.1% (28.9%–32.2%) | 34.9% | 4.19% | 4.19% | 0.75 | 0/5 | 45% |
| mondrian-fixed_sampling | 5% | 27.6% (25.2%–29.9%) | 33.6% | 4.48% | 4.48% | 0.74 | 0/5 | 45% |

Dataset files (SHA-256):

- `banking77/train.csv` `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`
- `banking77/test.csv` `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`
- `clinc150/data_full.json` `36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0`
- `offenseval_tr/offenseval2020-turkish.zip` `7977e96255dbc9b8d14893f1b14cbe3dec53c70358503c062c5a59720ec9c2f2`
