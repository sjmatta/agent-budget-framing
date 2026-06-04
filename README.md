# Does the *framing* of a budget change how an agent behaves?

A controlled study of whether labelling an agent's depleting tool-call budget as
**money**, **time**, a **whimsical currency**, or nothing changes its task quality and
its "panic" — and a cautionary tale about a measurement artifact that produced a
spectacular-but-false headline before we caught it.

> **TL;DR (the honest version).**
> Our first cut found a dramatic result — framing the budget as **"doubloons"** appeared
> to ~10× the odds of a correct answer vs. a neutral budget. **It was an artifact.** The
> task secretly hinged on an *unverifiable string-casing guess* (`status = 'completed'`
> vs `'Completed'`), and the currency label was merely nudging that guess. Once we control
> for casing, **framing has *zero* effect on task quality** (within correctly-cased trials
> every condition is at 100%, χ² p = 1.00). What *survives* is more useful than the
> headline we lost:
> 1. **Agents almost never verify their assumptions** (95% of trials never checked a value)
>    and **silently return confident wrong answers** ("$0.00") from empty result sets.
> 2. **Framing reliably perturbs low-level *stylistic* choices** (here, SQL string casing) —
>    real, but mundane, not "intelligence." On a brittle task that's enough to swing outcomes.
> 3. **Urgent "running-low" framing modestly raises judged panic** (the one affective,
>    casing-independent signal).

Agent: **Claude Sonnet 4.6** (+ a **Haiku 4.5** capability panel) via OpenRouter. Judge:
**GPT-5-mini** (different family, blinded). Eval: **DeepEval** `GEval`. ~2,000 trials, ~$45.

---

## The question & original hypotheses

Hold the budget *mechanics* identical (exactly 5 paid tool calls, 1 per call) and vary
**only the label** the budget is described with. Original predictions:

- **H1 — Money** ("$5, $1/call") → does well, gets *careful* as it runs low.
- **H2 — Time** ("50s, 10s/call") → *slightly worse*, *panics*.
- **H3 — Whimsy** ("doubloons" / "gold-pressed latinum") → *slightly better*, *calmer*.

## The testbed

A budgeted **SQL-analyst agent** over a deterministic synthetic e-commerce SQLite DB
(`db.py`) with exact gold-SQL ground truth (`tasks.py`). Tools: `list_tables`,
`describe_table`, `run_sql` (each costs 1 unit), `final_answer` (free). Conditions live in
`conditions.py`; the agent loop in `agent.py`; a blinded panic judge in `judge.py`; a
resumable, cost-capped orchestrator in `run_experiment.py`.

## What we *first* saw (the seductive, wrong headline)

With the budget tightened to 5 (calibrated so it binds — a looser budget left Sonnet at a
100% ceiling), correctness varied dramatically by framing (equal-task-weighted, n≈84/cond):

| condition | "correctness" | what we wrongly concluded |
|---|---:|---|
| **dubloons** | **0.88** | whimsy makes the agent ~10× better (p<0.0001) |
| control (no budget) | 0.80 | a budget *hurts* |
| time | 0.68 | time wasn't worse |
| credits / money / latinum | 0.50–0.56 | money inert; verbose whimsy worst |

It even *replicated* across two independent runs. It was still an artifact.

## Catching the confounder

Digging into the traces: **correctness was almost perfectly determined by one thing** —
whether the agent wrote `status = 'completed'` (lowercase, matches the data → correct) or
`'Completed'` (title-case → **0 rows → a confident "$0.00, 0 customers" answer**).

| casing the agent used | correctness | n (panel) |
|---|---:|---:|
| `'completed'` (lowercase) | **1.00** | 497 |
| `LOWER(...)` / case-insensitive | 1.00 | 36 |
| `'Completed'` (title-case) | **0.003** | 307 |

`describe_table` exposed column *names/types* but **not values**, so the casing was
*unknowable* without spending a precious query — and **95% of trials never spent it**
(0 ran a `DISTINCT` check or used case-insensitive matching). The agent just *guessed*,
and the currency label nudged the guess:

```
framing → P(lowercase) on the hard task:  money 0.07 · lives 0.07 · credits 0.14 ·
          latinum 0.25 · gems 0.29 · dub_playful 0.32 · dub_urgent 0.82 · doubloons 0.89
```

## The clean, confounder-controlled result

**Mediation check — within correctly-cased trials, does framing still matter?**

| condition (lowercase-casing trials only) | correctness |
|---|---:|
| credits, money, time, dubloons, latinum, gems, goldcoins, lives, tokens, dub_* | **1.00** |

