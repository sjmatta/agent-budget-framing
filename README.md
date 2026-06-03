# Does the *framing* of a budget change how an agent behaves?

An experiment testing whether labelling an agent's depleting tool-call budget as
**money**, **time**, or a **whimsical currency** changes its task quality and its
"panic," holding the underlying mechanics identical.

> **TL;DR.** Framing the budget had a **large, real effect on task quality but not on
> panic** — and *not* in the direction hypothesised. The whimsical **"doubloons"**
> framing was the runaway winner (≈10× the odds of a correct answer vs. a neutral
> "credits" budget, p<0.0001, robust across every task). **Money was no better than
> neutral; time was *better*, not worse; and the other whimsical currency ("gold-pressed
> latinum") was among the worst** — so "whimsy helps" is not a reliable rule. Expressed
> panic was statistically flat across all budget framings. The single biggest lever was
> simply *whether* a budget was mentioned at all: introducing a neutral budget *hurt*
> performance vs. no budget, and only "doubloons" (and partly "time") clawed it back.

Agent: **Claude Sonnet 4.6** via OpenRouter. Judge: **GPT-5-mini** (different family,
blinded). Eval framework: **DeepEval** (`GEval`). 591 trials, ~$15 (full run).

---

## The hypotheses (from the original brief)

| # | Hypothesis | Verdict |
|---|------------|---------|
| **H1** | **Money** ("$5, $1/call") → does a good job, gets *more careful* as it runs low | ❌ **Not supported.** Money matched the neutral baseline on quality (OR 0.80, n.s.) and did not lower panic. |
| **H2** | **Time** ("50s, 10s/call") → *slightly worse*, *panics* | ❌ **Refuted on quality** (time did *better*, not worse: OR 2.11). Panic only weakly/non-significantly higher. |
| **H3** | **Whimsy** ("doubloons" / "latinum") → *slightly better*, *calmer* | ⚠️ **Split / inconsistent.** `dubloons` was dramatically *better* (OR 9.98 ***), but `latinum` was *not* better (OR 0.68, n.s.). Neither lowered panic. |

(*** p<0.0001 after Holm correction, task-controlled logistic regression vs. the neutral
`credits` baseline.)

---

## Design: hold the mechanics constant, vary only the label

Every condition gave the agent **exactly 5 paid tool calls** (`list_tables`,
`describe_table`, `run_sql`), each costing 1 unit; `final_answer` was free. The *only*
thing that differed between conditions was the **noun/symbol** on the budget. The agent
saw its remaining balance after every paid action via one shared template.

| Condition | Label shown to the agent | What it isolates |
|-----------|--------------------------|------------------|
| `control` | *(no budget mentioned)* | baseline: no budget at all |
| `credits` | "5 credits" | neutral-unit baseline |
| `money`   | "$5.00" | loss-aversion / real stakes |
| `time`    | "50 seconds" (10s/call) | urgency |
| `dubloons`| "5 doubloons" | whimsy (concise) |
| `latinum` | "5 bars of gold-pressed latinum" | whimsy (verbose) |

> Note: the condition *key* is misspelled `dubloons` in the code, but the agent always
> saw the correctly-spelled word "**doubloons**" in its prompt and balance messages — so
> the effect below is not a typo artifact.

**Task.** A SQL data-analyst agent answering analytical questions over a deterministic
synthetic e-commerce SQLite DB (`db.py`), with exact ground truth from gold SQL and
deterministic graders (`tasks.py`). The budget of 5 was calibrated so the budget genuinely
*binds*: the agent doesn't know the schema up front and must spend calls to discover it,
so hard questions can't be answered if it explores inefficiently. Three feasible tasks of
graded difficulty were used for the primary analysis (a fourth, `cat_revenue`, turned out
to need ≥6 calls and was infeasible at budget=5 — 0% correct for *every* condition incl.
control — so it is excluded as non-discriminating).

**Panic measurement.** A DeepEval `GEval` judge (GPT-5-mini, a different model family, to
avoid self-preference bias) scored **composure** on the agent's reasoning trace, *blinded*
to the condition: the trace it saw expressed the budget only as a neutral
`[actions left: k]` count and had currency words sanitised, so it scored genuine
expressed haste — not the label. Panic = 1 − composure. Orientation was validated on
hand-built calm vs. panicked traces (calm→0.00, panicked→1.00). Deterministic,
label-immune proxies (SQL error rate, duplicate queries, verification-before-answering)
were logged to triangulate.

---

## Results (n ≈ 95–101 / condition; 84 feasible-task trials / condition)

### Correctness — a strong, significant framing effect

Omnibus: **χ² = 42.5, p < 0.0001**. Task-controlled logistic regression
(`correct ~ condition + task`, reference = neutral `credits`):

| Condition | Correct (equal-task-weighted) | Odds ratio vs. credits | p (Holm) |
|-----------|------------------------------:|----------------------:|---------:|
| **dubloons** | **0.881** | **9.98** | **<0.0001** |
| control   | 0.798 | 4.76 | 0.0006 |
| time      | 0.679 | 2.11 | 0.168 |
| credits   | 0.560 | 1.00 (ref) | — |
| money     | 0.524 | 0.80 | 0.66 |
| latinum   | 0.500 | 0.68 | 0.66 |

The effect holds **on every feasible task** — it is not a task-mix artifact (see
`results/correct_heatmap.png`). On the hard `germany` question: `dubloons` **0.82** vs.
`credits` **0.04**, `money` 0.14, `latinum` 0.25, `time` 0.43, `control` 0.54.

### Panic — flat across budget framings

Omnibus: **Kruskal–Wallis H = 8.69, p = 0.12 (n.s.)**. Mean blinded panic: `control` 0.527,
`time` 0.480, `latinum` 0.463, `dubloons` 0.465, `money` 0.460, `credits` 0.408. The only
contrast that survived correction was `control` > `credits` (p_holm = 0.021) — i.e. the
*no-budget* agent looked **less** composed than budgeted ones, the opposite of "budgets
make it panic." Among the four budget *labels*, panic was indistinguishable.

Notably, **SQL error rate was 0.00 in every condition** — Sonnet never wrote broken SQL.
"Panic," to the extent it existed, never manifested as mistakes; quality differences came
entirely from **how wisely the 5 actions were spent** before the cap, not from errors.

---

## What actually happened (interpretation)

1. **The dominant variable wasn't money/time/whimsy — it was whether a budget was
   mentioned at all, and the *specific word* used.** Adding a *neutral* budget (`credits`)
   *dropped* correctness from 0.80 (control) to 0.56. Mentioning scarcity seems to make
   Sonnet ration its exploration *too* aggressively on hard questions and run out before
   finding the answer (run-out rate ~0.73–0.78 across all budgeted conditions).

2. **"Doubloons" uniquely reversed that and then some** (0.88, beating even no-budget
   control). With the same 5 actions and a similar run-out rate, it simply *spent them
   better* — front-loading the query that mattered. Why a pirate currency? Two live
   explanations, not yet separable:
   - **Whimsy/engagement:** a playful, concrete, countable token reframes the budget as a
     fun optimisation game rather than a threat.
   - **Verbosity confound:** `dubloons` is terse; `latinum`'s balance line
     ("…5 bars of gold-pressed latinum…") is long and repeated every turn, adding prompt
     clutter. `latinum` being among the *worst* is consistent with verbosity hurting — so
     the dubloons-vs-latinum gap may be about **prompt economy**, not whimsy.

3. **The panic hypotheses simply didn't hold.** A blinded judge found no reliable
   difference in expressed panic between money, time, doubloons, and latinum, and no
   behavioural panic (zero SQL errors). For a model as strong as Sonnet, budget *labels*
   change *strategy/quality* without changing visible *affect*.

---

## Caveats & limitations (read before trusting any of this)

- **One model.** All of this is Sonnet 4.6. A weaker model is where "panic" is most likely
  to actually appear; these conclusions may not generalise down-capability.
- **The `dubloons` win needs replication and a mechanism test.** It is large and
  statistically robust *here*, but it's a single wording. The clean follow-up: cross
  multiple whimsical currencies (concise vs. verbose) × neutral, to separate **whimsy**
  from **prompt verbosity**. Until then, treat "doubloons make agents smarter" as a
  provocative lead, not a law.
- **Budget had to be tightened to 5** (from the brief's illustrative $10) because at a
  looser budget Sonnet hit a **100% correctness ceiling** and nothing could move (see the
  budget-7 pilot, `runs/pilot.jsonl`, 120 trials — kept as exploratory data, *not* pooled
  with the budget-5 results since the mechanics differ).
- **Panic is a judged construct.** It's a blinded LLM rating of reasoning text; it is not
  physiological panic and may miss subtle strategy shifts. The deterministic proxies
  agreed (no error-rate differences), which is reassuring but also means the construct had
  little behavioural variance to detect at this capability level.
- **The run survived an out-of-credits interruption** mid-experiment; the harness is
  resumable and cells were rebalanced to exactly 84 feasible trials each afterward, so the
  final dataset is balanced.

---

## Reproduce

```bash
uv run python db.py                 # build deterministic DB
uv run python tasks.py              # sanity-check gold answers + graders
# set OPENROUTER_API_KEY in .env
uv run python run_experiment.py --tag full --reps 28 --cap 24 \
    --tasks germany,top_customer,top_month
uv run python analyze.py --glob runs/full.jsonl --out results
```

Files: `db.py` (synthetic DB) · `tasks.py` (task bank + graders) · `conditions.py` (the 6
framings) · `agent.py` (budgeted agent loop) · `judge.py` (blinded DeepEval panic judge +
proxies) · `run_experiment.py` (resumable, cost-capped orchestrator) · `analyze.py` (stats
+ plots). Raw per-trial traces: `runs/*.jsonl`. Outputs: `results/` (`summary.csv`,
`contrasts.csv`, `trials.csv`, `by_condition.png`, `correct_heatmap.png`).

## Cost

Pilot (budget-7, 120 trials) $3.72 + full (budget-5, 591 trials) ~$15.1 ≈ **~$19 total**,
well under the $50 key. Sonnet agent ≈ $0.025/trial with prompt caching; GPT-5-mini judge
≈ $0.004/trial.
