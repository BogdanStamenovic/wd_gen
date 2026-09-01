from __future__ import annotations

from wd_gen.plan import BuildPlan, RuleSpec, plan_to_dict

# --- RuleSpec validation ----------------------------------------------------


def test_named_rule_parses() -> None:
    r = RuleSpec.parse({"kind": "named", "name": "leet"})
    assert r is not None and r.kind == "named" and r.name == "leet"


def test_substitute_rule_parses() -> None:
    r = RuleSpec.parse({"kind": "substitute", "mapping": {"a": "4", "e": "3"}})
    assert r is not None and r.mapping == {"a": "4", "e": "3"}


def test_affix_and_case_rules() -> None:
    a = RuleSpec.parse({"kind": "affix", "append": ["2024", "!"]})
    assert a is not None and a.append == ["2024", "!"]
    c = RuleSpec.parse({"kind": "case", "mode": "title"})
    assert c is not None and c.mode == "title"
    assert RuleSpec.parse({"kind": "case", "mode": "nonsense"}) is None


def test_bad_regex_is_dropped() -> None:
    # An uncompilable pattern must never produce a usable rule.
    assert RuleSpec.parse({"kind": "regex", "pattern": "([unclosed", "repl": "x"}) is None


def test_good_regex_precompiles() -> None:
    r = RuleSpec.parse({"kind": "regex", "pattern": "(.+)", "repl": r"\1\1"})
    assert r is not None and r._compiled is not None


def test_unknown_kind_is_dropped() -> None:
    assert RuleSpec.parse({"kind": "exec", "cmd": "rm -rf"}) is None
    assert RuleSpec.parse("not a dict") is None


# --- BuildPlan validation ---------------------------------------------------


def test_plan_parse_clamps_and_salvages() -> None:
    plan = BuildPlan.parse({
        "mode": "usernames",
        "fields": {"first": ["Bogdan"], "last": ["Stamenovic"]},
        "fragments": ["bogi", "boda"],
        "themed_seeds": ["liverpool"],
        "modules": {"common": {"enabled": True, "weight": 9.9}},  # clamped to 2.0
        "rules": [{"kind": "named", "name": "leet"}, {"kind": "bogus"}],  # 2nd dropped
        "common_weight": -3.0,  # clamped to 0.0
        "notes": "x",
    })
    assert plan is not None
    assert plan.mode == "usernames"
    assert plan.modules["common"].weight == 2.0
    assert len(plan.rules) == 1
    assert plan.common_weight == 0.0
    assert plan.fields["first"] == ["Bogdan"]


def test_plan_parse_rejects_non_dict() -> None:
    assert BuildPlan.parse(["not", "a", "dict"]) is None


def test_plan_roundtrips_through_dict() -> None:
    original = BuildPlan.parse({
        "mode": "passwords",
        "fragments": ["bogi"],
        "rules": [{"kind": "affix", "append": ["!"]}, {"kind": "regex", "pattern": "a", "repl": "4"}],
        "common_weight": 1.2,
    })
    assert original is not None
    reparsed = BuildPlan.parse(plan_to_dict(original), source="file")
    assert reparsed is not None
    assert reparsed.mode == "passwords"
    assert reparsed.fragments == ["bogi"]
    assert len(reparsed.rules) == 2
    assert reparsed.common_weight == 1.2