χ² test of framing within correct-casing: **p = 1.00**. The effect is **fully mediated by
the casing guess.** There is **no real framing → analytical-quality effect** in this data.
(Same result holds in Experiment 1's data: within-casing all conditions ~100%.)

### Hypothesis verdicts (honest)

| | verdict |
|---|---|
| **H1 money → better/careful** | ❌ No quality effect (artifact). |
| **H2 time → worse/panicky** | ❌ No quality effect; panic n.s. |
| **H3 whimsy → better/calmer** | ❌ The "doubloons" win was a casing artifact; it did **not** lower panic. The whimsy *class* never replicated (gold coins / gems were flat even before controlling). |
| **"doubloons is special"** | ⚠️ Real but trivial: doubloons framing made the model write lowercase string literals more often (a stylistic-register spillover), which happened to be outcome-determining on a brittle task. Not intelligence. |

### What *does* survive

- **Framing perturbs low-level generation.** A semantically-irrelevant label reliably
  shifted an outcome-determining stylistic choice (SQL casing) from 7% → 89%. Real, and a
  caution: framing effects can be large *and* mechanistically dumb.
- **Urgent framing → more judged panic.** Holding the noun fixed at "doubloons," an urgent
  running-low message ("Careful — only 3 left!") raised the blinded panic score to **0.58**
  vs. ~0.46 for neutral/playful — the one genuine affective effect, independent of casing.
- **Capability > framing.** Haiku 4.5 scored ~100% everywhere and was **immune to framing**
  — not because it's smarter, but because it had a strong prior to write lowercase enums.
  A model's stylistic priors mattered more than any budget label.

### The robust, generalizable finding (better than the headline we lost)

> **Under a binding budget, agents commit to unverifiable assumptions and return silently,
> confidently wrong answers rather than spending an action to check.** 91–95% of trials
> never verified the `status` value; ~13% answered off a 0-row query. The failure is
> *silent* — "$0.00 revenue" with full confidence.

## Implications for a real (cost-constrained) data agent

The practical lesson is **not** "use whimsical currency." It's:

1. **Make value/metadata discovery free.** The whole artifact existed because the schema
   tool hid column *values*. A good data-agent `describe_table` should return **sample /
   distinct values** for low-cardinality columns (enums like `status`) — we fixed exactly
   this in `agent.py`. Then the agent never has to trade an expensive query to learn a fact.
2. **Don't let a tight budget force skipping verification.** Return **row counts**; treat a
   `0-row` result as a signal to re-examine, not an answer. Prefer case-insensitive matching.
3. **Differentiate tools honestly** (`query_postgres`: cheap, iterate freely · `query_athena`:
   slow/expensive, justify first) + **observed-cost feedback** in results + **hard guardrails
   in code** (timeouts, scan limits) + **escalation-to-user** for expensive ops.
4. **Tone:** prefer neutral/mildly-serious over reassuring framing — but **don't expect
   framing to improve correctness**; it mostly perturbs style.
5. **Test your actual model on your actual data.** Capability/stylistic priors dominated
   framing here; the cheap model was more robust.

## Related work (corroborating & contextual)

- **EmotionPrompt** — *LLMs Understand and Can Be Enhanced by Emotional Stimuli* ([arXiv:2307.11760](https://arxiv.org/abs/2307.11760)): framing/affect can change outputs (supports the premise, though our quality effect dissolved).
- **Inducing anxiety in LLMs** ([arXiv:2304.11111](https://arxiv.org/abs/2304.11111)); *Assessing & alleviating state anxiety in LLMs* ([npj Digital Medicine 2025](https://www.nature.com/articles/s41746-025-01512-6)): emotion-induction is measurable — context for our panic signal.
- **Wharton "I'll pay you or I'll kill you"** ([arXiv:2508.00614](https://arxiv.org/pdf/2508.00614)): tips/threats have **no aggregate effect** on benchmarks — matches our money/threat null.
- **Token-Budget-Aware Reasoning (TALE)** ([arXiv:2412.18547](https://arxiv.org/pdf/2412.18547)): stating a budget reshapes behavior; "token elasticity" (too-tight budgets backfire).
- **Budget-Aware Tool-Use (BATS)** ([arXiv:2511.17006](https://arxiv.org/abs/2511.17006)) & **CostBench** ([arXiv:2511.02734](https://arxiv.org/pdf/2511.02734)): tool-call-budget agents; *naive* budgets don't help without budget awareness — aligns with our "budget framing alone doesn't improve quality."

## Limitations

- One task family (SQL over one synthetic DB), one frontier model + one small model.
- The headline artifact is a reminder that **a gradeable outcome can be driven by a hidden
  brittle factor**; we caught it only by reading traces. Treat single-number agent evals
  with suspicion.
- "Panic" is a blinded LLM judgment of reasoning text, not affect; effects are modest.
- The clean *confirmatory* experiment (re-run on the fixed `describe_table` so casing is
  discoverable) is **pending a working API key**; the mediation analysis above already
  establishes the conclusion (framing → quality is fully explained by the casing guess),
  and the fixed harness is committed and ready (`uv run python run_experiment.py ...`).

## Reproduce

```bash
uv run python db.py                       # deterministic DB
uv run python tasks.py                    # gold answers + grader self-test
# set OPENROUTER_API_KEY in .env
uv run python run_experiment.py --tag run --reps 28 \
    --conditions control,credits,money,time,dubloons --tasks germany,top_customer,top_month
uv run python analyze.py        --glob runs/run.jsonl     # primary stats + plots
uv run python analyze_clean.py  --glob runs/run.jsonl     # confounder-controlled re-analysis
uv run python analyze_panel.py  --glob runs/run.jsonl     # currency-property + tone decomposition
```

Code: `db.py`, `tasks.py`, `conditions.py`, `agent.py`, `judge.py`, `run_experiment.py`,
`analyze*.py`. Raw per-trial traces: `runs/*.jsonl` (full reasoning + balances + SQL).
Plots/tables: `results/`.

## Cost

Exp 1 (budget calibration + 6-condition run) ~$18.8 · Exp 2 (10-condition currency panel +
tone probe) ~$20.6 · Haiku capability panel ~$5.0 ≈ **~$45 total**. Sonnet ≈ $0.025/trial
with prompt caching; Haiku ≈ $0.012; GPT-5-mini judge ≈ $0.004.
