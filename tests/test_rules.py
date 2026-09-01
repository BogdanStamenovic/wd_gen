from __future__ import annotations

import random

from wd_gen import rules
from wd_gen.plan import RuleSpec


def _apply(word: str, spec: RuleSpec) -> set[str]:
    return set(rules.apply_rule(word, spec, random.Random(0)))


def test_named_rule_runs_builtin() -> None:
    out = _apply("bogdan", RuleSpec("named", name="capitalize"))
    assert "Bogdan" in out


def test_substitute_rule() -> None:
    out = _apply("bogdan", RuleSpec("substitute", mapping={"o": "0", "a": "4"}))
    assert "b0gd4n" in out


def test_affix_rule() -> None:
    out = _apply("bogdan", RuleSpec("affix", prepend=["#"], append=["2024"]))
    assert "bogdan2024" in out
    assert "#bogdan" in out


def test_case_rules() -> None:
    assert _apply("bogdan", RuleSpec("case", mode="upper")) == {"BOGDAN"}
    assert _apply("bogdan", RuleSpec("case", mode="reverse")) == {"nadgob"}


def test_authored_regex_rule() -> None:
    spec = RuleSpec.parse({"kind": "regex", "pattern": r"(.+)", "repl": r"\1_\1"})
    assert spec is not None
    assert "bogdan_bogdan" in _apply("bogdan", spec)


def test_regex_with_bad_backref_does_not_raise() -> None:
    # \9 has no group; sub raises internally and must be swallowed to nothing.
    spec = RuleSpec.parse({"kind": "regex", "pattern": r"(.)", "repl": r"\9"})
    assert spec is not None
    assert _apply("bogdan", spec) == set()  # no crash, no output


def test_overlong_token_is_skipped() -> None:
    huge = "a" * 200
    assert _apply(huge, RuleSpec("case", mode="upper")) == set()


def test_apply_rules_dedups_across_specs() -> None:
    specs = [RuleSpec("case", mode="upper"), RuleSpec("case", mode="upper")]
    out = list(rules.apply_rules("bogdan", specs, random.Random(0)))
    assert out == ["BOGDAN"]


def test_default_rules_are_named_and_safe() -> None:
    defaults = rules.default_rules()
    assert defaults
    assert all(r.kind == "named" and r.name in rules.BUILTIN for r in defaults)
