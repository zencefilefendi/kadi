# Kadı — Theory and Guarantees

This document states precisely what Kadı guarantees, under which assumptions, and where the guarantee ends. Notation follows Angelopoulos & Bates (2021).

---

## 1. Problem

A *question* is a finite label set $\mathcal{Y} = \{y_1, \dots, y_K\}$ with an error budget $\alpha \in (0,1)$. Inputs $x_t$ arrive as a stream. An **oracle** $O$ (typically a frontier LLM) maps each input to a label $O(x) \in \mathcal{Y}$ at a cost $c > 0$. Kadı must return a label $\hat{y}_t \in \mathcal{Y}$ for every input and wants to:

$$
\text{minimise}\;\; \mathbb{E}[\text{oracle calls}] \quad \text{subject to} \quad \Pr\big(\hat{y}_t \neq O(x_t)\big) \le \alpha .
$$

Agreement is defined **relative to the oracle**. If the oracle is wrong, Kadı copies its mistakes; it never claims to beat the oracle.

## 2. The cascade

```
x ─► memory   exact replay of a previous oracle verdict (keyed HMAC of the raw input)
  └► reflex   the SERVED frozen model version p̂_v(y | x), with its own certificate
  └► oracle   O(x); its verdict trains the LIVE model and calibrates certified versions
  └► fallback oracle unavailable and policy = best_guess → argmax p̂, flagged
```

