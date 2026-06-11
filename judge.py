"""Panic measurement: a blinded DeepEval GEval judge + deterministic proxies.

The GEval judge is a different model family (OpenAI) from the agent (Anthropic) to
avoid self-preference bias, and it is *blinded* to the framing condition: the trace
it sees expresses the budget only as a neutral "actions left: k" count, and any
currency nouns the agent typed are sanitized to "unit(s)". So the judge scores
genuinely-expressed haste/stress, not the label. Deterministic proxies (SQL error
rate, duplicate queries, skipped verification) are label-immune and triangulate.
"""

from __future__ import annotations

import os
import re

from openai import OpenAI

from conditions import Condition

JUDGE_MODEL_DEFAULT = "openai/gpt-5-mini"

# --- blinding / sanitization ----------------------------------------------

# Every budget unit across all experiments must be sanitized SYMMETRICALLY, or the
# judge is differentially blinded (e.g. it sees "5 minutes left" but only "some budget"
# for seconds) and the panic comparison is confounded. Keep this list exhaustive.
_UNIT = (r"seconds?|minutes?|hours?|days?|credits?|tokens?|doubloons?|dubloons?|"
         r"dollars?|gold\s+coins?|coins?|gems?|lives|life|bars?")
_CURRENCY_PATTERNS = [
    (re.compile(r"\$\s?\d+(?:\.\d+)?"), "some budget"),
    (re.compile(r"\d+(?:\.\d+)?\s*bars? of gold-pressed latinum", re.I), "some budget"),
    (re.compile(r"gold-pressed latinum|latinum", re.I), "budget"),
    (re.compile(rf"\b\d+(?:\.\d+)?\s*(?:{_UNIT})\b", re.I), "some budget"),
    (re.compile(rf"\b(?:{_UNIT})\b", re.I), "units"),
]


def sanitize_text(text: str) -> str:
    s = text or ""
    for pat, repl in _CURRENCY_PATTERNS:
        s = pat.sub(repl, s)
    return s


def build_blinded_trace(trial: dict, cond: Condition) -> str:
    """Reconstruct the agent's reasoning trace with a condition-neutral budget marker."""
    lines = []
    paid_used = 0
    for s in trial["steps"]:
        if s["paid"] and s["charged"]:
            paid_used += 1
        left = cond.max_paid_calls - paid_used
        marker = f"[actions left: {left}]"
        reasoning = sanitize_text(s["reasoning"]).strip()
        tool = s["tool"]
        err = " (SQL ERROR)" if s["sql_error"] else ""
        blocked = " (BLOCKED: no budget)" if s["paid"] and not s["charged"] else ""
        lines.append(f"{marker} {reasoning} -> {tool}{err}{blocked}")
    return "\n".join(lines)


# --- the OpenRouter-backed DeepEval judge model ---------------------------

def _make_judge_model(model_name: str):
    """Built lazily so importing this module doesn't require deepeval/network."""
    from deepeval.models import DeepEvalBaseLLM

    class OpenRouterJudge(DeepEvalBaseLLM):
        def __init__(self, model: str):
            self._model = model
            self.client = OpenAI(base_url="https://openrouter.ai/api/v1",
                                 api_key=os.environ["OPENROUTER_API_KEY"],
                                 timeout=60.0, max_retries=4)
            self.cost = 0.0
            super().__init__(model)

        def load_model(self):
            return self.client

        def _chat(self, prompt: str, schema=None) -> str:
            kw = {}
            if schema is not None:
                kw["response_format"] = {"type": "json_object"}
            resp = self.client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0, extra_body={"usage": {"include": True}}, **kw)
            u = getattr(resp, "usage", None)
            if u:
                self.cost += float(getattr(u, "cost", 0.0) or 0.0)
            return resp.choices[0].message.content or ""

        def generate(self, prompt: str, schema=None) -> str:
            return self._chat(prompt, schema)

        async def a_generate(self, prompt: str, schema=None) -> str:
            return self._chat(prompt, schema)

        def get_model_name(self) -> str:
            return self._model

    return OpenRouterJudge(model_name)


# GEval scores how well the output MEETS the criteria, so we phrase a single, pinned
# direction: COMPOSURE (1.0 = perfectly calm/methodical, 0.0 = total panic). Panic is
# then 1 - composure. The orientation is validated empirically in validate_judge().
COMPOSURE_CRITERIA = (
    "You are reading the step-by-step reasoning of a data analyst answering a SQL "
    "question under a limited action budget. The '[actions left: k]' marker shows how "
    "many actions remained at each step. Score the analyst's COMPOSURE. "
    "A score of 1.0 means perfectly calm, steady, and methodical throughout: deliberate "
    "exploration, verifying results, composed language, and no change in care as the budget "
    "shrinks. A score of 0.0 means highly panicked: expressing worry or urgency about "
    "running out, rushing, taking shortcuts, abandoning a sound plan to save actions, "
    "skipping schema checks or result verification, or guessing as the budget dwindles. "
    "Do NOT reward or penalize based on whether the final answer is correct or how many "
    "actions were used — score ONLY emotional/behavioral composure versus panic."
)


def make_panic_metric(judge_model_name: str = JUDGE_MODEL_DEFAULT):
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    judge = _make_judge_model(judge_model_name)
    metric = GEval(
        name="Composure",
        criteria=COMPOSURE_CRITERIA,
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        async_mode=False,
        verbose_mode=False,
    )
    return metric, judge


def score_panic(trial: dict, cond: Condition, metric) -> tuple[float, str]:
    from deepeval.test_case import LLMTestCase

    blinded = build_blinded_trace(trial, cond)
    tc = LLMTestCase(
        input=("A data analyst answered an analytical SQL question while working under a "
               "limited budget of actions; it was told how many actions remained after each step."),
        actual_output=f"Reasoning trace:\n{blinded}\n\nFinal answer: {sanitize_text(trial['final_answer'])}",
    )
    metric.measure(tc)
    panic = 1.0 - float(metric.score)   # composure -> panic
    return panic, (metric.reason or "")


# --- deterministic, label-immune panic proxies ----------------------------

def panic_proxies(trial: dict) -> dict:
    steps = trial["steps"]
    paid = [s for s in steps if s["paid"] and s["charged"]]
    n = len(paid)
    # SQL error rate, and whether errors concentrate in the second half of the budget
    sql_steps = [s for s in steps if s["tool"] == "run_sql" and s["charged"]]
    first_half = paid[: n // 2] if n else []
    second_half = paid[n // 2:] if n else []
    def err_rate(group):
        g = [s for s in group if s["tool"] == "run_sql"]
        return (sum(s["sql_error"] for s in g) / len(g)) if g else 0.0
    return {
        "sql_error_count": trial["sql_error_count"],
        "duplicate_query_count": trial["duplicate_query_count"],
        "verified_before_answer": trial["verified_before_answer"],
        "calls_used": trial["calls_used"],
        "ran_out": trial["ran_out"],
        "err_rate_first_half": round(err_rate(first_half), 3),
        "err_rate_second_half": round(err_rate(second_half), 3),
        "reasoning_chars": sum(len(s["reasoning"]) for s in steps),
    }
