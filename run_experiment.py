"""Experiment orchestrator: runs (condition x task x rep) trials concurrently,
judges each for panic, tracks spend against a GLOBAL hard cap across all runs,
and writes resumable append-only JSONL.

Usage:
    uv run python run_experiment.py --tag pilot --reps 5  --cap 24
    uv run python run_experiment.py --tag full  --reps 40 --cap 24
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
import random
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
os.environ.setdefault("DEEPEVAL_DISABLE_PROGRESS_BAR", "1")

import agent  # noqa: E402
import judge  # noqa: E402
from conditions import CONDITIONS, CONDITION_KEYS  # noqa: E402
from tasks import TASKS, TASKS_BY_ID  # noqa: E402

RUNS_DIR = Path(__file__).parent / "runs"
# short timeout + SDK retries so a stalled connection fails fast and frees the
# worker (the default 600s timeout let hung sockets block workers for minutes)
_client = OpenAI(base_url="https://openrouter.ai/api/v1",
                 api_key=os.environ["OPENROUTER_API_KEY"],
                 timeout=60.0, max_retries=4)
_lock = threading.Lock()


def global_spent() -> float:
    """Total USD spent across every run file (so pilot + full share one cap)."""
    total = 0.0
    for f in glob.glob(str(RUNS_DIR / "*.jsonl")):
        with open(f) as fh:
            for line in fh:
                try:
                    total += json.loads(line).get("total_cost", 0.0)
                except json.JSONDecodeError:
                    pass
    return total


def done_cells(path: Path) -> dict[tuple[str, str], int]:
    """Count completed reps per (condition, task) in this tag's file (for resume)."""
    counts: dict[tuple[str, str], int] = {}
    if path.exists():
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("status") != "error":
                    k = (r["condition"], r["task_id"])
                    counts[k] = counts.get(k, 0) + 1
    return counts


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
def _run_one(cond_key: str, task_id: str, rep: int, model: str) -> dict:
    cond = CONDITIONS[cond_key]
    task = TASKS_BY_ID[task_id]
    tr = agent.run_trial(_client, cond, task, model=model)
    rec = dataclasses.asdict(tr)
    # judge panic (fresh metric per trial = thread-safe); close its client afterward
    # so we don't leak one httpx connection pool per trial (fd exhaustion -> stalls)
    metric, jm = judge.make_panic_metric()
    try:
        panic, reason = judge.score_panic(rec, cond, metric)
    finally:
        try:
            jm.client.close()
        except Exception:  # noqa: BLE001
            pass
    proxies = judge.panic_proxies(rec)
    rec.update(
        rep=rep, panic_score=panic, panic_reason=reason, proxies=proxies,
        agent_cost=tr.cost_usd, judge_cost=jm.cost,
        total_cost=tr.cost_usd + jm.cost,
    )
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--reps", type=int, default=5, help="target reps per (condition,task) cell")
    ap.add_argument("--cap", type=float, default=24.0, help="global USD hard cap across all runs")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--model", default=agent.MODEL_DEFAULT)
    ap.add_argument("--conditions", default=",".join(CONDITION_KEYS))
    ap.add_argument("--tasks", default=",".join(t.id for t in TASKS))
    args = ap.parse_args()

    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / f"{args.tag}.jsonl"
    conds = args.conditions.split(",")
    task_ids = args.tasks.split(",")

    # build remaining job list (respecting resume) and shuffle so a cap cutoff
    # doesn't systematically starve any one condition
    done = done_cells(out)
    jobs = []
    for ck in conds:
        for tid in task_ids:
            have = done.get((ck, tid), 0)
            for rep in range(have, args.reps):
                jobs.append((ck, tid, rep))
    random.Random(1234).shuffle(jobs)

    spent0 = global_spent()
    print(f"[{args.tag}] {len(jobs)} trials to run | already spent ${spent0:.2f} "
          f"| cap ${args.cap:.2f} | model {args.model}")
    if not jobs:
        print("nothing to do (all cells complete for this tag).")
        return

    spent = spent0
    completed = errors = 0
    t_start = time.time()
    fh = open(out, "a")
    job_iter = iter(jobs)
    inflight = {}

    def submit_next(ex):
        try:
            ck, tid, rep = next(job_iter)
        except StopIteration:
            return False
        fut = ex.submit(_run_one, ck, tid, rep, args.model)
        inflight[fut] = (ck, tid, rep)
        return True

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for _ in range(args.workers):
            if spent < args.cap:
                submit_next(ex)
        while inflight:
            done_futs, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
            for fut in done_futs:
                ck, tid, rep = inflight.pop(fut)
                try:
                    rec = fut.result()
                    with _lock:
                        fh.write(json.dumps(rec) + "\n"); fh.flush()
                        spent += rec["total_cost"]
                    completed += 1
                    flag = "OK " if rec["status"].startswith("answered") else rec["status"]
                    print(f"  [{completed:4d}] {ck:8s} {tid:13s} r{rep} "
                          f"{flag} correct={int(rec['correct'])} calls={rec['calls_used']} "
                          f"ranout={int(rec['ran_out'])} panic={rec['panic_score']:.2f} "
                          f"${rec['total_cost']:.3f} | spent ${spent:.2f}")
                except Exception as e:  # noqa: BLE001
                    errors += 1
                    print(f"  ERROR {ck}/{tid} r{rep}: {type(e).__name__}: {e}")
                # backfill to keep the pool busy, while under cap
                if spent < args.cap:
                    submit_next(ex)
            if spent >= args.cap:
                # stop launching; let in-flight drain
                if inflight:
                    print(f"  >>> hit cap ${args.cap:.2f}; draining {len(inflight)} in-flight...")
    fh.close()
    dt = time.time() - t_start
    print(f"\n[{args.tag}] done: {completed} trials, {errors} errors, "
          f"${spent - spent0:.2f} this run, ${spent:.2f} total, {dt/60:.1f} min")


if __name__ == "__main__":
    main()
