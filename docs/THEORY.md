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
  └► reflex   local probabilistic classifier p̂(y | x)
  └► oracle   O(x); its verdict trains the reflex
  └► fallback oracle unavailable and policy = best_guess → argmax p̂, flagged
```

The reflex answers **only** when all of the following hold. Otherwise the input is escalated.

1. The court is calibrated (it has at least $n_{\min}$ calibration examples, per label for Mondrian).
2. The conformal prediction set is a singleton: $|C(x)| = 1$.
3. That singleton equals $\arg\max_y \hat{p}(y\mid x)$ (the consistency rule).
4. The novelty $\nu(x) \le \tau$ (§6).
5. The court is not on probation (§7).

Rules 3–5 can only *remove* local answers. Escalating never adds error relative to the oracle, so these rules preserve every bound below.

## 3. Split conformal prediction

**Nonconformity score.** $s(x, y) = 1 - \hat{p}(y \mid x)$.

**Calibration set.** $\{(x_i, y_i)\}_{i=1}^{n}$, where $y_i = O(x_i)$. The set must be a **random sample of the stream that is never used to train $\hat{p}$**, for the reasons given in §5.

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

**Corollary 1 (Kadı's decision error).** A disagreement with the oracle can only happen when Kadı answers locally. A local answer requires $C(x) = \{\hat{y}\}$, so a disagreement $\hat{y} \ne O(x)$ implies $O(x) \notin C(x)$. Escalated answers *are* the oracle's answer. Therefore

$$
\Pr\big(\hat{y} \neq O(x)\big) \;\le\; \Pr\big(O(x) \notin C(x)\big) \;\le\; \alpha .
$$

The bound is **marginal**: it holds over the stream, not for each input separately. It is also typically conservative, because errors inside escalated decisions are zero.

## 3b. Learn then Test: a high-probability guarantee (`policy = "ltt"`)

Theorem 1 holds *in expectation over the calibration draw*: in an unlucky draw, the realised error rate of a deployed threshold can exceed α. Learn then Test (Angelopoulos, Bates, Candès, Jordan & Lei 2021) replaces it with a PAC-style statement and, for selective classification, uses a less conservative decision rule.

**Decision rule.** Answer locally iff $\max_y \hat{p}(y\mid x) \ge \lambda$. The answer is the argmax.

**Loss.** For a calibration pair, $L_i(\lambda) = \mathbf{1}\{\max_y \hat{p}(y\mid x_i) \ge \lambda \;\wedge\; \arg\max_y \hat{p}(y\mid x_i) \ne y_i\}$. This is "answered locally, and wrongly"; escalations cost 0. Its mean $R(\lambda) = \mathbb{E}[L(\lambda)]$ is exactly the probability that a returned decision disagrees with the oracle.

**Test.** For each $\lambda$ on a grid fixed in advance (`LTT_GRID`, ordered from strict to loose), test $H_0(\lambda): R(\lambda) > \alpha$ with the exact binomial p-value

$$
p(\lambda) = \Pr\Big(\mathrm{Bin}(n, \alpha) \le \textstyle\sum_i L_i(\lambda)\Big).
$$

Under $H_0$ the count is stochastically larger than $\mathrm{Bin}(n,\alpha)$, so the p-value is valid. Fixed-sequence testing rejects while $p(\lambda) \le \delta$ and stops at the first non-rejection; $\hat{\lambda}$ is the loosest rejected threshold. If none is rejected, the court stays uncalibrated and escalates.

**Theorem 2 (Angelopoulos et al. 2021).** With i.i.d. calibration data and $\hat{p}$ independent of it,

$$
\Pr_{\text{calibration}}\Big(R(\hat{\lambda}) \le \alpha\Big) \ge 1 - \delta .
$$

Fixed-sequence testing controls the family-wise error rate at δ, and an error-free certificate needs $n \ge \lceil \log\delta / \log(1-\alpha) \rceil$ samples (59 for α = δ = 0.05; 299 for α = 0.01). The validity of the certificate is checked by simulation in `tests/test_core.py::test_ltt_certificate_is_valid`.

**Conformal or LTT?** The conformal rule demands a *singleton set*, which with many labels is a much stronger requirement than "top label is confident". LTT tests the decision risk directly and so typically answers more locally at the same α (see `benchmarks/`). Conformal keeps two advantages: per-label (Mondrian) guarantees and ACI adaptivity. Under LTT, drift is handled by re-certification on the rolling, re-scored window and by the drift breaker.

## 4. Class-conditional (Mondrian) guarantee

With `conditional=True`, Kadı keeps one calibrator per label $y$, using only the calibration examples whose oracle label is $y$. Label $y$ is included in $C(x)$ iff $s(x,y) \le \hat{q}_y$. Under exchangeability *within each label* (Vovk 2012):

$$
\Pr\big(O(x) \in C(x) \mid O(x) = y\big) \ge 1 - \alpha \qquad \forall\, y \in \mathcal{Y}.
$$

So a rare label such as "fraud" or "urgent" gets its own bound and cannot hide behind a good average. The price is coverage: every label must collect $n_{\min}$ examples before the court may answer locally, and the per-label sets are wider.

## 5. Why the calibration sample must be random *and* held out

Two tempting shortcuts each break Theorem 1.

**(a) Calibrating on escalated examples.** An input is escalated precisely because $|C(x)| \ne 1$. For most escalations this means $|C(x)| \ge 2$, so $O(x) \in C(x)$ holds *by construction*. The observed miscoverage is then biased toward zero. ACI (§6) reads this as "too conservative" and raises $\alpha_t$, which shrinks the sets. That produces more local answers whose errors are never observed, and the loop feeds itself. An early prototype of Kadı did exactly this: with an imbalanced binary question and per-label calibration, local answers disagreed with the oracle **58%** of the time. The regression test `tests/test_production.py::TestGuarantee` pins the fix.

**(b) Training on calibration examples.** If $\hat{p}$ has been trained on $(x_i, y_i)$, then $s(x_i, y_i)$ is optimistically small, $\hat{q}$ is too small, and coverage falls below $1-\alpha$.

**Kadı's rule.** For each decision Kadı draws $u_t \sim \mathrm{Unif}(0,1)$ and marks the decision as a *calibration sample* iff $u_t < \rho_t$, where:

- $\rho_t = 0.25$ during warm-up, when every input is escalated anyway;
- $\rho_t = 0.20$ in shadow mode;
- $\rho_t = $ `audit_rate` when live.

A sampled decision obtains $O(x_t)$, from the escalation it was already making or from an extra *audit* call if it was answered locally. Its label enters the calibration set and **is not used for training**. Unsampled escalations train the model. The calibration set is therefore an i.i.d. thinning of the stream, disjoint from the training data.

**Fresh scores.** $\hat{p}$ keeps learning, so Kadı stores the calibration *inputs* (bounded sparse vectors) and recomputes all scores with the current model after every `RESCORE_EVERY` training updates. Stale scores from an early, weaker model would otherwise dominate the upper tail and keep $\hat{q}$ needlessly large.

## 6. Adaptivity, novelty and drift

**Adaptive Conformal Inference (Gibbs & Candès 2021).** Kadı replaces the fixed $\alpha$ with $\alpha_t$ and updates it after every calibration example:

$$
\alpha_{t+1} = \alpha_t + \gamma\,\big(\alpha - \mathrm{err}_t\big), \qquad \mathrm{err}_t = \mathbf{1}\{O(x_t) \notin C_t(x_t)\}.
$$

For any sequence, including adversarial ones, the long-run miscoverage on these examples satisfies

$$
\left| \frac{1}{T}\sum_{t=1}^{T} \mathrm{err}_t - \alpha \right| \le \frac{\max(\alpha_1, 1-\alpha_1) + \gamma}{\gamma T}.
$$

The calibration examples are a uniform random thinning of the stream, so this transfers in expectation to the stream itself. Kadı uses $\gamma = 0.005$ and clips $\alpha_t \in [0, 0.999]$.

**Novelty guard.** Inputs are L2-normalised hashed features $x \in \mathbb{R}^{2^{18}}$ (Weinberger et al. 2009). Let $S$ be the set of features the reflex has ever been trained on. The novelty

$$
\nu(x) = \sum_{j \notin S} x_j^2 \in [0, 1]
$$

is the share of input mass on features the reflex has never seen. If $\nu(x) > \tau$ (default $0.8$), the input is escalated, whatever $\hat{p}$ says. This is a cheap out-of-distribution signal (in the spirit of Hendrycks & Gimpel 2017). It also blocks the simplest adversarial strategy of feeding gibberish.

**Drift breaker.** Over the last 300 *checks* (audits plus shadow comparisons) let $\hat{r}$ be the observed disagreement rate and $n$ the number of checks. When

$$
\hat{r} - 1.96\sqrt{\hat{r}(1-\hat{r})/n} \;>\; \alpha \quad\text{and}\quad n \ge 50,
$$

the court goes on **probation**: every live decision is escalated for the next $N$ (default 300) non-memory decisions. An alert is persisted and sent to a webhook (rate-limited to one per hour). ACI repairs slow drift; the breaker handles abrupt breaks that ACI's small $\gamma$ would take too long to absorb.

## 7. The reflex model

- **Model:** multinomial logistic regression over sparse hashed word uni/bi-grams and character 3–5-grams. Trained online with AdaGrad (Duchi, Hazan & Singer 2011) and L2 regularisation.
- **Teacher:** every unsampled oracle verdict is one SGD step. This is online knowledge distillation from the oracle (Hinton, Vinyals & Dean 2015).
- **Limits:** features are capped at 4,000 characters and 2,048 non-zeros per input. This bounds model growth, calibration memory and checkpoint size.
- **Fit:** a linear model is deliberately simple. It is strong when the decision is lexically signalled (routing, spam, intent, triage). It is weak for decisions that need world knowledge or multi-step reasoning, and there the conformal sets stay wide and Kadı escalates. Escalating is correct behaviour, not a failure.

### 7b. Semantic reflex (optional)

`kadi.embed.KNNHybridReflex` mixes the logistic probabilities with a k-NN vote. The vote takes the $k = 10$ nearest oracle-labelled examples by cosine similarity of L2-normalised sentence embeddings, with weights $\propto \exp(\mathrm{sim}/T)$, $T = 0.02$ and mix $0.8$. Its probabilities are not calibrated, and they do not need to be: the calibration layer (§3–§5) turns any scoring function into a guaranteed decision rule. On Banking77 and CLINC150 the semantic reflex raised the local share at α = 5% under LTT from 63.9% to 79.6% and from 79.5% to 89.8% respectively, with the bound holding in all runs. The novelty guard continues to use only the sparse n-gram block, because a dense embedding has no "unseen" dimensions.

## 7c. Known statistical caveats (from the v0.5 expert review)

- **Pointwise in time.** LTT is re-certified after every calibration sample, so "with probability ≥ 1 − δ" holds at each fixed time, not uniformly over the stream. Anytime-valid certification is roadmap P0 #1.
- **Approximate independence.** Held-out samples are never trained on, but through q̂/λ, ACI and probation they influence which escalations do train the reflex, and the reflex later re-scores them. Theorems 1–2 therefore hold only approximately. Certifying frozen snapshots is roadmap P0 #2.
- **The drift breaker tests a different quantity.** It tests Pr(wrong | local) with a Wald interval on overlapping windows, while α bounds Pr(local ∧ wrong). A correctly certified court can be put on probation, and false alarms accumulate over time.
- **ACI on a thinned stream.** T counts calibration samples, not decisions, so the finite-sample ACI bound is loose. Clipping α_t at 0.999 departs from the proof.
- **Mixed sampling rates.** The calibration window mixes warm-up samples (ρ = 0.25) with live ones (ρ = audit_rate).
- **Memory answers.** Replayed verdicts are neither calibrated nor audited. With a noisy oracle they disagree with a fresh call about ε of the time, so the bound applies to non-memory decisions.

## 8. What is *not* guaranteed

1. **Correctness.** Kadı bounds disagreement *with the oracle*, not with the truth. Choose an oracle you trust.
2. **Noise floor.** If the oracle disagrees with itself (sampling, temperature, ambiguity) at rate $\varepsilon$, then audits measure disagreement of at least about $\varepsilon$. With $\alpha \lesssim \varepsilon$ Kadı escalates almost everything, which is the only way to honour the bound. Pick $\alpha$ comfortably above $\varepsilon$, for example with `kadi replay`.
3. **Per-input validity.** The bound is marginal (or per-label with Mondrian). It is never per input.
4. **Exchangeability.** Real traffic is not exchangeable. ACI, the drift breaker and continuous audits are the mitigation, and the dashboard reports the *realised* miscoverage so the claim can be checked.
5. **Fallback decisions.** When the oracle is down and `on_oracle_error = "best_guess"`, answers carry no guarantee and are flagged as such.

## 9. Empirical check

`examples/demo.py` simulates a 2%-noisy oracle at $0.012 per call. The run has an oracle outage at 30–33% of the stream and a vocabulary drift at 50%. 6,000 tickets, 2 questions, α = 5%:

| | Local | Audited agreement | Realised miscoverage | Cost vs. oracle-only |
|---|---|---|---|---|
| `route_ticket`, marginal | 94.3% | 99.1% | 3.0% | $6.83 vs. $72 |
| `is_urgent`, Mondrian | 62.6% | 97.8% | 3.7% (per-label average) | $28.09 vs. $72 |

Measured with v0.4. Realised miscoverage is measured on calibration samples, so it includes the outage and drift windows; both stay below α. (An earlier v0.2 run showed 6.0% for `route_ticket` before ACI tightened α<sub>t</sub>, which is the finite-sample behaviour the ACI bound allows.) The decision-level disagreement (1 − audited agreement) is lower than the set miscoverage, as Corollary 1 predicts. The data are synthetic and lexically easy. Measure your own traffic with `kadi replay` and shadow mode before drawing conclusions.

## 10. Public benchmarks

On Banking77 and CLINC150, with gold labels as the oracle, 3 seeds and the full datasets, the empirical risk stayed below α in all 54 runs (18 configurations × 3 seeds, checked per seed). LTT kept more decisions local than conformal at every α. For example, at α = 5% Banking77 gave 63.9% vs. 54.7% and CLINC150 gave 79.5% vs. 74.7%. Mondrian calibration with 77–150 labels rarely becomes certifiable, as expected from §4. With the semantic reflex (bge-small-en or multilingual MiniLM plus k-NN), a further 72 runs again showed no violation, giving 126 of 126 in total. See [benchmarks/results/](../benchmarks/results/).

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
- Ong, I., et al. (2024). *RouteLLM: Learning to Route LLMs with Preference Data.* arXiv:2406.18665.
- Papadopoulos, H., Proedrou, K., Vovk, V., & Gammerman, A. (2002). Inductive Confidence Machines for Regression. *ECML*.
- Vovk, V. (2012). Conditional Validity of Inductive Conformal Predictors. *ACML*.
- Vovk, V., Gammerman, A., & Shafer, G. (2005). *Algorithmic Learning in a Random World.* Springer.
- Weinberger, K., Dasgupta, A., Langford, J., Smola, A., & Attenberg, J. (2009). Feature Hashing for Large Scale Multitask Learning. *ICML*.
