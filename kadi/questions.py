"""Decision schemas. Every answer Kadı returns is one of the declared options."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MODES = ("live", "shadow")
_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class Question:
    """A decision Kadı can take.

    mode:        "live"   - local answers are returned when the guarantee allows.
                 "shadow" - the oracle always answers; Kadı only records what it
                            *would* have said. Use this to prove value risk-free.
    conditional: Mondrian (per-label) conformal. The error bound then holds for
                 every label separately, not just on average. Slower to warm up.
    novelty_threshold: share of an input's feature mass never seen in training
                 above which Kadı refuses to answer locally (OOD / adversarial guard).
    """
    name: str
    options: tuple[str, ...]
    instructions: str = ""
    target_error: float = 0.05
    mode: str = "live"
    conditional: bool = False
    novelty_threshold: float = 0.8
    meta: dict = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self):
        if not _NAME.match(self.name):
            raise ValueError("question name must match [A-Za-z0-9_.:-]{1,64}")
        if len(self.options) < 2:
            raise ValueError("a question needs at least two options")
        if len(set(self.options)) != len(self.options):
            raise ValueError("options must be unique")
        if not 0 < self.target_error < 1:
            raise ValueError("target_error must be in (0, 1)")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if not 0 < self.novelty_threshold <= 1:
            raise ValueError("novelty_threshold must be in (0, 1]")

    def index(self, label: str) -> int:
        return self.options.index(label)


def Choice(name: str, options, instructions: str = "", target_error: float = 0.05, **kw) -> Question:
    return Question(name, tuple(options), instructions, target_error, meta={"kind": "choice"}, **kw)


def Binary(name: str, question: str, target_error: float = 0.05,
           yes: str = "yes", no: str = "no", **kw) -> Question:
    return Question(name, (yes, no), question, target_error, meta={"kind": "binary"}, **kw)


def Score(name: str, low: int = 1, high: int = 5, instructions: str = "",
          target_error: float = 0.1, **kw) -> Question:
    opts = tuple(str(i) for i in range(low, high + 1))
    return Question(name, opts, instructions, target_error,
                    meta={"kind": "score", "low": low, "high": high}, **kw)
