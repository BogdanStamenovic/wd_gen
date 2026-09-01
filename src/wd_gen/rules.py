"""Rule interpreter: run named built-in rules *and* rules the model authored.

The planner decides which mangling rules a run uses. It can pick from the named
built-ins (the hashcat-flavoured set in :mod:`mangle`) and it can invent new ones
inline as :class:`~wd_gen.plan.RuleSpec` data. This module executes both against a
single word, safely: authored regex is pre-compiled at parse time, every
application is wrapped, and rules only ever touch short tokens — so a hostile or
confused rule can neither crash the run nor hang it.

Nothing here is a security boundary against a malicious *operator* (it's their
tool); it is a robustness boundary against a small model emitting junk.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterator, Sequence

from . import mangle
from .plan import MAX_TOKEN_LEN, RuleSpec

# The named rules the model can select by name. Reuses the mangle registry so the
# built-in set stays in one place.
BUILTIN = mangle.RULES

# What the planner gets if it doesn't specify a rule set — the same sensible
# default breadth as --chaos, minus the meme/bro flavour that doesn't suit
# realistic OSINT output.
DEFAULT_RULE_NAMES: tuple[str, ...] = ("identity", "capitalize", "leet", "numbers", "symbols")


def builtin_names() -> list[str]:
    return list(BUILTIN)


def apply_rule(word: str, spec: RuleSpec, rng: random.Random) -> Iterator[str]:
    """Yield every variant one rule produces for ``word``. Never raises."""
    if not word or len(word) > MAX_TOKEN_LEN:
        return

    if spec.kind == "named":
        fn = BUILTIN.get(spec.name)
        if fn is not None:
            yield from fn(word, rng)
        return

    if spec.kind == "substitute":
        out = "".join(spec.mapping.get(ch, ch) for ch in word)
        if out != word:
            yield out
        # also a lowercase-keyed pass, since models often give lowercase maps
        low = "".join(spec.mapping.get(ch.lower(), ch) for ch in word)
        if low != word and low != out:
            yield low
        return

    if spec.kind == "affix":
        for pre in spec.prepend:
            yield pre + word
        for app in spec.append:
            yield word + app
        return

    if spec.kind == "case":
        variant = _apply_case(word, spec.mode)
        if variant and variant != word:
            yield variant
        return

    if spec.kind == "regex" and spec._compiled is not None:
        try:
            out = spec._compiled.sub(spec.repl, word)
        except (re.error, IndexError):  # bad backreference in repl, etc.
            return
        if out and out != word and len(out) <= MAX_TOKEN_LEN:
            yield out


def apply_rules(word: str, specs: Sequence[RuleSpec], rng: random.Random) -> Iterator[str]:
    """Apply every rule to ``word``, yielding all produced variants (deduped)."""
    seen: set[str] = set()
    for spec in specs:
        for variant in apply_rule(word, spec, rng):
            if variant not in seen:
                seen.add(variant)
                yield variant


def _apply_case(word: str, mode: str) -> str:
    if mode == "lower":
        return word.lower()
    if mode == "upper":
        return word.upper()
    if mode in ("title", "capitalize"):
        return word.capitalize()
    if mode == "reverse":
        return word[::-1]
    if mode == "toggle":
        return "".join(c.lower() if c.isupper() else c.upper() for c in word)
    return word


def default_rules() -> list[RuleSpec]:
    """The RuleSpec list a plan uses when the planner selects nothing."""
    return [RuleSpec("named", name=n, label=n) for n in DEFAULT_RULE_NAMES]
