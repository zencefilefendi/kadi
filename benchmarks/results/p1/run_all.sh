#!/bin/bash
# P1 evidence matrix. Reproduce with:  bash benchmarks/results/p1/run_all.sh  (needs the [embed] extra + pyarrow)
set -u
PY=${PY:-.venv/bin/python}
OUT=benchmarks/results/p1
S10=0,1,2,3,4,5,6,7,8,9
S5=0,1,2,3,4
# A: new datasets, zero-dependency reflex, policies + baselines, 10 seeds
$PY benchmarks/run.py --datasets massive_tr,offenseval_tr,hatespeech_en --policies conformal,ltt --alphas 0.02,0.05,0.1 \
    --taus 0.5,0.9 --baselines tuned,deferral --seeds $S10 --out $OUT --tag=-A-new-hashed
# B: new datasets, semantic reflex (multilingual MiniLM for Turkish, bge for English), 10 seeds
$PY benchmarks/run.py --datasets massive_tr --reflex minilm --knn --policies conformal,ltt --alphas 0.02,0.05,0.1 \
    --taus "" --baselines tuned,deferral --seeds $S10 --out $OUT --tag=-B-tr-minilm
$PY benchmarks/run.py --datasets offenseval_tr --reflex minilm --knn --policies conformal,ltt --alphas 0.02,0.05,0.1 \
    --taus "" --baselines tuned,deferral --seeds $S10 --out $OUT --tag=-B-tr-minilm-offenseval
$PY benchmarks/run.py --datasets hatespeech_en --reflex bge --knn --policies conformal,ltt --alphas 0.02,0.05,0.1 \
    --taus "" --baselines tuned,deferral --seeds $S10 --out $OUT --tag=-B-en-bge
# C: Banking77 / CLINC150 at alpha = 5%, 10 seeds, both reflexes, with the fair baselines
$PY benchmarks/run.py --datasets banking77,clinc150 --policies conformal,ltt --alphas 0.05 --taus "" --baselines tuned,deferral \
    --seeds $S10 --out $OUT --tag=-C-intent-hashed
$PY benchmarks/run.py --datasets banking77,clinc150 --reflex bge --knn --policies conformal,ltt --alphas 0.05 --taus "" \
    --baselines tuned,deferral --seeds $S10 --out $OUT --tag=-C-intent-bge
# D: ablations (each disables one mechanism), 5 seeds
$PY benchmarks/run.py --datasets banking77,clinc150,offenseval_tr --policies conformal,ltt,mondrian --alphas 0.05 --taus "" \
    --ablate calibrate_on_escalated,no_freeze,no_novelty,no_consistency,fixed_sampling --seeds $S5 --out $OUT --tag=-D-ablations
# E: a 3%-noisy oracle: three-way metrics and the noise floor, 5 seeds
$PY benchmarks/run.py --datasets banking77,offenseval_tr --oracle noisy:0.03 --policies conformal,ltt --alphas 0.02,0.05,0.1 \
    --taus "" --baselines tuned --seeds $S5 --out $OUT --tag=-E-noisy
echo "ALL DONE"
