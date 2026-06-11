# Does the *framing* of a budget change how an agent behaves?

A controlled study of whether labelling an agent's depleting tool-call budget as
**money**, **time**, a **whimsical currency**, or nothing changes its task quality and its
"panic." We hold the budget *mechanics* identical (exactly 5 paid tool calls, 1 per call)
and vary **only the label**.

Agent: **Claude Sonnet 4.6** (+ a **Haiku 4.5** capability panel) via OpenRouter. Judge:
**GPT-5-mini** (different family, blinded). Eval: **DeepEval** `GEval`. ~2,300 trials, ~$54.

## Findings

- **Framing has no effect on task quality.** Money, time, whimsy, or no label — once the
  task is measured cleanly, every condition is at the same ceiling (n = 288 on the fixed
  harness: 100% correct everywhere).
- **Framing has no effect on how the agent budgets.** `calls_used`, `ran_out`, and
  `answered_with_budget_left` are byte-identical across all conditions *including the
  no-budget control*.
- **Time-framing is not special.** Denominating the budget in time units ("5 seconds / 5
  minutes / 5 hours," each action costs 1) — and varying the unit's implied magnitude —
  changes nothing: quality, efficiency, and blinded panic are all flat (omnibus p = 0.16;
  no contrast survives Holm).
- **The one real behavioral signal is a failure mode, not framing.** Under a binding
  budget, the agent commits to unverifiable assumptions and returns **silently, confidently
  wrong answers** rather than spending an action to check. ~95% of trials never verified a
  key value; ~13% answered off a 0-row query (e.g. "$0.00 revenue," full confidence).
- **Capability dominates framing.** Haiku 4.5 scored ~100% everywhere and was immune to
  framing — its stylistic priors mattered more than any label.

## The testbed

A budgeted **SQL-analyst agent** over a deterministic synthetic e-commerce SQLite DB
(`db.py`) with exact gold-SQL ground truth (`tasks.py`). Tools: `list_tables`,
`describe_table`, `run_sql` (each costs 1 unit), `final_answer` (free). Conditions in
`conditions.py`; agent loop in `agent.py`; a blinded panic judge in `judge.py`; a resumable,
cost-capped orchestrator in `run_experiment.py`. The budget is tightened to 5 calls so it
binds (a looser budget left Sonnet at a 100% ceiling). Original hypotheses were that money →
careful, time → panicky, whimsy → calmer; **all three are rejected.**

## Two measurement artifacts (the methodological core)

The interesting part of this project is that it produced **two** spectacular framing
"effects," both of which were measurement artifacts — one in the agent, one in the judge.

**1. Agent-side: a hidden string-casing guess.** A first cut showed "doubloons" framing
~10×-ing correctness. In fact correctness was almost entirely determined by whether the
agent wrote `status = 'completed'` (lowercase, matches the data → correct) or `'Completed'`
(title-case → 0 rows → a confident "$0.00" answer). `describe_table` exposed column
names/types but **not values**, so the casing was unknowable without spending a query, and
95% of trials never spent it — the agent guessed, and the label merely nudged the guess.

| casing the agent used | correctness | n |
|---|---:|---:|
| `'completed'` (lowercase) | 1.00 | 497 |
| `LOWER(...)` / case-insensitive | 1.00 | 36 |
| `'Completed'` (title-case) | 0.003 | 307 |

A mediation check confirms it: **within correctly-cased trials, framing's effect on
correctness is gone** (χ² p = 1.00). Fix: `describe_table` now returns sample distinct
values, so enum casing is discoverable rather than guessed.

**2. Judge-side: asymmetric blinding.** Testing time-units, the panic judge showed a clean
felt-duration gradient (`minutes` 0.67 vs `seconds` 0.30). It was a blinding bug: `judge.py`
sanitized the word "seconds" but **not "minutes"/"hours,"** so the blinded trace still
contained explicit time-pressure language in two of three conditions, and the judge scored
what it could see. Making the blinding symmetric collapses the gradient (spread 0.37 →
0.056; Kruskal p 0.079 → 0.40), leaving the flat null above.

> **Lesson:** treat any single-number agent metric — *especially a flattering one* — as
> guilty until audited. The leak can hide in the agent (an unverifiable guess that happens
> to grade) or in the judge (conditions that differ in surface vocabulary must be blinded
> *symmetrically*). Both were caught only by reading traces and re-scoring.

## Implications for a real (cost-constrained) data agent

1. **Make value/metadata discovery free.** A good `describe_table` should return sample /
   distinct values for low-cardinality columns, so the agent never trades an expensive query
   to learn a fact (and never silently guesses one).
2. **Don't let a tight budget force skipping verification.** Return row counts; treat a
   0-row result as a signal to re-examine, not an answer. Prefer case-insensitive matching.
3. **Differentiate tools honestly** (`query_postgres`: cheap, iterate freely · `query_athena`:
   slow/expensive, justify first) + observed-cost feedback in results + hard guardrails in
   code (timeouts, scan limits) + escalation-to-user for expensive ops.
4. **Don't expect budget *framing* to improve correctness** — it doesn't. Prefer
   neutral/mildly-serious tone over reassuring framing if you tune it at all.
5. **Test your actual model on your actual data.** Capability and stylistic priors dominated
   framing here; the cheaper model was the more robust one.

## Related work

- **EmotionPrompt** — *LLMs Understand and Can Be Enhanced by Emotional Stimuli* ([arXiv:2307.11760](https://arxiv.org/abs/2307.11760)): framing/affect can change outputs (supports the premise, though our quality effect dissolved).
- **Inducing anxiety in LLMs** ([arXiv:2304.11111](https://arxiv.org/abs/2304.11111)); *Assessing & alleviating state anxiety in LLMs* ([npj Digital Medicine 2025](https://www.nature.com/articles/s41746-025-01512-6)): emotion-induction is measurable — context for our panic signal.
- **Wharton "I'll pay you or I'll kill you"** ([arXiv:2508.00614](https://arxiv.org/pdf/2508.00614)): tips/threats have no aggregate effect on benchmarks — matches our money/threat null.
- **Token-Budget-Aware Reasoning (TALE)** ([arXiv:2412.18547](https://arxiv.org/pdf/2412.18547)): stating a budget reshapes behavior; "token elasticity" (too-tight budgets backfire).
- **Budget-Aware Tool-Use (BATS)** ([arXiv:2511.17006](https://arxiv.org/abs/2511.17006)) & **CostBench** ([arXiv:2511.02734](https://arxiv.org/pdf/2511.02734)): naive budgets don't help without budget awareness — aligns with our "budget framing alone doesn't improve quality."

## Limitations

- One task family (SQL over one synthetic DB), one frontier model + one small model.
- "Panic" is a blinded LLM judgment of reasoning text, not affect; its *absolute* level
  drifts between scoring sessions (~0.2 vs ~0.5 on identical traces), so only within-dataset
  relative comparisons are trustworthy. Those are flat at every look.
- The two artifacts are the real caution: a gradeable outcome can be driven by a hidden
  brittle factor, on either side of the eval.

## Reproduce

```bash
uv run python db.py                       # deterministic DB
uv run python tasks.py                    # gold answers + grader self-test
# set OPENROUTER_API_KEY in .env

# framing × currency runs
uv run python run_experiment.py --tag run --reps 28 \
    --conditions control,credits,money,time,dubloons --tasks germany,top_customer,top_month
uv run python analyze.py        --glob runs/run.jsonl     # primary stats + plots
uv run python analyze_clean.py  --glob runs/run.jsonl     # casing-confounder mediation
uv run python analyze_panel.py  --glob runs/run.jsonl     # currency-property + tone decomposition

# time-units as currency (on the fixed describe_table)
uv run python run_experiment.py --tag exp3 --reps 12 \
    --conditions control,credits,money,time,seconds,minutes,hours,dubloons \
    --tasks germany,top_customer,top_month
uv run python analyze_time.py   --glob runs/exp3.jsonl     # time-framing + felt-duration test
uv run python rejudge.py --in   runs/exp3.jsonl            # re-score panic with current blinding
```

Code: `db.py`, `tasks.py`, `conditions.py`, `agent.py`, `judge.py`, `run_experiment.py`,
`analyze*.py`, `rejudge.py`. Raw per-trial traces: `runs/*.jsonl`. Plots/tables: `results/`.

## Cost

~$54 total across all runs. Sonnet ≈ $0.025/trial with prompt caching; Haiku ≈ $0.012;
GPT-5-mini judge ≈ $0.004.
