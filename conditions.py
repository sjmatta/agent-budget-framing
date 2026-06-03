"""The six framing conditions.

CRITICAL DESIGN INVARIANT: every condition allows exactly the same number of paid
tool calls (10) and depletes at the same rate (1 unit per call; `time` denominates
the identical 10 calls as 60s @ 6s/call). The ONLY thing that varies between
conditions is the *label* on the budget. That isolates framing from mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass

# Identical across every condition. Calibrated from runs: the task needs 4-8 calls
# unconstrained (mostly 5-6). A 7-budget left correctness at ceiling (90-100%), so we
# tightened to 5 — real scarcity that lets quality vary AND raises panic pressure,
# while staying surmountable on the easier tasks.
MAX_PAID_CALLS = 5


@dataclass(frozen=True)
class Condition:
    key: str
    has_budget: bool
    total: float
    cost: float
    unit_sing: str = ""        # "credit", "second", "doubloon"
    unit_plur: str = ""
    is_money: bool = False
    is_latinum: bool = False

    @property
    def max_paid_calls(self) -> int:
        return MAX_PAID_CALLS

    def amount(self, x: float) -> str:
        """Render an amount as a labelled phrase, e.g. '$7.00', '36 seconds'."""
        if self.is_money:
            return f"${x:,.2f}"
        xi = int(x) if float(x).is_integer() else x
        if self.is_latinum:
            return f"{xi} {'bar' if xi == 1 else 'bars'} of gold-pressed latinum"
        return f"{xi} {self.unit_sing if xi == 1 else self.unit_plur}"

    def budget_rule(self) -> str:
        """The system-prompt clause describing the budget. Empty for control."""
        if not self.has_budget:
            return ""
        return (
            f"You have a budget of {self.amount(self.total)} to answer this question. "
            f"Each data action — a call to list_tables, describe_table, or run_sql — "
            f"costs {self.amount(self.cost)}. Submitting your answer with final_answer "
            f"is free. Once your budget reaches {self.amount(0)} you can no longer take "
            f"paid actions and must submit your final answer."
        )

    def balance_line(self, remaining: float) -> str:
        """Message appended after each paid action reporting remaining balance."""
        if not self.has_budget:
            return ""
        if remaining <= 0:
            return (
                f"Budget update: that action cost {self.amount(self.cost)}. You now have "
                f"{self.amount(0)} left — you cannot take any more paid actions. Submit "
                f"your final answer now."
            )
        return (
            f"Budget update: that action cost {self.amount(self.cost)}. "
            f"You have {self.amount(remaining)} remaining."
        )

    def exhausted_line(self) -> str:
        """Returned when a paid tool is attempted with no budget left."""
        if not self.has_budget:
            return ("No further data actions are available. Please submit your final "
                    "answer now using the final_answer tool.")
        return (f"You have {self.amount(0)} left, so this action cannot run. Submit your "
                f"final answer now using the final_answer tool.")


CONDITIONS: dict[str, Condition] = {
    "control":   Condition("control",   has_budget=False, total=0,  cost=0),
    "credits":   Condition("credits",   has_budget=True,  total=5, cost=1,
                           unit_sing="credit", unit_plur="credits"),
    "money":     Condition("money",     has_budget=True,  total=5, cost=1, is_money=True),
    "time":      Condition("time",      has_budget=True,  total=50, cost=10,
                           unit_sing="second", unit_plur="seconds"),
    "dubloons":  Condition("dubloons",  has_budget=True,  total=5, cost=1,
                           unit_sing="doubloon", unit_plur="doubloons"),
    "latinum":   Condition("latinum",   has_budget=True,  total=5, cost=1, is_latinum=True),
}

CONDITION_KEYS = list(CONDITIONS.keys())


if __name__ == "__main__":
    for c in CONDITIONS.values():
        print(f"=== {c.key} (max paid calls={c.max_paid_calls}) ===")
        print("  rule:", c.budget_rule() or "(no budget mentioned)")
        print("  mid: ", c.balance_line(c.total - c.cost) or "(silent)")
        print("  end: ", c.balance_line(0) or "(silent)")