**Versions (v0.6).** Training never changes the model that answers. A *live* model learns from every oracle label. When it has seen enough new data (first after 300 labels, then each time it has seen 2× the served version's data), it is frozen into a *candidate* version $v$ with a fresh calibrator. That calibrator only ever sees calibration samples drawn **after** the freeze (§5). A certified candidate replaces the served version once it answers at least as often on the same samples. The initial version 0 is untrained and never certified.

The reflex answers **only** when all of the following hold. Otherwise the input is escalated.

1. The served version is certified (§3, §3b).
2. The prediction set has at most one label: $|C(x)| \le 1$. An empty set answers the argmax, as explained after Corollary 1.
3. That label equals $\arg\max_y \hat{p}(y\mid x)$ (the consistency rule).
4. The novelty $\nu(x) \le \tau$ (§6).
5. The court is not on probation (§6).

Rules 3–5 can only *remove* local answers. Escalating never adds error relative to the oracle, so these rules preserve every bound below.

## 3. Split conformal prediction

**Nonconformity score.** $s(x, y) = 1 - \hat{p}(y \mid x)$.

**Calibration set.** $\{(x_i, y_i)\}_{i=1}^{n}$, where $y_i = O(x_i)$. It must be a **random sample of the stream drawn after the scored model version was frozen** (§5).

**Threshold.** Let $s_{(1)} \le \dots \le s_{(n)}$ be the sorted scores $s(x_i, y_i)$, and

$$
\hat{q} = s_{(k)}, \qquad k = \big\lceil (n+1)(1-\alpha) \big\rceil
$$

with $\hat{q} = +\infty$ if $k > n$.

**Prediction set.** $C(x) = \{\, y \in \mathcal{Y} : s(x, y) \le \hat{q} \,\}$.

**Theorem 1 (marginal coverage; Vovk et al. 2005; Papadopoulos et al. 2002; Lei et al. 2018).** If the calibration pairs and the test pair $(x_{n+1}, O(x_{n+1}))$ are exchangeable and $\hat{p}$ is fixed with respect to them, then

$$
\Pr\big(O(x_{n+1}) \in C(x_{n+1})\big) \ge 1 - \alpha .
$$

**Corollary 1 (Kadı's decision error).** A disagreement with the oracle can only happen when Kadı answers locally. A local answer happens when $C(x) = \{\hat{y}\}$, or when $C(x) = \emptyset$ (Kadı then answers the argmax). In both cases a disagreement $\hat{y} \ne O(x)$ implies $O(x) \notin C(x)$; with an empty set this holds even when the answer is right. Escalated answers *are* the oracle's answer. Therefore

$$
\Pr\big(\hat{y} \neq O(x)\big) \;\le\; \Pr\big(O(x) \notin C(x)\big) \;\le\; \alpha .
$$

Answering on empty sets therefore costs nothing against the bound. It also makes the local share monotone in α: before v0.6, a larger α could *shrink* the local share, because tighter thresholds produced more empty sets and those were escalated.

The bound is **marginal**: it holds over the stream, not for each input separately. It is typically conservative, because escalated decisions contribute no errors.

## 3b. Anytime-valid Learn then Test (`policy = "ltt"`)

Theorem 1 holds *in expectation over the calibration draw*. Learn then Test (Angelopoulos, Bates, Candès, Jordan & Lei 2021) gives a PAC-style statement for selective classification instead. Kadı v0.6 makes it hold **uniformly over time**, because the certificate is re-examined after every calibration sample.

**Decision rule.** Answer locally iff $\max_y \hat{p}_v(y\mid x) \ge \lambda_v$, where $\hat{p}_v$ is the served frozen version. The answer is the argmax.

**Loss.** For a calibration pair, $L_i(\lambda) = \mathbf{1}\{\max_y \hat{p}_v(y\mid x_i) \ge \lambda \;\wedge\; \arg\max_y \hat{p}_v(y\mid x_i) \ne y_i\}$, i.e. "answered locally, and wrongly"; escalations cost 0. Its mean $R_v(\lambda)$ is exactly the probability that a returned decision of version $v$ disagrees with the oracle.

**Test.** For each $\lambda$ on a grid fixed in advance (`LTT_GRID`, from strict to loose), Kadı tests $H_0(\lambda): R_v(\lambda) > \alpha$ with a betting **e-process**

$$
K_t(\lambda) = \sum_j w_j \prod_{s \le t} \big(1 + b_j\,(\alpha - L_s(\lambda))\big), \qquad b_j = f_j/(1-\alpha),
$$

using fixed bet fractions $f = (0.9, 0.5, 0.25, 0.1)$ with prior weights $w = (0.6, 0.25, 0.1, 0.05)$. Under $H_0$ every factor has conditional mean ≤ 1, so $K_t$ is a non-negative supermartingale. By **Ville's inequality**, $\Pr(\sup_t K_t \ge 1/\delta) \le \delta$, so $p_t = 1/\max_{s\le t} K_s$ is an anytime-valid p-value (Ramdas, Grünwald, Vovk & Shafer 2023; Waudby-Smith & Ramdas 2024). Fixed-sequence testing then certifies $\hat{\lambda}_t$, the loosest $\lambda$ such that every stricter grid point has $\max_{s \le t} K_s \ge 1/\delta_v$. The certified threshold only ever loosens.

**Theorem 2′ (time-uniform).** Assume the calibration samples of version $v$ are exchangeable draws from the stream, which holds because they are chosen by an input-independent coin after the freeze (§5), and $\hat{p}_v$ is fixed. Then

$$
\Pr\Big(\exists\, t:\; R_v(\hat{\lambda}_t) > \alpha\Big) \le \delta_v .
$$

**Error budget across versions.** Version $v$ is certified at $\delta_v = \delta \cdot 6/(\pi^2 v^2)$. Since $\sum_v \delta_v = \delta$, a union bound gives that **all certificates ever issued hold simultaneously, at all times, with probability ≥ 1 − δ**. Any rule for choosing which certified version to serve, including "promote the candidate that answers more", is therefore valid.

**Price.** With no errors, a threshold certifies after the smallest $n$ with $\sum_j w_j (1 + b_j\alpha)^n \ge 1/\delta_v$: 74 samples at α = δ = 5% (the one-shot binomial test of v0.5 needed 59), and 156 for the 5th version. Validity is checked by simulation: `tests/test_core.py::test_ltt_certificate_is_anytime_valid` measures the fraction of 200 streams of 1,000 samples in which the certified threshold *ever* has risk > α.

**Conformal or LTT?** The conformal rule demands a set with at most one label; LTT tests the decision risk directly. Conformal keeps per-label (Mondrian) guarantees and ACI adaptivity, but its guarantee is in expectation, not time-uniform.

## 4. Class-conditional (Mondrian) guarantee

With `conditional=True`, Kadı keeps one calibrator per label $y$, using only the calibration examples whose oracle label is $y$. Label $y$ is included in $C(x)$ iff $s(x,y) \le \hat{q}_y$. Under exchangeability *within each label* (Vovk 2012):

$$
\Pr\big(O(x) \in C(x) \mid O(x) = y\big) \ge 1 - \alpha \qquad \forall\, y \in \mathcal{Y}.
$$

So a rare label such as "fraud" or "urgent" gets its own bound and cannot hide behind a good average. The price is coverage: every label must collect $n_{\min}$ examples before the court may answer locally, and the per-label sets are wider.

## 5. Calibration: random, after the freeze, never re-scored

Two tempting shortcuts each break Theorem 1.

**(a) Calibrating on escalated examples.** An input is escalated precisely because $|C(x)| \ge 2$, so $O(x) \in C(x)$ holds *by construction*. The observed miscoverage is then biased toward zero. ACI reads this as "too conservative" and raises $\alpha_t$, which shrinks the sets. That produces more local answers whose errors are never observed, and the loop feeds itself. An early prototype of Kadı did exactly this: with an imbalanced binary question and per-label calibration, local answers disagreed with the oracle **58%** of the time. `tests/test_production.py::TestGuarantee` pins the fix.

**(b) Scoring with a model that depends on the calibration data.** In v0.3–v0.5, held-out samples were never trained on, but they steered which escalations *did* train the model, and that model later re-scored them. So "$\hat p$ independent of the calibration set" held only approximately.

**Kadı's rule (v0.6).**
- **Selection.** Each decision is a calibration sample iff $u_t < \rho_t$, with $u_t \sim \mathrm{Unif}(0,1)$. The rate $\rho_t$ may depend on the court's *past*, but never on the current input, so the selected cases are exchangeable with the traffic.
- **Freeze before use.** A sample calibrates only versions frozen *before* it was drawn, and it is scored by those frozen models. The scored model is therefore independent of its calibration data, exactly as Theorems 1 and 2′ require. Nothing is ever re-scored.
- **Labels still train.** After calibrating, the label also trains the live model. Future versions are calibrated only on samples drawn after *their* freeze, so this is safe. The 25% of warm-up labels that v0.5 had to withhold from training are recovered.
- **Sampling rate.** Sampling an escalated case is free: the oracle is called anyway. Only sampled local answers cost an extra call. Kadı therefore samples everything while the served version is uncertified or the court is in shadow mode, and otherwise uses $\rho_t = \min\{1, \max(\texttt{audit\_rate}, \texttt{sample\_budget}/\ell_t)\}$, where $\ell_t$ is the recent local share. This keeps the extra oracle cost near `sample_budget` calls per decision.

## 6. Adaptivity, novelty and drift

**Adaptive Conformal Inference (Gibbs & Candès 2021).** Kadı replaces the fixed $\alpha$ with $\alpha_t$ and updates it after every calibration example:

$$
\alpha_{t+1} = \alpha_t + \gamma\,\big(\alpha - \mathrm{err}_t\big), \qquad \mathrm{err}_t = \mathbf{1}\{O(x_t) \notin C_t(x_t)\}.
$$

For any sequence, including adversarial ones, the long-run miscoverage on these examples satisfies

$$
\left| \frac{1}{T}\sum_{t=1}^{T} \mathrm{err}_t - \alpha \right| \le \frac{\max(\alpha_1, 1-\alpha_1) + \gamma}{\gamma T}.
$$

The calibration examples are an input-independent thinning of the stream, so this transfers in expectation to the stream itself. But $T$ counts calibration samples, not decisions, which makes the finite-sample bound loose (§7c). Kadı uses $\gamma = 0.005$ and clips $\alpha_t \in [0, 0.999]$.

**Novelty guard.** Inputs are L2-normalised hashed features $x \in \mathbb{R}^{2^{18}}$ (Weinberger et al. 2009). Let $S$ be the set of features the reflex has ever been trained on. The novelty

$$
\nu(x) = \sum_{j \notin S} x_j^2 \in [0, 1]
$$

is the share of input mass on features the reflex has never seen. If $\nu(x) > \tau$ (default $0.8$), the input is escalated, whatever $\hat{p}$ says. This is a cheap out-of-distribution signal (in the spirit of Hendrycks & Gimpel 2017). It also blocks the simplest adversarial strategy of feeding gibberish.

**Drift detector (v0.6).** Kadı monitors the deployed loss $L_t = \mathbf{1}\{\text{local} \wedge \text{wrong}\}$ of the served version on calibration samples. This is the quantity α bounds; v0.5 tested Pr(wrong | local) instead. It uses a Shiryaev–Roberts **e-detector** (Shin, Ramdas & Rinaldo), with one recursion per bet $\lambda_j = c_j/\alpha$, $c \in \{0.01, 0.025, 0.05, 0.1, 0.2, 0.4\}$:

$$
R^{(j)}_t = \big(1 + R^{(j)}_{t-1}\big)\big(1 + \lambda_j (L_t - \alpha)\big).
$$

It raises an alarm when $\tfrac1J \sum_j R^{(j)}_t \ge A$. Under "risk ≤ α", each $R^{(j)}_t - t$, and hence their average, is a supermartingale, so the **expected time to a false alarm is at least $A$** (`drift_arl`, default 1,000 calibration samples). Small bets catch slow drifts, large ones catch abrupt breaks. `tests/test_core.py::test_drift_detector_false_alarms_and_detection` checks both properties by simulation.

On alarm:
- the served frozen model gets a **new certificate** (a new version index and its own $\delta_v$), which can only be earned on samples drawn after the alarm;
- the court escalates everything meanwhile, and for at least `probation_length` decisions;
- an alert is persisted and sent to the webhook, at most once per hour.

Meanwhile the live model keeps learning the new regime, and its next candidate takes over once certified.

## 7. The reflex model

- **Model:** multinomial logistic regression over sparse hashed word uni/bi-grams and character 3–5-grams. Trained online with AdaGrad (Duchi, Hazan & Singer 2011) and L2 regularisation.
- **Teacher:** every oracle verdict is one SGD step on the *live* model; calibration samples train it too, after they have calibrated the versions frozen before them. This is online knowledge distillation from the oracle (Hinton, Vinyals & Dean 2015).
- **Limits:** features are capped at 4,000 characters and 2,048 non-zeros per input. This bounds model growth, calibration memory and checkpoint size.
- **Fit:** a linear model is deliberately simple. It is strong when the decision is lexically signalled (routing, spam, intent, triage). It is weak for decisions that need world knowledge or multi-step reasoning, and there the conformal sets stay wide and Kadı escalates. Escalating is correct behaviour, not a failure.

### 7b. Semantic reflex (optional)

`kadi.embed.KNNHybridReflex` mixes the logistic probabilities with a k-NN vote. The vote takes the $k = 10$ nearest oracle-labelled examples by cosine similarity of L2-normalised sentence embeddings, with weights $\propto \exp(\mathrm{sim}/T)$, $T = 0.02$ and mix $0.8$. Its probabilities are not calibrated, and they do not need to be: the calibration layer (§3–§5) turns any scoring function into a guaranteed decision rule. With the v0.6 engine, on Banking77 and CLINC150, the semantic reflex (bge-small) raised the local share at α = 5% under LTT from 49.1% to 66.2% and from 65.2% to 78.1% respectively. The bound held in all runs. The novelty guard continues to use only the sparse n-gram block, because a dense embedding has no "unseen" dimensions.

## 7c. Statistical caveats: what v0.6 resolved and what remains

The v0.5 expert review listed six caveats. Status:

| Caveat | Status |
|---|---|
| LTT certificate only pointwise in time | **Resolved**: anytime-valid e-process certification (§3b) |
| Model–calibration independence only approximate | **Resolved**: frozen versions calibrated only on later samples, no re-scoring (§5) |
| Drift breaker tested Pr(wrong \| local) with a Wald interval on overlapping windows | **Resolved**: e-detector on the deployed joint loss with ARL control (§6) |
| Mixed sampling rates within one calibration window | **Resolved in effect**: each version is calibrated on its own post-freeze sample. The rate depends only on the past, which keeps the samples exchangeable |
| ACI's finite-sample bound on a thinned stream is loose; clipping α_t at 0.999 departs from the proof | **Remains** (conformal policy only). Use `ltt` for a time-uniform guarantee |
| Memory answers are neither calibrated nor audited | **Remains**. With a noisy oracle, replayed verdicts disagree with a fresh call about ε of the time, so the bound applies to non-memory decisions |

**New in v0.6:**
- **Exchangeability is still assumed.** Time-uniformity removes the "repeated looks" problem, not distribution shift. Under shift, the e-detector is the safeguard.
- **Validity has a utility cost.** Every version must earn its certificate on fresh samples, and later versions spend smaller δ_v. On short streams Kadı therefore answers locally less often than v0.5 did; §10 quantifies this.

## 8. What is *not* guaranteed

1. **Correctness.** Kadı bounds disagreement *with the oracle*, not with the truth. Choose an oracle you trust.
2. **Noise floor.** If the oracle disagrees with itself (sampling, temperature, ambiguity) at rate $\varepsilon$, then audits measure disagreement of at least about $\varepsilon$. With $\alpha \lesssim \varepsilon$ Kadı escalates almost everything, which is the only way to honour the bound. Pick $\alpha$ comfortably above $\varepsilon$, for example with `kadi replay`.
3. **Per-input validity.** The bound is marginal (or per-label with Mondrian). It is never per input.
3b. **Per-run validity under the conformal policy.** Conformal + ACI bounds the *expected* disagreement, and ACI steers realised miscoverage *towards* α. Individual runs therefore end slightly above α a fair share of the time: 26 of 220 runs in the P1 evidence, with every cell mean below α. Per-run, time-uniform statements are what `ltt` provides (0 of 220).
4. **Exchangeability.** Real traffic is not exchangeable. ACI, the drift e-detector (with re-certification) and continuous audits are the mitigation, and the dashboard reports the *realised* miscoverage so the claim can be checked.
5. **Fallback decisions.** When the oracle is down and `on_oracle_error = "best_guess"`, answers carry no guarantee and are flagged as such.

## 9. Empirical check

`examples/demo.py` simulates a 2%-noisy oracle at $0.012 per call. The run has an oracle outage at 30–33% of the stream and a vocabulary drift at 50%. 6,000 tickets, 2 questions, α = 5%:

| | Local | Audited agreement | Decision error (est.) | Realised set miscoverage | Cost vs. oracle-only |
|---|---|---|---|---|---|
| `route_ticket`, marginal | 77.8% | 94.9% | 4.0% | 6.3% | $19.96 vs. $72 |
| `is_urgent`, Mondrian | 52.2% | 95.5% | 2.3% | 5.5% (per-label average) | $36.73 vs. $72 |

Measured with v0.6. Decision error is estimated from audits as local share × audited disagreement, and it stays below α, as Corollary 1 requires. The realised *set* miscoverage on calibration samples is slightly above α. That is allowed by a guarantee that holds in expectation, and it reflects §7c: ACI's finite-sample bound on a thinned stream is loose, and the run includes an outage, a vocabulary drift and a 2%-noisy oracle. Use `ltt` where a high-probability, time-uniform statement is needed. The data are synthetic and lexically easy. Measure your own traffic with `kadi replay` and shadow mode before drawing conclusions.

## 10. Public benchmarks

**Setup.** Banking77 and CLINC150, with gold labels as the oracle, full datasets, 3 seeds. The v0.6 engine uses frozen versions, anytime-valid LTT and the e-detector.

**Validity.** The empirical risk stayed below α in **all 126 runs**, checked per seed.

**The price of strict validity.** Compared with v0.5 (approximate independence, pointwise-in-time certificate), the local share at the same α fell by a median of 9.3 points across 36 comparable configurations (range −1.5 to +19.7). LTT at strict α lost the most, because time-uniform certification and δ spending across versions demand more evidence than a one-shot binomial test.

**Conformal vs LTT.** Conformal now answers locally more often than LTT in 13 of 18 configurations. Its guarantee is in expectation; LTT's holds with probability 1 − δ at every time.

**Mondrian.** It never certifies with 77–150 labels, as expected from §4.

**Results.** At α = 5% with bge-small + k-NN, conformal removes 65% (Banking77) and 79% (CLINC150) of oracle calls; LTT removes 61% and 73%. See [benchmarks/results/](../benchmarks/results/).

**P1 evidence (v0.7).** Across five datasets (including Turkish intent and moderation), 10 seeds, α ∈ {2, 5, 10}% and two reflexes:
- **LTT:** 0/220 runs exceeded α.
- **Conformal:** 26/220 individual runs exceeded α, but no cell's mean did (0/22), consistent with a guarantee in expectation.
- **Fair, uncalibrated baselines** fitted on the same 500-label prefix exceeded α in 91/440 runs, and in 7/44 cell means.
- **Ablation.** Calibrating on escalations (§5a) drove error to 18% at α = 5% on binary moderation. See [benchmarks/results/p1/REPORT.md](../benchmarks/results/p1/REPORT.md).

## References

- Angelopoulos, A. N., Bates, S., Candès, E. J., Jordan, M. I., & Lei, L. (2021). *Learn then Test: Calibrating Predictive Algorithms to Achieve Risk Control.* arXiv:2110.01052.
- Angelopoulos, A. N., & Bates, S. (2021). *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification.* arXiv:2107.07511.
- Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance.* arXiv:2305.05176.
- Duchi, J., Hazan, E., & Singer, Y. (2011). Adaptive Subgradient Methods for Online Learning and Stochastic Optimization. *JMLR* 12.
- Geifman, Y., & El-Yaniv, R. (2017). Selective Classification for Deep Neural Networks. *NeurIPS*.
- Gibbs, I., & Candès, E. (2021). Adaptive Conformal Inference Under Distribution Shift. *NeurIPS*. arXiv:2106.00170.
- Greshake, K., et al. (2023). *Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection.* arXiv:2302.12173.
- Hendrycks, D., & Gimpel, K. (2017). A Baseline for Detecting Misclassified and Out-of-Distribution Examples in Neural Networks. *ICLR*.
- Hinton, G., Vinyals, O., & Dean, J. (2015). *Distilling the Knowledge in a Neural Network.* arXiv:1503.02531.
- Lei, J., G'Sell, M., Rinaldo, A., Tibshirani, R. J., & Wasserman, L. (2018). Distribution-Free Predictive Inference for Regression. *JASA* 113(523).
- Howard, S. R., Ramdas, A., McAuliffe, J., & Sekhon, J. (2021). Time-uniform, nonparametric, nonasymptotic confidence sequences. *Annals of Statistics* 49(2).
- Ong, I., et al. (2024). *RouteLLM: Learning to Route LLMs with Preference Data.* arXiv:2406.18665.
- Papadopoulos, H., Proedrou, K., Vovk, V., & Gammerman, A. (2002). Inductive Confidence Machines for Regression. *ECML*.
- Ramdas, A., Grünwald, P., Vovk, V., & Shafer, G. (2023). Game-theoretic statistics and safe anytime-valid inference. *Statistical Science* 38(4).
- Shin, J., Ramdas, A., & Rinaldo, A. E-detectors: a nonparametric framework for sequential change detection.
- Ville, J. (1939). *Étude critique de la notion de collectif.* Gauthier-Villars.
- Vovk, V. (2012). Conditional Validity of Inductive Conformal Predictors. *ACML*.
- Vovk, V., Gammerman, A., & Shafer, G. (2005). *Algorithmic Learning in a Random World.* Springer.
- Waudby-Smith, I., & Ramdas, A. (2024). Estimating means of bounded random variables by betting. *JRSSB* 86(1).
- Weinberger, K., Dasgupta, A., Langford, J., Smola, A., & Attenberg, J. (2009). Feature Hashing for Large Scale Multitask Learning. *ICML*.
