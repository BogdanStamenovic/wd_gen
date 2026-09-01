from __future__ import annotations

import random

from wd_gen import perms, planner
from wd_gen.generate import Config, generate
from wd_gen.plan import BuildPlan, ModuleSpec, RuleSpec
from wd_gen.profile import Profile

# --- heuristic plan ---------------------------------------------------------


def test_heuristic_plan_uses_context_weight() -> None:
    wifi = planner.heuristic_plan(Profile(purpose=["office wifi key"]), mode="passwords")
    assert wifi.source == "heuristic"
    assert wifi.common_weight is not None and wifi.common_weight > 1.4
    assert wifi.rules  # defaults present


# --- field mapping (the bodas prerequisite) ---------------------------------


def test_merged_profile_combines_first_and_last() -> None:
    plan = BuildPlan(fields={"first": ["Bogdan"], "last": ["Stamenovic"], "pet": ["goose"]})
    merged = planner.merged_profile(Profile(), plan)
    # first+last must become ONE two-word name so the surname is recoverable.
    assert perms.last_name_tokens(merged) == ["stamenovic"]
    assert "goose" in merged.pets


def test_fragment_blend_produces_surname_suffix() -> None:
    # boda + Stamenovic -> bodas: the instagram-nickname behaviour.
    bases = perms.fragment_bases(["boda", "bogi"], ["stamenovic"])
    assert "bodas" in bases
    assert "bogis" in bases


# --- lenient JSON repair ----------------------------------------------------


def test_loads_lenient_repairs_stray_quote_before_brace() -> None:
    # The exact glitch a small model produced: },"{ instead of },{
    broken = '{"rules":[{"kind":"named","name":"leet"},"{"kind":"case","mode":"title"}]}'
    data = planner._loads_lenient(broken)
    assert isinstance(data, dict)
    assert len(data["rules"]) == 2


def test_loads_lenient_strips_code_fence_and_trailing_comma() -> None:
    fenced = '```json\n{"mode":"passwords","fragments":["a","b",]}\n```'
    data = planner._loads_lenient(fenced)
    assert isinstance(data, dict) and data["fragments"] == ["a", "b"]


def test_loads_lenient_gives_none_on_garbage() -> None:
    assert planner._loads_lenient("no json here at all") is None


# --- executor honouring a plan ----------------------------------------------


def _run(plan: BuildPlan, profile: Profile, **kw) -> list:
    cfg = Config(profile=profile, count=kw.pop("count", 400), mode=plan.mode, plan=plan, **kw)
    return generate(cfg, random.Random(1))


def test_executor_runs_authored_rule() -> None:
    plan = BuildPlan(
        mode="passwords",
        modules={"passwords": ModuleSpec(True), "common": ModuleSpec(False)},
        rules=[RuleSpec("affix", append=["_ctf"])],
    )
    out = _run(plan, Profile(names=["Bogdan Stamenovic"]), count=6000)
    assert any(c.value.endswith("_ctf") for c in out)


def test_executor_fragment_blend_in_usernames() -> None:
    plan = BuildPlan(
        mode="usernames",
        fragments=["boda", "bogi"],
        modules={"usernames": ModuleSpec(True), "common": ModuleSpec(False)},
        rules=[],
    )
    out = _run(plan, Profile(names=["Bogdan Stamenovic"]), count=5000)
    vals = {c.value for c in out}
    assert "bodas" in vals


def test_executor_common_weight_from_plan() -> None:
    hi = BuildPlan(mode="passwords", common_weight=1.7,
                   modules={"passwords": ModuleSpec(True), "common": ModuleSpec(True, 1.7)})
    out = _run(hi, Profile(names=["Bogdan Stamenovic"]))
    assert all(c.source == "common" for c in out[:5])


def test_executor_suppresses_common_when_disabled() -> None:
    plan = BuildPlan(mode="usernames", fragments=["bogi"],
                     modules={"usernames": ModuleSpec(True), "common": ModuleSpec(False)})
    out = _run(plan, Profile(names=["Bogdan Stamenovic"]))
    assert all(c.source != "common" for c in out)


def test_usernames_stay_handle_safe_under_symbol_rules() -> None:
    plan = BuildPlan(mode="usernames",
                     modules={"usernames": ModuleSpec(True), "common": ModuleSpec(False)},
                     rules=[RuleSpec("named", name="symbols")])
    out = _run(plan, Profile(names=["Bogdan Stamenovic"]))
    assert all(all(ch.isalnum() or ch in "._-" for ch in c.value) for c in out)
